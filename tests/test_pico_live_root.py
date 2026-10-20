import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('live_root', Path(__file__).parents[1] / 'tools/build-pico-live-root.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveRootConfigTests(unittest.TestCase):
    def test_userdata_contract_requires_private_path_and_partition_geometry(self):
        valid = 'unencrypted/reframed-c980c8d4-86ccecef/root.squashfs'
        self.assertIn('USERDATA_START=18919752', live.userdata_config(valid, 18919752, 476548752))
        for path, start, sectors in ((valid, 0, 1), (valid, 1, None), (valid, 1, 2**40),
                                      ('/data/' + valid, 1, 1), ('unencrypted/../root.squashfs', 1, 1),
                                      ('local/tmp/root.squashfs', 1, 1)):
            with self.subTest(path=path), self.assertRaises(ValueError):
                live.userdata_config(path, start, sectors)

    def test_pinned_contract(self):
        result = live.config('c980c8d4', 1024, 'a' * 64, 8 * 1024**3, 'reframed-vr-root')
        self.assertIn('PAYLOAD_BYTES=1024\nPAYLOAD_SHA256=' + 'a' * 64, result)
        self.assertIn('ROOT_BYTES=8589934592', result)
        self.assertIn('CONSOLE_SECONDS=1800\n', result)

    def test_bounded_console_duration(self):
        for seconds in (60, 7200, 86400):
            result = live.config('c980c8d4', 1024, 'a' * 64, 4096, 'root', seconds)
            self.assertIn(f'CONSOLE_SECONDS={seconds}\n', result)
        for seconds in (True, None, 59, 86401, 7200.0, '7200\ncommand'):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                live.config('c980c8d4', 1024, 'a' * 64, 4096, 'root', seconds)

    def test_unsafe_identity_or_unbounded_payload_refused(self):
        for serial, size, sha, root_size, label in (
            ('qemu', 1, 'a' * 64, 4096, 'root'),
            ('bad; command', 1, 'a' * 64, 4096, 'root'),
            ('c980c8d4', 0, 'a' * 64, 4096, 'root'),
            ('c980c8d4', 3 * 1024**3 + 1, 'a' * 64, 4096, 'root'),
            ('c980c8d4', 1, 'bad', 4096, 'root'),
            ('c980c8d4', 1, 'a' * 64, 0, 'root'),
            ('c980c8d4', 1, 'a' * 64, 4096, 'root\ncommand'),
        ):
            with self.subTest(serial=serial, size=size, label=label), self.assertRaises(ValueError):
                live.config(serial, size, sha, root_size, label)


if __name__ == '__main__':
    unittest.main()
