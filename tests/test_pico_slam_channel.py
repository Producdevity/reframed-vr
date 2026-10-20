from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoSlamChannelTests(unittest.TestCase):
    def test_concurrent_pose_transport_and_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-slam-channel'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                str(root / 'tests/pico-slam-channel.c'), str(root / 'src/pico-slam-channel.c'),
                str(root / 'src/pico-slam-pose.c'),
                '-pthread', '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_SLAM_CHANNEL_PASS', result.stdout)
