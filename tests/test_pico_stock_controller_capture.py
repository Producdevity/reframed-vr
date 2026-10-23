import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stock_capture', ROOT / 'tools/capture-pico-stock-controller.py')
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


def recording(timestamp=100000000, rc=0):
    data = bytearray(struct.pack('<8Q', *CAPTURE.HEADER_V1))
    for i in range(300):
        now = 1000000000 + i * 10000000
        data.extend(struct.pack('<5q', now + 2000000000, now, now + 1000, now + 2000001000, rc))
        left, right = bytearray(368), bytearray(368)
        struct.pack_into('<q', left, 0, timestamp)
        struct.pack_into('<q', right, 0, -1)
        left[0x41] = right[0x41] = 1
        data.extend(left)
        data.extend(right)
    return data


class PicoStockControllerCaptureTests(unittest.TestCase):
    def test_raw_clock_is_observed_without_changing_vendor_timestamps(self):
        data = bytearray(struct.pack('<8Q', *CAPTURE.HEADER))
        for i in range(300):
            mono = 1000000000 + i * 10000000
            raw = mono + 3450000000
            data.extend(struct.pack('<9q', mono, mono, raw, raw + 4000000000,
                                    raw + 4000001000, raw + 1000, mono + 2000, mono + 3000, 0))
            left, right = bytearray(368), bytearray(368)
            struct.pack_into('<q', left, 0, raw - 2000000)
            struct.pack_into('<q', right, 0, -1)
            left[0x40] = left[0x41] = left[0x52] = 1
            data.extend(left + right)
        report = CAPTURE.analyze(data)
        self.assertEqual(report['format_version'], 2)
        left = report['hands']['left']
        self.assertEqual(left['monotonic_raw_within_100ms'], 300)
        self.assertEqual(left['monotonic_within_100ms'], 0)
        self.assertEqual(left['boottime_within_100ms'], 0)
        self.assertEqual(left['qtimer_within_100ms'], 0)
        self.assertEqual(left['distinct_positive_timestamps'], 300)
        self.assertFalse(report['optical_tracking_verified'])
        counter_data = bytearray(data)
        for i in range(300):
            struct.pack_into('<q', counter_data, 64 + i * 808 + 72,
                             1000000000 + i * 10000000 + 3450000000 + 4000000000 - 2000000)
        counter_report = CAPTURE.analyze(counter_data)['hands']['left']
        self.assertEqual(counter_report['qtimer_within_100ms'], 300)
        self.assertEqual(counter_report['monotonic_raw_within_100ms'], 0)
        struct.pack_into('<q', data, 64 + 32, 0)
        with self.assertRaises(ValueError):
            CAPTURE.analyze(data)

    def test_success_and_public_confidence_do_not_promote_cached_poses(self):
        report = CAPTURE.analyze(recording())
        self.assertEqual(report['calls'], {0: 300})
        self.assertFalse(report['optical_tracking_verified'])
        self.assertEqual(report['hands']['left']['distinct_positive_timestamps'], 1)
        self.assertEqual(report['hands']['left']['monotonic_within_100ms'], 0)
        self.assertEqual(report['hands']['right']['positive_timestamps'], 0)
        self.assertIsNone(report['hands']['right']['monotonic_age_ns'])

    def test_observation_clocks_stay_separate_and_freshness_is_not_optical_proof(self):
        data = recording()
        for i in range(300):
            struct.pack_into('<q', data, 64 + i * 776 + 40, 1000000000 + i * 10000000)
        report = CAPTURE.analyze(data)
        left = report['hands']['left']
        self.assertEqual(left['monotonic_within_100ms'], 300)
        self.assertEqual(left['boottime_within_100ms'], 0)
        self.assertEqual(left['distinct_positive_timestamps'], 300)
        self.assertFalse(report['optical_tracking_verified'])

    def test_failed_getters_do_not_use_output_bytes(self):
        report = CAPTURE.analyze(recording(rc=-3))
        self.assertEqual(report['calls'], {-3: 300})
        self.assertEqual(report['hands']['left']['successful_reads'], 0)
        self.assertFalse(report['optical_tracking_verified'])

    def test_truncation_header_and_clock_corruption_are_refused(self):
        data = recording()
        with self.assertRaises(ValueError):
            CAPTURE.analyze(data[:-1])
        with self.assertRaises(ValueError):
            CAPTURE.analyze(data + b'\x00')
        data[0] ^= 1
        with self.assertRaises(ValueError):
            CAPTURE.analyze(data)
        data = recording()
        struct.pack_into('<q', data, 64 + 16, 0)
        with self.assertRaises(ValueError):
            CAPTURE.analyze(data)


if __name__ == '__main__':
    unittest.main()
