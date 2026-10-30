import importlib.util
from pathlib import Path
import subprocess
import tempfile
import stat
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
    def test_guard_checks_character_device_identity_and_closes_on_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, uart, _ = self.fixture(root)
            (uart / 'dev').write_text('243:0\n')
            for mode, device, accepted in ((stat.S_IFCHR, transport.os.makedev(243, 0), True),
                                           (stat.S_IFREG, transport.os.makedev(243, 0), False),
                                           (stat.S_IFCHR, transport.os.makedev(243, 1), False)):
                with self.subTest(mode=mode, device=device), patch.object(transport.os, 'open', return_value=42) as opened, \
                        patch.object(transport.os, 'fstat', return_value=SimpleNamespace(st_mode=mode, st_rdev=device)), \
                        patch.object(transport.os, 'close') as closed:
                    if accepted:
                        guard = transport.TTYGuard(root)
                        closed.assert_not_called()
                        guard.close()
                        guard.close()
                    else:
                        with self.assertRaises(ValueError):
                            transport.TTYGuard(root)
                    closed.assert_called_once_with(42)
                    flags = opened.call_args.args[1]
                    self.assertTrue(flags & transport.os.O_CLOEXEC)
                    self.assertTrue(flags & transport.os.O_NOFOLLOW)
                    self.assertTrue(flags & transport.os.O_NOCTTY)

    def fixture(self, root, original='1', policy='auto'):
        rf = root / 'class/rfkill/rfkill3'
        rf.mkdir(parents=True)
        for name, value in [('name', 'bt_power'), ('type', 'bluetooth'),
                            ('hard', '0'), ('soft', original)]:
            (rf / name).write_text(value + '\n')
        device = root / 'devices/platform/soc/998000.qcom,qup_uart'
        driver = root / 'bus/platform/drivers/msm_geni_serial'
        driver.mkdir(parents=True)
        device.mkdir(parents=True)
        (device / 'driver').symlink_to(driver)
        (device / 'subsystem').symlink_to(root / 'bus/platform')
        (driver / device.name).symlink_to(device)
        (device / 'of_node').mkdir()
        (device / 'of_node/compatible').write_bytes(b'qcom,msm-geni-serial-hs\0')
        (device / 'of_node/qcom,wakeup-byte').write_bytes(b'\0\0\0\xfd')
        (device / 'power').mkdir()
        (device / 'power/control').write_text(policy + '\n')
        (device / 'power/runtime_status').write_text('active\n')
        uart = device / 'tty/ttyHS0'
        uart.mkdir(parents=True)
        (root / 'class/tty').mkdir(parents=True)
        (root / 'class/tty/ttyHS0').symlink_to(uart)
        (root / 'class/bluetooth').mkdir(parents=True)
        return rf / 'soft', uart, root / 'class/bluetooth/hci0'

    def exercise(self, fault=None, original='1', policy='auto'):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            soft, uart, adapter = self.fixture(root, original, policy)
            control = uart.parents[1] / 'power/control'
            calls, report, ready, reads = [], {}, [], 0
            stopping = False
            events = []
            class Child:
                pid = 123
                code = None
                terminated = False
                killed = False
                def poll(self):
                    if fault == 'exit': self.code = 7
                    return self.code
                def terminate(self):
                    self.terminated = True
                    if fault != 'stuck':
                        self.code = -15
                    events.append('child-terminated')
                def kill(self):
                    self.killed = True
                    self.code = -9
                def wait(self, timeout):
                    events.append('child-wait')
                    if self.code is None:
                        raise subprocess.TimeoutExpired('btattach', timeout)
                    return self.code
            child = Child()
            class Guard:
                def __init__(self, sysfs):
                    self_test.assertEqual(sysfs, root)
                    self_test.assertEqual(control.read_text().strip(), policy)
                    if fault == 'guard-open':
                        raise OSError('fixture guard open failure')
                    events.append('guard-open')
                def close(self):
                    self_test.assertEqual(control.read_text().strip(), policy if fault != 'pm-policy-changed' else 'auto')
                    if child.terminated:
                        self_test.assertIn('child-wait', events)
                    self_test.assertFalse(report.get('adapter_detached', False))
                    if adapter.is_symlink() and fault != 'detach':
                        adapter.unlink()
                    events.append('guard-close')
            self_test = self
            def spawn(command):
                calls.append(command)
                self.assertEqual(soft.read_text().strip(), '0')
                self.assertEqual(control.read_text().strip(), 'on')
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
                if fault == 'pm-policy-changed':
                    control.write_text('auto\n')
                if fault == 'pm-suspended':
                    control.with_name('runtime_status').write_text('suspended\n')
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
                                            settle_seconds=0, open_guard=Guard)
                except BaseException as error:
                    failure = error
            self.assertEqual(soft.read_text().strip(), original)
            if fault != 'bluez':
                self.assertTrue(report['rfkill_restored'])
            if fault == 'pm-policy-changed':
                self.assertEqual(control.read_text().strip(), 'auto')
                self.assertFalse(report['uart_runtime_power']['restored'])
            else:
                self.assertEqual(control.read_text().strip(), policy)
                if fault not in ('bluez',):
                    self.assertTrue(report['uart_runtime_power']['restored'])
            if fault not in ('bluez', 'guard-open'):
                self.assertEqual(events[0], 'guard-open')
                self.assertEqual(events[-1], 'guard-close')
                self.assertTrue(report['tty_guard_closed'])
                if fault != 'pm-policy-changed':
                    self.assertTrue(report['uart_runtime_power']['restored_before_tty_close'])
            return failure, report, ready, calls, child

    def test_existing_on_policy_is_preserved(self):
        error, report, ready, calls, child = self.exercise(policy='on')
        self.assertIsNone(error)
        self.assertEqual(report['uart_runtime_power']['original_policy'], 'on')
        self.assertTrue(report['uart_runtime_power']['restored'])

    def test_runtime_pm_failure_and_external_change_stop_attachment(self):
        for fault in ('pm-suspended', 'pm-policy-changed'):
            with self.subTest(fault=fault):
                error, report, ready, calls, child = self.exercise(fault)
                self.assertIsNotNone(error)
                self.assertFalse(ready)
                self.assertTrue(child.terminated)

    def test_wrong_uart_binding_is_refused_before_mutation(self):
        for field, value in [('compatible', b'qcom,msm-geni-console\0'),
                             ('qcom,wakeup-byte', b'\0\0\0\xfc')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                soft, uart, adapter = self.fixture(root)
                control = uart.parents[1] / 'power/control'
                (uart.parents[1] / 'of_node' / field).write_bytes(value)
                with self.assertRaisesRegex(ValueError, 'Unexpected Pico Bluetooth UART binding'):
                    transport.own_transport(lambda: None, lambda: False, {}, lambda: None,
                                            sysfs=root, run=lambda *a, **k: SimpleNamespace(returncode=3),
                                            spawn=lambda _: self.fail('must not attach'))
                self.assertEqual(control.read_text().strip(), 'auto')
                self.assertEqual(soft.read_text().strip(), '1')

    def test_readiness_requires_a_bound_initialized_unpowered_adapter(self):
        for original in ('0', '1'):
            error, report, ready, calls, child = self.exercise(original=original)
            self.assertIsNone(error)
            self.assertEqual(ready, [True])
            self.assertTrue(report['adapter_detached'])
            self.assertTrue(child.terminated)
            self.assertEqual(calls[1], ['btattach', '-B', '/dev/ttyHS0', '-P', 'qca', '-S', '115200'])

    def test_failed_startups_restore_rfkill_and_never_signal_ready(self):
        for fault in ('guard-open', 'spawn', 'exit', 'timeout', 'powered', 'wrong-uart', 'close'):
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
