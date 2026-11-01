from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerHapticsTests(unittest.TestCase):
    def test_requests_frames_and_fifo_writes(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'controller-haptics'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-haptics.c'),
                str(root / 'src/pico-controller-haptics.c'), str(root / 'src/pico-station-protocol.c'),
                '-lm', '-pthread', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            # The closed-reader case must report EPIPE without a SIGPIPE disposition change.
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_HAPTICS_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
