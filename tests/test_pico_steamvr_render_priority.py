import copy
from contextlib import ExitStack, contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('render_priority',
    Path(__file__).resolve().parents[1]/'tools/pico-steamvr-render-priority.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RESET = 0x40000000


class RenderPriorityTests(unittest.TestCase):
    def state(self):
        return {'pid': 20, 'tid': 21, 'executable': '/opt/vrcompositor',
                'process_start': 100, 'thread_start': 110, 'policy': 0, 'rt_priority': 0,
                'affinity': [4, 5, 6], 'nice': -20,
                'limits': {'rtprio': [2, 2], 'rttime_us': [100000, 100000]}}

    def proof(self):
        return {'schema': 1, 'boot_id': 'fixture-boot', 'pid': 20, 'tid': 21,
                'process_start': 100, 'thread_start': 110, 'observed_ns': 200000000000,
                'dashboard_app_key': 'valve.steam.gamepadui.main', 'dashboard_visible': True,
                'gpu_context': 1}

    @contextmanager
    def fixture(self, state=None, setter=None, reader=None, validate=None, proof=None):
        state = self.state() if state is None else state
        writes = []
        def write(tid, policy, param):
            self.assertEqual(tid, 21)
            writes.append((policy, param.sched_priority))
            state.update(policy=policy, rt_priority=param.sched_priority)
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            ready = root/'ready.json'
            raw = json.dumps(self.proof() if proof is None else proof).encode()
            ready.write_bytes(raw)
            for name, value in [('SCHED_OTHER', 0), ('SCHED_RR', 2), ('SCHED_RESET_ON_FORK', RESET)]:
                stack.enter_context(patch.object(MODULE.os, name, value, create=True))
            stack.enter_context(patch.object(MODULE.os, 'sched_param',
                side_effect=lambda p: SimpleNamespace(sched_priority=p), create=True))
            stack.enter_context(patch.object(MODULE.os, 'sched_setscheduler', setter or write, create=True))
            stack.enter_context(patch.object(MODULE, 'LOCK', root/'lock'))
            stack.enter_context(patch.object(MODULE, 'PROC', root))
            stack.enter_context(patch.object(MODULE, 'validate_device', validate or (lambda *_: None)))
            stack.enter_context(patch.object(MODULE, 'snapshot', reader or (lambda *_: copy.deepcopy(state))))
            stack.enter_context(patch.object(MODULE.os, 'fstat', return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_size=len(raw))))
            stack.enter_context(patch.object(MODULE.time, 'monotonic_ns', return_value=201000000000))
            yield root, ready, state, writes

    def context(self, ready):
        return MODULE.prioritize_render('fixture', 'fixture-boot', 20, 21, ready)

    def test_exact_promotion_and_restoration(self):
        with self.fixture() as (_, ready, state, writes):
            before = copy.deepcopy(state)
            with self.context(ready) as record:
                self.assertEqual(record['active'], before | {'policy': 2 | RESET, 'rt_priority': 2})
                self.assertEqual(record['ready']['proof'], self.proof())
            self.assertEqual(state, before)
            self.assertEqual(record['after'], before)
            self.assertEqual(record['restoration'], 'restored')
            self.assertEqual(writes, [(2 | RESET, 2), (0, 0)])

    def test_driver_reset_flag_loss_at_readback_and_restoration(self):
        for when in ('readback', 'body'):
            with self.subTest(when=when):
                state, writes = self.state(), []
                def setter(_tid, policy, param):
                    writes.append((policy, param.sched_priority))
                    state.update(policy=policy & ~RESET if when == 'readback' else policy,
                                 rt_priority=param.sched_priority)
                with self.fixture(state, setter) as (_, ready, _, _):
                    with self.context(ready):
                        state['policy'] &= ~RESET
                self.assertEqual(state, self.state())
                self.assertEqual(writes, [(2 | RESET, 2), (0, 0)])

    def test_initial_policy_and_limits_refused_without_writes(self):
        for key, value in [('nice', 0), ('policy', 2), ('rt_priority', 1), ('affinity', []),
                           ('limits', {'rtprio': [3, 3], 'rttime_us': [100000, 100000]}),
                           ('limits', {'rtprio': [2, 2], 'rttime_us': [100000, 200000]})]:
            with self.subTest(key=key, value=value), self.fixture(self.state() | {key: value}) as (_, ready, _, writes):
                with self.assertRaisesRegex(ValueError, 'Requires OTHER'):
                    with self.context(ready):self.fail('Entered invalid context')
                self.assertEqual(writes, [])

    def test_receipt_identity_visibility_age_and_schema(self):
        invalid = [('schema', True), ('schema', 2), ('boot_id', 'other'), ('pid', 22), ('tid', 22),
                   ('process_start', 101), ('thread_start', 111), ('observed_ns', 1),
                   ('observed_ns', 202000000000), ('dashboard_visible', 1),
                   ('dashboard_app_key', 'another'), ('gpu_context', 0), ('gpu_context', True)]
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.fixture(proof=self.proof() | {key: value}) as (_, ready, _, writes):
                with self.assertRaises(ValueError):
                    with self.context(ready):self.fail('Entered invalid context')
                self.assertEqual(writes, [])
        with self.fixture(proof={}) as (_, ready, _, writes), self.assertRaises(ValueError):
            with self.context(ready):self.fail('Missing receipt fields accepted')
        self.assertEqual(writes, [])

    def test_private_regular_receipt_and_no_follow(self):
        for field, value in [('st_uid', 1000), ('st_nlink', 2), ('st_mode', stat.S_IFREG | 0o644),
                             ('st_mode', stat.S_IFIFO | 0o600), ('st_size', 32769)]:
            with self.subTest(field=field), self.fixture() as (_, ready, _, writes):
                info = dict(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_size=ready.stat().st_size)
                info[field] = value
                with patch.object(MODULE.os, 'fstat', return_value=SimpleNamespace(**info)), self.assertRaises(ValueError):
                    MODULE.ready_receipt(ready, 'fixture-boot', self.state())
                self.assertEqual(writes, [])
        with self.fixture() as (root, ready, _, _):
            link = root/'link';link.symlink_to(ready)
            with self.assertRaises(OSError):MODULE.ready_receipt(link, 'fixture-boot', self.state())

    def test_request_failure_before_and_after_application(self):
        for applied in (False, True):
            with self.subTest(applied=applied):
                state, writes = self.state(), []
                def setter(_tid, policy, param):
                    writes.append((policy, param.sched_priority))
                    if policy == 0 or applied:state.update(policy=policy, rt_priority=param.sched_priority)
                    if policy:raise OSError('request failed')
                with self.fixture(state, setter) as (_, ready, _, _), self.assertRaisesRegex(OSError, 'request failed'):
                    with self.context(ready):self.fail('Failed request yielded')
                self.assertEqual(state, self.state())
                self.assertEqual(writes, [(2 | RESET, 2)] + ([(0, 0)] if applied else []))

    def test_readback_error_and_body_failure_restore(self):
        for fault in ('readback', 'body'):
            state, calls = self.state(), [0]
            def reader(*_):
                calls[0] += 1
                if fault == 'readback' and calls[0] == 2:raise OSError('readback failed')
                return copy.deepcopy(state)
            with self.subTest(fault=fault), self.fixture(state, reader=reader) as (_, ready, _, writes):
                with self.assertRaises((OSError, RuntimeError)):
                    with self.context(ready):raise RuntimeError('body failed')
                self.assertEqual(writes, [(2 | RESET, 2), (0, 0)])
                self.assertEqual(state, self.state())

    def test_noop_request_readback_refused_without_restoration_write(self):
        writes = []
        with self.fixture(setter=lambda _t, p, s: writes.append((p, s.sched_priority))) as (_, ready, _, _):
            with self.assertRaisesRegex(RuntimeError, 'readback') as error:
                with self.context(ready):self.fail('No-op request accepted')
            observed = json.loads(str(error.exception).split(': ', 1)[1])
            self.assertEqual(observed, {'before': self.state(), 'active': self.state()})
        self.assertEqual(writes, [(2 | RESET, 2)])

    def test_failed_readback_preserves_changed_fields_and_restores_owned_task(self):
        state, calls = self.state(), [0]
        def reader(*_):
            calls[0] += 1
            observed = copy.deepcopy(state)
            if calls[0] == 2:observed['affinity'] = [7]
            return observed
        with self.fixture(state, reader=reader) as (_, ready, _, writes):
            with self.assertRaisesRegex(RuntimeError, 'readback') as error:
                with self.context(ready):self.fail('Changed readback accepted')
            observed = json.loads(str(error.exception).split(': ', 1)[1])
            self.assertEqual(observed['before'], self.state())
            self.assertEqual(observed['active'], self.state() | {
                'policy': 2 | RESET, 'rt_priority': 2, 'affinity': [7]})
            self.assertEqual(state, self.state())
            self.assertEqual(writes, [(2 | RESET, 2), (0, 0)])

    def test_restore_refuses_identity_policy_affinity_nice_or_limit_drift(self):
        faults = [('process_start', 101), ('thread_start', 111), ('executable', '/other/vrcompositor'),
                  ('affinity', [7]), ('nice', 0), ('policy', 0), ('policy', 1), ('rt_priority', 1),
                  ('limits', {'rtprio': [2, 2], 'rttime_us': [200000, 200000]})]
        for key, value in faults:
            with self.subTest(key=key, value=value), self.fixture() as (_, ready, state, writes):
                with self.assertRaisesRegex(RuntimeError, 'restoration refused'):
                    with self.context(ready):state[key] = value
                self.assertEqual(writes, [(2 | RESET, 2)])

    def test_boot_drift_refuses_restoration(self):
        changed = [False]
        def validate(*_):
            if changed[0]:raise ValueError('boot changed')
        with self.fixture(validate=validate) as (_, ready, _, writes):
            with self.assertRaisesRegex(ValueError, 'boot changed'):
                with self.context(ready):changed[0] = True
            self.assertEqual(writes, [(2 | RESET, 2)])

    def test_exited_task_vs_failed_inspection(self):
        for exists in (False, True):
            state, gone = self.state(), [False]
            def reader(*_):
                if gone[0]:raise FileNotFoundError('task inspection unavailable')
                return copy.deepcopy(state)
            with self.subTest(exists=exists), self.fixture(state, reader=reader) as (root, ready, _, writes):
                if exists:
                    task = root/'20/task/21/stat';task.parent.mkdir(parents=True);task.touch()
                def run():
                    with self.context(ready) as record:gone[0] = True
                    return record
                if exists:
                    with self.assertRaisesRegex(RuntimeError, 'task still exists'):run()
                else:self.assertEqual(run()['restoration'], 'owned-renderer-exited')
                self.assertEqual(writes, [(2 | RESET, 2)])

    def test_restoration_write_or_readback_failure_is_reported(self):
        for fault in ('write', 'readback'):
            state = self.state()
            def setter(_tid, policy, param):
                if policy == 0 and fault == 'write':raise OSError('restore write failed')
                state.update(policy=policy, rt_priority=param.sched_priority)
                if policy == 0 and fault == 'readback':state['nice'] = -19
            with self.subTest(fault=fault), self.fixture(state, setter) as (_, ready, _, _):
                with self.assertRaises((OSError, RuntimeError)):
                    with self.context(ready):pass

    def test_receipt_non_object_and_truncated_read_are_refused(self):
        for raw in (b'[]', b'{', b'null'):
            with self.subTest(raw=raw), self.fixture() as (_, ready, _, _):
                ready.write_bytes(raw)
                info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_size=len(raw))
                with patch.object(MODULE.os, 'fstat', return_value=info), self.assertRaises(ValueError):
                    MODULE.ready_receipt(ready, 'fixture-boot', self.state())
        with self.fixture() as (_, ready, _, _), patch.object(MODULE.os, 'read', return_value=b'{}'):
            with self.assertRaisesRegex(ValueError, 'changed'):
                MODULE.ready_receipt(ready, 'fixture-boot', self.state())

    def test_helper_never_writes_affinity_nice_or_limits(self):
        with self.fixture() as (_, ready, _, _), \
                patch.object(MODULE.os, 'setpriority', side_effect=AssertionError('nice write')), \
                patch.object(MODULE.os, 'sched_setaffinity', side_effect=AssertionError('affinity write'), create=True):
            with self.context(ready):pass

    def test_cli_rejects_unbounded_duration_before_activation(self):
        for seconds in ('0', '901'):
            with self.subTest(seconds=seconds), patch.object(MODULE, 'prioritize_render') as promote, \
                    patch('sys.stderr', new_callable=io.StringIO), \
                    patch('sys.argv', ['helper', '--boot-serial', 'fixture', '--boot-id', 'fixture-boot',
                                      '--pid', '20', '--tid', '21', '--ready-json', '/fixture', '--seconds', seconds]):
                with self.assertRaises(SystemExit):MODULE.main()
                promote.assert_not_called()

    def test_snapshot_role_and_limit_parsing(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp);proc = root/'20';task = proc/'task/21';task.mkdir(parents=True)
            binary = root/'vrcompositor';binary.touch();(proc/'exe').symlink_to(binary)
            (proc/'comm').write_text('vrcompositor\n')
            for path in (proc, task):
                (path/'status').write_text('Uid: 1000 1000 1000 1000\n');(path/'cgroup').write_text(MODULE.GROUP+'\n')
            fields = ['S']+['0']*18+['100'];(proc/'stat').write_text('20 (vrcompositor) '+' '.join(fields))
            fields[-1] = '110';(task/'stat').write_text('21 (RenderThread) '+' '.join(fields))
            (proc/'limits').write_text('Max realtime priority     2       2\nMax realtime timeout      100000  100000  us\n')
            stack.enter_context(patch.object(MODULE, 'PROC', root))
            for name, value in [('sched_getscheduler', 0), ('sched_getparam', SimpleNamespace(sched_priority=0)),
                                ('sched_getaffinity', {4, 5, 6}), ('getpriority', -20)]:
                stack.enter_context(patch.object(MODULE.os, name, return_value=value, create=True))
            self.assertEqual(MODULE.snapshot(20, 21), self.state() | {'executable': str(binary.resolve())})
            for path, bad in [(proc/'comm', 'other'), (proc/'status', 'Uid: 0 0 0 0'),
                              (task/'status', 'Uid: 0 0 0 0'), (proc/'cgroup', '0::/other'),
                              (task/'cgroup', MODULE.GROUP+'\n1:other\n'),
                              (task/'stat', '21 (other) '+' '.join(fields)),
                              (proc/'limits', 'Max realtime priority unlimited unlimited\n')]:
                original = path.read_text();path.write_text(bad)
                with self.subTest(path=path), self.assertRaises(ValueError):MODULE.snapshot(20, 21)
                path.write_text(original)
            for pid, tid in [(True, 21), (0, 21), (20, -1)]:
                with self.assertRaises(ValueError):MODULE.snapshot(pid, tid)

    def test_cli_signal_unwinds_context_and_restores_handlers(self):
        handlers, lifecycle = {}, []
        @contextmanager
        def context(*_):
            lifecycle.append('active')
            try:yield {'fixture': True}
            finally:lifecycle.append('restored')
        def set_handler(sig, handler):
            old = handlers.get(sig, signal.SIG_DFL);handlers[sig] = handler;return old
        with patch.object(MODULE, 'prioritize_render', context), \
                patch.object(MODULE.signal, 'signal', set_handler), \
                patch.object(MODULE.time, 'sleep', side_effect=lambda _: handlers[signal.SIGTERM]()), \
                patch('sys.stdout', new_callable=io.StringIO), \
                patch('sys.argv', ['helper', '--boot-serial', 'fixture', '--boot-id', 'fixture-boot',
                                  '--pid', '20', '--tid', '21', '--ready-json', '/fixture', '--seconds', '1']):
            MODULE.main()
        self.assertEqual(lifecycle, ['active', 'restored'])
        self.assertEqual(handlers, {signal.SIGTERM: signal.SIG_DFL, signal.SIGINT: signal.SIG_DFL})


if __name__ == '__main__':
    unittest.main()
