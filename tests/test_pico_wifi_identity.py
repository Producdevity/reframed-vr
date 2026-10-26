import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_identity', ROOT/'tools/pico-wifi-identity.py')
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)
UNIT = 'a0:12:34:56:78:90'
ORIGINAL = '00:03:7f:12:2b:b0'


class Backend:
    def __init__(self, address=ORIGINAL):
        self.state = {'address': address, 'flags': 4098, 'ifindex': 7,
                      'device': '/sys/devices/pci/qca6390', 'driver': '/sys/bus/pci/drivers/cnss_pci'}
        self.writes = []

    def snapshot(self):
        return self.state.copy()

    def set_address(self, address):
        self.writes.append(address)
        self.state['address'] = address


class WifiIdentityTests(unittest.TestCase):
    def test_changes_address_and_preserves_interface_state(self):
        interface, report, checks = Backend(), {}, []
        before = interface.snapshot()
        wifi.provision(UNIT, interface, report, lambda: checks.append(True))
        self.assertEqual(interface.writes, [UNIT])
        self.assertEqual(report['before'], before)
        self.assertEqual(report['after'], before | {'address': UNIT})
        self.assertTrue(report['address_write_attempted'])
        self.assertEqual(len(checks), 3)

    def test_matching_identity_requires_no_write(self):
        interface, report = Backend(UNIT), {}
        wifi.provision(UNIT, interface, report, lambda: None)
        self.assertFalse(report['address_write_attempted'])
        self.assertEqual(interface.writes, [])

    def test_failed_write_or_readback_restores_original(self):
        for fault in ('write_applied_then_error', 'wrong_readback', 'read_error', 'interrupted'):
            with self.subTest(fault=fault):
                interface, report = Backend(), {}
                write, read = interface.set_address, interface.snapshot
                injected = False
                def faulty_write(address):
                    write(address)
                    if address == UNIT and fault == 'write_applied_then_error':
                        raise OSError('write failure after mutation')
                    if address == UNIT and fault == 'interrupted':
                        raise InterruptedError('cancelled after mutation')
                def faulty_read():
                    nonlocal injected
                    if interface.writes == [UNIT] and not injected:
                        injected = True
                        if fault == 'wrong_readback':return read() | {'address': 'a0:12:34:56:78:91'}
                        if fault == 'read_error':raise OSError('read failure')
                    return read()
                interface.set_address, interface.snapshot = faulty_write, faulty_read
                with self.assertRaises((OSError, RuntimeError)):
                    wifi.provision(UNIT, interface, report, lambda: None)
                self.assertEqual(interface.writes, [UNIT, ORIGINAL])
                self.assertEqual(report['rollback']['status'], 'restored')
                self.assertEqual(interface.state['address'], ORIGINAL)
                self.assertNotIn('after', report)

    def test_rollback_refuses_changed_boot_interface_or_flags(self):
        for fault in ('boot', 'ifindex', 'device', 'driver', 'flags', 'unsafe_state'):
            with self.subTest(fault=fault):
                interface, report, calls = Backend(), {}, []
                read = interface.snapshot
                def check():
                    calls.append(True)
                    if fault == 'boot' and interface.writes:raise ValueError('boot changed')
                def snapshot():
                    if interface.writes:
                        if fault == 'unsafe_state':raise ValueError('interface is up')
                        if fault in ('ifindex', 'flags'):return read() | {fault: read()[fault]+1}
                        if fault == 'device':return read() | {'device': '/sys/devices/replacement'}
                        if fault == 'driver':return read() | {'driver': '/sys/bus/pci/drivers/replacement'}
                    return read()
                interface.snapshot = snapshot
                with self.assertRaisesRegex(RuntimeError, 'restoration incomplete'):
                    wifi.provision(UNIT, interface, report, check)
                self.assertEqual(interface.writes, [UNIT])
                self.assertEqual(report['rollback']['status'], 'failed')

    def test_failed_restoration_never_claims_success(self):
        interface, report = Backend(), {}
        write = interface.set_address
        def failed(address):
            write(address)
            raise OSError('failed write')
        interface.set_address = failed
        with self.assertRaisesRegex(RuntimeError, 'restoration incomplete'):
            wifi.provision(UNIT, interface, report, lambda: None)
        self.assertEqual(report['rollback']['status'], 'failed')
        self.assertNotIn('after', report)

    def test_private_receipt_binds_unit_and_rejects_bad_addresses_and_files(self):
        record = {'status': 'stock-offline-identities-verified', 'fingerprint': wifi.identity.FINGERPRINT,
                  'bluetooth_hal_sha256': wifi.identity.HAL_SHA256,
                  'identity': {'boot_serial': 'unit123', 'wifi_address': UNIT}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'identity.json'
            path.write_text(json.dumps(record));path.chmod(0o600)
            address, digest = wifi.load_identity(path, 'unit123')
            self.assertEqual(address, UNIT)
            self.assertEqual(len(digest), 64)
            with self.assertRaises(ValueError):wifi.load_identity(path, 'another')
            path.chmod(0o644)
            with self.assertRaises(ValueError):wifi.load_identity(path, 'unit123')
            path.chmod(0o600)
            for value in ('00:00:00:00:00:00', '01:12:34:56:78:90', ORIGINAL, 'invalid'):
                bad = copy.deepcopy(record);bad['identity']['wifi_address'] = value
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):wifi.load_identity(path, 'unit123')
            link = Path(tmp)/'link';link.symlink_to(path)
            with self.assertRaises(OSError):wifi.load_identity(link, 'unit123')
            path.write_bytes(b' ' * 65537)
            with self.assertRaises(ValueError):wifi.load_identity(path, 'unit123')

    def test_actual_ioctl_uses_complete_arm64_ifreq(self):
        with patch.object(wifi.socket, 'socket') as socket, patch.object(wifi.fcntl, 'ioctl') as ioctl:
            interface = wifi.Interface('wlan0', lambda _: '')
            interface.set_address(UNIT)
            args = ioctl.call_args.args
            self.assertEqual(args[0], socket.return_value)
            self.assertEqual(args[1], 0x8924)
            self.assertEqual(len(args[2]), 40)
            name, family, address = struct.unpack('16sH6s16x', args[2])
            self.assertEqual((name.rstrip(b'\0'), family, address), (b'wlan0', 1, bytes.fromhex(UNIT.replace(':',''))))
            interface.close();socket.return_value.close.assert_called_once()

    def test_snapshot_requires_down_managed_disconnected_qca6390(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(wifi.socket, 'socket'), \
                patch.object(wifi.fcntl, 'ioctl') as ioctl:
            root = Path(tmp)
            device = root/'devices/pci/qca6390';device.mkdir(parents=True)
            module = root/'modules/wlan';module.mkdir(parents=True)
            driver = root/'drivers/cnss_pci';driver.mkdir(parents=True)
            (device/'driver').symlink_to(driver)
            (device/'vendor').write_text('0x17cb\n');(device/'device').write_text('0x1101\n')
            net = root/'net/wlan0';net.mkdir(parents=True);(net/'device').symlink_to(device)
            (net/'address').write_text(ORIGINAL+'\n');(net/'ifindex').write_text('7\n')
            info = 'Interface wlan0\n\tifindex 7\n\ttype managed\n'
            response = {'info': info, 'link': 'Not connected.\n'}
            interface = wifi.Interface('wlan0', lambda command: response[command[-1]])
            interface.path = net
            ioctl.return_value = struct.pack('16sH22x', b'wlan0', 4098)
            module_patch = patch.object(wifi, 'WLAN_MODULE', module)
            self.addCleanup(module_patch.stop);module_patch.start()
            value = interface.snapshot()
            self.assertEqual(value['address'], ORIGINAL)
            self.assertEqual(value['ifindex'], 7)
            for fault in ('up', 'p2p', 'connected', 'wrong_vendor', 'wrong_chip', 'wrong_driver'):
                with self.subTest(fault=fault):
                    ioctl.return_value = struct.pack('16sH22x', b'wlan0', 4099 if fault=='up' else 4098)
                    response.update(info=info.replace('managed','P2P-device') if fault=='p2p' else info,
                                    link='Connected to test\n' if fault=='connected' else 'Not connected.\n')
                    (device/'vendor').write_text('0x1234' if fault=='wrong_vendor' else '0x17cb')
                    (device/'device').write_text('0x5678' if fault=='wrong_chip' else '0x1101')
                    if fault=='wrong_driver':
                        (device/'driver').unlink();(root/'drivers/other').mkdir()
                        (device/'driver').symlink_to(root/'drivers/other')
                    with self.assertRaises(ValueError):interface.snapshot()
            self.assertTrue(all(call.args[1]==0x8913 for call in ioctl.call_args_list))
            interface.close()


if __name__ == '__main__':
    unittest.main()
