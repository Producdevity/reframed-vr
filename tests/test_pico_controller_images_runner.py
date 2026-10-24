import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('image_runner', ROOT/'tools/test-pico-controller-images.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class ImageRunnerTests(unittest.TestCase):
    def fixture(self, root):
        source, bundle, output = root/'source', root/'bundle', root/'result'
        profile = json.loads((ROOT/'profiles/pico-controller-images.json').read_text())
        hashes = {}
        for name in RUNNER.EXPECTED_INPUTS:
            path = source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(profile) if name.endswith('.json') else 'fixture input')
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        bundle.mkdir()
        artifacts = {}
        for name in ['pico-controller-images', 'pico-controller-images-public', 'libpico-controller-images.so']:
            (bundle/name).write_bytes(name.encode())
            artifacts[name] = hashlib.sha256((bundle/name).read_bytes()).hexdigest()
        manifest = {'status': 'compiled', 'profile': profile, 'source_sha256': hashes, 'artifacts': artifacts}
        (bundle/'build.json').write_text(json.dumps(manifest))
        return source, bundle, output, manifest

    def run_fixture(self, root, fault=None):
        source, bundle, output, manifest = self.fixture(root)
        calls = []
        if fault == 'manifest':
            manifest['source_sha256'].pop('src/pico-controller-images.cpp')
            (bundle/'build.json').write_text(json.dumps(manifest))

        def adb(command, **kwargs):
            calls.append(command)
            tokens = shlex.split(command[4]) if command[3] == 'shell' else command[3:]
            text, code = '', 0
            if tokens[0] == 'getprop':
                text = {'ro.serialno': 'fixture', 'ro.product.device': 'PICOA7H10',
                        'ro.build.fingerprint': RUNNER.FINGERPRINT}[tokens[1]]
                if fault == tokens[1]:
                    text = 'wrong device or firmware'
            elif tokens[0] == 'cat':
                text = '11111111-1111-4111-8111-111111111111'
            elif tokens[0] == 'pm':
                text = '' if fault == 'updater' else 'package:com.picovr.updatesystem'
            elif tokens[0] == 'sha256sum':
                name = tokens[1].rsplit('/', 1)[-1]
                text = (manifest['profile']['sdk']['sha256'] if name.endswith('.pxr.so') else
                        '36c5d73e58c7141ac0c34737b558e263eaec80c8cb76f428a1819045dad2f98a'
                        if name == 'libminiglog.so' else manifest['artifacts'][name]) + '  file'
            elif tokens[0] == 'settings':
                text = '0'
            elif tokens[0] == 'env':
                mode = 'public' if any(p.endswith('pico-controller-images-public') for p in tokens) else tokens[-1]
                text = 'PICO_IMAGE_OWNER_' + mode.upper() + '_PASS'
            elif tokens[0] == 'rmdir' and fault == 'cleanup':
                code = 1
            return subprocess.CompletedProcess(command, code, text+'\n', '')

        argv = ['runner', '--serial', 'fixture', '--bundle', str(bundle), '--output', str(output)]
        with patch.object(RUNNER, 'ROOT', source), patch.object(sys, 'argv', argv), \
                patch.object(RUNNER.subprocess, 'run', side_effect=adb):
            if fault == 'manifest':
                with self.assertRaises(SystemExit):
                    RUNNER.main()
                self.assertFalse(calls)
                return
            if fault in ['ro.product.device', 'ro.build.fingerprint', 'updater']:
                with self.assertRaises(ValueError):
                    RUNNER.main()
                self.assertFalse(any(c[3] == 'push' for c in calls))
            elif fault == 'cleanup':
                with self.assertRaisesRegex(RuntimeError, 'Temporary probe files'):
                    RUNNER.main()
            else:
                RUNNER.main()
        result = json.loads((output/'result.json').read_text())
        self.assertEqual(result['status'], 'passed' if fault is None else 'failed')
        if fault in (None, 'cleanup'):
            self.assertEqual(result['temporary_files_removed'], fault is None)
            self.assertTrue((output/'empty.log').is_file())

    def test_complete_bundle_and_cleanup_receipt(self):
        for fault in [None, 'cleanup', 'manifest']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                self.run_fixture(Path(temporary), fault)

    def test_rejects_firmware_and_updater_mismatch_before_upload(self):
        for fault in ['ro.product.device', 'ro.build.fingerprint', 'updater']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                self.run_fixture(Path(temporary), fault)
