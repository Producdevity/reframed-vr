#!/usr/bin/env python3
"""Exercise the Neo3 scanout helper with modeled libdrm queries and requests."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def run(source, output):
    output.mkdir(parents=True, exist_ok=True)
    header = output / 'wsi_display_pico.h'
    shutil.copy2(source, header)
    executable = output / 'mesa-pico-split-tests'
    subprocess.run(['clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I', str(output), str(Path(__file__).with_suffix('.c')),
                    '-o', str(executable)], check=True, timeout=60)
    result = subprocess.run([str(executable.resolve())], capture_output=True,
                            text=True, timeout=30)
    (output / 'mesa-pico-split-tests.stdout').write_text(result.stdout)
    (output / 'mesa-pico-split-tests.stderr').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr[:3000] or result.stdout[:3000])
    assert result.stdout.startswith('PICO_SPLIT_MODEL_PASS ')
    (output / 'mesa-pico-split-result.json').write_text(json.dumps({
        'status': 'passed', 'scope': 'actual helper; modeled libdrm inventory and atomic property assembly',
        'hardware_verified': False, 'stdout': result.stdout,
        'header_sha256': hashlib.sha256(header.read_bytes()).hexdigest(),
    }, indent=2) + '\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
