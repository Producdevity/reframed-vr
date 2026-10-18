#!/usr/bin/env python3
"""Package a verified Pico ext4 root for bounded USB delivery into RAM."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'tools/assemble-pico-boot.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
digest = runtime.digest
FILES = ('reframed-pico-live-root', 'reframed-pico-live-root.service',
         'reframed-pico-live-console', 'reframed-pico-live-console.service',
         'reframed-pico-live-install', 'reframed-pico-live-install.service')
PACK = r'''
set -eu
mksquashfs /root/rootfs.ext4 /output/root.squashfs -noappend -all-root -no-xattrs \
    -comp zstd -b 131072 -processors 2 -mem 256M -mkfs-time 0 -all-time 0 -no-progress
set -o pipefail
unsquashfs -cat /output/root.squashfs rootfs.ext4 | sha256sum > /output/inner-root.sha256
'''
AUGMENT = r'''
set -eu
mkdir /tmp/rd
cd /tmp/rd
lsinitrd --unpack /baseline/initramfs.img
/usr/lib/dracut/dracut-install -D /tmp/rd -l /usr/bin/head /usr/bin/stty /usr/bin/stat /usr/bin/od \
    /usr/bin/tr /usr/bin/mountpoint /usr/bin/install /usr/bin/readlink /usr/bin/sleep /usr/sbin/blockdev
mkdir -p usr/libexec etc/reframed-vr etc/systemd/system/initrd.target.wants
for name in reframed-pico-live-root reframed-pico-live-console reframed-pico-live-install; do
    install -m 0755 /source/$name usr/libexec/$name
    install -m 0644 /source/$name.service usr/lib/systemd/system/$name.service
done
install -m 0600 /output/pico-live-root.conf etc/reframed-vr/pico-live-root.conf
for name in reframed-pico-live-root reframed-pico-live-install; do
    ln -s /usr/lib/systemd/system/$name.service etc/systemd/system/initrd.target.wants/$name.service
done
find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --reproducible --owner=0:0 | gzip -n -9 > /output/initramfs-live.img
find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /output/initramfs-live-contents.sha256
'''


def config(serial, payload_bytes, payload_sha256, root_bytes, label):
    runtime.diagnostic.diagnostic.serial(serial)
    runtime.assembly.root_arguments(label, pico_services=True)
    if not 0 < payload_bytes <= 3 * 1024**3 or not runtime.re.fullmatch('[0-9a-f]{64}', payload_sha256):
        raise ValueError('Compressed root must fit the 3 GiB development limit')
    if type(root_bytes) is not int or not 0 < root_bytes <= 128 * 1024**3:
        raise ValueError('Invalid inner filesystem size')
    return (f'BOOT_SERIAL={serial}\nPAYLOAD_BYTES={payload_bytes}\nPAYLOAD_SHA256={payload_sha256}\n'
            f'ROOT_BYTES={root_bytes}\nROOT_LABEL={label}\n')


def userdata_config(relative, start, sectors):
    if (not runtime.re.fullmatch(r'unencrypted/[A-Za-z0-9][A-Za-z0-9_-]*/root\.squashfs', relative) or
            type(start) is not int or type(sectors) is not int or
            not 0 < start < 2**40 or not 0 < sectors < 2**40):
        raise ValueError('Require an explicit private unencrypted root file and retained partition geometry')
    return f'USERDATA_RELATIVE={relative}\nUSERDATA_START={start}\nUSERDATA_SECTORS={sectors}\n'


def build(args):
    kernel, initrd, root, output, tools, reference = (
        p.absolute() for p in (args.kernel, args.initramfs, args.root, args.output, args.mkbootimg, args.reference))
    if output.exists():
        raise ValueError('Choose a new output directory')
    inputs = runtime.runtime_inputs(kernel, initrd, root, args.root_manifest_sha256)
    stock = runtime.container.reference_input(reference, args.reference_sha256)
    profile = runtime.assembly.checked_tools(tools)
    serial = runtime.diagnostic.diagnostic.serial(args.boot_serial)
    userdata = userdata_config(args.userdata_file, args.userdata_start, args.userdata_sectors) if args.userdata_file else ''
    sources = {n: digest(ROOT / 'system/pico' / n) for n in FILES}
    output.mkdir(parents=True)
    report = dict(status='started', scope='physical Pico USB RAM-root development assembly',
                  physical_boot_verified=False, flash_ready=False, device_actions=[],
                  inputs=inputs, sources_sha256=sources, boot_serial=serial,
                  baseline_initramfs_sha256=inputs['initramfs_sha256'],
                  reference_sha256=stock['sha256'], aosp_profile=profile, commands=[])
    def run(image, script, mounts, log):
        command = [args.engine, 'run', '--rm', '--network', 'none', '--memory', '2g',
                   '--memory-swap', '2g', '--cpus', '2', '--pids-limit', '128',
                   '-v', f'{output}:/output', *mounts, '--entrypoint', 'bash', image, '-c', script]
        report['commands'].append(command)
        with (output / log).open('xb') as stream:
            subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    try:
        if args.packed_root:
            runtime.regular(args.packed_root, 3 * 1024**3)
            if digest(args.packed_root) != args.packed_root_sha256:
                raise ValueError('Retained compressed root checksum differs')
            shutil.copyfile(args.packed_root, output / 'root.squashfs')
            run(args.pack_image, 'set -eo pipefail; unsquashfs -cat /output/root.squashfs rootfs.ext4 | sha256sum > /output/inner-root.sha256',
                [], 'pack.log')
        else:
            run(args.pack_image, PACK, ['-v', f'{root}:/root:ro'], 'pack.log')
        if (output / 'inner-root.sha256').read_text().split() != [inputs['root_image_sha256'], '-']:
            raise ValueError('SquashFS changed the embedded ext4 bytes')
        payload_bytes = (output / 'root.squashfs').stat().st_size
        payload_sha = digest(output / 'root.squashfs')
        (output / 'pico-live-root.conf').write_text(config(serial, payload_bytes, payload_sha,
            (root / 'rootfs.ext4').stat().st_size, inputs['root_label']) + userdata)
        run(args.initramfs_image, AUGMENT,
            ['-v', f'{initrd}:/baseline:ro', '-v', f'{ROOT / "system/pico"}:/source:ro'], 'augment.log')
        cmdline = runtime.assembly.root_arguments(inputs['root_label'], pico_services=True)
        cmdline = cmdline.replace('rd.retry=15 rd.timeout=30', 'rd.retry=2340 rd.timeout=2400')
        cmdline += ' reframed.live=usb selinux=1 enforcing=1 panic=10'
        if args.disable_panic_download:
            cmdline += ' msm_poweroff.download_mode=0'
        if not args.enable_display:
            cmdline += ' msm_drm.modeset=0'
        runtime.container.assemble(reference, stock, kernel / 'Image', output / 'initramfs-live.img',
            {'kernel': inputs['kernel_inputs']['Image'], 'ramdisk': digest(output / 'initramfs-live.img')},
            cmdline, tools, output, 'boot-live-unsigned.img', report)
        if (runtime.runtime_inputs(kernel, initrd, root, args.root_manifest_sha256) != inputs or
                {n: digest(ROOT / 'system/pico' / n) for n in FILES} != sources or
                digest(reference) != stock['sha256'] or runtime.assembly.checked_tools(tools) != profile):
            raise ValueError('Source inputs changed during live-root construction')
        report.update(status='assembled-and-roundtrip-verified', source_inputs_unchanged=True,
                      payload_bytes=payload_bytes, payload_sha256=payload_sha, cmdline=cmdline,
                      derived_initramfs_sha256=digest(output / 'initramfs-live.img'),
                      config_sha256=digest(output / 'pico-live-root.conf'),
                      root_delivery='userdata-file' if userdata else 'usb-RAM',
                      userdata_config=userdata or None,
                      root_backing='readonly SquashFS and ext4 loops, volatile OverlayFS root',
                      persistent_partition_writes=False, maximum_transfer_seconds=2400)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (output / 'live-root.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'live-root.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reference', 'kernel', 'initramfs', 'root'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--reference-sha256', required=True)
    parser.add_argument('--root-manifest-sha256', required=True)
    parser.add_argument('--mkbootimg', type=Path, required=True)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--disable-panic-download', action='store_true',
                        help='Disable the BSP panic download-mode switch for this RAM boot; recovery remains unverified')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pack-image', required=True)
    parser.add_argument('--initramfs-image', required=True)
    parser.add_argument('--engine', default='docker')
    parser.add_argument('--packed-root', type=Path, help='Reuse an existing compressed root; embedded ext4 is reverified')
    parser.add_argument('--packed-root-sha256')
    parser.add_argument('--userdata-file', help='Private unencrypted root.squashfs path relative to the retained userdata partition')
    parser.add_argument('--userdata-start', type=int, help='Retained userdata start in 512-byte sectors')
    parser.add_argument('--userdata-sectors', type=int, help='Retained userdata length in 512-byte sectors')
    parser.add_argument('--enable-display', action='store_true')
    try:
        build(parser.parse_args())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
