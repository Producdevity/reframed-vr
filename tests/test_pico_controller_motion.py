from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerMotionTests(unittest.TestCase):
    def test_stock_units_and_clock_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "pico-controller-motion"
            subprocess.run([
                "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I", str(root / "src"),
                str(root / "tests/pico-controller-motion.c"),
                str(root / "src/pico-controller-motion.c"), str(root / "src/ssc-clock.c"),
                "-o", str(executable),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(executable)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn("PICO_CONTROLLER_MOTION_PASS", result.stdout)
