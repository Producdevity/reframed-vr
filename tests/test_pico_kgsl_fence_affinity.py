from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

R = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location(
    "affinity", R / "pico-kgsl-fence-affinity.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AffinityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "affinity.json"
        self.enabled = True
        self.ticks = 22
        self.mask = set(range(8))
        self.writes = []
        self.present = True
        self.patches = [
            patch.object(m, "native"),
            patch.object(m, "task", side_effect=self.task),
            patch.object(
                m, "workers", side_effect=lambda: [self.task(7)] if self.present else []
            ),
            patch.object(
                m.os, "sched_setaffinity", create=True, side_effect=self.setmask
            ),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def task(self, pid):
        return {
            "pid": pid,
            "start_ticks": self.ticks,
            "cpus": sorted(self.mask),
            "comm": "kgsl-fence",
            "ppid": 2,
            "cmdline_empty": True,
            "uids": [0] * 4,
            "policy": 1,
            "rt_priority": 40,
        }

    def setmask(self, pid, cpus):
        self.writes.append((pid, set(cpus)))
        self.mask = set(cpus)

    def test_control_has_no_writes(self):
        self.present = False
        with m.session(
            "boot",
            self.out,
            enabled=False,
            serial="fixture",
            kernel_notes_sha256="0" * 64,
        ) as r:
            self.assertIsNone(r["worker_identity"])
        self.assertEqual(self.writes, [])
        self.assertTrue(r["restored"])

    def test_on_binds_and_restores_only_owned_tid(self):
        with m.session(
            "boot",
            self.out,
            enabled=True,
            serial="fixture",
            kernel_notes_sha256="0" * 64,
        ) as r:
            self.assertEqual(self.mask, {0, 1, 2, 3})
            self.assertEqual(r["worker_identity"], {"pid": 7, "start_ticks": 22})
        self.assertEqual(self.mask, set(range(8)))
        self.assertEqual(len(self.writes), 2)
        self.assertTrue(r["restored"])

    def test_exception_restores(self):
        with self.assertRaisesRegex(RuntimeError, "measurement"):
            with m.session(
                "boot",
                self.out,
                enabled=True,
                serial="fixture",
                kernel_notes_sha256="0" * 64,
            ) as r:
                raise RuntimeError("measurement")
        self.assertTrue(r["restored"])
        self.assertEqual(self.mask, set(range(8)))

    def test_pid_reuse_refuses_restore(self):
        with self.assertRaises(AssertionError):
            with m.session(
                "boot",
                self.out,
                enabled=True,
                serial="fixture",
                kernel_notes_sha256="0" * 64,
            ) as r:
                self.ticks = 23
        self.assertFalse(r["restored"])
        self.assertEqual(len(self.writes), 1)

    def test_affinity_drift_refuses_restore(self):
        with self.assertRaises(AssertionError):
            with m.session(
                "boot",
                self.out,
                enabled=True,
                serial="fixture",
                kernel_notes_sha256="0" * 64,
            ) as r:
                self.mask = {7}
        self.assertFalse(r["restored"])
        self.assertEqual(len(self.writes), 1)

    def test_already_bound_zero_writes(self):
        self.mask = set(m.TARGET)
        with m.session(
            "boot",
            self.out,
            enabled=True,
            serial="fixture",
            kernel_notes_sha256="0" * 64,
        ) as r:
            pass
        self.assertTrue(r["restored"])
        self.assertEqual(self.writes, [])

    def test_failed_bind_restores_if_write_took_effect(self):
        def partial(pid, cpus):
            self.setmask(pid, cpus)
            if len(self.writes) == 1:
                raise OSError("interrupted after bind")

        with (
            patch.object(m.os, "sched_setaffinity", create=True, side_effect=partial),
            self.assertRaises(OSError),
        ):
            with m.session(
                "boot",
                self.out,
                enabled=True,
                serial="fixture",
                kernel_notes_sha256="0" * 64,
            ):
                pass
        self.assertEqual(self.mask, set(range(8)))
        self.assertEqual(len(self.writes), 2)

    def test_missing_enabled_worker_refused(self):
        self.present = False
        with self.assertRaises(AssertionError):
            with m.session(
                "boot",
                self.out,
                enabled=True,
                serial="fixture",
                kernel_notes_sha256="0" * 64,
            ):
                pass
        self.assertEqual(self.writes, [])


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.proc = root / "proc"
        boot = self.proc / "sys/kernel/random/boot_id"
        boot.parent.mkdir(parents=True)
        boot.write_text("fixture-boot")
        (self.proc / "cmdline").write_text(
            "androidboot.serialno=fixture-unit reframed.live=usb msm_kgsl_core.fence_rt=1"
        )
        self.param = root / "parameter"
        self.param.write_text("Y")
        self.notes = b"fixture kernel notes"
        self.notes_sha = m.hashlib.sha256(self.notes).hexdigest()
        for mocked in (
            patch.object(m, "PROC", self.proc),
            patch.object(m, "PARAM", self.param),
            patch.object(m.os, "geteuid", return_value=0),
            patch.object(Path, "read_bytes", return_value=self.notes),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_caller_identity_and_kernel_pin_are_required(self):
        m.native("fixture-boot", True, "fixture-unit", self.notes_sha)
        for boot, serial, notes in (
            ("other-boot", "fixture-unit", self.notes_sha),
            ("fixture-boot", "other-unit", self.notes_sha),
            ("fixture-boot", "fixture-unit", "0" * 64),
        ):
            with (
                self.subTest(boot=boot, serial=serial),
                self.assertRaises(AssertionError),
            ):
                m.native(boot, True, serial, notes)

    def test_boot_parameter_must_match_read_only_parameter(self):
        self.param.write_text("N")
        with self.assertRaises(AssertionError):
            m.native("fixture-boot", True, "fixture-unit", self.notes_sha)

    def test_root_is_required(self):
        with (
            patch.object(m.os, "geteuid", return_value=1000),
            self.assertRaises(AssertionError),
        ):
            m.native("fixture-boot", True, "fixture-unit", self.notes_sha)


if __name__ == "__main__":
    unittest.main()
