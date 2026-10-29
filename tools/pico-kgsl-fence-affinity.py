"""Temporary affinity for one exact private fence worker; no policy changes."""

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import re

PROC = Path("/proc")
PARAM = Path("/sys/module/msm_kgsl_core/parameters/fence_rt")
TARGET = {0, 1, 2, 3}


def native(boot, enabled, serial, kernel_notes_sha256):
    assert os.geteuid() == 0
    assert (PROC / "sys/kernel/random/boot_id").read_text().strip() == boot
    tokens = (PROC / "cmdline").read_text().split()
    assert isinstance(serial, str) and serial and not any(c.isspace() for c in serial)
    assert re.fullmatch(r"[0-9a-f]{64}", kernel_notes_sha256) is not None
    assert "androidboot.serialno=" + serial in tokens and "reframed.live=usb" in tokens
    assert [x for x in tokens if x.startswith("msm_kgsl_core.fence_rt=")] == [
        "msm_kgsl_core.fence_rt=" + str(int(enabled))
    ]
    assert PARAM.read_text().strip() == ("Y" if enabled else "N")
    assert (
        hashlib.sha256(Path("/sys/kernel/notes").read_bytes()).hexdigest()
        == kernel_notes_sha256
    )


def task(pid):
    root = PROC / str(pid)
    raw = (root / "stat").read_text()
    begin, end = raw.find("("), raw.rfind(")")
    assert begin > 0 and end > begin and raw[begin + 1 : end] == "kgsl-fence"
    fields = raw[end + 2 :].split()
    assert int(raw[:begin].strip()) == pid and int(fields[1]) == 2
    assert (root / "cmdline").read_bytes() == b""
    status = (root / "status").read_text().splitlines()
    uids = [line.split(":", 1)[1].split() for line in status if line.startswith("Uid:")]
    assert uids == [["0", "0", "0", "0"]]
    assert (os.sched_getscheduler(pid), os.sched_getparam(pid).sched_priority) == (
        1,
        40,
    )
    assert (int(fields[38]), int(fields[37])) == (1, 40)
    return {
        "pid": pid,
        "start_ticks": int(fields[19]),
        "comm": "kgsl-fence",
        "ppid": 2,
        "cmdline_empty": True,
        "uids": [0, 0, 0, 0],
        "policy": 1,
        "rt_priority": 40,
        "cpus": sorted(os.sched_getaffinity(pid)),
    }


def workers():
    result = []
    for path in sorted(PROC.glob("[0-9]*/comm")):
        try:
            comm = path.read_text().strip()
        except FileNotFoundError:
            continue
        if comm == "kgsl-fence":
            result.append(task(int(path.parent.name)))
    return result


def identity(row):
    return {"pid": row["pid"], "start_ticks": row["start_ticks"]}


@contextmanager
def session(boot, out, *, enabled, serial, kernel_notes_sha256):
    assert type(enabled) is bool
    out = Path(out)
    assert out.parent.is_dir() and not out.exists() and not out.is_symlink()
    record = {
        "schema": 1,
        "boot_id": boot,
        "enabled": enabled,
        "serial": serial,
        "kernel_notes_sha256": kernel_notes_sha256,
        "target_cpus": sorted(TARGET),
        "worker_identity": None,
        "writes": [],
        "restored": False,
        "errors": [],
    }
    before = None
    attempted = False

    def save():
        out.write_text(json.dumps(record, indent=2) + "\n")

    try:
        native(boot, enabled, serial, kernel_notes_sha256)
        found = workers()
        record["before"] = found
        assert len(found) == (1 if enabled else 0), found
        if enabled:
            before = found[0]
            record["worker_identity"] = identity(before)
            assert before["start_ticks"] > 0 and before["cpus"]
            if set(before["cpus"]) != TARGET:
                verified = task(before["pid"])
                assert (
                    identity(verified) == identity(before)
                    and verified["cpus"] == before["cpus"]
                )
                attempted = True
                record["writes"].append(
                    {"pid": before["pid"], "cpus": sorted(TARGET), "reason": "bind"}
                )
                os.sched_setaffinity(before["pid"], TARGET)
            active = task(before["pid"])
            assert (
                identity(active) == identity(before) and set(active["cpus"]) == TARGET
            )
            record["active"] = active
        else:
            record["active"] = None
        save()
        yield record
    except BaseException as error:
        record["errors"].append(repr(error))
        error.fence_affinity_receipt = record
        raise
    finally:
        try:
            native(boot, enabled, serial, kernel_notes_sha256)
            if before is not None:
                found = workers()
                assert len(found) == 1 and identity(found[0]) == identity(before)
                current = found[0]
                assert set(current["cpus"]) in (TARGET, set(before["cpus"])), current
                if attempted and set(current["cpus"]) != set(before["cpus"]):
                    record["writes"].append(
                        {
                            "pid": before["pid"],
                            "cpus": before["cpus"],
                            "reason": "restore",
                        }
                    )
                    os.sched_setaffinity(before["pid"], set(before["cpus"]))
                after = task(before["pid"])
                assert (
                    identity(after) == identity(before)
                    and after["cpus"] == before["cpus"]
                )
                record["after"] = after
            else:
                assert not workers()
                record["after"] = None
            record["restored"] = True
        except BaseException as error:
            record["errors"].append("restore: " + repr(error))
            error.fence_affinity_receipt = record
            raise
        finally:
            save()
