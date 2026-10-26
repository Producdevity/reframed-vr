from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import signal
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('imu_priority',
    Path(__file__).resolve().parents[1]/'tools/pico-imu-priority.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
SHA = 'a'*64


def state():
    tasks = [{'tid': tid, 'start': start, 'comm': comm, 'policy': 0,
              'rt_priority': 0, 'nice': 0, 'affinity': [0, 1]}
             for tid, start, comm in [(20, 100, 'producer-live'), (21, 101, 'ssc-imu'), (22, 102, 'gmain')]]
    return {'pid': 20, 'tid': 21, 'process_start': 100, 'thread_start': 101,
            'executable': {'sha256': SHA}, 'limits': 'limits\n', 'tasks': tasks,
            'policy': 0, 'rt_priority': 0, 'nice': 0, 'affinity': [0, 1]}


def write_stat(path, tid, comm, start, status='S'):
    path.mkdir(parents=True, exist_ok=True)
    (path/'stat').write_text(f'{tid} ({comm}) '+ ' '.join([status]+['0']*18+[str(start)])+'\n')


class ImuPriorityTests(unittest.TestCase):
    @contextmanager
    def environment(self, root, current, writes, *, reader=None, setter=None, gone=None, validator=None, lock_info=None):
        def set_nice(which, tid, value):
            self.assertEqual((which, tid), (os.PRIO_PROCESS, 21))
            writes.append(value)
            current.update(M.target_nice(current, value))
        with ExitStack() as stack:
            for obj, name, value in [
                (M, 'PROC', root), (M, 'LOCK', root/'lock'),
                (M, 'validate_device', validator or (lambda *_: None)),
                (M, 'snapshot', reader or (lambda *_: deepcopy(current))),
                (M, 'exited_reason', gone or (lambda *_: None)),
                (M.os, 'SCHED_OTHER', 0), (M.os, 'setpriority', setter or set_nice),
                (M.os, 'fstat', lambda _: lock_info or SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1)),
                (M.os, 'sched_setscheduler', lambda *_: self.fail('No policy writes')),
                (M.os, 'sched_setaffinity', lambda *_: self.fail('No affinity writes'))]:
                stack.enter_context(patch.object(obj, name, value, create=True))
            yield

    def test_exact_reader_only_change_and_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, writes = state(), []
            with self.environment(Path(tmp), current, writes):
                with M.prioritize_imu('serial', 'boot', 20, 21, SHA) as record:
                    self.assertEqual(record['active'], M.target_nice(record['before'], -20))
                    self.assertEqual(record['active']['tasks'][::2], record['before']['tasks'][::2])
                self.assertEqual(record['after'], record['before'])
                self.assertEqual(record['restoration'], 'restored')
            self.assertEqual(writes, [-20, 0])

    def test_failed_set_before_or_after_apply_restores_and_preserves_error(self):
        for applied in (False, True):
            with self.subTest(applied=applied), tempfile.TemporaryDirectory() as tmp:
                current, writes = state(), []
                failure = PermissionError('set failed')
                def setter(_, tid, value):
                    self.assertEqual(tid, 21)
                    writes.append(value)
                    if value == -20:
                        if applied:
                            current.update(M.target_nice(current, value))
                        raise failure
                    current.update(M.target_nice(current, value))
                with self.environment(Path(tmp), current, writes, setter=setter):
                    with self.assertRaises(PermissionError) as caught:
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            self.fail('Failed apply yielded')
                self.assertIs(caught.exception, failure)
                self.assertEqual(writes, [-20, 0] if applied else [-20])
                self.assertEqual(current['nice'], 0)

    def test_transient_readback_error_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, writes, calls = state(), [], []
            def reader(*_):
                calls.append(1)
                if len(calls) == 2:
                    raise OSError('readback failed')
                return deepcopy(current)
            with self.environment(Path(tmp), current, writes, reader=reader):
                with self.assertRaisesRegex(OSError, 'readback failed'):
                    with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                        self.fail('Failed readback yielded')
            self.assertEqual(writes, [-20, 0])

    def test_body_failure_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, writes = state(), []
            with self.environment(Path(tmp), current, writes):
                with self.assertRaisesRegex(RuntimeError, 'body failed'):
                    with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                        raise RuntimeError('body failed')
            self.assertEqual(writes, [-20, 0])

    def test_restoration_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, writes = state(), []
            def setter(_, tid, value):
                self.assertEqual(tid, 21)
                writes.append(value)
                if value == 0:
                    raise PermissionError('restore failed')
                current.update(M.target_nice(current, value))
            with self.environment(Path(tmp), current, writes, setter=setter):
                with self.assertRaisesRegex(PermissionError, 'restore failed'):
                    with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                        pass
            self.assertEqual(writes, [-20, 0])

    def test_initial_scheduler_baseline_required(self):
        for key, value in [('nice', -20), ('policy', 2), ('rt_priority', 1), ('affinity', [])]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                current, writes = state() | {key: value}, []
                with self.environment(Path(tmp), current, writes):
                    with self.assertRaises(ValueError):
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            self.fail('Bad baseline yielded')
                self.assertEqual(writes, [])

    def test_identity_and_other_task_drift_refuses_overwrite(self):
        mutations = [lambda s: s.update(process_start=200), lambda s: s.update(thread_start=201),
                     lambda s: s.update(limits='changed'), lambda s: s.update(executable={'sha256': 'b'*64}),
                     lambda s: s.update(policy=2), lambda s: s.update(affinity=[1]),
                     lambda s: s.update(nice=-10), lambda s: s['tasks'][0].update(nice=-1),
                     lambda s: s['tasks'][2].update(policy=2), lambda s: s['tasks'].pop()]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                current, writes = state(), []
                with self.environment(Path(tmp), current, writes):
                    with self.assertRaisesRegex(RuntimeError, 'restoration refused'):
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            mutate(current)
                self.assertEqual(writes, [-20])

    def test_changed_boot_and_persistent_read_failure_no_write(self):
        for failure_kind in ('boot', 'read'):
            with self.subTest(kind=failure_kind), tempfile.TemporaryDirectory() as tmp:
                current, writes, failed = state(), [], [False]
                def validate(*_):
                    if failed[0] and failure_kind == 'boot':
                        raise ValueError('boot changed')
                def reader(*_):
                    if failed[0] and failure_kind == 'read':
                        raise OSError('inspection failed')
                    return deepcopy(current)
                with self.environment(Path(tmp), current, writes, validator=validate, reader=reader):
                    with self.assertRaises((ValueError, OSError)):
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            failed[0] = True
                self.assertEqual(writes, [-20])

    def test_gone_reader_with_live_parent_and_zombie_process_skip_write(self):
        real_exit = M.exited_reason
        for zombie in (False, True):
            with self.subTest(zombie=zombie), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_stat(root/'20', 20, 'producer-live', 100)
                write_stat(root/'20/task/21', 21, 'ssc-imu', 101)
                current, writes = state(), []
                with self.environment(root, current, writes, gone=real_exit):
                    with M.prioritize_imu('serial', 'boot', 20, 21, SHA) as record:
                        if zombie:
                            write_stat(root/'20', 20, 'producer-live', 100, 'Z')
                        else:
                            (root/'20/task/21/stat').unlink()
                            (root/'20/task/21').rmdir()
                    self.assertEqual(record['restoration'], 'owned-producer-not-live' if zombie else 'owned-imu-thread-exited')
                self.assertEqual(writes, [-20])

    def test_reused_identity_or_missing_stat_not_treated_as_exit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(M, 'PROC', Path(tmp)):
            root = Path(tmp)
            write_stat(root/'20', 20, 'producer-live', 100)
            write_stat(root/'20/task/21', 21, 'ssc-imu', 201)
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                M.exited_reason(state())
            (root/'20/task/21/stat').unlink()
            with self.assertRaisesRegex(RuntimeError, 'directory exists'):
                M.exited_reason(state())

    def test_private_lock_overlap_and_symlink_refusal(self):
        for key, value in [('st_uid', 1), ('st_nlink', 2), ('st_mode', 0o100644), ('st_mode', stat.S_IFIFO | 0o600)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                current, writes = state(), []
                info = SimpleNamespace(**({'st_mode': 0o100600, 'st_uid': 0, 'st_nlink': 1} | {key: value}))
                with self.environment(Path(tmp), current, writes, lock_info=info):
                    with self.assertRaises(ValueError):
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            self.fail('Bad lock yielded')
                self.assertEqual(writes, [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); current, writes = state(), []
            with self.environment(root, current, writes):
                with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                    with self.assertRaises(BlockingIOError):
                        with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                            self.fail('Overlapping lease yielded')
            (root/'lock').unlink()
            (root/'lock').symlink_to(root/'elsewhere')
            with self.environment(root, current, writes), self.assertRaises(OSError):
                with M.prioritize_imu('serial', 'boot', 20, 21, SHA):
                    self.fail('Symlink lock yielded')

    def test_bad_explicit_inputs_rejected_before_device_check(self):
        with patch.object(M, 'validate_device') as device:
            for pid, tid, sha in [(True, 21, SHA), (0, 21, SHA), (20, -1, SHA), (20, 20, SHA), (20, 21, 'A'*64), (20, '21', SHA)]:
                with self.subTest(pid=pid, tid=tid, sha=sha), self.assertRaises(ValueError):
                    with M.prioritize_imu('serial', 'boot', pid, tid, sha):
                        self.fail('Bad input yielded')
            device.assert_not_called()

    @contextmanager
    def proc_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); exe = root/'producer-live'; exe.write_bytes(b'fixture executable'); exe.chmod(0o700)
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            for path, tid, comm, start in [(root/'20', 20, 'producer-live', 100),
                    (root/'20/task/20', 20, 'producer-live', 100), (root/'20/task/21', 21, 'ssc-imu', 101),
                    (root/'20/task/22', 22, 'gmain', 102)]:
                write_stat(path, tid, comm, start)
                (path/'comm').write_text(comm+'\n'); (path/'status').write_text('Uid:\t0\t0\t0\t0\n')
                (path/'cgroup').write_text(M.GROUP+'\n'); (path/'limits').write_text('limits\n')
            (root/'20/exe').symlink_to(exe)
            (root/'20/cmdline').write_bytes(b'\0'.join(os.fsencode(x) for x in (exe, M.VIO, '300'))+b'\0')
            fstat = os.fstat
            def root_stat(fd):
                original = fstat(fd)
                names = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                return SimpleNamespace(**({name: getattr(original, name) for name in names} | {'st_uid': 0}))
            for obj, name, value in [(M, 'PROC', root), (M, 'EXE', exe), (M.os, 'fstat', root_stat),
                    (M.os, 'sched_getscheduler', lambda _: 0), (M.os, 'sched_getparam', lambda _: SimpleNamespace(sched_priority=0)),
                    (M.os, 'getpriority', lambda *_: 0), (M.os, 'sched_getaffinity', lambda _: {0, 1})]:
                stack.enter_context(patch.object(obj, name, value, create=True))
            yield root, digest

    def test_actual_proc_identity_snapshot(self):
        with self.proc_fixture() as (root, digest):
            result = M.snapshot(20, 21, digest)
            self.assertEqual(result['thread_start'], 101)
            self.assertEqual([x['tid'] for x in result['tasks']], [20, 21, 22])
            self.assertEqual(result['executable']['sha256'], digest)

    def test_proc_identity_command_owner_hash_unique_reader_guards(self):
        cases = ['uid', 'cgroup', 'command', 'hash', 'writable', 'duplicate', 'wrong-target', 'zombie', 'task-limit', 'limits']
        for case in cases:
            with self.subTest(case=case), self.proc_fixture() as (root, digest):
                tid = 21
                if case == 'uid': (root/'20/task/21/status').write_text('Uid:\t1000\t1000\t1000\t1000\n')
                if case == 'cgroup': (root/'20/cgroup').write_text('0::/other\n')
                if case == 'command': (root/'20/cmdline').write_bytes(b'other\0')
                if case == 'hash': digest = '0'*64
                if case == 'writable': (root/'producer-live').chmod(0o722)
                if case == 'duplicate':
                    write_stat(root/'20/task/22', 22, 'ssc-imu', 102)
                    (root/'20/task/22/comm').write_text('ssc-imu\n')
                if case == 'wrong-target': tid = 22
                if case == 'zombie': write_stat(root/'20', 20, 'producer-live', 100, 'Z')
                if case == 'task-limit':
                    for number in range(100, 165): (root/f'20/task/{number}').mkdir()
                if case == 'limits': (root/'20/task/22/limits').write_text('different\n')
                with self.assertRaises(ValueError): M.snapshot(20, tid, digest)

    def test_cli_bounds_and_signal_cleanup(self):
        args = ['helper', '--boot-serial', 'serial', '--boot-id', 'boot', '--pid', '20', '--tid', '21', '--binary-sha256', SHA, '--seconds']
        for duration in ('0', '901'):
            with patch('sys.argv', args+[duration]), patch.object(M, 'prioritize_imu') as lease, patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit): M.main()
                lease.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            current, writes, handlers = state(), [], {}
            def signal_handler(sig, handler):
                old = handlers.get(sig, signal.SIG_DFL); handlers[sig] = handler; return old
            with self.environment(Path(tmp), current, writes), patch('sys.argv', args+['900']), \
                    patch.object(M.signal, 'signal', signal_handler), patch.object(M.time, 'sleep', lambda _: handlers[signal.SIGTERM](None, None)), \
                    patch('sys.stdout', io.StringIO()):
                M.main()
            self.assertEqual(writes, [-20, 0])
            self.assertEqual(handlers, {signal.SIGTERM: signal.SIG_DFL, signal.SIGINT: signal.SIG_DFL})


if __name__ == '__main__':
    unittest.main()
