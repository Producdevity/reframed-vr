import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery_assembly', ROOT / 'tools/assemble-pico-boot.py')
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)


class PicoRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.serial, self.cmdline, self.compatible = (directory / n for n in ('serial', 'cmdline', 'compatible'))
        self.serial.write_text('c980c8d4\n')
        self.arguments = ('root=LABEL=linux reframed.pico=qrtr '
                          'androidboot.serialno=c980c8d4 reframed.pico.recovery=fastboot\n')
        self.cmdline.write_text(self.arguments)
        self.board = b'qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0'
        self.compatible.write_bytes(self.board)

    def identity(self):
        result = subprocess.run([
            'bash', '-c', 'source "$1"; pico_recovery_identity "$2" "$3" "$4"',
            'identity-test', str(ROOT / 'system/pico/reframed-pico-recover'),
            str(self.serial), str(self.cmdline), str(self.compatible),
        ], text=True, capture_output=True, timeout=10)
        return result.returncode

    def test_exact_physical_identity(self):
        self.assertEqual(self.identity(), 0)

    def test_missing_wrong_and_duplicate_tokens_refused(self):
        for wanted in ('reframed.pico=qrtr', 'androidboot.serialno=c980c8d4',
                       'reframed.pico.recovery=fastboot'):
            for altered in (self.arguments.replace(wanted, ''), self.arguments.rstrip() + ' ' + wanted + '\n',
                            self.arguments.replace(wanted, wanted + 'other')):
                with self.subTest(wanted=wanted, altered=altered):
                    self.cmdline.write_text(altered)
                    self.assertNotEqual(self.identity(), 0)
        self.cmdline.write_text(self.arguments + 'extra\n')
        self.assertNotEqual(self.identity(), 0)

    def test_other_board_and_virtual_or_malformed_serial_refused(self):
        for board in (b'qcom,kona\0', self.board + b'extra\0', b'qcom,mtp\0qcom,kona-iot\0qcom,kona-iot-mtp\0'):
            with self.subTest(board=board):
                self.compatible.write_bytes(board)
                self.assertNotEqual(self.identity(), 0)
        self.compatible.write_bytes(self.board)
        for serial in ('qemu\n', 'another-unit\n', 'c980c8d4\nextra\n', 'invalid value\n', ''):
            with self.subTest(serial=serial):
                self.serial.write_text(serial)
                self.assertNotEqual(self.identity(), 0)

    def test_probe_is_distinct_and_keeps_recovery_timeouts(self):
        cmdline = assembly.assembly.root_arguments('linux', pico_services=True)
        probe = assembly.recovery_arguments(cmdline, 'c980c8d4', True)
        self.assertIn('root=LABEL=reframed-missing', probe.split())
        self.assertNotIn('root=LABEL=linux', probe.split())
        self.assertIn('rd.shell=0', probe.split())
        self.assertIn('rd.emergency=reboot', probe.split())
        self.assertIn('msm_drm.modeset=0', probe.split())
        self.assertIn('reframed.pico.recovery=fastboot', probe.split())
        for serial in ('qemu', 'bad serial'):
            with self.assertRaises(ValueError):
                assembly.recovery_arguments(cmdline, serial, True)
        with self.assertRaises(ValueError):
            assembly.recovery_arguments(probe, 'c980c8d4', True)
