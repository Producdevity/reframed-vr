#!/usr/bin/env python3
"""Exercise actual Vulkan/KGSL priority mapping with modeled context creation."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess


def run(source_path, output):
    definitions = []
    for path, name in [(source_path, 'kgsl_submitqueue_priority_count'),
                       (source_path.with_name('tu_device.cc'),
                        'tu_physical_device_get_global_priority_properties'),
                       (source_path.with_name('tu_queue.cc'), 'tu_get_submitqueue_priority'),
                       (source_path, 'kgsl_submitqueue_new')]:
        text = path.read_text()
        start = re.search(r'^(?:static )?(?:void|int|uint32_t)\n' + name + r'\(', text, re.M)
        if start is None:
            raise ValueError('Missing priority function: ' + name)
        end = text.index('\n}\n', start.start()) + 3
        definitions.append(text[start.start():end])
    output.mkdir(parents=True, exist_ok=True)
    (output / 'kgsl-priority-under-test.h').write_text('\n'.join(definitions))
    shutil.copy2(source_path.with_name('msm_kgsl.h'), output / 'msm_kgsl.h')
    executable = output / 'kgsl-priority-tests'
    subprocess.run(['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-Wno-missing-field-initializers', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-I', str(output),
                    str(Path(__file__).with_suffix('.cpp')), '-o', str(executable)],
                   check=True, timeout=60)
    subprocess.run([str(executable.resolve())], check=True, timeout=20)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
