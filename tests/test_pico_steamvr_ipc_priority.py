import importlib.util
from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('ipc_priority',
    Path(__file__).resolve().parents[1]/'tools/pico-steamvr-ipc-priority.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IpcPriorityTests(unittest.TestCase):
    def state(self):
        return {'pid': 20, 'tid': 21, 'process_start': 100, 'thread_start': 110,
                'policy': 0, 'rt_priority': 0, 'affinity': [0, 1, 2, 3], 'nice': 0}

    def run_context(self, root, state, setter, body=lambda _: None, validate=lambda *_: None, reader=None):
        with patch.object(MODULE, 'LOCK', root/'lock'), \
                patch.object(MODULE.os, 'SCHED_OTHER', 0), \
                patch.object(MODULE, 'validate_device', validate), \
                patch.object(MODULE, 'snapshot', side_effect=reader or (lambda *_: dict(state))), \
                patch.object(MODULE.os, 'fstat', return_value=SimpleNamespace(
                    st_mode=0o100600, st_uid=0, st_nlink=1)), \
                patch.object(MODULE.os, 'setpriority', setter):
            with MODULE.prioritize_worker('fixture', 'fixture-boot', 20, 21) as record:
                body(record)
            return record

    def test_priority_and_exact_restoration_keep_rt_and_affinity(self):
        state, writes = self.state(), []
        def setter(which, tid, value):
            self.assertEqual((which, tid), (os.PRIO_PROCESS, 21))
            writes.append(value)
            state['nice'] = value
        with tempfile.TemporaryDirectory() as tmp:
            record = self.run_context(Path(tmp), state, setter,
                lambda r: self.assertEqual(r['active'], r['before'] | {'nice': -20}))
        self.assertEqual(writes, [-20, 0])
        self.assertEqual(record['after'], record['before'])

    def test_applied_then_failed_write_and_body_failure_restore(self):
        for failure in ('write', 'body'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                state, writes = self.state(), []
                def setter(_which, _tid, value):
                    state['nice'] = value
                    writes.append(value)
                    if failure == 'write' and value == -20:
                        raise OSError('fixture applied-then-failed')
                def body(_record):
                    raise RuntimeError('fixture body failure')
                with self.assertRaises((OSError, RuntimeError)):
                    self.run_context(Path(tmp), state, setter, body)
                self.assertEqual(writes, [-20, 0])
                self.assertEqual(state['nice'], 0)

    def test_readback_failure_is_restored(self):
        state, writes = self.state(), []
        def setter(_which, _tid, value):
            writes.append(value)
            state['nice'] = -10 if value == -20 else value
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(RuntimeError, 'readback'):
            self.run_context(Path(tmp), state, setter)
        self.assertEqual(writes, [-20, 0])

    def test_refuse_existing_policy_without_writes(self):
        for field, value in [('nice', -5), ('policy', 2), ('rt_priority', 1)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                state = self.state() | {field: value}
                with self.assertRaisesRegex(ValueError, 'ordinary-priority'):
                    self.run_context(Path(tmp), state, lambda *_: self.fail('Unexpected write'))

    def test_no_restore_across_boot_or_thread_identity_change(self):
        for fault in ('boot', 'identity', 'affinity'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                state, writes, changed = self.state(), [], [False]
                def setter(_which, _tid, value):
                    state['nice'] = value
                    writes.append(value)
                def validate(*_):
                    if fault == 'boot' and changed[0]:
                        raise ValueError('fixture boot changed')
                def body(_record):
                    changed[0] = True
                    if fault == 'identity':
                        state['thread_start'] += 1
                    elif fault == 'affinity':
                        state['affinity'] = [3]
                with self.assertRaises((ValueError, RuntimeError)):
                    self.run_context(Path(tmp), state, setter, body, validate)
                self.assertEqual(writes, [-20])

    def test_exited_worker_requires_no_write_but_failed_inspection_is_not_exit(self):
        for task_exists in (False, True):
            with self.subTest(task_exists=task_exists), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state, writes, gone = self.state(), [], [False]
                if task_exists:
                    path = root/'20/task/21/stat'
                    path.parent.mkdir(parents=True)
                    path.touch()
                def read(*_):
                    if gone[0]:
                        raise FileNotFoundError('fixture inspection unavailable')
                    return dict(state)
                def setter(_which, _tid, value):
                    writes.append(value)
                    state['nice'] = value
                def body(_record):
                    gone[0] = True
                with patch.object(MODULE, 'PROC', root):
                    if task_exists:
                        with self.assertRaisesRegex(RuntimeError, 'task still exists'):
                            self.run_context(root, state, setter, body, reader=read)
                    else:
                        result = self.run_context(root, state, setter, body, reader=read)
                        self.assertEqual(result['restoration'], 'owned-worker-exited')
                self.assertEqual(writes, [-20])

    def test_restore_write_failure_is_not_reported_as_success(self):
        state = self.state()
        def setter(_which, _tid, value):
            if value == 0:
                raise OSError('fixture restoration failure')
            state['nice'] = value
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(OSError, 'restoration failure'):
            self.run_context(Path(tmp), state, setter)

    def test_snapshot_requires_owned_api_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            process = root/'20'
            task = process/'task/21'
            task.mkdir(parents=True)
            binary = root/'steamwebhelper'
            binary.touch()
            (process/'exe').symlink_to(binary)
            (process/'comm').write_text('steamwebhelper\n')
            (process/'status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
            (process/'cgroup').write_text(MODULE.GROUP+'\n')
            fields = ['S']+['0']*18+['100']
            (process/'stat').write_text('20 (steamwebhelper) '+' '.join(fields))
            fields[-1] = '110'
            (task/'stat').write_text('21 (CVRAPIITask::Ru) '+' '.join(fields))
            with patch.object(MODULE, 'PROC', root), \
                    patch.object(MODULE.os, 'sched_getscheduler', return_value=0, create=True), \
                    patch.object(MODULE.os, 'sched_getparam', return_value=SimpleNamespace(sched_priority=0), create=True), \
                    patch.object(MODULE.os, 'sched_getaffinity', return_value={0, 1, 2, 3}, create=True), \
                    patch.object(MODULE.os, 'getpriority', return_value=0):
                self.assertEqual(MODULE.snapshot(20, 21), self.state())
                for name, bad in [('comm', 'another-program'), ('status', 'Uid: 0 0 0 0'),
                                  ('cgroup', '0::/another.service')]:
                    path = process/name
                    original = path.read_text()
                    path.write_text(bad)
                    with self.assertRaises(ValueError):
                        MODULE.snapshot(20, 21)
                    path.write_text(original)
                (task/'stat').write_text('21 (unrelated worker) '+' '.join(fields))
                with self.assertRaises(ValueError):
                    MODULE.snapshot(20, 21)


if __name__ == '__main__':
    unittest.main()
