import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/kernel/pico-neo3-linux/0017-bluetooth-default-scan-response.patch'
FIXTURE = ROOT / 'tests/fixtures/pico-bluetooth-scan-response.c'
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('bluetooth_kernel_inputs', ROOT / 'tools/kernel-build.py')
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class BluetoothScanResponseTests(unittest.TestCase):
    def test_patch_is_only_selected_with_pico_linux_userspace(self):
        pico = {'repository': 'bytedance/neo3-kernel'}
        other = {'repository': 'facebookincubator/oculus-linux-kernel'}
        for profile, linux, qemu, expected in [
            (pico, False, False, False), (pico, True, False, True),
            (pico, True, True, True), (other, False, False, False),
            (other, True, False, False), (other, True, True, False),
        ]:
            with self.subTest(profile=profile, linux=linux, qemu=qemu):
                _, patches = kernel.build_inputs(profile, linux, qemu)
                self.assertEqual(PATCH in patches, expected)
        _, patches = kernel.build_inputs(pico, True, False, pico_fence_rt=True)
        self.assertEqual(patches.count(PATCH), 1)

    @unittest.skipUnless(shutil.which('cc') and shutil.which('patch'),
                         'C compiler and patch are required for the source fixture')
    def test_default_advertising_mode_matches_scan_response_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            source = tree / 'net/bluetooth/hci_request.c'
            source.parent.mkdir(parents=True)
            shutil.copyfile(FIXTURE, source)
            results = []
            for patched in (0, 1):
                if patched:
                    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', str(tree),
                                    '-i', str(PATCH)], check=True, capture_output=True, timeout=10)
                binary = tree / ('scan-response-' + str(patched))
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source),
                                '-o', str(binary)], check=True, capture_output=True, timeout=30)
                result = subprocess.run([str(binary), str(patched)], check=True,
                                        capture_output=True, text=True, timeout=10)
                results.append(json.loads(result.stdout))
            before, after = results
            self.assertEqual([before['default_properties'], after['default_properties']], [0x10, 0x12])
            self.assertEqual([before['mode_rule_status'], after['mode_rule_status']], [0x12, 0])
            self.assertEqual(before['default_scan_response_hex'], after['default_scan_response_hex'])
            self.assertEqual(after['default_scan_response_hex'],
                             '0003010d0c0872656672616d65642d7600000000000000000000000000000000000000')
            self.assertTrue(before['passed'] and after['passed'])
            self.assertEqual(before['scenarios'], 8)
            self.assertEqual(after['scenarios'], 8)


if __name__ == '__main__':
    unittest.main()
