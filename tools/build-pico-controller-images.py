#!/usr/bin/env python3
"""Build the pinned Bionic controller image owner and CPU probes; no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ['src/pico-controller-images.cpp', 'src/pico-controller-images.h',
          'src/pico-controller-images.exports', 'tests/pico-controller-images.cpp',
          'tests/pico-controller-images-public.cpp', 'profiles/pico-controller-images.json',
          'tools/build-pico-controller-images.py']


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ndk', type=Path, required=True)
    parser.add_argument('--opencv-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not hasattr(tarfile, 'data_filter'):
        parser.error('Safe archive extraction requires Python 3.11.4 or later')
    profile = json.loads((ROOT / 'profiles/pico-controller-images.json').read_text())
    ndk, archive, output = args.ndk.resolve(), args.opencv_archive.resolve(), args.output.resolve()
    if digest(archive) != profile['opencv']['archive_sha256']:
        parser.error('OpenCV archive differs from pinned input')
    properties = dict(line.split('=', 1) for line in (ndk / 'source.properties').read_text().splitlines() if '=' in line)
    if properties.get('Pkg.Revision ', '').strip() != profile['ndk_revision']:
        parser.error('NDK revision differs from the tested C++ ABI')
    host = {'Darwin': 'darwin-x86_64', 'Linux': 'linux-x86_64'}.get(platform.system())
    if not host:
        parser.error('Requires a supported NDK host')
    compiler = ndk / 'toolchains/llvm/prebuilt' / host / 'bin/aarch64-linux-android29-clang++'
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'started', 'device_actions': [], 'commands': [],
              'source_sha256': {name: digest(ROOT / name) for name in INPUTS},
              'opencv_archive_sha256': digest(archive), 'profile': profile}

    def run(command, name):
        report['commands'].append(command)
        with (output / (name + '.log')).open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            raise RuntimeError(name + ' failed; see build log')

    try:
        source_root = output / 'opencv-source'
        source_root.mkdir()
        archive_root = 'opencv-' + profile['opencv']['commit']
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if not parts or parts[0] != archive_root or '..' in parts or member.name.startswith('/'):
                    raise ValueError('Unexpected OpenCV archive member')
            tar.extractall(source_root, filter='data')
        source = source_root / archive_root
        license = source / 'LICENSE'
        if digest(license) != profile['opencv']['license_sha256']:
            raise ValueError('OpenCV license differs')
        (output / 'OpenCV-LICENSE.txt').write_bytes(license.read_bytes())
        compatibility = output / 'opencv-native-core.cmake'
        compatibility.write_text('function(android_get_compatible_target result)\n'
                                 '  set(${result} "unused by native core" PARENT_SCOPE)\n'
                                 'endfunction()\n')
        build = output / 'opencv-build'
        configure = ['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
                     '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
                     '-DCMAKE_TOOLCHAIN_FILE=' + str(ndk / 'build/cmake/android.toolchain.cmake'),
                     '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-29',
                     '-DANDROID_STL=c++_static', '-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DBUILD_SHARED_LIBS=OFF',
                     '-DBUILD_LIST=core', '-DCV_DISABLE_OPTIMIZATION=ON',
                     '-DCMAKE_C_FLAGS=-fvisibility=hidden -include string.h',
                     '-DCMAKE_CXX_FLAGS=-fvisibility=hidden -fvisibility-inlines-hidden -include arm_neon.h',
                     '-DCMAKE_PROJECT_INCLUDE_BEFORE=' + str(compatibility)]
        disabled = ['BUILD_TESTS', 'BUILD_PERF_TESTS', 'BUILD_EXAMPLES', 'BUILD_JAVA',
                    'BUILD_opencv_apps', 'BUILD_opencv_python2', 'BUILD_opencv_python3',
                    'BUILD_ANDROID_EXAMPLES', 'BUILD_ANDROID_PROJECTS', 'WITH_IPP', 'WITH_ITT',
                    'WITH_OPENCL', 'WITH_LAPACK', 'WITH_EIGEN', 'WITH_TBB', 'WITH_CAROTENE', 'BUILD_ZLIB']
        run(configure + ['-D' + name + '=OFF' for name in disabled], 'configure')
        run(['cmake', '--build', str(build), '--target', 'opencv_core', '--parallel', '2'], 'opencv')
        common = [str(compiler), '-std=c++17', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
                  '-I', str(ROOT / 'src'), '-isystem', str(source / 'modules/core/include'),
                  '-isystem', str(build), '-static-libstdc++']
        libraries = [str(build / 'lib/arm64-v8a/libopencv_core.a'),
                     str(build / '3rdparty/lib/arm64-v8a/libcpufeatures.a'),
                     '-llog', '-lz', '-lm', '-ldl', '-Wl,--exclude-libs,ALL']
        library = output / 'libpico-controller-images.so'
        run([*common, '-fPIC', '-fvisibility=hidden', '-fvisibility-inlines-hidden', '-shared',
             str(ROOT / 'src/pico-controller-images.cpp'), *libraries,
             '-Wl,--version-script,' + str(ROOT / 'src/pico-controller-images.exports'),
             '-o', str(library)], 'owner')
        for name in ['pico-controller-images', 'pico-controller-images-public']:
            run([*common, str(ROOT / 'tests' / (name + '.cpp')), *libraries,
                 '-o', str(output / name)], name)
        if report['source_sha256'] != {name: digest(ROOT / name) for name in INPUTS} or digest(archive) != report['opencv_archive_sha256']:
            raise ValueError('Build inputs changed')
        report.update(status='compiled', artifacts={name: digest(output / name) for name in
                      ['libpico-controller-images.so', 'pico-controller-images', 'pico-controller-images-public']})
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
