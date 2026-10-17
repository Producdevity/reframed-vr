#!/usr/bin/env python3
"""Race the CVE-2026-64560 CPU-timer deletion bug on the Quest 3 QEMU kernel.

Boots the QEMU-transport kernel built from the pinned Quest 3 source with a
minimal initramfs whose /init is the static race probe in
tests/quest-cpu-timer/race.c. The probe forks children that race a
child-targeted process-CPU timer against a non-leader exec() using swept
single deletes, aligned cascades, settime window detection and back-to-back
delete tiling, and reports the WARN_ON_ONCE win, kernel oopses and phase2
churn anomalies. This is offline QEMU evidence for race feasibility on the
vulnerable source; it is not a headset run, not a privilege escalation and
not a flash-readiness result.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RACE_SOURCE = ROOT / "tests/quest-cpu-timer/race.c"
KERNEL_COMMIT = "dbc2bc83a2b673f5d1c24ee9dadb0cd708ffda3f"
# Static ARM64 toolchain proven to live in the Quest kernel-build image.
BUILD_IMAGE = "localhost/reframed-vr:kernel"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_kernel(kernel):
    build = json.loads((kernel / "build.json").read_text())
    if build.get("status") != "compiled" or build.get("qemu_transports") is not True:
        raise ValueError("Expected the compiled QEMU-transport Quest kernel")
    if build.get("commit") != KERNEL_COMMIT:
        raise ValueError(f"Expected pinned Quest source {KERNEL_COMMIT}, got {build.get('commit')}")
    wanted = next((a["sha256"] for a in build["artifacts"] if a["path"] == "Image"), None)
    actual = digest(kernel / "Image")
    if wanted != actual:
        raise ValueError(f"Kernel Image hash mismatch: {actual}")
    return build, actual


def build_probe(engine, image, output):
    binary = output / "race-init"
    log = output / "build.log"
    script = (f"gcc -static -O2 -pthread -Wall -Wextra -Werror "
              f"-o /out/race-init {RACE_SOURCE} && test -s /out/race-init")
    command = [engine, "run", "--rm", "--platform", "linux/arm64",
               "-v", f"{RACE_SOURCE.parent}:{RACE_SOURCE.parent}:ro",
               "-v", f"{output}:/out", "--entrypoint", "bash", image, "-c", script]
    with log.open("wb") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=300, check=True)
    if not binary.is_file() or binary.stat().st_size < 10000:
        raise RuntimeError("Race probe did not build; see " + str(log))
    return binary


def cpio_newc(entries):
    """Build an uncompressed newc cpio archive from {name: (mode, bytes)}."""
    out = io.BytesIO()

    def record(name, mode, data):
        # "070701" magic (6 bytes) + 13 eight-char hex fields = 110 bytes.
        # namesize counts the trailing NUL of the name, per the kernel's
        # initramfs extractor ("initramfs name without nulterm" otherwise).
        fields = [0, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0,
                  len(name) + 1, 0]
        header = b"070701" + "".join(f"{f:08X}" for f in fields).encode()
        out.write(header + name.encode() + b"\0")
        out.write(b"\0" * ((-(111 + len(name))) % 4))  # 110B header + name + NUL
        out.write(data)
        out.write(b"\0" * (-len(data) % 4))

    for name, (mode, data) in entries.items():
        record(name, mode, data)
    out.write(b"070701" + "".join(
        f"{f:08X}" for f in [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 11, 0]).encode())
    out.write(b"TRAILER!!!\0")
    out.write(b"\0" * ((-111 - 11) % 4))
    out.write(b"\0" * (-out.tell() % 512))
    return out.getvalue()


def build_initramfs(binary, output):
    payload = cpio_newc({"init": (0o100755, binary.read_bytes())})
    path = output / "initramfs.cpio.gz"
    with path.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as gz:
            gz.write(payload)
    return path


def run_boot(qemu, accel, kernel, initramfs, output, name, timeout):
    directory = output / name
    directory.mkdir()
    command = [qemu, "-name", f"quest-cpu-timer-race-{name}", "-machine", "virt",
               "-accel", accel, "-cpu", "host" if accel in ("hvf", "kvm") else "max",
               "-smp", "4", "-m", "1024", "-nodefaults", "-nographic",
               "-monitor", "none", "-serial", "stdio", "-no-reboot", "-nic", "none",
               "-kernel", str(kernel / "Image"), "-initrd", str(initramfs),
               "-append", "console=ttyAMA0 earlycon"]
    report = {"name": name, "command": command, "timeout_seconds": timeout,
              "status": "started"}
    started = time.monotonic()
    try:
        with (directory / "boot.log").open("wb") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                report["returncode"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise TimeoutError(f"Race VM {name} did not finish before the deadline")
        text = (directory / "boot.log").read_text(errors="replace")
        report["markers"] = {
            "race_init": text.count("RACE_INIT"),
            "sweep_end": text.count("SWEEP_END"),
            "warn_first": [line for line in text.splitlines() if "WARN_FIRST" in line],
            "watch": [line for line in text.splitlines() if line.startswith("WATCH")],
            "oops_first": [line for line in text.splitlines() if "OOPS_FIRST" in line],
            "watchdog": text.count("WATCHDOG"),
            "phase2_anomalies": sum(1 for line in text.splitlines()
                                    if "PHASE2" in line and "anomalies=0" not in line),
            "phase2_total": text.count("PHASE2"),
            "warn_splat": [line for line in text.splitlines() if "posix_cpu_timer_del" in line and "WARNING" in line],
            "power_down": "reboot: Power down" in text,
        }
        report["status"] = "passed" if report["markers"]["power_down"] else "completed"
    except (OSError, TimeoutError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path,
                        default=Path("output/kernel/quest3/qemu-camera-stream-20261016-v3"),
                        nargs="?")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", default=os.environ.get("CONTAINER_ENGINE", "docker"))
    parser.add_argument("--image", default=BUILD_IMAGE)
    parser.add_argument("--qemu", default="qemu-system-aarch64")
    default_accel = "hvf" if platform.system() == "Darwin" and platform.machine() == "arm64" else "tcg"
    parser.add_argument("--accel", choices=("hvf", "kvm", "tcg"), default=default_accel)
    parser.add_argument("--boots", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=430)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit("Output directory exists; choose a new one")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    build, image_hash = check_kernel(args.kernel.resolve())

    result = {
        "schema_version": 1,
        "target": "quest3-qemu-cpu-timer-race",
        "cve": "CVE-2026-64560",
        "kernel_commit": build["commit"],
        "kernel_image_sha256": image_hash,
        "kernel_build_json_sha256": digest(args.kernel.resolve() / "build.json"),
        "probe_source_sha256": digest(RACE_SOURCE),
        "hardware_boot_verified": False,
        "flash_image": False,
        "privilege_escalation_claimed": False,
        "boots": [],
        "status": "started",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    binary = build_probe(args.engine, args.image, args.output)
    result["probe_sha256"] = digest(binary)
    initramfs = build_initramfs(binary, args.output)
    result["initramfs_sha256"] = digest(initramfs)
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    try:
        for index in range(args.boots):
            report = run_boot(args.qemu, args.accel, args.kernel.resolve(),
                              initramfs, args.output, f"boot{index + 1}", args.timeout)
            result["boots"].append(report)
            print(f"boot{index + 1}: {report['status']} "
                  f"warn={bool(report['markers']['warn_first'])} "
                  f"oops={bool(report['markers']['oops_first'])}", flush=True)
        result["status"] = "completed"
        result["warn_observed"] = any(b["markers"]["warn_first"] for b in result["boots"])
        result["oops_observed"] = any(b["markers"]["oops_first"] for b in result["boots"])
    except (OSError, TimeoutError, RuntimeError) as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(args.output / "result.json")


if __name__ == "__main__":
    main()
