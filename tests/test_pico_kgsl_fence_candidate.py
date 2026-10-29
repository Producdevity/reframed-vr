import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "kernel_fence_build", ROOT / "tools/kernel-build.py"
)
kernel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kernel)
PATCH = (
    ROOT
    / "patches/kernel/pico-neo3-linux/experimental/0019-kgsl-fence-rt-dispatch.patch"
)


def function(source, name):
    match = re.search(
        r"(?m)^(?:static (?:inline |noinline )?)?(?:void|int|bool) "
        + name
        + r"\([^;]*?\)\n\{",
        source,
    )
    if not match:
        raise AssertionError("Missing function " + name)
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start() : end]


class FenceCandidateTests(unittest.TestCase):
    def test_host_lifecycle_fixture_uses_the_patch_functions(self):
        additions = {}
        for block in PATCH.read_text().split("--- a/")[1:]:
            lines = block.splitlines()
            additions[lines[0]] = "\n".join(
                line[1:]
                for line in lines
                if line.startswith(("+", " ")) and not line.startswith("+++")
            )
        added = additions["drivers/gpu/msm/kgsl_events.c"]
        fixture = (ROOT / "tests/fixtures/pico-kgsl-fence-rt.c").read_text()
        for name in (
            "kgsl_fence_worker_init",
            "kgsl_event_workers_flush",
            "kgsl_event_workers_close",
            "_kgsl_event_cleanup",
            "_kgsl_fence_worker",
            "finish_event",
            "queue_event",
            "kgsl_sync_is_fence_event",
        ):
            with self.subTest(function=name):
                source = (
                    additions["drivers/gpu/msm/kgsl_sync.c"]
                    if name == "kgsl_sync_is_fence_event"
                    else added
                )
                self.assertEqual(function(source, name), function(fixture, name))
        self.assertIn("static bool fence_rt;", added)
        self.assertIn("module_param_named(fence_rt, fence_rt, bool, 0444);", added)
        self.assertNotIn("trace_workqueue_", added)

    @unittest.skipUnless(
        shutil.which("clang"), "clang is needed for the source-extracted C fixture"
    )
    def test_fence_lifecycle_and_reference_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "fence-fixture"
            subprocess.run(
                [
                    "clang",
                    "-std=gnu11",
                    "-Werror=implicit-function-declaration",
                    "-Werror=incompatible-pointer-types",
                    "-fsanitize=address,undefined",
                    str(ROOT / "tests/fixtures/pico-kgsl-fence-rt.c"),
                    "-o",
                    str(binary),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True, timeout=10
            )
            self.assertEqual(
                result.stdout.strip(), "14 source-extracted C lifecycle cases passed"
            )

    def test_opt_in_appends_only_phase_and_dispatch_prerequisites(self):
        profile = kernel.sources.read_profile("pico-neo3")
        baseline_config, baseline = kernel.build_inputs(profile, True, False)
        config, candidate = kernel.build_inputs(
            profile, True, False, pico_fence_rt=True
        )
        self.assertEqual(config, baseline_config)
        self.assertEqual(candidate[:-2], baseline)
        self.assertEqual(
            [path.name for path in candidate[-2:]],
            [
                "0018-kgsl-delayed-callback-phases.patch",
                "0019-kgsl-fence-rt-dispatch.patch",
            ],
        )
        self.assertTrue(all("experimental" not in path.parts for path in baseline))
        self.assertNotIn(
            "0017-kgsl-maintenance-workqueue-sysfs.patch", [p.name for p in candidate]
        )

    def test_other_configurations_cannot_enable_fence_variant(self):
        for profile, userspace, qemu, ram in (
            ("quest3", True, False, False),
            ("pico-neo3", False, False, False),
            ("pico-neo3", True, True, False),
            ("pico-neo3", True, False, True),
        ):
            with self.subTest(profile=profile, userspace=userspace, qemu=qemu, ram=ram):
                with self.assertRaisesRegex(ValueError, "physical Pico"):
                    kernel.build_inputs(
                        kernel.sources.read_profile(profile),
                        userspace,
                        qemu,
                        ram,
                        pico_fence_rt=True,
                    )

    def test_missing_prerequisite_is_an_error(self):
        original = Path.is_file
        with patch.object(
            Path, "is_file", lambda path: False if path == PATCH else original(path)
        ):
            with self.assertRaisesRegex(
                ValueError, "Missing fence dispatch prerequisite"
            ):
                kernel.build_inputs(
                    kernel.sources.read_profile("pico-neo3"),
                    True,
                    False,
                    pico_fence_rt=True,
                )


if __name__ == "__main__":
    unittest.main()
