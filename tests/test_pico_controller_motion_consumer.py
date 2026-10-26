from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerMotionConsumerTests(unittest.TestCase):
    def test_brackets_latency_and_terminal_failures(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'motion-consumer'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-motion-consumer.c'),
                *[str(root / 'src' / name) for name in (
                    'pico-controller-motion-consumer.c', 'pico-controller-motion-channel.c',
                    'pico-controller-head.c', 'pico-slam-result.c')],
                '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_MOTION_CONSUMER_PASS', result.stdout)
