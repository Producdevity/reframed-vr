import importlib.util
import math
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pico_config', ROOT / 'tools/pico-controller-config.py')
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class PicoControllerConfigTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.replies = {}
        self.boot = '12345678-1234-1234-1234-123456789abc'

    def read(self, *command):
        self.commands.append(command)
        if command in self.replies:
            reply = self.replies[command]
            return reply.pop(0) if isinstance(reply, list) else reply
        known = {
            ('getprop', 'ro.build.fingerprint'): CONFIG.FINGERPRINT,
            ('getprop', 'ro.product.device'): 'PICOA7H10',
            ('sha256sum', CONFIG.LIBRARY): CONFIG.LIBRARY_SHA256 + '  ' + CONFIG.LIBRARY,
            ('sha256sum', CONFIG.CONFIG_APK): CONFIG.CONFIG_SHA256 + '  ' + CONFIG.CONFIG_APK,
            ('cat', '/proc/sys/kernel/random/boot_id'): self.boot,
            ('service', 'call', 'PicoStation-new', '76'): "Result: Parcel(00000000 00000002   '........')",
            ('service', 'call', 'PicoStation-new', '74'): "Result: Parcel(00000000 00000001   '........')",
        }
        for key, value in [('sys_controller_chip', '31'), ('sys_controller_prototype', '32')]:
            known[('service', 'call', 'ConfigurationService', '3', 's16', 'com.pvr.configuration',
                   'i32', '0', 's16', key, 'i32', '-1')] = \
                f"Result: Parcel(00000000 00000001 000000{value}  '........?...')"
        self.assertIn(command, known, 'Collector attempted an unverified command')
        return known[command]

    def test_verified_snapshot(self):
        report = CONFIG.collect(self.read)
        self.assertEqual(report['controller'], {'mcu_type': 1, 'radio_type': 2, 'touch_supported': True})
        self.assertEqual(sum(command[:2] == ('service', 'call') for command in self.commands), 8)

    def test_interface_changes_refuse_before_binder(self):
        for command in [('getprop', 'ro.build.fingerprint'), ('getprop', 'ro.product.device'),
                        ('sha256sum', CONFIG.LIBRARY), ('sha256sum', CONFIG.CONFIG_APK)]:
            with self.subTest(command=command):
                self.replies = {command: 'different'}
                self.commands.clear()
                with self.assertRaises(ValueError):
                    CONFIG.collect(self.read)
                self.assertFalse(any(c[0] == 'service' for c in self.commands))

    def test_getter_error_and_disagreement(self):
        for text in ["Result: Parcel(ffffffff 00000002 '........')", 'Permission denied',
                     "Result: Parcel(00000000 00000000 '........')",
                     "Result: Parcel(00000000 00000001 '........')"]:
            self.replies = {('service', 'call', 'PicoStation-new', '76'): text}
            with self.subTest(text=text), self.assertRaises(ValueError):
                CONFIG.collect(self.read)

    def test_reboot_and_changed_settings(self):
        for command, replies in [
            (('cat', '/proc/sys/kernel/random/boot_id'), [self.boot, '87654321-1234-1234-1234-123456789abc']),
            (('getprop', 'ro.build.fingerprint'), [CONFIG.FINGERPRINT, 'changed']),
            (('service', 'call', 'PicoStation-new', '74'),
             ["Result: Parcel(00000000 00000001 '..')", "Result: Parcel(00000000 00000000 '..')"]),
        ]:
            self.replies = {command: replies}
            with self.subTest(command=command), self.assertRaises(ValueError):
                CONFIG.collect(self.read)

    def test_string_framing(self):
        for text in ["Result: Parcel(00000000 00000000 00000031 '..')",
                     "Result: Parcel(00000000 00000001 00310031 '..')",
                     "Result: Parcel(00000000 00000001 00000030 '..')",
                     "Result: Parcel(00000000 00000001 00000031 00000000 '..')",
                     "Result: Parcel(00000000 00000001 00000031 '..') extra"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                CONFIG.digit(text)


def status_reply(raw=None, header=(0, 0, 1, 18)):
    import struct
    if raw is None:
        raw = bytearray(96)
        struct.pack_into('<I', raw, 0, 1)
        raw[15], raw[42], raw[43] = ord('0'), 1, 0
        raw[48 + 15], raw[48 + 42], raw[48 + 43] = ord('1'), 0, 1
    words = (*header, *struct.unpack('<24I', raw))
    return 'Result: Parcel(\n' + '\n'.join(
        f"  0x{i * 4:08x}: " + ''.join(f'{w:08x} ' for w in words[i:i + 4]) + "'................'"
        for i in range(0, len(words), 4)) + '\n)'


class PicoControllerMotionConfigTests(unittest.TestCase):
    read = PicoControllerConfigTests.read

    def setUp(self):
        PicoControllerConfigTests.setUp(self)
        self.replies.update({('sha256sum', p): f'{h}  {p}' for p, h in CONFIG.MOTION_LIBRARIES})
        self.replies[('service', 'call', 'PicoStation-new', '19')] = status_reply()

    def test_status_snapshot(self):
        report = CONFIG.collect(self.read, include_motion_status=True)
        left = report['motion_status'][0]['settings']['left']
        self.assertEqual(left, {'connected': True, 'revision_byte': 48,
                                'double_scale_byte': 1, 'axis_reversal_bypass_byte': 0})
        self.assertFalse(report['motion_status'][0]['settings']['right']['connected'])
        self.assertEqual(report['motion_status'][0], report['motion_status'][1])
        self.assertEqual(len(report['motion_status'][0]['raw_status_hex']), 192)
        self.assertEqual(self.commands.count(('service', 'call', 'PicoStation-new', '19')), 2)

    def test_inline_parcel_terminator(self):
        separate = status_reply()
        inline = separate.removesuffix('\n)') + ')'
        self.assertEqual(CONFIG.motion_status(inline), CONFIG.motion_status(separate))
        self.replies[('service', 'call', 'PicoStation-new', '19')] = inline
        report = CONFIG.collect(self.read, include_motion_status=True)
        self.assertEqual(report['motion_status'][0], report['motion_status'][1])
        for malformed in (inline + ')', inline + '\n)', inline + 'extra',
                          inline.replace('0x00000060', '0x00000050')):
            with self.subTest(reply=malformed), self.assertRaises(ValueError):
                CONFIG.motion_status(malformed)

    def test_status_not_requested_by_default(self):
        report = CONFIG.collect(self.read)
        self.assertNotIn('motion_status', report)
        self.assertNotIn(('service', 'call', 'PicoStation-new', '19'), self.commands)
        for path, _ in CONFIG.MOTION_LIBRARIES:
            self.assertNotIn(('sha256sum', path), self.commands)

    def test_motion_hash_changes_refuse_before_binder(self):
        for path, _ in CONFIG.MOTION_LIBRARIES:
            with self.subTest(path=path):
                self.setUp()
                self.replies[('sha256sum', path)] = 'different'
                with self.assertRaises(ValueError):
                    CONFIG.collect(self.read, include_motion_status=True)
                self.assertFalse(any(c[0] == 'service' for c in self.commands))

    def test_status_connection_and_configuration_changes(self):
        base = bytes.fromhex(CONFIG.motion_status(status_reply())['raw_status_hex'])
        for offset in (0, 15, 42, 43, 48, 63, 90, 91):
            with self.subTest(offset=offset):
                changed = bytearray(base)
                changed[offset] ^= 1
                self.replies[('service', 'call', 'PicoStation-new', '19')] = [status_reply(base), status_reply(changed)]
                with self.assertRaisesRegex(ValueError, 'changed while reading'):
                    CONFIG.collect(self.read, include_motion_status=True)

    def test_preserves_other_live_fields(self):
        base = bytes.fromhex(CONFIG.motion_status(status_reply())['raw_status_hex'])
        changed = bytearray(base)
        changed[20] = 255
        self.replies[('service', 'call', 'PicoStation-new', '19')] = [status_reply(base), status_reply(changed)]
        report = CONFIG.collect(self.read, include_motion_status=True)
        self.assertEqual(report['motion_status'][1]['raw_status_hex'], changed.hex())
        self.assertNotEqual(report['motion_status'][0]['raw_status_hex'], changed.hex())

    def test_status_exceptions_and_null_payload(self):
        for header in ((1, 0, 1, 18), (0, 0xffffffff, 1, 18), (0, 0, 0, 18), (0, 0, 2, 18), (0, 0, 1, 17)):
            with self.subTest(header=header), self.assertRaises(ValueError):
                CONFIG.motion_status(status_reply(header=header))

    def test_status_unknown_connection(self):
        for offset in (0, 48):
            for value in (2, 255):
                raw = bytearray(96)
                raw[offset] = value
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    CONFIG.motion_status(status_reply(raw))

    def test_status_framing(self):
        valid = status_reply()
        cases = [valid + 'extra', valid.replace('0x00000010', '0x00000000'),
                 valid.replace('0x00000010', '0x00000020'),
                 valid.replace('00000012 ', '00000012 00000000 ', 1),
                 valid.replace('00000012 ', '', 1), '\n'.join(valid.splitlines()[:-2]) + '\n)',
                 valid.replace('Result: Parcel(', 'Result: Parcel(object)'),
                 valid.replace("'................'", "'fake'\n0x00000000: 00000000", 1)]
        for reply in cases:
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                CONFIG.motion_status(reply)

    def calibration_replies(self):
        for path, digest in CONFIG.MOTION_LIBRARIES:
            self.replies[('sha256sum', path)] = digest + '  ' + path
        self.replies[('service', 'call', 'PicoStation-new', '19')] = status_reply()
        self.replies[('service', 'call', 'PicoStation-new', '12', 'i32', '1')] = calibration_reply()

    def test_complete_cached_calibration(self):
        self.calibration_replies()
        report = CONFIG.collect(self.read, calibration_hand='left')
        result = report['calibration']
        self.assertEqual(result['source'], 'stock_service_cache')
        self.assertEqual(result['hand'], 'left')
        self.assertEqual(result['generation'], 0)
        self.assertEqual({k: len(v) for k, v in result['sections'].items()},
                         {'imu': 24, 'ir': 48, 'imu_ir': 7})
        self.assertEqual(len(result['raw_cv3_hex']), 1320)
        self.assertEqual(self.commands.count(('service', 'call', 'PicoStation-new', '12', 'i32', '1')), 2)
        inline = calibration_reply().removesuffix('\n)') + ')'
        self.assertEqual(CONFIG.calibration(inline), CONFIG.calibration(calibration_reply()))

    def test_calibration_flags_counts_generation_and_finiteness(self):
        raw = calibration_raw()
        for offset, value in [(0, 1), (4, 0), (8, 48), (204, 0), (208, 60),
                              (596, 0), (600, -1)]:
            changed = bytearray(raw)
            struct.pack_into('<i', changed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                CONFIG.calibration(calibration_reply(changed))
        for offset in (12, 212, 604):
            for value in (math.nan, math.inf, -math.inf):
                changed = bytearray(raw)
                struct.pack_into('<f', changed, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    CONFIG.calibration(calibration_reply(changed))

    def test_calibration_failed_getter_and_framing(self):
        valid = calibration_reply()
        for header in ((1, 0, 1, 14), (0, 1, 1, 14), (0, 0, 0, 14), (0, 0, 1, 18)):
            with self.subTest(header=header), self.assertRaises(ValueError):
                CONFIG.calibration(calibration_reply(header=header))
        for text in (valid + ')', valid + 'extra', valid.replace('0x00000010', '0x00000000'),
                     valid.replace('0000000e ', '', 1),
                     valid.replace("'................'", "'fake'\n0x00000000: 00000000", 1),
                     '\n'.join(valid.splitlines()[:-2]) + '\n)'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                CONFIG.calibration(text)

    def test_calibration_cache_or_station_change_refuses(self):
        self.calibration_replies()
        changed = calibration_raw()
        struct.pack_into('<f', changed, 12, 2.0)
        key = ('service', 'call', 'PicoStation-new', '12', 'i32', '1')
        self.replies[key] = [calibration_reply(), calibration_reply(changed)]
        with self.assertRaisesRegex(ValueError, 'calibration changed'):
            CONFIG.collect(self.read, calibration_hand='left')
        self.calibration_replies()
        status = bytearray.fromhex(CONFIG.motion_status(status_reply())['raw_status_hex'])
        status[20] ^= 1
        self.replies[('service', 'call', 'PicoStation-new', '19')] = [status_reply(), status_reply(status)]
        with self.assertRaisesRegex(ValueError, 'station record changed'):
            CONFIG.collect(self.read, calibration_hand='left')

    def test_calibration_explicit_hand_only(self):
        with self.assertRaises(ValueError):
            CONFIG.collect(self.read, calibration_hand='both')
        self.assertEqual(self.commands, [])
        self.calibration_replies()
        self.replies[('service', 'call', 'PicoStation-new', '12', 'i32', '2')] = calibration_reply()
        self.assertEqual(CONFIG.collect(self.read, calibration_hand='right')['calibration']['hand'], 'right')
        self.assertNotIn(('service', 'call', 'PicoStation-new', '12', 'i32', '1'), self.commands)


def calibration_raw():
    raw = bytearray(660)
    for offset, count in ((4, 24), (204, 48), (596, 7)):
        struct.pack_into('<ii', raw, offset, 1, count)
        struct.pack_into('<' + str(count) + 'f', raw, offset + 8, *([1.0] * count))
    return raw


def calibration_reply(raw=None, header=(0, 0, 1, 14)):
    raw = calibration_raw() if raw is None else raw
    words = list(header) + list(struct.unpack('<165I', raw))
    lines = ['Result: Parcel(']
    for start in range(0, len(words), 4):
        lines.append('  0x%08x: %s  %r' %
                     (start * 4, ' '.join('%08x' % v for v in words[start:start + 4]), '................'))
    return '\n'.join(lines + [')'])
