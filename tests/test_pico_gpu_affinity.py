from contextlib import redirect_stdout
import io
from pathlib import Path
import importlib.util
import os
import signal
import tempfile
import unittest
from unittest.mock import patch

B = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("candidate", B / "pico-gpu-events.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class AffinityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.q = self.root / "queue"
        self.q.mkdir()
        self.cpu = self.root / "cpu"
        self.cpu.mkdir()
        self.boot = self.root / "boot"
        self.boot.write_text("boot")
        self.globalmask = self.root / "global"
        self.globalmask.write_text("ff")
        for name in ["online", "possible"]:
            (self.cpu / name).write_text("0-7")
        for i in range(8):
            values = {
                "regs/identification/midr_el1": hex(
                    0x51DF805E if i < 4 else 0x411FD0D0
                ),
                "cpu_capacity": str(351 if i < 4 else 871 if i < 7 else 1024),
                "cpufreq/cpuinfo_max_freq": str(
                    1804800 if i < 4 else 2419200 if i < 7 else 2841600
                ),
            }
            for name, value in values.items():
                f = self.cpu / f"cpu{i}" / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(value)
        self.before = {"nice": "0", "cpumask": "ff", "max_active": "256", "numa": "1"}
        for name, value in self.before.items():
            (self.q / name).write_text(value)
        (self.q / "pool_ids").write_text("0:17")
        original = os.fstat

        def rootstat(fd):
            values = list(original(fd))
            values[4] = 0
            return os.stat_result(values)

        self.patches = [
            patch.object(p, "QUEUE", self.q),
            patch.object(p, "LOCK", self.root / "lock"),
            patch.object(p, "CPU", self.cpu),
            patch.object(p, "BOOT", self.boot),
            patch.object(p, "GLOBAL_MASK", self.globalmask),
            patch.object(p, "validate_device"),
            patch.object(p.os, "fstat", side_effect=rootstat),
        ]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in reversed(self.patches):
            x.stop()
        self.tmp.cleanup()

    def context(self, mask="f0"):
        return p.prioritize_events("serial", "boot", mask)

    def restored(self):
        self.assertEqual(p.snapshot(), self.before)

    def test_no_option_matches_original_and_does_not_require_topology(self):
        self.boot.write_text("wrong")
        with self.context(None) as r:
            self.assertEqual(p.snapshot(), self.before | {"nice": "-20"})
            self.assertNotIn("generation", r)
        self.restored()

    def test_valid_only_two_attrs_and_pool_turnover(self):
        with self.context() as r:
            self.assertEqual(
                p.snapshot(), self.before | {"nice": "-20", "cpumask": "f0"}
            )
            (self.q / "pool_ids").write_text("0:23")
        self.restored()
        self.assertEqual(r["after_pool"]["pool_ids"], [23])
        self.assertEqual(
            [x["attribute"] for x in r["restorations"]], ["cpumask", "nice"]
        )

    def test_invalid_masks_before_mutation(self):
        for mask in ["", "0", "0f", "ff", "f0\n", "100"]:
            with self.assertRaises(ValueError):
                with self.context(mask):
                    self.fail()
            self.restored()

    def test_disjoint_or_partial_global_before_mutation(self):
        for mask in ["0", "0f", "70"]:
            self.globalmask.write_text(mask)
            with self.assertRaises(ValueError):
                with self.context():
                    self.fail()
            self.restored()

    def test_offline_cpu_before_mutation(self):
        (self.cpu / "online").write_text("0-6")
        with self.assertRaises(ValueError):
            with self.context():
                self.fail()
        self.restored()

    def test_identity_capacity_frequency_mismatch(self):
        for rel in [
            "cpu0/regs/identification/midr_el1",
            "cpu7/cpu_capacity",
            "cpu4/cpufreq/cpuinfo_max_freq",
        ]:
            path = self.cpu / rel
            old = path.read_text()
            path.write_text("1")
            with self.assertRaises(ValueError):
                with self.context():
                    self.fail()
            self.restored()
            path.write_text(old)

    def test_workload_exception_restores_receipt(self):
        with self.assertRaisesRegex(RuntimeError, "workload") as got:
            with self.context():
                raise RuntimeError("workload")
        self.restored()
        self.assertEqual(got.exception.receipt["restoration_errors"], [])

    def test_partial_write_failure_restores_both(self):
        write = Path.write_text

        def faulty(path, text, *a, **kw):
            result = write(path, text, *a, **kw)
            if path == self.q / "cpumask" and text == "f0\n":
                raise OSError("partial write")
            return result

        with patch.object(Path, "write_text", faulty), self.assertRaises(OSError):
            with self.context():
                self.fail()
        self.restored()

    def test_readback_failure_restores_both(self):
        snap = p.snapshot
        count = 0

        def faulty():
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("active read")
            return snap()

        with (
            patch.object(p, "snapshot", side_effect=faulty),
            self.assertRaises(OSError),
        ):
            with self.context():
                self.fail()
        self.restored()

    def test_nested_owner_cannot_restore_outer(self):
        with self.context():
            with self.assertRaises(BlockingIOError):
                with self.context():
                    self.fail()
            self.assertEqual(p.snapshot()["cpumask"], "f0")
        self.restored()

    def test_failed_mask_restore_still_restores_nice(self):
        write = Path.write_text

        def faulty(path, text, *a, **kw):
            if path == self.q / "cpumask" and text == "ff\n":
                raise OSError("restore failed")
            return write(path, text, *a, **kw)

        with (
            patch.object(Path, "write_text", faulty),
            self.assertRaises(p.AffinityPolicyError) as got,
        ):
            with self.context():
                pass
        self.assertEqual(p.snapshot()["nice"], "0")
        self.assertEqual(len(got.exception.receipt["restorations"]), 2)
        self.assertTrue(got.exception.receipt["restoration_errors"])

    def test_unrelated_drift_not_overwritten(self):
        with self.assertRaises(p.AffinityPolicyError):
            with self.context():
                (self.q / "numa").write_text("0")
        self.assertEqual(p.snapshot(), self.before | {"numa": "0"})

    def test_boot_change_refuses_replacement_writes(self):
        with self.assertRaises(p.AffinityPolicyError) as got:
            with self.context():
                self.boot.write_text("newboot")
        self.assertEqual(len(got.exception.receipt["restorations"]), 2)
        self.assertTrue(
            all("error" in r for r in got.exception.receipt["restorations"])
        )

    def test_actual_sigint_unwind_restores(self):
        old = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            with self.assertRaises(KeyboardInterrupt):
                with self.context():
                    os.kill(os.getpid(), signal.SIGINT)
            self.restored()
        finally:
            signal.signal(signal.SIGINT, old)

    def test_main_sigterm_stop_restores(self):
        def stop_sleep(_):
            os.kill(os.getpid(), signal.SIGTERM)

        output = io.StringIO()
        with (
            patch(
                "sys.argv",
                [
                    "candidate",
                    "--boot-serial",
                    "serial",
                    "--boot-id",
                    "boot",
                    "--seconds",
                    "1",
                    "--cpu-mask",
                    "f0",
                ],
            ),
            patch.object(p.time, "sleep", side_effect=stop_sleep),
            redirect_stdout(output),
        ):
            p.main()
        self.restored()
        self.assertIn("PICO_GPU_EVENTS_READY ", output.getvalue())
        self.assertIn("PICO_GPU_EVENTS_RESTORED ", output.getvalue())

    def test_each_mutation_records_intermediate_pool(self):
        write = Path.write_text

        def mutate(path, text, *args, **kwargs):
            result = write(path, text, *args, **kwargs)
            if path == self.q / "nice" and text == "-20\n":
                write(self.q / "pool_ids", "0:17")
            if path == self.q / "cpumask" and text == "f0\n":
                write(self.q / "pool_ids", "0:23")
            return result

        with patch.object(Path, "write_text", mutate):
            with self.context() as r:
                self.assertEqual(
                    [x["pool_snapshot"]["pool_ids"] for x in r["mutations"]],
                    [[17], [23]],
                )
                self.assertEqual(p.transition_pool_ids(r), [17, 23])
                self.assertTrue(
                    all(x["pool_snapshot_ns"] >= x["after_ns"] for x in r["mutations"])
                )

    def test_preflight_requires_original_queue_mask_and_nice(self):
        for name, value in [("nice", "-20"), ("cpumask", "f0")]:
            (self.q / name).write_text(value)
            with self.assertRaises(ValueError):
                with self.context():
                    self.fail()
            self.assertEqual((self.q / name).read_text(), value)
            (self.q / name).write_text(self.before[name])


if __name__ == "__main__":
    unittest.main()
