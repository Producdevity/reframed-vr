import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULES = ['q6_notifier_dlkm', 'rx_macro_dlkm', 'tx_macro_dlkm',
           'va_macro_dlkm', 'wcd938x_slave_dlkm', 'pinctrl_wcd_dlkm', 'stub_dlkm']


class AudioStartupTests(unittest.TestCase):
    def setUp(self):
        source = (ROOT / 'system/pico/reframed-pico-pd-mapper').read_text()
        start = source.index('for module in q6_notifier_dlkm ')
        end = source.index('\ndone', start) + len('\ndone')
        self.block = source[start:end]
        self.assertLess(source.index("((count == 0)) || fail"), start)
        self.assertLess(end, source.index('/usr/bin/pd-mapper "${arguments[@]}" &'))

    def run_modules(self, failure=''):
        script = '''set -eu
fail() { printf '%s\n' "$*" >&2; exit 23; }
modprobe() { printf '%s\n' "$1"; [ "$1" != "$FAIL_MODULE" ]; }
''' + self.block + "\nprintf 'PUBLISH_MAPPER\\n'\n"
        return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                              env=dict(os.environ, FAIL_MODULE=failure), timeout=5)

    def test_notifier_and_codecs_finish_before_mapper_publication(self):
        result = self.run_modules()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), MODULES + ['PUBLISH_MAPPER'])

    def test_any_module_failure_prevents_mapper_publication(self):
        for index, module in enumerate(MODULES):
            with self.subTest(module=module):
                result = self.run_modules(module)
                self.assertEqual(result.returncode, 23)
                self.assertEqual(result.stdout.splitlines(), MODULES[:index + 1])
                self.assertIn('audio module initialization failed: ' + module, result.stderr)


if __name__ == '__main__':
    unittest.main()
