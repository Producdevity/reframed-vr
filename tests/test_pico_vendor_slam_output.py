from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoVendorSlamOutputTests(unittest.TestCase):
    def test_serialized_callbacks_and_shutdown(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-vendor-slam-output'
            sources = ['tests/pico-vendor-slam-output.c', 'src/pico-vendor-slam-output.c',
                       'src/pico-slam-channel.c', 'src/pico-slam-result.c', 'src/pico-slam-pose.c']
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                *(str(root / name) for name in sources), '-pthread', '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_VENDOR_SLAM_OUTPUT_PASS', result.stdout)
