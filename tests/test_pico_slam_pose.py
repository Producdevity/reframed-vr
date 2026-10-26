from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoSlamPoseTests(unittest.TestCase):
    def test_frame_conversion_and_tracking_validity(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-slam-pose'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                str(root / 'tests/pico-slam-pose.c'), str(root / 'src/pico-slam-pose.c'),
                str(root / 'src/pico-slam-result.c'), '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_SLAM_POSE_PASS', result.stdout)
