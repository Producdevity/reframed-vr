"""Strict whole-file parsing for the diagnostic kgsl_event_phases event.

This module neither operates tracefs nor changes scheduling. analyze() validates
bytes and records, not the capture provenance. qualify_capture() is a separate
gate, and association with accepted main work generations is a third gate.
"""
from pathlib import Path
import collections
import gzip
import hashlib
import re

EVENT = 'kgsl_event_phases'
TIME_FIELDS = ('entry_ns', 'fire_enter_ns', 'fire_exit_ns', 'promote_end_ns',
               'callback_end_ns', 'restore_end_ns')
POLICY_FIELDS = ('entry_policy', 'entry_prio', 'promoted_policy', 'promoted_prio',
                 'restored_policy', 'restored_prio')
RETURN_FIELDS = ('promote_ret', 'restore_ret')
DURATION_FIELDS = ('entry_to_fire_enter_ns', 'fire_trace_envelope_ns',
                   'promotion_envelope_ns', 'callback_envelope_ns',
                   'restore_envelope_ns')
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100000
ROW = re.compile(
    rb' *(?P<comm>[^\n\x00]{1,128}?)-(?P<pid>\d+) +\[(?P<cpu>\d{3})\] +'
    rb'(?P<flags>[dX.][Nnp.][ZzHhs.](?:\.|[1-9a-f][0-9a-f]?)) +'
    rb'(?P<sec>\d+)\.(?P<frac>\d{6}): kgsl_event_phases: (?P<body>[^\n\x00]+)\n')
BODY = re.compile(
    r'work=(?P<work>[0-9a-f]{16}) ctx=(?P<ctx>\d+) ts=(?P<ts>\d+) result=(?P<result>-?\d+) '
    + ' '.join(name+r'=(?P<'+name+r'>\d+)' for name in TIME_FIELDS) + ' '
    + ' '.join(name+r'=(?P<'+name+r'>-?\d+)' for name in POLICY_FIELDS+RETURN_FIELDS))
LOSS_FIELDS = ('overrun', 'commit overrun', 'dropped events')
STAT_FIELDS = ('entries', 'overrun', 'commit overrun', 'bytes', 'dropped events', 'read events')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def _uint(value, bits, name):
    need(type(value) is int and 0 <= value < 1 << bits, 'invalid '+name)


def _int32(value, name):
    need(type(value) is int and -(1 << 31) <= value < 1 << 31, 'invalid '+name)


def analyze(path):
    """Parse the complete plain or gzip file; reject any bad row, never a prefix."""
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    need(len(raw) <= MAX_BYTES, 'raw byte cap')
    need(not raw or raw.endswith(b'\n'), 'unterminated final row')
    lines = raw.splitlines(keepends=True)
    need(len(lines) <= MAX_ROWS, 'row cap')
    rows, cpu_previous, pid_previous, seen = [], {}, {}, set()
    counts = collections.Counter()
    for number, line in enumerate(lines, 1):
        match = ROW.fullmatch(line)
        need(match is not None, 'malformed or unexpected row '+str(number))
        groups = match.groupdict()
        body = BODY.fullmatch(groups['body'].decode('ascii'))
        need(body is not None, 'malformed phase fields at row '+str(number))
        row = {name: value if name == 'work' else int(value)
               for name, value in body.groupdict().items()}
        row.update(line=number, comm=groups['comm'].decode('utf-8'),
                   pid=int(groups['pid']), cpu=int(groups['cpu']),
                   printed_ns=int(groups['sec'])*10**9+int(groups['frac'])*1000,
                   printed_lower_ns=int(groups['sec'])*10**9+int(groups['frac'])*1000-500,
                   printed_upper_ns=int(groups['sec'])*10**9+int(groups['frac'])*1000+499)
        need(0 < row['pid'] < 1 << 31 and 0 <= row['cpu'] < 8, 'PID/CPU range')
        _uint(row['ctx'], 32, 'ctx')
        _uint(row['ts'], 32, 'ts')
        _int32(row['result'], 'result')
        for name in TIME_FIELDS:
            _uint(row[name], 64, name)
        for name in POLICY_FIELDS+RETURN_FIELDS:
            _int32(row[name], name)
        marks = [row[name] for name in TIME_FIELDS]
        need(marks[0] > 0 and marks == sorted(marks), 'phase marks reversed')
        need(marks[-1] <= row['printed_upper_ns'], 'emission before restore')
        need(row['printed_ns'] >= cpu_previous.get(row['cpu'], 0), 'CPU time reversal')
        need(marks[0] >= pid_previous.get(row['pid'], 0), 'overlapping PID callbacks')
        identity = (row['pid'], row['work'], row['ctx'], row['ts'], marks[0])
        need(identity not in seen, 'duplicate phase row')
        seen.add(identity)
        cpu_previous[row['cpu']] = row['printed_ns']
        pid_previous[row['pid']] = marks[-1]
        row['identity_key'] = [row['pid'], row['work'], row['ctx'], row['ts']]
        row['durations_ns'] = dict(zip(DURATION_FIELDS, (b-a for a, b in zip(marks, marks[1:]))))
        row['durations_ns']['entry_to_restore_ns'] = marks[-1]-marks[0]
        rows.append(row)
        counts[row['cpu']] += 1
    summaries = {}
    for name in DURATION_FIELDS+('entry_to_restore_ns',):
        values = sorted(row['durations_ns'][name] for row in rows)
        summaries[name] = {'count': len(values), 'max_ns': values[-1] if values else None,
                           'p99_ns': values[(99*len(values)+99)//100-1] if values else None}
    return {'schema': 1, 'structurally_valid': True, 'capture_accepted': False,
            'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'row_count': len(rows), 'per_cpu_rows': dict(counts), 'rows': rows,
            'duration_summaries': summaries,
            'limits': 'Elapsed phase envelopes include preemption, IRQs and instrumentation. '
                      'No exclusive CPU time, scheduling cause, presentation or display latch claim. '
                      'PID and pointer reuse require an independently accepted main-work generation join. '
                      'Header CPU is emission CPU, not every sample CPU. Headers round to nearest microsecond: '
                      'the original time is in [printed-500, printed+499] ns.'}


def _stats(value):
    if isinstance(value, str):
        data = {}
        for line in value.splitlines():
            name, separator, content = line.partition(':')
            need(separator and name.strip() not in data, 'stats line or duplicate')
            data[name.strip()] = content.strip()
        value = data
    need(isinstance(value, dict), 'stats object')
    need(set(value) == set(STAT_FIELDS) | {'oldest event ts', 'now ts'}, 'stats inventory')
    result = {}
    for name in STAT_FIELDS:
        text = str(value[name])
        need(re.fullmatch(r'\d+', text) is not None, 'stats integer')
        result[name] = int(text)
    for name in ('oldest event ts', 'now ts'):
        need(re.fullmatch(r'\d+\.\d{6}', str(value[name])) is not None, 'stats timestamp')
    return result


def qualify_capture(parsed, *, expected_sha256, expected_bytes, stats_before,
                    stats_after, start_ns, end_ns, reader_joined, reader_error,
                    cleanup_errors, source_qualified, enabled, allowed_results):
    """Qualify independently supplied whole-capture receipts; never repair data.

    source_qualified is supplied only after the caller verifies runtime kernel,
    source, format, clock/options, all-instance event enablement, ownership and
    stable worker identities. Stats maps must contain numeric CPU keys 0..7.
    start/end bound the complete enabled capture, not a selected subset.
    """
    need(parsed.get('structurally_valid') is True, 'parsed file required')
    need(parsed['source_sha256'] == expected_sha256 and parsed['source_bytes'] == expected_bytes,
         'whole raw hash/bytes')
    need(source_qualified is True, 'source/settings/identity qualification')
    need(reader_joined is True and reader_error is None and cleanup_errors == [], 'reader/cleanup')
    need(type(enabled) is bool, 'enabled boolean')
    need(type(start_ns) is int and type(end_ns) is int and 0 < start_ns < end_ns, 'capture bounds')
    need(set(stats_before) == set(stats_after) == set(range(8)), 'all eight CPU stats')
    need(isinstance(allowed_results, (list, tuple, set)) and allowed_results, 'pinned result enum required')
    for value in allowed_results:
        _int32(value, 'allowed result')
    for cpu in range(8):
        before, after = _stats(stats_before[cpu]), _stats(stats_after[cpu])
        need(all(before[name] == 0 for name in STAT_FIELDS), 'initial stats not cleared')
        need(all(after[name] == 0 for name in LOSS_FIELDS), 'trace loss')
        need(after['entries'] == 0, 'undrained trace')
        need(after['read events'] == parsed['per_cpu_rows'].get(cpu, 0), 'read/row count mismatch')
    need(enabled or not parsed['rows'], 'phase rows while event disabled')
    need(not enabled or parsed['row_count'] > 0, 'empty enabled phase capture')
    for row in parsed['rows']:
        need(start_ns <= row['entry_ns'] <= row['restore_end_ns'] and row['printed_upper_ns'] < end_ns,
             'callback crosses complete capture bounds')
        need(row['result'] in allowed_results, 'unknown callback result')
    return dict(parsed, capture_accepted=True)


def join_generations(parsed, works, *, result_names):
    """Exact complete-generation association to an already accepted main epoch.

    Caller supplies the same-boot accepted callback-generations list and only
    contained capture interval works. Every supplied work must match exactly one
    phase row. An empty or subset join is not proof of full event coverage.
    """
    need(parsed.get('capture_accepted') is True, 'independent phase capture gate')
    need(isinstance(works, list) and works, 'complete main-work population required')
    need(isinstance(result_names, dict) and result_names
         and set(result_names.values()) <= {'retired', 'cancelled'}, 'pinned result names required')
    by_key = collections.defaultdict(list)
    for work in works:
        need(work['start']['kind'] == 'workqueue_execute_start'
             and work['end']['kind'] == 'workqueue_execute_end', 'main closed work boundaries')
        need(work['start']['tid'] == work['end']['tid'], 'main executor identity')
        need(len(work['fires']) == 1, 'unique main fire required')
        fire = work['fires'][0]
        match = re.fullmatch(r'ctx=(\d+) ts=(\d+) type=(retired|cancelled) age=\d+ cb=\S+', fire['fields'])
        need(match is not None, 'main fire grammar')
        need(fire['tid'] == work['start']['tid'], 'main fire executor')
        key = (work['start']['tid'], work['work'], int(match[1]), int(match[2]))
        by_key[key].append(work)
    used, joined = set(), []
    for row in parsed['rows']:
        matches = []
        for work in by_key[tuple(row['identity_key'])]:
            start, end, fire = work['start']['ns'], work['end']['ns'], work['fires'][0]['ns']
            if (start-500 <= row['entry_ns'] and row['printed_lower_ns'] <= end+499
                and row['fire_enter_ns'] <= fire+499 and fire-500 <= row['fire_exit_ns']
                and ('type='+result_names.get(row['result'], 'unmapped')+' ') in work['fires'][0]['fields']):
                matches.append(work)
        need(len(matches) == 1, 'missing or ambiguous exact work join')
        work = matches[0]
        identity = (work['work'], work['generation'])
        need(identity not in used, 'duplicate phase for work generation')
        used.add(identity)
        joined.append(dict(row, work_generation=work['generation'],
                           execute_to_entry_lower_ns=max(0, row['entry_ns']-work['start']['ns']-499),
                           execute_to_entry_upper_ns=row['entry_ns']-work['start']['ns']+500,
                           execute_start_ns=work['start']['ns']))
    need(len(used) == len(works), 'incomplete main-work coverage')
    return {'accepted': True, 'same_boot_and_main_qualification_required': True,
            'matched_works': len(used), 'rows': joined,
            'scope': 'Same-boot exact identity and bounded timestamp association only; '
                     'separate phase and main streams retain independent acceptance gates.'}


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = analyze(args.trace)
    if args.output:
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
