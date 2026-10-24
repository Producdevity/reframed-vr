import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pico_steamvr_build', ROOT / 'tools/build-pico-steamvr.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class PicoSteamvrBuildTests(unittest.TestCase):
    def test_failed_probe_leaves_no_bundle_and_retry_records_all_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'LICENSE').write_text('fixture dependency license')
            (root / 'cJSON.h').write_text('/* fixture license */')
            output = root / 'bundle'

            def compile(command, **_):
                target = Path(command[-1])
                if target.name == 'pico-steamvr-live' and failed[0]:
                    raise subprocess.CalledProcessError(1, command)
                target.write_bytes(b'fixture compiler output')

            failed = [True]
            argv = ['build', '--output', str(output), '--sdk', str(root), '--cjson', str(root)]
            with patch.object(sys, 'argv', argv), patch.object(BUILD.platform, 'system', return_value='Linux'), \
                    patch.object(BUILD.platform, 'machine', return_value='aarch64'), \
                    patch.object(BUILD, 'verify'), patch.object(BUILD.subprocess, 'run', side_effect=compile):
                with self.assertRaises(subprocess.CalledProcessError):
                    BUILD.main()
                self.assertFalse(output.exists())
                failed[0] = False
                BUILD.main()
            record = json.loads((output / 'build.json').read_text())
            for resource in (ROOT / 'system/steamvr-pico/resources').rglob('*'):
                if resource.is_file():
                    source = str(resource.relative_to(ROOT))
                    packaged = str(resource.relative_to(ROOT / 'system/steamvr-pico'))
                    self.assertEqual(record['source_sha256'][source],
                                     record['files_sha256']['reframed_pico/' + packaged])
