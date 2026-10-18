#!/usr/bin/env python3
"""Assemble a matching Pico Linux runtime boot container without device access."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnostic_assembly', ROOT / 'tools/assemble-pico-diagnostic.py')
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)
assembly = diagnostic.assembly
container = diagnostic.container
digest = diagnostic.digest
regular = diagnostic.regular
RECOVERY_SOURCES = ('reframed-pico-recover', '20-pico-recovery.sh')
RECOVERY_AUGMENT = r'''
set -euo pipefail
mkdir /tmp/rd
cd /tmp/rd
lsinitrd --unpack /baseline/initramfs.img
test -x usr/bin/bash && test -x usr/bin/systemctl
mkdir -p usr/libexec usr/lib/dracut/hooks/shutdown-emergency etc/reframed-vr
install -m 0755 /source/reframed-pico-recover usr/libexec/reframed-pico-recover
install -m 0755 /source/20-pico-recovery.sh usr/lib/dracut/hooks/shutdown-emergency/20-pico-recovery.sh
install -m 0600 /output/pico-boot-serial etc/reframed-vr/pico-boot-serial
find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --reproducible --owner=0:0 | gzip -n -9 > /output/initramfs-recovery.img
find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /output/initramfs-recovery-contents.sha256
'''


def recovery_arguments(cmdline, serial, probe=False):
    diagnostic.diagnostic.serial(serial)
    if 'reframed.pico=qrtr' not in cmdline.split() or 'reframed.pico.recovery=' in cmdline:
        raise ValueError('Recovery requires an unmodified Pico runtime command line')
    if probe:
        tokens = cmdline.split()
        roots = [i for i, token in enumerate(tokens) if token.startswith('root=')]
        if len(roots) != 1 or tokens[roots[0]] == 'root=LABEL=reframed-missing':
            raise ValueError('Recovery probe requires a distinct known root')
        tokens[roots[0]] = 'root=LABEL=reframed-missing'
        cmdline = ' '.join(tokens) + ' msm_drm.modeset=0'
    return cmdline + ' reframed.pico.recovery=fastboot'


def augment_recovery(initrd, output, image, serial, engine):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Recovery augmentation requires an immutable ARM64 image ID')
    metadata = json.loads(subprocess.check_output([engine, 'image', 'inspect', image], text=True, timeout=30))[0]
    if metadata.get('Architecture') != 'arm64':
        raise ValueError('Recovery augmentation requires an ARM64 image')
    (output / 'pico-boot-serial').write_text(serial + '\n')
    (output / 'pico-boot-serial').chmod(0o600)
    command = [engine, 'run', '--rm', '--network', 'none', '--memory', '1g', '--cpus', '2',
               '-v', f'{initrd}:/baseline:ro', '-v', f'{output}:/output',
               '-v', f'{ROOT / "system/pico"}:/source:ro', '--entrypoint', 'bash', image,
               '-c', RECOVERY_AUGMENT]
    with (output / 'recovery-augment.log').open('xb') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    return command


def receipt(directory, name, required, limit):
    regular(directory / name, 4 * 1024**2)
    report = json.loads((directory / name).read_text())
    entries = report['artifacts']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 256:
        raise ValueError('Invalid artifact inventory')
    checked = {}
    for item in entries:
        path = item['path']
        if not isinstance(path, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', path) or path in checked:
            raise ValueError('Unsafe or repeated artifact path')
        regular(directory / path, limit if path == 'rootfs.ext4' else 128 * 1024**2)
        if (type(item['bytes']) is not int or (directory / path).stat().st_size != item['bytes'] or
                digest(directory / path) != item['sha256']):
            raise ValueError('Artifact changed: ' + path)
        checked[path] = item['sha256']
    if not required <= checked.keys():
        raise ValueError('Missing required artifacts')
    return report, checked


def root_label(image, expected):
    assembly.root_arguments(expected, pico_services=True)
    with image.open('rb') as stream:
        stream.seek(1024)
        sb = stream.read(1024)
    if len(sb) != 1024 or sb[56:58] != b'\x53\xef':
        raise ValueError('Root image is not ext4')
    shift = struct.unpack_from('<I', sb, 24)[0]
    blocks = struct.unpack_from('<I', sb, 4)[0]
    if struct.unpack_from('<I', sb, 96)[0] & 0x80:
        blocks |= struct.unpack_from('<I', sb, 336)[0] << 32
    if (shift > 6 or blocks * (1024 << shift) != image.stat().st_size or
            sb[120:136].rstrip(b'\0') != expected.encode('ascii')):
        raise ValueError('Root image label or geometry differs from its receipt')


def runtime_inputs(kernel, initrd, root, root_manifest_sha256):
    regular(root / 'manifest.json', 4 * 1024**2)
    if (not re.fullmatch(r'[0-9a-f]{64}', root_manifest_sha256) or
            digest(root / 'manifest.json') != root_manifest_sha256):
        raise ValueError('Root manifest checksum differs from the retained verification receipt')
    hashes = diagnostic.diagnostic.kernel_input(kernel)
    kernel_sha = digest(kernel / 'build.json')
    rd, rd_hashes = receipt(initrd, 'build.json', {'initramfs.img', 'contents.json'}, 128 * 1024**2)
    root_record, root_hashes = receipt(root, 'manifest.json', {'rootfs.ext4', 'contents.json', 'root-profile.json'}, 128 * 1024**3)
    for record in (rd, root_record):
        if (record.get('status') != 'built' or record.get('qemu_transports') is not False or
                record.get('kernel_variant') != 'linux-userspace' or
                record.get('kernel_build_sha256') != kernel_sha or record.get('kernel_inputs_sha256') != hashes or
                record.get('hardware_boot_verified') is not False or record.get('hardware_flash_image') is not False or
                record.get('pico_services') is not True or record.get('quest_services', False) is not False or
                not record.get('systemd_runtime_sha256')):
            raise ValueError('Requires matching physical Pico kernel, root and startup initramfs')
    if (root_record.get('profile') != 'pico-neo3' or root_record.get('target') != 'headset-root-offline' or
            root_record.get('initramfs_sha256') != rd_hashes['initramfs.img'] or
            not rd.get('firmware') or root_record.get('firmware') != rd['firmware'] or
            root_record.get('sha256') != root_hashes or
            rd.get('pico_inputs_sha256') != {name: digest(ROOT / name) for name in assembly.builder.PICO_INPUTS}):
        raise ValueError('Root, firmware or Pico startup inputs differ')
    contents = json.loads((root / 'contents.json').read_text())
    components = ('ssc', 'ssc_inventory', 'fastrpc', 'monado', 'turnip')
    if 'basalt' in contents or 'basalt' in root_record:
        components += ('basalt',)
    if any(contents.get(name) != root_record.get(name) for name in components):
        raise ValueError('Root component receipts disagree')
    profile = json.loads((root / 'root-profile.json').read_text())
    if profile.get('profile') != 'pico-neo3' or profile.get('pico_services') is not True:
        raise ValueError('Root profile differs')
    root_label(root / 'rootfs.ext4', root_record['root_label'])
    return {'kernel_build_sha256': kernel_sha, 'kernel_inputs': hashes,
            'initramfs_build_sha256': digest(initrd / 'build.json'), 'initramfs_sha256': rd_hashes['initramfs.img'],
            'root_manifest_sha256': root_manifest_sha256, 'root_image_sha256': root_hashes['rootfs.ext4'],
            'root_label': root_record['root_label'], 'components': {n: root_record.get(n) for n in components}}


def run(args):
    reference, kernel, initrd, root, tools, output = (
        p.absolute() for p in (args.reference, args.kernel, args.initramfs, args.root, args.mkbootimg, args.output))
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a new output directory')
    serial = getattr(args, 'recovery_boot_serial', None)
    probe = getattr(args, 'recovery_probe', False)
    image = getattr(args, 'initramfs_image', None)
    if (probe and not serial) or bool(serial) != bool(image):
        raise ValueError('Recovery probe requires a serial and immutable initramfs image')
    stock = container.reference_input(reference, args.reference_sha256)
    profile = assembly.checked_tools(tools)
    inputs = runtime_inputs(kernel, initrd, root, args.root_manifest_sha256)
    arm64 = assembly.checked_kernel_image(kernel / 'Image', inputs['kernel_inputs']['Image'])
    cmdline = assembly.root_arguments(inputs['root_label'], pico_services=True) + ' selinux=1 enforcing=1'
    sources = {n: digest(ROOT / 'system/pico' / n) for n in RECOVERY_SOURCES} if serial else {}
    if serial:
        cmdline = recovery_arguments(cmdline, serial, probe) + ' panic=10'
    report = dict(inputs, status='started', scope='unsigned offline Pico runtime assembly',
                  flash_ready=False, physical_boot_verified=False, recovery_verified=False,
                  dtb_compatibility_verified=False, root_transport_verified=False, rootfs_included=False,
                  signatures_created=False, device_actions=[], reference_sha256=stock['sha256'],
                  reference_authentication='expected hash supplied by caller', kernel_image=arm64,
                  assembler_sha256=digest(Path(__file__)), container_helper_sha256=digest(ROOT / 'tools/pico-boot.py'),
                  aosp_profile=profile, commands=[])
    output.mkdir(parents=True)
    try:
        ramdisk = initrd / 'initramfs.img'
        name = 'boot-linux-unsigned.img'
        if serial:
            report['commands'].append(augment_recovery(initrd, output, image, serial, args.engine))
            ramdisk = output / 'initramfs-recovery.img'
            report.update(recovery_to='fastboot', recovery_probe=probe, recovery_boot_serial=serial,
                          recovery_sources_sha256=sources, initramfs_image=image,
                          derived_initramfs_sha256=digest(ramdisk))
            if probe:
                name = 'boot-recovery-probe.img'
                report['scope'] = 'RAM-only missing-root recovery probe; never flash this image'
        container.assemble(reference, stock, kernel / 'Image', ramdisk,
                           {'kernel': arm64['sha256'], 'ramdisk': digest(ramdisk)},
                           cmdline, tools, output, name, report)
        if (digest(reference) != stock['sha256'] or assembly.checked_tools(tools) != profile or
                runtime_inputs(kernel, initrd, root, args.root_manifest_sha256) != inputs or
                (serial and {n: digest(ROOT / 'system/pico' / n) for n in RECOVERY_SOURCES} != sources)):
            raise ValueError('Inputs changed during assembly')
        report.update(status='assembled-and-roundtrip-verified', source_inputs_unchanged=True)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reference', 'kernel', 'initramfs', 'root'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--reference-sha256', required=True)
    parser.add_argument('--root-manifest-sha256', required=True, help='manifest hash retained from offline root verification')
    parser.add_argument('--mkbootimg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recovery-boot-serial', help='Opt in to guarded emergency return to fastboot')
    parser.add_argument('--recovery-probe', action='store_true', help='RAM-only missing-root test; never flash this image')
    parser.add_argument('--initramfs-image', help='Immutable ARM64 builder image ID for recovery augmentation')
    parser.add_argument('--engine', default='docker')
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
