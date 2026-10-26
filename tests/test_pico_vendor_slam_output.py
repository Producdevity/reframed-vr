from pathlib import Path
import subprocess
import struct
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
            def record(timestamp,confidence=1,state=1):
                raw=bytearray(0x170);struct.pack_into('<q',raw,0,timestamp)
                struct.pack_into('<d',raw,32,1);raw[64]=state;raw[65]=confidence
                return raw
            replay=Path(temp)/'replay.bin'
            replay.write_bytes(record(1000000000,0)+record(1001000000)+
                               record(1002000000,0)+record(1003000000))
            replayed=subprocess.run([str(binary),str(replay)],check=True,capture_output=True,text=True,timeout=10)
            self.assertIn('replay_records=4 published=1',replayed.stdout)
            for invalid,reason in [(b'', 'records'),(record((1<<63)-1),'timestamp_ns')]:
                replay.write_bytes(invalid)
                refused=subprocess.run([str(binary),str(replay)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(refused.returncode,0)
                self.assertNotIn('runtime error:',refused.stderr)
                self.assertIn(reason,refused.stderr)
