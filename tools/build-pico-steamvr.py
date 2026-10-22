#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def verify(directory, profile):
    for name, digest in profile.items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Dependency hash mismatch: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description='Build the physical Neo3 SteamVR driver; does not install or start it.')
    parser.add_argument('--sdk', type=Path, default=ROOT / 'output/openvr-sdk')
    parser.add_argument('--cjson', type=Path, default=ROOT / 'output/pico-steamvr-deps/cjson')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--cxx', default='clang++-14')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('The physical driver must be built on native ARM64 Linux')
    if args.output.exists() or args.output.is_symlink():
        parser.error('Output must be a new directory')
    sdk = json.loads((ROOT / 'profiles/openvr.json').read_text())
    verify(args.sdk, {Path(name).name: value for name, value in sdk['files'].items()})
    cjson = json.loads((ROOT / 'profiles/pico-steamvr-cjson.json').read_text())
    verify(args.cjson, cjson['sha256'])
    sources = ['src/pico-steamvr-driver.cpp', 'src/pico-steamvr-display.cpp', 'src/pico-steamvr-config.cpp',
               'src/pico-steamvr-display.h', 'src/pico-steamvr-pose.cpp', 'src/pico-steamvr-pose.h',
               'src/pico-slam-channel.c', 'src/pico-slam-channel.h', 'src/pico-slam-pose.c',
               'src/pico-slam-pose.h', 'src/pico-slam-result.h', 'profiles/openvr.json',
               'profiles/pico-steamvr-cjson.json', 'profiles/pico-steamvr.json',
               'system/steamvr-pico/driver.vrdrivermanifest',
               'system/steamvr-pico/compositor.conf',
               'system/steamvr-pico/gamescope.conf',
               'system/steamvr-pico/vrserver',
               'tests/pico-steamvr-live.cpp',
               'tools/build-pico-steamvr.py']
    commands = []
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        flags = ['-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-fvisibility=hidden',
                 '-I', str(ROOT / 'src'), '-isystem', str(args.sdk), '-I', str(args.cjson)]
        objects = []
        units = [(ROOT / 'src' / (name + '.c'), args.cc, 'c11')
                 for name in ['pico-slam-channel', 'pico-slam-pose']]
        units += [(args.cjson / 'cJSON.c', args.cc, 'c11')]
        units += [(ROOT / 'src' / (name + '.cpp'), args.cxx, 'c++17')
                  for name in ['pico-steamvr-driver', 'pico-steamvr-display', 'pico-steamvr-config', 'pico-steamvr-pose']]
        for source, compiler, standard in units:
            target = work / (source.stem + '.o')
            command = [compiler, '-std=' + standard, *flags, '-c', str(source), '-o', str(target)]
            commands.append(command)
            subprocess.run(command, check=True)
            objects.append(str(target))
        binary = work / 'driver_reframed_pico.so'
        command = [args.cxx, '-shared', *objects, '-pthread', '-lm', '-Wl,-z,defs', '-o', str(binary)]
        commands.append(command)
        subprocess.run(command, check=True)
        destination = args.output / 'reframed_pico/bin/linuxarm64'
        destination.mkdir(parents=True)
        shutil.copyfile(binary, destination / binary.name)
        shutil.copyfile(ROOT / 'system/steamvr-pico/driver.vrdrivermanifest',
                        args.output / 'reframed_pico/driver.vrdrivermanifest')
        probe = args.output / 'pico-steamvr-live'
        command = [args.cxx, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-isystem', str(args.sdk), str(ROOT / 'tests/pico-steamvr-live.cpp'),
                   '-ldl', '-lm', '-o', str(probe)]
        commands.append(command)
        subprocess.run(command, check=True)
    shutil.copyfile(args.sdk / 'LICENSE', args.output / 'OpenVR-LICENSE')
    shutil.copyfile(ROOT / 'profiles/pico-steamvr.json', args.output / 'steamvr.vrsettings')
    shutil.copyfile(ROOT / 'system/steamvr-pico/compositor.conf', args.output / 'compositor.conf')
    shutil.copyfile(ROOT / 'system/steamvr-pico/gamescope.conf', args.output / 'gamescope.conf')
    shutil.copyfile(ROOT / 'system/steamvr-pico/vrserver', args.output / 'vrserver')
    (args.output / 'vrserver').chmod(0o755)
    notice = (args.cjson / 'cJSON.h').read_text().split('*/', 1)[0].removeprefix('/*').strip()
    (args.output / 'cJSON-LICENSE').write_text(notice + '\n')
    record = {'architecture': 'aarch64-linux', 'physical_driver': True, 'device_actions': [],
              'hardware_verified': False, 'commands': commands, 'openvr': sdk, 'cjson': cjson,
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
              'files_sha256': {p.relative_to(args.output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in args.output.rglob('*') if p.is_file()}}
    (args.output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print('PICO_STEAMVR_DRIVER_BUILT ' + str(args.output))


if __name__ == '__main__':
    main()
