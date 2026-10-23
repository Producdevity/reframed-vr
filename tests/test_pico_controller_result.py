import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ControllerResultTests(unittest.TestCase):
    def test_wire_units_diagnostics_and_rejected_results(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'controller-result'
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O1', '-g',
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/pico-controller-result.c'),
                            str(ROOT / 'src/pico-controller-result.c'),
                            str(ROOT / 'src/pico-slam-result.c'), '-lm', '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
            self.assertIn('PICO_CONTROLLER_RESULT_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
