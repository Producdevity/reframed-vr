import hashlib
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'system/steamvr-pico/resources/rendermodels'


class PicoSteamvrModelTests(unittest.TestCase):
    def test_assets_match_pinned_conversion_and_license(self):
        self.assertEqual(hashlib.sha256((MODELS / 'provenance.json').read_bytes()).hexdigest(),
                         '1d150a427afb69f11f5ebb916876be2199b399076ae83bd47e4c1a96a24b366a')
        record = json.loads((MODELS / 'provenance.json').read_text())
        self.assertEqual(set(record['models']), {'left', 'right'})
        self.assertEqual(record['upstream'], json.loads((ROOT / 'profiles/pico-controller-models.json').read_text()))
        self.assertEqual(hashlib.sha256((MODELS / 'LICENSE').read_bytes()).hexdigest(),
                         '0ef0c87e8ffdd0681f332dc3b39f284dee2166d1f853fabc3853884fe81a6f30')
        for hand, model in record['models'].items():
            directory = MODELS / ('neo3_' + hand)
            for name, digest in model['sha256'].items():
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest)
            definition = json.loads((directory / ('neo3_' + hand + '.json')).read_text())
            self.assertEqual(set(definition['components']), {'body', 'tip', 'grip', 'handgrip'})

    def test_geometry_has_valid_indices_normals_and_physical_scale(self):
        bounds = {}
        for hand in ('left', 'right'):
            path = MODELS / ('neo3_' + hand) / ('neo3_' + hand + '.obj')
            rows = [line.split() for line in path.read_text().splitlines() if line and not line.startswith('#')]
            positions = [[float(x) for x in r[1:]] for r in rows if r[0] == 'v']
            uv = [[float(x) for x in r[1:]] for r in rows if r[0] == 'vt']
            normals = [[float(x) for x in r[1:]] for r in rows if r[0] == 'vn']
            self.assertLess(len(positions), 65000)
            self.assertEqual(len(positions), len(uv))
            self.assertEqual(len(positions), len(normals))
            self.assertEqual(sum(r[0] == 'o' for r in rows), 1)
            self.assertEqual(sum(r[0] == 'f' for r in rows), 3488)
            for normal in normals:
                self.assertAlmostEqual(sum(v*v for v in normal), 1, places=6)
            for triangle in (r for r in rows if r[0] == 'f'):
                self.assertEqual(len(triangle), 4)
                for vertex in triangle[1:]:
                    self.assertTrue(all(1 <= int(i) <= len(positions) for i in vertex.split('/')))
            self.assertTrue(all(math.isfinite(v) for p in positions for v in p))
            bounds[hand] = [[min(p[i] for p in positions), max(p[i] for p in positions)] for i in range(3)]
            self.assertGreater(max(b-a for a, b in bounds[hand]), .1)
            self.assertLess(max(b-a for a, b in bounds[hand]), .2)
        self.assertAlmostEqual(bounds['left'][0][0], -bounds['right'][0][1], places=6)
        self.assertAlmostEqual(bounds['left'][0][1], -bounds['right'][0][0], places=6)
        self.assertEqual(bounds['left'][1:], bounds['right'][1:])


if __name__ == '__main__':
    unittest.main()
