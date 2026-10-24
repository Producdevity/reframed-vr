import importlib.util
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('pico_preview', Path(__file__).parents[1]/'tools/preview-pico-scanout.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def view(width, height):
    return {'viewport': [0, 0, width, height], 'display': [width, height], 'rotation': [1, 0, 0, 1],
            'fov': [-math.pi/4, math.pi/4, math.pi/4, -math.pi/4],
            'analytic_distortion': {'type': 'pico-radial-2', 'tangent_scale': [2, -2], 'tangent_offset': [-1, 1],
                                    'radial_coefficients': [1]+[0]*10, 'chromatic_coefficients': [0]*6}}


class PicoScanoutPreviewTests(unittest.TestCase):
    def test_output_aspect_follows_per_eye_display(self):
        self.assertEqual(preview.eye_size(view(1920, 1832), 960), (960, 916))
        self.assertEqual(preview.eye_size(view(1832, 1920), 916), (916, 960))
        for invalid in [None, [0, 1920], [True, 1920], [1832], [1, 16384]]:
            optics = view(1920, 1832)
            optics['display'] = invalid
            with self.subTest(display=invalid), self.assertRaises(ValueError):
                preview.eye_size(optics, 916)

    def test_loads_eight_and_ten_bit_captures_with_both_profile_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            optics = view(1920, 1832)
            profile = {'schema_version': 2, 'device': 'PICOA7H10', 'serial': 'fixture',
                       'screen': {'width': 1920, 'height': 3664},
                       'views': [optics, copy.deepcopy(optics)]}
            profile['views'][1]['viewport'][1] = 1832
            for name in ['XR24', 'AR24', 'XB24', 'AB24', 'XR30', 'AR30', 'XB30', 'AB30']:
                bits = 10 if name.endswith('30') else 8
                maximum = (1 << bits)-1
                red, blue = (2*bits, 0) if name[1] == 'R' else (0, 2*bits)
                words = np.zeros((3664, 1924), dtype='<u4')
                words[0, :4] = [maximum << red, maximum << bits, maximum << blue, 0xffffffff]
                raw = words.tobytes()
                (root/'native.bin').write_bytes(raw)
                metadata = {'boot_serial': 'fixture', 'size': [1920, 3664], 'pitch': 7696,
                            'modifier': 0, 'offset': 0, 'fourcc': name, 'native_bytes': len(raw),
                            'native_sha256': hashlib.sha256(raw).hexdigest()}
                (root/'metadata.json').write_text(json.dumps(metadata))
                profile['schema_version'] = 2 if name.startswith('X') else 3
                (root/'optics.json').write_text(json.dumps(profile))
                with self.subTest(format=name, schema=profile['schema_version']):
                    pixels, _, _ = preview.load_capture(root, root/'optics.json')
                    np.testing.assert_array_equal(pixels[0, :4],
                                                  [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]])

    def test_identity_and_quarter_turns_preserve_pixels(self):
        pixels = np.random.default_rng(42).integers(0, 256, size=(24, 32, 3), dtype=np.uint8)
        rotations = [[1, 0, 0, 1], [0, 1, -1, 0], [-1, 0, 0, -1], [0, -1, 1, 0]]
        for turn, rotation in enumerate(rotations):
            with self.subTest(turn=turn):
                optics = view(32, 24)
                optics['rotation'] = rotation
                expected = np.rot90(pixels, -turn)
                got, coverage, residual = preview.render_eye(pixels, optics, expected.shape[1], expected.shape[0])
                self.assertTrue(np.all(coverage))
                np.testing.assert_array_equal(got, expected)
                self.assertLess(residual, 1e-8)

    def test_recovers_neutral_source_from_separated_panel_channels(self):
        width, height = 80, 64
        optics = view(width, height)
        optics['analytic_distortion']['chromatic_coefficients'] = [.12, 0, -.08, 0, 0, 0]
        u, v = np.meshgrid((np.arange(width)+.5)/width, (np.arange(height)+.5)/height)
        channels = []
        for scale in [1.12, 1., .92]:
            source_u, source_v = (u-.5)*scale+.5, (v-.5)*scale+.5
            channels.append(np.rint(30+100*source_u+100*source_v).astype(np.uint8))
        panel = np.stack(channels, axis=-1)
        before = panel.astype(float)
        self.assertGreater(np.max(np.abs(before[:, :, 0]-before[:, :, 2])), 10)
        got, coverage, residual = preview.render_eye(panel, optics, width, height)
        expected = np.rint(30+100*u+100*v)
        self.assertGreater(np.count_nonzero(coverage), width*height*.8)
        for channel in range(3):
            self.assertLessEqual(np.max(np.abs(got[:, :, channel][coverage].astype(float)-expected[coverage])), 1)
        self.assertLess(residual, 1e-8)

    def test_nonlinear_roundtrip_and_outside_pixels(self):
        optics = view(80, 64)
        optics['analytic_distortion']['radial_coefficients'][1] = .3
        optics['analytic_distortion']['chromatic_coefficients'] = [.01, -.02, -.01, .03, -.005, .007]
        u = np.array([[.2, .35, .6, .8]])
        v = np.array([[.3, .7, .45, .65]])
        for channel in range(3):
            target_u, target_v = preview.coordinates(optics, u, v, channel)
            actual_u, actual_v, valid, residual = preview.inverse_coordinates(optics, target_u, target_v, channel)
            self.assertTrue(np.all(valid))
            np.testing.assert_allclose(actual_u, u, atol=1e-7)
            np.testing.assert_allclose(actual_v, v, atol=1e-7)
        _, _, valid, _ = preview.inverse_coordinates(view(80, 64), np.array([[-1.]]), np.array([[.5]]), 1)
        self.assertFalse(np.any(valid))


if __name__ == '__main__':
    unittest.main()
