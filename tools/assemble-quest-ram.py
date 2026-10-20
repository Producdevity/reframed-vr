#!/usr/bin/env python3
"""Pack a Quest 3 RAM-only Image/initramfs/DTB; never contact a device."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from devicetree import boot_memory, read_fdt, string_list

BANK = 4 * 1024**2
CAPACITY = 4 * BANK
USB_PARENT = '/soc/ssusb@a600000'
USB_CHILD = USB_PARENT + '/dwc3@a600000'
COMMAND_LINE = ('rdinit=/init nokaslr maxcpus=1 cma=0 swiotlb=1024 panic=1 '
                'loglevel=7 ignore_loglevel printk.devkmsg=on reframed.ram_usb=1')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def owned_banks(info):
    def address(value):
        if not isinstance(value, str):
            raise ValueError('Expected a hexadecimal physical address')
        result = int(value, 16)
        if result < 0 or result >= 1 << 39 or result % BANK:
            raise ValueError('Unsupported or unaligned physical bank')
        return result

    if info.get('image_bytes') != CAPACITY or len(info.get('heap', [])) != 24:
        raise ValueError('Requires a resident 16 MiB Image region and 24 heap banks')
    image = address(info['image_start'])
    banks = [(image, CAPACITY)]
    for index, entry in enumerate(info['heap']):
        start = address(entry['start'])
        if entry['bytes'] != BANK or (index < 2 and start + BANK > 1 << 32):
            raise ValueError('Invalid heap or low DMA bank')
        banks.append((start, BANK))
    ordered = sorted(banks)
    if any(left + size > right for (left, size), (right, _) in zip(ordered, ordered[1:])):
        raise ValueError('Overlapping owned banks')
    if any(start + size > 1 << 39 for start, size in banks):
        raise ValueError('Bank exceeds the supported physical range')
    return image, ordered


def layout(image, initrd_bytes, dtb_bytes):
    if len(image) < 64 or image[56:60] != b'ARM\x64':
        raise ValueError('Requires a raw ARM64 Image')
    offset, extent, flags = struct.unpack_from('<QQQ', image, 8)
    if offset or flags != 0xa or not len(image) <= extent <= CAPACITY:
        raise ValueError('Requires a 4 KiB arbitrary-placement Image with text_offset=0')
    if not 0 < initrd_bytes <= CAPACITY or not 40 <= dtb_bytes <= 2 * 1024**2:
        raise ValueError('Invalid initramfs/DTB size')
    initrd = (extent + 4095) & ~4095
    dtb = (initrd + initrd_bytes + 4095) & ~4095
    if dtb + dtb_bytes > CAPACITY:
        raise ValueError('Image, initramfs and DTB exceed the owned Image region')
    return {'image_extent': extent, 'initrd_offset': initrd, 'dtb_offset': dtb,
            'used_bytes': dtb + dtb_bytes}


def prepare_dtb(source, target, info, image, initrd):
    data = source.read_bytes()
    nodes = read_fdt(data)
    compatible = string_list(nodes['/'].get('compatible', b''))
    if not {'oculus,eureka', 'qcom,anorak'} <= set(compatible):
        raise ValueError('Requires the current Quest 3 Eureka/Anorak tree')
    if any(nodes['/'].get(key) != struct.pack('>I', 2)
           for key in ('#address-cells', '#size-cells')):
        raise ValueError('Requires two-cell root addresses and sizes')
    for path, expected in ((USB_PARENT, 'qcom,dwc-usb3-msm'), (USB_CHILD, 'snps,dwc3')):
        if expected not in string_list(nodes.get(path, {}).get('compatible', b'')):
            raise ValueError('Unexpected USB topology')
    base, banks = owned_banks(info)
    memory = boot_memory(data)
    for start, size in banks:
        if not any(entry['start'] <= start and start + size <= entry['start'] + entry['size']
                   for entry in memory['ram']):
            raise ValueError('Owned bank is outside the captured stock RAM map')
        if any(start < entry['start'] + entry['size'] and entry['start'] < start + size
               for entry in memory['reserved']):
            raise ValueError('Owned bank overlaps a firmware reservation')
    shutil.copyfile(source, target)

    def put(*args):
        subprocess.run(['fdtput', *args[:2], str(target), *args[2:]], check=True,
                       capture_output=True, timeout=10)

    def prop(path, name, value):
        put('-t', 's', path, name, value)

    def cells(path, name, values):
        put('-t', 'x', path, name, *(f'{value:x}' for value in values))

    for path, props in nodes.items():
        if props.get('device_type') == b'memory\0':
            if path.count('/') != 1:
                raise ValueError('Unsupported non-root memory node')
            subprocess.run(['fdtput', '-r', str(target), path], check=True, capture_output=True)
    path = f'/memory@{banks[0][0]:x}'
    subprocess.run(['fdtput', '-c', str(target), path], check=True, capture_output=True)
    prop(path, 'device_type', 'memory')
    cells(path, 'reg', [cell for start, size in banks for value in (start, size)
                        for cell in (value >> 32, value & 0xffffffff)])
    disabled = []
    for entry in memory['dynamic_reservations']:
        prop(entry['path'], 'status', 'disabled')
        disabled.append(entry['path'])
    for path in (USB_PARENT, USB_CHILD):
        for name in ('usb-role-switch', 'extcon', 'io-channels', 'io-channel-names', 'usb-psy-name'):
            if name in nodes[path]:
                subprocess.run(['fdtput', '-d', str(target), path, name], check=True, capture_output=True)
    prop(USB_CHILD, 'dr_mode', 'peripheral')
    prop(USB_CHILD, 'maximum-speed', 'high-speed')
    prop('/chosen', 'bootargs', COMMAND_LINE)
    for name in ('linux,usable-memory-range', 'linux,elfcorehdr', 'kaslr-seed', 'rng-seed',
                 'linux,uefi-mmap-start', 'linux,uefi-mmap-size', 'linux,uefi-system-table'):
        if name in nodes.get('/chosen', {}):
            subprocess.run(['fdtput', '-d', str(target), '/chosen', name], check=True, capture_output=True)
    plan = layout(image, len(initrd), target.stat().st_size)
    start = base + plan['initrd_offset']
    cells('/chosen', 'linux,initrd-start', [start >> 32, start & 0xffffffff])
    end = start + len(initrd)
    cells('/chosen', 'linux,initrd-end', [end >> 32, end & 0xffffffff])
    result = target.read_bytes()
    plan = layout(image, len(initrd), len(result))
    after = boot_memory(result)
    if (sorted((entry['start'], entry['size']) for entry in after['ram']) != banks or
            after['reserved'] != memory['reserved'] or not after['fixed_memory_map_complete']):
        raise ValueError('Final DT memory map differs from the owned banks/reservations')
    return result, plan, disabled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('info', 'image', 'initramfs', 'dtb', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output must be a new directory')
    info = json.loads(args.info.read_text())
    image, initrd = args.image.read_bytes(), args.initramfs.read_bytes()
    if not initrd.startswith(b'\x1f\x8b'):
        raise ValueError('Requires a gzip-compressed native initramfs')
    args.output.mkdir(parents=True)
    dtb, plan, disabled = prepare_dtb(args.dtb, args.output / 'target.dtb', info, image, initrd)
    payload = bytearray(CAPACITY)
    payload[:len(image)] = image
    for start, data in ((plan['initrd_offset'], initrd), (plan['dtb_offset'], dtb)):
        payload[start:start + len(data)] = data
    (args.output / 'payload.bin').write_bytes(payload)
    base, banks = owned_banks(info)
    report = {'status': 'assembled', 'device_actions': [], 'hardware_boot_verified': False,
              'ownership_must_be_rechecked_live': True, 'image_start': hex(base),
              'banks': [{'start': hex(start), 'bytes': size} for start, size in banks],
              'dtb_start': hex(base + plan['dtb_offset']), 'layout': plan,
              'disabled_dynamic_reservations': disabled, 'command_line': COMMAND_LINE,
              'inputs_sha256': {name: digest(getattr(args, name).read_bytes())
                                for name in ('info', 'image', 'initramfs', 'dtb')},
              'artifacts': {name: {'bytes': len(data), 'sha256': digest(data)}
                            for name, data in (('target.dtb', dtb), ('payload.bin', payload))}}
    (args.output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(args.output / 'manifest.json')


if __name__ == '__main__':
    main()
