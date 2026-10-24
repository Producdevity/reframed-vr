#!/usr/bin/env python3
"""Run synthetic CPU ownership probes on stock Pico; does not start sensors or flash."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    build = json.loads((bundle / 'build.json').read_text())
    profile = json.loads((ROOT / 'profiles/pico-controller-images.json').read_text())
    if build['status'] != 'compiled' or build['profile'] != profile:
        parser.error('Bundle profile is stale')
    for name, expected in build['source_sha256'].items():
        if (Path(name).is_absolute() or '..' in Path(name).parts or
                digest(ROOT / name) != expected):
            parser.error('Build input differs: ' + name)
    names = ['pico-controller-images', 'pico-controller-images-public', 'libpico-controller-images.so']
    for name in names:
        if digest(bundle / name) != build['artifacts'][name]:
            parser.error('Artifact differs: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    remote = '/data/local/tmp/reframed-image-owner-' + uuid.uuid4().hex
    sdk = '/system/lib64/' + profile['sdk']['filename']
    report = {'status': 'started', 'hardware_tracking': False, 'commands': [],
              'bundle_manifest_sha256': digest(bundle / 'build.json'),
              'scope': 'Synthetic CPU inputs; no camera, radio or firmware operation'}

    def run(arguments, check=True):
        result = subprocess.run(['adb', '-s', args.serial, *arguments],
                                capture_output=True, text=True, timeout=110)
        report['commands'].append({'arguments': arguments, 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        if check and result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result

    def shell(arguments, check=True):
        return run(['shell', shlex.join(arguments)], check)

    created = False
    try:
        if shell(['getprop', 'ro.serialno']).stdout.strip() != args.serial:
            raise ValueError('Unexpected physical device serial')
        report['boot_id'] = shell(['cat', '/proc/sys/kernel/random/boot_id']).stdout.strip()
        if shell(['sha256sum', sdk]).stdout.split()[0] != profile['sdk']['sha256']:
            raise ValueError('Device SDK differs from verified ABI')
        miniglog = '/system/lib64/libminiglog.so'
        if shell(['sha256sum', miniglog]).stdout.split()[0] != '36c5d73e58c7141ac0c34737b558e263eaec80c8cb76f428a1819045dad2f98a':
            raise ValueError('SDK unwind dependency differs')
        if shell(['settings', 'get', 'global', 'wifi_on']).stdout.strip() != '0':
            raise ValueError('Pico must already be offline')
        shell(['mkdir', '-m', '700', remote])
        created = True
        for name in names:
            run(['push', str(bundle / name), remote + '/' + name])
            if shell(['sha256sum', remote + '/' + name]).stdout.split()[0] != build['artifacts'][name]:
                raise ValueError('Transfer differs: ' + name)
        shell(['chmod', '700', *(remote + '/' + name for name in names[:2])])
        for mode in ['negative', 'owned', 'delayed', 'retained', 'public']:
            binary = 'pico-controller-images-public' if mode == 'public' else 'pico-controller-images'
            command = ['env', 'LD_PRELOAD=' + miniglog + ':' + remote + '/libpico-controller-images.so',
                       remote + '/' + binary, sdk]
            if mode != 'public':
                command.append(mode)
            result = shell(command, check=False)
            (output / (mode + '.log')).write_text(result.stdout + result.stderr)
            marker = 'PICO_IMAGE_OWNER_' + mode.upper() + '_PASS'
            if result.returncode or marker not in result.stdout:
                raise RuntimeError(mode + ' probe failed; see log')
            print(next(line for line in result.stdout.splitlines() if marker in line), flush=True)
        if shell(['cat', '/proc/sys/kernel/random/boot_id']).stdout.strip() != report['boot_id']:
            raise ValueError('Stock boot changed during test')
        if shell(['settings', 'get', 'global', 'wifi_on']).stdout.strip() != '0':
            raise ValueError('Offline state changed')
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        if created:
            cleanup = [shell(['rm', '-f', remote + '/' + name], check=False).returncode for name in names]
            cleanup.append(shell(['rmdir', remote], check=False).returncode)
            report['temporary_files_removed'] = not any(cleanup)
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
