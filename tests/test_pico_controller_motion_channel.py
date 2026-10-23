from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerMotionChannelTests(unittest.TestCase):
    def test_cross_process_history_overrun_freshness_and_stop(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'motion-channel'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-motion-channel.c'),
                str(root / 'src/pico-controller-motion-channel.c'), '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=30)
            self.assertIn('PICO_CONTROLLER_MOTION_CHANNEL_PASS cross_process_samples=100000', result.stdout)
