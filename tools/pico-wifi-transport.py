#!/usr/bin/env python3
"""Own native Neo3 WLAN startup and firmware fallback until service stop."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import time

spec = importlib.util.spec_from_file_location('wifi_identity', Path(__file__).with_name('pico-wifi-identity.py'))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)

# Unmodified b1977 files used by the accepted minimal QCA6390 startup.
FIRMWARE = {
    'qca6390/amss20.bin': '16350944a77b4e1b5466bec034c96a5f913882599e7ac81cb9bf5cd03a4d9d90',
    'qca6390/m3.bin': '42ac5423ebd35dc5d7f68d8fced32b0617413fb3d0c845e34cde553a33949bba',
    'qca6390/bdwlanq.elf': '23dd0ae04bd5eabf5f5bb028db4b2417639152b5c4dd62e76ce29c15e74da2a8',
    'wlan/qca_cld/qca6390/WCNSS_qcom_cfg.ini': '6e243e4ff92e0521e7d0f0df3d26a44af025c2b99ea065c1bfa2f32c619db0e7',
}
FIRMWARE.update({Path(name).name: digest for name, digest in list(FIRMWARE.items())
                 if name.startswith('qca6390/')})


def file_pin(path, *, uid=0):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_mode & 0o022:
            raise ValueError('Expected root-owned, non-writable firmware/module: ' + str(path))
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    fields = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                            value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if fields(before) != fields(after) or fields(path.stat()) != fields(after):
        raise ValueError('Firmware/module changed while reading: ' + str(path))
    return digest


def firmware_files(custom, release, root=Path('/lib/firmware')):
    roots = [root / 'updates' / release, root / 'updates', root / release, root]
    if custom:
        if not Path(custom).is_absolute() or '\n' in custom:
            raise ValueError('Invalid existing firmware search path')
        roots.insert(0, Path(custom))
    found = {}
    for name, expected in FIRMWARE.items():
        path = next((base / name for base in roots if (base / name).exists()), None)
        if path is None or file_pin(path) != expected:
            raise ValueError('Missing or different b1977 WLAN firmware: ' + name)
        found[name] = {'path': str(path), 'sha256': expected}
    return found


def notify_ready():
    address = os.environ['NOTIFY_SOCKET']
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.connect('\0' + address[1:] if address.startswith('@') else address)
        channel.sendall(b'READY=1\nSTATUS=QCA6390 wlan0 ready; unit identity provisioning follows')


class Backend:
    def __init__(self, report, *, sysfs=Path('/sys')):
        self.report = report
        self.sysfs = sysfs
        self.module = sysfs / 'module/wlan'
        self.fallback = Path('/proc/sys/kernel/firmware_config/ignore_sysfs_fallback')
        self.firmware_path = sysfs / 'module/firmware_class/parameters/path'

    def command(self, args, timeout=10):
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env=os.environ | {'LC_ALL': 'C'})
        self.report.setdefault('commands', []).append({'args': args, 'rc': result.returncode,
                                                       'stderr': result.stderr})
        if result.returncode:
            raise RuntimeError('Wi-Fi startup command failed: ' + repr(args))
        return result.stdout

    def preflight(self):
        if self.module.exists() or any((p / 'phy80211').exists() for p in (self.sysfs / 'class/net').iterdir()):
            raise ValueError('Refusing to adopt an existing WLAN module or wireless interface')
        if (self.sysfs / 'module/cnss2/parameters/daemon_support').read_text().strip() != 'N':
            raise ValueError('Requires kernel patch 0053 and cnss2.daemon_support=0')
        pci = self.sysfs / 'bus/pci/devices/0000:01:00.0'
        if ((pci / 'vendor').read_text().strip() != '0x17cb' or
                (pci / 'device').read_text().strip() != '0x1101' or
                (pci / 'driver').resolve(strict=True).name != 'cnss_pci'):
            raise ValueError('Expected the native QCA6390 PCI device')
        for service in ('NetworkManager.service', 'wpa_supplicant.service'):
            result = subprocess.run(['systemctl', 'show', service, '-p', 'ActiveState', '-p', 'MainPID'],
                                    capture_output=True, text=True, timeout=10)
            properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            if (result.returncode or properties.get('MainPID') != '0' or
                    properties.get('ActiveState') not in ('inactive', 'failed', 'activating')):
                raise ValueError('Network managers must be stopped before WLAN ownership')
        self.path_before = self.firmware_path.read_text()
        self.report['firmware'] = firmware_files(self.path_before.strip(), os.uname().release)
        module_path = Path(self.command(['modinfo', '-n', 'wlan']).strip())
        if not module_path.is_absolute():
            raise ValueError('Expected an installed WLAN module')
        if self.command(['modinfo', '-F', 'vermagic', 'wlan']).split()[0] != os.uname().release:
            raise ValueError('WLAN module kernel release differs')
        self.report['module'] = {'path': str(module_path), 'sha256': file_pin(module_path)}

    def module_identity(self):
        if not self.module.exists():
            return None
        value = self.module.stat()
        return value.st_dev, value.st_ino

    def policy(self):
        if self.firmware_path.read_text() != self.path_before:
            raise RuntimeError('Firmware search path changed during WLAN ownership')
        if self.fallback.read_text().strip() != '1':
            raise RuntimeError('Firmware fallback policy changed during WLAN ownership')

    def load(self):
        self.command(['modprobe', '--first-time', 'wlan'], timeout=75)

    def unload(self):
        self.command(['rmmod', 'wlan'], timeout=45)

    def interface(self):
        path = Path('/sys/class/net/wlan0')
        if not path.exists():
            return None
        interface = identity.Interface('wlan0', self.command)
        try:
            value = interface.snapshot()
        finally:
            interface.close()
        self.command(['udevadm', 'settle', '--timeout=20'], timeout=25)
        properties = self.command(['udevadm', 'info', '--query=property', '--path=' + str(path)])
        link = next((row.split('=', 1)[1] for row in properties.splitlines()
                     if row.startswith('ID_NET_LINK_FILE=')), '')
        if Path(link).name != '10-reframed-pico-wifi.link':
            raise ValueError('Managed interface did not use the installed Pico naming policy')
        self.command(['systemctl', 'is-active', '--quiet', 'sys-subsystem-net-devices-wlan0.device'])
        return {key: value[key] for key in ('ifindex', 'device', 'driver')}

    def same_interface(self, expected):
        path = Path('/sys/class/net/wlan0')
        return {'ifindex': int((path / 'ifindex').read_text()),
                'device': str((path / 'device').resolve(strict=True)),
                'driver': str((path / 'device/driver').resolve(strict=True))} == expected


def own_transport(backend, check_boot, stopped, report, ready, *, seconds=30):
    check_boot()
    backend.preflight()
    original = backend.fallback.read_text()
    if original.strip() not in ('0', '1'):
        raise ValueError('Invalid firmware fallback policy')
    target = backend.fallback.resolve(strict=True)
    report['fallback_before'] = original.strip()
    changed = False
    attempted = False
    owned = None
    try:
        check_boot()
        if stopped():
            return
        changed = original.strip() != '1'
        if changed:
            backend.fallback.write_text('1\n')
        backend.policy()
        if backend.module_identity() is not None:
            raise RuntimeError('WLAN appeared before owned load')
        attempted = True
        backend.load()
        owned = backend.module_identity()
        if owned is None:
            raise RuntimeError('WLAN module did not load')
        deadline = time.monotonic() + seconds
        while not stopped():
            check_boot()
            backend.policy()
            interface = backend.interface()
            if interface is not None:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Managed wlan0 initialization deadline exceeded')
            time.sleep(.1)
        else:
            return
        if stopped():
            return
        report.update(status='wlan-ready', interface=interface)
        ready()
        while not stopped():
            check_boot()
            backend.policy()
            if backend.module_identity() != owned or not backend.same_interface(interface):
                raise RuntimeError('Owned WLAN device disappeared or changed')
            time.sleep(.2)
    finally:
        errors = []
        try:
            check_boot()
            current = backend.module_identity()
            if attempted and current is not None:
                if owned is None or current != owned:
                    raise RuntimeError('Refusing to unload WLAN without verified load ownership')
                backend.unload()
                if backend.module_identity() is not None:
                    raise RuntimeError('Owned WLAN module did not unload')
            report['module_unloaded'] = attempted and backend.module_identity() is None
        except BaseException as error:
            errors.append(str(error))
        try:
            check_boot()
            if backend.fallback.resolve(strict=True) != target:
                raise RuntimeError('Firmware fallback control changed')
            if changed:
                if backend.module_identity() is not None:
                    raise RuntimeError('WLAN remains loaded; keeping its fallback policy')
                current = backend.fallback.read_text()
                if current.strip() != '1' and current != original:
                    raise RuntimeError('Refusing to overwrite an externally changed fallback policy')
                if current != original:
                    backend.fallback.write_text(original)
            if backend.fallback.read_text() != original:
                raise RuntimeError('Firmware fallback restoration did not read back')
            report['fallback_restored'] = True
        except BaseException as error:
            errors.append(str(error))
        if errors:
            report['cleanup_errors'] = errors
            raise RuntimeError('Wi-Fi transport cleanup incomplete: ' + '; '.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    check = lambda: identity.validate_device(args.boot_serial, args.boot_id)
    check()
    report = {'status': 'starting', 'boot_id': args.boot_id,
              'scope': 'Owned WLAN module and temporary firmware fallback; no association or firmware writes'}
    lock = os.open('/run/reframed-pico-wifi-transport.lock', os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, 'w'):
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('Wi-Fi transport lock must be private and root-owned')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600), 'w') as output:
            stopping = False
            def stop(_signal, _frame):
                nonlocal stopping
                stopping = True
            handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
            try:
                own_transport(Backend(report), check, lambda: stopping, report, notify_ready)
                report['status'] = 'stopped-and-restored'
            except BaseException as error:
                report.update(status='failed', error=str(error))
                raise
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
                json.dump(report, output, indent=2)
                output.write('\n')
                print('PICO_WIFI_TRANSPORT ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
