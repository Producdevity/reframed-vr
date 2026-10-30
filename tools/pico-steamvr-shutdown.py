#!/usr/bin/env python3
"""Close an owned transient SteamVR session and retain systemd's final exit results."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def unit_name(value):
    if value != 'pico-ui-seatd' and not re.fullmatch(r'pico-steamvr-[a-z0-9-]+', value):
        raise ValueError('Not an owned Pico SteamVR unit: ' + value)
    return value


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def record_exit(directory, unit):
    unit_name(unit)
    record = {'unit': unit, 'boot_id': boot_id(),
              'monotonic_ns': time.monotonic_ns(),
              'result': os.environ.get('SERVICE_RESULT'),
              'code': os.environ.get('EXIT_CODE'), 'status': os.environ.get('EXIT_STATUS')}
    with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(record, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.link(temporary, directory / (unit + '.json'))
        finally:
            temporary.unlink()


def close_session(units, server, compositor, command, directory, *, run=subprocess.run,
                  clock=time.monotonic, sleep=time.sleep, grace_seconds=20, allow_partial=False):
    units = [unit_name(unit) for unit in units]
    server, compositor = unit_name(server), unit_name(compositor)
    missing = [unit for unit in (server, compositor) if unit not in units]
    if len(set(units)) != len(units) or server == compositor or (missing and not allow_partial):
        raise ValueError('Invalid owned session')
    boot = boot_id()
    report = {'boot_id': boot, 'request': None, 'natural_core_exit': False,
              'stops': [], 'exits': {}, 'errors': [], 'clean_core_shutdown': False,
              'missing_core_units': missing}
    request_started_ns = time.monotonic_ns()
    report['request_started_ns'] = request_started_ns

    def invoke(args, timeout):
        result = run(args, capture_output=True, text=True, timeout=timeout)
        return {'command': args, 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}

    def receipt(unit):
        path = directory / (unit + '.json')
        if not path.exists():
            return None
        row = json.loads(path.read_text())
        if not isinstance(row, dict):
            raise ValueError('Invalid exit receipt: ' + unit)
        if row.get('unit') != unit or row.get('boot_id') != boot:
            raise ValueError('Exit receipt identity mismatch: ' + unit)
        if type(row.get('monotonic_ns')) is not int or row['monotonic_ns'] < request_started_ns:
            raise ValueError('Exit receipt predates this shutdown: ' + unit)
        return row

    try:
        if missing:
            report['request_skipped'] = 'Core session did not fully start'
        else:
            report['request'] = invoke(command, 15)
        if report['request'] is not None and report['request']['returncode'] == 0:
            end = clock() + grace_seconds
            while clock() < end:
                if receipt(server) and receipt(compositor):
                    report['natural_core_exit'] = True
                    break
                sleep(.1)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['errors'].append('quit: ' + repr(error))
    infrastructure = [u for u in units if u == 'pico-ui-seatd' or u.startswith('pico-steamvr-xvfb-')]
    stop_order = [u for u in reversed(units) if u not in infrastructure] + list(reversed(infrastructure))
    for unit in stop_order:
        try:
            stopped = invoke(['systemctl', 'stop', unit], 15)
            report['stops'].append(stopped)
            if stopped['returncode'] and receipt(unit) is None:
                report['errors'].append(unit + ': stop failed without a final exit receipt')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['errors'].append(unit + ': ' + repr(error))
    for unit in units:
        try:
            report['exits'][unit] = receipt(unit)
        except (OSError, ValueError) as error:
            report['errors'].append(unit + ': ' + repr(error))
    report['clean_core_shutdown'] = (report['natural_core_exit'] and not report['errors'] and
        all(report['exits'].get(unit) and
            (report['exits'][unit].get('result'), report['exits'][unit].get('code'), report['exits'][unit].get('status')) ==
            ('success', 'exited', '0') for unit in (server, compositor)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', metavar='UNIT')
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--units', nargs='+')
    parser.add_argument('--server')
    parser.add_argument('--compositor')
    parser.add_argument('--allow-partial', action='store_true',
                        help='Clean up registered units after an incomplete startup; never qualifies clean core shutdown')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.record:
        record_exit(args.directory, args.record)
        return
    if not args.units or not args.server or not args.compositor or args.command[:1] != ['--'] or len(args.command) < 2:
        parser.error('Owned units, server, compositor and -- quit command are required')
    report = close_session(args.units, args.server, args.compositor, args.command[1:], args.directory,
                           allow_partial=args.allow_partial)
    (args.directory / 'shutdown.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PICO_STEAMVR_SHUTDOWN ' + json.dumps(report), flush=True)
    raise SystemExit(0 if report['clean_core_shutdown'] else 1)


if __name__ == '__main__':
    main()
