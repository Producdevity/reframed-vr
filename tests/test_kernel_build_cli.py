import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KernelBuildCliTests(unittest.TestCase):
    def test_supported_variants_forward_the_required_configuration_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            engine = work / 'container-engine'
            engine.write_text('''#!/bin/sh
if [ "$1" = image ]; then
    printf '%s\\n' sha256:fixture
else
    printf '%s\\n' "$@" > "$KERNEL_TEST_ARGUMENTS"
fi
''')
            engine.chmod(0o755)
            python = work / 'python3'
            python.write_text('#!/bin/sh\nexit 0\n')
            python.chmod(0o755)
            arguments = work / 'arguments'
            environment = os.environ | {
                'PATH': str(work) + os.pathsep + os.environ['PATH'],
                'CONTAINER_ENGINE': str(engine),
                'KERNEL_TEST_ARGUMENTS': str(arguments),
            }
            for profile, variant, expected in (
                ('pico-neo3', 'vendor', []),
                ('pico-neo3', 'linux-userspace', ['--linux-userspace']),
                ('pico-neo3', 'fence-rt', ['--linux-userspace', '--pico-fence-rt']),
                ('pico-neo3', 'qemu-abi', ['--linux-userspace', '--qemu-abi']),
                ('quest3', 'vendor', []),
                ('quest3', 'linux-userspace', ['--linux-userspace']),
                ('quest3', 'qemu-abi', ['--linux-userspace', '--qemu-abi']),
                ('quest3', 'ram-usb', ['--ram-usb']),
            ):
                with self.subTest(profile=profile, variant=variant):
                    subprocess.run(['bash', str(ROOT / 'tools/build-kernel.sh'),
                                    profile, str(work / f'{profile}-{variant}'), variant, 'configure'],
                                   env=environment, check=True, capture_output=True, timeout=10)
                    actual = arguments.read_text().splitlines()
                    self.assertEqual(actual[actual.index('_') + 1:],
                                     [profile, *expected, '--configure-only'])

    def test_ram_usb_rejects_pico_before_starting_the_container_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            output = work / 'output'
            result = subprocess.run(
                ['bash', str(ROOT / 'tools/build-kernel.sh'),
                 'pico-neo3', str(output), 'ram-usb', 'configure'],
                env=os.environ | {'CONTAINER_ENGINE': str(work / 'missing-engine')},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.strip(), 'RAM USB requires quest3')
            self.assertFalse(output.exists())

    def test_fence_rt_rejects_quest_before_starting_the_container_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            output = work / 'output'
            result = subprocess.run(
                ['bash', str(ROOT / 'tools/build-kernel.sh'),
                 'quest3', str(output), 'fence-rt', 'configure'],
                env=os.environ | {'CONTAINER_ENGINE': str(work / 'missing-engine')},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.strip(), 'Fence RT requires pico-neo3')
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
