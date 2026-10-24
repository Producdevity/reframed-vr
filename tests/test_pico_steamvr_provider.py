import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'output/openvr-sdk'
CJSON = ROOT / 'output/pico-steamvr-deps/cjson'


@unittest.skipUnless((SDK / 'openvr_driver.h').is_file() and
                     all((CJSON / n).is_file() for n in ('cJSON.c', 'cJSON.h')) and
                     shutil.which('cc') and shutil.which('c++'),
                     'requires pinned OpenVR, cJSON and host compilers')
class PicoSteamvrProviderTests(unittest.TestCase):
    def test_controller_registration_failure_preserves_hmd_and_board_identity_is_unique(self):
        for name, digest in json.loads((ROOT / 'profiles/pico-steamvr-cjson.json').read_text())['sha256'].items():
            self.assertEqual(hashlib.sha256((CJSON / name).read_bytes()).hexdigest(), digest)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = (ROOT / 'src/pico-steamvr-driver.cpp').read_text()
            self.assertEqual(source.count('std::fopen("/proc/cmdline","r")'), 1)
            self.assertEqual(source.count('VR_INIT_SERVER_DRIVER_CONTEXT(context);'), 1)
            source = source.replace('std::fopen("/proc/cmdline","r")', 'fixture_cmdline()')
            source = source.replace('VR_INIT_SERVER_DRIVER_CONTEXT(context);',
                                    'VRDriverContext()=context;OpenVRInternal_ModuleServerDriverContext().Clear();')
            (work / 'provider-under-test.cpp').write_text(source)
            flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I', str(ROOT / 'src'), '-I', str(CJSON), '-I', str(work)]
            objects = []
            for name in ('pico-controller-channel', 'pico-slam-channel', 'pico-slam-pose'):
                target = work / (name + '.o')
                subprocess.run(['cc', '-std=c11', *flags, '-c', str(ROOT / 'src' / (name + '.c')),
                                '-o', str(target)], check=True, capture_output=True, timeout=30)
                objects.append(str(target))
            subprocess.run(['cc', '-std=c11', *flags, '-Wno-deprecated-declarations',
                            '-c', str(CJSON / 'cJSON.c'), '-o', str(work / 'json.o')],
                           check=True, capture_output=True, timeout=30)
            binary = work / 'provider'
            subprocess.run(['c++', '-std=c++17', *flags, '-Wno-unused-parameter', '-isystem', str(SDK),
                            str(ROOT / 'tests/pico-steamvr-provider.cpp'),
                            *(str(ROOT / 'src' / (n + '.cpp')) for n in
                              ('pico-steamvr-controller', 'pico-steamvr-pose',
                               'pico-steamvr-display', 'pico-steamvr-config')),
                            *objects, str(work / 'json.o'), '-pthread', '-lm', '-o', str(binary)],
                           check=True, capture_output=True, timeout=30)
            view = {'viewport': [0, 0, 1920, 1832], 'display': [1832, 1920], 'rotation': [0, 1, -1, 0],
                    'fov': [-.7, .8, .6, -.9], 'eye_pose': [0, 0, 0, 1, -.032, 0, 0],
                    'analytic_distortion': {'type': 'pico-radial-2', 'tangent_scale': [2, -2],
                                            'tangent_offset': [-1, 1], 'radial_coefficients': [1] + [0]*10,
                                            'chromatic_coefficients': [0]*6}}
            optics = {'schema_version': 3, 'device': 'PICOA7H10', 'serial': 'synthetic-only',
                      'screen': {'width': 1920, 'height': 3664, 'frame_interval_ns': 11111111},
                      'views': [view, copy.deepcopy(view)]}
            optics['views'][1]['viewport'][1] = 1832
            optics['views'][1]['eye_pose'][4] = .032
            path = work / 'optics.json'
            path.write_text(json.dumps(optics))
            result = subprocess.run([str(binary), str(path), str(work)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PICO_STEAMVR_PROVIDER_PASS', result.stdout)
