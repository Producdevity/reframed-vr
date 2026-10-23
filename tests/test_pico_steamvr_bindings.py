import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'system/steamvr-pico/resources/input'
RUNTIME = ROOT / 'output/frame-native-steamvr-v2/runtime/resources/config'


class PicoSteamvrBindingTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((INPUT / 'neo3_profile.json').read_text())
        self.bindings = {name: json.loads((INPUT / name).read_text()) for name in (
            'neo3_legacy_bindings.json', 'neo3_compositor_bindings.json')}

    def test_driver_resource_references(self):
        legacy = self.profile['legacy_binding']
        self.assertEqual(legacy, '{reframed_pico}/input/neo3_legacy_bindings.json')
        self.assertEqual(self.profile['default_bindings'], [{
            'app_key': 'openvr.component.vrcompositor',
            'binding_url': 'neo3_compositor_bindings.json'}])
        for name, binding in self.bindings.items():
            self.assertEqual(binding['controller_type'], self.profile['controller_type'])
            self.assertIn('system/steamvr-pico/resources/input/' + name,
                          (ROOT / 'tools/build-pico-steamvr.py').read_text())

    def test_only_available_components_and_correct_hands(self):
        for binding in self.bindings.values():
            for group in binding['bindings'].values():
                paths = set()
                self.assertFalse(group.get('haptics'))
                self.assertFalse(group.get('skeleton'))
                for item in group['sources']:
                    path = item['path']
                    self.assertNotIn(path, paths)
                    paths.add(path)
                    parts = path.split('/')
                    self.assertEqual(parts[:3], ['', 'user', 'hand'])
                    self.assertIn(parts[3], ('left', 'right'))
                    source = self.profile['input_source']['/' + '/'.join(parts[4:])]
                    self.assertEqual(source['type'], 'button')
                    self.assertIn(source.get('side'), (None, parts[3]))
                    self.assertIn(item['mode'], ('button', 'complex_button'))
                    for component in item['inputs']:
                        actual = 'click' if item['mode'] == 'complex_button' and component == 'single' else component
                        self.assertIn(actual, ('click', 'touch'))
                        self.assertTrue(source.get(actual), path + '/' + actual)
                for item in group.get('poses', []):
                    self.assertIn(item['path'], ('/user/hand/left/pose/tip', '/user/hand/right/pose/tip'))
                    self.assertEqual(self.profile['input_source']['/pose/tip']['type'], 'pose')

    def test_handed_action_routes(self):
        legacy = self.bindings['neo3_legacy_bindings.json']['bindings']['/actions/legacy']
        for source in legacy['sources']:
            hand = source['path'].split('/')[3]
            for target in source['inputs'].values():
                self.assertTrue(target['output'].startswith('/actions/legacy/in/' + hand + '_'))
        dual = self.bindings['neo3_compositor_bindings.json']['bindings']['/actions/dualanalog']
        for source in dual['sources']:
            hand = source['path'].split('/')[3]
            for target in source['inputs'].values():
                action = target['output'].rsplit('/', 1)[1]
                if source['path'].endswith('/grip'):
                    self.assertEqual(action, 'modeswitch1' if hand == 'left' else 'modeswitch2')
                else:
                    self.assertIn(action, (hand + 'click', hand + 'touch'))

    @unittest.skipUnless(all((RUNTIME / name).is_file() for name in
                             ('vrcompositor_actions.json', 'legacy_actions.json')),
                         'requires cached SteamVR action manifests')
    def test_targets_match_verified_runtime_actions(self):
        contracts = [
            ('neo3_legacy_bindings.json', 'legacy_actions.json',
             '59c6e92b0f22e87d01530010e27cac244ef539de5fbd70cc6adf19c85f35d026'),
            ('neo3_compositor_bindings.json', 'vrcompositor_actions.json',
             '970b2e2dff7d45cdc5ccfae068667cb6049c8dc9d3cd931592cb4cb3d3a673e9')]
        for name, manifest, digest in contracts:
            data = (RUNTIME / manifest).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
            actions = {action['name'].lower(): action['type'] for action in json.loads(data)['actions']}
            for group in self.bindings[name]['bindings'].values():
                for source in group['sources']:
                    for target in source['inputs'].values():
                        self.assertEqual(actions[target['output'].lower()], 'boolean')
                for pose in group.get('poses', []):
                    self.assertEqual(actions[pose['output'].lower()], 'pose')


if __name__ == '__main__':
    unittest.main()
