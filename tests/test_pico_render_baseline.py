import copy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('render_baseline',
    Path(__file__).resolve().parents[1]/'tools/pico-steamvr-render-priority.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class BaselineTests(unittest.TestCase):
    def state(self, policy=0, priority=0):
        return dict(pid=20, tid=21, executable='/opt/vrcompositor', process_start=100,
                    thread_start=110, policy=policy, rt_priority=priority,
                    nice=-20, affinity=[4, 5, 6], limits=copy.deepcopy(M.LIMITS))

    def run_states(self, states, expected=None):
        record = {}
        clock = [0]
        index = [0]

        def read(*_):
            row = states[min(index[0], len(states)-1)]
            index[0] += 1
            return copy.deepcopy(row)

        def sleep(seconds):
            clock[0] += int(seconds*1000000000)

        with patch.object(M, 'snapshot', side_effect=read), \
                patch.object(M.time, 'monotonic_ns', side_effect=lambda: clock[0]), \
                patch.object(M.time, 'sleep', side_effect=sleep), \
                patch.object(M.os, 'SCHED_OTHER', 0, create=True), \
                patch.object(M.os, 'SCHED_FIFO', 1, create=True), \
                patch.object(M.os, 'sched_setscheduler', create=True) as setter:
            if expected:
                with self.assertRaises(expected):
                    M.wait_cfs_baseline(20, 21, record)
                self.assertFalse(record['accepted'])
                self.assertIn('error', record)
            else:
                result = M.wait_cfs_baseline(20, 21, record)
                self.assertEqual((result['policy'], result['rt_priority']), (0, 0))
                self.assertTrue(record['accepted'])
            setter.assert_not_called()
        return record

    def test_requires_two_target_samples(self):
        r = self.run_states([self.state()])
        self.assertEqual(len(r['samples']), 2)

    def test_fifo_promotion_and_nonatomic_readbacks_are_not_accepted(self):
        r = self.run_states([self.state(1, 40), self.state(0, 40), self.state(1, 0), self.state()])
        self.assertEqual(len(r['samples']), 5)

    def test_intervening_promotion_resets_readiness(self):
        r = self.run_states([self.state(), self.state(1, 40), self.state()])
        self.assertEqual(len(r['samples']), 4)

    def test_unexpected_scheduler_is_terminal(self):
        for p, q in [(2, 2), (0, 1), (1, 99)]:
            with self.subTest(policy=p, priority=q):
                self.run_states([self.state(p, q)], ValueError)

    def test_changed_identity_or_attributes_is_terminal(self):
        for key, value in [('thread_start', 111), ('process_start', 101),
                           ('affinity', [7]), ('nice', 0), ('limits', {})]:
            with self.subTest(key=key):
                self.run_states([self.state(1, 40), self.state() | {key: value}], ValueError)

    def test_persistent_fifo_times_out_and_keeps_all_samples(self):
        r = self.run_states([self.state(1, 40)], TimeoutError)
        self.assertEqual(len(r['samples']), 101)
        self.assertGreater(r['ended_ns']-r['started_ns'], 500000000)

    def test_read_finishing_after_deadline_cannot_accept(self):
        record = {}
        with patch.object(M, 'snapshot', return_value=self.state()), \
                patch.object(M.time, 'monotonic_ns', side_effect=[0, 0, 500000001, 500000001]), \
                patch.object(M.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                M.wait_cfs_baseline(20, 21, record)
            self.assertFalse(record['accepted'])
            self.assertEqual(len(record['samples']), 1)
            sleep.assert_not_called()

    def test_invalid_initial_attributes_are_rejected(self):
        for key, value in [('nice', 0), ('affinity', []), ('limits', {})]:
            with self.subTest(key=key):
                self.run_states([self.state() | {key: value}], ValueError)


if __name__ == '__main__':
    unittest.main()
