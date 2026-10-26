#!/usr/bin/env python3
"""Arm a dedicated Pico CPU trace before exec, then run as the compositor user."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re

EVENTS = ('sched/sched_switch', 'sched/sched_wakeup',
          'raw_syscalls/sys_enter', 'raw_syscalls/sys_exit')


def workqueue_pool_ids(value):
    tokens = value.split()
    if not 1 <= len(tokens) <= 64:
        raise ValueError('Expected bounded node:pool workqueue identities')
    nodes, pools = set(), set()
    for token in tokens:
        match = re.fullmatch(r'(-?\d+):(\d+)', token)
        if not match:
            raise ValueError('Invalid workqueue pool identity')
        node, pool = map(int, match.groups())
        if not -1 <= node <= 4095 or not 0 <= pool <= 2147483647 or node in nodes:
            raise ValueError('Invalid or duplicate workqueue node')
        nodes.add(node)
        pools.add(pool)
    return sorted(pools)


def callback_pool_filters(pools, function):
    if (not pools or len(pools) > 64 or
            any(type(pool) is not int or not 0 <= pool <= 2147483647 for pool in pools) or
            type(function) is not int or not 0 < function < 1 << 64):
        raise ValueError('Expected bounded pool IDs and a resolved callback-worker function')

    def names(field):
        return '('+' || '.join([*(field+' ~ "kworker/u'+str(pool)+':*"'
                                 for pool in sorted(set(pools))),
                                field+' == "kgsl-events"'])+')'

    current = names('COMM')
    target = names('comm')+' || comm == "kgsl_worker_thr"'
    return {
        'workqueue/workqueue_queue_work': 'function == '+hex(function),
        # Activation/end events contain only a work pointer in this vendor kernel.
        'workqueue/workqueue_activate_work': None,
        'workqueue/workqueue_execute_start': '(function == '+hex(function)+') || '+current,
        'workqueue/workqueue_execute_end': current,
        'sched/sched_switch': (names('prev_comm')+' || '+names('next_comm')+
                             ' || prev_comm == "kgsl_worker_thr" || next_comm == "kgsl_worker_thr"'),
        'sched/sched_waking': target,
        'sched/sched_wakeup': target,
        'sched/sched_wakeup_new': target,
    }


def arm(instance, pid, syscalls=()):
    if any(type(number) is not int or not 0 <= number <= 2147483647 for number in syscalls):
        raise ValueError('Expected nonnegative syscall IDs')
    syscalls = sorted(set(syscalls))
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
    for event in EVENTS:
        if (instance / 'events' / event / 'filter').read_text().strip() not in ('', 'none', '0'):
            raise ValueError('Trace event already filtered: ' + event)
    clock = instance / 'trace_clock'
    clocks = clock.read_text().split()
    if 'mono' not in [name.strip('[]') for name in clocks]:
        raise ValueError('Monotonic trace clock unavailable')
    selected_clocks = [name[1:-1] for name in clocks if name.startswith('[') and name.endswith(']')]
    if len(selected_clocks) != 1:
        raise ValueError('Current trace clock unavailable')
    fork = instance / 'options/event-fork'
    original_fork = fork.read_text().strip()
    if original_fork not in ('0', '1'):
        raise ValueError('Unexpected PID inheritance state')
    changes = []

    def write(path, value, previous):
        changes.append((path, previous))
        path.write_text(value)

    try:
        if syscalls:
            expression = ' || '.join('id == ' + str(number) for number in syscalls)
            for event in EVENTS[2:]:
                path = instance / 'events' / event / 'filter'
                write(path, expression, '0')
                if ''.join(path.read_text().split()) != ''.join(expression.split()):
                    raise ValueError('Kernel did not accept the syscall filter: ' + event)
        write(clock, 'mono', selected_clocks[0])
        write(fork, '1', original_fork)
        if fork.read_text().strip() != '1':
            raise ValueError('Kernel did not enable PID inheritance')
        write(instance / 'set_event_pid', str(pid), '')
        if (instance / 'set_event_pid').read_text().split() != [str(pid)]:
            raise ValueError('Kernel did not select the launching PID')
        (instance / 'trace').write_text('')
        for event in EVENTS:
            write(instance / 'events' / event / 'enable', '1', '0')
        write(instance / 'tracing_on', '1', '0')
        (instance / 'trace_marker').write_text('PICO_COMPOSITOR_PRE_EXEC pid=' + str(pid))
    except BaseException as error:
        failures = []
        for path, previous in reversed(changes):
            try:
                path.write_text(previous)
            except OSError as cleanup_error:
                failures.append(str(path) + ': ' + str(cleanup_error))
        if failures:
            raise RuntimeError('Trace setup failed; state restoration incomplete: ' + '; '.join(failures)) from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, required=True)
    parser.add_argument('--boot', required=True)
    parser.add_argument('--user', default='vr')
    parser.add_argument('--syscall', type=int, action='append', default=[],
                        help='Retain only this syscall ID (repeatable; scheduler events retain the compositor PID selection)')
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
    arm(args.instance, os.getpid(), args.syscall)
    print('PICO_COMPOSITOR_TRACE_ARMED ' + json.dumps({
        'pid': os.getpid(), 'uid': user.pw_uid, 'instance': str(args.instance),
        'events': EVENTS, 'syscall_ids': sorted(set(args.syscall)),
        'event_fork': True}), flush=True)
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    environment = os.environ | {'HOME': user.pw_dir, 'USER': user.pw_name,
                                 'LOGNAME': user.pw_name, 'SHELL': user.pw_shell}
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()
