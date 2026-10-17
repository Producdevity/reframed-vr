import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("cpu_timer_race", ROOT / "tools/test-cpu-timer-race.py")
race = importlib.util.module_from_spec(spec)
spec.loader.exec_module(race)

COMPLETE_LOG = (
    "RACE_INIT pid=1\n"
    "SWEEP_END label=hammer seconds=20.0 warns=0 oops=0\n"
    "SWEEP_END label=dhammer seconds=320.0 warns=0 oops=0\n"
    "RACE_RESULT warn_seen=0\n"
    "[ 340.0] reboot: Power down\n"
)
SPLATS = (
    "EXEC_LAT iter=544[ 68.628629] WARNING: CPU: 2 PID: 1 at "
    "kernel/time/posix-cpu-timers.c:437 posix_cpu_timer_del+0xe8/0x104\n"
    "[ 172.556449] Unable to handle kernel paging request at virtual address 006445bea5e17963\n"
    "[ 172.560926] Internal error: Oops: 96000004 [#1] PREEMPT SMP\n"
)


class KernelLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A native C compiler is required for the kernel-log parser test")
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        source = (ROOT / "tests/quest-cpu-timer/race.c").read_text()
        scanner = source[source.index("struct klog_watch {"):
                         source.index("static volatile sig_atomic_t g_alarm_fired;")]
        harness = directory / "klog.c"
        harness.write_text(
            '#include <stdio.h>\n#include <string.h>\n'
            'static const char *fixture;\n'
            'static void emit(const char *format, ...) { (void)format; }\n'
            'static int klogctl(int type, char *buf, int len) {\n'
            '    (void)type;\n'
            '    return snprintf(buf, (size_t)len, "%s", fixture);\n'
            '}\n' + scanner + '\n'
            'int main(int argc, char **argv) {\n'
            '    if (argc != 2) return 2;\n'
            '    fixture = argv[1];\n'
            '    struct klog_watch watch = {0, 0};\n'
            '    klog_scan(&watch);\n'
            '    klog_scan(&watch);\n'
            '    if (g_warn_seen != (watch.warns > 0)) return 3;\n'
            '    printf("%d %d\\n", watch.warns, watch.oops);\n'
            '    return 0;\n'
            '}\n')
        cls.binary = directory / "klog"
        subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                        str(harness), "-o", str(cls.binary)], check=True, capture_output=True)

    def test_syslog_prefixes_and_repeated_snapshots(self):
        for prefix in ("", "<4>", "[   68.628629] ", "<4>[   68.628629] ",
                       "<4>[   68.628629][    T1] "):
            with self.subTest(prefix=prefix):
                fixture = "\n".join(prefix + message for message in (
                    "WARNING: CPU: 2 at posix_cpu_timer_del+0xe8/0x104",
                    "Unable to handle kernel paging request",
                    "Internal error: Oops: 96000004",
                    "BUG: failure",
                )) + "\n"
                result = subprocess.run([str(self.binary), fixture], check=True,
                                        text=True, capture_output=True)
                self.assertEqual(result.stdout, "1 3\n")

    def test_unrelated_messages_do_not_count(self):
        fixture = (
            "<4>[ 1.0] WARNING: CPU: 2 at timerqueue_del\n"
            "<6>[ 2.0] info: posix_cpu_timer_del WARNING: diagnostic text\n"
            "<6>[ 3.0] info: Internal error: diagnostic text\n"
            "<4>[truncated\n"
        )
        result = subprocess.run([str(self.binary), fixture], check=True,
                                text=True, capture_output=True)
        self.assertEqual(result.stdout, "0 0\n")


class RaceRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)

    def run_log(self, text, waits=(0,)):
        process = mock.Mock()
        process.wait.side_effect = waits

        def launch(command, *, stdin, stdout, stderr):
            stdout.write(text.encode())
            return process

        with mock.patch.object(race.subprocess, "Popen", side_effect=launch):
            report = race.run_boot("qemu", "hvf", self.output, self.output / "initrd",
                                   self.output, "boot1", 1)
        saved = json.loads((self.output / "boot1/result.json").read_text())
        self.assertEqual(report, saved)
        return report, process

    def test_complete_run_without_a_warning_is_valid(self):
        report, _ = self.run_log(COMPLETE_LOG)
        self.assertEqual(report["status"], "guest_completed")
        self.assertFalse(report["warn_observed"])
        self.assertFalse(report["oops_observed"])

    def test_serial_splats_are_observed_without_guest_detection_markers(self):
        report, _ = self.run_log(SPLATS + COMPLETE_LOG)
        self.assertEqual(report["status"], "guest_completed")
        self.assertTrue(report["warn_observed"])
        self.assertTrue(report["oops_observed"])
        self.assertFalse(report["markers"]["warn_first"])
        self.assertFalse(report["markers"]["oops_first"])

    def test_guest_detection_markers_are_still_observed(self):
        report, _ = self.run_log("WARN_FIRST iter=1\nOOPS_FIRST iter=1\n" + COMPLETE_LOG)
        self.assertTrue(report["warn_observed"])
        self.assertTrue(report["oops_observed"])

    def test_timeout_keeps_splats_and_reaps_the_process(self):
        report, process = self.run_log("RACE_INIT pid=1\n" + SPLATS,
                                       (subprocess.TimeoutExpired("qemu", 1), -15))
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["timed_out"])
        self.assertEqual(report["returncode"], -15)
        self.assertTrue(report["warn_observed"])
        self.assertTrue(report["oops_observed"])
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_timeout_escalates_to_kill_and_keeps_splats(self):
        report, process = self.run_log(SPLATS, (subprocess.TimeoutExpired("qemu", 1),
                                               subprocess.TimeoutExpired("qemu", 5), -9))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["returncode"], -9)
        self.assertTrue(report["warn_observed"])
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_nonzero_exit_fails_even_with_completion_markers(self):
        report, _ = self.run_log(COMPLETE_LOG, (1,))
        self.assertEqual(report["status"], "failed")
        self.assertIn("QEMU exited with code 1", report["error"])

    def test_completion_requires_every_guest_marker(self):
        for index, line in enumerate(COMPLETE_LOG.splitlines(keepends=True)):
            with self.subTest(line=line):
                directory = self.output / str(index)
                directory.mkdir()
                original = self.output
                self.output = directory
                try:
                    report, _ = self.run_log(COMPLETE_LOG.replace(line, ""))
                finally:
                    self.output = original
                self.assertEqual(report["status"], "failed")
                self.assertIn("Missing guest markers", report["error"])

    def test_missing_qemu_is_a_persisted_failed_boot(self):
        with mock.patch.object(race.subprocess, "Popen", side_effect=FileNotFoundError("qemu")):
            report = race.run_boot("qemu", "hvf", self.output, self.output / "initrd",
                                   self.output, "boot1", 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["markers"]["race_init"], 0)
        self.assertEqual(json.loads((self.output / "boot1/result.json").read_text()), report)

    def test_main_retains_failed_boots_and_continues(self):
        for label, first_waits in (
            ("startup-error", (1,)),
            ("timeout", (subprocess.TimeoutExpired("qemu", 1), -15)),
            ("success", (0,)),
        ):
            with self.subTest(case=label):
                output = self.output / label
                processes = [mock.Mock(), mock.Mock()]
                processes[0].wait.side_effect = first_waits
                processes[1].wait.return_value = 0
                pending = iter(zip(processes, (SPLATS + COMPLETE_LOG, COMPLETE_LOG)))

                def launch(command, *, stdin, stdout, stderr):
                    process, text = next(pending)
                    stdout.write(text.encode())
                    return process

                with mock.patch("sys.argv", [str(race.__file__), "--output", str(output)]), \
                     mock.patch.object(race, "check_kernel", return_value=({"commit": race.KERNEL_COMMIT}, "sha256")), \
                     mock.patch.object(race, "digest", return_value="sha256"), \
                     mock.patch.object(race, "build_probe", return_value=output / "race-init"), \
                     mock.patch.object(race, "build_initramfs", return_value=output / "initrd"), \
                     mock.patch.object(race.subprocess, "Popen", side_effect=launch), \
                     contextlib.redirect_stdout(io.StringIO()):
                    code = race.main()
                report = json.loads((output / "result.json").read_text())
                self.assertEqual(code, 0 if label == "success" else 1)
                self.assertEqual(report["status"], "completed" if label == "success" else "failed")
                self.assertEqual(len(report["boots"]), 2)
                self.assertEqual(report["boots"][1]["status"], "guest_completed")
                self.assertTrue(report["warn_observed"])
                self.assertTrue(report["oops_observed"])


if __name__ == "__main__":
    unittest.main()
