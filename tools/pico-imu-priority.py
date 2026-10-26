#!/usr/bin/env python3
"""Opt-in CFS nice -20 for the owned Neo3 producer's existing ssc-imu thread.

Only the explicit reader TID's nice value is written. Proc identity checks do
not make PID/TID reuse atomic. No default activation or SDK-thread selection.
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
LOCK = Path('/run/reframed-pico-imu-priority.lock')
EXE = Path('/run/neo3-vio-fresh/producer-live')
VIO = '/run/neo3-vendor-slam-v1/vio-v1.ring'
GROUP = '0::/system.slice/pico-owned-live-test.service'
MAX_TASKS = 64


def validate_target(pid, tid, binary_sha256):
    if any(type(value) is not int or value <= 0 for value in (pid, tid)) or pid == tid:
        raise ValueError('Expected explicit positive producer PID and separate reader TID')
    if not isinstance(binary_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', binary_sha256):
        raise ValueError('Expected canonical lowercase producer SHA-256')


def identity(path, tid, comm=None, allow_dead=False):
    prefix, tail = (path/'stat').read_text().rsplit(') ', 1)
    match = re.fullmatch(r'(\d+) \((.*)', prefix)
    fields = tail.split()
    if not match or int(match[1]) != tid or len(fields) < 20 or (comm is not None and match[2] != comm):
        raise ValueError('Producer/task identity differs')
    start = int(fields[19])
    if start <= 0 or (not allow_dead and fields[0] in ('Z', 'X', 'x')):
        raise ValueError('Producer/task is not live')
    return {'start': start, 'comm': match[2], 'state': fields[0]}


def ownership(path, comm):
    users = re.findall(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',
                       (path/'status').read_text(), re.M)
    if (users != [('0',)*4] or (path/'comm').read_text().strip() != comm or
            (path/'cgroup').read_text().splitlines() != [GROUP]):
        raise ValueError('Requires the owned root producer task')


def executable_identity(proc, expected):
    if os.readlink(proc/'exe') != str(EXE):
        raise ValueError('Producer executable path changed')
    with (proc/'exe').open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Producer executable must be root-owned and not group/world writable')
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    attributes = ['st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                  'st_size', 'st_mtime_ns', 'st_ctime_ns']
    result = {key: getattr(info, key) for key in attributes}
    if result != {key: getattr(after, key) for key in attributes} or checksum != expected:
        raise ValueError('Producer executable bytes or metadata changed')
    return result | {'sha256': checksum, 'path': str(EXE)}


def task_ids(proc):
    result = sorted(int(path.name) for path in (proc/'task').iterdir())
    if not 2 <= len(result) <= MAX_TASKS:
        raise ValueError('Producer task inventory exceeds expected bounds')
    return result


def snapshot(pid, tid, binary_sha256):
    validate_target(pid, tid, binary_sha256)
    proc = PROC/str(pid)
    process = identity(proc, pid, 'producer-live')
    ownership(proc, 'producer-live')
    if (proc/'cmdline').read_bytes() != b'\0'.join(os.fsencode(x) for x in (EXE, VIO, '300'))+b'\0':
        raise ValueError('Requires the exact owned producer command')
    executable = executable_identity(proc, binary_sha256)
    limits = (proc/'limits').read_text()
    if not limits.strip():
        raise ValueError('Producer limits unavailable')
    tids = task_ids(proc)
    if pid not in tids or tid not in tids:
        raise ValueError('Reader is not a member of the producer')
    tasks = []
    for number in tids:
        path = proc/'task'/str(number)
        item = identity(path, number)
        ownership(path, item['comm'])
        if (path/'limits').read_text() != limits:
            raise ValueError('Producer task limits differ')
        tasks.append({'tid': number, 'start': item['start'], 'comm': item['comm'],
                      'policy': os.sched_getscheduler(number),
                      'rt_priority': os.sched_getparam(number).sched_priority,
                      'nice': os.getpriority(os.PRIO_PROCESS, number),
                      'affinity': sorted(os.sched_getaffinity(number))})
    if [task['tid'] for task in tasks if task['comm'] == 'ssc-imu'] != [tid]:
        raise ValueError('Requires the unique existing ssc-imu reader')
    main = next(task for task in tasks if task['tid'] == pid)
    if main['start'] != process['start'] or main['comm'] != 'producer-live':
        raise ValueError('Producer main identity differs')
    if tids != task_ids(proc) or identity(proc, pid, 'producer-live')['start'] != process['start']:
        raise ValueError('Producer identity changed during inspection')
    for task in tasks:
        check = identity(proc/'task'/str(task['tid']), task['tid'], task['comm'])
        if check['start'] != task['start']:
            raise ValueError('Producer task changed during inspection')
    reader = next(task for task in tasks if task['tid'] == tid)
    return {'pid': pid, 'tid': tid, 'process_start': process['start'], 'thread_start': reader['start'],
            'executable': executable, 'limits': limits, 'tasks': tasks,
            **{key: reader[key] for key in ('policy', 'rt_priority', 'nice', 'affinity')}}


def target_nice(state, nice):
    return state | {'nice': nice, 'tasks': [task | {'nice': nice} if task['tid'] == state['tid'] else dict(task)
                                          for task in state['tasks']]}


def exited_reason(before):
    proc = PROC/str(before['pid'])
    task = proc/'task'/str(before['tid'])
    for path, number, comm, start, label in (
            (proc, before['pid'], 'producer-live', before['process_start'], 'producer'),
            (task, before['tid'], 'ssc-imu', before['thread_start'], 'imu-thread')):
        try:
            current = identity(path, number, comm, allow_dead=True)
        except (FileNotFoundError, ProcessLookupError):
            if path.exists():
                raise RuntimeError('Target inspection failed while its proc directory exists')
            return 'owned-'+label+'-exited'
        if current['start'] != start:
            raise RuntimeError('Target identity changed; restoration refused')
        if current['state'] in ('Z', 'X', 'x'):
            return 'owned-'+label+'-not-live'
    return None


@contextmanager
def prioritize_imu(serial, boot, pid, tid, binary_sha256):
    validate_target(pid, tid, binary_sha256)
    validate_device(serial, boot)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Priority lock must be a private 0600 root-owned regular file')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot(pid, tid, binary_sha256)
        if (before['policy'], before['rt_priority'], before['nice']) != (os.SCHED_OTHER, 0, 0) or not before['affinity']:
            raise ValueError('Requires the unchanged OTHER0/nice0 IMU reader')
        record = {'boot_id': boot, 'before': before}
        active_verified = False
        try:
            os.setpriority(os.PRIO_PROCESS, tid, -20)
            validate_device(serial, boot)
            active = snapshot(pid, tid, binary_sha256)
            if active != target_nice(before, -20):
                raise RuntimeError('IMU priority readback or producer state changed')
            active_verified = True
            record['active'] = active
            yield record
        finally:
            validate_device(serial, boot)
            gone = exited_reason(before)
            if gone:
                record['restoration'] = gone
            else:
                current = snapshot(pid, tid, binary_sha256)
                if target_nice(current, before['nice']) != before:
                    raise RuntimeError('Producer/task identity, policy, affinity or limits changed; restoration refused')
                if not active_verified and current == before:
                    record['after'] = current
                    record['restoration'] = 'unchanged'
                else:
                    if current['nice'] != -20:
                        raise RuntimeError('IMU nice changed; restoration refused')
                    os.setpriority(os.PRIO_PROCESS, tid, before['nice'])
                    validate_device(serial, boot)
                    record['after'] = snapshot(pid, tid, binary_sha256)
                    if record['after'] != before:
                        raise RuntimeError('IMU priority restoration failed')
                    record['restoration'] = 'restored'
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--tid', type=int, required=True)
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
        with prioritize_imu(args.boot_serial, args.boot_id, args.pid, args.tid, args.binary_sha256) as record:
            print('PICO_IMU_PRIORITY_READY '+json.dumps(record), flush=True)
            deadline = time.monotonic()+args.seconds
            while not stopped and time.monotonic() < deadline:
                time.sleep(.05)
        print('PICO_IMU_PRIORITY_RESTORED '+json.dumps(record), flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
