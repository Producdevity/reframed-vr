#!/usr/bin/env python3
"""Opt-in RR2 for an owned Neo3 renderer after an owning-session UI-ready receipt.

The receipt's tid attests the GPU submitter; this is a trusted session gate,
not independent attestation. Proc identity checks cannot make TID reuse atomic.
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
LOCK = Path('/run/reframed-pico-steam-render-priority.lock')
GROUP = '0::/system.slice/pico-steamvr-compositor-controller-render-v1.service'
LIMITS = {'rtprio': [2, 2], 'rttime_us': [100000, 100000]}


def snapshot(pid, tid):
    if any(type(value) is not int or value <= 0 for value in (pid, tid)):
        raise ValueError('Expected explicit positive process and thread IDs')
    proc = PROC/str(pid)
    task = proc/'task'/str(tid)
    for path in (proc, task):
        users = re.findall(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',
                           (path/'status').read_text(), re.M)
        if users != [('1000',)*4] or (path/'cgroup').read_text().splitlines() != [GROUP]:
            raise ValueError('Requires the owned UID1000 compositor task')
    raw = (task/'stat').read_text()
    executable = (proc/'exe').resolve(strict=True)
    if ((proc/'comm').read_text().strip() != 'vrcompositor' or executable.name != 'vrcompositor' or
            raw.split('(', 1)[1].rsplit(')', 1)[0] != 'RenderThread'):
        raise ValueError('Requires vrcompositor RenderThread')
    limits = (proc/'limits').read_text()
    parsed = {}
    for key, label, suffix in [('rtprio', 'Max realtime priority', ''),
                               ('rttime_us', 'Max realtime timeout', r'\s+us')]:
        match = re.findall(r'^'+label+r'\s+(\d+)\s+(\d+)'+suffix+r'\s*$', limits, re.M)
        if len(match) != 1:
            raise ValueError('Missing numeric realtime resource limits')
        parsed[key] = [int(v) for v in match[0]]
    return {'pid': pid, 'tid': tid, 'executable': str(executable),
            'process_start': int((proc/'stat').read_text().rsplit(') ', 1)[1].split()[19]),
            'thread_start': int(raw.rsplit(') ', 1)[1].split()[19]),
            'policy': os.sched_getscheduler(tid),
            'rt_priority': os.sched_getparam(tid).sched_priority,
            'affinity': sorted(os.sched_getaffinity(tid)),
            'nice': os.getpriority(os.PRIO_PROCESS, tid), 'limits': parsed}


def private_regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
            info.st_nlink == 1 and not info.st_mode & 0o077)


def ready_receipt(path, boot, before):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not private_regular(info) or not 0 < info.st_size <= 32768:
            raise ValueError('UI-ready receipt must be a private root-owned regular file <=32KiB')
        raw = os.read(fd, 32769)
        if len(raw) != info.st_size:
            raise ValueError('UI-ready receipt changed or exceeded its bound')
    finally:
        os.close(fd)
    proof = json.loads(raw)
    if not isinstance(proof, dict):
        raise ValueError('UI-ready receipt must be an object')
    for key in ['schema', 'pid', 'tid', 'process_start', 'thread_start', 'observed_ns', 'gpu_context']:
        if type(proof.get(key)) is not int or proof[key] <= 0:
            raise ValueError('Invalid UI-ready receipt field: '+key)
    if (proof['schema'] != 1 or proof.get('boot_id') != boot or
            any(proof[k] != before[k] for k in ['pid', 'tid', 'process_start', 'thread_start']) or
            proof.get('dashboard_app_key') != 'valve.steam.gamepadui.main' or
            proof.get('dashboard_visible') is not True or
            not 0 <= time.monotonic_ns()-proof['observed_ns'] <= 120000000000):
        raise ValueError('UI-ready receipt does not match this live renderer and recent dashboard')
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'proof': proof}


def stable_fields(state):
    return {k: v for k, v in state.items() if k not in ('policy', 'rt_priority')}


def is_rr2(state):
    return (state['policy'] in (os.SCHED_RR, os.SCHED_RR | os.SCHED_RESET_ON_FORK) and
            state['rt_priority'] == 2)


@contextmanager
def prioritize_render(serial, boot, pid, tid, ready_json):
    validate_device(serial, boot)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        if not private_regular(os.fstat(fd)):
            raise ValueError('Priority lock must be private and root-owned')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot(pid, tid)
        if ((before['policy'], before['rt_priority'], before['nice']) != (os.SCHED_OTHER, 0, -20) or
                before['limits'] != LIMITS or not before['affinity']):
            raise ValueError('Requires OTHER0/nice-20, RTPRIO2 and unchanged100ms RTTIME')
        record = {'boot_id': boot, 'before': before,
                  'ready': ready_receipt(ready_json, boot, before)}
        active_verified = False
        try:
            os.sched_setscheduler(tid, os.SCHED_RR | os.SCHED_RESET_ON_FORK, os.sched_param(2))
            validate_device(serial, boot)
            active = snapshot(pid, tid)
            if stable_fields(active) != stable_fields(before) or not is_rr2(active):
                raise RuntimeError('Renderer policy readback or identity changed: ' +
                                   json.dumps({'before': before, 'active': active}, sort_keys=True))
            active_verified = True
            record['active'] = active
            yield record
        finally:
            validate_device(serial, boot)
            try:
                current = snapshot(pid, tid)
            except (FileNotFoundError, ProcessLookupError):
                if (PROC/str(pid)/'task'/str(tid)/'stat').exists():
                    raise RuntimeError('Renderer inspection failed while the task still exists')
                record['restoration'] = 'owned-renderer-exited'
            else:
                if stable_fields(current) != stable_fields(before):
                    raise RuntimeError('Renderer identity, affinity, nice or limits changed; restoration refused')
                if not active_verified and current == before:
                    record['after'] = current
                    record['restoration'] = 'unchanged'
                else:
                    if not is_rr2(current):
                        raise RuntimeError('Renderer policy changed; restoration refused')
                    os.sched_setscheduler(tid, before['policy'], os.sched_param(before['rt_priority']))
                    record['after'] = snapshot(pid, tid)
                    if record['after'] != before:
                        raise RuntimeError('Renderer policy restoration failed')
                    record['restoration'] = 'restored'
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--tid', type=int, required=True)
    parser.add_argument('--ready-json', type=Path, required=True)
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
        with prioritize_render(args.boot_serial, args.boot_id, args.pid, args.tid, args.ready_json) as record:
            print('PICO_STEAM_RENDER_PRIORITY_READY '+json.dumps(record), flush=True)
            deadline = time.monotonic()+args.seconds
            while not stopped and time.monotonic() < deadline:
                time.sleep(.05)
        print('PICO_STEAM_RENDER_PRIORITY_RESTORED '+json.dumps(record), flush=True)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
