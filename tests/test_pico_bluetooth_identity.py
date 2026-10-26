import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


bt = module('bluetooth_identity', 'tools/pico-bluetooth-identity.py')
collector = module('wireless_config', 'tools/pico-wireless-config.py')
UNIT = 'a0:12:34:56:78:90'
BOOT = '11111111-1111-4111-8111-111111111111'


def info(address='00:03:7f:12:2b:b0', settings='br/edr'):
    return ('hci0: Primary controller\n'
            f'\taddr {address} version 11 manufacturer 29 class 0x000000\n'
            f'\tcurrent settings: {settings}\n'
            'hci0: Configuration options\n'
            '\tsupported options: public-address\n\tmissing options:\n')


class PicoBluetoothIdentityTests(unittest.TestCase):
    def test_adapter_must_belong_to_the_selected_uart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            uart = root / 'devices/platform/soc/uart/tty/ttyHS0'
            (uart / 'hci0').mkdir(parents=True)
            for name in ('bluetooth', 'tty'):
                (root / 'class' / name).mkdir(parents=True)
            (root / 'class/tty/ttyHS0').symlink_to(uart)
            adapter = root / 'class/bluetooth/hci0'
            adapter.symlink_to(uart / 'hci0')
            bt.validate_transport(0, root)
            adapter.unlink()
            other = root / 'devices/usb/hci0'
            other.mkdir(parents=True)
            adapter.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'ttyHS0 transport'):
                bt.validate_transport(0, root)
            adapter.unlink()
            with self.assertRaises(FileNotFoundError):
                bt.validate_transport(0, root)

    def test_service_termination_restores_address_and_signal_handlers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'result.json'
            original = '00:03:7f:12:2b:b0'
            current = original
            writes = []
            previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
            real_open, real_fstat = os.open, os.fstat

            def opened(path, *args, **kwargs):
                if str(path) == '/run/reframed-pico-bluetooth-identity.lock':
                    path = root / 'lock'
                return real_open(path, *args, **kwargs)

            def root_lock(fd):
                value = real_fstat(fd)
                return SimpleNamespace(st_mode=value.st_mode, st_uid=0, st_nlink=value.st_nlink)

            def run(command, **_kwargs):
                nonlocal current
                if command[:2] == ['systemctl', 'is-active']:
                    return subprocess.CompletedProcess(command, 3)
                if command[-2] == 'public-addr':
                    current = command[-1]
                    writes.append(current)
                    signal.raise_signal(signal.SIGTERM)
                    return subprocess.CompletedProcess(command, 0, '', '')
                return subprocess.CompletedProcess(command, 0, info(current), '')

            arguments = ['pico-bluetooth-identity.py', '--boot-serial', 'fixture', '--boot-id', BOOT,
                         '--identity', str(root / 'identity.json'), '--output', str(output)]
            with patch.object(sys, 'argv', arguments), patch.object(bt, 'validate_device'), \
                    patch.object(bt, 'validate_transport'), \
                    patch.object(bt, 'load_identity', return_value=(UNIT, 'fixture-sha')), \
                    patch.object(bt.os, 'open', opened), patch.object(bt.os, 'fstat', root_lock), \
                    patch.object(bt.subprocess, 'run', run):
                with self.assertRaisesRegex(InterruptedError, 'interrupted by signal'):
                    bt.main()
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['rollback']['status'], 'restored')
            self.assertEqual(current, original)
            self.assertEqual(writes, [UNIT, original])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            for sig, handler in previous.items():
                self.assertEqual(signal.getsignal(sig), handler)

    def test_provisioning_requires_unpowered_adapter_and_verifies_readback(self):
        calls, checks, report = [], [], {}

        def run(command):
            calls.append(command)
            return info(UNIT if len(calls) == 3 else '00:03:7f:12:2b:b0') if command[-1] == 'info' else ''

        bt.provision(0, UNIT, run, report, lambda: checks.append(True))
        self.assertEqual(calls, [['btmgmt', '--index', '0', 'info'],
                                 ['btmgmt', '--index', '0', 'public-addr', UNIT],
                                 ['btmgmt', '--index', '0', 'info']])
        self.assertEqual(report['after']['address'], UNIT)
        self.assertNotIn('powered', report['after']['settings'])
        self.assertTrue(report['address_write_attempted'])
        self.assertEqual(len(checks), 3)

    def test_matching_unit_address_requires_no_write(self):
        calls, report = [], {}
        def run(command):
            calls.append(command)
            return info(UNIT)
        bt.provision(0, UNIT, run, report, lambda: None)
        self.assertFalse(report['address_write_attempted'])
        self.assertTrue(all(c[-1] == 'info' for c in calls))

    def test_unsafe_or_wrong_adapter_is_refused_before_address_write(self):
        for raw in [info(settings='powered br/edr'), info(settings='advertising'),
                    info().replace('manufacturer 29', 'manufacturer 15'), info().replace('hci0:', 'hci1:'),
                    info().replace('public-address', 'static-address'),
                    '\n'.join(line for line in info().splitlines() if not line.startswith('hci0:')),
                    '\n'.join(line for line in info().splitlines() if 'addr ' not in line)]:
            with self.subTest(info=raw):
                calls = []
                def run(command):
                    calls.append(command)
                    return raw
                with self.assertRaises(ValueError):
                    bt.provision(0, UNIT, run, {}, lambda: None)
                self.assertEqual(len(calls), 1)

    def test_reconfiguration_gap_is_tolerated_but_wrong_readback_never_passes(self):
        responses = iter([info(), '', 'Invalid index', info(UNIT)])
        def run(command):
            return next(responses) if command[-1] == 'info' else ''
        report = {}
        with patch.object(bt.time, 'sleep'):
            bt.provision(0, UNIT, run, report, lambda: None)
        self.assertEqual(report['after']['address'], UNIT)
        with self.assertRaisesRegex(RuntimeError, 'readback'):
            bt.provision(0, UNIT, lambda _: info(), {}, lambda: None, seconds=0)
        calls, report = [], {}
        def powered(command):
            calls.append(command)
            return info(UNIT, 'powered') if len(calls) > 2 else info()
        with self.assertRaisesRegex(RuntimeError, 'restoration incomplete.*unpowered'):
            bt.provision(0, UNIT, powered, report, lambda: None)
        self.assertEqual(report['rollback']['status'], 'failed')
        self.assertEqual([c for c in calls if c[-2] == 'public-addr'],
                         [['btmgmt', '--index', '0', 'public-addr', UNIT]])

    def test_failed_address_update_restores_and_verifies_previous_address(self):
        original = '00:03:7f:12:2b:b0'
        for fault in ('wrong_readback', 'read_timeout', 'write_timeout'):
            with self.subTest(fault=fault):
                calls, report = [], {}
                current, injected = original, False

                def run(command):
                    nonlocal current, injected
                    calls.append(command)
                    if command[-2] == 'public-addr':
                        current = command[-1]
                        if current == UNIT and fault == 'write_timeout':
                            raise subprocess.TimeoutExpired(command, 20)
                        return ''
                    if current == UNIT and not injected:
                        injected = True
                        if fault == 'read_timeout':
                            raise subprocess.TimeoutExpired(command, 20)
                        if fault == 'wrong_readback':
                            return info(original)
                    return info(current)

                expected = RuntimeError if fault == 'wrong_readback' else subprocess.TimeoutExpired
                with self.assertRaises(expected):
                    bt.provision(0, UNIT, run, report, lambda: None, seconds=0)
                self.assertEqual(current, original)
                self.assertEqual([c[-1] for c in calls if c[-2] == 'public-addr'], [UNIT, original])
                self.assertEqual(report['rollback']['status'], 'restored')
                self.assertEqual(report['rollback']['after']['address'], original)
                self.assertNotIn('after', report)

    def test_failed_restoration_is_reported_and_never_crosses_boots(self):
        for fault in ('restore_write', 'restore_readback', 'boot_changed'):
            with self.subTest(fault=fault):
                calls, report, checks = [], {}, []
                current, restore_started = '00:03:7f:12:2b:b0', False

                def run(command):
                    nonlocal current, restore_started
                    calls.append(command)
                    if command[-2] == 'public-addr':
                        if command[-1] == UNIT:
                            current = UNIT
                            raise subprocess.TimeoutExpired(command, 20)
                        restore_started = True
                        if fault == 'restore_write':
                            raise RuntimeError('fixture restore write failed')
                        current = command[-1]
                        return ''
                    return info(UNIT if restore_started and fault == 'restore_readback' else current)

                def check_boot():
                    checks.append(True)
                    if fault == 'boot_changed' and len(checks) >= 3:
                        raise ValueError('fixture boot changed')

                with self.assertRaisesRegex(RuntimeError, 'restoration incomplete') as failure:
                    bt.provision(0, UNIT, run, report, check_boot, seconds=0)
                self.assertIsInstance(failure.exception.__cause__, subprocess.TimeoutExpired)
                self.assertEqual(report['rollback']['status'], 'failed')
                if fault == 'boot_changed':
                    self.assertEqual([c[-1] for c in calls if c[-2] == 'public-addr'], [UNIT])

    def test_restoration_waits_for_adapter_reconfiguration_gap(self):
        original = '00:03:7f:12:2b:b0'
        calls, report = [], {}
        current, gap = original, False
        def run(command):
            nonlocal current, gap
            calls.append(command)
            if command[-2] == 'public-addr':
                current = command[-1]
                if current == UNIT:
                    raise subprocess.TimeoutExpired(command, 20)
                return ''
            if current == UNIT and not gap:
                gap = True
                raise bt.AdapterUnavailable('fixture reconfiguration gap')
            return info(current)
        with patch.object(bt.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.TimeoutExpired):
                bt.provision(0, UNIT, run, report, lambda: None)
        sleep.assert_called_once_with(.2)
        self.assertEqual(current, original)
        self.assertEqual(report['rollback']['status'], 'restored')

    def test_unchanged_address_failure_does_not_attempt_restoration(self):
        calls, report = [], {}
        def run(command):
            calls.append(command)
            if len(calls) > 1:
                raise subprocess.TimeoutExpired(command, 20)
            return info(UNIT)
        with self.assertRaises(subprocess.TimeoutExpired):
            bt.provision(0, UNIT, run, report, lambda: None)
        self.assertFalse(report['address_write_attempted'])
        self.assertNotIn('rollback', report)
        self.assertTrue(all(c[-1] == 'info' for c in calls))

    def test_identity_receipt_rejects_other_units_placeholders_and_public_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'identity.json'
            record = {'status': 'stock-offline-identities-verified', 'fingerprint': bt.FINGERPRINT,
                      'bluetooth_hal_sha256': bt.HAL_SHA256,
                      'identity': {'boot_serial': 'fixture', 'bluetooth_address': UNIT}}
            path.write_text(json.dumps(record));path.chmod(0o600)
            self.assertEqual(bt.load_identity(path, 'fixture')[0], UNIT)
            with self.assertRaisesRegex(ValueError, 'boot serial'):
                bt.load_identity(path, 'another')
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'private'):
                bt.load_identity(path, 'fixture')
            path.chmod(0o600)
            for address in ['00:00:00:00:00:00', '00:03:7f:12:2b:b0', '01:12:34:56:78:90', 'bad']:
                record['identity']['bluetooth_address'] = address
                path.write_text(json.dumps(record))
                with self.subTest(address=address), self.assertRaises(ValueError):
                    bt.load_identity(path, 'fixture')

    def test_stock_collection_binds_stable_native_boot_serial_without_setters(self):
        for changed in [False, True]:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'identity.json'
                calls, serial_reads = [], []
                def adb(command, **kwargs):
                    import shlex
                    args = shlex.split(command[-1]);calls.append(args)
                    if args == ['getprop', 'ro.boot.serialno']:
                        serial_reads.append(True)
                        value = 'different' if changed and len(serial_reads) == 2 else 'fixtureboot'
                    elif args[0] == 'getprop':
                        value = {'ro.serialno': 'fixture', 'ro.build.fingerprint': collector.FINGERPRINT}[args[1]]
                    elif args == ['cat', '/proc/sys/kernel/random/boot_id']:value = BOOT
                    elif args[-1].endswith('addr_assign_type'):value = '0'
                    elif args[-1].endswith('/address'):value = 'a0:12:34:56:78:92'
                    elif args[0] == 'sha256sum':value = collector.HAL_SHA256+'  file'
                    elif args[:3] == ['settings', 'get', 'global']:value = '0'
                    elif args[0] == 'settings':value = UNIT
                    elif args[0] == 'dumpsys':value = 'enabled: false\nstate: OFF\naddress: '+UNIT
                    elif args[0] == 'ip':value = ''
                    else:raise AssertionError(args)
                    return subprocess.CompletedProcess(command, 0, value+'\n', '')
                with patch.object(sys, 'argv', ['collector', '--serial', 'fixture', '--output', str(path)]), \
                        patch.object(collector.subprocess, 'run', side_effect=adb):
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            collector.main()
                        self.assertFalse(path.exists())
                    else:
                        collector.main()
                        self.assertEqual(json.loads(path.read_text())['identity']['boot_serial'], 'fixtureboot')
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertTrue(all(c[0] in ('getprop','cat','sha256sum','settings','ip','dumpsys') for c in calls))
                self.assertTrue(all(c[1] == 'get' for c in calls if c[0] == 'settings'))


if __name__ == '__main__':
    unittest.main()
