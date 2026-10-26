#!/usr/bin/env python3
"""Exercise actual KGSL native/DRM submissions and queue completion ownership."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


def run(source_path, output):
    spec = importlib.util.spec_from_file_location("fences", Path(__file__).with_name("kgsl-fence-tests.py"))
    fences = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fences)
    source = source_path.read_text()
    queue_path = source_path.with_name("tu_queue.h")
    queue = queue_path.read_text()
    cached = "kgsl_completion_cache_store(" in source
    output.mkdir(parents=True, exist_ok=True)
    (output / "kgsl-queue-under-test.h").write_text(
        queue[queue.index("enum tu_queue_type"):queue.index("VK_DEFINE_HANDLE_CASTS")])
    names = ["kgsl_submitqueue_priority_count", "kgsl_submitqueue_new", "kgsl_submitqueue_close",
             "kgsl_syncobj_init", "kgsl_syncobj_reset", "kgsl_syncobj_destroy", "kgsl_syncobj_dup",
             "timestamp_to_fd", "kgsl_syncobj_ts_to_fd", "timestamp_cmp", "max_ts",
             "kgsl_syncobj_export", "kgsl_syncobj_import", "kgsl_syncobj_merge",
             "kgsl_queue_submit_native", "kgsl_queue_submit_drm", "kgsl_queue_submit"]
    if cached:
        names.insert(0, "kgsl_completion_cache_clear")
        names.insert(names.index("kgsl_queue_submit_drm"), "kgsl_completion_cache_store")
    definitions = source[source.index("enum kgsl_syncobj_state"):source.index("static void\nkgsl_syncobj_init")]
    native = source[source.index("struct vk_kgsl_syncobj\n{"):source.index("static VkResult\nvk_kgsl_sync_init")]
    (output / "kgsl-completion-under-test.h").write_text(
        definitions + native + "\n".join(fences.function(source, name) for name in names))
    executable = output / "kgsl-completion-cache-tests"
    # The existing native function uses GNU zero-length VLAs and C++ extensions.
    subprocess.run(["clang++", "-std=gnu++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-Wno-missing-field-initializers", "-Wno-vla-extension",
                    "-Wno-gnu-alignof-expression", "-Wno-c++11-narrowing",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-fno-sanitize=vla-bound",
                    "-DHAVE_LIBDRM=1", "-DHAVE_PERFETTO=0", f"-DHAS_CACHE={int(cached)}",
                    "-I", str(output), str(Path(__file__).with_name("kgsl-completion-cache-tests.cpp")),
                    "-o", str(executable)], check=True, timeout=60)
    result = subprocess.run([str(executable.resolve())], check=True, capture_output=True, text=True, timeout=30)
    print(result.stdout, end="")
    if result.stderr:
        raise RuntimeError(result.stderr)
    (output / "result.json").write_text(json.dumps({
        "source": str(source_path), "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "queue_source_sha256": hashlib.sha256(queue.encode()).hexdigest(),
        "cache_candidate": cached, "functions": names, "stdout": result.stdout,
        "boundary": "Actual extracted functions; modeled GPU/DRM ioctls, real descriptor ownership; no device proof."
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)
