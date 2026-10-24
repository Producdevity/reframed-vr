#!/usr/bin/env python3
"""Read offline b1977 unit radio addresses; never enables or configures a radio."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

FINGERPRINT = 'Pico/A7H10/PICOA7H10:10/5.8.4.0/smartcm.1696861506:user/test-keys'
HAL = '/vendor/lib64/hw/android.hardware.bluetooth@1.0-impl-qti.so'
HAL_SHA256 = '59f013ff41adbf8e1f2ca350f62938f4602a833d0f97809838bc2c417541af52'


def address(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Missing or malformed radio address')
    data = bytes.fromhex(value.replace(':', ''))
    placeholders = {'02:00:00:00:00:00', '00:00:00:00:5a:ad', '00:03:7f:12:2b:b0'}
    if data[0] & 1 or data in (bytes(6), b'\xff' * 6) or value.lower() in placeholders:
        raise ValueError('Expected a unicast unit address, not a placeholder')
    return value.lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'scope': 'Stock service/sysfs identities; no radio or firmware changes',
              'serial': args.serial, 'commands': [],
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def shell(arguments):
        result = subprocess.run(['adb', '-s', args.serial, 'shell', shlex.join(arguments)],
                                capture_output=True, text=True, timeout=20)
        report['commands'].append({'arguments': arguments, 'returncode': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise RuntimeError('Stock read failed: ' + shlex.join(arguments))
        return result.stdout.strip()

    def snapshot():
        if shell(['getprop', 'ro.serialno']) != args.serial:
            raise ValueError('Device serial differs')
        boot = shell(['cat', '/proc/sys/kernel/random/boot_id'])
        if not boot:
            raise ValueError('Missing stock boot identity')
        if shell(['getprop', 'ro.build.fingerprint']) != FINGERPRINT:
            raise ValueError('Requires the verified Neo3 b1977 build')
        if shell(['sha256sum', HAL]).split()[0] != HAL_SHA256:
            raise ValueError('Bluetooth HAL differs from the verified build')
        if shell(['settings', 'get', 'global', 'wifi_on']) != '0':
            raise ValueError('Wi-Fi must already be disabled')
        for family in ['-4', '-6']:
            if shell(['ip', family, 'route', 'show', 'table', 'main']):
                raise ValueError('Expected an offline device without main-table routes')
        if shell(['cat', '/sys/class/net/wlan0/addr_assign_type']) != '0':
            raise ValueError('Stock WLAN address is not marked permanent')
        wifi = address(shell(['cat', '/sys/class/net/wlan0/address']))
        bluetooth = address(shell(['settings', 'get', 'secure', 'bluetooth_address']))
        manager = shell(['dumpsys', 'bluetooth_manager'])
        enabled = re.findall(r'^\s*enabled:\s*(\w+)\s*$', manager, re.M)
        state = re.findall(r'^\s*state:\s*(\w+)\s*$', manager, re.M)
        addresses = re.findall(r'^\s*address:\s*(\S+)\s*$', manager, re.M)
        if enabled != ['false'] or state != ['OFF'] or len(addresses) != 1:
            raise ValueError('Bluetooth must already be off with one readable stock address')
        if address(addresses[0]) != bluetooth:
            raise ValueError('Stock Bluetooth address sources disagree')
        if shell(['cat', '/proc/sys/kernel/random/boot_id']) != boot:
            raise ValueError('Stock boot changed during snapshot')
        return {'boot_id': boot, 'wifi_address': wifi, 'bluetooth_address': bluetooth}

    first, second = snapshot(), snapshot()
    if first != second:
        raise ValueError('Stock radio identity or boot changed during collection')
    report.update(status='stock-offline-identities-verified', identity=first,
                  fingerprint=FINGERPRINT, bluetooth_hal_sha256=HAL_SHA256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print('Verified stock radio identities saved to ' + str(args.output))


if __name__ == '__main__':
    main()
