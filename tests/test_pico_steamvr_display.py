import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'output/openvr-sdk'
CJSON = ROOT / 'output/pico-steamvr-deps/cjson'


@unittest.skipUnless((SDK / 'openvr_driver.h').is_file() and (CJSON / 'cJSON.c').is_file(),
                     'requires cached pinned OpenVR and cJSON dependencies')
class PicoSteamvrDisplayTests(unittest.TestCase):
    def test_optics_and_profile_refusals(self):
        expected = json.loads((ROOT / 'profiles/pico-steamvr-cjson.json').read_text())['sha256']
        expected_sdk = json.loads((ROOT / 'profiles/openvr.json').read_text())['files']['headers/openvr_driver.h']
        self.assertEqual(hashlib.sha256((SDK / 'openvr_driver.h').read_bytes()).hexdigest(), expected_sdk)
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((CJSON / name).read_bytes()).hexdigest(), digest)
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I', str(ROOT / 'src'), '-I', str(CJSON)]
            subprocess.run(['cc', '-std=c11', *flags, '-Wno-deprecated-declarations',
                            '-c', str(CJSON / 'cJSON.c'), '-o', str(work / 'cJSON.o')],
                           check=True, capture_output=True, text=True, timeout=30)
            binary = work / 'display-test'
            subprocess.run(['c++', '-std=c++17', *flags, '-isystem', str(SDK),
                            str(ROOT / 'tests/pico-steamvr-display.cpp'), str(ROOT / 'src/pico-steamvr-display.cpp'),
                            str(ROOT / 'src/pico-steamvr-config.cpp'), str(work / 'cJSON.o'), '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=20)
            self.assertIn('PICO_STEAMVR_DISPLAY_PASS', result.stdout)
            view = {'viewport': [0, 0, 1920, 1832], 'display': [1832, 1920], 'rotation': [0, 1, -1, 0],
                    'fov': [-.7, .8, .6, -.9], 'eye_pose': [0, 0, 0, 1, -.032, 0, 0],
                    'analytic_distortion': {'type': 'pico-radial-2', 'tangent_scale': [2, -2],
                                            'tangent_offset': [-1, 1], 'radial_coefficients': [1] + [0]*10,
                                            'chromatic_coefficients': [0]*6}}
            profile = {'schema_version': 3, 'device': 'PICOA7H10', 'serial': 'synthetic-only',
                       'screen': {'width': 1920, 'height': 3664, 'frame_interval_ns': 11111111},
                       'views': [view, copy.deepcopy(view)]}
            profile['views'][1]['viewport'][1] = 1832
            profile['views'][1]['eye_pose'][4] = .032
            path = work / 'optics.json'

            def check(value, valid):
                path.write_text(value if isinstance(value, str) else json.dumps(value))
                subprocess.run([str(binary), '--load' if valid else '--refuse', str(path)], check=True,
                               capture_output=True, text=True, timeout=10)

            check(profile, True)
            for mutate in [lambda p: p.update(schema_version=1), lambda p: p.update(device='PICO4'),
                           lambda p: p['views'][1]['viewport'].__setitem__(1, 0),
                           lambda p: p['views'][0]['eye_pose'].__setitem__(3, 2),
                           lambda p: p['views'][0]['analytic_distortion'].update(type='unknown')]:
                bad = copy.deepcopy(profile)
                mutate(bad)
                check(bad, False)
            check(json.dumps(profile).replace('"schema_version": 3', '"schema_version": 3, "schema_version": 3'), False)
            for name in ['distortion', 'grid_width', 'grid_height']:
                check(json.dumps(profile).replace('"viewport":', f'"{name}": null, "{name}": null, "viewport":'), False)
            check(json.dumps(profile) + '\x00', False)
            check('{', False)
            path.unlink()
            path.symlink_to(work / 'missing')
            subprocess.run([str(binary), '--refuse', str(path)], check=True, capture_output=True, text=True, timeout=10)
