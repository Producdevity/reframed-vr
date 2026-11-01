#!/usr/bin/env python3
"""Save or restore a private native Pico Wi-Fi profile on its verified userdata volume."""
import argparse
import configparser
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid


def private_bytes(path, *, uid=0):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or
                before.st_mode & 0o077 or before.st_nlink != 1 or not 0 < before.st_size <= 65536):
            raise ValueError('Expected a bounded private regular file')
        data = stream.read(65537)
        after = os.fstat(stream.fileno())
    if (len(data) != before.st_size or
            (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('Private file changed during reading')
    return data


def private_directory(path, *, create=False, uid=0, private=True):
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    forbidden = 0o077 if private else 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & forbidden:
        raise ValueError('Expected an owned directory with restricted permissions')


def validate_profile(data, expected_address=None):
    profile = configparser.ConfigParser(interpolation=None)
    try:
        profile.read_string(data.decode())
    except (UnicodeError, configparser.Error):
        raise ValueError('Invalid private NetworkManager keyfile') from None
    connection = profile['connection']
    key = profile['wifi-security'].get('psk', '')
    escapes = {'s': ' ', 'n': '\n', 'r': '\r', 't': '\t', '\\': '\\'}
    def unescape(match):
        if match[1] not in escapes:
            raise ValueError('Invalid private keyfile escape')
        return escapes[match[1]]
    key = re.sub(r'\\(.)|\\$', unescape, key)
    if (str(uuid.UUID(connection['uuid'])) != connection['uuid'] or
            connection.get('type') not in ('wifi', '802-11-wireless') or
            connection.get('interface-name') != 'wlan0' or
            connection.get('autoconnect', 'true') != 'true' or
            profile['wifi-security'].get('key-mgmt') != 'wpa-psk' or
            not re.fullmatch(r'[\x20-\x7e]{8,63}|[0-9a-fA-F]{64}', key)):
        raise ValueError('Expected an autoconnecting wlan0 WPA-PSK keyfile')
    if expected_address is not None and profile['wifi'].get('cloned-mac-address', '').lower() != expected_address:
        raise ValueError('Profile does not use the verified unit address')


def exclusive_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_state(directory, serial, identity_sha, *, uid=0):
    private_directory(directory, uid=uid)
    record = json.loads(private_bytes(directory / 'state.json', uid=uid))
    digest = record.get('profile_sha256', '')
    if (record.get('format') != 1 or record.get('serial') != serial or
            record.get('identity_sha256') != identity_sha or
            not re.fullmatch('[0-9a-f]{64}', digest)):
        raise ValueError('Wi-Fi state belongs to a different unit or identity receipt')
    data = private_bytes(directory / ('profile-' + digest + '.nmconnection'), uid=uid)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Saved Wi-Fi profile hash differs')
    validate_profile(data)
    return data, record


def save(directory, source, serial, identity_sha, *, replace=False, uid=0, expected_address=None):
    data = private_bytes(source, uid=uid)
    validate_profile(data, expected_address)
    private_directory(directory, create=True, uid=uid)
    if (directory / 'state.json').exists() or (directory / 'state.json').is_symlink():
        old, _ = read_state(directory, serial, identity_sha, uid=uid)
        if old != data and not replace:
            raise FileExistsError('Saved profile differs; replacement requires --replace')
    digest = hashlib.sha256(data).hexdigest()
    profile = directory / ('profile-' + digest + '.nmconnection')
    if profile.exists() or profile.is_symlink():
        if private_bytes(profile, uid=uid) != data:
            raise ValueError('Existing profile differs')
    else:
        exclusive_write(profile, data)
    record = {'format': 1, 'serial': serial, 'identity_sha256': identity_sha,
              'profile_sha256': digest}
    temporary = directory / ('.state-' + uuid.uuid4().hex)
    exclusive_write(temporary, (json.dumps(record, sort_keys=True) + '\n').encode())
    os.replace(temporary, directory / 'state.json')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def restore(directory, destination, serial, identity_sha, *, uid=0, expected_address=None):
    data, record = read_state(directory, serial, identity_sha, uid=uid)
    validate_profile(data, expected_address)
    private_directory(destination.parent, uid=uid, private=False)
    if destination.exists() or destination.is_symlink():
        if private_bytes(destination, uid=uid) != data:
            raise FileExistsError('Refusing to replace a different installed profile')
    else:
        exclusive_write(destination, data)
    return record


def existing_mount(mountinfo, number, writable):
    """Return a whole-filesystem f2fs mount of device number, or None if unmounted."""
    found = []
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 10 or fields[2] != number:
            continue
        separator = fields.index('-')
        if fields[3] != '/' or fields[separator + 1] != 'f2fs':
            continue
        point = fields[4].replace('\\040', ' ').replace('\\011', '\t').replace('\\012', '\n').replace('\\134', '\\')
        found.append((Path(point), 'rw' in fields[5].split(',')))
    if not found and any(line.split()[2:3] == [number] for line in mountinfo.splitlines()):
        raise ValueError('Userdata is mounted only as a subtree or another filesystem type')
    if not found:
        return None
    for point, is_writable in found:
        if is_writable or not writable:
            return point
    raise ValueError('Userdata is mounted read-only; saving needs a writable mount')


@contextmanager
def userdata_mount(expected_uuid, writable):
    device = Path('/dev/disk/by-partlabel/userdata')
    info = device.stat()
    if not stat.S_ISBLK(info.st_mode) or str(uuid.UUID(expected_uuid)) != expected_uuid:
        raise ValueError('Expected the selected userdata block device and UUID')
    number = str(os.major(info.st_rdev)) + ':' + str(os.minor(info.st_rdev))
    actual = subprocess.check_output(['blkid', '-s', 'UUID', '-o', 'value', str(device)], text=True).strip()
    if actual != expected_uuid:
        raise ValueError('Userdata UUID differs')
    # A session that already owns userdata is reused; f2fs is never mounted twice.
    current = existing_mount(Path('/proc/self/mountinfo').read_text(), number, writable)
    if current:
        yield current
        return
    mount = Path('/run') / ('pico-wifi-state-' + uuid.uuid4().hex)
    mount.mkdir(mode=0o700)
    options = 'rw,nodev,nosuid,noexec' if writable else 'ro,norecovery,nodev,nosuid,noexec'
    mounted = False
    try:
        subprocess.run(['mount', '-t', 'f2fs', '-o', options, str(device), str(mount)], check=True, timeout=30)
        mounted = True
        yield mount
    finally:
        if mounted:
            subprocess.run(['umount', str(mount)], check=True, timeout=30)
        mount.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('save', 'restore'))
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--userdata-uuid', required=True)
    parser.add_argument('--identity', type=Path, default=Path('/etc/reframed-vr/pico-radio-identities.json'))
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    if args.action == 'restore' and args.replace:
        parser.error('--replace applies only to saved state, not an installed profile')
    spec = importlib.util.spec_from_file_location('pico_wifi_identity', Path(__file__).with_name('pico-wifi-identity.py'))
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    identity.validate_device(args.boot_serial, args.boot_id)
    address, identity_sha = identity.load_identity(args.identity, args.boot_serial)
    fd = os.open('/run/pico-wifi-state.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('Expected a private root-owned state lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with userdata_mount(args.userdata_uuid, args.action == 'save') as mount:
            directory = mount / ('reframed-vr-wifi-state-' + args.boot_serial)
            if args.action == 'save':
                record = save(directory, args.profile, args.boot_serial, identity_sha,
                              replace=args.replace, expected_address=address)
            else:
                record = restore(directory, args.profile, args.boot_serial, identity_sha,
                                 expected_address=address)
            identity.validate_device(args.boot_serial, args.boot_id)
    print(json.dumps({'status': args.action + '-verified', 'profile_sha256': record['profile_sha256'],
                      'credentials_printed': False}), flush=True)


if __name__ == '__main__':
    main()
