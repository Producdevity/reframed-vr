#!/usr/bin/env python3
"""Summarize overlapping OpenVR frame-history snapshots; this does not measure photon latency."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {name: ordered[min(len(ordered)-1, math.ceil(fraction*len(ordered))-1)]
            for name, fraction in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]}


def analyze(text, refresh):
    if not math.isfinite(refresh) or refresh <= 0:
        raise ValueError('Invalid refresh rate')
    frames = {}
    observations = 0
    for line in text.splitlines():
        if not line.startswith('PICO_STEAMVR_FRAME_HISTORY '):
            continue
        pairs = [item.split('=', 1) for item in line.split()[1:]]
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError('Duplicate frame-history field')
        if set(fields) != {'index', 'system_s', 'presents', 'mispresented', 'dropped', 'gpu_ms', 'cpu_ms'}:
            raise ValueError('Unexpected frame-history fields')
        value = {key: float(raw) if key in ('system_s', 'gpu_ms', 'cpu_ms') else int(raw)
                 for key, raw in fields.items()}
        if any(not math.isfinite(v) or v < 0 for v in value.values()):
            raise ValueError('Invalid frame-history value')
        if value['index'] in frames and frames[value['index']]['system_s'] != value['system_s']:
            raise ValueError('Frame index reused with a different timestamp; do not mix sessions')
        frames[value['index']] = value
        observations += 1
    rows = [frames[i] for i in sorted(frames)]
    if len(rows) < 2:
        raise ValueError('Insufficient frame history')
    intervals = []
    missing = 0
    for a, b in zip(rows, rows[1:]):
        delta = b['system_s'] - a['system_s']
        if delta <= 0:
            raise ValueError('Regressing frame timestamps')
        missing += b['index'] - a['index'] - 1
        if b['index'] == a['index'] + 1:
            intervals.append(delta*1000)
    duration = rows[-1]['system_s'] - rows[0]['system_s']
    return {'refresh_hz': refresh, 'observations': observations, 'unique_frames': len(rows),
            'missing_frame_indices': missing, 'duration_s': duration,
            'observed_frame_rate_hz': (len(rows)-1)/duration,
            'consecutive_frame_interval_ms': distribution(intervals),
            'intervals_over_1_5_periods': sum(x > 1500/refresh for x in intervals),
            'compositor_gpu_ms': distribution([r['gpu_ms'] for r in rows]),
            'gpu_over_frame_budget': sum(r['gpu_ms'] > 1000/refresh for r in rows),
            'compositor_cpu_ms': distribution([r['cpu_ms'] for r in rows]),
            'frame_presents': dict(Counter(r['presents'] for r in rows)),
            'reported_dropped': sum(r['dropped'] for r in rows),
            'reported_mispresented': sum(r['mispresented'] for r in rows),
            'photon_latency_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--refresh', type=float, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.log.read_text(), args.refresh), indent=2))


if __name__ == '__main__':
    main()
