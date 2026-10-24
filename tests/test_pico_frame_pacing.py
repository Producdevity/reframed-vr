import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pacing', ROOT / 'tools/analyze-pico-frame-pacing.py')
PACING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACING)


def frame(index, time, presents=1, gpu=7):
    return f'PICO_STEAMVR_FRAME_HISTORY index={index} system_s={time} presents={presents} mispresented=0 dropped=0 gpu_ms={gpu} cpu_ms=0.5\n'


class PicoFramePacingTests(unittest.TestCase):
    def test_overlapping_snapshots_update_counts_without_duplicating_frames(self):
        text = frame(1, 1) + frame(2, 1.01, 0) + frame(2, 1.01, 1) + frame(3, 1.03, 2, 12)
        result = PACING.analyze(text, 100)
        self.assertEqual(result['observations'], 4)
        self.assertEqual(result['unique_frames'], 3)
        self.assertEqual(result['frame_presents'], {1: 2, 2: 1})
        self.assertEqual(result['intervals_over_1_5_periods'], 1)
        self.assertEqual(result['gpu_over_frame_budget'], 1)
        self.assertEqual(result['missing_frame_indices'], 0)
        self.assertFalse(result['photon_latency_verified'])

    def test_missing_frames_are_not_invented_and_corrupt_sessions_are_refused(self):
        result = PACING.analyze(frame(1, 1) + frame(4, 1.03), 100)
        self.assertEqual(result['missing_frame_indices'], 2)
        self.assertIsNone(result['consecutive_frame_interval_ms'])
        for text in [frame(1, 1), frame(1, 1) + frame(1, 2),
                     frame(1, 2) + frame(2, 1), frame(1, 1) + frame(2, 'nan')]:
            with self.assertRaises(ValueError):
                PACING.analyze(text, 100)
