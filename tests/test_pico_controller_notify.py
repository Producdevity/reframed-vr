import pathlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


COMPILER = os.environ.get('CC', 'clang')


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which(COMPILER),
                     'Linux eventfd and a C compiler required')
class ControllerNotifyTests(unittest.TestCase):
    def test_coalescing_queue_publication_and_faults(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'test'
            subprocess.run([COMPILER, '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-pthread', '-I', str(root / 'src'),
                            str(root / 'tests/pico-controller-notify.c'),
                            str(root / 'src/pico-controller-notify.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)


if __name__ == '__main__':
    unittest.main()
