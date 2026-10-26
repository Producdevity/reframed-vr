#!/usr/bin/env python3
"""Opt-in CFS nice -20 for one owned, single-threaded Neo3 capture process.

Only nice is changed. Identity, executable bytes, policy, affinity and limits
are checked around writes; proc checks cannot make PID reuse atomic.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import time

_SPEC = importlib.util.spec_from_file_location('pico_ipc_priority',
    Path(__file__).with_name('pico-steamvr-ipc-priority.py'))
_IPC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IPC)
validate_device = _IPC.validate_device
PROC = Path('/proc')
LOCK = Path('/run/reframed-pico-camera-priority.lock')
EXE = Path('/run/neo3-vio-fresh/capture-steamvr')
GROUP = '0::/system.slice/pico-owned-live-test.service'


def validate_target(pid, binary_sha256):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Expected an explicit positive capture PID')
    if not isinstance(binary_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', binary_sha256):
        raise ValueError('Expected the canonical lowercase capture SHA-256')


def process_start(path, pid):
    raw = (path/'stat').read_text()
    prefix, fields = raw.rsplit(') ', 1)
    if prefix != str(pid)+' (capture-steamvr':
        raise ValueError('Requires the capture main thread')
    start = int(fields.split()[19])
    if start <= 0:
        raise ValueError('Invalid capture start identity')
    return start


def executable_identity(proc, expected):
    if os.readlink(proc/'exe') != str(EXE):
        raise ValueError('Capture executable path changed')
    with (proc/'exe').open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Capture executable must be root-owned and not group/world writable')
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    attributes = ['st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                  'st_size', 'st_mtime_ns', 'st_ctime_ns']
    identity = {key: getattr(info, key) for key in attributes}
    if identity != {key: getattr(after, key) for key in attributes} or checksum != expected:
        raise ValueError('Capture executable bytes or metadata changed')
    return identity | {'sha256': checksum, 'path': str(EXE)}


def snapshot(pid, binary_sha256):
    validate_target(pid, binary_sha256)
    proc = PROC/str(pid)
    task = proc/'task'/str(pid)
    starts = [process_start(path, pid) for path in (proc, task)]
    if starts[0] != starts[1] or sorted(p.name for p in (proc/'task').iterdir()) != [str(pid)]:
        raise ValueError('Requires one capture main thread')
    for path in (proc, task):
        users = re.findall(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',
                           (path/'status').read_text(), re.M)
        if (users != [('0',)*4] or (path/'comm').read_text().strip() != 'capture-steamvr' or
                (path/'cgroup').read_text().splitlines() != [GROUP]):
            raise ValueError('Requires the owned root capture task')
    if (proc/'cmdline').read_bytes() != os.fsencode(EXE)+b'\0--capture\0':
        raise ValueError('Requires the exact capture command')
    executable = executable_identity(proc, binary_sha256)
    limits = (proc/'limits').read_text()
    if not limits.strip() or (task/'limits').read_text() != limits:
        raise ValueError('Capture resource limits are unavailable or inconsistent')
    state = {'pid': pid, 'tid': pid, 'process_start': starts[0], 'thread_start': starts[1],
             'executable': executable, 'policy': os.sched_getscheduler(pid),
             'rt_priority': os.sched_getparam(pid).sched_priority,
             'affinity': sorted(os.sched_getaffinity(pid)),
             'nice': os.getpriority(os.PRIO_PROCESS, pid), 'limits': limits}
    if starts != [process_start(path, pid) for path in (proc, task)]:
        raise ValueError('Capture identity changed during inspection')
    return state


def stable_fields(state):
    return {key: value for key, value in state.items() if key != 'nice'}


@contextmanager
def prioritize_capture(serial, boot, pid, binary_sha256):
    validate_target(pid, binary_sha256)
    validate_device(serial, boot)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Priority lock must be a private 0600 root-owned regular file')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot(pid, binary_sha256)
        if (before['policy'], before['rt_priority'], before['nice']) != (os.SCHED_OTHER, 0, 0) or not before['affinity']:
            raise ValueError('Requires the unchanged OTHER0/nice0 capture task')
        record = {'boot_id': boot, 'before': before}
        active_verified = False
        try:
            os.setpriority(os.PRIO_PROCESS, pid, -20)
            validate_device(serial, boot)
            active = snapshot(pid, binary_sha256)
            if active != before | {'nice': -20}:
                raise RuntimeError('Capture priority readback or identity changed')
            active_verified = True
            record['active'] = active
            yield record
        finally:
            validate_device(serial, boot)
            try:
                current = snapshot(pid, binary_sha256)
            except (FileNotFoundError, ProcessLookupError):
                if (PROC/str(pid)).exists():
                    raise RuntimeError('Capture inspection failed while the process still exists')
                record['restoration'] = 'owned-capture-exited'
            else:
                if stable_fields(current) != stable_fields(before):
                    raise RuntimeError('Capture identity, policy, affinity or limits changed; restoration refused')
                if not active_verified and current == before:
                    record['after'] = current
                    record['restoration'] = 'unchanged'
                else:
                    if current['nice'] != -20:
                        raise RuntimeError('Capture nice changed; restoration refused')
                    os.setpriority(os.PRIO_PROCESS, pid, before['nice'])
                    validate_device(serial, boot)
                    record['after'] = snapshot(pid, binary_sha256)
                    if record['after'] != before:
                        raise RuntimeError('Capture priority restoration failed')
                    record['restoration'] = 'restored'
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--binary-sha256', required=True)
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
        with prioritize_capture(args.boot_serial, args.boot_id, args.pid, args.binary_sha256) as record:
            print('PICO_CAMERA_PRIORITY_READY '+json.dumps(record), flush=True)
            deadline = time.monotonic()+args.seconds
            while not stopped and time.monotonic() < deadline:
                time.sleep(.05)
        print('PICO_CAMERA_PRIORITY_RESTORED '+json.dumps(record), flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
