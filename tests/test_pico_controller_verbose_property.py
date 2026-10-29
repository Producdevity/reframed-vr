import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('cc'),
                     'Requires a native Linux ELF loader and C compiler')
class ControllerVerbosePropertyTests(unittest.TestCase):
    def test_delegation_opt_in_concurrency_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = directory / 'libbase.so'
            hook = directory / 'hook.so'
            driver = directory / 'driver'
            flags = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']
            commands = [
                flags + ['-fPIC', '-shared',
                         str(ROOT / 'tests/fixtures/pico-controller-property-base.c'), '-o', str(base)],
                flags + ['-fPIC', '-fvisibility=hidden', '-shared',
                         str(ROOT / 'src/pico-controller-verbose-property.c'), '-ldl', '-pthread', '-o', str(hook)],
                flags + [str(ROOT / 'tests/fixtures/pico-controller-property-driver.c'),
                         '-L' + str(directory), '-lbase', '-Wl,-rpath,$ORIGIN', '-ldl', '-pthread', '-o', str(driver)],
            ]
            for command in commands:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            for mode, option in [('off', None), ('off', '0'), ('off', 'yes'), ('on', '1')]:
                with self.subTest(option=option):
                    env = dict(os.environ, LD_PRELOAD=str(hook))
                    env.pop('PICO_CONTROLLER_VERBOSE', None)
                    if option is not None:
                        env['PICO_CONTROLLER_VERBOSE'] = option
                    result = subprocess.run([str(driver), mode], env=env, check=True,
                                            capture_output=True, text=True, timeout=20)
                    self.assertIn('PASS property delegation', result.stdout)
                    if mode == 'on':
                        self.assertEqual(result.stderr.count('PICO_CONTROLLER_VERBOSE_PROPERTY enabled '), 1)
                        self.assertEqual(result.stderr.count('PICO_CONTROLLER_VERBOSE_PROPERTY disabled '), 1)
                    else:
                        self.assertNotIn('PICO_CONTROLLER_VERBOSE_PROPERTY', result.stderr)


if __name__ == '__main__':
    unittest.main()
