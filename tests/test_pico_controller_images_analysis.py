import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('image_analysis', ROOT / 'tools/analyze-pico-controller-images.py')
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)
acquisition = analysis.acquisition


def head(timestamp):
    raw = bytearray(368)
    struct.pack_into('<q', raw, 0, timestamp)
    struct.pack_into('<d', raw, 32, 1)
    raw[64:66] = b'\x01\x01'
    return raw


def yaml(transform):
    return ('sensor_type: camera\nT_BS:\n  rows: 4\n  cols: 4\n  data: [' +
            ', '.join(map(str, transform.flatten())) + ']\nresolution: [640,480]\n'
            'camera_model: omni\nintrinsics: [0,200,200,320,240]\n'
            'distortion_model: radtan\ndistortion_coefficients: [0,0,0,0]\n')


class ControllerImageAnalysisTests(unittest.TestCase):
    def fixture(self, root, flip=False, version=2):
        cameras = []
        for i, x in enumerate((-.06, .06)):
            transform = np.eye(4)
            transform[0, 3] = x
            path = root / f'cam{i}.yaml'
            path.write_text(yaml(transform))
            cameras.append(path)
        vector = np.zeros(85, dtype='<f4')
        vector[25] = 1
        vector[26:74] = np.column_stack((np.linspace(-.05, .05, 16),
                                        np.zeros(16), np.zeros(16))).flatten()
        tracker = root / 'tracker.bin'
        tracker.write_bytes(vector.tobytes())
        raw = bytearray(struct.pack('<4Q', acquisition.IMAGE_MAGIC, version, acquisition.IMAGE_SIZE, 150))
        raw += struct.pack('<3Q', 200, 7, 1) + head(199) + head(201)
        locations = [(300, 220), (306, 224), (312, 228), (318, 224), (310, 232)]
        for i in range(4):
            raw += acquisition.FRAME.pack(i, 640, 480, 0x123, 0, 1, 1, 0, 210, 200, 12,
                                          acquisition.PIXELS, 0)
            pixels = np.zeros((480, 640), dtype=np.uint8)
            if i < 2:
                for x, y in locations:
                    x -= 24*i
                    pixels[y:y+2, x:x+2] = 255
                if flip:
                    pixels = pixels[:, ::-1]
            raw += pixels.tobytes()
        images = root / 'images.raw'
        images.write_bytes(raw)
        return images, cameras, tracker

    def run_fixture(self, paths, **kwargs):
        return analysis.analyze(*paths, frames=[1], image_cameras=[0, 1],
                                transforms=['none', 'none'], thresholds=[80], **kwargs)

    def test_saved_pixels_produce_hypotheses_with_exact_inputs_and_no_tracking_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.fixture(Path(tmp))
            report = self.run_fixture(paths)
            self.assertFalse(report['optical_tracking_verified'])
            self.assertFalse(report['sdk_gate_comparison_performed'])
            self.assertGreater(report['observations'][0]['total_hypotheses'], 0)
            hypothesis = report['observations'][0]['hypotheses'][0]
            self.assertAlmostEqual(hypothesis['feature_centroid_body_m'][2], 1, places=10)
            self.assertGreater(hypothesis['centroid_radial_distance_m'], 1)
            for path in [paths[0], *paths[1], paths[2]]:
                self.assertEqual(report['input_sha256'][str(path)], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_omni_radtan_projection_inverts_in_rotated_body_frame(self):
        rotation = np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]])
        origin = np.array([.3, -.1, .2])
        cameras = []
        for x in (-.06, .06):
            transform = np.eye(4)
            transform[:3, :3] = rotation
            transform[:3, 3] = rotation @ [x, 0, 0] + origin
            cameras.append((transform, np.array([1.5, 500, 510, 320, 240]),
                            np.array([.3, -.2, .001, -.002])))
        local = np.array([[-.03, -.02, 0], [.02, -.025, 0], [.04, .01, 0],
                          [0, .03, 0], [-.03, .01, 0]])
        for depth in (.3, .6, 1.1):
            points = (local + [0, 0, depth]) @ rotation.T + origin
            pixels = [analysis.project(c, points) for c in cameras]
            result = analysis.hypotheses(cameras, pixels, .12, 1e-5)
            self.assertEqual(result['total_hypotheses'], 1)
            np.testing.assert_allclose(result['hypotheses'][0]['points_body_m'], points, atol=1e-9)

    def test_version_three_images_keep_the_same_geometry_interpretation(self):
        observations = []
        for version in (2, 3):
            with tempfile.TemporaryDirectory() as tmp:
                paths = self.fixture(Path(tmp), version=version)
                self.assertEqual(acquisition.records(paths[0], 'images')[0]['format_version'], version)
                report = self.run_fixture(paths)
                observations.append(report['observations'])
                self.assertFalse(report['optical_tracking_verified'])
        self.assertEqual(observations[0], observations[1])

    def test_explicit_camera_mapping_and_pixel_transform_are_not_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            images, cameras, tracker = self.fixture(Path(tmp), flip=True)
            corrected = analysis.analyze(images, cameras, tracker, [1], [0, 1],
                                         ['flip-x', 'flip-x'], [80])
            self.assertGreater(corrected['observations'][0]['total_hypotheses'], 0)
            self.assertEqual(corrected['camera_mapping_assumptions'][0]['pixel_transform'], 'flip-x')
            incorrect = analysis.analyze(images, cameras, tracker, [1], [0, 1], ['none', 'none'], [80])
            self.assertEqual(incorrect['observations'][0]['total_hypotheses'], 0)
            self.assertFalse(corrected['optical_tracking_verified'])

    def test_multiple_constellations_remain_ambiguous(self):
        cameras = []
        for x in (-.06, .06):
            transform = np.eye(4)
            transform[0, 3] = x
            cameras.append((transform, np.array([0, 200, 200, 320, 240]), np.zeros(4)))
        points = np.array([[.01*i, .007*i, 1] for i in range(6)])
        pixels = [analysis.project(c, points) for c in cameras]
        report = analysis.hypotheses(cameras, pixels, .1, 1e-5)
        self.assertEqual(report['total_hypotheses'], 6)
        self.assertEqual(len(report['hypotheses']), 6)
        self.assertFalse(report['reported_hypotheses_truncated'])

    def test_insufficient_features_and_detection_limits_are_explicit(self):
        c = (np.eye(4), np.array([0, 200, 200, 320, 240]), np.zeros(4))
        result = analysis.hypotheses([c, c], [np.zeros((4, 2)), np.zeros((5, 2))], .1, .5)
        self.assertEqual(result['status'], 'insufficient_features')
        pixels = np.full(640*480, 255, dtype=np.uint8)
        self.assertEqual(analysis.components(pixels, 80, 4)['status'], 'bright_pixel_limit')
        pixels[:] = 0
        for i in range(8):
            pixels[100*640 + i*10:100*640 + i*10+2] = 255
        result = analysis.components(pixels, 80, 4)
        self.assertEqual((result['status'], result['feature_count']), ('feature_limit', 8))
        self.assertEqual(len(result['features']), analysis.MAX_FEATURES)

    def test_metadata_rows_and_row_edges_do_not_create_connected_blobs(self):
        pixels = np.zeros(640*480, dtype=np.uint8)
        pixels[:640] = 255
        pixels[10*640+638:10*640+640] = 255
        pixels[11*640:11*640+2] = 255
        result = analysis.components(pixels, 80, 4)
        self.assertEqual(result['feature_count'], 2)
        self.assertEqual([f['area'] for f in result['features']], [2, 2])

    def test_legacy_truncated_mixed_camera_and_bad_head_carriers_are_refused(self):
        for fault in ('legacy', 'truncated', 'camera', 'head', 'timing', 'exposure'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                paths = self.fixture(Path(tmp))
                raw = bytearray(paths[0].read_bytes())
                if fault == 'legacy':
                    struct.pack_into('<Q', raw, 8, 1)
                elif fault == 'truncated':
                    raw.pop()
                elif fault == 'camera':
                    raw[32+760] = 2
                elif fault == 'head':
                    raw[32+24+64] = 0
                elif fault == 'timing':
                    struct.pack_into('<q', raw, 32+760+32, 190)
                elif fault == 'exposure':
                    struct.pack_into('<I', raw, 32+760+20, 0)
                paths[0].write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.run_fixture(paths)

    def test_bad_calibration_is_not_treated_as_no_visible_controller(self):
        for fault in ('nan', 'reflection', 'duplicate', 'model', 'baseline'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                paths = self.fixture(Path(tmp))
                if fault in ('nan', 'reflection'):
                    transform = np.eye(4)
                    transform[0, 0] = float('nan') if fault == 'nan' else -1
                    paths[1][0].write_text(yaml(transform))
                elif fault == 'duplicate':
                    paths[1][0].write_text(paths[1][0].read_text() + 'camera_model: omni\n')
                elif fault == 'baseline':
                    paths[1][1].write_bytes(paths[1][0].read_bytes())
                else:
                    paths[2].write_bytes(bytes(340))
                with self.assertRaises(ValueError):
                    self.run_fixture(paths)

    def test_caller_search_bounds_and_missing_frames_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.fixture(Path(tmp))
            for options in ({'frames': [2]}, {'frames': [1]*5}, {'thresholds': [80]*4},
                            {'image_cameras': [0, 0]}, {'pixel_limit': float('nan')},
                            {'diameter_margin': 1}, {'masked_rows': 480}):
                arguments = dict(frames=[1], image_cameras=[0, 1], transforms=['none', 'none'], thresholds=[80])
                arguments.update(options)
                with self.subTest(options=options), self.assertRaises(ValueError):
                    analysis.analyze(*paths, **arguments)


if __name__ == '__main__':
    unittest.main()
