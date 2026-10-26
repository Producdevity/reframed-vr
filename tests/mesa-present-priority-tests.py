#!/usr/bin/env python3
"""Exercise actual presentation-wait activation with modeled synchronization and scheduling."""
import argparse
import importlib.util
from pathlib import Path
import subprocess


def run(source, output):
    spec = importlib.util.spec_from_file_location("fences", Path(__file__).with_name("kgsl-fence-tests.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    text = source.read_text()
    output.mkdir(parents=True, exist_ok=True)
    definitions = "\n".join(helpers.function(text, name) for name in
                             ("wsi_display_present_thread_priority", "wsi_display_wait_for_present"))
    (output / "display-present-priority-under-test.h").write_text(definitions)
    executable = output / "mesa-present-priority-tests"
    subprocess.run(["clang", "-std=c11", "-D_GNU_SOURCE", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-pthread", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(output), str(Path(__file__).with_suffix(".c")), "-o", str(executable)],
                   check=True, timeout=60)
    subprocess.run([str(executable.resolve())], check=True, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
