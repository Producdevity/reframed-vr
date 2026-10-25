#!/usr/bin/env python3
"""Provision a native Neo3's verified Wi-Fi address before network startup."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import stat
import struct
import subprocess
import uuid

SOURCE = Path(__file__).resolve().parent
WLAN_MODULE = Path('/sys/module/wlan')
spec = importlib.util.spec_from_file_location('pico_wireless_config', SOURCE / 'pico-wireless-config.py')
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


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
            record.get('fingerprint') != identity.FINGERPRINT or
            record.get('bluetooth_hal_sha256') != identity.HAL_SHA256 or
            record.get('identity', {}).get('boot_serial') != boot_serial):
        raise ValueError('Stock identity receipt does not match this boot serial and firmware')
    return identity.address(record['identity'].get('wifi_address', '')), hashlib.sha256(raw).hexdigest()


def validate_device(boot_serial, boot_id):
    if (platform.system() != 'Linux' or platform.machine() != 'aarch64' or os.geteuid() != 0 or
            not re.fullmatch(r'[A-Za-z0-9]{1,32}', boot_serial) or
            'androidboot.serialno=' + boot_serial not in Path('/proc/cmdline').read_text().split() or
            Path('/proc/device-tree/compatible').read_bytes() != b'qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0' or
            not Path('/run/systemd/system').is_dir()):
        raise ValueError('Requires the selected native Linux Pico Neo3 as root')
    if str(uuid.UUID(boot_id)) != boot_id or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_id:
        raise ValueError('Native boot identity changed')


class Interface:
    def __init__(self, name, run):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', name):
            raise ValueError('Invalid network interface name')
        self.name, self.run = name, run
        self.path = Path('/sys/class/net') / name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self):
        self.sock.close()

    def snapshot(self):
        raw = fcntl.ioctl(self.sock, 0x8913, struct.pack('16sH22x', self.name.encode(), 0))
        flags = struct.unpack_from('16sH', raw)[1]
        info = self.run(['iw', 'dev', self.name, 'info'])
        if (re.findall(r'^Interface (\S+)$', info, re.M) != [self.name] or
                re.findall(r'^\s*type (\S+)$', info, re.M) != ['managed'] or flags & 1 or
                self.run(['iw', 'dev', self.name, 'link']).strip() != 'Not connected.'):
            raise ValueError('Wi-Fi must be a down, unassociated managed interface')
        parent = (self.path / 'device').resolve(strict=True)
        driver = (self.path / 'device/driver').resolve(strict=True)
        if driver.name != 'cnss_pci' or not WLAN_MODULE.is_dir() or not any(
                (p / 'vendor').is_file() and (p / 'device').is_file() and
                (p / 'vendor').read_text().strip() == '0x17cb' and
                (p / 'device').read_text().strip() == '0x1101' for p in [parent, *parent.parents]):
            raise ValueError('Expected the native QCA6390 WLAN device')
        address = (self.path / 'address').read_text().strip().lower()
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', address):
            raise ValueError('Malformed interface address')
        return {'address': address, 'flags': flags,
                'ifindex': int((self.path / 'ifindex').read_text()),
                'device': str(parent), 'driver': str(driver)}

    def set_address(self, address):
        fcntl.ioctl(self.sock, 0x8924, struct.pack('16sH6s16x', self.name.encode(), 1,
                                               bytes.fromhex(address.replace(':', ''))))


def provision(address, interface, report, check_boot):
    check_boot()
    before = interface.snapshot()
    report.update(before=before, address_write_attempted=False)

    def verify():
        check_boot()
        value = interface.snapshot()
        if any(value[key] != before[key] for key in ('flags', 'ifindex', 'device', 'driver')):
            raise RuntimeError('Wi-Fi interface identity or flags changed')
        return value

    try:
        if before['address'] != address:
            verify()
            report['address_write_attempted'] = True
            interface.set_address(address)
        after = verify()
        if after['address'] != address:
            raise RuntimeError('Wi-Fi address readback differs from the unit identity')
        report['after'] = after
    except BaseException as error:
        if report['address_write_attempted']:
            try:
                current = verify()
                if current['address'] != before['address']:
                    interface.set_address(before['address'])
                restored = verify()
                if restored != before:
                    raise RuntimeError('Wi-Fi address restoration readback failed')
                report['rollback'] = {'status': 'restored', 'after': restored}
            except BaseException as restore_error:
                report['rollback'] = {'status': 'failed', 'error': str(restore_error)}
                raise RuntimeError('Wi-Fi address update failed; restoration incomplete: ' +
                                   str(restore_error)) from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--interface', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    validate_device(args.boot_serial, args.boot_id)
    address, digest = load_identity(args.identity, args.boot_serial)
    report = {'boot_id': args.boot_id, 'boot_serial': args.boot_serial,
              'identity_sha256': digest, 'interface': args.interface,
              'scope': 'Unit Wi-Fi address only; interface remains down and unassociated', 'commands': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(output, 'w') as stream:
        lock = None
        handlers = {}
        try:
            lock = os.open('/run/reframed-pico-wifi-identity.lock',
                           os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
                raise ValueError('Wi-Fi identity lock must be private and root-owned')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def run(command):
                p = subprocess.run(command, capture_output=True, text=True, timeout=15,
                                   env=os.environ | {'LC_ALL': 'C'})
                report['commands'].append({'args': command, 'rc': p.returncode,
                                           'stdout': p.stdout, 'stderr': p.stderr})
                if p.returncode:
                    raise RuntimeError('Wi-Fi command failed: ' + repr(command))
                return p.stdout

            for service in ('NetworkManager.service', 'wpa_supplicant.service'):
                p = subprocess.run(['systemctl', 'is-active', '--quiet', service], timeout=10)
                if p.returncode not in (3, 4):
                    raise ValueError('Network managers must be stopped before provisioning')
            interface = Interface(args.interface, run)
            try:
                def interrupted(signum, _frame):
                    for sig in handlers:
                        signal.signal(sig, signal.SIG_IGN)
                    raise InterruptedError('Wi-Fi provisioning interrupted by signal ' + str(signum))
                for sig in (signal.SIGTERM, signal.SIGINT):
                    handlers[sig] = signal.signal(sig, interrupted)
                provision(address, interface, report,
                          lambda: validate_device(args.boot_serial, args.boot_id))
            finally:
                interface.close()
            report['status'] = 'unit-address-verified-down'
        except BaseException as error:
            report.update(status='failed', error=str(error))
            raise
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
            if lock is not None:
                os.close(lock)
            json.dump(report, stream, indent=2)
            stream.write('\n')
    print('Verified native Wi-Fi unit identity; interface remains down')


if __name__ == '__main__':
    main()
