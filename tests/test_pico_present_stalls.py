import gzip
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('present_stalls',
    Path(__file__).resolve().parents[1] / 'tools/analyze-pico-present-stalls.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PresentStallTests(unittest.TestCase):
    def analyze(self, text, **metadata):
        raw = text.encode()
        meta = {'tail_only': False, 'source_bytes': len(raw),
                'source_sha256': hashlib.sha256(raw).hexdigest()} | metadata
        faults = {'misses': [{'present': 8, 'source': 'phase.json',
                              'prior_vblank_trace_ns': 200961471000,
                              'prior_wait_end_ns': 200968979193,
                              'command': {'submitter_pid': 2015, 'queued_ns': 200970952000}}]}
        maps = '7f8157a000-7f8177a000 rw-s 00000000 00:13 1 /dev/shm/ValveIPC\n'
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'trace.gz'
            trace.write_bytes(gzip.compress(raw))
            return MODULE.analyze(trace, meta, faults, maps)

    def sample(self, operation='0', result='0'):
        return ('RenderThread-2015 [004] .... 200.960049: sys_enter: NR 98 '
                f'(7f815830a8, {operation}, 8000094c, 7f7c5bf3f0, 0, 0)\n'
                'CVRAPIITask::Ru-2380 [000] d..2 200.968645: sched_wakeup: '
                'comm=RenderThread pid=2015 prio=97 target_cpu=006\n'
                f'RenderThread-2015 [006] .... 200.968654: sys_exit: NR 98 = {result}\n')

    def test_wait_before_present_return_is_retained_with_clipped_overlap(self):
        report = self.analyze(self.sample())
        call, = report['presents'][0]['waits']
        self.assertEqual(call['duration_ns'], 8605000)
        self.assertEqual(call['overlap_ns'], 7183000)
        self.assertTrue(call['ended_before_present_wait_return'])
        self.assertEqual(call['mapping'], '/dev/shm/ValveIPC')
        self.assertEqual(call['wakeups'][0]['waker_tid'], 2380)
        self.assertNotIn('owner_tid', call)

    def test_wake_operations_are_not_blocking_waits(self):
        self.assertEqual(self.analyze(self.sample(operation='81'))['presents'][0]['waits'], [])
        call, = self.analyze(self.sample(operation='89', result='-110'))['presents'][0]['waits']
        self.assertEqual(call['result'], -110)

    def test_incomplete_or_mismatched_source_is_refused(self):
        for changes in ({'tail_only': True}, {'source_bytes': 0}, {'source_sha256': '0'*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.analyze(self.sample(), **changes)
        with self.assertRaisesRegex(ValueError, 'Unfinished futex'):
            self.analyze(self.sample().rsplit('\n', 2)[0]+'\n')
        with self.assertRaisesRegex(ValueError, 'Missing syscall exit'):
            self.analyze(self.sample().splitlines()[0]+'\n'+self.sample())


if __name__ == '__main__':
    unittest.main()
