import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'wifi_state', Path(__file__).resolve().parents[1] / 'tools/pico-wifi-state.py')
state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state)
PROFILE = (b'[connection]\nuuid=11111111-1111-4111-8111-111111111111\n'
           b'type=wifi\ninterface-name=wlan0\nautoconnect=true\n'
           b'[wifi]\nssid=fixture\ncloned-mac-address=08:16:d5:01:02:03\n'
           b'[wifi-security]\nkey-mgmt=wpa-psk\npsk=' + b'0' * 64 + b'\n')


class WifiStateTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source.nmconnection'
        source.write_bytes(PROFILE)
        source.chmod(0o600)
        return source, root / 'state', root / 'restored.nmconnection'

    def test_roundtrip_is_private_idempotent_and_bound_to_the_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, directory, destination = self.fixture(root)
            record = state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            restored = state.restore(directory, destination, 'fixture', 'a' * 64, uid=os.getuid())
            self.assertEqual(record, restored)
            self.assertEqual(destination.read_bytes(), PROFILE)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            state.restore(directory, destination, 'fixture', 'a' * 64, uid=os.getuid())
            for serial, identity in [('other', 'a' * 64), ('fixture', 'b' * 64)]:
                with self.assertRaises(ValueError):
                    state.read_state(directory, serial, identity, uid=os.getuid())

    def test_existing_credentials_and_different_destinations_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, directory, destination = self.fixture(root)
            state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            source.write_bytes(PROFILE.replace(b'ssid=fixture', b'ssid=changed'))
            with self.assertRaises(FileExistsError):
                state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            self.assertEqual(state.read_state(directory, 'fixture', 'a' * 64, uid=os.getuid())[0], PROFILE)
            destination.write_bytes(b'preserve existing file')
            destination.chmod(0o600)
            with self.assertRaises(FileExistsError):
                state.restore(directory, destination, 'fixture', 'a' * 64, uid=os.getuid())
            self.assertEqual(destination.read_bytes(), b'preserve existing file')

    def test_readable_system_directory_is_allowed_but_writable_directory_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, directory, _ = self.fixture(root)
            state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            parent = root / 'system-connections'
            parent.mkdir(mode=0o755)
            destination = parent / 'restored.nmconnection'
            state.restore(directory, destination, 'fixture', 'a' * 64, uid=os.getuid())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            destination.unlink()
            parent.chmod(0o777)
            with self.assertRaises(ValueError):
                state.restore(directory, destination, 'fixture', 'a' * 64, uid=os.getuid())
            self.assertFalse(destination.exists())

    def test_interrupted_marker_update_keeps_the_old_profile_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, directory, _ = self.fixture(root)
            state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            source.write_bytes(PROFILE.replace(b'ssid=fixture', b'ssid=changed'))
            with patch.object(state.os, 'replace', side_effect=OSError('interrupted')), self.assertRaises(OSError):
                state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid(), replace=True)
            self.assertEqual(state.read_state(directory, 'fixture', 'a' * 64, uid=os.getuid())[0], PROFILE)

    def test_symlinks_open_permissions_and_corruption_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, directory, _ = self.fixture(root)
            link = root / 'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):
                state.private_bytes(link, uid=os.getuid())
            source.chmod(0o644)
            with self.assertRaises(ValueError):
                state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            source.chmod(0o600)
            record = state.save(directory, source, 'fixture', 'a' * 64, uid=os.getuid())
            (directory / ('profile-' + record['profile_sha256'] + '.nmconnection')).write_bytes(PROFILE + b'corruption')
            with self.assertRaises(ValueError):
                state.read_state(directory, 'fixture', 'a' * 64, uid=os.getuid())

    def test_profile_format_and_unit_mac_are_checked_without_exposing_secrets(self):
        state.validate_profile(PROFILE, '08:16:d5:01:02:03')
        with self.assertRaises(ValueError):
            state.validate_profile(PROFILE, '08:16:d5:04:05:06')
        for data in [b'private-password-without-section', PROFILE.replace(b'wlan0', b'eth0'),
                     PROFILE.replace(b'wpa-psk', b'none'), PROFILE.replace(b'autoconnect=true', b'autoconnect=false')]:
            with self.assertRaises(ValueError) as caught:
                state.validate_profile(data)
            self.assertNotIn('private-password', str(caught.exception))

    def test_standard_passphrases_and_keyfile_escapes_are_preserved(self):
        for key in [b'fixture-passphrase', b'\\sfixture\\spassphrase', b'x' * 62 + b'\\\\']:
            state.validate_profile(PROFILE.replace(b'0' * 64, key))
        for key in [b'short', b'x' * 64, b'fixture\\qinvalid', b'fixture\\ninvalid']:
            with self.assertRaises(ValueError):
                state.validate_profile(PROFILE.replace(b'0' * 64, key))


    def test_existing_session_mount_is_reused_without_a_second_mount(self):
        info = ('22 1 259:9 / /data rw,nosuid,nodev,noatime shared:5 - f2fs /dev/sda9 rw,lazytime\n'
                '30 22 259:9 /media /media rw - f2fs /dev/sda9 rw\n'
                '31 22 259:7 / /mnt/with\\040space ro - f2fs /dev/sda7 ro\n'
                '32 22 259:6 /sub /sub rw - f2fs /dev/sda6 rw\n'
                '33 22 259:5 / /other rw - ext4 /dev/sda5 rw\n')
        self.assertEqual(state.existing_mount(info, '259:9', True), Path('/data'))
        self.assertEqual(state.existing_mount(info, '259:9', False), Path('/data'))
        self.assertIsNone(state.existing_mount(info, '259:8', False))
        self.assertEqual(state.existing_mount(info, '259:7', False), Path('/mnt/with space'))
        with self.assertRaisesRegex(ValueError, 'read-only'):
            state.existing_mount(info, '259:7', True)
        for number in ('259:6', '259:5'):
            with self.assertRaisesRegex(ValueError, 'subtree or another'):
                state.existing_mount(info, number, False)

if __name__ == '__main__':
    unittest.main()
