#!/usr/bin/env python3
"""Bounded Neo3 KGSL callback priority; restores the previous queue policy."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import threading
import uuid

QUEUE = Path('/sys/bus/workqueue/devices/kgsl-events')
LOCK = Path('/run/reframed-pico-gpu-events.lock')
ATTRIBUTES = ('nice', 'cpumask', 'max_active', 'numa')


def validate_device(boot_serial, boot_id):
    if (platform.system() != 'Linux' or os.geteuid() != 0 or
            not re.fullmatch(r'[A-Za-z0-9]{1,32}', boot_serial) or
            'androidboot.serialno=' + boot_serial not in Path('/proc/cmdline').read_text().split() or
            b'qcom,kona-iot' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')):
        raise ValueError('Requires the selected native Linux Pico Neo3 as root')
    if (str(uuid.UUID(boot_id)) != boot_id or
            Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_id):
        raise ValueError('Pico boot identity changed')


def snapshot():
    return {name: (QUEUE / name).read_text().strip() for name in ATTRIBUTES}


@contextmanager
def prioritize_events(boot_serial, boot_id):
    validate_device(boot_serial, boot_id)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('GPU event policy lock must be private and root-owned')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot()
        if not -20 <= int(before['nice']) <= 19:
            raise ValueError('Invalid existing KGSL callback priority')
        record = {'boot_id': boot_id, 'boot_serial': boot_serial, 'before': before}
        try:
            (QUEUE / 'nice').write_text('-20\n')
            active = snapshot()
            if active != before | {'nice': '-20'}:
                raise RuntimeError('KGSL queue priority readback failed')
            record['active'] = active
            yield record
        finally:
            (QUEUE / 'nice').write_text(before['nice'] + '\n')
            after = snapshot()
            record['after'] = after
            if after != before:
                raise RuntimeError('KGSL queue policy restoration failed')
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--seconds', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error('--seconds must be between 1 and 900')
    stopped = threading.Event()
    previous = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, lambda *_: stopped.set())
        with prioritize_events(args.boot_serial, args.boot_id) as record:
            print('PICO_GPU_EVENTS_READY ' + json.dumps(record), flush=True)
            stopped.wait(args.seconds)
        print('PICO_GPU_EVENTS_RESTORED ' + json.dumps(record), flush=True)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    main()
