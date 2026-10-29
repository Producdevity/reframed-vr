"""Malformed tail, loss, source and generation-closure failure fixtures."""
from pathlib import Path
import copy
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kgsl_phases", ROOT / "tools/pico-kgsl-phases.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)



def line(**changes):
    values = dict(work='00000000556b3de4', ctx=1, ts=6107, result=1,
                  entry_ns=1000001000, fire_enter_ns=1000002000,
                  fire_exit_ns=1000003000, promote_end_ns=1000004000,
                  callback_end_ns=1000005000, restore_end_ns=1000006000,
                  entry_policy=0, entry_prio=100, promoted_policy=1,
                  promoted_prio=59, restored_policy=0, restored_prio=100,
                  promote_ret=0, restore_ret=0)
    values.update(changes)
    body = ' '.join(str(k)+'='+str(v) for k, v in values.items())
    return (' kworker/u18:4-2743 [003] .... 1.000007: kgsl_event_phases: '+body+'\n').encode()


def stats():
    row = {name: 0 for name in p.STAT_FIELDS}
    row.update({'oldest event ts': '0.000000', 'now ts': '1.000000'})
    return {cpu: dict(row) for cpu in range(8)}


def work():
    return dict(work='00000000556b3de4', generation=17,
                start=dict(kind='workqueue_execute_start', tid=2743, ns=1000000000),
                end=dict(kind='workqueue_execute_end', tid=2743, ns=1000008000),
                fires=[dict(tid=2743, ns=1000002500,
                            fields='ctx=1 ts=6107 type=retired age=3 cb=kgsl_sync_fence_event_cb+0x0/0x50')])


class Phases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'phase.txt'

    def parse(self, data=None):
        self.path.write_bytes(line() if data is None else data)
        return p.analyze(self.path)

    def test_cli_reports_structure_without_runtime_acceptance_and_preserves_output(self):
        self.path.write_bytes(line())
        output = Path(self.temp.name) / 'result.json'
        command = [sys.executable, '-B', p.__file__, str(self.path), '--output', str(output)]
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        summary = json.loads(result.stdout)
        self.assertTrue(summary['structurally_valid'])
        self.assertFalse(summary['capture_accepted'])
        self.assertNotIn('rows', summary)
        original = output.read_bytes()
        self.assertEqual(len(json.loads(original)['rows']), 1)
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertEqual(output.read_bytes(), original)

    def qualified(self, parsed=None, **changes):
        parsed = parsed or self.parse()
        before, after = stats(), stats()
        for cpu, count in parsed['per_cpu_rows'].items():
            after[cpu]['read events'] = count
        args = dict(expected_sha256=parsed['source_sha256'], expected_bytes=parsed['source_bytes'],
                    stats_before=before, stats_after=after, start_ns=999000000, end_ns=1001000000,
                    reader_joined=True, reader_error=None, cleanup_errors=[], source_qualified=True,
                    enabled=True, allowed_results=[1, 2])
        args.update(changes)
        return p.qualify_capture(parsed, **args)

    def test_valid_capture_is_separate_from_parse(self):
        parsed = self.parse()
        self.assertFalse(parsed['capture_accepted'])
        self.assertEqual(parsed['duration_summaries']['fire_trace_envelope_ns']['max_ns'], 1000)
        self.assertTrue(self.qualified(parsed)['capture_accepted'])

    def test_plain_and_gzip_same_raw(self):
        parsed = self.parse()
        target = self.path.with_suffix('.gz')
        target.write_bytes(gzip.compress(self.path.read_bytes()))
        self.assertEqual(parsed, p.analyze(target))

    def test_bad_tail_rejects_whole_file(self):
        with self.assertRaisesRegex(ValueError, 'unexpected row 2'):
            self.parse(line()+b'broken\n')

    def test_unterminated_row(self):
        with self.assertRaisesRegex(ValueError, 'unterminated'):
            self.parse(line()[:-1])

    def test_duplicate_and_overlap(self):
        with self.assertRaises(ValueError):
            self.parse(line()+line())

    def test_unknown_event_and_partial_pointer(self):
        for data in (line().replace(b'kgsl_event_phases:', b'kgsl_fire_event:'),
                     line().replace(b'00000000556b3de4', b'556b3de4')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.parse(data)

    def test_timestamp_reversal_and_overflow(self):
        for data in (line(fire_exit_ns=1000001999), line(restore_end_ns=1 << 64),
                     line(ctx=1 << 32), line(promote_ret=1 << 31)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.parse(data)

    def test_emission_before_restore(self):
        with self.assertRaisesRegex(ValueError, 'emission'):
            self.parse(line(restore_end_ns=1000010000))

    def test_source_bytes_and_hash(self):
        for kwargs in ({'expected_sha256': '0'*64}, {'expected_bytes': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.qualified(**kwargs)

    def test_reader_and_source_gates(self):
        for kwargs in ({'source_qualified': False}, {'reader_joined': False},
                       {'reader_error': 'short write'}, {'cleanup_errors': ['not removed']}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.qualified(**kwargs)

    def test_loss_and_drain(self):
        for field in p.LOSS_FIELDS+('entries',):
            after = stats()
            after[3]['read events'] = 1
            after[3][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.qualified(stats_after=after)

    def test_complete_cpu_and_read_counts(self):
        for after in ({}, stats()):
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.qualified(stats_after=after)

    def test_capture_boundary(self):
        for kwargs in ({'start_ns': 1000001001}, {'end_ns': 1000007499}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.qualified(**kwargs)

    def test_result_enum_and_disabled_rows(self):
        for kwargs in ({'allowed_results': [9]}, {'enabled': False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.qualified(**kwargs)

    def test_empty_enabled_rejected_off_accepted(self):
        parsed = self.parse(b'')
        with self.assertRaises(ValueError):
            self.qualified(parsed)
        self.assertTrue(self.qualified(parsed, enabled=False)['capture_accepted'])

    def test_join_exact_closed_work(self):
        joined = p.join_generations(self.qualified(), [work()], result_names={1: 'retired', 2: 'cancelled'})
        self.assertEqual(joined['matched_works'], 1)
        self.assertEqual(joined['rows'][0]['execute_to_entry_lower_ns'], 501)
        self.assertEqual(joined['rows'][0]['execute_to_entry_upper_ns'], 1500)

    def test_header_uses_source_bound_nearest_microsecond_interval(self):
        parsed = self.parse(line(restore_end_ns=1000007499))
        self.assertEqual(parsed['rows'][0]['printed_lower_ns'], 1000006500)
        self.assertEqual(parsed['rows'][0]['printed_upper_ns'], 1000007499)
        with self.assertRaisesRegex(ValueError, 'emission before restore'):
            self.parse(line(restore_end_ns=1000007500))

    def test_rounded_fire_can_print_31_ns_after_exact_exit(self):
        parsed = self.qualified(self.parse(line(fire_enter_ns=1000002354,
                                                fire_exit_ns=1000003969)))
        candidate = work()
        candidate['fires'][0]['ns'] = 1000004000
        self.assertTrue(p.join_generations(parsed, [candidate],
                                           result_names={1: 'retired'})['accepted'])
        candidate['fires'][0]['ns'] = 1000005000
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            p.join_generations(parsed, [candidate], result_names={1: 'retired'})

    def test_execute_can_round_above_exact_worker_entry(self):
        candidate = work()
        candidate['start']['ns'] = 1000001000
        joined = p.join_generations(self.qualified(self.parse(line(entry_ns=1000000999))),
                                    [candidate], result_names={1: 'retired'})
        self.assertEqual(joined['rows'][0]['execute_to_entry_lower_ns'], 0)
        self.assertEqual(joined['rows'][0]['execute_to_entry_upper_ns'], 499)
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            p.join_generations(self.qualified(self.parse(line(entry_ns=1000000499))),
                               [candidate], result_names={1: 'retired'})

    def test_join_requires_phase_gate(self):
        with self.assertRaises(ValueError):
            p.join_generations(self.parse(), [work()], result_names={1: 'retired'})

    def test_join_requires_all_main_works(self):
        second = work()
        second.update(generation=18, work='00000000556b3de5')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            p.join_generations(self.qualified(), [work(), second], result_names={1: 'retired'})

    def test_join_rejects_ambiguous_generation(self):
        second = work()
        second['generation'] = 18
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            p.join_generations(self.qualified(), [work(), second], result_names={1: 'retired'})

    def test_join_rejects_wrong_identity_and_fire_bounds(self):
        for change in ('pid', 'ts', 'result', 'fire_bound', 'end_bound'):
            candidate = work()
            if change == 'pid':
                candidate['start']['tid'] = 2744
            elif change == 'ts':
                candidate['fires'][0]['fields'] = candidate['fires'][0]['fields'].replace('ts=6107', 'ts=6108')
            elif change == 'result':
                candidate['fires'][0]['fields'] = candidate['fires'][0]['fields'].replace('retired', 'cancelled')
            elif change == 'fire_bound':
                candidate['fires'][0]['ns'] = 1000010000
            else:
                candidate['end']['ns'] = 1000005000
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.join_generations(self.qualified(), [candidate], result_names={1: 'retired'})


if __name__ == '__main__':
    unittest.main()
