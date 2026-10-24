from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import unittest


class PicoControllerMotionProducerTests(unittest.TestCase):
    def test_snapshot_conversion_channel_and_permanent_lifecycle_failure(self):
        root = Path(__file__).resolve().parents[1]
        units = ['pico-controller', 'pico-controller-ring', 'pico-controller-motion',
                 'pico-controller-motion-channel', 'pico-controller-motion-producer']
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'motion-producer'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-I', str(root / 'src'), str(root / 'tests/pico-controller-motion-producer.c'),
                *(str(root / 'src' / (unit + '.c')) for unit in units), '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn('PICO_CONTROLLER_MOTION_PRODUCER_PASS', result.stdout)
            header=struct.pack('<8Q',0x52564354494d0001,1,0,0,2024,19200000,0,0)
            for index,extra in enumerate((b'',b'x')):
                capture=Path(temp)/f'capture-{index}.bin';capture.write_bytes(header+extra)
                replayed=subprocess.run([str(binary),'--replay',str(capture),str(Path(temp)/f'out-{index}')],
                                        capture_output=True,text=True,timeout=10)
                self.assertNotEqual(replayed.returncode,0)
                self.assertNotIn('runtime error:',replayed.stderr)
                self.assertNotIn('PICO_CONTROLLER_MOTION_REPLAY_PASS',replayed.stdout)
            if shutil.which('c++') is None:
                return
            objects=[]
            for unit in units:
                target=Path(temp)/(unit+'.o')
                subprocess.run(['cc','-std=c11','-I',str(root/'src'),'-c',
                                str(root/'src'/(unit+'.c')),'-o',str(target)],check=True,timeout=30)
                objects.append(str(target))
            cpp=Path(temp)/'cpp-producer'
            subprocess.run(['c++','-std=c++17','-I',str(root/'src'),'-x','c++','-',
                            '-x','none',*objects,'-o',str(cpp)],
                           input='#include "pico-controller-motion-producer.h"\nint main(){pico_controller_motion_producer_stop(nullptr);}',
                           text=True,check=True,capture_output=True,timeout=30)
            subprocess.run([str(cpp)],check=True,timeout=10)
