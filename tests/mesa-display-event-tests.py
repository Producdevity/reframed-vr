#!/usr/bin/env python3
"""Exercise the actual WSI event-priority request without changing host scheduling."""
import argparse
import importlib.util
from pathlib import Path
import subprocess


def run(source, output):
    spec = importlib.util.spec_from_file_location("fence_tests", Path(__file__).with_name("kgsl-fence-tests.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    text = source.read_text()
    definition = "\nstatic void *\nwsi_display_wait_thread(void *data)"
    caller = helpers.function(text[text.index(definition):], "wsi_display_wait_thread")
    if caller.index("wsi_display_event_priority()") >= caller.index("for (;;)"):
        raise ValueError("Event priority must be requested before event dispatch starts")
    output.mkdir(parents=True, exist_ok=True)
    (output / "display-event-under-test.h").write_text(helpers.function(text, "wsi_display_event_priority"))
    executable = output / "mesa-display-event-tests"
    subprocess.run(["clang", "-std=gnu11", "-D_GNU_SOURCE", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(output), str(Path(__file__).with_suffix(".c")),
                    "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable.resolve())], check=True, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
