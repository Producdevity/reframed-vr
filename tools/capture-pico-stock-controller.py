#!/usr/bin/env python3
"""Capture existing b1977 controller results through stock getters; never starts tracking."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = 'Pico/A7H10/PICOA7H10:10/5.8.4.0/smartcm.1696861506:user/test-keys'
LIBRARY = '/system/lib64/libtrackingclient.pxr.so'
LIBRARY_SHA256 = '54829201c43cfd5ea8e121e59dbf80ad8e0e30b0ff848eaaced20d29f9bb2579'
HEADER_V1 = (0x5256504353500001, 1, 368, 776, 300, 0, 0, 0)
HEADER = (0x5256504353500001, 2, 368, 808, 300, 19200000, 0, 0)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(data):
    if len(data) < 64:
        raise ValueError('Incomplete or unsupported stock capture')
    header = struct.unpack_from('<8Q', data)
    if header not in (HEADER_V1, HEADER) or len(data) != 64 + 300 * header[3]:
        raise ValueError('Incomplete or unsupported stock capture')
    calls, hands = Counter(), {'left': [], 'right': []}
    clocks = ['monotonic', 'boottime'] + (['monotonic_raw', 'qtimer'] if header == HEADER else [])
    for offset in range(64, len(data), header[3]):
        raw_after = None
        counter_after = None
        if header == HEADER_V1:
            boot_before, mono_before, mono_after, boot_after, rc = struct.unpack_from('<5q', data, offset)
            payload = offset + 40
        else:
            boot_before, mono_before, raw_before, counter_before, counter_after, raw_after, mono_after, boot_after, rc = struct.unpack_from('<9q', data, offset)
            if raw_before < 0 or raw_after < raw_before or counter_before < 0 or counter_after < counter_before:
                raise ValueError('Regressing raw/counter observation clock')
            payload = offset + 72
        if min(boot_before, mono_before) < 0 or boot_after < boot_before or mono_after < mono_before:
            raise ValueError('Regressing observation clock')
        calls[rc] += 1
        if rc:
            continue
        for hand, position in [('left', payload), ('right', payload + 368)]:
            raw = data[position:position + 368]
            timestamp, = struct.unpack_from('<q', raw)
            hands[hand].append((timestamp, {'monotonic': mono_after, 'boottime': boot_after,
                                          'monotonic_raw': raw_after, 'qtimer': counter_after}, raw))
    report = {'format_version': header[1], 'observation_clocks': clocks,
              'calls': dict(calls), 'hands': {}, 'optical_tracking_verified': False,
              'coherent_snapshot_verified': False,
              'scope': 'Stock shared-buffer observations; getter success/confidence do not prove freshness or optical tracking'}
    for hand, rows in hands.items():
        stamps = [r[0] for r in rows if r[0] > 0]
        item = {'successful_reads': len(rows), 'positive_timestamps': len(stamps),
                'distinct_positive_timestamps': len(set(stamps)),
                'timestamp_regressions': sum(b < a for a, b in zip(stamps, stamps[1:])),
                'state_confidence_diagnostic_52': dict(Counter(
                    f'{r[2][0x40]},{r[2][0x41]},{r[2][0x52]}' for r in rows))}
        for name in clocks:
            ages = [r[1][name] - r[0] for r in rows if r[0] > 0]
            item[name + '_age_ns'] = {'min': min(ages), 'max': max(ages)} if ages else None
            item[name + '_within_100ms'] = sum(0 <= age <= 100000000 for age in ages)
        report['hands'][hand] = item
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--cc', type=Path, required=True, help='NDK aarch64-linux-android29-clang')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.serial or '\0' in args.serial:
        parser.error('Invalid device serial')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = ROOT / 'tools/capture-pico-stock-controller.c'
    source_hash = digest(source)
    report = {'status': 'started', 'source_sha256': source_hash, 'commands': []}
    remote = '/data/local/tmp/reframed-stock-controller-' + uuid.uuid4().hex
    created = False

    def run(command, *, timeout=30):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        report['commands'].append({'args': command, 'rc': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise ValueError(f'Command failed: {command[0]}: {result.stdout}{result.stderr}')
        return result.stdout.strip()

    def adb(*command):
        return run(['adb', '-s', args.serial, *command])

    def shell(*command):
        return adb('shell', shlex.join(command))

    def identity():
        fingerprint = shell('getprop', 'ro.build.fingerprint')
        boot_id = shell('cat', '/proc/sys/kernel/random/boot_id')
        uuid.UUID(boot_id)
        if fingerprint != FINGERPRINT or shell('getprop', 'ro.product.device') != 'PICOA7H10':
            raise ValueError('Unsupported stock firmware/device')
        if shell('settings', 'get', 'global', 'wifi_on') != '0' or \
                shell('pm', 'list', 'packages', '-d', 'com.picovr.updatesystem') != 'package:com.picovr.updatesystem':
            raise ValueError('Pico must already be offline with updater disabled')
        if shell('sha256sum', LIBRARY).split() != [LIBRARY_SHA256, LIBRARY]:
            raise ValueError('Stock client ABI differs')
        return {'boot_id': boot_id, 'fingerprint': fingerprint, 'library_sha256': LIBRARY_SHA256}

    def power_state():
        text = shell('dumpsys', 'power')
        state = re.search(r'^\s*mWakefulness=(\w+)\s*$', text, re.M)
        interactive = re.search(r'^\s*mHalInteractiveModeEnabled=(true|false)\s*$', text, re.M)
        return {'wakefulness': state[1] if state else None,
                'interactive': interactive[1] == 'true' if interactive else None}

    try:
        before = identity()
        report['identity'] = before
        binary = output / 'stock-controller-probe'
        run([str(args.cc.resolve()), '-std=c11', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
             str(source), '-ldl', '-o', str(binary)])
        elf = binary.read_bytes()
        if elf[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', elf, 18)[0] != 183:
            raise ValueError('Compiler did not produce ARM64 little-endian ELF')
        if digest(source) != source_hash:
            raise ValueError('Source changed during build')
        report['probe_sha256'] = digest(binary)
        shell('mkdir', '-m', '700', remote)
        created = True
        adb('push', str(binary), remote + '/probe')
        if shell('sha256sum', remote + '/probe').split()[0] != report['probe_sha256']:
            raise ValueError('Transferred probe differs')
        shell('chmod', '700', remote + '/probe')
        report['power_before'] = power_state()
        report['continuous_wakefulness_verified'] = False
        shell(remote + '/probe', before['boot_id'], remote + '/capture.bin')
        report['power_after'] = power_state()
        adb('pull', remote + '/capture.bin', str(output / 'capture.bin'))
        data = (output / 'capture.bin').read_bytes()
        report['capture_sha256'] = hashlib.sha256(data).hexdigest()
        if shell('sha256sum', remote + '/capture.bin').split()[0] != report['capture_sha256']:
            raise ValueError('Transferred capture differs')
        report['observation'] = analyze(data)
        if identity() != before:
            raise ValueError('Stock identity changed during observation')
        report['status'] = 'captured'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        try:
            if created:
                shell('rm', '-f', remote + '/probe', remote + '/capture.bin')
                shell('rmdir', remote)
                report['temporary_files_removed'] = True
        except Exception as error:
            report.update(status='failed', cleanup_error=str(error), temporary_files_removed=False)
            raise
        finally:
            (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['observation'], indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    main()
