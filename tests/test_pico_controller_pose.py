from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerPoseTests(unittest.TestCase):
    def test_tracked_lost_recovered_and_stopped(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'controller-pose'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-pose.c'),
                *[str(root / 'src' / name) for name in (
                    'pico-controller-pose.c', 'pico-slam-channel.c', 'pico-slam-pose.c',
                    'pico-slam-result.c')],
                '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_POSE_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
