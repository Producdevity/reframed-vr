#!/usr/bin/env python3
"""Find ARM64 futex waits overlapping the full pre-submit interval of missed presents."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re

EVENT = re.compile(r'\s*(.*?)-(\d+)\s+\[\d+\]\s+\S+\s+(\d+)\.(\d+): (\w+): (.*)')


def analyze(trace, metadata, boundaries, maps):
    if metadata['tail_only']:
        raise ValueError('Requires the complete trace, not a retained tail')
    scopes = []
    for miss in boundaries['misses']:
        start = min(miss['prior_vblank_trace_ns'], miss['prior_wait_end_ns'])
        end = miss['command']['queued_ns']
        if not 0 < start < end:
            raise ValueError('Invalid pre-submit interval')
        scopes.append({'present': miss['present'], 'source': miss['source'],
                       'tid': miss['command']['submitter_pid'], 'start_ns': start,
                       'end_ns': end, 'wait_return_ns': miss['prior_wait_end_ns'], 'waits': []})
    tids = {scope['tid'] for scope in scopes}
    mappings = []
    for line in maps.splitlines():
        match = re.fullmatch(r'([0-9a-f]+)-([0-9a-f]+)\s+\S+\s+\S+\s+\S+\s+\d+\s*(.*)', line)
        if match:
            mappings.append((int(match[1], 16), int(match[2], 16), match[3]))
    digest, size, pending = hashlib.sha256(), 0, {}
    with gzip.open(trace, 'rb') as stream:
        for raw in stream:
            digest.update(raw)
            size += len(raw)
            line = raw.decode().rstrip('\n')
            if line.startswith('#') or not line.strip():
                continue
            match = EVENT.fullmatch(line)
            if not match:
                raise ValueError('Unrecognized trace event')
            comm, tid, seconds, fraction, kind, fields = match.groups()
            tid = int(tid)
            ns = int(seconds) * 10**9 + int(fraction.ljust(9, '0'))
            if kind == 'sched_wakeup':
                target = re.search(r'\bpid=(\d+)\b', fields)
                call = pending.get(int(target[1])) if target else None
                if call is not None:
                    call['wakeups'].append({'ns': ns, 'waker_tid': tid, 'waker_comm': comm})
            if tid not in tids:
                continue
            if kind == 'sys_enter':
                if tid in pending:
                    raise ValueError('Missing syscall exit within a selected thread')
                entry = re.fullmatch(r'NR (\d+) \((.*)\)', fields)
                if not entry:
                    raise ValueError('Unrecognized syscall entry')
                if int(entry[1]) != 98:
                    continue
                args = [int(value.strip(), 16) for value in entry[2].split(',')]
                if len(args) != 6:
                    raise ValueError('Expected six ARM64 syscall arguments')
                pending[tid] = {'start_ns': ns, 'arguments': args, 'wakeups': []}
            elif kind == 'sys_exit':
                exit_call = re.fullmatch(r'NR (\d+) = (-?\d+)', fields)
                if not exit_call:
                    raise ValueError('Unrecognized syscall exit')
                if int(exit_call[1]) != 98:
                    continue
                call = pending.pop(tid, None)
                if call is None:
                    continue
                args = call['arguments']
                # FUTEX_WAIT and FUTEX_WAIT_BITSET, with PRIVATE/CLOCK_REALTIME masked.
                if args[1] & 127 not in (0, 9):
                    continue
                if ns < call['start_ns']:
                    raise ValueError('Syscall clock regressed')
                call.update(end_ns=ns, duration_ns=ns-call['start_ns'], result=int(exit_call[2]),
                            mapping=next((name for start, end, name in mappings
                                          if start <= args[0] < end), None))
                for scope in scopes:
                    overlap = min(ns, scope['end_ns']) - max(call['start_ns'], scope['start_ns'])
                    if scope['tid'] == tid and overlap > 0:
                        scope['waits'].append(call | {'overlap_ns': overlap,
                            'ended_before_present_wait_return': ns <= scope['wait_return_ns']})
    if size != metadata['source_bytes'] or digest.hexdigest() != metadata['source_sha256']:
        raise ValueError('Trace does not match its source manifest')
    if any(call['start_ns'] < scope['end_ns'] for tid, call in pending.items()
           for scope in scopes if tid == scope['tid']):
        raise ValueError('Unfinished futex call in a selected interval')
    return {'scope': 'Hash-verified ARM64 syscall intervals from the prior observed vblank through '
                    'GPU queueing, including waits before Mesa presentation entry/return. Futex '
                    'expected words and wakeup threads do not prove lock ownership. No physical '
                    'latch deadline or optical acceptance is inferred.',
            'source_bytes': size, 'source_sha256': digest.hexdigest(), 'presents': scopes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--boundaries', type=Path, required=True)
    parser.add_argument('--maps', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.trace, json.loads(args.metadata.read_text()),
                     json.loads(args.boundaries.read_text()), args.maps.read_text())
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
