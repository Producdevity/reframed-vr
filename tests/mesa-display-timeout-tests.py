#!/usr/bin/env python3
"""Exercise the actual WSI wait helper with Mesa's compiled POSIX condition variable."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source, build, output):
    spec = importlib.util.spec_from_file_location(
        'fence_tests', Path(__file__).with_name('kgsl-fence-tests.py'))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    function = helpers.function(source.read_text(), 'cond_timedwait_ns')
    injected = function.replace('cond_timedwait_ns(', 'injected_cond_timedwait_ns(')
    injected = injected.replace('u_cnd_monotonic_timedwait(', 'injected_wait(')
    output.mkdir(parents=True, exist_ok=False)
    header = output / 'display-timeout-under-test.h'
    header.write_text(function + '\n' + injected + '\n')

    commands = json.loads((build / 'compile_commands.json').read_text())
    rows = [row for row in commands if row['file'].endswith('/cnd_monotonic.c')]
    if len(rows) != 1:
        raise ValueError('Expected exactly one compiled Mesa condition-variable implementation')
    row = rows[0]
    directory = Path(row['directory'])
    arguments = shlex.split(row['command'])
    configuration = [arg for arg in arguments if arg.startswith(('-D', '-I')) and arg != '-DNDEBUG']
    condition_object = directory / row['output']
    condition_source = (directory / row['file']).resolve()
    fixture = Path(__file__).with_suffix('.c')
    executable = output / 'mesa-display-timeout-tests'
    command = ['clang', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
               *configuration, '-I' + str(output.resolve()), str(fixture.resolve()),
               str(condition_object), '-pthread', '-lm', '-o', str(executable.resolve())]
    subprocess.run(command, cwd=directory, check=True, timeout=60)
    result = subprocess.run([str(executable.resolve())], capture_output=True, text=True,
                            timeout=20, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1'))
    (output / 'test.log').write_text(result.stdout + result.stderr)
    report = {'status': 'passed' if result.returncode == 0 else 'failed',
              'source_sha256': sha(source), 'fixture_sha256': sha(fixture),
              'condition_source_sha256': sha(condition_source),
              'condition_object_sha256': sha(condition_object),
              'command': command, 'compiler_directory': str(directory),
              'returncode': result.returncode, 'hardware_verified': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(result.stdout, end='')
    print(result.stderr, end='')
    return result.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('build', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.source.resolve(), args.build.resolve(), args.output.resolve()))
