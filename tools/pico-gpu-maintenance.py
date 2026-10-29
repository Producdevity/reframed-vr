#!/usr/bin/env python3
"""Opt-in Neo3 KGSL maintenance placement; use inside the active events context.

The required source_guard() must verify the running kernel and pinned source
provenance, raising on mismatch, and return a nonempty JSON object as evidence.
Its result must remain identical through entry, activation and context exit.
The caller owns signal handling and must unwind this context before kgsl-events.
"""

from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid


_spec = importlib.util.spec_from_file_location(
    "_pico_maintenance_events", Path(__file__).with_name("pico-gpu-events.py")
)
events = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(events)

QUEUES = Path("/sys/bus/workqueue/devices")
LOCK = Path("/run/reframed-pico-gpu-maintenance.lock")
CMDLINE = Path("/proc/cmdline")
COMPATIBLE = Path("/proc/device-tree/compatible")
EXPECTED = {"kgsl-workqueue": 256, "kgsl-mementry": 256}
CALLBACK = "kgsl-events"
MASK = "70"
ATTRIBUTES = ("nice", "cpumask", "max_active", "numa")
METADATA_LIMIT = 4096


class MaintenancePolicyError(RuntimeError):
    def __init__(self, receipt):
        super().__init__("KGSL maintenance restoration failed; inspect receipt")
        self.receipt = receipt


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino}


def _validate_lock(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_nlink != 1
        or info.st_mode & 0o077
    ):
        raise ValueError("Maintenance policy lock must be private and root-owned")


def _read_fd(fd):
    chunks = []
    remaining = METADATA_LIMIT + 1
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if not remaining:
        raise ValueError("Policy metadata exceeds bound")
    return b"".join(chunks)


def _bounded_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        return _read_fd(fd)
    finally:
        os.close(fd)


def validate_device(boot_serial, boot_id):
    if (
        events.platform.system() != "Linux"
        or events.platform.machine() != "aarch64"
        or os.geteuid() != 0
        or not re.fullmatch(r"[A-Za-z0-9]{1,32}", boot_serial)
        or "androidboot.serialno=" + boot_serial
        not in events.bounded_text(CMDLINE).split()
        or _bounded_bytes(COMPATIBLE)
        != b"qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0"
    ):
        raise ValueError("Requires the selected native Linux Pico Neo3 as root")
    if str(uuid.UUID(boot_id)) != boot_id or events.bounded_text(events.BOOT) != boot_id:
        raise ValueError("Pico boot identity changed")


def topology(boot_id):
    value = events.native_preflight(boot_id, "0f")
    if events.mask_value(value["global_mask"]) & 0x70 != 0x70:
        raise ValueError("Global workqueue mask excludes maintenance CPUs")
    return value


def _provenance(source_guard):
    if not callable(source_guard):
        raise ValueError("A verifying source/provenance caller guard is required")
    value = source_guard()
    if not isinstance(value, dict) or not value:
        raise ValueError("Source guard must return nonempty JSON evidence")
    encoded = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > 16384:
        raise ValueError("Source/provenance evidence exceeds bound")
    return json.loads(encoded)


def _pools(raw):
    tokens = raw.split()
    nodes, pools = set(), set()
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
        pools.add(pool)
    return {"raw": raw, "pool_ids": sorted(pools)}


class _Queue:
    def __init__(self, name):
        if name not in (*EXPECTED, CALLBACK):
            raise ValueError("Queue is outside maintenance experiment scope")
        self.name = name
        self.path = QUEUES / name
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.attributes = {}
        try:
            self.identity = _identity(os.fstat(self.fd)) | {
                "path": str(self.path.resolve(strict=True))
            }
            self.validate_owner()
        except BaseException:
            os.close(self.fd)
            raise

    def validate_owner(self):
        actual = _identity(self.path.stat()) | {
            "path": str(self.path.resolve(strict=True))
        }
        if actual != self.identity:
            raise RuntimeError(self.name + " identity changed; refuse replacement access")

    def _open_attribute(self, name, flags):
        fd = os.open(name, flags | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            identity = _identity(info)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Queue attribute is not a regular sysfs file")
            if name in self.attributes and identity != self.attributes[name]:
                raise RuntimeError(self.name + "/" + name + " identity changed")
            self.attributes[name] = identity
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, name):
        fd = self._open_attribute(name, os.O_RDONLY)
        try:
            return _read_fd(fd).decode("ascii").strip()
        finally:
            os.close(fd)

    def snapshot(self):
        self.validate_owner()
        attrs = {name: self.read(name) for name in ATTRIBUTES}
        pools = _pools(self.read("pool_ids"))
        self.validate_owner()
        return {
            "identity": dict(self.identity),
            "attribute_identities": dict(self.attributes),
            "attributes": attrs,
            "pools": pools,
        }

    def write_mask(self, value):
        if self.name not in EXPECTED:
            raise ValueError("Queue is observation-only")
        self.validate_owner()
        fd = self._open_attribute("cpumask", os.O_WRONLY)
        try:
            data = (value + "\n").encode("ascii")
            if os.write(fd, data) != len(data):
                raise OSError("Short sysfs cpumask write")
        finally:
            os.close(fd)


def _validate_policy(queues, enabled, active):
    for name, row in queues.items():
        attrs = row["attributes"]
        if attrs["nice"] not in {str(value) for value in range(-20, 20)}:
            raise ValueError("Invalid queue nice: " + name)
        if attrs["numa"] not in ("0", "1"):
            raise ValueError("Invalid queue numa: " + name)
        if not 0 < events.mask_value(attrs["cpumask"]) <= 0xFF:
            raise ValueError("Invalid queue CPU mask: " + name)
        expected_max = EXPECTED.get(name, 256)
        if attrs["max_active"] != str(expected_max):
            raise ValueError("Unexpected source-defined max_active: " + name)
        if name == CALLBACK:
            if attrs["nice"] != "-20" or events.mask_value(attrs["cpumask"]) != 0x0F:
                raise ValueError("kgsl-events must already be active at 0f/-20")
        elif attrs["nice"] != "0" or events.mask_value(attrs["cpumask"]) != (
            0x70 if active and enabled else 0xFF
        ):
            raise ValueError("Unexpected maintenance mask/nice: " + name)
    if active:
        callback_pools = set(queues[CALLBACK]["pools"]["pool_ids"])
        for name in EXPECTED:
            if callback_pools.intersection(queues[name]["pools"]["pool_ids"]):
                raise RuntimeError("Maintenance/callback pools overlap: " + name)


@contextmanager
def place_maintenance(boot_serial, boot_id, *, source_guard, enabled=False):
    """Place only maintenance queues on CPUs4–6; restore in reverse write order.

    The source guard must pin unchanged devfreq source; no devfreq sysfs path is
    accessed. Vendor attribute application clears its implicit ordering flag,
    which restoring a mask cannot recover. Sysfs does not prove that flag.
    Shared pools among the two maintenance queues are
    allowed; all must be disjoint from the active callback queue's pools.
    enabled=False observes the identical guards/snapshots without any writes.
    """
    if type(enabled) is not bool:
        raise ValueError("enabled must be an explicit boolean")
    validate_device(boot_serial, boot_id)
    provenance = _provenance(source_guard)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    opened = {}
    record = {
        "schema": 1,
        "experiment": "maintenance-cpumask-70" if enabled else "maintenance-control",
        "enabled": enabled,
        "generation": str(uuid.uuid4()),
        "boot_serial": boot_serial,
        "boot_id": boot_id,
        "source_provenance": provenance,
        "requested_mask": MASK if enabled else None,
        "mutations": [],
        "restorations": [],
        "restoration_errors": [],
        "worker_policy_changed": False,
        "begin_ns": time.monotonic_ns(),
    }
    try:
        info = os.fstat(fd)
        _validate_lock(info)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record["lock_identity"] = _identity(info)

        def validate_owner(queue=None):
            if events.bounded_text(events.BOOT) != boot_id:
                raise RuntimeError("Boot identity changed; refuse restoration/write")
            lock_info = LOCK.lstat()
            _validate_lock(lock_info)
            if _identity(lock_info) != record["lock_identity"]:
                raise RuntimeError("Maintenance lock identity changed")
            if queue is not None:
                queue.validate_owner()

        def capture(stage):
            value = record[stage] = {"queues": {}, "begin_ns": time.monotonic_ns()}
            errors = []
            checks = (
                ("owner", validate_owner),
                ("device", lambda: validate_device(boot_serial, boot_id)),
                ("topology", lambda: topology(boot_id)),
                ("source_provenance", lambda: _provenance(source_guard)),
            )
            for key, check in checks:
                try:
                    value[key] = check()
                except BaseException as error:
                    errors.append(error)
            for name, queue in opened.items():
                try:
                    value["queues"][name] = queue.snapshot()
                except BaseException as error:
                    value["queues"][name] = {"error": repr(error)[:2048]}
                    errors.append(error)
            try:
                validate_owner()
            except BaseException as error:
                errors.append(error)
            if "source_provenance" in value and value["source_provenance"] != provenance:
                errors.append(RuntimeError("Source/provenance guard changed"))
            value["end_ns"] = time.monotonic_ns()
            if errors:
                value["errors"] = [repr(error)[:2048] for error in errors]
                raise errors[0]
            return value

        for name in (*EXPECTED, CALLBACK):
            opened[name] = _Queue(name)
        before = capture("before")
        _validate_policy(before["queues"], enabled=enabled, active=False)
        attempted = []
        failure = None
        try:
            for name in EXPECTED if enabled else ():
                queue = opened[name]
                original = before["queues"][name]["attributes"]["cpumask"]
                validate_owner(queue)
                attempted.append(name)
                row = {"queue": name, "attribute": "cpumask", "value": MASK,
                       "before_ns": time.monotonic_ns()}
                record["mutations"].append(row)
                queue.write_mask(MASK)
                row["after_ns"] = time.monotonic_ns()
                row["readback"] = queue.snapshot()
            active = capture("active")
            _validate_policy(active["queues"], enabled=enabled, active=True)
            if active["topology"] != before["topology"]:
                raise RuntimeError("Topology changed during placement")
            for name in opened:
                expected = before["queues"][name]["attributes"].copy()
                if name != CALLBACK and enabled:
                    expected["cpumask"] = active["queues"][name]["attributes"]["cpumask"]
                if active["queues"][name]["attributes"] != expected:
                    raise RuntimeError("Unrelated queue attribute changed: " + name)
            if active["queues"][CALLBACK] != before["queues"][CALLBACK]:
                raise RuntimeError("Active callback queue changed during placement")
            yield record
            exiting = capture("before_restore")
            if any(exiting[key] != active[key]
                   for key in ("queues", "topology", "source_provenance")):
                raise RuntimeError("Active queue policy/identity/topology drifted")
        except BaseException as error:
            failure = error
            record["error"] = repr(error)[:2048]
            raise
        finally:
            if "active" not in record:
                try:
                    capture("active")
                except BaseException:
                    pass
            if "before_restore" not in record:
                try:
                    capture("before_restore")
                except BaseException:
                    pass
            for name in reversed(attempted):
                queue = opened[name]
                original = before["queues"][name]["attributes"]["cpumask"]
                row = {"queue": name, "attribute": "cpumask", "value": original,
                       "before_ns": time.monotonic_ns()}
                record["restorations"].append(row)
                try:
                    validate_owner(queue)
                    queue.write_mask(original)
                    row["readback"] = queue.read("cpumask")
                    if row["readback"] != original:
                        raise RuntimeError("Restoration readback mismatch")
                except BaseException as error:
                    row["error"] = repr(error)[:2048]
                    record["restoration_errors"].append(name + ": " + row["error"])
                row["after_ns"] = time.monotonic_ns()
            try:
                after = capture("after")
                if after["topology"] != before["topology"]:
                    raise RuntimeError("Topology changed before restoration check")
                for name in opened:
                    if after["queues"][name]["attributes"] != before["queues"][name]["attributes"]:
                        raise RuntimeError("Original queue attributes differ: " + name)
                if after["queues"][CALLBACK] != before["queues"][CALLBACK]:
                    raise RuntimeError("Callback queue changed before restoration check")
            except BaseException as error:
                record["restoration_errors"].append("final readback: " + repr(error)[:2048])
            record["end_ns"] = time.monotonic_ns()
            if record["restoration_errors"]:
                raise MaintenancePolicyError(record) from failure
    except BaseException as error:
        if "error" not in record:
            record["error"] = repr(error)[:2048]
        error.receipt = record
        raise
    finally:
        for queue in reversed(tuple(opened.values())):
            os.close(queue.fd)
        os.close(fd)
