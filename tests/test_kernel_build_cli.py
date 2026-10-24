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
            for variant, expected in (
                ('vendor', []),
                ('linux-userspace', ['--linux-userspace']),
                ('qemu-abi', ['--linux-userspace', '--qemu-abi']),
            ):
                with self.subTest(variant=variant):
                    subprocess.run(['bash', str(ROOT / 'tools/build-kernel.sh'),
                                    'pico-neo3', str(work / variant), variant, 'configure'],
                                   env=environment, check=True, capture_output=True, timeout=10)
                    actual = arguments.read_text().splitlines()
                    self.assertEqual(actual[actual.index('_') + 1:],
                                     ['pico-neo3', *expected, '--configure-only'])


if __name__ == '__main__':
    unittest.main()
