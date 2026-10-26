from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoControllerHeadTests(unittest.TestCase):
    def test_bracketing_loss_recovery_and_ring_lifetime(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "pico-controller-head"
            subprocess.run([
                "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-I", str(root / "src"), str(root / "tests/pico-controller-head.c"),
                str(root / "src/pico-controller-head.c"), str(root / "src/pico-slam-result.c"),
                "-lm", "-o", str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertIn("PICO_CONTROLLER_HEAD_PASS", result.stdout)
