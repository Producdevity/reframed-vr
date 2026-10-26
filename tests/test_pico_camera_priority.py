from contextlib import ExitStack, contextmanager
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('camera_priority',
    Path(__file__).resolve().parents[1]/'tools/pico-camera-priority.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = 'a'*64


class CameraPriorityTests(unittest.TestCase):
    def state(self):
        return {'pid': 20, 'tid': 20, 'process_start': 100, 'thread_start': 100,
                'executable': {'path': str(MODULE.EXE), 'sha256': SHA, 'st_ino': 123},
                'policy': 0, 'rt_priority': 0, 'affinity': [0, 1], 'nice': 0,
                'limits': 'Max realtime priority     0     0\n'}

    @contextmanager
    def environment(self, root, state, writes, *, reader=None, setter=None, validator=None, lock_info=None):
        def set_nice(which, pid, value):
            self.assertEqual((which, pid), (os.PRIO_PROCESS, 20))
            writes.append(value)
            state['nice'] = value
        with ExitStack() as stack:
            for obj, name, value in [
                (MODULE, 'PROC', root), (MODULE, 'LOCK', root/'lock'),
                (MODULE, 'validate_device', validator or (lambda *_: None)),
                (MODULE, 'snapshot', reader or (lambda *_: dict(state))),
                (MODULE.os, 'SCHED_OTHER', 0), (MODULE.os, 'setpriority', setter or set_nice),
                (MODULE.os, 'fstat', lambda _fd: lock_info or SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1)),
                (MODULE.os, 'sched_setscheduler', lambda *_: self.fail('Policy must never be written')),
                (MODULE.os, 'sched_setaffinity', lambda *_: self.fail('Affinity must never be written'))]:
                stack.enter_context(patch.object(obj, name, value, create=True))
            yield

    def test_exact_priority_and_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, writes = self.state(), []
            with self.environment(Path(tmp), state, writes):
                with MODULE.prioritize_capture('fixture', 'boot', 20, SHA) as record:
                    self.assertEqual(record['active'], record['before'] | {'nice': -20})
                self.assertEqual(record['after'], record['before'])
                self.assertEqual(record['restoration'], 'restored')
            self.assertEqual(writes, [-20, 0])

    def test_permission_failure_before_and_after_apply_preserves_original_error(self):
        for applied in [False, True]:
            with self.subTest(applied=applied), tempfile.TemporaryDirectory() as tmp:
                state, writes = self.state(), []
                failure = PermissionError('injected setpriority failure')
                def setter(_which, _pid, value):
                    writes.append(value)
                    if value == -20:
                        if applied:
                            state['nice'] = value
                        raise failure
                    state['nice'] = value
                with self.environment(Path(tmp), state, writes, setter=setter):
                    with self.assertRaises(PermissionError) as caught:
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                            self.fail('Failed activation yielded')
                self.assertIs(caught.exception, failure)
                self.assertEqual(writes, [-20, 0] if applied else [-20])
                self.assertEqual(state['nice'], 0)

    def test_body_exception_is_preserved_after_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, writes = self.state(), []
            failure = RuntimeError('body failed')
            with self.environment(Path(tmp), state, writes):
                with self.assertRaises(RuntimeError) as caught:
                    with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                        raise failure
            self.assertIs(caught.exception, failure)
            self.assertEqual(writes, [-20, 0])

    def test_restoration_failure_is_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, writes = self.state(), []
            def setter(_which, _pid, value):
                writes.append(value)
                if value == 0:
                    raise PermissionError('restoration failed')
                state['nice'] = value
            with self.environment(Path(tmp), state, writes, setter=setter):
                with self.assertRaisesRegex(PermissionError, 'restoration failed'):
                    with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                        raise RuntimeError('body failed')
            self.assertEqual(writes, [-20, 0])

    def test_refuses_initial_policy_nice_or_empty_affinity_without_write(self):
        for key, value in [('nice', -5), ('policy', 2), ('rt_priority', 1), ('affinity', [])]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                state, writes = self.state() | {key: value}, []
                with self.environment(Path(tmp), state, writes):
                    with self.assertRaises(ValueError):
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                            self.fail('Invalid target yielded')
                self.assertEqual(writes, [])

    def test_state_drift_refuses_overwrite(self):
        changes = [('process_start', 101), ('thread_start', 101), ('policy', 2),
                   ('affinity', [1]), ('limits', 'changed'), ('nice', -10), ('nice', 0),
                   ('executable', {'path': 'replaced', 'sha256': 'b'*64, 'st_ino': 456})]
        for key, value in changes:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as tmp:
                state, writes = self.state(), []
                with self.environment(Path(tmp), state, writes):
                    with self.assertRaisesRegex(RuntimeError, 'restoration refused'):
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                            state[key] = value
                self.assertEqual(writes, [-20])

    def test_unexpected_activation_nice_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, writes = self.state(), []
            def setter(_which, _pid, value):
                writes.append(value); state['nice'] = -10
            with self.environment(Path(tmp), state, writes, setter=setter):
                with self.assertRaisesRegex(RuntimeError, 'restoration refused'):
                    with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                        self.fail('Bad readback yielded')
            self.assertEqual(writes, [-20])

    def test_boot_drift_prevents_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, writes, changed = self.state(), [], [False]
            def validate(*_):
                if changed[0]:
                    raise ValueError('boot changed')
            with self.environment(Path(tmp), state, writes, validator=validate):
                with self.assertRaisesRegex(ValueError, 'boot changed'):
                    with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                        changed[0] = True
            self.assertEqual(writes, [-20])

    def test_exited_process_no_write_and_inspection_failure_not_exit(self):
        for process_exists in [False, True]:
            with self.subTest(process_exists=process_exists), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if process_exists:
                    (root/'20').mkdir()
                state, writes, gone = self.state(), [], [False]
                def reader(*_):
                    if gone[0]:
                        raise FileNotFoundError('process unavailable')
                    return dict(state)
                with self.environment(root, state, writes, reader=reader):
                    if process_exists:
                        with self.assertRaisesRegex(RuntimeError, 'process still exists'):
                            with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                                gone[0] = True
                    else:
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA) as record:
                            gone[0] = True
                        self.assertEqual(record['restoration'], 'owned-capture-exited')
                self.assertEqual(writes, [-20])

    def test_private_lock_and_no_overlap(self):
        for key, value in [('st_uid', 1), ('st_nlink', 2), ('st_mode', 0o100644), ('st_mode', 0o100400), ('st_mode', stat.S_IFIFO | 0o600)]:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as tmp:
                state, writes = self.state(), []
                info = SimpleNamespace(**({'st_mode': 0o100600, 'st_uid': 0, 'st_nlink': 1} | {key: value}))
                with self.environment(Path(tmp), state, writes, lock_info=info):
                    with self.assertRaisesRegex(ValueError, 'private 0600'):
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                            self.fail('Bad lock yielded')
                self.assertEqual(writes, [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state, writes = self.state(), []
            with self.environment(root, state, writes):
                with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                    with self.assertRaises(BlockingIOError):
                        with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                            self.fail('Overlapping context yielded')
            self.assertEqual(writes, [-20, 0])
            (root/'lock').unlink(); (root/'target').touch(); (root/'lock').symlink_to(root/'target')
            with self.environment(root, state, writes), self.assertRaises(OSError):
                with MODULE.prioritize_capture('fixture', 'boot', 20, SHA):
                    self.fail('Symlink lock yielded')

    def test_invalid_target_rejected_before_device_or_lock_access(self):
        for pid, checksum in [(True, SHA), (0, SHA), (-1, SHA), ('20', SHA), (20, 'A'*64), (20, 'a'*63), (20, None)]:
            with self.subTest(pid=pid, checksum=checksum), patch.object(MODULE, 'validate_device', side_effect=AssertionError('must not inspect device')):
                with self.assertRaises(ValueError):
                    with MODULE.prioritize_capture('fixture', 'boot', pid, checksum):
                        self.fail('Invalid target yielded')

    @contextmanager
    def proc_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp); proc = root/'20'; task = proc/'task/20'; task.mkdir(parents=True)
            binary = root/'capture-steamvr'; binary.write_bytes(b'fixture ELF contents'); binary.chmod(0o755)
            (proc/'exe').symlink_to(binary)
            raw = '20 (capture-steamvr) '+' '.join(['S']+['0']*18+['100'])
            for path in [proc, task]:
                (path/'stat').write_text(raw); (path/'comm').write_text('capture-steamvr\n')
                (path/'status').write_text('Uid:\t0\t0\t0\t0\n'); (path/'cgroup').write_text(MODULE.GROUP+'\n')
                (path/'limits').write_text('Max realtime priority     0     0\n')
            (proc/'cmdline').write_bytes(os.fsencode(binary)+b'\0--capture\0')
            actual_fstat = os.fstat
            def root_owned(fd):
                info = actual_fstat(fd)
                names = ['st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns']
                return SimpleNamespace(**({name: getattr(info, name) for name in names} | {'st_uid': 0}))
            for obj, name, value in [(MODULE, 'PROC', root), (MODULE, 'EXE', binary),
                (MODULE.os, 'fstat', root_owned), (MODULE.os, 'sched_getscheduler', lambda _: 0),
                (MODULE.os, 'sched_getparam', lambda _: SimpleNamespace(sched_priority=0)),
                (MODULE.os, 'sched_getaffinity', lambda _: {0, 1}), (MODULE.os, 'getpriority', lambda *_: 0)]:
                stack.enter_context(patch.object(obj, name, value, create=True))
            yield root, proc, task, binary, hashlib.sha256(binary.read_bytes()).hexdigest()

    def test_real_proc_snapshot_and_identity_rejections(self):
        with self.proc_fixture() as (root, proc, task, binary, checksum):
            state = MODULE.snapshot(20, checksum)
            self.assertEqual((state['process_start'], state['thread_start'], state['nice']), (100, 100, 0))
            self.assertEqual(state['executable']['sha256'], checksum)
            edits = [(proc/'status', b'Uid: 0 1 0 0\n'), (task/'status', b'Uid: 0 0 1 0\n'),
                     (proc/'comm', b'other'), (task/'comm', b'other'),
                     (proc/'cgroup', b'0::/wrong.service\n'), (task/'cgroup', b'0::/wrong.service\n'),
                     (proc/'cmdline', os.fsencode(binary)+b'\0--other\0'),
                     (task/'limits', b'changed'), (task/'stat', b'20 (wrong) S')]
            for path, bad in edits:
                with self.subTest(path=path):
                    original = path.read_bytes(); path.write_bytes(bad)
                    with self.assertRaises(ValueError):
                        MODULE.snapshot(20, checksum)
                    path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'executable bytes'):
                MODULE.snapshot(20, 'b'*64)
            binary.chmod(0o775)
            with self.assertRaisesRegex(ValueError, 'not group/world writable'):
                MODULE.snapshot(20, checksum)
            binary.chmod(0o755)
            (proc/'task/21').mkdir()
            with self.assertRaisesRegex(ValueError, 'one capture main thread'):
                MODULE.snapshot(20, checksum)

    def test_hashes_open_proc_executable_not_replaced_path(self):
        with self.proc_fixture() as (root, proc, task, binary, checksum):
            running = root/'running-image'; binary.rename(running); binary.write_bytes(b'replacement image')
            (proc/'exe').unlink(); (proc/'exe').symlink_to(running)
            with patch.object(MODULE.os, 'readlink', return_value=str(binary)):
                state = MODULE.snapshot(20, checksum)
            self.assertEqual(state['executable']['sha256'], checksum)
            self.assertEqual(state['executable']['st_ino'], running.stat().st_ino)


if __name__ == '__main__':
    unittest.main()
