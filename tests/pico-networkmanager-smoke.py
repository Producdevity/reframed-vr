"""Parent-invoked test for the prepared, initially masked native Pico radio environment."""
from pathlib import Path
import hashlib, json, os, subprocess, time

def exercise(out):
    out = Path(out)
    out.mkdir(mode=448)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    owner = 'reframed-pico-wifi-transport.service'
    identity = 'reframed-pico-wifi-identity@wlan0.service'
    manager = 'NetworkManager.service'
    fallback = Path('/proc/sys/kernel/firmware_config/ignore_sysfs_fallback')
    before = fallback.read_text()
    report = {'boot_id': boot, 'status': 'starting', 'commands': [], 'cycles': [], 'scope': 'Installed NetworkManager dependency startup and teardown, unassociated; no credentials or user profiles'}

    def save():
        (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(args, timeout=30, check=True):
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=os.environ | {'LC_ALL': 'C'})
        report['commands'].append({'args': args, 'rc': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
        save()
        if check and p.returncode:
            raise RuntimeError(str(args) + ': ' + p.stderr)
        return p.stdout.strip()
    try:
        assert os.geteuid() == 0 and os.uname().machine == 'aarch64' and ('androidboot.serialno=c980c8d4' in Path('/proc/cmdline').read_text().split())
        assert not Path('/sys/module/wlan').exists()
        for p in [Path('/etc/NetworkManager/system-connections'), Path('/run/NetworkManager/system-connections')]:
            assert not p.exists() or not list(p.iterdir()), str(p)
        assert run(['systemctl', 'show', manager, '-p', 'MainPID', '--value']) == '0'
        run(['systemctl', 'unmask', '--runtime', manager, 'wpa_supplicant.service'])
        run(['systemctl', 'enable', '--runtime', identity])
        run(['systemctl', 'daemon-reload'])
        for cycle in range(2):
            started = time.monotonic_ns()
            run(['systemctl', 'start', manager], timeout=160)
            assert run(['systemctl', 'is-active', manager]) == 'active'
            assert run(['systemctl', 'is-active', owner]) == 'active'
            assert run(['systemctl', 'is-active', identity]) == 'active'
            inv = run(['systemctl', 'show', owner, '-p', 'InvocationID', '--value'])
            assert inv
            identity_report = json.loads(Path('/run/reframed-pico-wifi-wlan0/identity.json').read_text())
            assert identity_report['status'] == 'unit-address-verified-down'
            (out / ('identity-' + str(cycle) + '.json')).write_text(json.dumps(identity_report, indent=2) + '\n')
            radio_before = run(['nmcli', 'radio', 'wifi'])
            assert radio_before in ['enabled', 'disabled']
            if radio_before == 'disabled':
                run(['nmcli', 'radio', 'wifi', 'on'])
            end = time.monotonic() + 25
            while True:
                state = run(['nmcli', '-g', 'GENERAL.STATE', 'device', 'show', 'wlan0'])
                if state.startswith('30 '):
                    break
                assert time.monotonic() < end, state
                time.sleep(0.25)
            assert run(['nmcli', '-g', 'GENERAL.CONNECTION', 'device', 'show', 'wlan0']) in ['--', '']
            assert run(['iw', 'dev', 'wlan0', 'link']) == 'Not connected.'
            interfaces = run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'])
            profiles = run(['nmcli', '-t', '-f', 'TYPE', 'connection', 'show'])
            assert '802-11-wireless' not in profiles.splitlines()
            routes = {'ipv4': [line for line in Path('/proc/net/route').read_text().splitlines()[1:] if line.split()[0] == 'wlan0'], 'ipv6': [line for line in Path('/proc/net/ipv6_route').read_text().splitlines() if line.split()[-1] == 'wlan0']}
            assert not any((line.split()[1] == '00000000' and line.split()[7] == '00000000' for line in routes['ipv4']))
            assert not any((line.split()[0] == '0' * 32 and line.split()[1] == '00' for line in routes['ipv6']))
            row = {'cycle': cycle, 'startup_ns': time.monotonic_ns() - started, 'owner_invocation': inv, 'state': state, 'devices': interfaces, 'routes': routes, 'radio_before': radio_before}
            if radio_before == 'disabled':
                run(['nmcli', 'radio', 'wifi', 'off'])
            run(['systemctl', 'stop', manager], timeout=150)
            end = time.monotonic() + 140
            while Path('/sys/module/wlan').exists():
                assert time.monotonic() < end, 'WLAN owner did not unload after NM stop'
                time.sleep(0.2)
            assert fallback.read_text() == before
            row['unloaded_after_manager_stop'] = True
            report['cycles'].append(row)
            save()
        assert len({r['owner_invocation'] for r in report['cycles']}) == 2
        report['status'] = 'networkmanager-start-stop-verified'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = repr(error)
        raise
    finally:
        run(['systemctl', 'stop', manager], timeout=150, check=False)
        run(['systemctl', 'disable', '--runtime', identity], check=False)
        run(['systemctl', 'mask', '--runtime', manager, 'wpa_supplicant.service'], check=False)
        report['cleanup_verified'] = not Path('/sys/module/wlan').exists() and fallback.read_text() == before
        report['journal'] = run(['journalctl', '--no-pager', '-u', manager, '-u', owner, '-u', identity, '-n', '180'], check=False)
        save()
    return report
