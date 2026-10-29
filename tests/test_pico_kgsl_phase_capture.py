import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('phase_capture', ROOT / 'tools/pico-kgsl-phase-capture.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class PhaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.instance = root / 'instance'
        self.instance.mkdir()
        (self.instance / 'tracing_on').write_text('1')
        event = self.instance / 'events/kgsl/kgsl_event_phases'
        event.mkdir(parents=True)
        (event / 'enable').write_text('1')
        self.owner = p.Phases.__new__(p.Phases)
        self.owner.out = root
        self.owner.instance = self.instance
        self.owner.created = True
        self.owner.capture = None
        self.owner.record = {'errors': [], 'restored': False}
        self.disabled = patch.object(p, 'disabled', return_value={'owned': '0'})
        self.disabled.start()
        self.addCleanup(self.disabled.stop)

    def test_cleanup_disables_and_quiesces_without_removing_shared_tracer(self):
        with patch.object(Path, 'rmdir') as remove:
            self.owner.cleanup()
            remove.assert_not_called()
        self.assertEqual((self.instance / 'tracing_on').read_text(), '0')
        self.assertEqual((self.instance / 'events/kgsl/kgsl_event_phases/enable').read_text(), '0')
        self.assertTrue(self.owner.record['quiesced'])
        self.assertFalse(self.owner.record['restored'])
        self.assertEqual(json.loads((self.owner.out / 'receipt.json').read_text()), self.owner.record)

    def test_own_reader_is_not_sufficient_for_global_removal(self):
        self.owner.cleanup()
        with patch.object(Path, 'rmdir') as remove:
            with self.assertRaisesRegex(AssertionError, 'All trace readers'):
                self.owner.remove(all_readers_joined=False)
            remove.assert_not_called()
        self.assertFalse(self.owner.record['restored'])

    def test_remove_requires_quiescence_and_explicit_global_join(self):
        with patch.object(Path, 'rmdir') as remove:
            with self.assertRaises(AssertionError):
                self.owner.remove(all_readers_joined=True)
            remove.assert_not_called()
        self.owner.cleanup()
        with patch.object(Path, 'rmdir', autospec=True) as remove:
            self.owner.remove(all_readers_joined=True)
            remove.assert_called_once_with(self.instance)
        self.assertFalse(self.owner.created)
        self.assertTrue(self.owner.record['removed'])
        self.assertTrue(self.owner.record['restored'])

    def test_cleanup_joins_own_reader_before_quiescing(self):
        capture = Mock()
        capture.state = {'joined': True}
        capture.finish.return_value = dict(capture.state)
        self.owner.capture = capture
        self.owner.cleanup()
        capture.finish.assert_called_once_with('phase-cleanup')
        self.assertIsNone(self.owner.capture)
        self.assertTrue(self.owner.record['quiesced'])
        self.assertFalse(self.owner.record['restored'])

    def test_unjoined_reader_prevents_removal(self):
        capture = Mock()
        capture.state = {'joined': False}
        capture.finish.return_value = dict(capture.state)
        self.owner.capture = capture
        with self.assertRaises(AssertionError):
            self.owner.cleanup()
        with patch.object(Path, 'rmdir') as remove:
            with self.assertRaises(AssertionError):
                self.owner.remove(all_readers_joined=True)
            remove.assert_not_called()
        self.assertIs(self.owner.capture, capture)
        self.assertTrue(self.owner.record['errors'])
        self.assertFalse(self.owner.record['restored'])

    def test_failed_remove_is_not_reported_as_restored(self):
        self.owner.cleanup()
        with patch.object(Path, 'rmdir', side_effect=OSError(16, 'Device or resource busy')):
            with self.assertRaises(OSError):
                self.owner.remove(all_readers_joined=True)
        self.assertTrue(self.owner.created)
        self.assertFalse(self.owner.record['restored'])


if __name__ == '__main__':
    unittest.main()
