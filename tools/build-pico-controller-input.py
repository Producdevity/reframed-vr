#!/usr/bin/env python3
"""Build the b1977 FastRPC controller worker on native ARM64 Linux; no device access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
UNITS = ['pico-controller', 'pico-controller-channel', 'pico-controller-ring',
         'pico-controller-motion', 'pico-controller-motion-channel', 'pico-controller-motion-producer',
         'pico-sensor-rpc', 'sns-low-latency', 'ion-buffer', 'ssc-clock', 'ssc-clock-linux']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_runtime(prefix, manifest):
    required = {'lib64/libsdsprpc.so', 'lib64/libsdsprpc.so.1', 'lib64/libsdsprpc.so.1.0.0',
                'lib64/libbsd.so.0', 'lib64/libmd.so.0', 'lib64/libyaml-0.so.2'}
    if not required.issubset(manifest):
        raise ValueError('Incomplete FastRPC runtime manifest')
    for name, record in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid runtime path: ' + name)
        path = prefix / relative
        if not path.resolve().is_relative_to(prefix):
            raise ValueError('Runtime escapes prefix: ' + name)
        if 'symlink' in record:
            if not path.is_symlink() or path.readlink().as_posix() != record['symlink']:
                raise ValueError('Runtime link differs: ' + name)
            target = path.resolve().relative_to(prefix).as_posix()
            if target not in manifest or 'sha256' not in manifest[target]:
                raise ValueError('Unverified link target: ' + name)
        elif path.is_symlink() or digest(path) != record['sha256']:
            raise ValueError('Runtime file differs: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fastrpc-prefix', type=Path, default=Path('/opt/reframed-vr/fastrpc'))
    parser.add_argument('--runtime-manifest', type=Path, required=True,
                        help='Previously verified mapping of runtime paths to hashes or symlink targets')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('Requires native ARM64 Linux; does not install or start a receiver')
    prefix = args.fastrpc_prefix.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = ['tools/pico-controller-input.c', 'tools/build-pico-controller-input.py',
               'tools/pico-controller-session.py',
               'profiles/pico-fastrpc.json', 'tests/pico-controller-ring.c',
               'tests/pico-controller-motion-ring.c', 'tests/pico-controller-motion-channel.c',
               'tests/pico-controller-motion-producer.c', 'tests/pico-sensor-rpc.c']
    sources += ['src/' + unit + suffix for unit in UNITS for suffix in ('.c', '.h')]
    report = {'status': 'started', 'device_actions': [],
              'source_sha256': {name: digest(ROOT / name) for name in sources}, 'commands': []}
    try:
        runtime = json.loads(args.runtime_manifest.read_text())
        verify_runtime(prefix, runtime)
        report['runtime_manifest'] = runtime
        profile = json.loads((ROOT / 'profiles/pico-fastrpc.json').read_text())
        archive = prefix / 'share/fastrpc/source.tar.gz'
        if digest(archive) != profile['source_archive_sha256']:
            raise ValueError('FastRPC SDK archive differs')
        headers = output / 'include'
        headers.mkdir()
        with tarfile.open(archive) as tar:
            for name in ('remote.h', 'rpcmem.h'):
                members = [m for m in tar if m.name == profile['archive_root'] + '/inc/' + name]
                if len(members) != 1 or not members[0].isfile() or members[0].size > 262144:
                    raise ValueError('Invalid pinned SDK header: ' + name)
                (headers / name).write_bytes(tar.extractfile(members[0]).read())
            license_member = tar.getmember(profile['archive_root'] + '/LICENSE.txt')
            (output / 'fastrpc-LICENSE.txt').write_bytes(tar.extractfile(license_member).read())

        def run(command, log):
            report['commands'].append(command)
            result = subprocess.run(command, capture_output=True, text=True, timeout=90,
                                    env=os.environ | {'LD_LIBRARY_PATH': str(prefix / 'lib64')})
            (output / log).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError(log + ': ' + result.stdout + result.stderr)

        common = ['cc', '-std=gnu11', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
                  '-I', str(ROOT / 'src'), '-I', str(headers)]
        binary = output / 'pico-controller-input'
        run([*common, str(ROOT / 'tools/pico-controller-input.c'),
             *(str(ROOT / 'src' / (unit + '.c')) for unit in UNITS),
             '-L', str(prefix / 'lib64'), '-lsdsprpc', '-o', str(binary)], 'compile.log')
        for name, units in [('ring', ['pico-controller', 'pico-controller-ring']),
                            ('motion-ring', ['pico-controller', 'pico-controller-ring']),
                            ('motion-channel', ['pico-controller-motion-channel']),
                            ('motion-producer', ['pico-controller', 'pico-controller-ring',
                                'pico-controller-motion', 'pico-controller-motion-channel',
                                'pico-controller-motion-producer']),
                            ('rpc', ['pico-sensor-rpc', 'sns-low-latency'])]:
            source = 'pico-sensor-rpc' if name == 'rpc' else 'pico-controller-' + name
            test = output / (name + '-test')
            run([*common, '-fsanitize=undefined', '-fno-sanitize-recover=all',
                 str(ROOT / 'tests' / (source + '.c')),
                 *(str(ROOT / 'src' / (unit + '.c')) for unit in units),
                 '-o', str(test)], name + '-compile.log')
            run([str(test)], name + '-test.log')
        run(['ldd', '-r', str(binary)], 'dependencies.log')
        text = (output / 'dependencies.log').read_text()
        if 'not found' in text or 'undefined symbol' in text:
            raise ValueError('Unresolved runtime dependency')
        verify_runtime(prefix, runtime)
        if report['source_sha256'] != {name: digest(ROOT / name) for name in sources}:
            raise ValueError('Build inputs changed')
        helper = output / 'pico-controller-session.py'
        shutil.copyfile(ROOT / 'tools/pico-controller-session.py', helper)
        if digest(helper) != report['source_sha256']['tools/pico-controller-session.py']:
            raise ValueError('Session helper changed while copying')
        report.update(status='compiled', binary_sha256=digest(binary),
                      session_sha256=digest(helper),
                      sdk_archive_sha256=profile['source_archive_sha256'])
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
