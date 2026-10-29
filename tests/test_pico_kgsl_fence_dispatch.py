import importlib.util
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

R = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location(
    "dispatch", R / "pico-kgsl-fence-dispatch.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
spec = importlib.util.spec_from_file_location(
    "capture", R / "pico-kgsl-fence-capture.py"
)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
IDENTITY = {"pid": 123, "start_ticks": 456}
WORKER = dict(
    IDENTITY,
    comm="kgsl-fence",
    ppid=2,
    policy=1,
    rt_priority=40,
    cpus_allowed="0f",
    cpus_allowed_int=15,
)
GUARD = {"parameter": "Y", "workers": [WORKER]}


def line(
    q=1000000000,
    s=1000001000,
    d=1000005001,
    header="1.000005",
    pid=123,
    ctx=1,
    ts=1,
    policy=1,
    prio=59,
    result=1,
):
    return f"      kgsl-fence-{pid} [000] .... {header}: kgsl_fence_dispatch: work=0123456789abcdef ctx={ctx} ts={ts} result={result} queued_ns={q} start_ns={s} done_ns={d} policy={policy} prio={prio}\n".encode()


def stats(n=0):
    return dict(
        zip(p.STAT_FIELDS, [0, 0, 0, 0, 0, n]),
        **{"oldest event ts": "0.000000", "now ts": "1.000100"},
    )


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "raw"

    def parse(self, raw=None):
        self.path.write_bytes(line() if raw is None else raw)
        return p.analyze(self.path)

    def qualify(self, parsed=None, **change):
        parsed = parsed or self.parse()
        before = {i: stats() for i in range(8)}
        after = {i: stats(parsed["per_cpu_rows"].get(i, 0)) for i in range(8)}
        args = dict(
            expected_sha256=parsed["source_sha256"],
            expected_bytes=parsed["source_bytes"],
            stats_before=before,
            stats_after=after,
            start_ns=900000000,
            end_ns=1100000000,
            reader_joined=True,
            reader_error=None,
            cleanup_errors=[],
            source_qualified=True,
            enabled=True,
            allowed_results=[1, 2],
            worker_identity=IDENTITY,
            guard_before=GUARD,
            guard_after=GUARD,
            patch_sha256=p.PATCH_SHA256,
        )
        args.update(change)
        return p.qualify_capture(parsed, **args)

    def test_rounded_emission_and_durations(self):
        a = self.qualify()
        self.assertTrue(a["capture_accepted"])
        self.assertEqual(a["rows"][0]["durations_ns"]["queue_to_start_ns"], 1000)
        self.assertEqual(a["rows"][0]["printed_upper_ns"], 1000005499)

    def test_valid_cancelled(self):
        self.qualify(self.parse(line(result=2)))

    def test_command_cache_miss_preserves_row_with_independent_identity(self):
        parsed = self.parse(line().replace(b"kgsl-fence-", b"<...>-"))
        qualified = self.qualify(parsed)
        self.assertEqual(qualified["rows"][0]["comm"], "<...>")
        self.assertTrue(qualified["capture_accepted"])

    def test_known_wrong_command_rejected(self):
        with self.assertRaisesRegex(ValueError, "RT worker identity"):
            self.qualify(self.parse(line().replace(b"kgsl-fence-", b"other-task-")))

    def test_command_cache_miss_cannot_hide_pid_reuse(self):
        parsed = self.parse(line().replace(b"kgsl-fence-", b"<...>-"))
        after = copy.deepcopy(GUARD)
        after["workers"][0]["start_ticks"] += 1
        with self.assertRaises(ValueError):
            self.qualify(parsed, guard_after=after)
        with self.assertRaisesRegex(ValueError, "RT worker identity"):
            self.qualify(self.parse(line(pid=124).replace(b"kgsl-fence-", b"<...>-")))

    def test_complete_file_not_prefix(self):
        for raw in [
            line() + b"bad\n",
            line()[:-1],
            line().replace(b"kgsl_fence_dispatch:", b"workqueue_execute_start:"),
        ]:
            with self.subTest(raw=raw[-30:]), self.assertRaises(ValueError):
                self.parse(raw)

    def test_mark_and_header_bounds(self):
        for raw in [line(s=999999999), line(d=1000005500), line(q=0)]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.parse(raw)

    def test_valid_queued_while_previous_callback_runs(self):
        a = self.parse(
            line()
            + line(q=1000001000, s=1000006000, d=1000007000, header="1.000007", ts=2)
        )
        self.assertEqual(a["row_count"], 2)

    def test_invalid_overlapping_single_worker(self):
        with self.assertRaises(ValueError):
            self.parse(
                line()
                + line(
                    q=1000001000, s=1000004000, d=1000007000, header="1.000007", ts=2
                )
            )

    def test_duplicate(self):
        with self.assertRaises(ValueError):
            self.parse(line() + line())

    def test_legitimate_empty_control(self):
        a = self.qualify(
            self.parse(b""),
            enabled=False,
            worker_identity=None,
            guard_before={"parameter": "N", "workers": []},
            guard_after={"parameter": "N", "workers": []},
        )
        self.assertTrue(a["capture_accepted"])

    def test_empty_enabled_rejected(self):
        with self.assertRaises(ValueError):
            self.qualify(self.parse(b""))

    def test_rows_with_control_rejected(self):
        with self.assertRaises(ValueError):
            self.qualify(
                enabled=False,
                worker_identity=None,
                guard_before={"parameter": "N", "workers": []},
                guard_after={"parameter": "N", "workers": []},
            )

    def test_hash_bytes_closure_source_pins(self):
        for args in [
            dict(expected_bytes=0),
            dict(expected_sha256="0" * 64),
            dict(reader_joined=False),
            dict(reader_error="failure"),
            dict(cleanup_errors=["failure"]),
            dict(source_qualified=False),
            dict(patch_sha256="0" * 64),
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.qualify(**args)

    def test_stats_loss_count_inventory(self):
        for key, val in [
            ("overrun", 1),
            ("commit overrun", 1),
            ("dropped events", 1),
            ("entries", 1),
            ("read events", 0),
        ]:
            after = {i: stats(1 if i == 0 else 0) for i in range(8)}
            after[0][key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.qualify(stats_after=after)
        with self.assertRaises(ValueError):
            self.qualify(stats_before={0: stats()})

    def test_pid_policy_result_guard(self):
        for raw in [line(pid=124), line(policy=0), line(prio=100), line(result=3)]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.qualify(self.parse(raw))
        for key, val in [
            ("pid", 124),
            ("start_ticks", 999),
            ("comm", "other"),
            ("ppid", 1),
            ("policy", 0),
            ("rt_priority", 39),
            ("cpus_allowed_int", 255),
        ]:
            g = copy.deepcopy(GUARD)
            g["workers"][0][key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.qualify(guard_after=g)

    def test_param_and_unique_guard(self):
        for g in [
            {"parameter": "N", "workers": [WORKER]},
            {"parameter": "Y", "workers": [WORKER, WORKER]},
            {"parameter": "Y", "workers": []},
        ]:
            with self.subTest(g=g), self.assertRaises(ValueError):
                self.qualify(guard_after=g)

    def test_whole_capture_bounds(self):
        for args in [dict(start_ns=1000000001), dict(end_ns=1000005499)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.qualify(**args)

    def test_containment_reports_edges_without_clipping(self):
        a = self.qualify()
        v = p.contained_window(a, start_ns=999999999, end_ns=1000005500)
        self.assertEqual(v["contained_rows"], 1)
        self.assertEqual(v["per_context"]["1"]["count"], 1)
        v = p.contained_window(a, start_ns=1000000001, end_ns=1000005499)
        self.assertEqual(v["contained_rows"], 0)
        self.assertEqual(len(v["boundary_exclusions"]), 1)
        self.assertEqual(len(v["boundary_exclusions"][0]["reasons"]), 2)
        self.assertEqual(a["row_count"], 1)

    def test_summary_requires_capture_acceptance(self):
        with self.assertRaises(ValueError):
            p.contained_window(self.parse(), start_ns=1, end_ns=2000000000)


class NativeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.param = self.root / "param"
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.owner = c.FenceDispatch.__new__(c.FenceDispatch)
        self.owner.expected_enabled = True
        self.owner.worker_identity = IDENTITY
        self.a = patch.object(c, "PARAM", self.param)
        self.b = patch.object(c, "PROC", self.proc)
        self.a.start()
        self.b.start()
        self.addCleanup(self.a.stop)
        self.addCleanup(self.b.stop)
        self.param.write_text("Y\n")
        self.worker(123)

    def worker(self, pid, policy=1, rt=40, mask="0000000f", start=456):
        d = self.proc / str(pid)
        d.mkdir(exist_ok=True)
        f = ["0"] * 50
        f[0] = "S"
        f[1] = "2"
        f[19] = str(start)
        f[37] = str(rt)
        f[38] = str(policy)
        (d / "stat").write_text(f"{pid} (kgsl-fence) " + " ".join(f))
        (d / "status").write_text("Cpus_allowed:\t" + mask + "\n")

    def test_exact_worker(self):
        self.assertEqual(self.owner.guard()["workers"][0]["start_ticks"], 456)

    def test_reused_pid_rejected(self):
        self.worker(123, start=457)
        with self.assertRaises(AssertionError):
            self.owner.guard()

    def test_wrong_policy_affinity_duplicate(self):
        for kw in [dict(policy=0), dict(rt=39), dict(mask="ff")]:
            self.worker(123, **kw)
            with self.subTest(kw=kw), self.assertRaises(AssertionError):
                self.owner.guard()
        self.worker(123)
        self.worker(124)
        with self.assertRaises(AssertionError):
            self.owner.guard()

    def test_control_requires_no_worker(self):
        self.owner.expected_enabled = False
        self.owner.worker_identity = None
        self.param.write_text("N")
        with self.assertRaises(AssertionError):
            self.owner.guard()
        (self.proc / "123/stat").unlink()
        self.assertEqual(self.owner.guard()["workers"], [])


if __name__ == "__main__":
    unittest.main()
