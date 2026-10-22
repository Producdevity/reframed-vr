import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'output/openvr-sdk'


@unittest.skipUnless((SDK / 'openvr_driver.h').is_file(), 'requires cached pinned OpenVR SDK')
class PicoSteamvrControllerTests(unittest.TestCase):
    def test_input_release_freshness_and_invalid_pose(self):
        profile = json.loads((ROOT / 'profiles/openvr.json').read_text())
        self.assertEqual(hashlib.sha256((SDK / 'openvr_driver.h').read_bytes()).hexdigest(),
                         profile['files']['headers/openvr_driver.h'])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I', str(ROOT / 'src')]
            objects = []
            for name in ('pico-controller-channel',):
                target = directory / (name + '.o')
                subprocess.run(['cc', '-std=c11', *flags, '-c', str(ROOT / 'src' / (name + '.c')),
                                '-o', str(target)], check=True, text=True, timeout=30)
                objects.append(str(target))
            binary = directory / 'pico-steamvr-controller'
            subprocess.run(['c++', '-std=c++17', *flags, '-Wno-unused-parameter', '-isystem', str(SDK),
                            str(ROOT / 'tests/pico-steamvr-controller.cpp'), str(ROOT / 'src/pico-steamvr-controller.cpp'),
                            *objects, '-pthread', '-lm', '-o', str(binary)],
                           check=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_STEAMVR_CONTROLLER_PASS', result.stdout)
