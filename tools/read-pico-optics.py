#!/usr/bin/env python3
"""Read the stock Neo3 b1977 display/lens getters without changing device settings."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import time

FINGERPRINT = 'Pico/A7H10/PICOA7H10:10/5.8.4.0/smartcm.1696861506:user/test-keys'
CLIENT_SHA256 = '727c0f91007a65677899c0212835d57d031ab35633818dbd462bc1ee55083aaf'


def parcel(text, size):
    if not text.startswith('Result: Parcel('):
        raise ValueError('Expected a successful raw Binder parcel')
    data = bytearray()
    for line in text.splitlines()[1:]:
        if line.strip() == ')':
            continue
        match = re.fullmatch(r"\s*0x([0-9a-fA-F]{8}):((?:\s+[0-9a-fA-F]{8}){1,4})\s+'[^\r\n]*'\)?", line)
        if not match or int(match[1], 16) != len(data):
            raise ValueError('Malformed or discontinuous Binder parcel')
        data.extend(b''.join(struct.pack('<I', int(word, 16)) for word in match[2].split()))
    if len(data) != size + 4 or struct.unpack_from('<i', data, size)[0] != 0:
        raise ValueError('Unexpected getter response size or nonzero status')
    return bytes(data[:size])


def display_info(data):
    if len(data) != 96:
        raise ValueError('Expected the b1977 display record')
    word = lambda offset: struct.unpack_from('<I', data, offset)[0]
    number = lambda offset: struct.unpack_from('<f', data, offset)[0]
    result = {'width_pixels': word(8), 'height_pixels': word(12),
              'xdpi': number(16), 'ydpi': number(20), 'service_refresh_hz': number(24),
              'refresh_direction': word(28), 'orientation_degrees': word(32),
              'width_m': number(36), 'height_m': number(40), 'screen_gap_m': number(48)}
    if ((result['width_pixels'], result['height_pixels']) != (3664, 1920) or
            result['orientation_degrees'] not in (0, 90, 180, 270) or
            result['refresh_direction'] not in (0, 1)):
        raise ValueError('Unsupported Neo3 display geometry')
    for name, low, high in [('xdpi', 100, 2000), ('ydpi', 100, 2000),
                            ('service_refresh_hz', 30, 240), ('width_m', .05, .3),
                            ('height_m', .02, .2), ('screen_gap_m', 0, .02)]:
        if not math.isfinite(result[name]) or not low <= result[name] <= high:
            raise ValueError('Invalid display parameter: ' + name)
    return result


def lens_info(data):
    if len(data) != 128:
        raise ValueError('Expected the b1977 lens record')
    values = struct.unpack_from('<3fI24f', data)
    if (not all(math.isfinite(v) for v in (*values[:3], *values[4:])) or
            not .03 <= values[0] <= .09 or not 60 < values[1] < 160 or
            not .001 <= values[2] <= .1 or values[3] != 2 or
            any(abs(v) > 1000000 for v in values[4:])):
        raise ValueError('Invalid or unsupported stock lens parameters')
    return {'lens_separation_m': values[0], 'fov_degrees': values[1],
            'meters_per_tan_angle_at_center': values[2], 'equation_type': values[3],
            'distortion_coefficients': list(values[4:24]),
            'chromatic_aberration': list(values[24:28]),
            'axis_offsets_mm': list(values[18:22])}


def collect(adb, serial, boot_serial):
    if not re.fullmatch(r'[A-Za-z0-9]+', serial) or not re.fullmatch(r'[A-Za-z0-9]+', boot_serial):
        raise ValueError('Expected explicit USB serials')
    records = []

    def run(arguments):
        command = [adb, '-s', serial, 'shell', *arguments]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        records.append({'arguments': arguments, 'returncode': result.returncode,
                        'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise ValueError('Read-only device command failed: ' + str(arguments))
        return result.stdout.strip()

    identity = run(['getprop', 'ro.boot.serialno'])
    fingerprint = run(['getprop', 'ro.build.fingerprint'])
    if identity != boot_serial or fingerprint != FINGERPRINT:
        raise ValueError('Device identity or getter ABI differs from the verified stock build')
    checksum = run(['sha256sum', '/system/lib64/libpvrserviceclient.so']).split()[0]
    if checksum != CLIENT_SHA256:
        raise ValueError('Stock Binder client differs from the verified getter implementation')
    services = run(['service', 'list'])
    if not re.search(r'\bpxrhmdservice: \[android\.Service\.PxrHmdService\]', services):
        raise ValueError('Expected the verified HMD Binder interface')
    display = parcel(run(['service', 'call', 'pxrhmdservice', '4', *(['i32', '0'] * 24)]), 96)
    lens = parcel(run(['service', 'call', 'pxrhmdservice', '5', *(['i32', '0'] * 32)]), 128)
    if run(['getprop', 'ro.boot.serialno']) != identity:
        raise ValueError('Device changed during collection')
    return {'schema_version': 1, 'status': 'stock-optical-getters-verified',
            'time_unix': time.time(), 'adb_serial': serial, 'boot_serial': identity,
            'fingerprint': fingerprint, 'binder_client_sha256': checksum,
            'display': display_info(display), 'lens': lens_info(lens),
            'raw_records': {'display_hex': display.hex(), 'lens_hex': lens.hex()},
            'optical_alignment_verified': False, 'projection_matrices_verified': False,
            'runtime_profile': False, 'device_writes': False, 'commands': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('Output already exists')
    result = collect(args.adb, args.serial, args.boot_serial)
    result['collector_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('PICO_STOCK_OPTICS_PASS', args.output)


if __name__ == '__main__':
    main()
