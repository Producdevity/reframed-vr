import importlib.util
import math
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('pico_preview', Path(__file__).parents[1]/'tools/preview-pico-scanout.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def view(width, height):
    return {'viewport': [0, 0, width, height], 'rotation': [1, 0, 0, 1],
            'fov': [-math.pi/4, math.pi/4, math.pi/4, -math.pi/4],
            'analytic_distortion': {'tangent_scale': [2, -2], 'tangent_offset': [-1, 1],
                                    'radial_coefficients': [1]+[0]*10, 'chromatic_coefficients': [0]*6}}


class PicoScanoutPreviewTests(unittest.TestCase):
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
