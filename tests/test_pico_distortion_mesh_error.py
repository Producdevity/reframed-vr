import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('mesh_error', ROOT / 'tools/pico-distortion-mesh-error.py')
mesh_error = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mesh_error)


def profile(radial):
    view = {'rotation': [0, 1, -1, 0], 'fov': [-.83, .83, .85, -.85], 'eye_pose': [0, 0, 0, 1, -.0317, 0, 0],
            'analytic_distortion': {'type': 'pico-radial-2', 'tangent_scale': [1.49, -1.56],
                                    'tangent_offset': [-.76, .79], 'radial_coefficients': radial,
                                    'chromatic_coefficients': [-.0029, -.0071, .0062, .0146, -.0076, .0153]}}
    return {'views': [view]}


class DistortionMeshErrorTests(unittest.TestCase):
    def test_linear_lens_has_no_interpolation_error(self):
        result = mesh_error.summary(mesh_error.mesh_errors(profile([1] + [0] * 10), 9, (1832, 1920)))
        self.assertLess(result['max_px'], .5)

    def test_error_falls_with_resolution_and_needs_visible_samples(self):
        lens = profile([1, .35, .55, .012, .32, .81, 1.78, 0, .73, .74, .75])
        coarse = mesh_error.summary(mesh_error.mesh_errors(lens, 17, (1832, 1920)))
        fine = mesh_error.summary(mesh_error.mesh_errors(lens, 65, (1832, 1920)))
        self.assertGreater(coarse['max_px'], 4 * fine['max_px'])
        with self.assertRaises(ValueError):
            mesh_error.summary([])


if __name__ == '__main__':
    unittest.main()
