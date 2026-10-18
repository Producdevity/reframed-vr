from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoPanelBacklightTests(unittest.TestCase):
    def test_optional_defaults_and_required_errors(self):
        root = Path(__file__).resolve().parents[1]
        patch = root / "patches/kernel/pico-neo3/0048-panel-backlight-defaults.patch"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            driver = directory / "techpack/display/msm/dsi/dsi_panel.c"
            driver.parent.mkdir(parents=True)
            driver.write_bytes((root / "tests/fixtures/pico-panel-backlight.inc").read_bytes())
            for original in (True, False):
                if not original:
                    subprocess.run([
                        "patch", "--batch", "--fuzz=0", "--forward", "-p1", "-i", str(patch),
                    ], cwd=directory, check=True, capture_output=True, timeout=15)
                function = driver.read_text().split("\nvoid dsi_dsc_pclk_param_calc", 1)[0]
                (directory / "driver.inc").write_text(function)
                executable = directory / "backlight"
                subprocess.run([
                    "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", temp,
                    *(["-DEXPECT_OLD"] if original else []),
                    str(root / "tests/pico-panel-backlight.c"), "-o", str(executable),
                ], check=True, capture_output=True, timeout=30)
                result = subprocess.run([str(executable)], check=True, capture_output=True,
                                        text=True, timeout=15)
                if not original:
                    self.assertIn("0 default defects", result.stdout)
