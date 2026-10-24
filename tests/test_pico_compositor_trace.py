import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'tools/pico-compositor-trace.py'
SPEC = importlib.util.spec_from_file_location('compositor_trace', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PicoCompositorTraceTests(unittest.TestCase):
    def files(self, root):
        for name, content in [('tracing_on', '0'), ('set_event_pid', 'no pid\n'),
                              ('options/event-fork', '0'), ('trace_marker', ''),
                              ('trace', 'old capture'), ('trace_clock', '[local] mono global')]:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        for event in MODULE.EVENTS:
            p = root / 'events' / event / 'enable'
            p.parent.mkdir(parents=True)
            p.write_text('0')
        for event in MODULE.EVENTS:
            (root / 'events' / event / 'filter').write_text('none\n')

    def test_pid_inheritance_and_pre_exec_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            MODULE.arm(root, 1234)
            self.assertEqual((root / 'set_event_pid').read_text(), '1234')
            self.assertEqual((root / 'options/event-fork').read_text(), '1')
            self.assertEqual((root / 'tracing_on').read_text(), '1')
            self.assertIn('PRE_EXEC pid=1234', (root / 'trace_marker').read_text())
            self.assertEqual((root / 'trace_clock').read_text(), 'mono')
            self.assertEqual((root / 'trace').read_text(), '')
            self.assertEqual(MODULE.EVENTS, ('sched/sched_switch', 'sched/sched_wakeup',
                                            'raw_syscalls/sys_enter', 'raw_syscalls/sys_exit'))
            for event in MODULE.EVENTS:
                self.assertEqual((root / 'events' / event / 'enable').read_text(), '1')

    def test_existing_selection_or_missing_inheritance_refuses_launch(self):
        for fault in ('selected', 'no_inheritance', 'running', 'event_enabled', 'filtered'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.files(root)
                if fault == 'selected':
                    (root / 'set_event_pid').write_text('99')
                elif fault == 'no_inheritance':
                    (root / 'options/event-fork').unlink()
                elif fault == 'running':
                    (root / 'tracing_on').write_text('1')
                elif fault == 'event_enabled':
                    (root / 'events' / MODULE.EVENTS[0] / 'enable').write_text('1')
                else:
                    (root / 'events' / MODULE.EVENTS[2] / 'filter').write_text('id == 172')
                with self.assertRaises(ValueError):
                    MODULE.arm(root, 1234)
                self.assertEqual((root / 'trace_marker').read_text(), '')

    def test_syscall_selection_filters_both_directions_without_filtering_scheduling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            MODULE.arm(root, 1234, [98, 29, 29])
            self.assertEqual((root / 'tracing_on').read_text(), '1')
            for event in MODULE.EVENTS:
                self.assertEqual((root / 'events' / event / 'enable').read_text(), '1')
            for event in MODULE.EVENTS[2:]:
                self.assertEqual((root / 'events' / event / 'filter').read_text(), 'id == 29 || id == 98')
            for event in MODULE.EVENTS[:2]:
                self.assertEqual((root / 'events' / event / 'filter').read_text(), 'none\n')

    def test_existing_scheduler_filters_refuse_launch_without_mutating_selection(self):
        for event in MODULE.EVENTS[:2]:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.files(root)
                expression = 'prev_pid == 99' if event.endswith('sched_switch') else 'pid == 99'
                (root / 'events' / event / 'filter').write_text(expression)
                with self.assertRaisesRegex(ValueError, 'Trace event already filtered'):
                    MODULE.arm(root, 1234, [29])
                self.assertEqual((root / 'events' / event / 'filter').read_text(), expression)
                self.assertEqual((root / 'set_event_pid').read_text(), 'no pid\n')
                self.assertEqual((root / 'tracing_on').read_text(), '0')
                self.assertEqual((root / 'trace_marker').read_text(), '')

    def test_invalid_syscall_ids_leave_instance_idle(self):
        for numbers in ([-1], [2147483648], [True], ['29']):
            with self.subTest(numbers=numbers), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.files(root)
                with self.assertRaises(ValueError):
                    MODULE.arm(root, 1234, numbers)
                self.assertEqual((root / 'tracing_on').read_text(), '0')
                self.assertEqual((root / 'set_event_pid').read_text(), 'no pid\n')

    def test_kernel_filter_readback_mismatch_never_enables_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            read_text = Path.read_text

            def mismatched(path, *args, **kwargs):
                value = read_text(path, *args, **kwargs)
                return 'id == 172' if path.name == 'filter' and value == 'id == 29' else value

            with patch.object(Path, 'read_text', mismatched):
                with self.assertRaisesRegex(ValueError, 'did not accept the syscall filter'):
                    MODULE.arm(root, 1234, [29])
            self.assertEqual((root / 'tracing_on').read_text(), '0')
            self.assertEqual((root / 'trace_marker').read_text(), '')
            for event in MODULE.EVENTS:
                self.assertEqual((root / 'events' / event / 'enable').read_text(), '0')
            self.assertEqual((root / 'set_event_pid').read_text(), 'no pid\n')
            self.assertEqual((root / 'options/event-fork').read_text(), '0')
            for event in MODULE.EVENTS[2:]:
                self.assertIn((root / 'events' / event / 'filter').read_text().strip(), ('0', 'none'))

    def test_failed_filter_write_allows_clean_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            write_text = Path.write_text
            failed = []

            def interrupted(path, value, *args, **kwargs):
                if path == root / 'events' / MODULE.EVENTS[3] / 'filter' and value == 'id == 29' and not failed:
                    failed.append(True)
                    raise OSError('fixture filter write failure')
                return write_text(path, value, *args, **kwargs)

            with patch.object(Path, 'write_text', interrupted):
                with self.assertRaisesRegex(OSError, 'fixture filter write failure'):
                    MODULE.arm(root, 1234, [29])
            self.assertEqual((root / 'set_event_pid').read_text(), 'no pid\n')
            self.assertEqual((root / 'options/event-fork').read_text(), '0')
            self.assertEqual((root / 'trace').read_text(), 'old capture')
            MODULE.arm(root, 1234, [29])
            self.assertEqual((root / 'tracing_on').read_text(), '1')

    def test_failed_marker_restores_claim_and_event_enables(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            write_text = Path.write_text

            def interrupted(path, value, *args, **kwargs):
                if path == root / 'trace_marker':
                    raise OSError('fixture marker write failure')
                return write_text(path, value, *args, **kwargs)

            with patch.object(Path, 'write_text', interrupted):
                with self.assertRaisesRegex(OSError, 'fixture marker write failure'):
                    MODULE.arm(root, 1234, [29])
            self.assertEqual((root / 'set_event_pid').read_text(), '')
            self.assertEqual((root / 'options/event-fork').read_text(), '0')
            self.assertEqual((root / 'trace_clock').read_text(), 'local')
            self.assertEqual((root / 'tracing_on').read_text(), '0')
            for event in MODULE.EVENTS:
                self.assertEqual((root / 'events' / event / 'enable').read_text(), '0')
