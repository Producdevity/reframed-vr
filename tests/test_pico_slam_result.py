from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoSlamResultTests(unittest.TestCase):
    def test_vendor_result_layout(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-slam-result'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                str(root / 'tests/pico-slam-result.c'), str(root / 'src/pico-slam-result.c'),
                '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_SLAM_RESULT_PASS', result.stdout)
