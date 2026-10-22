from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoVendorSlamFeedTests(unittest.TestCase):
    def test_async_ownership_ordering_and_failures(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-vendor-slam-feed'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                str(root / 'tests/pico-vendor-slam-feed.c'), str(root / 'src/pico-vendor-slam-feed.c'),
                '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_VENDOR_SLAM_FEED_PASS cycles=100 faults=52', result.stdout)
            self.assertIn('PICO_VENDOR_SLAM_COPY_PASS delivered=1000 retained_limit=2 pending_on_stop=1', result.stdout)
