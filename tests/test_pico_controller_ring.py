from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PicoControllerRingTests(unittest.TestCase):
    def test_motion_history_survives_wrap_duplicates_and_torn_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'controller-motion-ring'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/pico-controller-motion-ring.c'),
                            str(ROOT / 'src/pico-controller-ring.c'), str(ROOT / 'src/pico-controller.c'),
                            '-o', str(binary)], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_CONTROLLER_MOTION_RING_PASS', result.stdout)

    def test_snapshot_ordering_and_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'controller-ring'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/pico-controller-ring.c'),
                            str(ROOT / 'src/pico-controller-ring.c'), str(ROOT / 'src/pico-controller.c'),
                            '-o', str(binary)], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_CONTROLLER_RING_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
