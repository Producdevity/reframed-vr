import importlib.util
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pico_stock_optics', Path(__file__).parents[1] / 'tools/read-pico-optics.py')
optics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(optics)


def response(data, status=0):
    data += struct.pack('<i', status)
    lines = ['Result: Parcel(']
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        words = struct.unpack('<' + 'I' * (len(block) // 4), block)
        lines.append(f'  0x{offset:08x}: ' + ' '.join(f'{v:08x}' for v in words) + " 'fixture'")
    return '\n'.join(lines) + ')\n'


def records():
    display = bytearray(96)
    for offset, value in [(8, 3664), (12, 1920), (28, 1), (32, 90)]:
        struct.pack_into('<I', display, offset, value)
    for offset, value in [(16, 773), (20, 773), (24, 72), (36, .12), (40, .063), (48, .003)]:
        struct.pack_into('<f', display, offset, value)
    lens = bytearray(128)
    coefficients = [1.] + [0.] * 19
    coefficients[14:18] = [.1, -.2, .3, -.4]
    struct.pack_into('<3fI24f', lens, 0, .06, 95, .04, 2, *coefficients, .01, .02, .03, .04)
    return bytes(display), bytes(lens)


class PicoStockOpticsTests(unittest.TestCase):
    def test_exact_getter_layouts(self):
        display, lens = records()
        self.assertEqual(optics.parcel(response(display), 96), display)
        self.assertEqual(optics.parcel(response(lens), 128), lens)
        d, l = optics.display_info(display), optics.lens_info(lens)
        self.assertEqual((d['width_pixels'], d['height_pixels'], d['orientation_degrees']), (3664, 1920, 90))
        self.assertEqual(d['service_refresh_hz'], 72)
        self.assertAlmostEqual(d['screen_gap_m'], .003)
        self.assertEqual(len(l['distortion_coefficients']), 20)
        for value, expected in zip(l['axis_offsets_mm'], [.1, -.2, .3, -.4]):
            self.assertAlmostEqual(value, expected)
        self.assertAlmostEqual(l['chromatic_aberration'][3], .04)

    def test_refuses_bad_parcel_and_getter_failures(self):
        display, _ = records()
        for text in [response(display, -1), response(display[:-4]), response(display + b'\0' * 4),
                     response(display).replace('0x00000010:', '0x00000020:'),
                     response(display).replace('00000e50', 'abcdefgh'), 'Permission Denial', 'Result: Parcel(\n)']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                optics.parcel(text, 96)

    def test_refuses_nonfinite_or_unsupported_optics(self):
        display, lens = records()
        for original, offset, fmt, value, parser in [(display, 32, '<I', 45, optics.display_info),
                (display, 8, '<I', 1920, optics.display_info), (display, 36, '<f', float('nan'), optics.display_info),
                (lens, 12, '<I', 3, optics.lens_info), (lens, 0, '<f', .2, optics.lens_info),
                (lens, 8, '<f', float('inf'), optics.lens_info), (lens, 60, '<f', float('nan'), optics.lens_info)]:
            data = bytearray(original)
            struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                parser(bytes(data))

    def test_collection_pins_identity_library_and_read_only_transactions(self):
        display, lens = records()
        replies = ['boot123', optics.FINGERPRINT, optics.CLIENT_SHA256 + '  /system/lib64/libpvrserviceclient.so',
                   '3\tpxrhmdservice: [android.Service.PxrHmdService]', response(display), response(lens), 'boot123']
        with patch.object(optics.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, v, '') for v in replies]) as run:
            result = optics.collect('adb', 'usb123', 'boot123')
        self.assertFalse(result['device_writes'])
        self.assertFalse(result['runtime_profile'])
        self.assertFalse(result['optical_alignment_verified'])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(all(c[:4] == ['adb', '-s', 'usb123', 'shell'] for c in commands))
        self.assertEqual([c[7] for c in commands if c[4:7] == ['service', 'call', 'pxrhmdservice']], ['4', '5'])

    def test_wrong_identity_refuses_before_getter(self):
        with patch.object(optics.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, 'wrong', ''),
                           subprocess.CompletedProcess([], 0, optics.FINGERPRINT, '')]) as run:
            with self.assertRaises(ValueError):
                optics.collect('adb', 'usb123', 'boot123')
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
