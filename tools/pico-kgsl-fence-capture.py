from pathlib import Path
import hashlib
import json
import os
import time

EVENT = "kgsl/kgsl_fence_dispatch"
PROC = Path("/proc")
PARAM = Path("/sys/module/msm_kgsl_core/parameters/fence_rt")
ROOT = Path("/sys/kernel/debug/tracing")


def disabled():
    paths = [ROOT / "events" / EVENT / "enable"]
    paths += sorted((ROOT / "instances").glob("*/events/" + EVENT + "/enable"))
    result = {str(p.relative_to(ROOT)): p.read_text().strip() for p in paths}
    assert result and all(value == "0" for value in result.values()), result
    return result


class FenceDispatch:
    def __init__(
        self, out, boot, factory, *, serial, expected_enabled, worker_identity=None
    ):
        assert os.geteuid() == 0
        assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() == boot
        assert (
            isinstance(serial, str) and serial and not any(c.isspace() for c in serial)
        )
        assert (
            "androidboot.serialno=" + serial
            in Path("/proc/cmdline").read_text().split()
        )
        assert type(expected_enabled) is bool
        self.expected_enabled, self.worker_identity = expected_enabled, worker_identity
        self.initial_guard = self.guard()
        self.out, self.boot, self.factory = Path(out), boot, factory
        self.out.mkdir(mode=0o700)
        self.instance = ROOT / "instances/reframed-pico-fence-dispatch"
        self.capture = None
        self.created = False
        self.rows = []
        self.record = {
            "schema": 1,
            "serial": serial,
            "boot_id": boot,
            "event": EVENT,
            "plan": [True, True, True],
            "route_enabled": expected_enabled,
            "initial_guard": self.initial_guard,
            "scope": "RT-only elapsed dispatch envelopes; WQ callback generations remain separate; no CPU-time or display-latch claim",
            "rows": self.rows,
            "restored": False,
            "errors": [],
            "initial_global_enables": disabled(),
        }
        self.save()
        try:
            assert not self.instance.exists()
            self.instance.mkdir()
            self.created = True
            (self.instance / "tracing_on").write_text("0")
            (self.instance / "current_tracer").write_text("nop")
            (self.instance / "trace_clock").write_text("mono")
            (self.instance / "buffer_size_kb").write_text("1024")
            assert (self.instance / "current_tracer").read_text().strip() == "nop"
            assert "[mono]" in (self.instance / "trace_clock").read_text()
            assert all(
                p.read_text().strip() == "0"
                for p in self.instance.glob("events/*/*/enable")
            )
            self.event = self.instance / "events" / EVENT
            raw = (self.event / "format").read_bytes()
            (self.out / "format.txt").write_bytes(raw)
            self.record["format_sha256"] = hashlib.sha256(raw).hexdigest()
            assert (
                b"name: kgsl_fence_dispatch\n" in raw
                and b"field:unsigned int id;" in raw
            )
            (self.event / "filter").write_text("0")
            assert (self.event / "filter").read_text().strip() == "none"
            self.record["filter"] = (self.event / "filter").read_text()
            self.record["configured_global_enables"] = disabled()
            self.save()
        except BaseException as error:
            error.fence_dispatch_handle = self
            try:
                self.cleanup()
            except BaseException as cleanup_error:
                cleanup_error.fence_dispatch_handle = self
                raise
            raise

    def guard(self):
        value = PARAM.read_text().strip()
        assert value == ("Y" if self.expected_enabled else "N"), value
        workers = []
        for path in sorted(PROC.glob("[0-9]*/stat")):
            try:
                raw = path.read_text()
            except FileNotFoundError:
                continue
            begin, end = raw.find("("), raw.rfind(")")
            assert 0 < begin < end
            if raw[begin + 1 : end] != "kgsl-fence":
                continue
            fields = raw[end + 2 :].split()
            assert len(fields) >= 39
            status = (path.parent / "status").read_text()
            masks = [
                line.split(":", 1)[1].strip()
                for line in status.splitlines()
                if line.startswith("Cpus_allowed:")
            ]
            assert len(masks) == 1
            workers.append(
                {
                    "pid": int(raw[:begin].strip()),
                    "comm": "kgsl-fence",
                    "ppid": int(fields[1]),
                    "start_ticks": int(fields[19]),
                    "rt_priority": int(fields[37]),
                    "policy": int(fields[38]),
                    "cpus_allowed": masks[0],
                    "cpus_allowed_int": int(masks[0].replace(",", ""), 16),
                }
            )
        if self.expected_enabled:
            assert isinstance(self.worker_identity, dict)
            assert len(workers) == 1, workers
            worker = workers[0]
            assert worker["pid"] == self.worker_identity["pid"]
            assert worker["start_ticks"] == self.worker_identity["start_ticks"]
            assert worker["ppid"] == 2 and worker["policy"] == 1
            assert worker["rt_priority"] == 40 and worker["cpus_allowed_int"] == 15
        else:
            assert self.worker_identity is None and not workers, workers
        return {
            "parameter": value,
            "workers": workers,
            "read_end_ns": time.monotonic_ns(),
        }

    def save(self):
        (self.out / "receipt.json").write_text(json.dumps(self.record, indent=2) + "\n")

    def start(self, window):
        assert window == len(self.rows) and window in (0, 1, 2)
        assert self.capture is None
        assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() == self.boot
        row = {
            "window": window,
            "enabled": True,
            "route_enabled": self.expected_enabled,
            "worker_before": self.guard(),
            "before_ns": time.monotonic_ns(),
            "global_before": disabled(),
            "complete": False,
        }
        self.rows.append(row)
        self.save()
        if row["enabled"]:
            assert (self.instance / "tracing_on").read_text().strip() == "0"
            assert all(
                p.read_text().strip() == "0"
                for p in self.instance.glob("events/*/*/enable")
            )
            (self.event / "enable").write_text("1")
            assert (self.event / "enable").read_text().strip() == "1"
            self.capture = self.factory(
                self.instance,
                self.out,
                "pico-fence-dispatch-" + str(window),
                16 * 1024 * 1024,
                self.boot,
            )
            self.capture.start()
            row["global_active"] = {
                str(p.relative_to(ROOT)): p.read_text().strip()
                for p in [ROOT / "events" / EVENT / "enable"]
                + sorted((ROOT / "instances").glob("*/events/" + EVENT + "/enable"))
            }
            own = str((self.event / "enable").relative_to(ROOT))
            assert row["global_active"][own] == "1"
            assert all(
                v == ("1" if k == own else "0") for k, v in row["global_active"].items()
            )
        row["ready_ns"] = time.monotonic_ns()
        self.save()

    def finish(self, window):
        assert window < len(self.rows)
        row = self.rows[window]
        if row["complete"]:
            return
        row["finish_begin_ns"] = time.monotonic_ns()
        try:
            if self.capture is not None:
                state = self.capture.finish("fence-window-" + str(window))
                row["capture"] = dict(state)
                assert (
                    state["joined"]
                    and state["error"] is None
                    and not state["cleanup_errors"]
                ), state
                self.capture = None
            row["global_after"] = disabled()
            row["worker_after"] = self.guard()
            row["complete"] = True
        finally:
            row["finish_end_ns"] = time.monotonic_ns()
            self.save()

    def cleanup(self):
        errors = self.record["errors"]
        if self.created:
            try:
                if self.capture is not None:
                    self.record["cleanup_capture"] = dict(
                        self.capture.finish("fence-cleanup")
                    )
                    assert (
                        self.capture.state["joined"]
                        and self.capture.state["error"] is None
                        and self.capture.state["cleanup_errors"] == []
                    )
                    self.capture = None
                (self.instance / "tracing_on").write_text("0")
                for path in self.instance.glob("events/*/*/enable"):
                    if path.read_text().strip() != "0":
                        path.write_text("0")
                self.record["final_global_enables"] = disabled()
                assert (self.instance / "tracing_on").read_text().strip() == "0"
                self.record["quiesced"] = True
            except BaseException as error:
                errors.append(repr(error))
        self.save()
        assert not errors, errors

    def remove(self, *, all_readers_joined):
        assert all_readers_joined is True, (
            "All trace readers must join before instance removal"
        )
        assert self.capture is None and not self.record["errors"]
        if self.created:
            assert self.record.get("quiesced") is True
            assert (self.instance / "tracing_on").read_text().strip() == "0"
            self.record["remove_global_enables"] = disabled()
            self.instance.rmdir()
            self.created = False
        self.record["removed"] = True
        self.record["restored"] = True
        self.record["remove_end_ns"] = time.monotonic_ns()
        self.save()
