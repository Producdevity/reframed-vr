import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'tools/pico-compositor-trace.py'
SPEC = importlib.util.spec_from_file_location('compositor_trace', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PicoCompositorTraceTests(unittest.TestCase):
    def files(self, root):
        for name, content in [('tracing_on', '0'), ('set_event_pid', 'no pid\n'),
                              ('options/event-fork', '0'), ('trace_marker', ''),
                              ('trace_clock', '[local] mono global')]:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        for event in MODULE.EVENTS:
            p = root / 'events' / event / 'enable'
            p.parent.mkdir(parents=True)
            p.write_text('0')

    def test_pid_inheritance_and_pre_exec_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.files(root)
            MODULE.arm(root, 1234)
            self.assertEqual((root / 'set_event_pid').read_text(), '1234')
            self.assertEqual((root / 'options/event-fork').read_text(), '1')
            self.assertEqual((root / 'tracing_on').read_text(), '1')
            self.assertIn('PRE_EXEC pid=1234', (root / 'trace_marker').read_text())
            for event in MODULE.EVENTS:
                self.assertEqual((root / 'events' / event / 'enable').read_text(), '1')

    def test_existing_selection_or_missing_inheritance_refuses_launch(self):
        for fault in ('selected', 'no_inheritance', 'running', 'event_enabled'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.files(root)
                if fault == 'selected':
                    (root / 'set_event_pid').write_text('99')
                elif fault == 'no_inheritance':
                    (root / 'options/event-fork').unlink()
                elif fault == 'running':
                    (root / 'tracing_on').write_text('1')
                else:
                    (root / 'events' / MODULE.EVENTS[0] / 'enable').write_text('1')
                with self.assertRaises(ValueError):
                    MODULE.arm(root, 1234)
                self.assertEqual((root / 'trace_marker').read_text(), '')
