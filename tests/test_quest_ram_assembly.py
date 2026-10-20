import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('quest_ram', ROOT / 'tools/assemble-quest-ram.py')
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)
from devicetree import boot_memory, read_fdt


def image(extent=13 * 1024**2):
    data = bytearray(4096)
    struct.pack_into('<QQQ', data, 8, 0, extent, 0xa)
    data[56:60] = b'ARM\x64'
    return data


def allocation():
    starts = [0x90000000, 0x90400000] + [0x800000000 + i * assembly.BANK for i in range(22)]
    return {'image_start': '840000000', 'image_bytes': assembly.CAPACITY,
            'heap': [{'start': f'{start:x}', 'bytes': assembly.BANK} for start in starts]}


class LayoutTests(unittest.TestCase):
    def test_above_4g_and_low_dma_banks(self):
        base, banks = assembly.owned_banks(allocation())
        self.assertEqual(base, 0x840000000)
        self.assertEqual(sum(size for _, size in banks), 112 * 1024**2)

    def test_overlap_rejected(self):
        info = allocation()
        info['heap'][3]['start'] = info['image_start']
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            assembly.owned_banks(info)

    def test_high_dma_bank_rejected(self):
        info = allocation()
        info['heap'][0]['start'] = '880000000'
        with self.assertRaisesRegex(ValueError, 'low DMA'):
            assembly.owned_banks(info)

    def test_extent_and_payload_bounds(self):
        plan = assembly.layout(image(), 1024**2, 700000)
        self.assertEqual(plan['initrd_offset'], 13 * 1024**2)
        with self.assertRaisesRegex(ValueError, 'exceed'):
            assembly.layout(image(15 * 1024**2), 1024**2, 700000)

    def test_physical_placement_contract_required(self):
        data = image()
        struct.pack_into('<Q', data, 24, 2)
        with self.assertRaisesRegex(ValueError, 'arbitrary-placement'):
            assembly.layout(data, 1024, 1024)


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtput'), 'requires device-tree tools')
class TreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.target = self.root / 'source.dtb', self.root / 'target.dtb'
        tree = '''/dts-v1/;
        /memreserve/ 0x82100000 0x1000;
        / {
          compatible = "oculus,eureka", "qcom,anorak";
          #address-cells = <2>; #size-cells = <2>;
          memory@80000000 { device_type = "memory"; reg = <0 0x80000000 0 0x40000000>; };
          memory@800000000 { device_type = "memory"; reg = <8 0 1 0>; };
          chosen { bootargs = "old-android-arguments"; kaslr-seed = <1 2>; };
          reserved-memory {
            #address-cells = <2>; #size-cells = <2>; ranges;
            fixed@82000000 { reg = <0 0x82000000 0 0x100000>; no-map; };
            linux,cma { compatible = "shared-dma-pool"; reusable; size = <0 0x2000000>; };
          };
          soc {
            ssusb@a600000 {
              compatible = "qcom,dwc-usb3-msm"; usb-role-switch;
              dwc3@a600000 { compatible = "snps,dwc3"; dr_mode = "otg";
                maximum-speed = "super-speed"; usb-role-switch; };
            };
          };
        };'''
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(self.source)],
                       input=tree, text=True, capture_output=True, check=True)

    def test_restrict_ram_preserve_reservations_and_fix_usb(self):
        before = boot_memory(self.source.read_bytes())
        data, plan, disabled = assembly.prepare_dtb(self.source, self.target, allocation(), image(), b'initrd')
        after, nodes = boot_memory(data), read_fdt(data)
        self.assertEqual(after['reserved'], before['reserved'])
        self.assertTrue(after['fixed_memory_map_complete'])
        self.assertEqual(sum(entry['size'] for entry in after['ram']), 112 * 1024**2)
        self.assertEqual(disabled, ['/reserved-memory/linux,cma'])
        self.assertEqual(nodes[assembly.USB_CHILD]['dr_mode'], b'peripheral\0')
        self.assertNotIn('usb-role-switch', nodes[assembly.USB_PARENT])
        self.assertNotIn('usb-role-switch', nodes[assembly.USB_CHILD])
        chosen = nodes['/chosen']
        self.assertNotIn('kaslr-seed', chosen)
        self.assertNotIn(b'old-android', chosen['bootargs'])
        self.assertEqual(int.from_bytes(chosen['linux,initrd-start'], 'big'),
                         0x840000000 + plan['initrd_offset'])

    def test_fixed_reserved_overlap_rejected(self):
        info = allocation()
        info['heap'][0]['start'] = '82000000'
        with self.assertRaisesRegex(ValueError, 'firmware reservation'):
            assembly.prepare_dtb(self.source, self.target, info, image(), b'initrd')

    def test_non_ram_bank_rejected(self):
        info = allocation()
        info['image_start'] = 'a40000000'
        with self.assertRaisesRegex(ValueError, 'outside'):
            assembly.prepare_dtb(self.source, self.target, info, image(), b'initrd')


if __name__ == '__main__':
    unittest.main()
