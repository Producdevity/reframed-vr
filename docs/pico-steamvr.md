# Native Neo3 SteamVR driver

`reframed_pico` is the physical Neo3 Pro Eye driver for Valve's native ARM64
SteamVR server and compositor. It is separate from `reframed_virtual` and does
not use Monado. Nothing enables or installs it automatically.

The display component reads the existing private Neo3 optical-profile format
(schema 2 or 3, `PICOA7H10`, analytic `pico-radial-2`). It preserves each eye's
viewport, projection, panel rotation, head-relative transform and RGB distortion.
The runtime receives the actual panel dimensions; PICO 4 side-by-side dimensions
are not defaults. The input profile owns the render-target recommendation and
nominal display interval. These values must match the selected hardware mode.

Poses come from the separate Bionic vendor-SLAM process through
[`pico-slam-channel`](pico-slam.md#pose-transport-to-steamvr). The driver binds a
single mapping inode, process instance and estimator generation. It publishes
fresh `DriverPose_t` samples on a worker and returns invalid tracking on silence,
confidence loss or a stopped generation. It supplies neither a simulated height
nor a fallback orientation. Capture age is carried in `poseTimeOffset`; velocity
prediction and measured photon latency remain to be implemented and validated.

The channel must already contain head poses in OpenVR coordinates. The driver
does not estimate axis conventions, recenter after loss, configure cameras or
start DSPs. Those lifetimes belong to the capture owner. Restarting SLAM requires
an explicit new generation/world-frame binding and a driver restart.

## Build and opt-in

On native ARM64 Linux, with the pinned OpenVR SDK and pinned cJSON source cached:

```sh
python3 tools/build-pico-steamvr.py --output output/NEW_PICO_DRIVER
```

`--sdk` and `--cjson` select dependency directories. The builder verifies their
hashes against `profiles/openvr.json` and `profiles/pico-steamvr-cjson.json`, emits
a standalone `reframed_pico` driver directory, a physical-headset client probe
and an opt-in `steamvr.vrsettings` session template,
and records source and artifact hashes. OpenVR and cJSON license notices accompany
the bundle. No unit-specific coefficients enter the build or repository.

The cJSON source is the existing vendored dependency in the pinned Monado source
tree; this does not link Monado into the driver. PicoFrame's PICO 4 driver was a
reference for separate Bionic tracking and Vulkan direct-display integration.
Neo3 calibration and pose conventions are established separately.

Register the resulting `reframed_pico` directory in the session's OpenVR path
registry and copy the template to that session's configuration directory. It
selects `reframed_pico`, Valve's asynchronous Vulkan path and 120 Hz. It disables
the Frame sensor driver and motion smoothing. Provide all of:

| Environment variable | Required value |
| --- | --- |
| `PICO_STEAMVR_BOOT_SERIAL` | Exact native `androidboot.serialno` |
| `PICO_STEAMVR_OPTICS` | Private, validated Neo3 optical-profile file |
| `PICO_STEAMVR_POSE_CHANNEL` | Readable mapping created by this capture owner |
| `PICO_STEAMVR_INSTANCE` | Nonzero process-instance identifier, 16 lowercase hex digits |
| `PICO_STEAMVR_GENERATION` | Nonzero estimator generation, 16 lowercase hex digits |
| `PICO_STEAMVR_MAX_AGE_NS` | Explicit maximum pose age, at most 100 ms |

The bundle also includes `compositor.conf`, an opt-in systemd drop-in for the
compositor unit. At the documented runtime location `/opt/reframed-vr/steamvr`,
it hides `drivers/cv/bin/linuxarm64/libArcturusPerception.so` in that process's
mount namespace. For a transient unit, pass its equivalent
`--property=InaccessiblePaths=/opt/reframed-vr/steamvr/drivers/cv/bin/linuxarm64/libArcturusPerception.so`
to `systemd-run`. Preserve the original runtime. Disabling `driver_cv` alone
does not prevent the compositor from loading this optional motion-estimation
library. It rejects the Neo3's `kona-iot MTP` platform during initialization.
This isolation does not hide the separate vendor SLAM library or change the
board model, optical profile or firmware.

The compatibility approach follows Florian Reintgen's
[PicoFrame change `dd8a402`](https://github.com/TheReal-Flo/PicoFrame/commit/dd8a402ba14d67d58f0b9d13ced61c3f169b8e33),
verified at PicoFrame `3affbc11ecaae56c56b7bd3eb13344c73a7a03da`.
Its `frame-session.sh` sets the same optional library aside, documenting an
unsupported ARMv8.4 instruction on Kryo 585. Namespace isolation here avoids
modifying the preserved Frame runtime. This omits CVP motion estimation;
asynchronous reprojection and live head tracking require their own validation.

Use an unprivileged SteamVR user with the required DRM/KGSL access. A root-owned
producer can share its mapping read-only with that user's group. Its private
directory must permit traversal without exposing calibration to other users.
The isolated Bionic filesystem namespace must bind the executable, dependencies
and shared mapping paths explicitly. Never truncate or reuse a mapping held by
an existing driver.

The Pico display rules installed by `PicoDisplayHandoff` grant the `video` group
access to `kgsl-3d0` and `ion`. The SteamVR user also needs the DRM primary and
render nodes. A 2026-10-21 native check confirmed that missing KGSL access hides
the GPU, while missing ION access prevents external-memory support. Giving the
session user those two device permissions makes binary OPAQUE_FD semaphore and
4 MiB buffer round trips pass across exec, for both exportable and import-only
receivers. That kernel lacked external timeline semaphores; the subsequent
[DRM timeline backport](pico-drm-timeline-backport.md) passes all four physical
GPU buffer round trips, including timeline OPAQUE_FD sharing.

The Pico display additionally needs the verified Turnip/KGSL direct-display path
with both DMA planes, rather than the single-plane bootstrap path. See the
[display investigation](pico-display-research-20261019.md). Building this driver
does not establish working Vulkan interprocess synchronization or presentation.

## Verification boundary

Host ASan/UBSan and native ARM64 tests verify 52,272 UV comparisons across four
panel rotations, identity and chromatic models, projection signs, eye transforms,
profile refusal and the private optical profile's structural validity. Earlier
pose tests verify the recorded vendor-to-OpenVR chain and invalidation.

A 2026-10-21 native Pico run independently receives 8,148 live tracked poses from
10,821 vendor callbacks. It consumes 249 synchronized head-camera sets, reports
no publication failure, and invalidates the mapping at shutdown. The independent
OpenVR-structure observer sees a maximum sampled capture age of 5.306 ms. Both
camera groups stop, the IMU producer joins and MCU references return to zero.
This observer is separate from SteamVR's server; it does not prove compositor
integration or physical optical alignment.

An offline oracle also reproduces b1977 `libSlamTools.getPredictResult` at zero
prediction for 1,024 synthetic poses. The fitted complete rigid transform matches
position within `7e-17` vendor units and quaternion components exactly. The native
stationary gravity sample supports its upward world axis. This establishes the
firmware SDK conversion, not physical metric accuracy, the active room origin
or completed head/lens acceptance. Private coefficients and evidence remain
under `output/pico-live-steamvr-20261021-v1/`.

A subsequent 30-second native capture publishes 28,627 tracked poses from 31,250
vendor callbacks and consumes 749 synchronized head-camera sets. Valve's actual
ARM64 `vrserver` loads `reframed_pico`; the physical client receives 300 tracked
HMD samples with no invalid samples. Capture and SLAM stop cleanly afterward.
This establishes live server integration using the firmware-derived SDK head
transform; it does not establish physical motion accuracy or presentation.

The compositor finds the panel and selects 90 Hz, but its first swapchain fails
with `VK_ERROR_DEVICE_LOST`. The same direct GPU probe fails as the SteamVR user
and presents 64 frames using both DMA planes as root. A libdrm check confirms
the vendor kernel denies unprivileged `DROP_MASTER` and `SET_MASTER`, even while
the file already holds master. The held-master WSI patch addresses that redundant
reacquisition. The rebuilt library then passes the same test as the unprivileged
SteamVR user: 64 GPU-rendered frames, 63 framebuffer changes, matching pixel
readbacks, both DMA planes active and successful present waits. The old source
fails the ownership regression; the patched source passes its held-master,
reacquisition, denial, nested-reference and external-file cases under sanitizers.
The reproducible build and device evidence are under
`output/mesa/pico-held-master-20261021-v2/` and the live-session evidence directory.
This closes the isolated swapchain permission failure; SteamVR's complete render
and synchronization paths require separate acceptance.

The next comparison isolates a second initialization failure: creating the same
swapchain succeeds at 120 Hz and fails at 90 Hz with
`VK_ERROR_INITIALIZATION_FAILED` on this kernel/display path. The optical profile
already specifies 120 Hz; SteamVR's bundled `preferredRefreshRate` defaults to
90 Hz independently. Setting that preference to 120 Hz makes the actual Valve
compositor select 120 Hz and create its two-image FIFO direct-display swapchain.
The session template preserves that verified setting. This does not establish
90 Hz support or clean optical presentation.

The compositor subsequently fails during renderer resource creation at
`vulkanrenderer.cpp:2710`, after constructing both distortion meshes. A Mesa
logging build identifies `VK_ERROR_INVALID_EXTERNAL_HANDLE` at
`vk_semaphore.c:165`. Disassembly of this exact native compositor confirms
creation of a timeline semaphore with OPAQUE_FD export. The running 4.19 kernel
supports the binary sharing tests but does not expose DRM timeline sync objects;
Mesa reports no external timeline support. The guarded launcher therefore does
not start the Steam overlay. This identifies the failed resource and missing
capability; it does not establish that enabling the capability will close all
remaining renderer failures. See the [targeted kernel backport](pico-drm-timeline-backport.md).
Evidence is retained under `output/pico-steamvr-session-20261021-v2/`, including
the hash-verified `error-log-export.tar.gz` and `renderer-resource-analysis.json`.
All camera/IMU/SLAM and SteamVR processes then stop, MCU references return to
zero and both DSPs go offline. Full BOOT/DTBO readbacks match the backups, and
the device returns to stock b1977 with Wi-Fi off and the updater disabled.

With the matching timeline kernel, the compositor passes that resource creation
and then terminates in Frame's optional perception library on its platform-name
check. The compositor-only namespace isolation above removes this fatal error:
the log records the unavailable CVP motion estimator and continues through
`Startup Complete`. The actual SteamVR client again receives 300 valid HMD
samples and no invalid samples. The native vendor process publishes 90,064
tracked poses, consumes 2,249 synchronized head-camera sets and stops cleanly,
with MCU references returning to zero.

A read-only, DMA-buffer-synchronized capture finds both DMA planes using the
same linear 1920×3664 framebuffer. Its stored pixels contain two optically
distorted views of SteamVR's skybox. This establishes compositor rendering into
the physical scanout buffer; it does not establish clean lens output, a coherent
single-frame capture, sustained presentation rate or measured head alignment.
The original Frame perception library retains SHA-256
`44ca80763343d6588798bb52418611304fd50e2fd7de6ddfce5cbd31989e1984`.
The hash-verified evidence is in
`output/pico-steamvr-session-20261021-v3/export-isolated.tar.gz`
(SHA-256 `9933b940527ab3e446639ef09e6eec12f9b1fa8872eae8156ce158ad039053fa`).

The next Steam launch passes its initial missing data-link failure after creating
the required owned `~/.steam/steam` and `~/.steam/root` links to the client, with
`sdkarm64` selecting its native libraries. It then triggers a `vrserver` SIGSEGV
shortly after Steam connects. The service journal and core dumps preserve this
new blocker; the kernel log does not report a GPU fault. Steam UI presentation
is not yet accepted. Realtime-priority requests also remain denied, despite
raising the unit's resource limits; timing requires separate investigation.

Clean lens output, measured motion scale/direction, sustained compositor timing
and usable Steam UI remain hardware acceptance steps. The default configuration
remains disabled until explicitly supplied.
