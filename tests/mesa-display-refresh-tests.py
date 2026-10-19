#!/usr/bin/env python3
"""Exercise Mesa's DRM mode conversion and refresh selection under sanitizers."""
import argparse
import importlib.util
from pathlib import Path
import subprocess


def run(source, output):
    spec = importlib.util.spec_from_file_location("fence_tests", Path(__file__).with_name("kgsl-fence-tests.py"))
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    text = source.read_text()
    start = text.index("typedef struct wsi_display_mode {")
    end = text.index("} wsi_display_mode;", start) + len("} wsi_display_mode;")
    definitions = text[start:end] + "\n"
    definitions += "\n".join(helpers.function(text, name) for name in
                             ("wsi_display_mode_set_drm", "wsi_display_mode_matches_drm", "wsi_display_mode_refresh"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "display-refresh-under-test.h").write_text(definitions)
    flags = subprocess.check_output(["pkg-config", "--cflags", "libdrm"], text=True).split()
    executable = output / "mesa-display-refresh-tests"
    subprocess.run(["clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(output), *flags, str(Path(__file__).with_suffix(".c")),
                    "-lm", "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable.resolve())], check=True, timeout=20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
