import importlib.util
from pathlib import Path
import struct
import unittest


spec = importlib.util.spec_from_file_location(
    'capture', Path(__file__).resolve().parents[1] / 'tools/capture-pico-scanout.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class PixelFormats(unittest.TestCase):
    def test_known_primary_colours(self):
        for format_name in capture.FORMATS:
            ten = format_name.endswith('30')
            maximum, shift = (1023, 10) if ten else (255, 8)
            red, blue = (2 * shift, 0) if format_name[1] == 'R' else (0, 2 * shift)
            for word, expected in [(maximum << red, (255, 0, 0)),
                                   (maximum << shift, (0, 255, 0)),
                                   (maximum << blue, (0, 0, 255)),
                                   (0xffffffff, (255, 255, 255)), (0, (0, 0, 0))]:
                with self.subTest(format=format_name, word=word):
                    self.assertEqual(capture.pixel_rgb(word, format_name), expected)

    def test_ten_bit_rounding_and_alpha(self):
        for prefix in ('X', 'A'):
            for order in ('R', 'B'):
                name = prefix + order + '30'
                for component, expected in [(1, 0), (2, 0), (3, 1), (511, 127), (512, 128), (1022, 255)]:
                    word = component | component << 10 | component << 20 | 3 << 30
                    self.assertEqual(capture.pixel_rgb(word, name), (expected,) * 3)

    def test_row_padding_and_little_endian_words(self):
        native = struct.pack('<III', 1023, 1023 << 10, 0xdeadbeef)
        native += struct.pack('<III', 1023 << 20, 0xffffffff, 0xdeadbeef)
        self.assertEqual(capture.decode_rgb(native, 2, 2, 12, 'XB30'),
                         bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]))

    def test_refuses_unknown_and_invalid_extents(self):
        with self.assertRaises(ValueError):
            capture.pixel_rgb(0, 'NV12')
        for width, height, pitch in [(0, 1, 4), (2, 1, 4), (1, 2, 4), (8193, 1, 32772)]:
            with self.subTest(width=width, height=height, pitch=pitch):
                with self.assertRaises(ValueError):
                    capture.decode_rgb(b'\0' * 4, width, height, pitch, 'XR24')


ACTIVE = [{'id': 109, 'fb': 235, 'crtc': 140}, {'id': 112, 'fb': 235, 'crtc': 140}]


def state():
    return ''.join(f'''plane[{plane}]: plane-6
\tcrtc=crtc-0
\tfb=235
\t\tformat=XB30 little-endian (0x30334258)
\t\tmodifier=0x0
\t\tsize=1920x3664
\t\tlayers:
\t\t\tpitch[0]=7680
\t\t\toffset[0]=0
\tcrtc-pos=960x3664+{x}+0
\tsrc-pos=960.000000x3664.000000+{x}.000000+0.000000
\trotation=1
''' for plane, x in [(109, 960), (112, 0)]) + 'crtc[140]: crtc-0\n\tactive=1\n'


class AtomicLayout(unittest.TestCase):
    def test_actual_ten_bit_layout(self):
        layout = capture.plane_layout(state(), ACTIVE)
        self.assertEqual(layout['fourcc'], 'XB30')
        self.assertEqual(layout['size'], [1920, 3664])
        self.assertEqual(layout['pitch'], 7680)

    def test_rejects_races_and_unsupported_layouts(self):
        replacements = [('fb=235', 'fb=236'), ('modifier=0x0', 'modifier=0x1'),
                        ('offset[0]=0', 'offset[0]=4096'), ('pitch[0]=7680', 'pitch[0]=7676'),
                        ('XB30', 'XR24'), ('0x30334258', '0x34325258'),
                        ('size=1920x3664', 'size=1920x3663'), ('rotation=1', 'rotation=2'),
                        ('src-pos=960.000000', 'src-pos=959.000000'),
                        ('crtc-pos=960x3664+960+0', 'crtc-pos=960x3664+0+0')]
        for old, new in replacements:
            with self.subTest(old=old, new=new):
                with self.assertRaises(ValueError):
                    capture.plane_layout(state().replace(old, new, 1), ACTIVE)
        with self.assertRaises(ValueError):
            capture.plane_layout(state() + state(), ACTIVE)


if __name__ == '__main__':
    unittest.main()
