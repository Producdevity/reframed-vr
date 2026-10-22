#!/usr/bin/env python3
"""Exercise the actual WSI counter dispatch with modeled DRM queries."""
import argparse
from pathlib import Path
import subprocess


def run(source, output):
    text = source.read_text()
    start = text.index('VKAPI_ATTR VkResult VKAPI_CALL\nwsi_GetSwapchainCounterEXT(')
    end = text.index('\n}\n', start) + 3
    output.mkdir(parents=True, exist_ok=True)
    (output / 'display-counter-under-test.h').write_text(
        text[start:end])
    binary = output / 'mesa-display-counter-tests'
    subprocess.run(['clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(output),
                    str(Path(__file__).with_suffix('.c')), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary.resolve())], check=True, timeout=20)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
