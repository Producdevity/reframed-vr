from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PicoSteamvrProbeGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        root = Path(cls.build.name)
        main = root / 'main.cpp'
        main.write_text('#include "pico-steamvr-probe-gate.h"\n#include <cstdio>\n#include <cstdlib>\n'
                        'int main(int argc,char **argv) {\n'
                        ' unsigned ms=argc>2?std::strtoul(argv[2],nullptr,10):1000;\n'
                        ' int error=pico_steamvr_probe_gate(argc>1?argv[1]:nullptr,ms);\n'
                        ' if(error) return error;\n'
                        ' std::puts("QUERY_START");return 0; }\n')
        cls.program = root / 'gate'
        subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'src'), str(main),
                        str(ROOT / 'src/pico-steamvr-probe-gate.cpp'),
                        '-o', str(cls.program)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def test_disabled_gate_runs_without_a_listener(self):
        result = subprocess.run([str(self.program)], capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'QUERY_START\n')

    def exchange(self, permission):
        with tempfile.TemporaryDirectory() as temporary, socket.socket(socket.AF_UNIX) as listener:
            path = str(Path(temporary) / 'gate.sock')
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(2)
            with subprocess.Popen([str(self.program), path], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as child:
                connection, _ = listener.accept()
                with connection:
                    self.assertIsNone(child.poll())
                    if permission is not None:
                        connection.sendall(permission)
                stdout, stderr = child.communicate(timeout=2)
                return child.returncode, stdout, stderr

    def test_first_observation_waits_for_explicit_release(self):
        code, stdout, stderr = self.exchange(b'G')
        self.assertEqual(code, 0)
        self.assertEqual(stdout, 'QUERY_START\n')
        self.assertEqual(stderr, '')

    def test_closed_or_rejected_gate_never_starts_observations(self):
        for permission in (None, b'X'):
            with self.subTest(permission=permission):
                code, stdout, _ = self.exchange(permission)
                self.assertNotEqual(code, 0)
                self.assertEqual(stdout, '')

    def test_unreleased_listener_is_bounded_and_does_not_start_observations(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket(socket.AF_UNIX) as listener:
            path = str(Path(temporary) / 'gate.sock')
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(2)
            before = time.monotonic()
            with subprocess.Popen([str(self.program), path, '100'], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as child:
                connection, _ = listener.accept()
                with connection:
                    stdout, _ = child.communicate(timeout=2)
                self.assertNotEqual(child.returncode, 0)
                self.assertEqual(stdout, '')
                self.assertLess(time.monotonic() - before, 2)

    def test_bad_gate_paths_never_start_observations(self):
        for path in ('', 'relative.sock', '/'+'x'*200, '/nonexistent-reframed-gate.sock'):
            with self.subTest(path=path):
                result = subprocess.run([str(self.program), path], capture_output=True,
                                        text=True, timeout=2)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
