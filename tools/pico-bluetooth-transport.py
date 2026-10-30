#!/usr/bin/env python3
"""Own the native Neo3 Bluetooth UART until systemd stops the service."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import stat
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


def uart_power_target(sysfs=Path('/sys')):
    uart = (sysfs / 'class/tty/ttyHS0').resolve(strict=True)
    matches = [p for p in uart.parents if p.name == '998000.qcom,qup_uart']
    if len(matches) != 1:
        raise ValueError('Expected the Pico Bluetooth GENI UART at 0x998000')
    device = matches[0]
    driver = sysfs / 'bus/platform/drivers/msm_geni_serial'
    if ((device / 'driver').resolve(strict=True) != driver.resolve(strict=True) or
            (driver / device.name).resolve(strict=True) != device or
            (device / 'subsystem').resolve(strict=True) !=
            (sysfs / 'bus/platform').resolve(strict=True) or
            (device / 'of_node/compatible').read_bytes() != b'qcom,msm-geni-serial-hs\0' or
            (device / 'of_node/qcom,wakeup-byte').read_bytes() != b'\0\0\0\xfd'):
        raise ValueError('Unexpected Pico Bluetooth UART binding')
    control = device / 'power/control'
    if control.is_symlink() or control.read_text().strip() not in ('on', 'auto'):
        raise ValueError('Unexpected UART runtime-power policy')
    return control.resolve(strict=True)


def require_uart_awake(control, sysfs=Path('/sys')):
    if uart_power_target(sysfs) != control:
        raise RuntimeError('Bluetooth UART changed during ownership')
    if (control.read_text().strip() != 'on' or
            control.with_name('runtime_status').read_text().strip() != 'active'):
        raise RuntimeError('Owned Bluetooth UART is not runtime-active')


class TTYGuard:
    def __init__(self, sysfs=Path('/sys')):
        uart_power_target(sysfs)
        expected = tuple(int(value) for value in
                         (sysfs / 'class/tty/ttyHS0/dev').read_text().strip().split(':'))
        self.fd = os.open('/dev/ttyHS0', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK |
                          os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(self.fd)
            if (not stat.S_ISCHR(info.st_mode) or
                    (os.major(info.st_rdev), os.minor(info.st_rdev)) != expected):
                raise ValueError('TTY descriptor does not match the validated Bluetooth UART')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            descriptor, self.fd = self.fd, None
            os.close(descriptor)


def own_transport(check_boot, stopped, report, ready, *, sysfs=Path('/sys'),
                  run=subprocess.run, spawn=subprocess.Popen, seconds=35,
                  settle_seconds=18, open_guard=TTYGuard):
    check_boot()
    inactive = run(['systemctl', 'is-active', '--quiet', 'bluetooth.service'], timeout=10)
    if inactive.returncode not in (3, 4):
        raise ValueError('BlueZ must be stopped before attaching its UART')
    if list((sysfs / 'class/bluetooth').glob('hci*')):
        raise ValueError('Refusing to adopt or replace an existing Bluetooth adapter')
    soft, original = radio(sysfs)
    target = soft.resolve(strict=True)
    control = uart_power_target(sysfs)
    original_policy = control.read_text().strip()
    report['uart_runtime_power'] = {'control': str(control), 'original_policy': original_policy,
                                   'initial_status': control.with_name('runtime_status').read_text().strip(),
                                   'restored': False}
    child = None
    guard = None
    policy_written = False
    try:
        check_boot()
        guard = open_guard(sysfs)
        report['tty_guard_opened'] = True
        # This vendor QCA TTY driver has no GENI clock-vote implementation.
        control.write_text('on\n')
        policy_written = True
        require_uart_awake(control, sysfs)
        report['uart_runtime_power']['held_policy'] = 'on'
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
            require_uart_awake(control, sysfs)
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
            require_uart_awake(control, sysfs)
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
            except BaseException as error:
                errors.append(str(error))
        try:
            check_boot()
            if uart_power_target(sysfs) != control:
                raise RuntimeError('Bluetooth UART changed before power-policy restoration')
            if policy_written and control.read_text().strip() != 'on':
                raise RuntimeError('Bluetooth UART power policy changed outside ownership')
            if policy_written:
                if guard is None or (child is not None and 'child_returncode' not in report):
                    raise RuntimeError('Cannot restore UART policy before owned child is reaped')
                # GENI must suspend while the final TTY descriptor still owns its wake IRQ.
                control.write_text(original_policy + '\n')
                report['uart_runtime_power']['restored_before_tty_close'] = True
            if control.read_text().strip() != original_policy:
                raise RuntimeError('Bluetooth UART power-policy restoration did not read back')
            report['uart_runtime_power']['restored'] = True
        except BaseException as error:
            errors.append(str(error))
        try:
            if guard is not None:
                guard.close()
                report['tty_guard_closed'] = True
            if child is not None:
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
