from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PicoControllerMotionControlTests(unittest.TestCase):
    def test_real_worker_parser_and_snapshot_offers(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'rpcmem.h').write_text('void rpcmem_init(void);\nvoid rpcmem_deinit(void);\n'
                'void *rpcmem_alloc(int,unsigned,int);\nvoid rpcmem_free(void*);\nint rpcmem_to_fd(void*);\n')
            binary = directory / 'control'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-ffunction-sections', '-fdata-sections',
                '-Wl,-dead_strip' if sys.platform == 'darwin' else '-Wl,--gc-sections',
                '-I', str(root / 'src'), '-I', temp,
                str(root / 'tests/pico-controller-motion-control.c'),
                *(str(root / 'src' / (unit + '.c')) for unit in (
                    'pico-controller', 'pico-controller-ring', 'pico-controller-motion',
                    'pico-controller-motion-channel', 'pico-controller-motion-producer')),
                '-o', str(binary)], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_MOTION_CONTROL_PASS', result.stdout)
