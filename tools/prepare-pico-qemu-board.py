#!/usr/bin/env python3
"""Flatten QEMU's socket wrapper for the Neo3 vendor CPU-topology parser."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def command(*args):
    return subprocess.check_output(list(args), text=True).strip()


def properties(path):
    result = {}

    def visit(node):
        result[node] = {name: command('fdtget', '-t', 'bx', str(path), node, name)
                        for name in command('fdtget', '-p', str(path), node).splitlines()}
        for child in command('fdtget', '-l', str(path), node).splitlines():
            visit(node.rstrip('/') + '/' + child)

    visit('/')
    return result


def prepare(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular QEMU DTB')
    before_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    before = properties(path)
    compatible = bytes(int(value, 16) for value in before['/'].get('compatible', '').split()).split(b'\0')
    if compatible != [b'linux,dummy-virt', b'']:
        raise ValueError('Only the linux,dummy-virt board is supported')
    phandles = []
    for index in range(2):
        node = f'/cpus/cpu@{index}'
        if command('fdtget', '-t', 'x', str(path), node, 'reg') != str(index):
            raise ValueError('Expected the two-CPU QEMU test topology')
        phandles.append(command('fdtget', '-t', 'x', str(path), node, 'phandle'))
    if len(set(phandles)) != 2 or any(int(value, 16) in (0, 0xffffffff) for value in phandles):
        raise ValueError('Invalid virtual CPU phandles')
    parent = '/cpus/cpu-map'
    children = command('fdtget', '-l', str(path), parent).splitlines()
    flattened = children == ['socket0']
    if flattened:
        parent += '/socket0'
    if command('fdtget', '-l', str(path), parent).splitlines() != ['cluster0']:
        raise ValueError('Unexpected virtual CPU cluster layout')
    if sorted(command('fdtget', '-l', str(path), parent + '/cluster0').splitlines()) != ['core0', 'core1']:
        raise ValueError('Expected two virtual cores')
    for index, phandle in enumerate(phandles):
        if command('fdtget', '-t', 'x', str(path), parent + f'/cluster0/core{index}', 'cpu') != phandle:
            raise ValueError('Virtual CPU map does not match CPU nodes')
    if flattened:
        command('fdtput', '-r', str(path), parent)
        for index, phandle in enumerate(phandles):
            node = f'/cpus/cpu-map/cluster0/core{index}'
            command('fdtput', '-p', '-c', str(path), node)
            command('fdtput', '-t', 'x', str(path), node, 'cpu', phandle)
    after = properties(path)

    def outside_map(tree):
        return {node: props for node, props in tree.items()
                if node != '/cpus/cpu-map' and not node.startswith('/cpus/cpu-map/')}

    if outside_map(before) != outside_map(after):
        raise ValueError('Preparation changed properties outside the virtual CPU map')
    return {'status': 'verified', 'board': 'linux,dummy-virt', 'socket_wrapper_removed': flattened,
            'cpu_phandles': phandles, 'input_sha256': before_sha,
            'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'all_properties_outside_cpu_map_unchanged': True, 'hardware_dtb': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Choose a new report path')
    try:
        result = prepare(args.dtb.absolute())
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')
