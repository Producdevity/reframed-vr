import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'pico_nvm', Path(__file__).resolve().parents[1] / 'tools/pico-bluetooth-nvm.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


def table(tags):
    payload = b''.join(struct.pack('<HHII', tag, len(value), 0, 0) + value for tag, value in tags)
    return struct.pack('<I', len(payload) << 8 | 2) + payload


class NvmTests(unittest.TestCase):
    def test_only_the_address_changes_in_bluetooth_byte_order(self):
        source = table([(17, b'unchanged transport'), (2, p.DEFAULT_ADDRESS), (27, b'unchanged calibration')])
        with patch.object(p, 'SOURCE_SHA256', hashlib.sha256(source).hexdigest()), \
                patch.object(p, 'SOURCE_SIZE', len(source)):
            result = p.personalize(source, '08:16:d5:01:02:03')
        begin, end = p.address_span(source)
        self.assertEqual(result[begin:end], bytes.fromhex('030201d51608'))
        self.assertEqual(result[:begin], source[:begin])
        self.assertEqual(result[end:], source[end:])
        self.assertEqual(len(result), len(source))

    def test_truncation_duplicate_missing_and_wrong_length_are_rejected(self):
        good = table([(2, p.DEFAULT_ADDRESS)])
        cases = [good[:i] for i in range(len(good))]
        cases += [good + b'x', table([(2, b'bad')]), table([]),
                  table([(2, p.DEFAULT_ADDRESS), (2, p.DEFAULT_ADDRESS)]),
                  struct.pack('<I', (len(good) - 4) << 8 | 1) + good[4:]]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                p.address_span(data)

    def test_unknown_firmware_is_rejected_before_personalization(self):
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            p.personalize(bytes(p.SOURCE_SIZE), '08:16:d5:01:02:03')

    def test_generation_requires_matching_private_identity_and_preserves_existing_paths(self):
        source = table([(2, p.DEFAULT_ADDRESS), (27, b'calibration')])
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(p, 'SOURCE_SHA256', hashlib.sha256(source).hexdigest()), \
                patch.object(p, 'SOURCE_SIZE', len(source)):
            root = Path(temporary)
            original, identity, output = root / 'source.bin', root / 'identity.json', root / 'unit.bin'
            original.write_bytes(source)
            identity.write_text(json.dumps({
                'status': 'stock-offline-identities-verified',
                'fingerprint': 'Pico/A7H10/PICOA7H10:10/5.8.4.0/smartcm.1696861506:user/test-keys',
                'bluetooth_hal_sha256': '59f013ff41adbf8e1f2ca350f62938f4602a833d0f97809838bc2c417541af52',
                'identity': {'boot_serial': 'fixture', 'bluetooth_address': '08:16:d5:01:02:03'},
            }))
            identity.chmod(0o600)
            with self.assertRaises(ValueError):
                p.generate(original, identity, 'other', output)
            self.assertFalse(output.exists())
            identity.chmod(0o644)
            with self.assertRaises(ValueError):
                p.generate(original, identity, 'fixture', output)
            self.assertFalse(output.exists())
            identity.chmod(0o600)
            receipt = p.generate(original, identity, 'fixture', output)
            self.assertEqual(original.read_bytes(), source)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(receipt['output_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertNotIn('08:16:d5:01:02:03', json.dumps(receipt))
            generated = output.read_bytes()
            with self.assertRaises(FileExistsError):
                p.generate(original, identity, 'fixture', output)
            self.assertEqual(output.read_bytes(), generated)
            output.unlink()
            output.symlink_to(original)
            with self.assertRaises(FileExistsError):
                p.generate(original, identity, 'fixture', output)
            self.assertEqual(original.read_bytes(), source)

    def test_source_default_and_target_addresses_are_checked(self):
        for source in [table([(2, p.DEFAULT_ADDRESS)]), table([(2, bytes(6))])]:
            with patch.object(p, 'SOURCE_SHA256', hashlib.sha256(source).hexdigest()), \
                    patch.object(p, 'SOURCE_SIZE', len(source)):
                for address in ['00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff', '09:16:d5:01:02:03',
                                '08:16:D5:01:02:03', '00:00:00:00:5a:ad', 'invalid']:
                    with self.subTest(address=address), self.assertRaises(ValueError):
                        p.personalize(source, address)


if __name__ == '__main__':
    unittest.main()
