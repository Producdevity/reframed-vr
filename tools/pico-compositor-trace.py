#!/usr/bin/env python3
"""Arm a dedicated Pico CPU trace before exec, then run as the compositor user."""
import argparse
import json
import os
from pathlib import Path
import pwd

EVENTS = ('sched/sched_switch', 'sched/sched_wakeup',
          'raw_syscalls/sys_enter', 'raw_syscalls/sys_exit')


def arm(instance, pid):
    if pid <= 0 or (instance / 'tracing_on').read_text().strip() != '0':
        raise ValueError('Expected an idle dedicated trace instance')
    selection = (instance / 'set_event_pid').read_text().strip()
    if selection not in ('', 'no pid'):
        raise ValueError('Trace instance already has a PID selection')
    if not (instance / 'options/event-fork').is_file():
        raise ValueError('Kernel does not expose event-fork inheritance')
    for event in EVENTS:
        if (instance / 'events' / event / 'enable').read_text().strip() != '0':
            raise ValueError('Trace event already enabled: ' + event)
    clock = instance / 'trace_clock'
    if 'mono' not in clock.read_text().replace('[', '').replace(']', '').split():
        raise ValueError('Monotonic trace clock unavailable')
    clock.write_text('mono')
    (instance / 'trace').write_text('')
    (instance / 'options/event-fork').write_text('1')
    if (instance / 'options/event-fork').read_text().strip() != '1':
        raise ValueError('Kernel did not enable PID inheritance')
    (instance / 'set_event_pid').write_text(str(pid))
    if (instance / 'set_event_pid').read_text().split() != [str(pid)]:
        raise ValueError('Kernel did not select the launching PID')
    for event in EVENTS:
        (instance / 'events' / event / 'enable').write_text('1')
    (instance / 'tracing_on').write_text('1')
    (instance / 'trace_marker').write_text('PICO_COMPOSITOR_PRE_EXEC pid=' + str(pid))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, required=True)
    parser.add_argument('--boot', required=True)
    parser.add_argument('--user', default='vr')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not Path(command[0]).is_absolute():
        parser.error('An absolute compositor command is required')
    if os.geteuid() != 0 or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != args.boot:
        parser.error('Wrong native boot or launcher identity')
    if args.instance.parent not in (Path('/sys/kernel/debug/tracing/instances'),
                                    Path('/sys/kernel/tracing/instances')):
        parser.error('Expected a dedicated tracefs instance')
    if not args.instance.name.startswith('reframed-pico-'):
        parser.error('Unexpected trace instance name')
    user = pwd.getpwnam(args.user)
    if user.pw_uid == 0:
        parser.error('Compositor must run without root privileges')
    arm(args.instance, os.getpid())
    print('PICO_COMPOSITOR_TRACE_ARMED ' + json.dumps({
        'pid': os.getpid(), 'uid': user.pw_uid, 'instance': str(args.instance),
        'events': EVENTS, 'event_fork': True}), flush=True)
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    environment = os.environ | {'HOME': user.pw_dir, 'USER': user.pw_name,
                                 'LOGNAME': user.pw_name, 'SHELL': user.pw_shell}
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()
