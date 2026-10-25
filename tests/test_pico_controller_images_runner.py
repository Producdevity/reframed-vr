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
        remote_files, directories, uploads = {}, set(), []
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
                path = tokens[1]
                if path == '/system/lib64/' + manifest['profile']['sdk']['filename']:
                    text = manifest['profile']['sdk']['sha256']
                elif path == '/system/lib64/libminiglog.so':
                    text = '36c5d73e58c7141ac0c34737b558e263eaec80c8cb76f428a1819045dad2f98a'
                elif path in remote_files:
                    text = hashlib.sha256(remote_files[path]).hexdigest()
                else:
                    text, code = 'missing remote input', 1
            elif tokens[0] == 'settings':
                text = '0'
            elif tokens[0] == 'mkdir':
                self.assertEqual(tokens[1:3], ['-m', '700'])
                self.assertTrue(tokens[3].startswith('/data/local/tmp/reframed-image-owner-'))
                self.assertNotIn(tokens[3], directories)
                directories.add(tokens[3])
            elif tokens[0] == 'push':
                local, remote = Path(tokens[1]), tokens[2]
                self.assertIn(str(Path(remote).parent), directories)
                data = local.read_bytes()
                if fault != 'missing_upload':
                    remote_files[remote] = data + (b'corrupt' if fault == 'corrupt_transfer' else b'')
                uploads.append(remote)
            elif tokens[0] == 'chmod':
                self.assertEqual(tokens[1], '700')
                self.assertEqual(set(tokens[2:]), {
                    next(iter(directories)) + '/pico-controller-images',
                    next(iter(directories)) + '/pico-controller-images-public',
                })
                self.assertEqual(len(tokens[2:]), 2)
                self.assertTrue(all(path in remote_files for path in tokens[2:]))
            elif tokens[0] == 'env':
                self.assertEqual(len(remote_files), 3)
                self.assertTrue(all(hashlib.sha256(data).hexdigest() == manifest['artifacts'][Path(path).name]
                                    for path, data in remote_files.items()))
                mode = 'public' if any(p.endswith('pico-controller-images-public') for p in tokens) else tokens[-1]
                text = 'PICO_IMAGE_OWNER_' + mode.upper() + '_PASS'
            elif tokens[0] == 'rm':
                self.assertEqual(tokens[1], '-f')
                if fault == 'cleanup' and tokens[2].endswith('/libpico-controller-images.so'):
                    code = 1
                else:
                    remote_files.pop(tokens[2], None)
            elif tokens[0] == 'rmdir':
                if tokens[1] not in directories or any(path.startswith(tokens[1] + '/') for path in remote_files):
                    code = 1
                else:
                    directories.remove(tokens[1])
            else:
                raise AssertionError('Unexpected adb operation: ' + repr(tokens))
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
            elif fault in ('missing_upload', 'corrupt_transfer'):
                error, message = ((RuntimeError, 'missing remote input') if fault == 'missing_upload'
                                  else (ValueError, 'Transfer differs'))
                with self.assertRaisesRegex(error, message):
                    RUNNER.main()
                self.assertFalse(any(c[3] == 'shell' and shlex.split(c[4])[0] == 'env' for c in calls))
            else:
                RUNNER.main()
        result = json.loads((output/'result.json').read_text())
        self.assertEqual(result['status'], 'passed' if fault is None else 'failed')
        if fault in (None, 'cleanup'):
            self.assertEqual(result['temporary_files_removed'], fault is None)
            self.assertTrue((output/'empty.log').is_file())
            self.assertEqual(len(uploads), 3)
        if fault == 'cleanup':
            self.assertEqual(len(directories), 1)
            self.assertEqual(list(remote_files), [next(iter(directories)) + '/libpico-controller-images.so'])
        else:
            self.assertFalse(remote_files)
            self.assertFalse(directories)

    def test_complete_bundle_and_cleanup_receipt(self):
        for fault in [None, 'cleanup', 'manifest']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                self.run_fixture(Path(temporary), fault)

    def test_rejects_firmware_and_updater_mismatch_before_upload(self):
        for fault in ['ro.product.device', 'ro.build.fingerprint', 'updater']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                self.run_fixture(Path(temporary), fault)

    def test_missing_or_corrupt_remote_uploads_fail_before_execution(self):
        for fault in ['missing_upload', 'corrupt_transfer']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                self.run_fixture(Path(temporary), fault)
