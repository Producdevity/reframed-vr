import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "maintenance", ROOT / "tools/pico-gpu-maintenance.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queues = self.root / "queues"
        self.queues.mkdir()
        self.boot = self.root / "boot"
        self.boot.write_text("boot")
        self.original = {}
        for name in (*p.EXPECTED, p.CALLBACK):
            queue = self.queues / name
            queue.mkdir()
            attrs = {
                "nice": "-20" if name == p.CALLBACK else "0",
                "cpumask": "0f" if name == p.CALLBACK else "ff",
                "max_active": str(p.EXPECTED.get(name, 256)),
                "numa": "1",
            }
            self.original[name] = attrs
            for attribute, value in attrs.items():
                (queue / attribute).write_text(value + "\n")
            (queue / "pool_ids").write_text("0:31" if name == p.CALLBACK else "0:17")
        self.provenance = {"kernel": "fixture", "source_sha256": "a" * 64}
        self.native = {"global_mask": "ff", "online": "0-7", "possible": "0-7"}
        self.writes = []
        self.on_write = None
        self.guard_calls = 0
        original_fstat = os.fstat

        def root_stat(fd):
            info = list(original_fstat(fd))
            info[4] = 0
            return os.stat_result(info)

        write = p._Queue.write_mask

        def fixture_write(queue, value):
            self.writes.append((queue.name, value))
            write(queue, value)
            (queue.path / "pool_ids").write_text("0:29" if value == "70" else "0:19")
            if self.on_write:
                self.on_write(queue, value)

        self.patches = [
            patch.object(p, "QUEUES", self.queues),
            patch.object(p, "LOCK", self.root / "lock"),
            patch.object(p.events, "BOOT", self.boot),
            patch.object(p, "validate_device"),
            patch.object(p.events, "native_preflight", side_effect=lambda *_: self.native.copy()),
            patch.object(p.os, "fstat", side_effect=root_stat),
            patch.object(p, "_validate_lock", side_effect=self.validate_fixture_lock),
            patch.object(p._Queue, "write_mask", fixture_write),
        ]
        for item in self.patches:
            item.start()

    @staticmethod
    def validate_fixture_lock(info):
        if info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError("Fixture lock is not private")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def guard(self):
        self.guard_calls += 1
        return self.provenance.copy()

    def context(self, guard=None, enabled=True):
        return p.place_maintenance("serial", "boot", source_guard=guard or self.guard, enabled=enabled)

    def attrs(self, name):
        return {a: (self.queues / name / a).read_text().strip() for a in p.ATTRIBUTES}

    def assert_restored(self):
        for name, attrs in self.original.items():
            self.assertEqual(self.attrs(name), attrs)

    def test_only_two_masks_and_reverse_restoration_with_complete_receipt(self):
        with self.context() as record:
            for name in p.EXPECTED:
                self.assertEqual(self.attrs(name), self.original[name] | {"cpumask": "70"})
            self.assertEqual(self.attrs(p.CALLBACK), self.original[p.CALLBACK])
            self.assertTrue(record["active"]["queues"])
        self.assert_restored()
        names = list(p.EXPECTED)
        self.assertEqual(self.writes, [(n, "70") for n in names] + [(n, "ff") for n in reversed(names)])
        self.assertEqual(record["restoration_errors"], [])
        for stage in ("before", "active", "before_restore", "after"):
            self.assertEqual(set(record[stage]["queues"]), {*p.EXPECTED, p.CALLBACK})
            for row in record[stage]["queues"].values():
                self.assertEqual(set(row["attribute_identities"]), {*p.ATTRIBUTES, "pool_ids"})
                self.assertIn("inode", row["identity"])
                self.assertTrue(row["pools"]["pool_ids"])
        self.assertEqual(record["after"]["queues"][names[0]]["pools"]["pool_ids"], [19])
        self.assertGreaterEqual(self.guard_calls, 4)

    def test_nondefault_numa_is_retained(self):
        name = next(iter(p.EXPECTED))
        for key, value in {"numa": "0"}.items():
            (self.queues / name / key).write_text(value)
            self.original[name][key] = value
        with self.context():
            self.assertEqual(self.attrs(name)["nice"], "0")
            self.assertEqual(self.attrs(name)["numa"], "0")
        self.assert_restored()

    def test_nonoriginal_masks_or_nice_are_rejected_without_writes(self):
        name = next(iter(p.EXPECTED))
        for key, value in (("cpumask", "70"), ("cpumask", "f0"), ("nice", "-5")):
            (self.queues / name / key).write_text(value)
            for enabled in (True, False):
                with self.subTest(key=key, enabled=enabled), self.assertRaises(ValueError):
                    with self.context(enabled=enabled):
                        self.fail()
            (self.queues / name / key).write_text(self.original[name][key])
        self.assertEqual(self.writes, [])
        self.assert_restored()

    def test_control_is_default_with_identical_snapshots_and_zero_writes(self):
        with p.place_maintenance("serial", "boot", source_guard=self.guard) as record:
            self.assert_restored()
            self.assertFalse(record["enabled"])
            self.assertEqual(record["experiment"], "maintenance-control")
        self.assertEqual(self.writes, [])
        self.assertEqual(record["mutations"], [])
        self.assertEqual(record["restorations"], [])
        for stage in ("active", "before_restore", "after"):
            self.assertEqual(record[stage]["queues"], record["before"]["queues"])

    def test_control_body_failure_never_writes(self):
        failure = RuntimeError("control workload")
        with self.assertRaises(RuntimeError) as got:
            with self.context(enabled=False):
                raise failure
        self.assertIs(got.exception, failure)
        self.assertEqual(self.writes, [])
        self.assertIn("after", failure.receipt)

    def test_devfreq_path_is_absent_and_never_accessed_in_either_arm(self):
        devfreq = self.queues / "kgsl_devfreq_wq"
        self.assertFalse(devfreq.exists())
        open_file = os.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn("kgsl_devfreq_wq", str(path))
            return open_file(path, *args, **kwargs)

        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(p.os, "open", side_effect=guarded_open):
                with self.context(enabled=enabled) as record:
                    for stage in ("before", "active"):
                        self.assertEqual(set(record[stage]["queues"]), {*p.EXPECTED, p.CALLBACK})
                self.assertEqual(set(record["after"]["queues"]), {*p.EXPECTED, p.CALLBACK})
        self.assertFalse(any(name == "kgsl_devfreq_wq" for name, _ in self.writes))
        self.assert_restored()

    def test_control_requires_pool_isolation_without_cpu_isolation(self):
        name = next(iter(p.EXPECTED))
        (self.queues / name / "pool_ids").write_text("0:31")
        with self.assertRaisesRegex(RuntimeError, "pools overlap"):
            with self.context(enabled=False):
                self.fail()
        self.assertEqual(self.writes, [])

    def test_enabled_must_be_boolean(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with self.context(enabled=value):
                    self.fail()
        self.assertEqual(self.writes, [])

    def test_workload_error_and_keyboard_interrupt_preserved(self):
        for failure in (RuntimeError("workload"), KeyboardInterrupt()):
            with self.subTest(failure=failure), self.assertRaises(type(failure)) as got:
                with self.context():
                    raise failure
            self.assertIs(got.exception, failure)
            self.assertEqual(failure.receipt["restoration_errors"], [])
            self.assert_restored()

    def test_each_partial_write_is_restored_including_failed_attempt(self):
        for failed in p.EXPECTED:
            with self.subTest(queue=failed):
                self.writes.clear()

                def fail(queue, value):
                    if queue.name == failed and value == "70":
                        raise OSError("write completed then failed")

                self.on_write = fail
                with self.assertRaisesRegex(OSError, "completed") as got:
                    with self.context():
                        self.fail("Partial write admitted")
                attempted = list(p.EXPECTED)[:list(p.EXPECTED).index(failed) + 1]
                self.assertEqual([r["queue"] for r in got.exception.receipt["restorations"]], attempted[::-1])
                self.assert_restored()

    def test_restore_failure_keeps_original_cause_and_attempts_remaining_queues(self):
        failed = list(p.EXPECTED)[1]
        failure = RuntimeError("original workload")

        def fail(queue, value):
            if queue.name == failed and value == "ff":
                raise OSError("restore failed")

        self.on_write = fail
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                raise failure
        self.assertIs(got.exception.__cause__, failure)
        self.assertEqual(len(got.exception.receipt["restorations"]), 2)
        self.assertIn("original workload", got.exception.receipt["error"])
        self.assertTrue(got.exception.receipt["restoration_errors"])

    def test_shared_callback_pool_rejects_after_apply_and_restores(self):
        def overlap(queue, value):
            if value == "70":
                (queue.path / "pool_ids").write_text("0:31")

        self.on_write = overlap
        with self.assertRaisesRegex(RuntimeError, "pools overlap"):
            with self.context():
                self.fail("Callback pool sharing admitted")
        self.assert_restored()

    def test_active_readback_error_restores(self):
        snapshot = p._Queue.snapshot
        calls = 0

        def fail(queue):
            nonlocal calls
            calls += 1
            if calls == 8:
                raise OSError("active read")
            return snapshot(queue)

        with patch.object(p._Queue, "snapshot", fail), self.assertRaisesRegex(OSError, "active read"):
            with self.context():
                self.fail()
        self.assert_restored()

    def test_bad_source_guard_or_changed_provenance_rejects(self):
        for value in (None, {}, {"bad": float("nan")}, {"oversize": "x" * 17000}):
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                with self.context(lambda: value):
                    self.fail()
        self.assertEqual(self.writes, [])
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                self.provenance = {"kernel": "changed"}
        self.assertIn("provenance", got.exception.receipt["error"])
        self.assert_restored()

    def test_missing_or_changed_source_rejects_before_any_write(self):
        def reject():
            raise ValueError("kernel source unavailable")

        with self.assertRaisesRegex(ValueError, "source unavailable"):
            with self.context(reject):
                self.fail()
        self.assertEqual(self.writes, [])
        self.assertFalse(p.LOCK.exists())

    def test_missing_queue_rejects_without_mutation(self):
        name = list(p.EXPECTED)[1]
        (self.queues / name).rename(self.queues / "missing")
        with self.assertRaises(FileNotFoundError):
            with self.context():
                self.fail()
        self.assertEqual(self.writes, [])

    def test_expected_max_active_and_callback_policy_required(self):
        cases = [(name, "max_active", "2") for name in p.EXPECTED]
        cases += [(p.CALLBACK, "nice", "0"), (p.CALLBACK, "cpumask", "f0")]
        for name, attr, value in cases:
            path = self.queues / name / attr
            old = path.read_text()
            path.write_text(value)
            with self.subTest(queue=name, attr=attr), self.assertRaises(ValueError):
                with self.context():
                    self.fail()
            path.write_text(old)
        self.assertEqual(self.writes, [])

    def test_topology_failure_and_global_mask_exclusion_precede_writes(self):
        for mask in ("0f", "3f", "8f", "00"):
            self.native["global_mask"] = mask
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                with self.context():
                    self.fail()
        with patch.object(p.events, "native_preflight", side_effect=ValueError("MIDR")):
            with self.assertRaisesRegex(ValueError, "MIDR"):
                with self.context():
                    self.fail()
        self.assertEqual(self.writes, [])

    def test_bad_pool_data_or_oversize_metadata_rejects(self):
        name = next(iter(p.EXPECTED))
        path = self.queues / name / "pool_ids"
        for value in ("", "0:1 0:2", "0:-1", "4096:1", "0:2147483648", "x" * 4097):
            path.write_text(value)
            with self.subTest(value=value[:30]), self.assertRaises(ValueError):
                with self.context():
                    self.fail()
        self.assertEqual(self.writes, [])

    def test_nested_owner_refused_without_resetting_outer(self):
        with self.context():
            with self.assertRaises(BlockingIOError):
                with self.context():
                    self.fail()
            self.assertEqual(len(self.writes), 2)
            self.assertTrue(all(self.attrs(name)["cpumask"] == "70" for name in p.EXPECTED))
        self.assert_restored()

    def test_symlink_and_nonprivate_locks_reject(self):
        target = self.root / "target"
        target.touch(mode=0o600)
        p.LOCK.symlink_to(target)
        with self.assertRaises(OSError):
            with self.context():
                self.fail()
        p.LOCK.unlink()
        p.LOCK.touch(mode=0o644)
        with self.assertRaises(ValueError):
            with self.context():
                self.fail()
        self.assertEqual(self.writes, [])

    def test_queue_replacement_refuses_its_restore_but_restores_others(self):
        replaced = list(p.EXPECTED)[1]
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                original = self.queues / replaced
                original.rename(self.queues / "old")
                original.mkdir()
                (original / "cpumask").write_text("replacement")
        self.assertEqual((self.queues / replaced / "cpumask").read_text(), "replacement")
        self.assertEqual(len(got.exception.receipt["restorations"]), 2)
        for name in p.EXPECTED:
            if name != replaced:
                self.assertEqual(self.attrs(name), self.original[name])

    def test_attribute_replacement_refuses_write_to_replacement(self):
        name = next(iter(p.EXPECTED))
        path = self.queues / name / "cpumask"
        with self.assertRaises(p.MaintenancePolicyError):
            with self.context():
                path.rename(path.with_name("old-mask"))
                path.write_text("replacement")
        self.assertEqual(path.read_text(), "replacement")

    def test_boot_or_lock_drift_refuses_all_restoration_writes(self):
        for target in ("boot", "lock"):
            with self.subTest(target=target), self.assertRaises(p.MaintenancePolicyError) as got:
                with self.context():
                    if target == "boot":
                        self.boot.write_text("new-boot")
                    else:
                        p.LOCK.rename(self.root / "old-lock")
                        p.LOCK.touch(mode=0o600)
            self.assertTrue(all("error" in row for row in got.exception.receipt["restorations"]))
            self.boot.write_text("boot")
            for name in p.EXPECTED:
                (self.queues / name / "cpumask").write_text("ff\n")

    def test_lock_permissions_drift_refuses_restoration_writes(self):
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                p.LOCK.chmod(0o644)
        self.assertTrue(all("error" in row for row in got.exception.receipt["restorations"]))

    def test_topology_change_after_apply_restores_masks(self):
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                self.native["online"] = "0-6"
        self.assertIn("drifted", got.exception.receipt["error"])
        self.assert_restored()

    def test_unrelated_drift_is_reported_without_overwriting_it(self):
        name = next(iter(p.EXPECTED))
        with self.assertRaises(p.MaintenancePolicyError) as got:
            with self.context():
                (self.queues / name / "nice").write_text("-5")
        self.assertEqual(self.attrs(name)["nice"], "-5")
        self.assertEqual(self.attrs(name)["cpumask"], "ff")
        self.assertIn("drifted", got.exception.receipt["error"])


class BoundedIdentityTests(unittest.TestCase):
    def test_devfreq_handle_and_callback_write_are_forbidden_before_io(self):
        with patch.object(p.os, "open") as open_file:
            with self.assertRaisesRegex(ValueError, "outside"):
                p._Queue("kgsl_devfreq_wq")
            open_file.assert_not_called()
            queue = p._Queue.__new__(p._Queue)
            queue.name = p.CALLBACK
            with self.assertRaisesRegex(ValueError, "observation-only"):
                queue.write_mask("70")
            open_file.assert_not_called()

    def test_lock_requires_root_private_regular_single_link(self):
        with tempfile.NamedTemporaryFile() as stream:
            values = list(os.fstat(stream.fileno()))
            values[4] = 0
            p._validate_lock(os.stat_result(values))
            for index, value in ((4, 501), (3, 2), (0, 0o100644), (0, 0o040600)):
                changed = values.copy()
                changed[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    p._validate_lock(os.stat_result(changed))

    def test_short_reads_continue_to_eof_and_overflow_refuses(self):
        with patch.object(p.os, "read", side_effect=[b"ab", b"c", b""]):
            self.assertEqual(p._read_fd(1), b"abc")
        with patch.object(p.os, "read", return_value=b"x" * 4097):
            with self.assertRaises(ValueError):
                p._read_fd(1)

    def test_native_identity_exact_board_arch_root_serial_and_boot(self):
        boot = "12345678-1234-1234-1234-123456789abc"
        correct = b"qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0"
        with (
            patch.object(p.events.platform, "system", return_value="Linux"),
            patch.object(p.events.platform, "machine", return_value="aarch64") as machine,
            patch.object(p.os, "geteuid", return_value=0) as uid,
            patch.object(p.events, "bounded_text", side_effect=lambda path: boot if path == p.events.BOOT else "androidboot.serialno=fixture"),
            patch.object(p, "_bounded_bytes", return_value=correct) as compatible,
        ):
            p.validate_device("fixture", boot)
            for wrong in ("other", "fixture\n"):
                with self.assertRaises(ValueError):
                    p.validate_device(wrong, boot)
            machine.return_value = "x86_64"
            with self.assertRaises(ValueError):
                p.validate_device("fixture", boot)
            machine.return_value = "aarch64"
            uid.return_value = 501
            with self.assertRaises(ValueError):
                p.validate_device("fixture", boot)
            uid.return_value = 0
            compatible.return_value = correct + b"other\0"
            with self.assertRaises(ValueError):
                p.validate_device("fixture", boot)
            compatible.return_value = correct
            with self.assertRaises(ValueError):
                p.validate_device("fixture", "12345678-1234-1234-1234-123456789abd")


if __name__ == "__main__":
    unittest.main()
