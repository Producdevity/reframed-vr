import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('transport', ROOT / 'tools/pico-bluetooth-transport.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)

INFO = ('hci0: Primary controller\n'
        '\taddr 00:03:7f:12:2b:b0 version 11 manufacturer 29 class 0x000000\n'
        '\tcurrent settings: br/edr\n'
        'hci0: Configuration options\n\tsupported options: public-address\n')


class BluetoothTransportTests(unittest.TestCase):
    def fixture(self, root, original='1'):
        rf = root / 'class/rfkill/rfkill3'
        rf.mkdir(parents=True)
        for name, value in [('name', 'bt_power'), ('type', 'bluetooth'),
                            ('hard', '0'), ('soft', original)]:
            (rf / name).write_text(value + '\n')
        uart = root / 'devices/uart/tty/ttyHS0'
        uart.mkdir(parents=True)
        (root / 'class/tty').mkdir(parents=True)
        (root / 'class/tty/ttyHS0').symlink_to(uart)
        (root / 'class/bluetooth').mkdir(parents=True)
        return rf / 'soft', uart, root / 'class/bluetooth/hci0'

    def exercise(self, fault=None, original='1'):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            soft, uart, adapter = self.fixture(root, original)
            calls, report, ready, reads = [], {}, [], 0
            stopping = False
            class Child:
                pid = 123
                code = None
                terminated = False
                killed = False
                def poll(self):
                    return 7 if fault == 'exit' else self.code
                def terminate(self):
                    self.terminated = True
                    if fault != 'stuck':
                        self.code = -15
                    if adapter.is_symlink() and fault != 'detach':
                        adapter.unlink()
                def kill(self):
                    self.killed = True
                    self.code = -9
                def wait(self, timeout):
                    if self.code is None:
                        raise subprocess.TimeoutExpired('btattach', timeout)
                    return self.code
            child = Child()
            def spawn(command):
                calls.append(command)
                self.assertEqual(soft.read_text().strip(), '0')
                if fault == 'spawn':
                    raise OSError('fixture spawn failure')
                if fault not in ('timeout', 'exit', 'stop-starting'):
                    (uart / 'hci0').mkdir()
                    adapter.symlink_to(uart / 'hci0')
                if fault == 'wrong-uart':
                    adapter.unlink()
                    other = root / 'devices/usb/hci0'
                    other.mkdir(parents=True)
                    adapter.symlink_to(other)
                return child
            def run(command, **kwargs):
                nonlocal reads
                calls.append(command)
                if command[0] == 'systemctl':
                    return SimpleNamespace(returncode=0 if fault == 'bluez' else 3)
                if command[0] == 'hciconfig':
                    self.assertEqual(command, ['hciconfig', 'hci0', 'down'])
                    return SimpleNamespace(returncode=1 if fault == 'close' else 0, stdout='')
                reads += 1
                if fault == 'pending-info' and reads == 1:
                    return SimpleNamespace(returncode=0, stdout='Invalid index\n')
                raw = INFO.replace('br/edr', 'powered br/edr') if fault == 'powered' else INFO
                return SimpleNamespace(returncode=0, stdout=raw)
            def notify():
                nonlocal stopping
                ready.append(True)
                if fault == 'notify':
                    raise OSError('fixture notification failure')
                stopping = True
            stopped = lambda: stopping or fault == 'stop-starting'
            failure = None
            with patch.object(transport.time, 'sleep'):
                try:
                    transport.own_transport(lambda: None, stopped, report, notify, sysfs=root,
                                            run=run, spawn=spawn, seconds=1 if fault == 'pending-info' else 0,
                                            settle_seconds=0)
                except BaseException as error:
                    failure = error
            self.assertEqual(soft.read_text().strip(), original)
            if fault != 'bluez':
                self.assertTrue(report['rfkill_restored'])
            return failure, report, ready, calls, child

    def test_readiness_requires_a_bound_initialized_unpowered_adapter(self):
        for original in ('0', '1'):
            error, report, ready, calls, child = self.exercise(original=original)
            self.assertIsNone(error)
            self.assertEqual(ready, [True])
            self.assertTrue(report['adapter_detached'])
            self.assertTrue(child.terminated)
            self.assertEqual(calls[1], ['btattach', '-B', '/dev/ttyHS0', '-P', 'qca', '-S', '115200'])

    def test_failed_startups_restore_rfkill_and_never_signal_ready(self):
        for fault in ('spawn', 'exit', 'timeout', 'powered', 'wrong-uart', 'close'):
            with self.subTest(fault=fault):
                error, report, ready, _, _ = self.exercise(fault)
                self.assertIsNotNone(error)
                self.assertFalse(ready)
                self.assertTrue(report['rfkill_restored'])

    def test_registered_adapter_can_precede_management_readiness(self):
        error, report, ready, calls, _ = self.exercise('pending-info')
        self.assertIsNone(error)
        self.assertEqual(ready, [True])
        self.assertEqual(sum(c[0] == 'btmgmt' for c in calls), 2)
        self.assertTrue(report['adapter_detached'])

    def test_management_unpowered_requires_synchronous_close_before_readiness(self):
        error, report, ready, calls, _ = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(ready, [True])
        self.assertEqual(calls[-1], ['hciconfig', 'hci0', 'down'])
        self.assertTrue(report['kernel_closed_before_identity'])

    def test_existing_bluez_is_not_interrupted(self):
        error, report, ready, calls, child = self.exercise('bluez')
        self.assertIn('BlueZ', str(error))
        self.assertEqual(len(calls), 1)
        self.assertFalse(child.terminated)
        self.assertFalse(report)
        self.assertFalse(ready)

    def test_stop_during_initialization_and_notification_failure_cleanup(self):
        error, report, ready, _, child = self.exercise('stop-starting')
        self.assertIsNone(error)
        self.assertFalse(ready)
        self.assertTrue(child.terminated)
        error, report, _, _, child = self.exercise('notify')
        self.assertIn('notification', str(error))
        self.assertTrue(report['rfkill_restored'])
        self.assertTrue(child.terminated)

    def test_stuck_owned_process_is_killed_and_cleanup_failure_is_visible(self):
        error, report, _, _, child = self.exercise('stuck')
        self.assertIsNone(error)
        self.assertTrue(child.killed)
        self.assertEqual(report['child_returncode'], -9)
        error, report, _, _, _ = self.exercise('detach')
        self.assertIn('did not detach', str(error))
        self.assertTrue(report['cleanup_errors'])
        self.assertTrue(report['rfkill_restored'])

    def test_existing_adapter_and_unsafe_rfkill_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            soft, uart, adapter = self.fixture(root)
            for name, value in [('hard', '1'), ('type', 'wlan'), ('soft', '9')]:
                path = soft.with_name(name)
                old = path.read_text()
                path.write_text(value)
                with self.assertRaises(ValueError):
                    transport.radio(root)
                path.write_text(old)
            (uart / 'hci0').mkdir()
            adapter.symlink_to(uart / 'hci0')
            with self.assertRaisesRegex(ValueError, 'existing Bluetooth adapter'):
                transport.own_transport(lambda: None, lambda: False, {}, lambda: None,
                                        sysfs=root, run=lambda *a, **k: SimpleNamespace(returncode=3),
                                        spawn=lambda _: self.fail('must not attach'))
            self.assertEqual(soft.read_text().strip(), '1')


if __name__ == '__main__':
    unittest.main()
