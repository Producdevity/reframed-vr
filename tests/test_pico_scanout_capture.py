import importlib.util
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch


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


class PausedCapture(unittest.TestCase):
    def exercise(self, frames, resume_failure=False, watchdog_elapsed=False):
        calls = []

        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:2] == ['systemctl', 'show']:
                if arguments[2].endswith('.timer'):
                    checks = sum(c[:2] == ['systemctl', 'show'] and c[2].endswith('.timer') for c in calls)
                    value = ('ActiveState=active\nSubState=elapsed\nLastTriggerUSecMonotonic=123\n'
                             if watchdog_elapsed and checks > 1 else
                             'ActiveState=active\nSubState=waiting\nLastTriggerUSecMonotonic=0\n')
                    return subprocess.CompletedProcess(arguments, 0, value, '')
                return subprocess.CompletedProcess(arguments, 0, 'ActiveState=active\nMainPID=42\n', '')
            code = int(resume_failure and '--signal=CONT' in arguments and arguments[0] == 'systemctl')
            return subprocess.CompletedProcess(arguments, code, '', '')

        metadata = {'active': ACTIVE, 'copy_started': 1., 'copy_ended': 2.}
        captures = [data if isinstance(data, Exception) else (data, 'state', dict(metadata)) for data in frames]
        with patch.object(capture.subprocess, 'run', side_effect=run), \
                patch.object(capture.time, 'sleep'), \
                patch.object(capture, 'capture', side_effect=captures):
            try:
                result = capture.capture_paused('pico-steamvr-compositor-test')
                return result, calls
            except (ValueError, RuntimeError, OSError) as error:
                return error, calls

    def test_watchdog_precedes_stop_and_matching_reads_resume(self):
        result, calls = self.exercise([b'abc', b'abc'])
        self.assertTrue(result[2]['stable_readback_verified'])
        self.assertEqual(result[2]['compositor_pause']['matching_readbacks'], 2)
        armed = next(i for i, c in enumerate(calls) if c[0] == 'systemd-run')
        stopped = next(i for i, c in enumerate(calls) if '--signal=STOP' in c)
        resumed = next(i for i, c in enumerate(calls) if '--signal=CONT' in c and c[0] == 'systemctl')
        self.assertLess(armed, stopped)
        self.assertLess(stopped, resumed)
        self.assertEqual(calls[-1][:2], ['systemctl', 'stop'])

    def test_changed_pixels_are_rejected_and_compositor_resumes(self):
        result, calls = self.exercise([b'abc', b'abd'])
        self.assertIsInstance(result, ValueError)
        self.assertIn('Framebuffer changed', str(result))
        self.assertTrue(any('--signal=CONT' in c and c[0] == 'systemctl' for c in calls))

    def test_failed_resume_keeps_watchdog_armed(self):
        result, calls = self.exercise([b'abc', b'abc'], resume_failure=True)
        self.assertIsInstance(result, RuntimeError)
        self.assertFalse(any(c[:2] == ['systemctl', 'stop'] for c in calls))

    def test_readback_exception_still_resumes(self):
        result, calls = self.exercise([OSError('readback failed')])
        self.assertIsInstance(result, OSError)
        self.assertTrue(any('--signal=CONT' in c and c[0] == 'systemctl' for c in calls))

    def test_elapsed_timer_is_rejected_even_when_still_active(self):
        result, calls = self.exercise([b'abc', b'abc'], watchdog_elapsed=True)
        self.assertIsInstance(result, ValueError)
        self.assertIn('already fired', str(result))
        self.assertTrue(any('--signal=CONT' in c and c[0] == 'systemctl' for c in calls))

    def test_other_services_are_refused_before_any_action(self):
        with patch.object(capture.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                capture.capture_paused('sshd.service')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
