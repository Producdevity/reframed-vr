import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shutdown', ROOT / 'tools/pico-steamvr-shutdown.py')
shutdown = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shutdown)


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(shutdown, 'boot_id', return_value='fixture-boot')
        patcher.start()
        self.addCleanup(patcher.stop)

    def exercise(self, request=0, core=('success', 'exited', '0'), missing=False, stop_error=False, stale=False):
        units = ['pico-steamvr-xvfb-test', 'pico-steamvr-server-test',
                 'pico-steamvr-compositor-test', 'pico-ui-seatd', 'pico-steamvr-monitor-test',
                 'pico-steamvr-dashboard-test']
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            def run(args, **kwargs):
                calls.append(args)
                if args == ['quit-client']:
                    if not missing:
                        for unit in units[1:3]:
                            with patch.dict(os.environ, dict(zip(('SERVICE_RESULT', 'EXIT_CODE', 'EXIT_STATUS'), core))):
                                shutdown.record_exit(directory, unit)
                            if stale:
                                path = directory / (unit + '.json')
                                row = json.loads(path.read_text())
                                row['monotonic_ns'] = 0
                                path.write_text(json.dumps(row))
                    return subprocess.CompletedProcess(args, request,
                        'quit request submitted\n', '')
                if stop_error and args[-1] == units[-1]:
                    raise subprocess.TimeoutExpired(args, 15)
                return subprocess.CompletedProcess(args, 0, '', '')
            now = [0]
            def sleep(seconds): now[0] += seconds
            result = shutdown.close_session(units, units[1], units[2], ['quit-client'], directory,
                run=run, clock=lambda: now[0], sleep=sleep, grace_seconds=1)
        expected = ['pico-steamvr-dashboard-test', 'pico-steamvr-monitor-test',
                    'pico-steamvr-compositor-test', 'pico-steamvr-server-test',
                    'pico-ui-seatd', 'pico-steamvr-xvfb-test']
        self.assertEqual(calls, [['quit-client']] + [['systemctl', 'stop', u] for u in expected])
        return result

    def test_orderly_core_exit(self):
        result = self.exercise()
        self.assertTrue(result['clean_core_shutdown'])
        self.assertTrue(result['natural_core_exit'])

    def test_failed_request_cannot_claim_success(self):
        self.assertFalse(self.exercise(request=1)['clean_core_shutdown'])

    def test_signal_or_crash_cannot_claim_success(self):
        for core in [('signal', 'killed', 'TERM'), ('exit-code', 'exited', '1')]:
            self.assertFalse(self.exercise(core=core)['clean_core_shutdown'])

    def test_absent_receipts_fall_back_in_order(self):
        self.assertFalse(self.exercise(missing=True)['clean_core_shutdown'])

    def test_same_boot_stale_receipts_cannot_claim_success(self):
        self.assertFalse(self.exercise(stale=True)['clean_core_shutdown'])

    def test_fallback_continues_after_stop_timeout(self):
        self.assertFalse(self.exercise(stop_error=True)['clean_core_shutdown'])

    def test_partial_startup_stops_registered_units_without_claiming_core_shutdown(self):
        server, compositor = 'pico-steamvr-server-test', 'pico-steamvr-compositor-test'
        for units in ([], ['pico-ui-seatd'], ['pico-ui-seatd', server]):
            with self.subTest(units=units), tempfile.TemporaryDirectory() as tmp:
                calls = []
                def run(args, **kwargs):
                    calls.append(args)
                    return subprocess.CompletedProcess(args, 0, '', '')
                report = shutdown.close_session(units, server, compositor, ['quit-client'],
                    Path(tmp), run=run, allow_partial=True,
                    sleep=lambda _: self.fail('Incomplete startup must not wait for absent core units'))
                expected = ([['systemctl', 'stop', server]] if server in units else [])
                if 'pico-ui-seatd' in units:
                    expected.append(['systemctl', 'stop', 'pico-ui-seatd'])
                self.assertEqual(calls, expected)
                self.assertFalse(report['clean_core_shutdown'])
                self.assertFalse(report['natural_core_exit'])
                self.assertIsNone(report['request'])
                self.assertIn(compositor, report['missing_core_units'])

    def test_partial_opt_in_does_not_relax_unit_ownership_or_duplicate_checks(self):
        server, compositor = 'pico-steamvr-server-test', 'pico-steamvr-compositor-test'
        with tempfile.TemporaryDirectory() as tmp:
            for units, core, allow in [([], server, False), ([server, server], server, True),
                                       (['other.service'], server, True), ([], '../other', True)]:
                with self.subTest(units=units, core=core, allow=allow), \
                        self.assertRaises(ValueError):
                    shutdown.close_session(units, core, compositor, ['quit-client'],
                                           Path(tmp), allow_partial=allow)

    def test_receipt_exclusive_and_owned_units_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            shutdown.record_exit(directory, 'pico-steamvr-test')
            before = (directory / 'pico-steamvr-test.json').read_bytes()
            with self.assertRaises(FileExistsError):
                shutdown.record_exit(directory, 'pico-steamvr-test')
            self.assertEqual(before, (directory / 'pico-steamvr-test.json').read_bytes())
            with self.assertRaises(ValueError):
                shutdown.record_exit(directory, '../other')
            self.assertEqual(len(list(directory.iterdir())), 1)

    def test_mismatched_receipt_fails_but_still_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            unit = 'pico-steamvr-server-test'
            (directory / (unit + '.json')).write_text(json.dumps({'unit': unit, 'boot_id': 'wrong'}))
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 0,
                    'quit request submitted\n', '')
            report = shutdown.close_session([unit, 'pico-steamvr-compositor-test'], unit,
                'pico-steamvr-compositor-test', ['quit-client'], directory, run=run)
            self.assertFalse(report['clean_core_shutdown'])
            self.assertTrue(report['errors'])
            self.assertEqual(calls[-1], ['systemctl', 'stop', unit])


if __name__ == '__main__':
    unittest.main()
