#!/usr/bin/env python3
"""Own the native Neo3 Bluetooth UART until systemd stops the service."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

spec = importlib.util.spec_from_file_location('bluetooth_identity',
                                            Path(__file__).with_name('pico-bluetooth-identity.py'))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def notify_ready():
    address = os.environ['NOTIFY_SOCKET']
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.connect(address)
        channel.sendall(b'READY=1\nSTATUS=QCA6390 UART ready; identity provisioning follows')


def radio(sysfs=Path('/sys')):
    matches = [p for p in (sysfs / 'class/rfkill').glob('rfkill*')
               if (p / 'name').read_text().strip() == 'bt_power']
    if (len(matches) != 1 or (matches[0] / 'type').read_text().strip() != 'bluetooth' or
            (matches[0] / 'hard').read_text().strip() != '0'):
        raise ValueError('Expected the unblocked Pico bt_power rfkill device')
    soft = matches[0] / 'soft'
    original = soft.read_text().strip()
    if original not in ('0', '1'):
        raise ValueError('Invalid Bluetooth rfkill state')
    return soft, original


def own_transport(check_boot, stopped, report, ready, *, sysfs=Path('/sys'),
                  run=subprocess.run, spawn=subprocess.Popen, seconds=35,
                  settle_seconds=18):
    check_boot()
    inactive = run(['systemctl', 'is-active', '--quiet', 'bluetooth.service'], timeout=10)
    if inactive.returncode not in (3, 4):
        raise ValueError('BlueZ must be stopped before attaching its UART')
    if list((sysfs / 'class/bluetooth').glob('hci*')):
        raise ValueError('Refusing to adopt or replace an existing Bluetooth adapter')
    soft, original = radio(sysfs)
    target = soft.resolve(strict=True)
    child = None
    try:
        check_boot()
        report['rfkill_before'] = original
        soft.write_text('0\n')
        if soft.read_text().strip() != '0':
            raise RuntimeError('Bluetooth rfkill unblock did not read back')
        # Retain the power-up interval used by the verified native UART test.
        time.sleep(.5)
        child = spawn(['btattach', '-B', '/dev/ttyHS0', '-P', 'qca', '-S', '115200'])
        report['child_pid'] = child.pid
        attached = time.monotonic()
        deadline = attached + seconds
        report['startup_settle_seconds'] = settle_seconds
        while True:
            check_boot()
            if stopped():
                return
            code = child.poll()
            if code is not None:
                raise RuntimeError('Owned btattach exited: ' + str(code))
            adapter = sysfs / 'class/bluetooth/hci0'
            # Preserve the successful b1977 manual startup interval: management
            # info alone became available before address programming was reliable.
            if adapter.exists() and time.monotonic() - attached >= settle_seconds:
                identity.validate_transport(0, sysfs)
                result = run(['btmgmt', '--index', '0', 'info'], capture_output=True,
                             text=True, timeout=5, env=os.environ | {'LC_ALL': 'C'})
                if not result.returncode:
                    try:
                        info = identity.adapter_info(result.stdout, 0)
                    except identity.AdapterUnavailable:
                        pass
                    else:
                        # Both management and HCIGETDEVINFO mask HCI_UP during auto-off.
                        # HCIDEVDOWN cancels that phase and synchronously closes HCI.
                        kernel = run(['hciconfig', 'hci0', 'down'], capture_output=True, text=True,
                                     timeout=10, env=os.environ | {'LC_ALL': 'C'})
                        if kernel.returncode:
                            raise RuntimeError('Cannot close startup HCI before provisioning')
                        identity.validate_transport(0, sysfs)
                        report['initial_adapter'] = info
                        report['kernel_closed_before_identity'] = True
                        break
            if time.monotonic() >= deadline:
                raise TimeoutError('QCA6390 UART initialization deadline exceeded')
            time.sleep(.1)
        check_boot()
        if stopped():
            return
        if child.poll() is not None:
            raise RuntimeError('Owned btattach exited before readiness')
        report['status'] = 'uart-ready'
        ready()
        last_adapter = time.monotonic()
        while not stopped():
            check_boot()
            if (sysfs / 'class/bluetooth/hci0').exists():
                identity.validate_transport(0, sysfs)
                last_adapter = time.monotonic()
            elif time.monotonic() - last_adapter > 5:
                raise RuntimeError('Owned HCI adapter disappeared')
            if child.poll() is not None:
                raise RuntimeError('Owned btattach exited while serving Bluetooth')
            time.sleep(.2)
    finally:
        errors = []
        if child is not None:
            try:
                if child.poll() is None:
                    child.terminate()
                try:
                    report['child_returncode'] = child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    report['child_returncode'] = child.wait(timeout=3)
                deadline = time.monotonic() + 3
                while (sysfs / 'class/bluetooth/hci0').exists():
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Owned HCI adapter did not detach')
                    time.sleep(.1)
                report['adapter_detached'] = True
            except BaseException as error:
                errors.append(str(error))
        try:
            check_boot()
            if soft.resolve(strict=True) != target:
                raise RuntimeError('Bluetooth rfkill device changed during ownership')
            soft.write_text(original + '\n')
            if soft.read_text().strip() != original:
                raise RuntimeError('Bluetooth rfkill restoration did not read back')
            report['rfkill_restored'] = True
        except BaseException as error:
            errors.append(str(error))
        if errors:
            report['cleanup_errors'] = errors
            raise RuntimeError('Bluetooth transport cleanup incomplete: ' + '; '.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    identity.validate_device(args.boot_serial, args.boot_id, require_uart=False)
    report = {'status': 'starting', 'boot_id': args.boot_id,
              'scope': 'Volatile UART and rfkill ownership; no pairing or partition writes'}
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                           0o600), 'w') as output:
        stopping = False
        def stop(_signum, _frame):
            nonlocal stopping
            stopping = True
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            for command in [['modprobe', 'btqca'], ['modprobe', 'hci_uart',
                            'qca6390_tty=1', 'qca_version_only=0']]:
                subprocess.run(command, check=True, timeout=10)
            identity.validate_device(args.boot_serial, args.boot_id)
            if Path('/sys/module/hci_uart/parameters/qca_version_only').read_text().strip() != 'N':
                raise ValueError('Version-only diagnostic transport is not usable')
            if not Path('/dev/ttyHS0').is_char_device():
                raise ValueError('Expected the Pico ttyHS0 character device')
            check = lambda: identity.validate_device(args.boot_serial, args.boot_id)
            own_transport(check, lambda: stopping, report, notify_ready)
            report['status'] = 'stopped-and-restored'
        except BaseException as error:
            report.update(status='failed', error=str(error))
            raise
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            json.dump(report, output, indent=2)
            output.write('\n')
            print('PICO_BLUETOOTH_TRANSPORT ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
