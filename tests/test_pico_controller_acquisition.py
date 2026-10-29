import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('acquisition', ROOT / 'tools/analyze-pico-controller-acquisition.py')
acquisition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquisition)


def head(timestamp):
    raw = bytearray(368)
    struct.pack_into('<q', raw, 0, timestamp)
    struct.pack_into('<d', raw, 32, 1)
    raw[64:66] = b'\x01\x01'
    return raw


class AcquisitionTests(unittest.TestCase):
    def fixture(self, root, version=2):
        motion = root / 'motion.raw'
        images = root / 'images.raw'
        size, capacity = ((acquisition.MOTION_SIZE, 4096) if version == 2
                          else (acquisition.MOTION_V3_SIZE, 16384))
        raw = bytearray(struct.pack('<4Q', acquisition.MOTION_MAGIC, version, size, capacity))
        rows = [(None, 100, 1), (None, 300, 2)] if version == 2 else [
            (1, 300, 1), (2, 100, 2), (1, 400, 4), (2, 200, 5)]
        for hand, timestamp, order in rows:
            raw += struct.pack('<3Q', timestamp, 7, order)
            if version == 3:
                raw += struct.pack('<2I', hand, 0)
            raw += struct.pack('<9d', *([0.] * 9))
            raw += head(timestamp-1) + head(timestamp+1)
        motion.write_bytes(raw)
        raw = bytearray(struct.pack('<4Q', acquisition.IMAGE_MAGIC, version, acquisition.IMAGE_SIZE, 150))
        raw += struct.pack('<3Q', 200, 7, 3) + head(199) + head(201)
        for camera in range(4):
            raw += acquisition.FRAME.pack(camera, 640, 480, 0x123, 0, 1, 1, 0, 210, 200, 12,
                                          acquisition.PIXELS, 0)
            raw += bytes(acquisition.PIXELS)
        images.write_bytes(raw)
        return motion, images

    def test_dispatch_order_is_retained_instead_of_capture_time_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.fixture(Path(tmp))
            report = acquisition.analyze(*paths)
            self.assertEqual([x['timestamp_ns'] for x in report['events']], [100, 300, 200])
            self.assertEqual((report['motion_records'], report['image_sets']), (2, 1))
            self.assertTrue(report['dispatch_order_recorded'])
            self.assertFalse(report['optical_tracking_verified'])
            self.assertFalse(report['original_wall_timing_reproduced'])
            self.assertFalse(report['motion_hands_recorded'])
            self.assertIsNone(report['motion_records_per_hand'])

    def test_version_three_preserves_hand_and_dispatch_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = acquisition.analyze(*self.fixture(Path(tmp), version=3))
            self.assertEqual(report['format_version'], 3)
            self.assertTrue(report['motion_hands_recorded'])
            self.assertEqual(report['motion_records_per_hand'], {'1': 2, '2': 2})
            self.assertEqual([(e['hand'], e['timestamp_ns']) for e in report['events']
                              if e['kind'] == 'motion'], [(1, 300), (2, 100), (1, 400), (2, 200)])
            self.assertEqual([e['dispatch_order'] for e in report['events']], [1, 2, 3, 4, 5])
            self.assertFalse(report['optical_tracking_verified'])

    def test_version_three_allows_equal_capture_times_between_hands(self):
        with tempfile.TemporaryDirectory() as tmp:
            motion, images = self.fixture(Path(tmp), version=3)
            raw = bytearray(motion.read_bytes())
            struct.pack_into('<Q', raw, 32+acquisition.MOTION_V3_SIZE, 300)
            struct.pack_into('<q', raw, 32+acquisition.MOTION_V3_SIZE+104, 299)
            struct.pack_into('<q', raw, 32+acquisition.MOTION_V3_SIZE+104+368, 301)
            struct.pack_into('<Q', raw, 32+3*acquisition.MOTION_V3_SIZE, 400)
            struct.pack_into('<q', raw, 32+3*acquisition.MOTION_V3_SIZE+104, 399)
            struct.pack_into('<q', raw, 32+3*acquisition.MOTION_V3_SIZE+104+368, 401)
            motion.write_bytes(raw)
            self.assertEqual(acquisition.analyze(motion, images)['motion_records'], 4)

    def test_version_three_rejects_invalid_hand_schema_and_per_hand_regression(self):
        faults = ['hand_zero', 'hand_three', 'reserved', 'stride', 'capacity', 'mixed_version',
                  'regression', 'nonfinite', 'bracket', 'truncated', 'generation']
        for fault in faults:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                motion, images = self.fixture(Path(tmp), version=3)
                raw = bytearray(motion.read_bytes())
                if fault.startswith('hand_'):
                    struct.pack_into('<I', raw, 32+24, 0 if fault == 'hand_zero' else 3)
                elif fault == 'reserved':
                    struct.pack_into('<I', raw, 32+28, 1)
                elif fault == 'stride':
                    struct.pack_into('<Q', raw, 16, acquisition.MOTION_SIZE)
                elif fault == 'capacity':
                    struct.pack_into('<Q', raw, 24, 16385)
                elif fault == 'mixed_version':
                    other = bytearray(images.read_bytes())
                    struct.pack_into('<Q', other, 8, 2)
                    images.write_bytes(other)
                elif fault == 'regression':
                    struct.pack_into('<Q', raw, 32+3*acquisition.MOTION_V3_SIZE, 99)
                elif fault == 'nonfinite':
                    struct.pack_into('<d', raw, 32+32, float('nan'))
                elif fault == 'bracket':
                    struct.pack_into('<q', raw, 32+104, 300)
                elif fault == 'generation':
                    struct.pack_into('<Q', raw, 32+acquisition.MOTION_V3_SIZE+8, 8)
                else:
                    raw.pop()
                motion.write_bytes(raw)
                with self.assertRaises(ValueError):
                    acquisition.analyze(motion, images)

    def test_missing_duplicate_orders_and_mixed_generations_are_rejected(self):
        for offset, value in [(16, 4), (16, 2), (8, 8)]:
            with self.subTest(offset=offset, value=value), tempfile.TemporaryDirectory() as tmp:
                motion, images = self.fixture(Path(tmp))
                raw = bytearray(images.read_bytes())
                struct.pack_into('<Q', raw, 32+offset, value)
                images.write_bytes(raw)
                with self.assertRaises(ValueError):
                    acquisition.analyze(motion, images)

    def test_unrecorded_order_truncation_and_nonfinite_motion_are_rejected(self):
        for fault in ['legacy', 'truncated', 'empty', 'nan', 'regressing_time']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                motion, images = self.fixture(Path(tmp))
                raw = bytearray(motion.read_bytes())
                if fault == 'legacy':
                    struct.pack_into('<Q', raw, 8, 1)
                elif fault == 'truncated':
                    raw.pop()
                elif fault == 'empty':
                    raw = raw[:32]
                elif fault == 'nan':
                    struct.pack_into('<d', raw, 32+24, float('nan'))
                else:
                    struct.pack_into('<Q', raw, 32+acquisition.MOTION_SIZE, 99)
                motion.write_bytes(raw)
                with self.assertRaises(ValueError):
                    acquisition.analyze(motion, images)

    def test_invalid_head_brackets_and_camera_sets_are_rejected(self):
        for fault in ['head_time', 'head_state', 'head_quaternion', 'camera', 'frame', 'center']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                motion, images = self.fixture(Path(tmp))
                raw = bytearray(images.read_bytes())
                if fault == 'head_time':
                    struct.pack_into('<q', raw, 32+24, 201)
                elif fault == 'head_state':
                    raw[32+24+64] = 0
                elif fault == 'head_quaternion':
                    struct.pack_into('<d', raw, 32+24+32, 2)
                elif fault == 'camera':
                    raw[32+760] = 3
                elif fault == 'frame':
                    struct.pack_into('<Q', raw, 32+760+48, 13)
                else:
                    struct.pack_into('<q', raw, 32+760+40, 199)
                images.write_bytes(raw)
                with self.assertRaises(ValueError):
                    acquisition.analyze(motion, images)

    def test_camera_exposure_and_gain_bounds_apply_to_every_view(self):
        for camera in range(4):
            for offset, value in [(20, 0), (20, 4096), (24, 0), (24, 256)]:
                with self.subTest(camera=camera, offset=offset, value=value), tempfile.TemporaryDirectory() as tmp:
                    motion, images = self.fixture(Path(tmp))
                    raw = bytearray(images.read_bytes())
                    struct.pack_into('<I', raw, 32+760+camera*(64+acquisition.PIXELS)+offset, value)
                    images.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, 'Invalid camera exposure or gain'):
                        acquisition.analyze(motion, images)
        with tempfile.TemporaryDirectory() as tmp:
            motion, images = self.fixture(Path(tmp))
            raw = bytearray(images.read_bytes())
            for camera in range(4):
                struct.pack_into('<II', raw, 32+760+camera*(64+acquisition.PIXELS)+20, 4095, 255)
            images.write_bytes(raw)
            self.assertEqual(acquisition.analyze(motion, images)['image_sets'], 1)


if __name__ == '__main__':
    unittest.main()
