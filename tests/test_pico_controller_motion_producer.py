from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerMotionProducerTests(unittest.TestCase):
    def test_snapshot_conversion_channel_and_permanent_lifecycle_failure(self):
        root = Path(__file__).resolve().parents[1]
        units = ['pico-controller', 'pico-controller-ring', 'pico-controller-motion',
                 'pico-controller-motion-channel', 'pico-controller-motion-producer']
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'motion-producer'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-motion-producer.c'),
                *(str(root / 'src' / (unit + '.c')) for unit in units), '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_MOTION_PRODUCER_PASS', result.stdout)
