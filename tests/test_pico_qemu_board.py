import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pico_qemu_board', Path(__file__).parents[1] / 'tools/prepare-pico-qemu-board.py')
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


@unittest.skipUnless(all(shutil.which(name) for name in ('dtc', 'fdtget', 'fdtput')), 'requires device-tree tools')
class PicoQemuBoardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / 'board.dts'
        source.write_text('''/dts-v1/;
/ {
    compatible = "linux,dummy-virt";
    marker = <0x1234>;
    cpus {
        #address-cells = <1>;
        #size-cells = <0>;
        cpu0: cpu@0 { device_type = "cpu"; reg = <0>; };
        cpu1: cpu@1 { device_type = "cpu"; reg = <1>; };
        cpu-map { socket0 { cluster0 {
            core0 { cpu = <&cpu0>; };
            core1 { cpu = <&cpu1>; };
        }; }; };
    };
};
''')
        self.dtb = self.root / 'board.dtb'
        subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', str(self.dtb), str(source)], check=True)

    def test_socket_wrapper_is_flattened_without_other_property_changes(self):
        before = board.properties(self.dtb)
        result = board.prepare(self.dtb)
        after = board.properties(self.dtb)
        self.assertTrue(result['socket_wrapper_removed'])
        self.assertTrue(result['all_properties_outside_cpu_map_unchanged'])
        self.assertEqual(after['/']['marker'], before['/']['marker'])
        self.assertEqual(after['/cpus/cpu@0'], before['/cpus/cpu@0'])
        self.assertEqual(after['/cpus/cpu-map/cluster0/core1'], before['/cpus/cpu-map/socket0/cluster0/core1'])
        self.assertNotIn('/cpus/cpu-map/socket0', after)

    def test_prepared_board_is_idempotent(self):
        board.prepare(self.dtb)
        before = self.dtb.read_bytes()
        result = board.prepare(self.dtb)
        self.assertFalse(result['socket_wrapper_removed'])
        self.assertEqual(self.dtb.read_bytes(), before)

    def test_physical_board_is_refused_before_mutation(self):
        subprocess.run(['fdtput', '-t', 's', str(self.dtb), '/', 'compatible', 'pico,neo3'], check=True)
        before = self.dtb.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Only the linux,dummy-virt'):
            board.prepare(self.dtb)
        self.assertEqual(self.dtb.read_bytes(), before)

    def test_inconsistent_cpu_map_is_refused_before_mutation(self):
        phandle = board.command('fdtget', '-t', 'x', str(self.dtb), '/cpus/cpu@0', 'phandle')
        subprocess.run(['fdtput', '-t', 'x', str(self.dtb), '/cpus/cpu-map/socket0/cluster0/core1', 'cpu', phandle], check=True)
        before = self.dtb.read_bytes()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            board.prepare(self.dtb)
        self.assertEqual(self.dtb.read_bytes(), before)
