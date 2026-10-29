import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('acquisition', ROOT / 'tools/analyze-pico-controller-acquisition.py')
acquisition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquisition)


class AcquisitionWriterTests(unittest.TestCase):
    def test_bounded_writer_failure_lifecycle_and_python_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'writer'
            source = ROOT / 'src/pico-controller-acquisition.c'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/pico-controller-acquisition.c'),
                            str(source), '-lm', '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            motion, images = root / 'motion.raw', root / 'images.raw'
            result = subprocess.run([str(binary), str(motion), str(images)], check=True,
                                    capture_output=True, text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_ACQUISITION_PASS', result.stdout)
            report = acquisition.analyze(motion, images)
            self.assertEqual((report['format_version'], report['image_sets']), (3, 1))
            self.assertEqual(report['motion_records_per_hand'], {'1': 2, '2': 2})
            self.assertEqual([e['dispatch_order'] for e in report['events']], [1, 2, 3, 4, 5])
            raw = images.read_bytes()
            for camera in range(4):
                offset = 32 + 760 + camera * (64 + acquisition.PIXELS)
                self.assertEqual(raw[offset+1:offset+4], bytes(3))
                self.assertEqual(raw[offset+64:offset+64+acquisition.PIXELS],
                                 bytes([camera+1]) * acquisition.PIXELS)
            if shutil.which('c++'):
                obj = root / 'writer.o'
                subprocess.run(['cc', '-std=c11', '-I', str(ROOT / 'src'), '-c', str(source),
                                '-o', str(obj)], check=True, capture_output=True, timeout=30)
                subprocess.run(['c++', '-std=c++17', '-I', str(ROOT / 'src'), '-x', 'c++', '-',
                                '-x', 'none', str(obj), '-lm', '-o', str(root / 'cpp')],
                               input='#include "pico-controller-acquisition.h"\n'
                                     'int main(){pico_controller_acquisition_destroy(nullptr);}',
                               text=True, check=True, capture_output=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
