import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
                    info().replace('public-address', 'static-address')]:
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
        with self.assertRaisesRegex(ValueError, 'unpowered'):
            calls = iter([info(), '', info(UNIT, 'powered')])
            bt.provision(0, UNIT, lambda _: next(calls), {}, lambda: None)

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
