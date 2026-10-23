import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pico_gpu_events', ROOT / 'tools/pico-gpu-events.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class GpuEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = self.root / 'queue'
        self.queue.mkdir()
        self.original = {'nice': '0', 'cpumask': 'ff', 'max_active': '256', 'numa': '1'}
        for name, value in self.original.items():
            (self.queue / name).write_text(value + '\n')
        original_stat = os.fstat
        self.patches = [patch.object(policy, 'QUEUE', self.queue),
                        patch.object(policy, 'LOCK', self.root / 'policy.lock'),
                        patch.object(policy, 'validate_device'),
                        patch.object(policy.os, 'fstat', wraps=os.fstat)]
        for item in self.patches:
            item.start()
        def root_stat(fd):
            result = list(original_stat(fd))
            result[4] = 0
            return os.stat_result(result)
        policy.os.fstat.side_effect = root_stat

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_only_nice_changes_and_restores_after_workload_error(self):
        with self.assertRaisesRegex(RuntimeError, 'workload failed'):
            with policy.prioritize_events('serial', 'boot') as record:
                self.assertEqual(policy.snapshot(), self.original | {'nice': '-20'})
                raise RuntimeError('workload failed')
        self.assertEqual(policy.snapshot(), self.original)
        self.assertEqual(record['after'], self.original)

    def test_nested_owner_cannot_reset_active_policy(self):
        with policy.prioritize_events('serial', 'boot'):
            with self.assertRaises(BlockingIOError):
                with policy.prioritize_events('serial', 'boot'):
                    self.fail('Second policy owner acquired the queue')
            self.assertEqual(policy.snapshot()['nice'], '-20')
        self.assertEqual(policy.snapshot(), self.original)

    def test_restores_existing_nondefault_priority(self):
        (self.queue / 'nice').write_text('-5\n')
        with policy.prioritize_events('serial', 'boot'):
            self.assertEqual(policy.snapshot()['nice'], '-20')
        self.assertEqual(policy.snapshot()['nice'], '-5')

    def test_rejects_symlink_lock_before_mutation(self):
        lock = self.root / 'policy.lock'
        target = self.root / 'other'
        target.touch(mode=0o600)
        lock.symlink_to(target)
        with self.assertRaises(OSError):
            with policy.prioritize_events('serial', 'boot'):
                self.fail('Symlink lock accepted')
        self.assertEqual(policy.snapshot(), self.original)

    def test_device_rejection_leaves_queue_unchanged(self):
        policy.validate_device.side_effect = ValueError('Wrong device')
        with self.assertRaisesRegex(ValueError, 'Wrong device'):
            with policy.prioritize_events('serial', 'boot'):
                self.fail('Invalid device accepted')
        self.assertEqual(policy.snapshot(), self.original)
        self.assertFalse((self.root / 'policy.lock').exists())


class GpuDeviceIdentityTests(unittest.TestCase):
    def test_exact_board_and_arm64_are_required(self):
        boot='12345678-1234-1234-1234-123456789abc'
        correct=b'qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0'
        texts={'/proc/cmdline':'androidboot.serialno=fixture',
               '/proc/sys/kernel/random/boot_id':boot}
        with patch.object(policy.platform,'system',return_value='Linux'), \
                patch.object(policy.os,'geteuid',return_value=0), \
                patch.object(Path,'read_text',autospec=True,side_effect=lambda p: texts[str(p)]):
            for machine,compatible in [('aarch64',correct),('x86_64',correct),
                                       ('aarch64',b'qcom,kona-iot\0'),
                                       ('aarch64',correct+b'other\0')]:
                with self.subTest(machine=machine,compatible=compatible), \
                        patch.object(policy.platform,'machine',return_value=machine), \
                        patch.object(Path,'read_bytes',return_value=compatible):
                    if machine=='aarch64' and compatible==correct:
                        policy.validate_device('fixture',boot)
                    else:
                        with self.assertRaises(ValueError):policy.validate_device('fixture',boot)


if __name__ == '__main__':
    unittest.main()
