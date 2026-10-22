#!/usr/bin/env python3
"""Build the opt-in b1977 controller receiver on native ARM64 Linux."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssc-prefix', type=Path, default=Path('/opt/reframed-vr/ssc'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sanitizer', choices=('undefined', 'address,undefined'))
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('Requires native ARM64 Linux; does not install or start a receiver')
    args.output.mkdir(parents=True, exist_ok=False)
    profile = json.loads((ROOT / 'profiles/ssc.json').read_text())
    prefix = args.ssc_prefix.resolve()
    sources = ['tools/capture-pico-controller.c', 'tools/build-pico-controller-capture.py',
               'src/pico-controller.c', 'src/pico-controller.h',
               'src/pico-controller-stream.c', 'src/pico-controller-stream.h',
               'src/ssc-clock.c', 'src/ssc-clock.h', 'src/ssc-clock-linux.c',
               'src/ssc-clock-linux.h', 'profiles/ssc.json', 'tests/pico-controller-capture.c']
    report = {'status': 'started', 'hardware_verified': False, 'device_actions': [],
              'source_sha256': {n: digest(ROOT / n) for n in sources}, 'commands': []}
    try:
        if json.loads((prefix / 'share/ssc/profile.json').read_text()) != profile:
            raise ValueError('SSC runtime profile differs')
        archive = prefix / 'share/ssc/source.tar.gz'
        if digest(archive) != profile['source_archive_sha256']:
            raise ValueError('SSC source archive differs')
        source, generated = args.output / 'source', args.output / 'generated'
        source.mkdir()
        generated.mkdir()
        names = list(profile['test_source_sha256'])
        with tarfile.open(archive) as tar:
            for name in names:
                matches = [m for m in tar.getmembers() if m.name.endswith('/' + name)]
                if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 262144:
                    raise ValueError('Expected one bounded pinned source: ' + name)
                target = source / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(tar.extractfile(matches[0]).read())
                if digest(target) != profile['test_source_sha256'][name]:
                    raise ValueError('SSC header/protocol differs: ' + name)

        def run(command, log):
            report['commands'].append(command)
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            (args.output / log).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError(log + ' failed: ' + result.stdout + result.stderr)

        for index, name in enumerate(profile['patches']):
            report['source_sha256'][name] = digest(ROOT / name)
            run(['patch', '--batch', '--fuzz=0', '--forward', '-p1', '-d', str(source),
                 '-i', str(ROOT / name)], 'patch-' + str(index) + '.log')
        for name, key in [('libssc-client.c', 'patched_report_source_sha256'),
                          ('libssc-sensor.c', 'patched_sensor_source_sha256')]:
            if digest(source / 'src' / name) != profile[key]:
                raise ValueError('Patched SSC source differs: ' + name)
        run(['protoc-c', '--proto_path=' + str(source / 'data'),
             '--c_out=' + str(generated), str(source / 'data/ssc-common.proto'),
             str(source / 'data/ssc-sensor-suid.proto')], 'protoc.log')
        flags = shlex.split(subprocess.check_output(
            ['pkg-config', '--cflags', '--libs', 'gio-2.0', 'qmi-glib', 'qrtr-glib', 'libprotobuf-c'], text=True))
        binary = args.output / 'capture-pico-controller'
        sanitizers = ['-fsanitize=' + args.sanitizer, '-fno-sanitize-recover=all'] if args.sanitizer else []
        common = ['cc', '-std=gnu11', '-O1' if args.sanitizer else '-O2', '-g',
             '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', *sanitizers,
             '-I', str(ROOT / 'src'), '-I', str(source / 'src'), '-I', str(generated)]
        shared = [*(str(ROOT / n) for n in sources if n.startswith('src/') and n.endswith('.c')),
             *(str(source / 'src' / n) for n in ['libssc-client.c', 'libssc-common.c', 'libssc-sensor.c']),
             *(str(p) for p in sorted(generated.glob('*.c'))), *flags, '-lm']
        run([*common, str(ROOT / 'tools/capture-pico-controller.c'), *shared, '-o', str(binary)], 'compile.log')
        tests = args.output / 'controller-report-tests'
        run([*common, str(ROOT / 'tests/pico-controller-capture.c'), *shared, '-o', str(tests)], 'test-compile.log')
        run([str(tests)], 'report-tests.log')
        if 'PICO_CONTROLLER_REPORT_TESTS_PASS cases=9 hardware_access=0' not in (args.output / 'report-tests.log').read_text():
            raise ValueError('Report tests did not complete')
        if report['source_sha256'] != {n: digest(ROOT / n) for n in sources + profile['patches']}:
            raise ValueError('Build inputs changed')
        shutil.copyfile(prefix / 'share/licenses/libssc/LICENSE', args.output / 'libssc-LICENSE')
        report.update(status='compiled', binary_sha256=digest(binary),
                      ssc_source_archive_sha256=digest(archive),
                      sanitizer=args.sanitizer, requested_rate_hz=480,
                      report_tests_sha256=digest(tests), report_test_cases=9)
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (args.output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
