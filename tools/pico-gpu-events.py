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
import time
import uuid

QUEUE = Path("/sys/bus/workqueue/devices/kgsl-events")
LOCK = Path("/run/reframed-pico-gpu-events.lock")
ATTRIBUTES = ("nice", "cpumask", "max_active", "numa")


def validate_device(boot_serial, boot_id):
    if (
        platform.system() != "Linux"
        or platform.machine() != "aarch64"
        or os.geteuid() != 0
        or not re.fullmatch(r"[A-Za-z0-9]{1,32}", boot_serial)
        or "androidboot.serialno=" + boot_serial
        not in Path("/proc/cmdline").read_text().split()
        or Path("/proc/device-tree/compatible").read_bytes()
        != b"qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0"
    ):
        raise ValueError("Requires the selected native Linux Pico Neo3 as root")
    if (
        str(uuid.UUID(boot_id)) != boot_id
        or Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot_id
    ):
        raise ValueError("Pico boot identity changed")


def snapshot():
    return {name: (QUEUE / name).read_text().strip() for name in ATTRIBUTES}


@contextmanager
def _prioritize_without_affinity(boot_serial, boot_id):
    validate_device(boot_serial, boot_id)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("GPU event policy lock must be private and root-owned")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = snapshot()
        if not -20 <= int(before["nice"]) <= 19:
            raise ValueError("Invalid existing KGSL callback priority")
        record = {"boot_id": boot_id, "boot_serial": boot_serial, "before": before}
        try:
            (QUEUE / "nice").write_text("-20\n")
            active = snapshot()
            if active != before | {"nice": "-20"}:
                raise RuntimeError("KGSL queue priority readback failed")
            record["active"] = active
            yield record
        finally:
            (QUEUE / "nice").write_text(before["nice"] + "\n")
            after = snapshot()
            record["after"] = after
            if after != before:
                raise RuntimeError("KGSL queue policy restoration failed")
    finally:
        os.close(fd)


CPU = Path("/sys/devices/system/cpu")
GLOBAL_MASK = Path("/sys/devices/virtual/workqueue/cpumask")
BOOT = Path("/proc/sys/kernel/random/boot_id")


class AffinityPolicyError(RuntimeError):
    def __init__(self, record):
        super().__init__("KGSL experimental policy failed; inspect receipt")
        self.receipt = record


def bounded_text(path):
    with path.open() as stream:
        value = stream.read(4097)
    if len(value) > 4096:
        raise ValueError("Policy metadata exceeds bound: " + str(path))
    return value.strip()


def mask_value(value):
    if not re.fullmatch(r"[0-9a-fA-F]{1,8}(?:,[0-9a-fA-F]{8}){0,3}", value):
        raise ValueError("Invalid bounded CPU mask")
    return int(value.replace(",", ""), 16)


def native_preflight(boot_id, cpu_mask):
    if cpu_mask != "f0":
        raise ValueError("Only explicitly selected f0 experiment is supported")
    before_boot = bounded_text(BOOT)
    online, possible = bounded_text(CPU / "online"), bounded_text(CPU / "possible")
    global_mask = bounded_text(GLOBAL_MASK)
    if before_boot != boot_id or online != "0-7" or possible != "0-7":
        raise ValueError("Native boot/online/possible topology differs")
    if mask_value(global_mask) & 0xF0 != 0xF0:
        raise ValueError("Global workqueue mask excludes requested CPUs")
    rows = []
    capacities = [351] * 4 + [871] * 3 + [1024]
    for index in range(8):
        path = CPU / ("cpu%d" % index)
        row = {
            "cpu": index,
            "midr": int(bounded_text(path / "regs/identification/midr_el1"), 16),
            "capacity": int(bounded_text(path / "cpu_capacity")),
            "max_frequency_khz": int(bounded_text(path / "cpufreq/cpuinfo_max_freq")),
        }
        if row["midr"] != (0x51DF805E if index < 4 else 0x411FD0D0):
            raise ValueError("Native MIDR differs")
        if row["max_frequency_khz"] != (
            1804800 if index < 4 else 2419200 if index < 7 else 2841600
        ):
            raise ValueError("Native maximum frequency differs")
        rows.append(row)
    if any(
        row["capacity"] <= 0
        or row["capacity"] * 1024 != capacities[row["cpu"]] * rows[7]["capacity"]
        for row in rows
    ):
        raise ValueError("Native relative CPU capacities differ")
    if (
        bounded_text(BOOT) != boot_id
        or bounded_text(CPU / "online") != online
        or bounded_text(CPU / "possible") != possible
        or bounded_text(GLOBAL_MASK) != global_mask
    ):
        raise ValueError("Native topology changed during preflight")
    return {
        "boot_id": boot_id,
        "online": online,
        "possible": possible,
        "global_mask": global_mask,
        "cpus": rows,
    }


def queue_identity():
    info = QUEUE.stat()
    return {
        "path": str(QUEUE.resolve(strict=True)),
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def pool_snapshot():
    raw = bounded_text(QUEUE / "pool_ids")
    tokens = raw.split()
    nodes = set()
    pools = []
    if not 1 <= len(tokens) <= 64:
        raise ValueError("Invalid bounded pool count")
    for token in tokens:
        match = re.fullmatch(r"(-?\d+):(\d+)", token)
        if not match:
            raise ValueError("Invalid node:pool")
        node, pool = map(int, match.groups())
        if node in nodes or not -1 <= node <= 4095 or not 0 <= pool <= 2147483647:
            raise ValueError("Invalid duplicate/range node:pool")
        nodes.add(node)
        pools.append(pool)
    return {"raw": raw, "pool_ids": sorted(set(pools))}


@contextmanager
def prioritize_events(boot_serial, boot_id, cpu_mask=None):
    if cpu_mask is None:
        with _prioritize_without_affinity(boot_serial, boot_id) as record:
            yield record
        return
    validate_device(boot_serial, boot_id)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("GPU event policy lock must be private and root-owned")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        topology = native_preflight(boot_id, cpu_mask)
        identity = queue_identity()
        before = snapshot()
        if before["nice"] != "0" or before["cpumask"] != "ff":
            raise ValueError("Invalid original queue policy")
        record = {
            "schema": 1,
            "experiment": "queue-cpumask-f0",
            "generation": str(uuid.uuid4()),
            "boot_id": boot_id,
            "boot_serial": boot_serial,
            "queue_identity": identity,
            "topology": topology,
            "before": before,
            "before_pool": pool_snapshot(),
            "requested": before | {"nice": "-20", "cpumask": cpu_mask},
            "mutations": [],
            "restorations": [],
            "restoration_errors": [],
            "begin_ns": time.monotonic_ns(),
            "worker_policy_changed": False,
        }
        failure = None
        attempted = []

        def validate_owner():
            if bounded_text(BOOT) != boot_id or queue_identity() != identity:
                raise RuntimeError(
                    "Boot/queue identity changed; refuse replacement write"
                )

        try:
            for name in ("nice", "cpumask"):
                value = record["requested"][name]
                if value == before[name]:
                    continue
                validate_owner()
                attempted.append(name)
                record["mutations"].append(
                    {
                        "attribute": name,
                        "value": value,
                        "before_ns": time.monotonic_ns(),
                    }
                )
                (QUEUE / name).write_text(value + "\n")
                record["mutations"][-1]["after_ns"] = time.monotonic_ns()
                record["mutations"][-1]["pool_snapshot"] = pool_snapshot()
                record["mutations"][-1]["pool_snapshot_ns"] = time.monotonic_ns()
            validate_owner()
            record["active"] = snapshot()
            record["active_pool"] = pool_snapshot()
            record["active_topology"] = native_preflight(boot_id, cpu_mask)
            if (
                record["active"] != record["requested"]
                or record["active_topology"] != topology
            ):
                raise RuntimeError("Queue policy/topology readback mismatch")
            record["active_ns"] = time.monotonic_ns()
            yield record
        except BaseException as error:
            failure = error
            record["error"] = repr(error)[:2048]
            raise
        finally:
            for name in reversed(attempted):
                row = {
                    "attribute": name,
                    "value": before[name],
                    "before_ns": time.monotonic_ns(),
                }
                record["restorations"].append(row)
                try:
                    validate_owner()
                    (QUEUE / name).write_text(before[name] + "\n")
                    row["readback"] = bounded_text(QUEUE / name)
                    if row["readback"] != before[name]:
                        raise RuntimeError("Attribute restoration readback mismatch")
                except BaseException as error:
                    row["error"] = repr(error)[:2048]
                    record["restoration_errors"].append(name + ": " + row["error"])
                row["after_ns"] = time.monotonic_ns()
            try:
                validate_owner()
                record["after"] = snapshot()
                record["after_pool"] = pool_snapshot()
                if record["after"] != before:
                    raise RuntimeError(
                        "Original queue attributes not restored or unrelated drift"
                    )
            except BaseException as error:
                record["restoration_errors"].append(
                    "final readback: " + repr(error)[:2048]
                )
            record["end_ns"] = time.monotonic_ns()
            if record["restoration_errors"]:
                raise AffinityPolicyError(record) from failure
            if failure is not None:
                try:
                    failure.receipt = record
                except Exception:
                    pass
    finally:
        os.close(fd)


def transition_pool_ids(record):
    return sorted(
        {
            value
            for row in [
                record["before_pool"],
                record["active_pool"],
                *(
                    item["pool_snapshot"]
                    for item in record["mutations"]
                    if "pool_snapshot" in item
                ),
            ]
            for value in row["pool_ids"]
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boot-serial", required=True)
    parser.add_argument("--boot-id", required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument(
        "--cpu-mask",
        choices=("f0",),
        default=None,
        help="Opt-in callback-affinity experiment; requires the verified Neo3 CPU topology",
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error("--seconds must be between 1 and 900")
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    previous = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, stop)
        with prioritize_events(args.boot_serial, args.boot_id, args.cpu_mask) as record:
            print("PICO_GPU_EVENTS_READY " + json.dumps(record), flush=True)
            # A signal can interrupt Event.wait while its condition lock is held.
            deadline = time.monotonic() + args.seconds
            while not stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.05))
        print("PICO_GPU_EVENTS_RESTORED " + json.dumps(record), flush=True)
    except BaseException as error:
        if args.cpu_mask is not None and hasattr(error, "receipt"):
            print(
                "PICO_GPU_EVENTS_EXPERIMENT_FAILED " + json.dumps(error.receipt),
                flush=True,
            )
        raise
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
