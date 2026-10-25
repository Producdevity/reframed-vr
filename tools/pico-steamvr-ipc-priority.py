#!/usr/bin/env python3
"""Temporarily raise one owned Neo3 Steam API worker's ordinary CFS priority."""
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
import time
import uuid

PROC = Path('/proc')
LOCK = Path('/run/reframed-pico-steam-ipc-priority.lock')
GROUP = '0::/system.slice/pico-steamvr-steam-overlay-controller-render-v1.service'


def validate_device(serial, boot):
    if (platform.system() != 'Linux' or platform.machine() != 'aarch64' or os.geteuid() != 0 or
            not re.fullmatch(r'[A-Za-z0-9]{1,32}', serial) or
            'androidboot.serialno='+serial not in (PROC/'cmdline').read_text().split() or
            Path('/proc/device-tree/compatible').read_bytes() !=
            b'qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0'):
        raise ValueError('Requires the selected native Linux Pico Neo3 as root')
    if str(uuid.UUID(boot)) != boot or (PROC/'sys/kernel/random/boot_id').read_text().strip() != boot:
        raise ValueError('Pico boot identity changed')


def snapshot(pid, tid):
    if any(type(value) is not int or value <= 0 for value in (pid, tid)):
        raise ValueError('Expected explicit positive process and thread IDs')
    proc = PROC/str(pid)
    task = proc/'task'/str(tid)
    user = next(line.split()[1:] for line in (proc/'status').read_text().splitlines()
                if line.startswith('Uid:'))
    raw = (task/'stat').read_text()
    if (user != ['1000']*4 or (proc/'comm').read_text().strip() != 'steamwebhelper' or
            (proc/'exe').resolve(strict=True).name != 'steamwebhelper' or
            GROUP not in (proc/'cgroup').read_text().splitlines() or
            raw.split('(', 1)[1].rsplit(')', 1)[0] != 'CVRAPIITask::Ru'):
        raise ValueError('Requires the owned Steam UI API worker')
    return {'pid': pid, 'tid': tid,
            'process_start': int((proc/'stat').read_text().rsplit(') ', 1)[1].split()[19]),
            'thread_start': int(raw.rsplit(') ', 1)[1].split()[19]),
            'policy': os.sched_getscheduler(tid),
            'rt_priority': os.sched_getparam(tid).sched_priority,
            'affinity': sorted(os.sched_getaffinity(tid)),
            'nice': os.getpriority(os.PRIO_PROCESS, tid)}


@contextmanager
def prioritize_worker(serial, boot, pid, tid):
    validate_device(serial, boot)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('Priority lock must be private and root-owned')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot(pid, tid)
        if (before['policy'], before['rt_priority'], before['nice']) != (os.SCHED_OTHER, 0, 0):
            raise ValueError('Requires the unchanged ordinary-priority worker')
        record = {'boot_id': boot, 'before': before}
        try:
            os.setpriority(os.PRIO_PROCESS, tid, -20)
            validate_device(serial, boot)
            active = snapshot(pid, tid)
            if active != before | {'nice': -20}:
                raise RuntimeError('Worker priority readback or identity changed')
            record['active'] = active
            yield record
        finally:
            validate_device(serial, boot)
            try:
                current = snapshot(pid, tid)
            except (FileNotFoundError, ProcessLookupError):
                if (PROC/str(pid)/'task'/str(tid)/'stat').exists():
                    raise RuntimeError('Worker inspection failed while the task still exists')
                record['restoration'] = 'owned-worker-exited'
            else:
                if {k: v for k, v in current.items() if k != 'nice'} != {k: v for k, v in before.items() if k != 'nice'}:
                    raise RuntimeError('Worker identity or policy changed; restoration refused')
                os.setpriority(os.PRIO_PROCESS, tid, before['nice'])
                record['after'] = snapshot(pid, tid)
                if record['after'] != before:
                    raise RuntimeError('Worker priority restoration failed')
                record['restoration'] = 'restored'
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--tid', type=int, required=True)
    parser.add_argument('--seconds', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error('--seconds must be between 1 and 900')
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    handlers = {}
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.signal(sig, stop)
        with prioritize_worker(args.boot_serial, args.boot_id, args.pid, args.tid) as record:
            print('PICO_STEAM_IPC_PRIORITY_READY '+json.dumps(record), flush=True)
            deadline = time.monotonic()+args.seconds
            while not stopped and time.monotonic() < deadline:
                time.sleep(.05)
        print('PICO_STEAM_IPC_PRIORITY_RESTORED '+json.dumps(record), flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
