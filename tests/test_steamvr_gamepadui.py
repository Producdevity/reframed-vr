import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SteamVRGamepadUiTests(unittest.TestCase):
    def test_source_launcher_executes_non_executable_child_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = root/'steamvr-gamepadui.sh'
            shutil.copyfile(ROOT/'tools/steamvr-gamepadui.sh', launcher)
            child = root/'desktop-steam.sh'
            child.write_text('printf "%s\\n" "$@" > "$FIXTURE_ARGUMENTS"\n')
            child.chmod(0o600)
            gamescope = root/'gamescope'
            gamescope.write_text('#!/usr/bin/env bash\nset -eu\nprintf "%s\\n" "$@" > "$FIXTURE_GAMESCOPE"\n'
                                 'while [[ "$1" != -- ]]; do shift; done\nshift\nexec "$@"\n')
            gamescope.chmod(0o700)
            runtime = root/'runtime/bin/linuxarm64'
            runtime.mkdir(parents=True)
            (runtime/'vrclient.so').touch()
            arguments, gamescope_arguments = root/'arguments', root/'gamescope-arguments'
            environment = os.environ | {'VR_OVERRIDE': str(root/'runtime'),
                                        'REFRAMED_GAMESCOPE_BIN': str(gamescope),
                                        'FIXTURE_ARGUMENTS': str(arguments),
                                        'FIXTURE_GAMESCOPE': str(gamescope_arguments)}
            environment.pop('REFRAMED_GAMESCOPE_REFRESH', None)
            subprocess.run(['bash', str(launcher), '-cef-disable-gpu'], check=True, timeout=5, env=environment)
            self.assertEqual(arguments.read_text().splitlines(),
                             ['-gamepadui', '-vrgamepadui', '-cef-disable-gpu'])
            refresh = gamescope_arguments.read_text().splitlines()
            self.assertEqual(refresh[refresh.index('-r') + 1], '90')
            subprocess.run(['bash', str(launcher)], check=True, timeout=5,
                           env=environment | {'REFRAMED_GAMESCOPE_REFRESH': '60'})
            refresh = gamescope_arguments.read_text().splitlines()
            self.assertEqual(refresh[refresh.index('-r') + 1], '60')
            for invalid in ('29', '121', '60.5', 'x'):
                result = subprocess.run(['bash', str(launcher)], capture_output=True, timeout=5,
                                        env=environment | {'REFRAMED_GAMESCOPE_REFRESH': invalid})
                self.assertEqual(result.returncode, 1, invalid)
