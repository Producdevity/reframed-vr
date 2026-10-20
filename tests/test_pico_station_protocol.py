from pathlib import Path
import subprocess
import tempfile
import unittest


class PicoStationProtocolTests(unittest.TestCase):
    def test_packets_and_invalid_inputs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "pico-station-protocol"
            subprocess.run([
                "cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-I", str(root / "src"), str(root / "tests/pico-station-protocol.c"),
                str(root / "src/pico-station-protocol.c"), "-o", str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("PICO_STATION_PROTOCOL_PASS", result.stdout)
