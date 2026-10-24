#!/usr/bin/env python3
"""Validate the recorded cross-stream order of Neo3 controller SDK inputs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

MOTION_MAGIC = 0x52564354494D0001
IMAGE_MAGIC = 0x5256435443410002
MOTION_SIZE = 832
PIXELS = 640 * 480
IMAGE_SIZE = 24 + 2 * 368 + 4 * (64 + PIXELS)
FRAME = struct.Struct('<B3x7I2qQ2I')


def header(stream, magic, size, maximum):
    raw = stream.read(32)
    if len(raw) != 32:
        raise ValueError('Incomplete acquisition header')
    value, version, stride, capacity = struct.unpack('<4Q', raw)
    if (value, version, stride) != (magic, 2, size) or not 1 <= capacity <= maximum:
        raise ValueError('Requires bounded version-2 inputs with recorded dispatch order')
    return capacity


def bracket(raw, timestamp):
    before, after = raw[:368], raw[368:]
    a, b = struct.unpack_from('<q', before)[0], struct.unpack_from('<q', after)[0]
    if not 0 < a < timestamp < b:
        raise ValueError('Input is not bracketed by head timestamps')
    for pose in (before, after):
        q = struct.unpack_from('<4d', pose, 32)
        p = struct.unpack_from('<3d', pose, 8)
        if (pose[64:66] != b'\x01\x01' or
                not all(math.isfinite(x) for x in (*p, *q)) or
                abs(sum(x*x for x in q)-1) > .0001):
            raise ValueError('Invalid tracked head bracket')


def records(path, kind):
    size, magic, maximum = ((MOTION_SIZE, MOTION_MAGIC, 4096) if kind == 'motion'
                            else (IMAGE_SIZE, IMAGE_MAGIC, 150))
    with path.open('rb') as stream:
        capacity = header(stream, magic, size, maximum)
        length = path.stat().st_size - 32
        if length % size or not 1 <= length // size <= capacity:
            raise ValueError('Incomplete or empty acquisition records')
        previous_time, previous_order = 0, 0
        events = []
        for index in range(length // size):
            row = stream.read(size)
            if len(row) != size:
                raise ValueError('Acquisition changed while reading')
            timestamp, generation, order = struct.unpack_from('<3Q', row)
            if not generation or not previous_time < timestamp <= (1 << 63)-1 or order <= previous_order:
                raise ValueError('Regressing capture time, dispatch order or missing generation')
            if kind == 'motion':
                if not all(math.isfinite(x) for x in struct.unpack_from('<9d', row, 24)):
                    raise ValueError('Nonfinite controller IMU input')
                bracket(row[96:], timestamp)
            else:
                bracket(row[24:760], timestamp)
                numbers = set()
                for camera in range(4):
                    values = FRAME.unpack_from(row, 760 + camera * (64 + PIXELS))
                    c, w, h, fmt, typ, exposure, gain, reserved, sof, center, number, pixels, pad = values
                    if (c, w, h, fmt, typ, center, pixels) != (camera, 640, 480, 0x123, 0, timestamp, PIXELS):
                        raise ValueError('Unsupported camera identity, geometry or timestamp')
                    if sof <= 0 or center > sof:
                        raise ValueError('Invalid exposure timing')
                    numbers.add(number)
                if len(numbers) != 1:
                    raise ValueError('Mixed camera frame numbers')
            events.append({'kind': kind, 'dispatch_order': order, 'timestamp_ns': timestamp,
                           'generation': generation, 'offset': 32 + index * size, 'bytes': size})
            previous_time, previous_order = timestamp, order
    return events


def analyze(motion, images):
    inputs = {}
    for kind, path in [('motion', motion), ('images', images)]:
        with path.open('rb') as stream:
            inputs[kind] = hashlib.file_digest(stream, 'sha256').hexdigest()
    events = records(motion, 'motion') + records(images, 'images')
    events.sort(key=lambda row: row['dispatch_order'])
    if [e['dispatch_order'] for e in events] != list(range(1, len(events)+1)):
        raise ValueError('Missing or duplicate cross-stream dispatch order')
    if len({e['generation'] for e in events}) != 1:
        raise ValueError('Mixed estimator generations')
    for kind, path in [('motion', motion), ('images', images)]:
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != inputs[kind]:
                raise ValueError('Acquisition changed during analysis')
    return {'scope': 'Recorded SDK call ordering and head brackets; no optical tracking or timing acceptance',
            'format_version': 2, 'source_sha256': inputs, 'events': events,
            'motion_records': sum(e['kind'] == 'motion' for e in events),
            'image_sets': sum(e['kind'] == 'images' for e in events),
            'dispatch_order_recorded': True, 'original_wall_timing_reproduced': False,
            'optical_tracking_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--motion', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.motion, args.images), indent=2))


if __name__ == '__main__':
    main()
