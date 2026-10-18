from pathlib import Path
import subprocess
import tempfile
import unittest


class XorgModesettingPropertyTests(unittest.TestCase):
    def test_preserve_advertised_mode_refresh(self):
        self.run_fixture('mode', '0002-modesetting-preserve-advertised-refresh.patch')

    def test_unexposed_property_and_supported_writes(self):
        self.run_fixture('property', '0001-modesetting-skip-unexposed-properties.patch')

    def run_fixture(self, name, patch):
        root = Path(__file__).resolve().parents[1]
        fixture = (root / f'tests/fixtures/xorg-modesetting-{name}.inc').read_text()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / 'hw/xfree86/drivers/modesetting/drmmode_display.c'
            source.parent.mkdir(parents=True)
            source.write_text(fixture)
            for original in (True, False):
                if not original:
                    subprocess.run([
                        'patch', '--batch', '--fuzz=0', '--forward', '-p1', '-i',
                        str(root / 'patches/xorg' / patch),
                    ], cwd=directory, check=True, capture_output=True, timeout=15)
                (directory / 'driver.inc').write_text(source.read_text())
                executable = directory / 'property'
                compiled = subprocess.run([
                    'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter',
                    '-fsanitize=address,undefined', '-I', temp,
                    *(['-DEXPECT_OLD'] if original and name == 'mode' else []),
                    str(root / f'tests/xorg-modesetting-{name}.c'), '-o', str(executable),
                ], capture_output=True, text=True, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                result = subprocess.run([str(executable)], capture_output=True,
                                        text=True, timeout=15)
                if original and name == 'property':
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('null pointer', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if not original:
                        self.assertIn('preserved', result.stdout)
