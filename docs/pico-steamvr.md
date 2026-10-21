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

Use the bundle's `vrserver` launcher for the native server at the same runtime
location. It retains the existing `/usr/lib64/libnm.so.0` through process-scoped
`LD_PRELOAD`, preserving other preload entries. It does not replace the library
or intercept loader calls. The library is required explicitly; a missing library
stops the launcher.

On the measured userspace, Steam API attachment reloads libnm and faults in
its constructor's error-type registration through `g_intern_static_string()`
and `strcmp()`. An isolated regression with GLib held loaded crashes on the
second normal libnm open. Both `RTLD_NODELETE` and process-start preloading
pass all 16 open/close cycles; the preload test reports linker namespace zero
(`LM_ID_BASE`). The system libnm is 1,613,280 bytes, SHA-256
`d473ee6ddf80926d6a9301badc31f788a3fa10cedbf6884b2840a9628eb8388a`.
Run `tests/steamvr-libnm-lifetime.py` on native Linux as the negative control,
then with `--nodelete` and with
`LD_PRELOAD=/usr/lib64/libnm.so.0` for the two retention cases. The negative
control intentionally may terminate with SIGSEGV; use a disposable process.

GNOME's [module-lifetime contract](https://docs.gtk.org/gmodule/modules.html)
requires modules registering shared static data to remain loaded;
[`g_intern_static_string()`](https://docs.gtk.org/glib/func.intern_static_string.html)
does not copy its input. NetworkManager's
[constructor](https://github.com/NetworkManager/NetworkManager/blob/ed279d788f3b1443254f8ba5a8a3217cf1cf9596/src/libnm-core-impl/nm-utils.c#L512)
invokes the corresponding error-type registration. These contracts corroborate
the observed lifetime failure; they do not imply a general GLib version defect.

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
shortly after Steam connects. The service journal, exact mapped libraries and
core dumps identify the libnm constructor failure described above; the kernel
log does not report a GPU fault. With the retained-library launcher, the next
90-second capture publishes 90,061 tracked poses and consumes 2,249 head-camera
sets. The actual client reports 300 valid poses and no invalid samples. Steam,
its native web helper, the server and compositor remain running through the
display test. All 280 plane queries succeed and observe 96 framebuffer changes
across two buffers. This is evidence of continuing scanout, not a frame-rate
measurement. The capture still shows the skybox, so Steam overlay visibility
remains unverified. The manifest-checked archive is
`output/pico-steamvr-session-20261021-v3/export-steam-render.tar.gz`
(SHA-256 `9cbc2474dc14fee7bed02a18f5280c95475cd4e8d2f52e7a334e18320e1703d9`).
Realtime-priority requests also remain denied, despite
raising the unit's resource limits; timing requires separate investigation.

The physical probe's optional `--dashboard` mode requests the dashboard, then
reports actual dashboard visibility, the two known overlay texture dimensions,
chaperone calibration state and headset activity. It returns 9 if head tracking
passes but the dashboard remains hidden. The ordinary pose-only mode is unchanged;
both modes still require the explicit physical boot serial and `reframed_pico`.
An optional argument after `--dashboard` selects a dashboard overlay by key,
for example `--dashboard reframed.pico.steam`. Omitting that argument preserves
the runtime's default dashboard selection. The request does not change tracking
origins, calibration or headset activity. When a key is supplied, success also
requires that specific overlay to exist, be visible and be the active dashboard.
Dashboard mode also logs sampled `GetFrameTiming` values and before/after
`GetCumulativeStats` records with a monotonic host timestamp. The latter counters
belong to the last scene application; `app_pid=0` does not measure dashboard FPS.
These read-only diagnostics do not change the probe's visibility acceptance.

The next hardware comparison receives another 300 valid head samples but returns
9: Steam's `valve.steam.gamepadui.main` texture exists at 1920×1080 and the named
gamescope overlay at 1280×800; both are hidden. Thus process startup and allocated
UI textures do not establish visible Steam UI. Adding the original Frame
`vrmonitor` identifies a separate loader failure: its bundled Qt 5.7 lacks
`QPushButton::hitButton(QPoint const&)`. The probe reports calibration state 201
(tracking center uninitialized) and activity 0 (idle). Neither observation alone
establishes why the dashboard is hidden. No floor, play area or physical
calibration was fabricated.
Evidence is retained in
`output/pico-steamvr-session-20261021-v3/export-monitor.tar.gz`
(SHA-256 `bb7cd890a3906b15292747df135793b92442f78100059a7fb3490a5d5adc502b`).

The cached Frame Qt 5.15.16 bundle subsequently passes `ldd -r vrmonitor` on the
Pico, and the monitor stays running until the test's cleanup. All 15 staged Qt,
plugin and dependency files match their source manifest. This uses a private Qt
directory first in the monitor's `LD_LIBRARY_PATH`, with its matching XCB plugin;
the preserved SteamVR runtime is unchanged. The transfer carrier is
`output/pico-steamvr-session-20261021-v3/frame-qt.tar.xz`
(SHA-256 `07d23aac0f39aad9f547e3d3e69d83bdaf32a8268e99ab15bb4b6feca60f51c9`).

That session ends because the compositor receives SIGXCPU, not because the
monitor exits. The compositor core records `SI_KERNEL`; its saved process limits
show unlimited ordinary CPU time and a 200,000 microsecond hard realtime limit.
The interrupted render thread is inside the KGSL submission ioctl. The saved soft
limit is 1,100,000 microseconds, consistent with the kernel increment after a
realtime timeout. SDL's [Linux realtime scheduling implementation](https://github.com/libsdl-org/SDL/blob/SDL2/src/core/linux/SDL_threadprio.c)
sets a 200 ms hard limit and half that soft limit before asking RealtimeKit.
That source corroborates the limit values; it does not establish which scheduling
call succeeded in this binary or why this GPU submission exceeded the budget.
The hash-verified compositor-core archive is
`output/pico-steamvr-session-20261021-v4/export-compositor-core.tar.gz`
(SHA-256 `1c4077508fd63eee9fb7f755143a9524caa2ce1dbd06eaa70975e36e90986618`).

A bounded diagnostic sets `SDL_THREAD_PRIORITY_POLICY=other`, `LimitRTPRIO=0`,
`LimitNICE=-20` and `RestrictRealtime=yes` only for the compositor. It keeps the
realtime watchdog intact and does not grant scheduler capabilities. SDL documents
the ordinary-policy hint in its [pthread implementation](https://github.com/libsdl-org/SDL/blob/SDL2/src/thread/pthread/SDL_systhread.c).
The compositor survives the comparison; all sampled compositor threads use
ordinary or batch scheduling. The dashboard probe receives 1,000 valid poses and
no invalid poses but returns 9, with both Steam overlays still hidden. All 280
plane queries succeed and observe 141 framebuffer changes. A scanout capture
still shows only the skybox. This separates the timeout from the unresolved UI
visibility issue; it is not a production timing fix or a frame-rate benchmark.
The manifest-checked archive is
`output/pico-steamvr-session-20261021-v4/export-other.tar.gz`
(SHA-256 `85087e637b4cbe3fe7ad93f66e593a329bb52eaf3848f85630b0a4131a063f78`).

The next session explicitly starts the preserved runtime's ARM64 `vrdashboard`
and requests `ShowDashboard("reframed.pico.steam")`. The probe reports the
dashboard and gamescope overlay visible, with 500 valid poses and no invalid
poses. Both DMA planes use the same 1920×3664 framebuffer; a synchronized readback
contains Steam's controller-setup screen in both optically distorted eye views.
The compositor and Steam remain active through the test. Calibration still
reports 201, so no fabricated room calibration was needed to reach this result.
This establishes rendered Steam UI in the physical scanout with live head poses;
it does not establish clean lens output, physical motion accuracy, input usability
or sustained VR performance. The manual component sequence must include the
dashboard process; Frame's packaged service instead enters through `vrstartup`.
The manifest-checked archive is
`output/pico-steamvr-session-20261021-v4/export-dashboard-service.tar.gz`
(SHA-256 `c19c12642cc45514dd1ff8383f9af8862632fe6e47d5e16cc0bcc6118bf22fc1`).

A same-generation control repeats both default and named requests before starting
`vrdashboard`: both return 9, with 300 valid poses each and the overlays hidden.
After starting `vrdashboard`, the same named request passes with 500 valid poses;
the requested overlay is now both active and visible. Readbacks before and after
show the skybox and Steam's setup screen respectively. This verifies the missing
dashboard process as a visibility blocker in the manual component sequence.
The 90-second capture publishes 90,062 tracked poses, consumes all 2,249 head-frame
sets and stops cleanly with zero MCU references. BOOT and the retained working
DTBO still match their complete backup hashes. The manifest-checked control is
`output/pico-steamvr-session-20261021-v4/export-dashboard-control.tar.gz`
(SHA-256 `2bfe8d80519ec110e456e412e47505c3deb8884031cb6b6f04e8faa7252a681b`).

The timing baseline keeps the selected Steam overlay visible and returns 2,000
valid poses without invalid samples. All 20 sampled OpenVR frame-timing records
are available. Their frame indices advance at approximately 59.87 per second,
while 120 DRM vblank queries measure 119.9999 Hz. Reported compositor GPU time
ranges from 10.50 to 10.73 ms (median 10.56 ms), CPU submission from 0.45 to 0.70 ms
and present spin-wait from 0.004 to 0.011 ms. Application cumulative counters
remain zero with `app_pid=0`, as expected without a scene application. The GPU
samples exceed the 8.33 ms budget for 120 Hz; they do not isolate a shader,
clock, idle-policy or scheduling cause, and include contention allowed by the
OpenVR timing contract. Ordinary compositor scheduling remains diagnostic.
The manifest-checked baseline is
`output/pico-steamvr-session-20261021-v4/export-dashboard-timing.tar.gz`
(SHA-256 `3da157bc16fba79204ef4cd1afba0baa7cbd35102ad0f764bdd650be170be1d5`).

Clean lens output, measured motion scale/direction, sustained compositor timing
and usable Steam UI remain hardware acceptance steps. The default configuration
remains disabled until explicitly supplied.
