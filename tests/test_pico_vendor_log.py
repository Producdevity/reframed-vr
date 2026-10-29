from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('cc'),
                     'Requires a native Linux C compiler')
class VendorLogTests(unittest.TestCase):
    def test_logging_abi_and_worker_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'log-fixture'
            output = Path(tmp) / 'log.txt'
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'tests/fixtures/pico-vendor-log.c'),
                            '-ldl', '-pthread', '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary), str(output)], check=True,
                                    capture_output=True, text=True, timeout=10)
            self.assertIn('logger fixtures passed:', result.stdout)
            markers = [json.loads(line) for line in output.read_text().splitlines()
                       if line.startswith('{"event":"pico_controller_candidate_worker",')]
            self.assertEqual(len(markers), 1)
            self.assertEqual(markers[0]['tid'], 4321)
            self.assertEqual(markers[0]['caller_offset'], 0xb9a08)
            self.assertEqual(markers[0]['caller_pc'] - markers[0]['sdk_base'], 0xb9a08)


if __name__ == '__main__':
    unittest.main()
