import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    'pico_trace_stream', Path(__file__).resolve().parents[1] / 'tools/pico-trace-stream.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class TraceStreamTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.instance = self.root / 'instance'
        self.instance.mkdir()
        (self.instance / 'tracing_on').write_text('0')
        (self.instance / 'current_tracer').write_text('nop')
        (self.instance / 'trace').write_text('')
        self.enable = self.instance / 'events/sched/sched_switch/enable'
        self.enable.parent.mkdir(parents=True)
        self.enable.write_text('1')
        (self.enable.parent / 'filter').write_text('common_pid == 2')
        stats = self.instance / 'per_cpu/cpu0/stats'
        stats.parent.mkdir(parents=True)
        stats.write_text('entries: 0\noverrun: 0\n')
        os.mkfifo(self.instance / 'trace_pipe')

    def capture(self, budget=1024):
        capture = p.Capture(self.instance, self.root, 'fixture', budget, 'fixture-boot')
        capture.path = self.root / 'trace.txt'
        capture.state['path'] = str(capture.path)
        return capture

    def test_real_nonblocking_reader_drains_and_closes_before_hash_acceptance(self):
        capture = self.capture()
        capture.start()
        data = b'one complete event\nanother complete event\n'
        with (self.instance / 'trace_pipe').open('wb', buffering=0) as writer:
            writer.write(data)
            state = capture.finish('window-end')
        self.assertTrue(state['joined'])
        self.assertTrue(capture.finished)
        self.assertIsNone(state['error'])
        self.assertEqual(state['cleanup_errors'], [])
        self.assertEqual(capture.path.read_bytes(), data)
        self.assertEqual(state['bytes'], len(data))
        self.assertEqual(state['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual((self.instance / 'tracing_on').read_text(), '0')
        self.assertEqual(self.enable.read_text(), '0')
        self.assertEqual(json.loads((self.root / 'fixture-capture.json').read_text()), state)
        self.assertIs(capture.finish('repeat'), state)
        self.assertEqual(state['join_attempts'], 1)

    def test_timed_out_join_is_retried_but_never_requalified(self):
        capture = self.capture()
        thread = Mock()
        thread.is_alive.side_effect = [True, False]
        capture.thread = thread
        first = dict(capture.finish('window-end'))
        self.assertFalse(first['joined'])
        self.assertFalse(capture.finished)
        self.assertTrue(capture.stop.is_set())
        self.assertEqual(first['join_attempts'], 1)
        self.assertIn('reader did not join within 5 seconds', first['cleanup_errors'])
        self.assertEqual(set(first['unjoined_reader']), {'stat', 'wchan', 'syscall', 'stack'})
        second = capture.finish('cleanup-retry')
        self.assertTrue(second['joined'])
        self.assertTrue(capture.finished)
        self.assertEqual(second['join_attempts'], 2)
        self.assertEqual(second['stop_reason'], 'window-end')
        self.assertEqual(second['cleanup_errors'], first['cleanup_errors'])
        self.assertEqual(thread.join.call_count, 2)
        self.assertEqual(json.loads((self.root / 'fixture-capture.json').read_text()), second)

    def test_budget_failure_is_not_an_accepted_short_capture(self):
        capture = self.capture(budget=3)
        capture.start()
        with (self.instance / 'trace_pipe').open('wb', buffering=0) as writer:
            writer.write(b'too many bytes\n')
            deadline = time.monotonic() + 2
            while capture.thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.01)
        state = capture.finish('budget-test')
        self.assertTrue(state['joined'])
        self.assertIn('budget exhausted', state['error'])
        self.assertEqual(state['bytes'], 0)

    def test_disable_failure_still_stops_reader_and_rejects_receipt(self):
        capture = self.capture()
        capture.thread = Mock()
        capture.thread.is_alive.return_value = False
        original = Path.write_text

        def write(path, value, *args, **kwargs):
            if path == self.instance / 'tracing_on':
                raise OSError('fixture failed to disable tracing')
            return original(path, value, *args, **kwargs)

        with patch.object(Path, 'write_text', write):
            state = capture.finish('failure')
        capture.thread.join.assert_called_once_with(timeout=5)
        self.assertTrue(capture.stop.is_set())
        self.assertTrue(state['joined'])
        self.assertTrue(any('tracing_off:' in error for error in state['cleanup_errors']))
        self.assertEqual(self.enable.read_text(), '0')

    def test_existing_output_is_not_overwritten(self):
        capture = self.capture()
        capture.path.write_bytes(b'prior evidence')
        with self.assertRaises(AssertionError):
            capture.start()
        state = capture.finish('start-failed')
        self.assertTrue(state['joined'])
        self.assertIn('FileExistsError', state['error'])
        self.assertEqual(capture.path.read_bytes(), b'prior evidence')

    def test_wrong_tracer_is_rejected_before_reader_start(self):
        capture = self.capture()
        (self.instance / 'current_tracer').write_text('function')
        with self.assertRaises(AssertionError):
            capture.start()
        self.assertIsNone(capture.thread)
        self.assertFalse(capture.path.exists())


if __name__ == '__main__':
    unittest.main()
