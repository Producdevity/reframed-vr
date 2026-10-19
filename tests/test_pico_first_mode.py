from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("techpack/display/msm/dsi/dsi_drm.c")


class PicoFirstModeTests(unittest.TestCase):
    def test_first_frame_rejection_and_valid_transitions(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / SOURCE
            source.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/fixtures/pico-first-mode" / SOURCE, source)
            for variant in ("original", "fixed"):
                if variant == "fixed":
                    subprocess.run([
                        "patch", "--batch", "--fuzz=0", "--forward", "-p1", "-i",
                        str(ROOT / "patches/kernel/pico-neo3-linux/0010-dsi-first-mode-validation.patch")
                    ], cwd=directory, check=True, capture_output=True, timeout=10)
                includes = directory / variant
                includes.mkdir()
                shutil.copy2(source, includes / "mode-fixup.inc")
                binary = directory / ("test-" + variant)
                subprocess.run([
                    "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(includes), str(ROOT / "tests/pico-first-mode.c"), "-o", str(binary)
                ], check=True, capture_output=True, timeout=30)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                match = re.fullmatch(
                    r"PICO_FIRST_MODE_(PASS|FAIL) cases=(\d+) checks=(\d+) failures=(\d+)\n",
                    result.stdout)
                self.assertIsNotNone(match, result.stdout + result.stderr)
                self.assertEqual(int(match[2]), 3072)
                self.assertEqual(int(match[3]), 9216)
                if variant == "original":
                    self.assertEqual(result.returncode, 1)
                    self.assertGreater(int(match[4]), 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(int(match[4]), 0)


if __name__ == "__main__":
    unittest.main()
