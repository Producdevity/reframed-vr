#!/usr/bin/env python3
"""Build a selected Quest 3 module; never load it or contact a device."""
import argparse
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
RELEASE = '5.10.246-gd7102a837402'
IMAGE = 'sha256:d656c1cd2295dc20105297a2ff85ad4a9f624808d17a259d34d6ccb189fcc2e3'
EXPORTERS = (
    'kernel/module.o', 'kernel/cfi.o', 'kernel/panic.o',
    'kernel/printk/printk.o', 'kernel/locking/mutex.o',
    'drivers/of/base.o', 'drivers/base/bus.o', 'drivers/base/platform.o',
    'mm/page_alloc.o',
    'drivers/firmware/efi/efi.o',
    'kernel/reboot.o',
    'kernel/cpu.o', 'kernel/params.o',
)
ASSEMBLY_EXPORTERS = ('arch/arm64/lib/strcmp.o', 'arch/arm64/lib/memset.o')
MODULES = {'probe': ('reframed_quest_probe', 'probe.c'),
           'reset-test': ('reframed_quest_reset_test', 'reset-test.c'),
           'memory-test': ('reframed_quest_memory_test', 'memory-test.c')}
MODULE_EXPORTERS = {'memory-test': ('kernel/time/hrtimer.o',
                                  'kernel/time/timekeeping.o', 'arch/arm64/mm/init.o')}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def config_values(text):
    values = {}
    for line in text.splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]] = 'n'
    return values


def source_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            record = [str(path.relative_to(root)), 'symlink', os.readlink(path)]
        elif path.is_file():
            record = [str(path.relative_to(root)), 'file', sha(path)]
        else:
            continue
        digest.update(json.dumps(record, separators=(',', ':')).encode() + b'\n')
    return digest.hexdigest()


def inside():
    out = Path('/output')
    selection = json.loads((out / 'inputs.json').read_text())['module']
    module_name, source_name = MODULES[selection]
    exporters = EXPORTERS + MODULE_EXPORTERS.get(selection, ())
    build = out / 'kbuild'
    build.mkdir()
    requested = (out / 'requested.config').read_text()
    (build / '.config').write_text(requested)
    env = {**os.environ, 'PATH': '/toolchain/bin:' + os.environ['PATH'],
           'ARCH': 'arm64', 'LLVM': '1', 'LLVM_IAS': '1', 'REAL_CC': 'clang-14',
           'CROSS_COMPILE': 'aarch64-linux-gnu-',
           'CROSS_COMPILE_COMPAT': 'arm-linux-gnueabi-',
           'CROSS_COMPILE_ARM32': 'arm-linux-gnueabi-'}
    make = ['make', '-C', '/source', 'O=' + str(build), 'CC=clang-14',
            'HOSTCC=gcc', 'HOSTCXX=g++', 'PYTHON=python3',
            'LOCALVERSION=-gd7102a837402',
            'QUEST_KEXEC_MODULE=' + module_name,
            'LD=ld.lld --threads=1 --lto-partitions=1']
    report = {'status': 'started', 'commands': [], 'hardware_tested': False}
    start = time.monotonic()

    def run(name, command):
        report['commands'].append(command)
        with (out / (name + '.log')).open('xb') as log:
            subprocess.run(command, env=env, check=True, stdout=log,
                           stderr=subprocess.STDOUT, timeout=600)

    try:
        report['compiler'] = subprocess.check_output(
            ['/toolchain/bin/clang-14', '--version'], text=True)
        if '8508608' not in report['compiler'] or '14.0.7' not in report['compiler']:
            raise ValueError('Requires stock Android Clang 14.0.7 build 8508608')
        run('configure', make + ['olddefconfig'])
        resolved = (build / '.config').read_text()
        (out / 'resolved.config').write_text(resolved)
        (out / 'config.diff').write_text(''.join(difflib.unified_diff(
            requested.splitlines(True), resolved.splitlines(True))))
        before, after = config_values(requested), config_values(resolved)
        changes = {key: [before.get(key, 'n'), after.get(key, 'n')]
                   for key in before.keys() | after.keys()
                   if before.get(key, 'n') != after.get(key, 'n')}
        report['config_changes'] = changes
        allowed = {'CONFIG_CC_CAN_LINK', 'CONFIG_CC_CAN_LINK_STATIC', 'CONFIG_PAHOLE_VERSION'}
        if changes.keys() - allowed:
            raise ValueError('Unreviewed configuration normalization: ' + str(changes))
        for option in ('CONFIG_MODVERSIONS', 'CONFIG_CFI_CLANG',
                       'CONFIG_CFI_CLANG_SHADOW', 'CONFIG_LTO_CLANG_FULL',
                       'CONFIG_SHADOW_CALL_STACK'):
            if after.get(option) != 'y':
                raise ValueError('Missing stock build protection: ' + option)
        if after.get('CONFIG_CFI_PERMISSIVE', 'n') != 'n':
            raise ValueError('CFI must remain strict')
        run('prepare', make + ['-j2', 'modules_prepare'])
        uts = (build / 'include/generated/utsrelease.h').read_text()
        if uts.strip() != '#define UTS_RELEASE "' + RELEASE + '"':
            raise ValueError('Unexpected generated kernel release: ' + uts)
        shutil.copyfile('/stock/Module.symvers', build / 'Module.symvers')
        run('module', make + ['-j2', 'V=1', 'M=/output/module', 'modules'])
        run('source-exporters', make + ['-j2', 'KBUILD_SYMTYPES=1', *exporters])
        run('assembly-exporter', make + ['-j1', 'build-dirs=arch/arm64/lib',
                                       'KBUILD_SYMTYPES=1', *ASSEMBLY_EXPORTERS])
        generated = {}
        for target in exporters + ASSEMBLY_EXPORTERS:
            script = Path(str(build / target) + '.symversions')
            if script.is_file():
                generated.update({name: int(value, 16) for name, value in
                                  re.findall(r'__crc_(\w+) = (0x[0-9a-f]+);', script.read_text())})
        # Assembly Kbuild links CRCs into absolute symbols and removes its temporary script.
        for target in ASSEMBLY_EXPORTERS:
            symbols = subprocess.check_output(
                ['/toolchain/bin/llvm-nm', '--defined-only', str(build / target)], text=True)
            generated.update({name: int(value, 16) for value, name in
                              re.findall(r'^([0-9a-f]+) A __crc_(\w+)$', symbols, re.MULTILINE)})
        expected = {line.split()[1]: int(line.split()[0], 16)
                    for line in Path('/stock/Module.symvers').read_text().splitlines()}
        imported = {name: int(value, 16) for value, name in re.findall(
            r'\{ 0x([0-9a-f]+), "([^"]+)" \}',
            (out / 'module' / (module_name + '.mod.c')).read_text())}
        if not imported:
            raise ValueError('Module has no versioned imports')
        missing = imported.keys() - generated.keys()
        if missing:
            raise ValueError('Missing source exporters: ' + ', '.join(sorted(missing)))
        for name, value in imported.items():
            if value != expected.get(name) or value != generated.get(name):
                raise ValueError('Stock/source/module CRC disagreement: ' + name)
        report['verified_imports'] = {key: f'{value:08x}' for key, value in imported.items()}
        module = out / 'module' / (module_name + '.ko')
        data = module.read_bytes()
        vermagic = RELEASE + ' SMP preempt mod_unload modversions aarch64'
        if ('vermagic=' + vermagic + '\x00').encode() not in data:
            raise ValueError('Unexpected module vermagic')
        command = (out / 'module' / ('.' + source_name[:-2] + '.o.cmd')).read_text()
        for flag in ('-flto', '-fsanitize=cfi', '-fsanitize=shadow-call-stack', '-ffixed-x18'):
            if flag not in command:
                raise ValueError('Missing compile protection: ' + flag)
        run('module-elf', ['/toolchain/bin/llvm-readelf', '-h', '-S', '-s', '-r', str(module)])
        run('module-disassembly', ['/toolchain/bin/llvm-objdump', '-dr', str(module)])
        report.update(status='passed', module_sha256=sha(module), vermagic=vermagic)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - start, 3)
        (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', choices=MODULES, default='probe')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--stock-symvers', type=Path, required=True)
    parser.add_argument('--stock-symvers-sha256', required=True)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for key in ('source', 'config', 'stock_symvers', 'toolchain'):
        setattr(args, key, getattr(args, key).resolve(strict=True))
    if sha(args.stock_symvers) != args.stock_symvers_sha256:
        raise ValueError('Stock export table checksum differs')
    out = args.output.resolve()
    if out.exists():
        raise ValueError('Output must be a new directory')
    out.mkdir(parents=True)
    module = out / 'module'
    module.mkdir()
    for name in ('Makefile', MODULES[args.module][1]):
        shutil.copyfile(ROOT / 'kernel/quest-kexec' / name, module / name)
    config = args.config.read_bytes()
    if config.startswith(b'\x1f\x8b'):
        config = gzip.decompress(config)
    (out / 'requested.config').write_bytes(config)
    inputs = {'module': args.module, 'release': RELEASE, 'source_profile_sha256': sha(ROOT / 'profiles/kernel/quest3.json'),
              'source_tree_sha256': source_digest(args.source),
              'config_sha256': sha(args.config), 'stock_symvers_sha256': sha(args.stock_symvers),
              'module_source_sha256': sha(module / MODULES[args.module][1]), 'makefile_sha256': sha(module / 'Makefile'),
              'builder_sha256': sha(Path(__file__)), 'container_image': IMAGE,
              'compiler_sha256': sha(args.toolchain / 'bin/clang-14')}
    (out / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    command = ['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/amd64',
               '--cpus', '2', '--memory', '4g', '--pids-limit', '256',
               '--mount', f'type=bind,source={args.source},target=/source,readonly',
               '--mount', f'type=bind,source={args.toolchain},target=/toolchain,readonly',
               '--mount', f'type=bind,source={args.stock_symvers},target=/stock/Module.symvers,readonly',
               '--mount', f'type=bind,source={Path(__file__).resolve()},target=/runner.py,readonly',
               '--mount', f'type=bind,source={out},target=/output',
               '--entrypoint', 'python3', IMAGE, '/runner.py', '--inside']
    with (out / 'container.log').open('xb') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1500)
    print(out / 'build.json')


if __name__ == '__main__':
    if sys.argv[1:] == ['--inside']:
        inside()
    else:
        main()
