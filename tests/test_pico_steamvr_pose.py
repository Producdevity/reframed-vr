import hashlib
import json
from pathlib import Path
import subprocess
import struct
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'output/openvr-sdk'


@unittest.skipUnless((SDK / 'openvr_driver.h').is_file() and shutil.which('cc') and shutil.which('c++'), 'requires cached pinned OpenVR SDK')
class PicoSteamvrPoseTests(unittest.TestCase):
    def test_calibrated_pose_and_invalid_tracking_flags(self):
        profile = json.loads((ROOT / 'profiles/openvr.json').read_text())
        self.assertEqual(hashlib.sha256((SDK / 'openvr_driver.h').read_bytes()).hexdigest(),
                         profile['files']['headers/openvr_driver.h'])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I', str(ROOT / 'src')]
            objects = []
            for name in ('pico-slam-channel', 'pico-slam-pose', 'pico-slam-result', 'pico-vendor-slam-output'):
                target = directory / (name + '.o')
                subprocess.run(['cc', '-std=c11', *flags, '-c', str(ROOT / 'src' / (name + '.c')),
                                '-o', str(target)], check=True, capture_output=True, text=True, timeout=30)
                objects.append(str(target))
            binary = directory / 'pico-steamvr-pose'
            subprocess.run(['c++', '-std=c++17', *flags, '-isystem', str(SDK),
                            str(ROOT / 'tests/pico-steamvr-pose.cpp'), str(ROOT / 'src/pico-steamvr-pose.cpp'),
                            *objects, '-pthread', '-lm', '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_STEAMVR_POSE_PASS', result.stdout)
            def record(timestamp,confidence=1,state=1,position=0):
                raw=bytearray(0x170);struct.pack_into('<q',raw,0,timestamp)
                struct.pack_into('<d',raw,8,position)
                struct.pack_into('<d',raw,32,1);raw[64]=state;raw[65]=confidence
                return raw
            replay=Path(temp)/'replay.bin'
            replay.write_bytes(record(1000000000,0)+record(1001000000)+
                               record(1002000000,0)+record(1003000000))
            replayed=subprocess.run([str(binary),str(replay)],check=True,capture_output=True,text=True,timeout=10)
            self.assertIn('replay_records=4 published=1',replayed.stdout)
            replay.write_bytes(record(1000000000,position=1000001))
            outlier=subprocess.run([str(binary),str(replay)],check=True,capture_output=True,text=True,timeout=10)
            self.assertIn('replay_records=1 published=0',outlier.stdout)
            for invalid,reason in [(b'', 'records'),(record((1<<63)-1),'timestamp_ns')]:
                replay.write_bytes(invalid)
                refused=subprocess.run([str(binary),str(replay)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(refused.returncode,0)
                self.assertNotIn('runtime error:',refused.stderr)
                self.assertIn(reason,refused.stderr)
