from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PicoControllerChannelTests(unittest.TestCase):
    def test_lifetime_freshness_and_concurrent_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'controller-channel'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/pico-controller-channel.c'),
                            str(ROOT / 'src/pico-controller-channel.c'), str(ROOT / 'src/pico-controller.c'),
                            '-pthread', '-o', str(binary)], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_CONTROLLER_CHANNEL_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
