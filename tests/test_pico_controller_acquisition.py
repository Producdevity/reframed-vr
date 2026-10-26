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
    def fixture(self, root):
        motion = root / 'motion.raw'
        images = root / 'images.raw'
        raw = bytearray(struct.pack('<4Q', acquisition.MOTION_MAGIC, 2, acquisition.MOTION_SIZE, 4096))
        for timestamp, order in [(100, 1), (300, 2)]:
            raw += struct.pack('<3Q9d', timestamp, 7, order, *([0.] * 9))
            raw += head(timestamp-1) + head(timestamp+1)
        motion.write_bytes(raw)
        raw = bytearray(struct.pack('<4Q', acquisition.IMAGE_MAGIC, 2, acquisition.IMAGE_SIZE, 150))
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
