#!/usr/bin/env python3
"""Provision the selected native Neo3's Bluetooth address while it is unpowered."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import time
import uuid

FINGERPRINT = 'Pico/A7H10/PICOA7H10:10/5.8.4.0/smartcm.1696861506:user/test-keys'
HAL_SHA256 = '59f013ff41adbf8e1f2ca350f62938f4602a833d0f97809838bc2c417541af52'


class AdapterUnavailable(RuntimeError):
    pass


def validate_transport(index, sysfs=Path('/sys')):
    adapter = (sysfs / 'class/bluetooth' / ('hci' + str(index))).resolve(strict=True)
    uart = (sysfs / 'class/tty/ttyHS0').resolve(strict=True)
    if adapter.parent != uart:
        raise ValueError('Bluetooth adapter is not attached to the Pico ttyHS0 transport')


def load_identity(path, boot_serial):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 0 < info.st_size <= 65536:
            raise ValueError('Expected a bounded private stock identity receipt')
        raw = stream.read(65537)
    if len(raw) != info.st_size:
        raise ValueError('Identity receipt changed while reading')
    record = json.loads(raw)
    if (record.get('status') != 'stock-offline-identities-verified' or
            record.get('fingerprint') != FINGERPRINT or record.get('bluetooth_hal_sha256') != HAL_SHA256 or
            record.get('identity', {}).get('boot_serial') != boot_serial):
        raise ValueError('Stock identity receipt does not match this boot serial and firmware')
    address = record['identity'].get('bluetooth_address', '')
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address):
        raise ValueError('Malformed unit Bluetooth address')
    octets = bytes.fromhex(address.replace(':', ''))
    if (octets[0] & 1 or octets in (bytes(6), b'\xff'*6) or
            address.lower() in ('02:00:00:00:00:00', '00:00:00:00:5a:ad', '00:03:7f:12:2b:b0')):
        raise ValueError('Expected the unit address, not a placeholder')
    return address.lower(), hashlib.sha256(raw).hexdigest()


def validate_device(boot_serial, boot_id, *, require_uart=True):
    if (platform.system() != 'Linux' or platform.machine() != 'aarch64' or os.geteuid() != 0 or
            not re.fullmatch(r'[A-Za-z0-9]{1,32}', boot_serial) or
            'androidboot.serialno='+boot_serial not in Path('/proc/cmdline').read_text().split() or
            Path('/proc/device-tree/compatible').read_bytes() != b'qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0' or
            not Path('/run/systemd/system').is_dir()):
        raise ValueError('Requires the selected native Linux Pico Neo3 as root')
    if str(uuid.UUID(boot_id)) != boot_id or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_id:
        raise ValueError('Native boot identity changed')
    if require_uart and Path('/sys/module/hci_uart/parameters/qca6390_tty').read_text().strip() != 'Y':
        raise ValueError('Requires the verified QCA6390 TTY transport')


def adapter_info(text, index):
    headers = re.findall(r'^hci(\d+):', text, re.M)
    addresses = re.findall(r'^\s*addr ([0-9a-fA-F:]{17}) version (\d+) manufacturer (\d+) class \S+', text, re.M)
    settings = re.findall(r'^[ \t]*current settings:[ \t]*([^\r\n]*)', text, re.M)
    options = re.findall(r'^[ \t]*supported options:[ \t]*([^\r\n]*)', text, re.M)
    if not headers and not addresses:
        raise AdapterUnavailable('Adapter is temporarily unavailable')
    if (not headers or any(int(value) != index for value in headers) or len(addresses) != 1 or
            len(settings) != 1 or len(options) != 1 or 'public-address' not in options[0].split() or
            addresses[0][1:] != ('11', '29')):
        raise ValueError('Expected one QCA6390 adapter with public-address configuration')
    current = settings[0].split()
    if set(current) & {'powered', 'connectable', 'discoverable', 'advertising'}:
        raise ValueError('Bluetooth must remain unpowered and non-discoverable')
    return {'address': addresses[0][0].lower(), 'settings': current}


def provision(index, address, run, report, check_boot, seconds=15):
    if type(index) is not int or not 0 <= index <= 255:
        raise ValueError('Invalid HCI adapter index')
    check_boot()
    report['before'] = adapter_info(run(['btmgmt', '--index', str(index), 'info']), index)
    report['address_write_attempted'] = report['before']['address'] != address

    def readback(expected=None):
        deadline = time.monotonic()+seconds
        while True:
            check_boot()
            try:
                after = adapter_info(run(['btmgmt', '--index', str(index), 'info']), index)
            except AdapterUnavailable:
                if time.monotonic() >= deadline:
                    raise
            else:
                if expected is None or after['address'] == expected:
                    return after
            if time.monotonic() >= deadline:
                raise RuntimeError('Bluetooth unit address readback did not complete')
            time.sleep(.2)

    write_started = False
    try:
        if report['address_write_attempted']:
            check_boot()
            write_started = True
            run(['btmgmt', '--index', str(index), 'public-addr', address])
        report['after'] = readback(address)
    except BaseException as error:
        if write_started:
            rollback = report['rollback'] = {'status': 'started'}
            try:
                current = readback()
                original = report['before']['address']
                if current['address'] != original:
                    check_boot()
                    run(['btmgmt', '--index', str(index), 'public-addr', original])
                rollback.update(status='restored', after=readback(original))
            except BaseException as restore_error:
                rollback.update(status='failed', error=str(restore_error))
                raise RuntimeError('Bluetooth address update failed; restoration incomplete: ' +
                                   str(restore_error)) from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.index <= 255:
        parser.error('Invalid HCI adapter index')
    validate_device(args.boot_serial, args.boot_id)
    validate_transport(args.index)
    address, source_sha = load_identity(args.identity, args.boot_serial)
    report = {'status': 'started', 'boot_id': args.boot_id, 'boot_serial': args.boot_serial,
              'identity_sha256': source_sha, 'scope': 'Native volatile public-address configuration; no discovery, pairing or firmware partition writes',
              'commands': []}
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600), 'w') as output:
        lock = None
        handlers = {}
        try:
            lock = os.open('/run/reframed-pico-bluetooth-identity.lock', os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
                raise ValueError('Expected a private root-owned identity lock')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            inactive = subprocess.run(['systemctl', 'is-active', '--quiet', 'bluetooth.service'], timeout=10)
            if inactive.returncode not in (3, 4):
                raise ValueError('BlueZ must be stopped before provisioning')

            def run(command):
                if command[-2] == 'public-addr':
                    validate_transport(args.index)
                result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                        env=os.environ | {'LC_ALL': 'C'})
                report['commands'].append({'args': command, 'rc': result.returncode,
                                           'stdout': result.stdout, 'stderr': result.stderr})
                if result.returncode:
                    if command[-1] == 'info':
                        raise AdapterUnavailable('Bluetooth adapter info unavailable; see receipt')
                    raise RuntimeError('Bluetooth management command failed; see receipt')
                if command[-1] == 'info':
                    validate_transport(args.index)
                return result.stdout

            def interrupted(signum, _frame):
                for sig in handlers:
                    signal.signal(sig, signal.SIG_IGN)
                raise InterruptedError('Bluetooth provisioning interrupted by signal ' + str(signum))

            for sig in (signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, interrupted)
            provision(args.index, address, run, report, lambda: validate_device(args.boot_serial, args.boot_id))
            report['status'] = 'unit-address-verified-unpowered'
        except BaseException as error:
            report.update(status='failed', error=str(error))
            raise
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            if lock is not None:
                os.close(lock)
            json.dump(report, output, indent=2)
            output.write('\n')
    print('Verified native Bluetooth unit identity; adapter remains unpowered')


if __name__ == '__main__':
    main()
