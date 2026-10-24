#!/usr/bin/env python3
"""Exercise Pico DRM timelines and software fences in a diskless QEMU guest."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dma_test', ROOT / 'tools/test-dma-buf-sync.py')
dma = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dma)


def run(args):
    kernel, output = args.kernel.resolve(), args.output.absolute()
    if output.exists() or output.is_symlink() or any(c in str(output) for c in ':,'):
        raise ValueError('Choose a new output directory without commas or colons')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.volume):
        raise ValueError('Invalid kernel cache volume')
    build = json.loads((kernel / 'build.json').read_text())
    if (build.get('status') != 'compiled' or build.get('qemu_transports') is not True or
            build.get('repository') != 'bytedance/neo3-kernel'):
        raise ValueError('Requires a compiled Pico QEMU variant; refuses physical kernels')
    image = build['container_image']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Expected immutable compiler image')
    expected = {entry['path']: entry['sha256'] for entry in build['artifacts']}
    for name in ('Image', 'resolved.config', 'Module.symvers'):
        if (kernel / name).is_symlink() or dma.digest(kernel / name) != expected.get(name):
            raise ValueError('Kernel artifact mismatch: ' + name)
    config = (kernel / 'resolved.config').read_text().splitlines()
    for name in ('CONFIG_DRM', 'CONFIG_SYNC_FILE', 'CONFIG_SW_SYNC', 'CONFIG_DEBUG_FS'):
        if name + '=y' not in config:
            raise ValueError('Test requires built-in ' + name)
    make = next(command[:-1] for command in build['commands']
                if command[0] == 'make' and command[-1] == 'olddefconfig')
    source = make[make.index('-C') + 1]
    if not re.fullmatch(r'/work/linux-userspace/[0-9a-f]{16}/source', source):
        raise ValueError('Unexpected kernel cache source path')
    if f'O={source.removesuffix("/source")}/build' not in make:
        raise ValueError('Unexpected kernel cache build path')
    output.mkdir(parents=True)
    shutil.copytree(ROOT / 'tests/kernel-drm-syncobj', output / 'module')
    paths = [ROOT / 'tests/drm-syncobj.c', ROOT / 'tools/prepare-pico-qemu-board.py',
             ROOT / 'tools/test-dma-buf-sync.py', Path(__file__),
             *sorted((ROOT / 'tests/kernel-drm-syncobj').iterdir())]
    pins = {str(p.relative_to(ROOT)): dma.digest(p) for p in paths if p.is_file()}
    report = {'status': 'started', 'scope': 'core DRM syncobj and software fences, no GPU or panel',
              'hardware_verified': False, 'flash_image': False, 'compiler_image': image,
              'kernel_build_sha256': dma.digest(kernel / 'build.json'),
              'kernel_sha256': expected['Image'], 'source_sha256': pins, 'commands': [],
              'expect_query_leak': args.expect_query_leak}
    started = time.monotonic()

    def execute(command, log, timeout):
        report['commands'].append(command)
        with (output / log).open('wb') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, check=True, timeout=timeout)

    container = [args.engine, 'run', '--rm', '--network', 'none', '--cpus', '1',
                 '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '64',
                 '--mount', f'type=volume,src={args.volume},dst=/work,readonly',
                 '--mount', f'type=bind,src={ROOT / "tests"},dst=/tests,readonly',
                 '--mount', f'type=bind,src={output},dst=/output']
    cached_build = source.removesuffix('/source') + '/build'
    cache_pins = {cached_build + '/' + name: expected[artifact] for name, artifact in
                  [('arch/arm64/boot/Image', 'Image'), ('.config', 'resolved.config'),
                   ('Module.symvers', 'Module.symvers')]}
    cache_check = ('import hashlib,json,sys; from pathlib import Path; '
                   'pins=json.loads(sys.argv[1]); '
                   'actual={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in pins}; '
                   'assert actual==pins,(actual,pins); print(json.dumps(actual,sort_keys=True))')
    try:
        execute([*container, '--entrypoint', 'python3', image, '-c', cache_check,
                 json.dumps(cache_pins)], 'cache-before.json', 30)
        environment = {'ARCH': 'arm64', 'LLVM': '1', 'LLVM_IAS': '1',
                       'CROSS_COMPILE': 'aarch64-linux-gnu-', 'REAL_CC': 'clang',
                       'KBUILD_BUILD_USER': 'reframed', 'KBUILD_BUILD_HOST': 'kernel-builder',
                       'KBUILD_BUILD_TIMESTAMP': '2026-09-10 00:00:00 UTC'}
        env_args = [part for key, value in environment.items() for part in ('--env', key + '=' + value)]
        execute([*container, *env_args, '--entrypoint', make[0], image, *make[1:],
                 'M=/output/module', '-j1', 'modules'], 'module-build.log', 120)
        execute([*container, '--entrypoint', cached_build + '/scripts/sign-file', image,
                 'sha512', cached_build + '/certs/signing_key.pem',
                 cached_build + '/certs/signing_key.x509',
                 '/output/module/drm_syncobj_test.ko'], 'module-sign.log', 30)
        execute([*container, '--entrypoint', 'gcc', image, '-static', '-O2', '-Wall',
                 '-Wextra', '-Werror', '-D__user=', '-I' + source + '/include/uapi/drm',
                 '/tests/drm-syncobj.c', '-o', '/output/init'], 'fixture-build.log', 60)
        module = output / 'module/drm_syncobj_test.ko'
        (output / 'initramfs.cpio').write_bytes(dma.initramfs(
            (output / 'init').read_bytes(), module.read_bytes(), 'drm_syncobj_test.ko'))
        dtb = output / 'pico-qemu-board.dtb'
        cpu = 'host' if args.accel in ('hvf', 'kvm') else 'max'
        machine = [args.qemu, '-machine', 'virt', '-accel', args.accel,
                   '-cpu', cpu, '-smp', '2', '-m', '1024', '-nodefaults',
                   '-nographic', '-monitor', 'none', '-nic', 'none']
        dump = machine.copy()
        dump[dump.index('virt')] = 'virt,dumpdtb=' + str(dtb)
        execute(dump, 'board-dump.log', 20)
        execute([sys.executable, '-B', str(ROOT / 'tools/prepare-pico-qemu-board.py'),
                 str(dtb), '--report', str(output / 'board.json')], 'board-prepare.log', 30)
        execute([*machine, '-serial', 'stdio', '-no-reboot', '-dtb', str(dtb),
                 '-kernel', str(kernel / 'Image'), '-initrd', str(output / 'initramfs.cpio'),
                 '-append', 'console=ttyAMA0 earlycon rdinit=/init selinux=0 audit=0 '
                 'initcall_blacklist=socinfo_init,remoteqdss_init,hwinfo_init' +
                 (' reframed.query_leak=expected' if args.expect_query_leak else '')], 'boot.log', 60)
        text = (output / 'boot.log').read_text(errors='replace')
        cases = ['FUTURE_AND_OPAQUE_FD', 'TRANSFER_COMPLETION', 'COUNTERS_AND_CLEANUP',
                 'WIDTH_AND_RELEASE', 'UNWRAP_EMPTY', 'UNWRAP_AND', 'UNWRAP_OR', 'FIXTURE_UNLOAD', 'ALL']
        cases.append('QUERY_LEAK_REPRODUCED' if args.expect_query_leak else 'QUERY_REFS')
        if any('DRM_SYNCOBJ_' + name + '_PASS' not in text for name in cases):
            raise RuntimeError('Missing syncobj acceptance; inspect boot.log')
        if ('reboot: Power down' not in text or any(marker in text for marker in
                ('DRM_SYNCOBJ_FAIL', 'DRM_SYNCOBJ_KERNEL_FAIL', 'WARNING:', 'BUG:', 'Kernel panic', 'Oops:'))):
            raise RuntimeError('Kernel failure or missing clean power-off; inspect boot.log')
        if (dma.digest(kernel / 'Image') != expected['Image'] or
                dma.digest(kernel / 'build.json') != report['kernel_build_sha256'] or
                any(dma.digest(ROOT / name) != value for name, value in pins.items())):
            raise ValueError('Test inputs changed during execution')
        execute([*container, '--entrypoint', 'python3', image, '-c', cache_check,
                 json.dumps(cache_pins)], 'cache-after.json', 30)
        report.update(status='passed', cases=cases)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['artifacts_sha256'] = {str(p.relative_to(output)): dma.digest(p)
            for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'result.json'}
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expect-query-leak', action='store_true',
                        help='Negative baseline: require the known owning-reference leak')
    parser.add_argument('--volume', default='reframed-vr-pico-neo3-kernel')
    parser.add_argument('--engine', default=os.environ.get('CONTAINER_ENGINE', 'docker'))
    parser.add_argument('--qemu', default='qemu-system-aarch64')
    parser.add_argument('--accel', choices=('hvf', 'kvm', 'tcg'),
                        default='hvf' if platform.system() == 'Darwin' and platform.machine() == 'arm64' else 'tcg')
    try:
        run(parser.parse_args())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
