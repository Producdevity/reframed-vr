# KGSL Turnip build and offline packaging

The headset graphics backend is native AArch64 Mesa Turnip using Qualcomm's
KGSL kernel interface. FEX is used separately for x86 applications; the native
ARM64 SteamVR runtime is now available for integration. The Android hardware
tests below establish bounded GPU execution on both headsets under their stock
kernels. The Neo3 now passes the bounded native GPU presentation test below;
clean lens output and a calibrated VR session remain open.

```sh
bash tools/build-mesa.sh NEW_MESA_DIRECTORY turnip
python3 -B tools/build-headset-root.py KERNEL_BUILD STARTUP_INITRAMFS \
  --firmware QUEST_FIRMWARE --image RUNTIME_IMAGE \
  --turnip NEW_MESA_DIRECTORY --output NEW_ROOT_DIRECTORY
```

The pinned Mesa 26.1.8 archive is checked by size and SHA-256. The build uses an
immutable ARM64 container image, a source cache keyed by profile, patches,
builder and image, and no network during compilation. Existing outputs are
refused. Build and test logs, source identities and artifact hashes are retained.

The Turnip patches fix fence ownership and wait-any behavior, implement
an opt-in KGSL-to-DRM synchronization bridge, enable that bridge in the
KGSL-only build, connect an explicitly selected DRM display to KGSL WSI, and
use the modern KGSL GPU-object allocation interfaces. Submission still uses KGSL.
The DRM device supplies synchronization objects; it does not replace the KGSL GPU driver.

The bridge requires `-Dfreedreno-kgsl-drm-sync=true` at build time and
`TU_KGSL_DRM_SYNC` pointing to a suitable DRM device at runtime. The device must
support the required synchronization features. Its actual path and capabilities
must be checked on the target; a numbered render node is not a device identity.

Binary-only DRM providers are supported. Point-zero fence import/export uses
the binary ioctls directly, without requiring timeline transfer ioctls. Local
Vulkan timelines use Mesa's emulation on these providers; this does not advertise
external timeline semaphore sharing.

On October 18, the Neo3 `live-root-v8` RAM boot physically verified binary DRM
object lifetime, sync-file import/export, reset, CPU signaling and a cross-process
wait for submission. The new SDE kernel flag advertises binary objects only;
the timeline capability query remains unsupported. Turnip also passed both
exportable and import-only receiver cases of `vulkan-external-sync --binary-only`,
with GPU-written 4 MiB buffer readbacks across separate processes. The fixture
notifies each binary peer after signal submission and transfers buffer ownership
through `VK_QUEUE_FAMILY_EXTERNAL`. Its earlier unsequenced binary waits violated
the submission-order requirement and are not evidence of a GPU failure.
The receipts are `native-v8-binary-sync-verification.json` and its bounded log
excerpts in `output/pico-recovery-bringup-20261018-v1/`.

These checks do not establish presentation. The same boot renders a Steam welcome
screen in Xorg, but the owner sees grey or corrupted colour bands through the
lenses. Direct KMS colour tests also look corrupted despite correct framebuffer
readbacks. That older kernel lacks the Neo3 DMA-buffer fence API. The later
physical kernel supplies it and passes direct GPU presentation; subsequent
owner checks still report corrupted output. The later two-DMA control below
establishes a clean stock-kernel direct path.

## Native GPU presentation and timing

The October 19 [physical presentation results](dma-buf-sync.md#neo3-physical-presentation)
supersede the earlier missing-fence-API limitation for the new Neo3 kernel.
The ordered binary-sync Turnip build renders and presents 64 checked RGB frames
on that kernel, with 63 actual plane-framebuffer changes and successful
present-completion/vblank checks. Its simple clear/readback workload completes
at about 120 Hz. This does not establish clean optical output or calibrated VR.

### Vendor DSI refresh reporting

The same physical test exposes a timing mismatch: Vulkan reports 48.358 Hz for
the 1920×3664 mode that DRM labels 120 Hz. The advertised pixel clock and totals
do not describe the measured frame cadence; Mesa's calculation therefore reports
the wrong refresh. Monado consequently starts its pacer at 20.679 ms despite the
measured approximately 8.33 ms presentation cadence.

Patch 0011 preserves the advertised DRM refresh for DSI modes when the explicitly
selected KGSL display backend is active. It leaves other connectors/backends on
the existing clock/totals calculation, preserving fractional desktop rates, and
falls back to that calculation when the DRM refresh is zero. Mode identity
distinguishes different advertised refresh values on the opted-in path while
retaining the existing XRandR matching behavior elsewhere. It does not alter the
kernel mode clock or the complete DRM mode passed back during a modeset.

The new sanitizer suite executes the actual mode conversion, mode matching and
refresh functions. It checks 72–120 Hz, zero-rate fallback, scan factors,
changed timing/refresh identity and the unchanged 59.94 Hz path. All 325 checks
pass. `output/mesa/pico-display-refresh-20261019-v2/` also passes the eight
existing KGSL/WSI suites and all five Freedreno tests, and its artifact validator
checks the added test inputs and extracted helper hash.

That exact driver subsequently runs from the Pico's RAM filesystem. Vulkan now
reports 120,000/90,000/72,000 mHz, and 64 GPU-cleared frames pass pixel readback,
present-completion and DRM vblank checks with 63 plane-framebuffer changes.
The median completion interval is 8.328 ms. Monado selects an 8.333333 ms period
and accepts 120 two-eye projection frames from a native OpenXR client with
simulated tracking. The client exits successfully; compositor missed-deadline
warnings remain, so this is not sustained VR performance acceptance. Eye
alignment and optical output were not inspected. Receipts are
`dmabuf-v1-refresh-v2-physical-verification.json` and
`dmabuf-v1-native-xr-verification.json` in the bring-up evidence directory.

### Neo3 split DMA scanout

An owner-confirmed stock-kernel direct test produces clean solid green using
DMA2/DMA3, each covering a 960×3664 half of the portrait output. Native Linux
subsequently accepts the same layout, with buffer checks and cleanup, but has
no contemporary optical result. These transport halves are not the VR eye
viewports. See the [matched display investigation](pico-display-research-20261019.md).

Patch 0012 adds an opt-in Vulkan display path using
`MESA_VK_WSI_PICO_SPLIT_DMA=1`. It applies to the KGSL DSI backend, validates the
vendor DMA inventory, intersects both planes' formats with the primary's, and
selects linear scanout. After the existing primary-plane initialization, each
atomic presentation disables that primary and updates both DMA halves with the
same GPU framebuffer. It retains the existing GPU-fence and flip-event paths;
it does not add another display-copy process. Other backends retain their
existing path. Unexpected inventory or mode geometry is rejected.

The actual helper passes 5,000 ASan/UBSan checks with modeled libdrm inventory
and atomic requests on macOS and ARM64 Linux. The compiled ARM64 bundle
`output/mesa/pico-split-dma-20261019-v1/` passes all ten helper suites, five
Freedreno tests and artifact validation. This verifies compilation and bounded
contracts. A subsequent native RAM test verifies 64 GPU frames through this
path at 120 Hz: 400 spatial pixel samples per frame, 63 framebuffer changes,
and a median observed completion interval of 8.376 ms. After the first-frame
primary bootstrap, all 63 later frames use DMA planes 109/112 with one shared
linear XR24 framebuffer. The full-state capture confirms both halves and the
disabled primary. This differs from the owner-observed stock test's AB24 format.
Boot and DTBO readback hashes remain unchanged, and normal stock return is
verified. Receipts are under `state-route-v1/gpu-dma-v2/` in the bring-up
evidence directory. Native lens output and VR acceptance remain pending;
the option is not enabled by default.

The same driver subsequently presents the native Steam desktop quad into both
eye viewports with physical SSC-backed orientation. Full framebuffer readback
verifies the stereo raster, but composition takes about 33 ms per completion
in that workload. This is separate from the 64-frame direct test and does not
establish lens clarity or a runtime performance winner. See the
[Steam stereo and timing evidence](pico-hmd.md#native-dual-dma-steam-stereo-and-timing).
The subsequent [render-path comparison](pico-hmd.md#render-path-and-pacing-comparison)
uses the same driver with linear XB30 in compute mode and improves average
completion cadence to about 80 Hz in its 90 Hz candidate. Missed frames remain,
and its legacy XR24-only screenshot conversion does not decode XB30 correctly.
The [format-aware capture](pico-hmd.md#format-aware-native-scanout-capture)
subsequently verifies those 10-bit buffers. Repeated sessions still show variable
cadence and vblank-fence errors, so sustained timing acceptance remains open.

### Display wait timeout correction

Patch 0013 translates C11 `thrd_timedout` to `ETIMEDOUT` in the shared WSI
condition-wait helper. Mesa 26.1.8's compiled condition-variable implementation
returns the former, while display acquisition and display-event fence callers
expect the latter. Passing it through reports an ordinary timeout as surface
loss or device loss. Successful waits and other errors retain their results.

`tests/mesa-display-timeout-tests.py` extracts the actual helper and links
Mesa's compiled condition-variable object with its configured headers. Real
expired and future deadlines, signalled waits and an injected error produce
250 checks: 68 fail before the fix and all pass after it. The fixture uses
ASan/UBSan; the existing Mesa utility object retains its release build flags.
Run it inside the matching Linux build environment with the WSI source,
Meson build directory and a new output directory as its three arguments.

An isolated ARM64 diagnostic build passes five Freedreno tests and four
related WSI helper suites. On the native Pico, the same-driver-hash warm Steam
session reports 31 vblank-fence `VK_TIMEOUT` warnings instead of the previous
false `VK_ERROR_DEVICE_LOST` errors. Thirty occur during composition. Missing
events persist, and the cold/warm completion averages remain 60.00/89.25 Hz;
this corrects the error contract without establishing steady 90 Hz.

Both sessions retain full format-aware XB30 captures and restore the original
GPU policy. BOOT/DTBO hashes and normal stock recovery are verified. Evidence
is retained under
`output/pico-recovery-bringup-20261018-v1/vblank-feedback-v1/`.
The candidate library is `57adb34739305d4b52586f5a936097bd1a6e2b12be46a0b6527b603e74ba7848`.
It is a manually verified RAM diagnostic candidate: canonical artifact
packaging remains unverified while the three unrelated build/test helper
deletions in this checkout remain unresolved. Artifact validation was not
weakened or bypassed.

The subsequent [inherited-mode investigation](pico-hmd.md#inherited-mode-and-presentation-feedback)
finds a separate startup error: requesting 90 Hz at the first splash handoff
violates the vendor driver contract. Adopting 120 Hz first and then starting
and restarting at 90 Hz restores approximately 11.11 ms hardware vblank
interrupts without vblank-fence timeouts. Both runs still average about 80
completions/s. This is a startup correction, separate from patch 0013's timeout
result fix, and it does not establish clean physical optics or a runtime winner.

### Frame compositor counter timing

Patch 0015 implements a process-scoped compatibility ABI for the retained Frame
compositor. Its `vkGetSwapchainCounterEXT` call uses private counter `0x7ffffffd`
and expects two `uint64_t` outputs: vblank sequence and CLOCK_MONOTONIC time in
nanoseconds. Mesa 26.1.8 ignored the counter argument and returned success after
writing only the sequence. The compositor's zero-initialized timestamp stayed
zero, producing a vsync age equal to monotonic uptime.

The contract is verified independently in Valve's retained official
`deckard-mesa-linux-aarch64-26.3.0_devel+gite07916b4-5-aarch64` package. Its
`wsi_GetSwapchainCounterEXT` compares the private value and calls
`drmCrtcGetSequence(fd, crtc, out, out + 1)`. Package SHA-256 is
`c30eb810cf537e839f5b7ff66b1088e3c29cf67e17bcbf44856b3ac38064b7cb`;
the reference `libvulkan_freedreno.so` has SHA-256
`6bed18a0a9d59fc0132766947f1c2657b50c4188776f718cfdf723cf8dd7b4ee`.
This patch independently implements the observed Valve ABI; it does not import
Frame optical calibration or add a public Vulkan enum.

Set `MESA_VK_WSI_FRAME_COUNTER_TIMING=1` only for this compositor process.
The private path returns both values from one real DRM query. Inactive display,
query failure or a missing timestamp returns an error without changing output.
Other unsupported counters are rejected. Public one-word vblank queries retain
their existing behavior even with the option enabled; there is no change to
query waits, GPU synchronization or connector timestamp caching.

`tests/mesa-display-counter-tests.py` extracts the actual patched function and
checks dispatch, failure output preservation and output bounds with ASan/UBSan.
The original Mesa function fails the unsupported-counter control; a guard-only
implementation fails the paired-output control. The complete ARM64 build passes
this suite, the other eleven helper suites and all five Freedreno tests.
Native Pico GPU interop and all four binary/timeline OPAQUE_FD buffer-sharing
cases pass. Two corrected Facet captures match their reported kernel vblank
timestamp within 9 microseconds in the sampled checks. Some client notifications
remain delayed; this is not proof of sustained 120 FPS or clean physical optics.
See the [full verification](pico-steamvr-verification.md#frame-counter-abi-and-pose-read-order).

### Presentation completion tracing

Patch 0016 adds opt-in `MESA_VK_WSI_PRESENT_TRACE=1` diagnostics for display
queueing, atomic commits, page-flip completion and both phases of present waits.
It also records counter-query arguments and whether the private paired path is
enabled. Both query and successful-pair records identify the queried swapchain,
including requests that fail or use an unsupported counter. A successful paired
query records its sequence and DRM timestamp,
allowing the compositor's last clock update to be correlated with those waits.
Present IDs and counter sequences are separate namespaces even when their
numeric values coincide. The extracted-function regression checks these trace
arguments across two swapchains while retaining standard-query and failure-output
assertions. Each line records monotonic time, thread, swapchain and image, plus
event-specific IDs, details and result. It preserves `errno` and ignores
write errors; wait and completion semantics are unchanged. Leave it disabled
for normal operation. Enabled trace I/O adds overhead and is not a performance
optimization.

The isolated ARM64 build under
`output/mesa/pico-present-trace-20261023-v1/` passes all twelve helper suites and
five Freedreno tests. Its library SHA-256 is
`85129536b1b05de22544f303a6799b5e63666f08491981aa449e52062998440b`.
The native Pico combined trial retains 106,890 correlated events. See the
[present-ID analysis](pico-steamvr-verification.md#present-id-correlation).

## Correction to earlier build evidence

The September 10 `output/mesa/turnip-drm-v5/` driver compiled with
`MESA_SYSTEM_HAS_KMS_DRM=0` and without `HAVE_LIBDRM`. Mesa's KGSL-only platform
logic disabled libdrm before the target dependency was added. Consequently the
conditional bridge was absent from the final shared library, despite successful
compilation and separate helper tests.

Patch 0004 adds an explicit Meson option that preserves DRM support for this
configuration and makes libdrm required. The builder now requires the actual
KGSL compiler command to enable DRM, the finished ELF to link libdrm, and the
bridge's runtime option to be present in that ELF. Compile and dynamic-link
records are included in the artifact hashes.

`output/mesa/turnip-drm-v7/` passes these checks, all three ASan/UBSan helper
suites and five Freedreno tests. `output/turnip-bridge-audit-v1/` retains the
old compiler command and library identity, verifies rejection of old, damaged,
foreign-architecture and inconsistent bundles, and records loading the corrected
library in the pinned userspace. Vulkan reaches the library and reports no GPU
when no KGSL device is exposed.

The earlier QEMU test of real DRM/software fences applies to its retained
helper header. It covers cross-process opaque descriptors,
future timeline points, merged dependencies and cleanup. The submission-wrapper
suite models KGSL calls. Neither test demonstrates actual GPU completion.

## Root contents

`--turnip` validates the build, source/profile/patch/test identities, artifact
checksums, ELF architecture and installed ICD path. The root receives the
library and ICD under `/opt/reframed-vr/turnip/`, plus the build record under
`/usr/share/reframed-vr/`. Loading with `RTLD_NOW` inside the assembled userspace
must succeed. After formatting, the builder extracts these files from the ext4
image and compares their hashes with the validated bundle.

Packaging does not select Turnip globally or start a physical VR session.
The existing QEMU software-rendering lab remains available. Headset session
selection, display scanout, GPU execution, tracking/calibration, thermal
operation, exact-device boot acceptance and recovery still require completion.

## Opt-in direct display

Patch 0005 allows a KGSL instance enabling `VK_KHR_display` to open the DRM
primary node named by `TU_KGSL_DISPLAY`. The helper requires a character device,
primary-node identity, PRIME import, universal planes, atomic KMS, DRM master,
and nonempty connector/CRTC/plane inventories. It does not force another client
to surrender DRM master. Failure closes the opened descriptor and preserves the
original error; later KGSL initialization failures also release that descriptor.

The display opens before the synchronization bridge, which could otherwise take
DRM master first. `local_fd` remains the KGSL GPU descriptor; `master_fd` is the
selected display. Existing common display WSI uses the latter for scanout.
Presentation-device checks match the selected primary's device identity,
including DRM leases. Physical-device DRM properties describe the selected
primary and do not invent a DRM render node for KGSL.

This selection applies only to instances enabling `VK_KHR_display`. Ordinary
application instances do not acquire the primary through `TU_KGSL_DISPLAY`.
`TU_KGSL_DRM_SYNC` remains independent; applications should use a verified,
suitable render node for synchronization so they do not occupy display master.
The vendor SDE DRM driver declares render-node support, but actual node identity,
permissions and synchronization capabilities still require target validation.

The [DMA-buffer sync-file backport](dma-buf-sync.md) supplies the kernel API
Mesa uses to attach completion fences before presentation on the documented
Quest builds. The October 18 Neo3 native-panel v2 kernel does not include that
backport. The separate 4.19 port passes the documented QEMU ioctl and
reservation tests and the later physical GPU presentation checks above.
KGSL now rejects
allocation/import requests for its unsupported implicit-sync fallback instead
of silently accepting that flag. This does not prove GPU completion, modifier
compatibility or scanout. Complete v10 kernel/module/device-tree exports now
include the backport. The October 9 restored roots contain the matching newer
modules and `turnip-display-v2`. The October 10 physical-kernel root also includes
the GPUOBJ driver update described below; its QEMU counterpart remains pending.

`output/mesa/turnip-display-v2/` contains the compiled ARM64 driver, four passing
ASan/UBSan suites and five passing Freedreno tests. The first display build is
preserved at `turnip-display-v1/`; it failed because the presentation callback
referenced a function private to another source file. The corrected callback
uses the kernel backend identity directly.

```sh
python3 -B tools/test-kgsl-display.py QEMU_KERNEL_BUILD \
  --turnip NEW_MESA_DIRECTORY --output NEW_DISPLAY_TEST_DIRECTORY
```

This runner refuses physical kernel builds and existing output directories,
verifies kernel/Turnip identities, and boots without disks or networking.
`output/kgsl-display-v1/` uses the QEMU DMA-buffer test kernel and the exact
compiled display helper with real virtio-gpu DRM ioctls. Primary/render-node
checks, master contention, lease identity, repeated release/reacquisition and
clean power-off pass. The separate sanitizer suite models libdrm failures with
real descriptor ownership. These tests perform no KGSL GPU work or panel scanout.

`output/kgsl-display-audit-v1/` records artifact rejection tests, loading the new
DSO in the pinned ARM64 runtime, and an absent-KGSL negative probe. The previous
v7 bundle is preserved but is not accepted as a build of the current patches.
The October 9 [restored roots](headset-root.md) include the display driver.
The later GPUOBJ allocation change is included in the October 10 physical-kernel
root and passes its loader/extraction checks; virtual root acceptance remains open.

## Native compositor integration still required

The pinned runtime already includes a native ARM64 Monado service with the
Vulkan direct-display target. Its package is
`25.1.0^20260820git01c1f6b-1.fc44.aarch64`; this is distinct from the translated
desktop SteamVR compatibility runtime.

The exact [Monado source](https://gitlab.freedesktop.org/monado/monado/-/tree/01c1f6b23ab73c1459c8f4cfd2eb16d5142214c2/src/xrt/compositor/main)
was retrieved and checked against Git blob identities. The files and hashes are
preserved under `output/hardware-research/monado-display-01c1f6b/`. Its
`XRT_COMPOSITOR_FORCE_VK_DISPLAY` setting selects a zero-based display index and
requests `VK_KHR_display`. The [native Monado bundle](monado.md) corrects the
display-index bounds check, empty-plane access, mode validation and compatible
plane selection. The existing runtime image still contains the original package;
the October 9 restored headset roots include the new bundle and pass dependency
and extraction checks. Automatic mode selection still prioritizes pixel count
and then refresh rate.

The earlier description of this target as forcing simulated display timing was
incomplete. `COMP_TARGET_FORCE_FAKE_DISPLAY_TIMING` selects the simple pacing
implementation, but the independent `VK_EXT_display_control` event thread feeds
actual vblank timestamps into it when supported. The new upstream pacing test
verifies that supplied vblank phase changes reach its predictions at 72, 90 and
120 Hz. No KGSL/SDE hardware timing has been measured; the existing flag is
preserved pending that validation.

The vendor Sharp panel description specifies two DSI controllers and a
2064-by-2208 per-panel timing. The vendor mode enumeration multiplies horizontal
active pixels by controller count; this implies a 4128-by-2208 combined mode for
that configuration. It is source-derived topology, not a measurement of the
attached headset. BOE/JDI/Sharp variants, selected panel, orientation, mode,
optics/calibration and compositor timing must be matched to the actual device.
Do not select the highest advertised refresh rate automatically for bring-up.

The native Monado bundle accepts `XRT_COMPOSITOR_FORCE_DISPLAY_MODE` as
`WIDTHxHEIGHT@REFRESH_MILLIHZ`. For example, `1920x3664@72000` requests exactly
that tuple; this is syntax, not an accepted mode for a particular headset.
Use a tuple from the selected DRM/Vulkan display's verified mode inventory.
The selector refuses malformed, absent or duplicate matches, and refuses a
conflict with `XRT_COMPOSITOR_DESIRED_MODE` if a numeric index is also supplied.
It never falls back to the automatic selector after an explicit tuple fails.
The constraint is checked before creating a display surface. Without it,
the existing numeric-index and automatic selection behavior remains.

This removes dependence on mode-list ordering; it does not identify a connector,
validate panel timing or establish physical scanout. Display identity and the
HMD's calibrated layout still need to agree with the selected mode.

No physical compositor service is enabled by this change. DMA allocation,
GPU rendering, PRIME import/modifiers, correct binocular output and timing,
tracking/calibration, thermal behavior, exact-device boot acceptance and recovery
remain required. Virtual results do not establish flash readiness.

## Physical Android GPU acceptance

On October 10, the source-built Android Turnip candidate passes actual GPU
buffer transfers and offscreen shader rendering on both connected development
headsets. Each test runs as the ordinary ADB shell with enforcing SELinux,
using a temporary process-local driver and exact firmware guards.

| Device | Stock firmware | GPU | Tested result |
|---|---|---|---|
| Quest 3 | `52083180032000520` | Adreno 740v3 | 32 buffer/fence checks; 16 shader-rendered frames |
| Neo3 Pro Eye | `smartcm.1696861506` / 5.8.4.0 | Adreno 650 | 32 buffer/fence checks; 16 shader-rendered frames |

The initial Quest candidate enumerates its GPU but fails `vkCreateDevice` with
`VK_ERROR_OUT_OF_DEVICE_MEMORY`. Patch 0006 adapts the
[community GPUOBJ allocator change](https://github.com/Jbbrack03/Quest-3-Turnip-Driver/blob/83cd874f3449d091fca51d25389f88f520a7f2f3/0001-android-carry-Quest-3-KGSL-compatibility-patches.patch)
to the existing Armada KGSL changes. Allocation, address queries, release and
memory-type probing use the modern ioctl family. An additional error path frees
an allocation whose address query fails before publishing the BO. A bounded
userspace-injected query error on each physical headset verifies a successful
release of that exact object, followed by normal process exit.

The initial Pico candidate cannot load because Android 10 lacks the exported
`atrace_get_enabled_tags` function used by newer platform headers. The separate
[Android tracing patch](../patches/mesa/android/README.md) restores the old ABI
for API 29 builds. Both headsets use their actual system libcutils; no stub
library is installed or used at runtime.

Each transfer checks every word of a 1 MiB GPU-written buffer after a bounded
fence wait. The rendering test executes vertex and fragment shaders into a
64-by-64 image, varies a push constant between red and yellow, and keeps the
right half blue. Every pixel is checked across 16 frames. Exported captures
match the stock-driver baseline. These small offscreen tests do not measure
headset frame pacing, thermal behavior, compositor presentation or scanout.

Both stock Vulkan drivers lack the queried opaque-FD semaphore sharing and
direct-display capabilities. Opening the SDE DRM render node from the shell
returns `EACCES` on both devices; its synchronization capabilities therefore
remain unmeasured. Explicitly enabling `TU_KGSL_DRM_SYNC` with that inaccessible
node fails initialization, preserving the bridge's refusal behavior.

The tested Android candidate has SHA-256
`b1db70afb1cf54fde2996b6ff60a2a26d576bcc8e45e088f529060a6c2eea3da`.
Build commands, negative baselines, driver/dependency hashes, pixel captures
and cleanup receipts are retained in `output/headset-gpu-20261010-v1`.
Firmware, boot identity, locked/green state and enforcement are unchanged;
the temporary device files are removed.

A separate Linux/glibc test also passes on both stock kernels. It uses the
unchanged output of the maintained Linux builder, including the KGSL DRM and
display patches: SHA-256
`4799fc79cdc9fb9c8ede6657428a5a2b9868e5675e37575d9ecc5c5388b76ee4`.
An explicit private glibc loader and 23-file dependency/test package run as the
ordinary ADB shell user, without a chroot, Android HAL or system-library changes.
Both devices render all 16 shader frames correctly; exported pixels match the
Android candidate byte for byte. The driver and its dependencies are removed
afterward, with device identity and enforcement unchanged. Exact package hashes,
build commands and results are in `output/headset-linux-gpu-20261010-v1`.

These results establish real GPU execution for both userspace ABIs under stock
kernels. Custom boot, DRM synchronization, display ownership and physical VR
remain separate gates.


The October 13 Reframed build in `output/pico-turnip-20261013-v1/` recompiles
Turnip with the current install prefix and unchanged KGSL/display patches. All
five Freedreno tests and the fence, wait, submission and display helper suites
pass. The resulting ARM64 library passes immediate loading alongside the rebuilt
Monado and SSC bundles through [the combined userspace check](monado.md#offline-graphics-bundle-compatibility).
This verifies the native dependency set, not execution or scanout on the Pico GPU.

## DMA-buffer import failures

Patch 0007 releases the imported KGSL GPU object if its address query or the
retained descriptor duplication fails. The import is published only after both
resources exist; failures preserve the original diagnostic and leave the caller's
descriptor untouched. A cleanup ioctl failure cannot guarantee reclamation, but
still returns the original import error without publishing an unusable BO.

The builder runs the actual import and export functions under ASan/UBSan with
modeled KGSL ioctls and real descriptors. The 2,304 cases cover successful imports,
query/import/duplication failures, cleanup failure and repeated recovery. The
preceding source fails 1,536 ownership checks; the corrected source passes.
These are userspace ownership tests, not hardware GPU or display acceptance.

Patch 0008 fixes display-plane modifier lookup: an absent format no longer
inherits the first format's modifiers. Missing property queries are handled
without dereferencing null, and all property metadata is released, including on
kernels without `IN_FORMATS`. The existing no-modifier fallback remains.

The actual WSI function passes 6,336 synthetic format/query/allocation cases,
including format indices across the 64-bit modifier-mask boundaries, and a
missing-property sanitizer test. The previous function fails 4,776 cases and
triggers a null-pointer diagnostic. This verifies lookup and ownership; compatible
physical SDE/Adreno layouts and actual PRIME import still need hardware testing.

The diskless DRM fixture now compiles the same WSI function as the driver and
compares its results with libdrm's modifier iterator while accounting for every
property allocation. It passes 352 lookups on the retained virtio-gpu test kernel,
plus descriptor, master-contention and lease checks. Both virtual planes omit
`IN_FORMATS`, so this kernel run covers the no-modifier path; populated tables
remain covered by the sanitizer suite. The original function fails the same
real-DRM fixture. Both guests power off normally. This uses the retained Quest
QEMU transport kernel, not the Pico kernel or a physical display.

The import/modifier driver and image receipts are under
`output/pico-import-cleanup-20261014-v1/`: `turnip-final/`, `root-final/`,
`qemu-root-final/` and `boot-final/`. Native loading, full root readback and a
fresh read-only Pico root VM pass. The exact-mode Monado package is unchanged.
Physical Adreno/SDE interoperability, panel/mux operation and recovery remain
unverified; these images must not be treated as flash-ready.


## Native allocation lifetime

Patch 0009 separates cleanup of an unpublished allocation from destruction of a
registered BO. A failed sparse binding or virtual-address query now releases the
GPU object. A rejected capture/replay address releases the returned CPU mapping,
and destroying a replayable sparse VMA releases its retained mapping. Mapping
failures no longer remove an unregistered object from the dump list or emit a
BO destruction event before its allocation event.

The allocation suite executes the actual patched functions with the source's
KGSL UAPI declarations, modeled GPU ioctls and real file-backed `mmap`/`munmap`.
It covers ordinary, lazy, sparse and capture/replay allocations, fixed-address
success and rejection, reference counts, owned descriptor closure, repeated
allocation/query/binding/mapping failures, and failed release ioctls. All 6,144
cases pass under ASan/UBSan; the preceding source fails 3,456 cases. When the
kernel refuses a release, reclamation remains unproven; the original allocation
error is still returned and no BO is published.

The full builder requires this suite alongside the existing fence, wait,
submission, display and import suites. These results establish userspace
lifetime handling, not physical Adreno execution or display acceptance.

## Multi-plane PRIME ownership

Patch 0010 imports each display image's DMA-buffer once and reuses that handle
in every plane slot. Repeated PRIME imports into the same DRM file return the
existing GEM handle without another handle reference. The previous per-plane
cleanup could therefore close the same handle repeatedly. Both framebuffer
failure cleanup and normal destruction now close it once.

The actual WSI image functions pass 4,096 ASan/UBSan cases covering one to four
plane slots, modifier/no-modifier paths, allocation/import/framebuffer failures
and successful teardown. The previous functions fail 1,536 cases.

The diskless virtual-DRM fixture also executes these functions against actual
PRIME and framebuffer ioctls. It passes 192 cases: 64 framebuffer creations,
64 invalid-descriptor import refusals and 64 unsupported-modifier framebuffer
refusals, with no repeated handle closes or leaked descriptors. The original
functions fail the same fixture. Both guests power down normally.

The virtual framebuffers use XRGB8888; extra plane slots do not establish
physical multi-plane format support. Adreno/SDE modifier compatibility, UBWC,
GPU completion and physical scanout remain unverified.


The combined allocation/PRIME build is
`output/pico-gpu-lifetime-20261014-v1/turnip-display/`. Six KGSL sanitizer suites,
both WSI suites and five Freedreno tests pass. Native loading alongside the
matched Monado and SSC packages passes, and the [updated roots](headset-root.md)
contain the same validated driver. Recovery originals were rehashed; the
missing `misc` backup, cold recovery and stock restoration gates remain open.

## KGSL context priority

Patch 0017 connects the existing Vulkan global-priority mapping to KGSL context
creation when `TU_KGSL_CONTEXT_PRIORITIES=1` is explicitly selected for a kernel
whose priority flags have been verified. Without that exact opt-in, the backend
retains its single-priority path, advertises only MEDIUM, and sends no priority
bits. An unknown kernel is not inferred to support the new path from its GPU name.
The common internal priorities 0–3 map to kernel values 1, 4, 8 and 12.
The kernel interprets a zero priority field as its default, so internal priority
zero must not be encoded as zero. An ordinary medium-priority queue remains at
kernel priority 8. Values outside the internal range are rejected before the
context ioctl; failed creation does not publish a queue identity.

The queue-family query advertises LOW, MEDIUM and HIGH through the existing
common helper. Its existing `globalPriorityQuery` check rejects an unadvertised
REALTIME request when that feature is enabled. Without the query feature, the
existing common mapping can produce internal index zero. The extracted-function
tests cover both cases, all advertised priorities, preserved context flags,
invalid indices, the default/invalid-option fallback and ioctl failure under
ASan/UBSan. This follows the
[Vulkan queue-priority contract](https://docs.vulkan.org/spec/latest/chapters/devsandqueues.html);
priority is not a guarantee of processing time or presentation latency.

A native Pico test verifies a compositor context at kernel priority 1/ring 0,
with gamescope remaining at priority 8/ring 2. The private `TU_DEBUG=hiprio`
setting is only a fallback when the application does not supply chained global
priority information. The API request itself was not traced, so this is evidence
for the observed kernel tiers, not a controlled HIGH-versus-MEDIUM API comparison.
The default interop path passes all four cross-exec semaphore/buffer cases.
Those hardware measurements predate the opt-in guard; the guarded mapping is
unchanged, and the added fallback is verified by focused extracted-function tests.
No kernel ring count is modified, and these KGSL observations do not establish
DRM/MSM preemption support on another headset or kernel.

The instrumented comparison and remaining failures are recorded in the
[SteamVR verification notes](pico-steamvr-verification.md#kgsl-gpu-priority-path-2026-10-25).
No realtime CPU launch policy or compositor priority override is made a default.

The subsequent guarded-library test in
`output/pico-camera-reorder-20261025-v1/` verifies the actual compositor opt-in
and priority separation on the pinned Pico kernel, with all four default interop
cases passing. The verification notes retain its exact library hash and limits.

## Display-event thread scheduling

Patch 0018 adds the Linux opt-in `MESA_VK_WSI_DISPLAY_EVENT_RT=1`. It requests
RR/2 with reset-on-fork for Mesa's display-event thread before dispatch starts.
The default path makes no scheduling request. A denied request logs its error
and continues with the existing policy; it does not fail presentation. No
affinity, render-thread policy or resource limit is changed by the library.

The event thread handles page-flip completion, which releases the next frame.
An exact-TID Pico comparison with render RR/2 fixed reduces recorded frame drops
from 18/9 in the normal-policy windows to 2/0 in the RR/2 windows. These are
overlapping OpenVR history snapshots, not disjoint display cohorts or a photon
latency measurement. See the [verification notes](pico-steamvr-verification.md#display-event-thread-delay-2026-10-25)
for the corresponding DRM sequence gaps and remaining misses.

The compositor service must permit this request. The original diagnostic's
`RestrictRealtime=yes` and zero `LimitRTPRIO` deny it, as a native test confirms.
The library does not bypass those settings. Sanitizer tests exercise the actual
helper with modeled scheduling calls, including absent/invalid opt-ins and
permission failures. Build and artifact checks bind that helper to its evidence.

The verified startup profile uses systemd `User=vr`, `LimitRTPRIO=2`,
`RestrictRealtime=no` and the existing `LimitRTTIME=100ms`. It grants no
capabilities. The owned session selects render RR/2 before starting the Steam UI;
that render-thread choice is separate from this library option. The full native
test in `output/pico-wsi-event-startup-20261025-v3/` verifies event RR/2 at startup,
all four default interop cases, Steam rendering and camera/head tracking. Rare
missed frames remain; no launch setting is made a default by this patch.

Patch 0019 adds `MESA_VK_WSI_PRESENT_THREAD_RT=1` for the presentation-wait caller.
After its first successful, nonzero present, and outside the wait mutex, an
ordinary SCHED_OTHER caller requests RR/2 once. Other scheduling policies are
retained. Timeout, semaphore/condition errors and zero completed IDs do not
activate it; a denied scheduling request preserves the presentation result.
Configuration is read once per thread after that first completion.

This replaces the diagnostic's external render-TID priority setter. Applying the
same policy at the first GPU submission was rejected after hardware exposed a
startup CPU-watchdog timeout; that implementation is retained only as ignored
evidence. The completed-present version finishes a full native SteamVR/camera
run with the existing 100 ms watchdog. Its render readback is RR/2 without the
reset-on-fork bit, despite requesting that bit; continued preservation of the bit
is not established. The service ceiling remains 2 and no capabilities are added.
The instrumented run still has one overdue age query, so this is not a complete
frame-pacing acceptance result.

A later cold run still exhausts the 100 ms real-time CPU watchdog while creating
a dashboard shader, after presentation has begun. Completing the first present
does not ensure that startup compilation is over. Patch 0020 therefore adds
`MESA_VK_WSI_PRESENT_THREAD_NICE=1` as an ordinary SCHED_OTHER nice −20 alternative.
It activates at the same completed-present boundary, once per thread and outside
the wait mutex. Setting both priority options to `1` rejects the request without
changing policy or niceness. Other scheduling policies, affinity, resource limits
and presentation results are preserved; both modes remain disabled by default.
The caller needs permission to request nice −20, such as the diagnostic service's
existing `LimitNICE=-20`. This option does not disable or increase its watchdog.

Ordinary mode alone is not a watchdog fix on this vendor kernel. The version-2
pool capture verifies SCHED_OTHER/nice −20 at startup and scheduler boundaries,
but the kernel still reports a hard RT-time watchdog kill during GPU submission.
KGSL can temporarily promote the caller to FIFO internally. Its restored CFS
sleepers miss the RT-class-only timeout reset, allowing accounting to survive
blocking sleeps. The option remains an explicit scheduling comparison; the
kernel wake-accounting correction requires separate validation. Pico Linux patch
0015 passes native blocking-wake and nonblocking enforcement controls; its first
combined run retains the compositor but stops on a camera sequence gap before
steady timing windows. It does not establish complete pacing acceptance.
