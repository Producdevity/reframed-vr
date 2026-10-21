#!/usr/bin/env python3
"""Pack the native Quest RAM-only USB initramfs from a verified static BusyBox."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import stat
import struct

ROOT = Path(__file__).resolve().parents[1]
APPLETS = ('sh', 'mount', 'mkdir', 'sleep', 'reboot', 'setsid', 'cat', 'uname',
           'hostname', 'ln')


def static_arm64(data):
    if (len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01' or
            struct.unpack_from('<HH', data, 16) != (2, 183)):
        raise ValueError('Requires a static little-endian ARM64 executable')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if size != 56 or not 0 < count < 128 or offset + size * count > len(data):
        raise ValueError('Invalid ELF program headers')
    if any(struct.unpack_from('<I', data, offset + i * size)[0] in (2, 3) for i in range(count)):
        raise ValueError('BusyBox must have no dynamic linker or dynamic dependencies')


def archive(binary, init):
    entries = [(name, stat.S_IFDIR | 0o755, b'') for name in ('bin', 'dev', 'proc', 'sys', 'run')]
    entries.extend((('init', stat.S_IFREG | 0o755, init),
                    ('bin/busybox', stat.S_IFREG | 0o755, binary)))
    entries.extend(('bin/' + name, stat.S_IFLNK | 0o777, b'busybox') for name in APPLETS)
    result = bytearray()
    for inode, (name, mode, data) in enumerate(entries + [('TRAILER!!!', 0, b'')], 1):
        encoded = name.encode() + b'\0'
        fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
        result.extend(b'070701' + ''.join(f'{value:08x}' for value in fields).encode() + encoded)
        result.extend(b'\0' * (-len(result) % 4))
        result.extend(data)
        result.extend(b'\0' * (-len(result) % 4))
    return bytes(result), entries


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--busybox', type=Path, required=True)
    parser.add_argument('--busybox-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.busybox.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', args.busybox_sha256) or digest(binary) != args.busybox_sha256:
        raise ValueError('BusyBox checksum differs from the verified input')
    static_arm64(binary)
    init = (ROOT / 'system/quest/ram-usb-init').read_bytes()
    cpio, entries = archive(binary, init)
    data = gzip.compress(cpio, compresslevel=9, mtime=0)
    if args.output.exists():
        raise ValueError('Output must be a new directory')
    args.output.mkdir(parents=True)
    (args.output / 'initramfs.cpio.gz').write_bytes(data)
    report = {'status': 'assembled', 'hardware_boot_verified': False, 'device_actions': [],
              'busybox_sha256': digest(binary), 'init_sha256': digest(init),
              'initramfs_sha256': digest(data), 'bytes': len(data),
              'required_applets': APPLETS, 'applets_runtime_checked': False,
              'required_command_line': 'reframed.ram_usb=1',
              'files': [{'path': name, 'mode': oct(mode), 'sha256': digest(content)}
                        for name, mode, content in entries]}
    (args.output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(args.output / 'manifest.json')


if __name__ == '__main__':
    main()
