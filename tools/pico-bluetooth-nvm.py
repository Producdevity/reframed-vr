#!/usr/bin/env python3
"""Generate a private b1977 Bluetooth NVM copy containing the verified unit address."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct


SOURCE_SHA256 = '697a967b880d1f3238dddb2feab385095a193805d2c09ca9f378544da1da543d'
SOURCE_SIZE = 5745
DEFAULT_ADDRESS = bytes.fromhex('ad5a00000000')


def address_span(data):
    if len(data) < 4:
        raise ValueError('Truncated NVM header')
    header, = struct.unpack_from('<I', data)
    if header & 255 != 2 or header >> 8 != len(data) - 4:
        raise ValueError('Expected one complete type-2 NVM table')
    offset, spans = 4, []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('Truncated NVM tag header')
        tag, length = struct.unpack_from('<HH', data, offset)
        begin = offset + 12
        if begin + length > len(data):
            raise ValueError('Truncated NVM tag payload')
        if tag == 2:
            if length != 6:
                raise ValueError('Unexpected Bluetooth address length')
            spans.append((begin, begin + length))
        offset = begin + length
    if len(spans) != 1:
        raise ValueError('Expected exactly one Bluetooth address tag')
    return spans[0]


def personalize(source, address):
    if len(source) != SOURCE_SIZE or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unrecognized stock b1977 NVM')
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', address):
        raise ValueError('Expected a normalized unit address')
    octets = bytes.fromhex(address.replace(':', ''))
    if octets[0] & 1 or octets in (bytes(6), b'\xff' * 6):
        raise ValueError('Expected a unicast unit address')
    begin, end = address_span(source)
    if source[begin:end] != DEFAULT_ADDRESS or octets[::-1] == DEFAULT_ADDRESS:
        raise ValueError('Unexpected source or target address')
    return source[:begin] + octets[::-1] + source[end:]


def generate(source, identity, boot_serial, destination):
    spec = importlib.util.spec_from_file_location(
        'pico_bluetooth_identity', Path(__file__).with_name('pico-bluetooth-identity.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    address, identity_sha = module.load_identity(identity, boot_serial)
    original = source.read_bytes()
    data = personalize(original, address)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    return {'source_sha256': SOURCE_SHA256, 'identity_sha256': identity_sha,
            'output_sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'address_span': list(address_span(data)),
            'scope': 'Generated copy only; no firmware or device writes. Only the six address bytes change.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.source, args.identity, args.boot_serial, args.output)), flush=True)


if __name__ == '__main__':
    main()
