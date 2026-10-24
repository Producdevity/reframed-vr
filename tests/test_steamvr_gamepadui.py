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
            gamescope.write_text('#!/usr/bin/env bash\nset -eu\n'
                                 'while [[ "$1" != -- ]]; do shift; done\nshift\nexec "$@"\n')
            gamescope.chmod(0o700)
            runtime = root/'runtime/bin/linuxarm64'
            runtime.mkdir(parents=True)
            (runtime/'vrclient.so').touch()
            arguments = root/'arguments'
            subprocess.run(['bash', str(launcher), '-cef-disable-gpu'], check=True, timeout=5,
                           env=os.environ | {'VR_OVERRIDE': str(root/'runtime'),
                                             'REFRAMED_GAMESCOPE_BIN': str(gamescope),
                                             'FIXTURE_ARGUMENTS': str(arguments)})
            self.assertEqual(arguments.read_text().splitlines(),
                             ['-gamepadui', '-vrgamepadui', '-cef-disable-gpu'])
