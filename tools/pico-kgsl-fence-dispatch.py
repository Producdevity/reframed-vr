"""Strict whole-file parsing for the diagnostic kgsl_fence_dispatch event.

This module neither operates tracefs nor changes scheduling. analyze() validates
bytes and records, not the capture provenance. qualify_capture() is a separate
gate, and contained measurement summaries are a separate gate. No WQ generation join exists.
"""

from pathlib import Path
import collections
import gzip
import hashlib
import re

EVENT = "kgsl_fence_dispatch"
TIME_FIELDS = ("queued_ns", "start_ns", "done_ns")
POLICY_FIELDS = ("policy", "prio")
RETURN_FIELDS = ()
DURATION_FIELDS = ("queue_to_start_ns", "start_to_done_ns")
PATCH_SHA256 = "9dfc709ae6abee2e505c0d690d1201bafed53837f0e02baa5daa34bf03926d85"
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100000
ROW = re.compile(
    rb" *(?P<comm>[^\n\x00]{1,128}?)-(?P<pid>\d+) +\[(?P<cpu>\d{3})\] +"
    rb"(?P<flags>[dX.][Nnp.][ZzHhs.](?:\.|[1-9a-f][0-9a-f]?)) +"
    rb"(?P<sec>\d+)\.(?P<frac>\d{6}): kgsl_fence_dispatch: (?P<body>[^\n\x00]+)\n"
)
BODY = re.compile(
    r"work=(?P<work>[0-9a-f]{16}) ctx=(?P<ctx>\d+) ts=(?P<ts>\d+) result=(?P<result>-?\d+) "
    + " ".join(name + r"=(?P<" + name + r">\d+)" for name in TIME_FIELDS)
    + " "
    + " ".join(
        name + r"=(?P<" + name + r">-?\d+)" for name in POLICY_FIELDS + RETURN_FIELDS
    )
)
LOSS_FIELDS = ("overrun", "commit overrun", "dropped events")
STAT_FIELDS = (
    "entries",
    "overrun",
    "commit overrun",
    "bytes",
    "dropped events",
    "read events",
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def _uint(value, bits, name):
    need(type(value) is int and 0 <= value < 1 << bits, "invalid " + name)


def _int32(value, name):
    need(type(value) is int and -(1 << 31) <= value < 1 << 31, "invalid " + name)


def analyze(path):
    """Parse the complete plain or gzip file; reject any bad row, never a prefix."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    need(len(raw) <= MAX_BYTES, "raw byte cap")
    need(not raw or raw.endswith(b"\n"), "unterminated final row")
    lines = raw.splitlines(keepends=True)
    need(len(lines) <= MAX_ROWS, "row cap")
    rows, cpu_previous, pid_previous, seen = [], {}, {}, set()
    counts = collections.Counter()
    for number, line in enumerate(lines, 1):
        match = ROW.fullmatch(line)
        need(match is not None, "malformed or unexpected row " + str(number))
        groups = match.groupdict()
        body = BODY.fullmatch(groups["body"].decode("ascii"))
        need(body is not None, "malformed dispatch fields at row " + str(number))
        row = {
            name: value if name == "work" else int(value)
            for name, value in body.groupdict().items()
        }
        row.update(
            line=number,
            comm=groups["comm"].decode("utf-8"),
            pid=int(groups["pid"]),
            cpu=int(groups["cpu"]),
            printed_ns=int(groups["sec"]) * 10**9 + int(groups["frac"]) * 1000,
            printed_lower_ns=int(groups["sec"]) * 10**9
            + int(groups["frac"]) * 1000
            - 500,
            printed_upper_ns=int(groups["sec"]) * 10**9
            + int(groups["frac"]) * 1000
            + 499,
        )
        need(0 < row["pid"] < 1 << 31 and 0 <= row["cpu"] < 8, "PID/CPU range")
        _uint(row["ctx"], 32, "ctx")
        _uint(row["ts"], 32, "ts")
        _int32(row["result"], "result")
        for name in TIME_FIELDS:
            _uint(row[name], 64, name)
        for name in POLICY_FIELDS + RETURN_FIELDS:
            _int32(row[name], name)
        marks = [row[name] for name in TIME_FIELDS]
        need(marks[0] > 0 and marks == sorted(marks), "dispatch marks reversed")
        need(marks[-1] <= row["printed_upper_ns"], "emission before completion")
        need(row["printed_ns"] >= cpu_previous.get(row["cpu"], 0), "CPU time reversal")
        need(marks[1] >= pid_previous.get(row["pid"], 0), "overlapping PID callbacks")
        identity = (row["pid"], row["work"], row["ctx"], row["ts"], marks[0])
        need(identity not in seen, "duplicate dispatch row")
        seen.add(identity)
        cpu_previous[row["cpu"]] = row["printed_ns"]
        pid_previous[row["pid"]] = marks[-1]
        row["identity_key"] = [row["pid"], row["work"], row["ctx"], row["ts"]]
        row["durations_ns"] = dict(
            zip(DURATION_FIELDS, (b - a for a, b in zip(marks, marks[1:])))
        )
        row["durations_ns"]["queue_to_done_ns"] = marks[-1] - marks[0]
        rows.append(row)
        counts[row["cpu"]] += 1
    summaries = {}
    for name in DURATION_FIELDS + ("queue_to_done_ns",):
        values = sorted(row["durations_ns"][name] for row in rows)
        summaries[name] = {
            "count": len(values),
            "max_ns": values[-1] if values else None,
            "p99_ns": values[(99 * len(values) + 99) // 100 - 1] if values else None,
        }
    return {
        "schema": 1,
        "structurally_valid": True,
        "capture_accepted": False,
        "source_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": len(rows),
        "per_cpu_rows": dict(counts),
        "rows": rows,
        "duration_summaries": summaries,
        "limits": "Elapsed queue/start/done envelopes include IRQs, preemption and instrumentation. "
        "Queue mark precedes actual insertion; header CPU is emission CPU. "
        "No CPU time, display latch, WQ generation join, or guaranteed count of unfinished callbacks. "
        "Headers round to nearest microsecond: [printed-500, printed+499] ns.",
    }


def _stats(value):
    if isinstance(value, str):
        data = {}
        for line in value.splitlines():
            name, separator, content = line.partition(":")
            need(separator and name.strip() not in data, "stats line or duplicate")
            data[name.strip()] = content.strip()
        value = data
    need(isinstance(value, dict), "stats object")
    need(
        set(value) == set(STAT_FIELDS) | {"oldest event ts", "now ts"},
        "stats inventory",
    )
    result = {}
    for name in STAT_FIELDS:
        text = str(value[name])
        need(re.fullmatch(r"\d+", text) is not None, "stats integer")
        result[name] = int(text)
    for name in ("oldest event ts", "now ts"):
        need(
            re.fullmatch(r"\d+\.\d{6}", str(value[name])) is not None, "stats timestamp"
        )
    return result


def qualify_capture(
    parsed,
    *,
    expected_sha256,
    expected_bytes,
    stats_before,
    stats_after,
    start_ns,
    end_ns,
    reader_joined,
    reader_error,
    cleanup_errors,
    source_qualified,
    enabled,
    allowed_results,
    worker_identity,
    guard_before,
    guard_after,
    patch_sha256,
):
    """Qualify independently supplied whole-capture receipts; never repair data.

    source_qualified is supplied only after the caller verifies runtime kernel,
    source, format, clock/options, all-instance event enablement, ownership and
    stable worker identities. Stats maps must contain numeric CPU keys 0..7.
    start/end bound the complete enabled capture, not a selected subset.
    """
    need(parsed.get("structurally_valid") is True, "parsed file required")
    need(
        parsed["source_sha256"] == expected_sha256
        and parsed["source_bytes"] == expected_bytes,
        "whole raw hash/bytes",
    )
    need(source_qualified is True, "source/settings/identity qualification")
    need(
        reader_joined is True and reader_error is None and cleanup_errors == [],
        "reader/cleanup",
    )
    need(type(enabled) is bool, "enabled boolean")
    need(patch_sha256 == PATCH_SHA256, "candidate patch identity")
    qualify_guard(guard_before, enabled=enabled, worker_identity=worker_identity)
    qualify_guard(guard_after, enabled=enabled, worker_identity=worker_identity)
    need(
        type(start_ns) is int and type(end_ns) is int and 0 < start_ns < end_ns,
        "capture bounds",
    )
    need(set(stats_before) == set(stats_after) == set(range(8)), "all eight CPU stats")
    need(
        isinstance(allowed_results, (list, tuple, set)) and allowed_results,
        "pinned result enum required",
    )
    need(set(allowed_results) == {1, 2}, "pinned retired/cancelled enum")
    for value in allowed_results:
        _int32(value, "allowed result")
    for cpu in range(8):
        before, after = _stats(stats_before[cpu]), _stats(stats_after[cpu])
        need(
            all(before[name] == 0 for name in STAT_FIELDS), "initial stats not cleared"
        )
        need(all(after[name] == 0 for name in LOSS_FIELDS), "trace loss")
        need(after["entries"] == 0, "undrained trace")
        need(
            after["read events"] == parsed["per_cpu_rows"].get(cpu, 0),
            "read/row count mismatch",
        )
    need(enabled or not parsed["rows"], "dispatch rows while event disabled")
    need(not enabled or parsed["row_count"] > 0, "empty enabled RT capture")
    for row in parsed["rows"]:
        need(
            start_ns <= row["queued_ns"] <= row["done_ns"]
            and row["printed_upper_ns"] < end_ns,
            "callback crosses complete capture bounds",
        )
        need(row["result"] in allowed_results, "unknown callback result")
        # trace_find_cmdline prints <...> for a cache miss; both guards above
        # independently bind this PID to the same kernel task start_ticks.
        need(
            row["pid"] == worker_identity["pid"]
            and row["comm"] in ("kgsl-fence", "<...>"),
            "RT worker identity",
        )
        need(row["policy"] == 1 and row["prio"] == 59, "RT FIFO40 policy")
    return dict(parsed, capture_accepted=True)


def qualify_guard(guard, *, enabled, worker_identity):
    need(isinstance(guard, dict), "worker guard receipt")
    need(guard.get("parameter") == ("Y" if enabled else "N"), "boot parameter guard")
    workers = guard.get("workers")
    need(isinstance(workers, list), "worker inventory")
    if not enabled:
        need(not workers and worker_identity is None, "off arm has RT worker")
        return
    need(
        isinstance(worker_identity, dict) and len(workers) == 1,
        "unique guarded RT worker",
    )
    worker = workers[0]
    need(
        worker.get("pid") == worker_identity.get("pid")
        and worker.get("start_ticks") == worker_identity.get("start_ticks"),
        "worker lifetime identity",
    )
    need(
        type(worker.get("pid")) is int
        and worker["pid"] > 0
        and type(worker.get("start_ticks")) is int
        and worker["start_ticks"] > 0,
        "worker identity range",
    )
    need(
        worker.get("comm") == "kgsl-fence"
        and worker.get("ppid") == 2
        and worker.get("policy") == 1
        and worker.get("rt_priority") == 40
        and worker.get("cpus_allowed_int") == 15,
        "worker policy/affinity",
    )


def contained_window(parsed, *, start_ns, end_ns):
    need(parsed.get("capture_accepted") is True, "independent whole-capture gate")
    need(
        type(start_ns) is int and type(end_ns) is int and 0 < start_ns < end_ns,
        "measurement bounds",
    )
    contained, excluded = [], []
    for row in parsed["rows"]:
        reasons = []
        if row["queued_ns"] < start_ns:
            reasons.append("queue_before_measurement")
        if row["done_ns"] >= end_ns or row["printed_upper_ns"] >= end_ns:
            reasons.append("completion_or_emission_after_measurement")
        if reasons:
            excluded.append(
                {
                    "line": row["line"],
                    "identity_key": row["identity_key"],
                    "queued_ns": row["queued_ns"],
                    "start_ns": row["start_ns"],
                    "done_ns": row["done_ns"],
                    "printed_upper_ns": row["printed_upper_ns"],
                    "reasons": reasons,
                }
            )
        else:
            contained.append(row)

    def summary(rows):
        result = {"count": len(rows)}
        for field in DURATION_FIELDS + ("queue_to_done_ns",):
            values = sorted(row["durations_ns"][field] for row in rows)
            result[field] = {
                "count": len(values),
                "p50_ns": values[(len(values) + 1) // 2 - 1] if values else None,
                "p99_ns": values[(99 * len(values) + 99) // 100 - 1]
                if values
                else None,
                "max_ns": values[-1] if values else None,
            }
        return result

    by_context = collections.defaultdict(list)
    for row in contained:
        by_context[row["ctx"]].append(row)
    return {
        "accepted": True,
        "start_ns": start_ns,
        "end_ns": end_ns,
        "whole_capture_rows": parsed["row_count"],
        "contained_rows": len(contained),
        "boundary_exclusions": excluded,
        "summary": summary(contained),
        "per_context": {
            str(ctx): summary(rows) for ctx, rows in sorted(by_context.items())
        },
        "worst_queue_to_start": sorted(
            contained,
            key=lambda row: row["durations_ns"]["queue_to_start_ns"],
            reverse=True,
        )[:10],
        "limits": parsed["limits"],
    }


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.trace)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "rows"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
