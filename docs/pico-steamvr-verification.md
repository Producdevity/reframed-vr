# Neo3 SteamVR verification

These records distinguish source and VM checks from bounded native Pico tests.
Private calibration, binary artifacts and hash manifests remain in gitignored
`output/`. See [driver setup](pico-steamvr.md) for the opt-in configuration.
The [native VR UI guide](pico-steamvr-ui.md) describes the separate main-panel
and toolbar launch contract; its acceptance record is below.

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
`GetCumulativeStats` records with a monotonic native timestamp. The latter counters
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
kernel realtime throttling unchanged and does not grant scheduler capabilities. SDL documents
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

Selecting the cached client's `-vrdisable` option instead of `-vr` runs its normal
Big Picture frontend inside the same gamescope OpenVR dashboard. Valve's
compositor and live tracking remain in use. This removes the separate
`valve.steam.gamepadui.main` overlay; the gamescope overlay remains active and
visible. The captured frontend is still at its input-setup screen. This run
records 1,998 valid poses and two invalid poses; those invalid samples remain an
acceptance concern. All 12 live GPU-frequency samples remain at 305 MHz under
the existing `msm-adreno-tz` governor, whose supported maximum is 587 MHz.
The manifest-checked comparison is
`output/pico-steamvr-session-20261021-v4/export-bpm.tar.gz`
(SHA-256 `0c15595586f6e3e041df379549fb04915534b247680075c7d65f23aed6abddfd`).

A bounded comparison requests the advertised 587 MHz operating point through
`devfreq/min_freq`, after arming an independent 150-second restoration timer.
The vendor devfreq and KGSL source retain maximum-frequency and thermal clamping;
neither control is disabled. All 12 live samples confirm 587 MHz. Median reported
compositor GPU time falls to 6.55 ms (range 6.49–6.89 ms), and the dashboard check
receives 2,000 valid poses without invalid samples. GPU sensors stay below
49.5 °C in the sampled interval. Frame indices nevertheless advance at only
about 64.82 per second, so this does not resolve presentation pacing. Cleanup
restores the original 305 MHz minimum, independently read back afterward; BOOT
and DTBO still match their full backup hashes. No persistent clock policy is
installed. The manifest-checked comparison is
`output/pico-steamvr-session-20261021-v4/export-gpu-opp.tar.gz`
(SHA-256 `9e242cc736b9600b1aee0b5157555ec20b5a9af2aa04ee036be7c75a8f08cade`).

The setup screen is the cached Steam client's generic SteamOS input page,
identified by its `https://s.team/os` link and the matching bundled UI source.
That source supports automatic advancement when a keyboard or controller is
detected. Delivering Return to the focused `Steam Big Picture Mode` X11 window
does not establish setup completion. A temporary standard uinput keyboard is
correctly classified by udev (`ID_INPUT_KEYBOARD=1`), but Steam still reports zero
keyboards and the captured input page remains. The device is destroyed at test
cleanup. The same run receives 2,000 valid poses without invalid samples; queries
for `framesToThrottle`, `powersaveFramesToThrottle` and
`additionalFramesToPredict` return error 5 (unset with no default), so their
returned zeros cannot establish the active throttling policy. Evidence is in
`output/pico-steamvr-session-20261021-v4/export-native-keyboard.tar.gz`
(SHA-256 `ba5c632217f723855a9511e84f0da302c6bcbca3db58ee9d2449fe190a2feaa2`).

A source-matched Continue click through the client's loopback CEF debugger
advances its DOM to `Welcome / Select a language`, but the subsequent physical
scanout still contains the preceding input page. This is control-plane progress,
not accepted presentation of the new page. The manifest-checked evidence is
`output/pico-steamvr-session-20261021-v4/export-steam-cef-v2.tar.gz`
(SHA-256 `703888e3d37201834e905844ddfdff703d4f14ee8c673ca0c7ccb95fdacefe9b`).

The diagnostic root reports Fedora 44, so forcing the client's `-steamos` mode
does not establish a working Frame OS installation. A disposable unprivileged
process successfully enters and leaves FIFO/RR policies at priorities 1 and 80
with the specified limits. A combined launch comparison then removes `-steamos`,
enables gamescope's installed `-e` Steam integration, allows priority 80 and sets
a 2/2.5-second realtime limit, while retaining the SDL ordinary-policy hint and
the bounded 587 MHz request. This profile fails: the compositor's saved live
limits have nevertheless been reduced to 100/200 ms, all sampled thread policies
remain ordinary/batch, and the service journal reports SIGXCPU after 23 seconds.
The camera helper later exits on SIGSEGV. Those observations do not establish a
single cause for both failures. This profile is rejected; its realtime limits
and launch changes are not adopted as a verified replacement configuration.
The manifest-checked archive is
`output/pico-steamvr-session-20261021-v4/export-native-profile.tar.gz`
(SHA-256 `0546ecc20dfe11b210152ae8687a480302b60f7285f2d8e836722ff228c940f3`).

The GPU minimum is restored to 305 MHz, complete BOOT/DTBO hashes still match,
MCU references return to zero and both DSPs go offline before reboot. The Pico
returns to b1977 with Wi-Fi off, the updater disabled and `flash.locked=0`, recorded
in `output/pico-steamvr-session-20261021-v4/stock-return-final.json`.

### Login rendering and presentation boundary

A fresh RAM session on 2026-10-22 retains ordinary compositor scheduling,
the 305 MHz GPU minimum, both DMA planes and 120 Hz. Removing the diagnostic
client's `-steamos` flag and enabling gamescope's `-e` Steam integration takes
the client directly to its Linux login route. The named gamescope dashboard is
active and visible, with 2,000 valid poses and no invalid samples. Both the
camera helper and SLAM consumer exit successfully and release the MCU reference.
The loopback CEF inspection finds the login form, but the physical scanout still
contains Steam's loading logo. This is not accepted presentation of the login UI.
The manifest-checked archive is
`output/pico-steamvr-session-20261022-v1/export-linux-ui.tar.gz`
(SHA-256 `fbe47dc5dab9cfb65184d1e7352d4209f534d691775787a5cf8b208b81d44eff`).

Steam's webhelper logs `AcquirePixmap` failures, `BadMatch` and `GLXBadPixmap`.
[Valve issue 10456](https://github.com/ValveSoftware/steam-for-linux/issues/10456)
reports the same error sequence on another graphics stack; that report does not
establish a shared cause. A bounded comparison uses the cached client's supported
`-cef-disable-gpu` option, leaving Valve's VR compositor GPU accelerated. The
webhelper confirms disabled browser GPU compositing and creates a system window.
Its CEF screenshot contains the login form, while the physical scanout still
contains the loading logo. Another 2,000 pose samples are valid with none invalid,
and both capture processes stop successfully. Disabling browser acceleration
therefore does not resolve the measured presentation failure and is not adopted
as a verified fix. The manifest-checked archive is
`output/pico-steamvr-session-20261022-v1/export-cef-software.tar.gz`
(SHA-256 `846c23c57c392a66fe39b2ddce0cb447fcc0a6fad28171581cf91c253a5675b0`).

The next comparison isolates stale gamescope shared-memory uploads. X11 window
pixels contain the login form, and the focused window is Steam Big Picture
(`STEAM_GAME=769`). The Wayland trace shows repeated 1280×800 `wl_shm` buffer
reuse. In gamescope 3.16.29, `import_commit()` memoizes the uploaded snapshot by
buffer identity, even when the next commit supplies new pixels. The local
[patch](../patches/gamescope/README.md) retains DMA-BUF memoization and uploads
each shared-memory commit into a new texture, preserving in-flight ownership.

Both the control and candidate use the same Fedora source, compiler,
dependencies and Meson configuration. The unmodified rebuild still shows the
loading logo; the patched rebuild renders Steam's login form into the distorted
stereo scanout. The early native buffer has SHA-256
`3bc999029bab24bda9cf1a4ee0d3d8ec6339bfcdbe9a056ded4398208f630913`.
Later in that candidate run the physical probe receives 2,000 valid head poses
without invalid samples, but CEF diagnostic capture times out. This closes the
isolated stale-image failure, not the complete session's stability or input
acceptance. The binary/source hashes and license notices accompany the patch.
The manifest-checked control and candidate archives are respectively:

- `output/pico-steamvr-session-20261022-v2/export-control.tar.gz`, SHA-256
  `f13edc4b3c40a88033843c419ca74d4d5f95199c03ca342e554bb436b946c3c5`.
- `output/pico-steamvr-session-20261022-v2/export-shm-ready-result.tar.gz`, SHA-256
  `62143791e4d1a4c8a1ee15d8a189a9c18d5bce541dde993dd10ea1129c2197d3`.

A subsequent run omits CEF debugging. It receives another 2,000 valid head poses,
then the vendor feed stops with `ENOBUFS` after 69,930 matched IMU pairs. Its
32-sample IMU pairing limit is exhausted; the camera queue has one pending set
against a limit of eight. After subtracting 708 startup discards and twice the
pair count, the consumed-record counter identifies the 33rd unpaired input.
The ring has overwritten that failed record by export time, so its exact values
are unavailable. The surviving matching gyro burst supports batched sensor
delivery. Both before/after input captures are grey: input delivery succeeds,
but the intended toggle's rendered effect is unverified. The wrapper's zero
exit status is not acceptance: the SLAM consumer exits 4 and camera helper 1.
The manifest-checked archive is
`output/pico-steamvr-session-20261022-v2/export-shm-ui.tar.gz`, SHA-256
`ca19bc64b225364bd828fa5c17b95f47568852b2b7ed216b5a18f400dce64df8`.

### Overlay transport and memory growth

Increasing the IMU pairing capacity to 256 removes that overflow, but a later
combined run fails closed with `ETIMEDOUT`. An initial full-composition comparison
finishes camera and SLAM capture but still shows growing memory pressure and
four invalid client samples in its late 2,000-sample check. Its IMU producer
also fills its ring after the consumer stops, because VR cleanup precedes
producer shutdown. That wrapper's zero status is not complete acceptance.
The diagnostic now stops and joins the producer immediately after the consumer,
before VR teardown, and checks all three component exit statuses.

The next run adds DMA-buffer, ION, process-RSS and scheduler samples. With
per-buffer DMA import enabled, gamescope-created DMA allocations grow from
7.9 MiB at about 20 seconds to 2,525.3 MiB at 70 seconds. The kernel's DMA-process
accounting shows these buffers held by `vrcompositor`. The vendor SLAM allocation
is stable at 52.4 MiB before its shutdown. Available memory falls to 142,308 KiB;
the late physical client reports 2,000 invalid samples and no valid samples.
This identifies a retained-buffer path and correlated pressure, not the precise
internal resource-lifetime defect in Valve's closed compositor. The checked
archive is `output/pico-steamvr-session-20261022-v2/export-shm-resources.tar.gz`,
SHA-256 `1c21cd8cabdb281f3bee94cb122d3b8f6bf7b14bd9221a15377985bf8624e75b`.

Keeping the same patched gamescope binary, full composition, optics, freshness
limits and ordinary scheduling, setting `gamescope_vr_use_modifiers=false` uses
the existing Vulkan overlay texture path. Gamescope's DMA allocation now stays
around 15.6–19.5 MiB after startup; compositor-created storage stays at 133.0 MiB.
From 50 seconds onward, sampled available memory stays between 2,192,068 and
2,474,944 KiB. Camera, SLAM and IMU all exit zero: 2,249 complete head-camera sets,
92,347 matched IMU pairs, 90,066 published tracked poses, no publication failure
and no ring overflow. The late client receives 2,000 valid poses and none invalid.
An earlier dashboard-readiness check still has one invalid sample out of 500;
the entire startup is therefore not claimed loss-free.

Before/after native scanout captures show the login form's Remember-me toggle
changing from on to off after a scoped X11 click. The input helper verifies the
focused Steam window and its 1280×800 geometry, clicks the switch at `(1104,467)`
and moves away before capture. An earlier `(1235,472)` click was outside the
switch and did not establish interaction. The accepted before/after native hashes
are respectively
`4bf75b95c4166a0af233480711ff678b72819bb6f4d89b930328afa0d63dec4b` and
`b983850265bb27ea65f82c8e145cc08f5173d33d76ff25c1221192295968c8f5`.
This verifies a rendered UI response through Valve's compositor, not controller
support or lens acceptance. The manifest-checked archive is
`output/pico-steamvr-session-20261022-v2/export-shm-vulkan.tar.gz`, SHA-256
`e404af746e738439dd639ed9c87ae0d300bec96af84a45d7059c214048095fc2`.

The current opt-in gamescope environment selects that Vulkan transport.
Sampled compositor GPU times remain around 10.6 ms in this diagnostic, above
the 8.33 ms budget for 120 Hz. The frame-index cadence with `app_pid=0` still does
not establish physical scanout FPS. This workaround closes the measured buffer
growth for a bounded session; long-session performance remains unverified.

### Supported GPU point and DRM timing

A further bounded comparison keeps that transport and requests the supported
587 MHz GPU minimum, restoring 305 MHz afterward. Its camera, SLAM and IMU
processes all exit zero, with 2,249 camera sets, 92,472 matched IMU pairs and
90,061 published tracked poses. The three physical-client checks receive
300, 500 and 2,000 valid poses respectively, with no invalid samples. Sampled
compositor GPU time in the late check is 6.490–6.976 ms, median 6.613 ms. This is
below the 8.33 ms nominal 120 Hz budget; it is not end-to-end photon latency.

A private ftrace instance records the kernel's existing DRM vblank and delivery
tracepoints without changing global tracing. All 25,424 entries are retained;
per-CPU overrun and dropped-event counters are zero. Between the dashboard-ready
and late-probe-finished markers, a 24.851-second interval contains 2,982
consecutive CRTC-0 vblank sequences: 119.999965 Hz, median interval 8.332 ms,
95th percentile 8.411 ms and maximum 8.994 ms.

The same interval contains 4,786 delivered callbacks covering those same 2,982
sequences. Multiple callbacks therefore occur within a vblank. This kernel's
delivery format identifies a DRM file rather than a submitting PID and does
not identify the callback's buffer or present ID. Counting callbacks, or their
unique sequence numbers, cannot establish newly rendered frames per second.
The trace does not identify which remaining delay belongs to render submission,
presentation completion or runtime policy. `WaitForPendingPresent` errors remain
in the compositor log; presentation pacing is still an open issue.

The trace instance is disabled and removed after capture, and the original GPU
minimum is restored. The manifest-checked archive is
`output/pico-steamvr-session-20261022-v2/export-shm-timing.tar.gz`, SHA-256
`3c6b565e00e7107a0a1904baa023968eb995a9162de3fe23823e842e9cfb1075`.
The retained trace's SHA-256 is
`74e8dccae00ebe809fca57e60d3b9273a114f34c4ce0175b208d5a0660b65d15`.

The updated physical-driver bundle builds offline in the cached ARM64 Fedora
container. All nine packaged artifacts match its manifest, including the opt-in
compositor scheduling and gamescope transport drop-ins. This is a bundle check,
not installation of a Frame-based operating system.

After these RAM-only tests, complete BOOT and DTBO readbacks still match the
retained recovery hashes. All VR service cgroups are empty, MCU references are
zero and both DSPs go offline before reboot. At 2026-10-22 00:31:32 UTC, stock
b1977 returns with Wi-Fi off, the updater disabled and `flash.locked=0`, recorded
in `output/pico-steamvr-session-20261022-v2/stock-return-final.json`.

Clean lens output, measured motion scale/direction, sustained compositor timing
and usable Steam UI remain hardware acceptance steps. The default configuration
remains disabled until explicitly supplied.

### Present-wait setting and API-level measurement

A fresh RAM boot compares `steamvr.disableLinuxWaitForPresent` as false, true,
then false again. The kernel, patched gamescope Vulkan transport, 587 MHz GPU
minimum, optical profile, freshness limits and ordinary scheduling are retained.
Each 90-second run completes 2,249 head-camera sets, and camera, SLAM and IMU
processes all exit zero. The original 305 MHz GPU minimum is restored each time.

| Setting | Logged present-wait failures | Late valid / invalid poses | Median sampled compositor GPU time |
| --- | --- | --- | --- |
| false, first control | 49 | 2,000 / 0 | 6.760 ms |
| true | 61 | 2,000 / 0 | 6.670 ms |
| false, repeat control | 64 | 1,999 / 1 | 6.721 ms |

All three compositor logs still report `Enabling eKHRPresentWait support!`.
The repeat's one invalid pose is retained as a failure of loss-free acceptance.
This comparison establishes no benefit from that setting on this path and does
not justify adding it to the session template. It does not identify the cause
of the variation in error counts.

Valve documents the contingency setting in
[SteamVR-for-Linux issue 948](https://github.com/ValveSoftware/SteamVR-for-Linux/issues/948).
That report concerns an Index/RADV/DRM-lease stack, and its reporter subsequently
retracts the setting as the cause of recovery. It supplies a supported option
to test, not a diagnosis of this Neo3.

The manifest-checked archives under
`output/pico-steamvr-session-20261022-v3/` are:

| Archive | SHA-256 |
| --- | --- |
| `export-present-enabled-a.tar.gz` | `52444dc194c787053b3e0d250de54367aea7e614eae44fd966461a311d91e3cd` |
| `export-present-disabled.tar.gz` | `12a3f1acffeb57156d8e1f7125c4723a05138c32d4976fb3ec635d2c94278713` |
| `export-present-enabled-b.tar.gz` | `dbcdfef1cc48306fc30dfe37a1491036d61549e1c886f9a5ceb59f00dd39e314` |

A fourth bounded run adds a private, explicit Vulkan diagnostic layer only to
`vrcompositor`. It records call arguments, monotonic entry/return times, present
IDs and return codes, forwarding the calls unchanged. The loader chain first
passes an offline ARM64 Lavapipe test with two instances and devices, including
preserved fence timeout and success results. This follows Khronos's
[loader/layer interface](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderLayerInterface.md).
The layer and VM harness remain private experiment artifacts, not installed
runtime dependencies or part of the driver bundle.

The maintained live probe now reads the setting through `IVRSettings`.
On this run it reports `present_wait_disabled=1 error=0`; nevertheless the
compositor's `CHmdWindowVulkanWSI` path makes 5,985 `vkWaitForPresentKHR` calls.
All use a 15,000,000 ns timeout: 5,928 succeed and 57 return `VK_TIMEOUT`.
Those 57 returns match the 57 compositor log failures. This directly establishes
that reading the option as true does not disable these calls in this runtime.
It does not establish why Valve handles this direct-display path differently.

Between dashboard readiness and the late probe's end, the 24.772-second trace
contains 1,800 swapchain present submissions, about 72.66 per second, and 2,972
CRTC-0 vblank events. Submitted present IDs identify queued frames, unlike the
earlier undifferentiated DRM callbacks; they still do not establish photon
latency, clean lens output or physical motion acceptance. The trace records
a median 6.653 ms from present return to entry into the wait for that present.
This first trace alone does not identify what occupies that gap.
Instrumentation overhead is not separately calibrated, so this is a diagnostic
measurement rather than an uninstrumented performance benchmark.

Camera, SLAM and IMU again exit zero. The late probe receives 2,000 valid poses
and no invalid samples. The manifest-checked archive is
`output/pico-steamvr-session-20261022-v3/export-present-api.tar.gz`, SHA-256
`ee0970305b97db5203ced7d740572f2cabd5689cc1c18747f7561f93d789873d`.

A second trace also records query-result, semaphore and idle waits, without
changing their arguments or return values. Its 55,529 records stay below the
200,000-record diagnostic limit. In the 24.823-second active window, each of
the 1,799 present submissions is followed on the same render thread by
`vkGetQueryPoolResults` for four queries with flags `3`:
`VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT`. These calls take a median
6.456 ms, 95th percentile 6.915 ms, totaling 11.366 seconds in that window.
The present wait follows afterward. This identifies a host-blocking query read
in the previously unmeasured gap; its precise internal purpose is not exposed
by the trace. Calling it a GPU-timestamp read remains an inference rather than
a recorded query-pool type.

Khronos's [query-result contract](https://docs.vulkan.org/refpages/latest/refpages/source/vkGetQueryPoolResults.html)
requires the requested wait. Removing that flag or returning invented query
results in a wrapper would change the application's synchronization semantics,
so the diagnostic does neither. A correct pacing change must account for this
serialization, rather than treating GPU duration alone as the complete frame
budget. The trace establishes 72.47 submitted presents per second in that
window, not an uninstrumented FPS result or proof of an unavoidable ceiling.

The second trace contains 76 present-wait timeouts. Its camera, SLAM and IMU
processes all exit zero, but its late check has 1,998 valid poses and two invalid
samples. It is not accepted as loss-free tracking. The checked archive is
`output/pico-steamvr-session-20261022-v3/export-present-sync.tar.gz`, SHA-256
`1a73d7011b32cd41cd7ead1c8b84d156a638b417710d70979bca7a145090f8a7`.

A final bounded comparison uses the kernel-advertised 90 Hz mode. A private copy
of the optical profile changes only `screen.frame_interval_ns` from 8,333,333
to 11,111,111; the session's `preferredRefreshRate` is also set to 90.
The original profile is unchanged and the original session settings are restored
afterward. The compositor selects `1920x3664@90.000008Hz`, and the trace measures
89.999984 Hz vblank cadence. This verifies the requested hardware mode, rather
than assuming the settings selected it.

The 24.784-second active window contains 1,490 submitted presents, about 60.12
per second. The four-query read still blocks for a median 6.323 ms. The full run
has 14 present-wait timeouts; fewer logged failures therefore do not establish
better throughput. All three capture components exit zero, with 2,249 camera
sets and 2,000 valid late poses without invalid samples. The 90 Hz comparison is
not adopted as a pacing fix. Its checked archive is
`output/pico-steamvr-session-20261022-v3/export-present-90hz.tar.gz`, SHA-256
`88372ece2fbffedce4711db2f41cf253c38b296f989f526fd6cf02de070eb615`.

The updated driver bundle builds offline in the cached ARM64 container. All nine
artifact hashes match its manifest, and the packaged live probe has the same
SHA-256 as the probe that reads both true and false successfully on this Pico:
`41a12ca6394f3856fb4fe5e5c8684f9ea0e23230644d6ad2c470f781227ffd72`.
The output is `output/pico-steamvr-bundle-20261022-v3/`.

After these RAM-only comparisons, the full BOOT and DTBO hashes still match the
retained recovery inputs. All VR cgroups are empty; MCU references are zero,
SLPI and CDSP are offline, and the GPU minimum is back at 305 MHz. Stock b1977
returns at 2026-10-22 01:06:41 UTC with Wi-Fi off, updater disabled and
`flash.locked=0`. The receipt is
`output/pico-steamvr-session-20261022-v3/stock-return-final.json`.
No partitions are written, and the Quest is untouched.

### Standalone direct-display capacity

A separate display-only RAM boot runs the direct Vulkan path as the same `vr`
user, using the same Mesa library, two-image FIFO, split-DMA opt-in and supported
587 MHz GPU minimum. Cameras, SLAM, SteamVR and their DSP owners are not started.
The private diagnostic derives from the retained dual-DMA probe, presents solid
green, checks 400 GPU-readback pixels per frame and verifies both DMA halves
after primary initialization and at the end. It removes per-frame DRM inventory
queries and logging from the measured loop. Each run completes 600 present IDs;
the reported rate excludes the first 30 completions.

| Run | Added host delay after the GPU fence, before present wait | Completed presents per second |
| --- | --- | --- |
| First control | none | 120.023 |
| Delay comparison | 6,500 microseconds | 105.404 |
| Repeat control | none | 119.987 |

All three exit zero and restore the GPU minimum to 305 MHz. No measured
present-to-completion interval after warmup exceeds 15 ms. The actual wait uses
a generous three-second deadline; this is not the compositor's 15 ms timeout
test. This light clear/readback workload also does not reproduce SteamVR's GPU
work or its surrounding CPU scheduling. It establishes full-refresh capacity
for this workload and rules out an unconditional approximately 73 Hz limit in
the direct path. The blocking query read identified above is a measured cost;
this comparison does not establish it as the sole cause of SteamVR's cadence.

The first diagnostic attempt incorrectly requires dual DMA on the initial
primary-plane frame and exits before collecting a rate. The corrected guard
allows that bootstrap frame and verifies both DMA halves on the second and final
frames. Both versions and the rejected log are retained. The corrected
binary's SHA-256 is
`46790ab8a70e3570f823158a70e53e4219d3be1b71ce32d73a6349099c89dfc3`.
The five exported files pass their manifest checks in
`output/pico-present-bench-20261022-v1/export-bench.tar.gz`, SHA-256
`85b43994d14b3a5e211b70e2294b0098c675f75d63d9436f8a24e57e4d00b640`.

This display-only session also differs from a started-and-stopped tracking
session: the vendor subsystem interface reports SLPI/CDSP as `OFFLINING`.
The pinned kernel's `subsystem_restart.c` defines that state as zero and
zero-initializes newly registered subsystems; only a lifecycle transition sets
`OFFLINE`. These strings alone do not establish active shutdown. No DSP-owner
units exist, no camera/SLAM/renderer processes or open FastRPC/SPI descriptors
remain, MCU references are zero and the GPU minimum is restored. The kernel has
no `/sys/class/remoteproc/remoteproc*` entries, so an empty remoteproc iteration
is not accepted as proof of DSP state. The display-specific recovery check
records the actual vendor states before normal reboot.

Complete BOOT/DTBO hashes still match the retained inputs. At 2026-10-22 01:20:48
UTC, stock b1977 returns with Wi-Fi off, updater disabled and `flash.locked=0`,
recorded in `output/pico-present-bench-20261022-v1/stock-return-final.json`.
No partitions are written and the Quest remains untouched.


### Renderer comparison and client vsync timing

A 2026-10-22 legacy/Facet/legacy comparison uses the same native compositor,
120 Hz optical profile, patched gamescope Vulkan transport, ordinary scheduling
and bounded 587 MHz GPU minimum. Each complete capture lasts 90 seconds; the
rates below cover the approximately 25-second marked dashboard/probe window.
They count submitted present IDs under instrumentation, not physical FPS.
The private diagnostic now records query-pool creation: all observed pools are
`VK_QUERY_TYPE_TIMESTAMP` (2), confirming the query type that the earlier trace
could only infer.

| Renderer | Submitted presents/sec | Median sampled GPU time | Median four-query wait |
| --- | ---: | ---: | ---: |
| Legacy control | 66.42 | 6.883 ms | 6.552 ms |
| Facet candidate | 102.54 | 6.189 ms | 0.000989 ms |
| Legacy repeat | 71.56 | 6.758 ms | 6.453 ms |

All three consume 2,249 camera sets, return zero from camera, SLAM and IMU
processes, and receive 2,000 valid late poses without invalid samples. Kernel
vblank remains approximately 120 Hz. Every traced swapchain-counter read matches
the latest kernel CRTC-0 sequence. Facet's active-window present waits all
succeed; the two legacy windows have seven and ten timeouts respectively.
This identifies a faster renderer path, without proving the blocking query read
alone explains the difference.

The renderer choice comes from Valve's retained Frame runtime resource
`drivers/frame_hmd/resources/frame_hmd_additional.vrsettings`, SHA-256
`c3d5351b1f15c1f39a75fbcd419fadeb9b362737de54e2d8cf9f54aa2335df12`.
The unchanged compositor has SHA-256
`9b1bd5fe4463592cbc71b2517b9ceb0a0fcd66cd6885a19dca4be0784bf6c265`.
Only `useFacetRenderer` changes in the initial comparison. Frame's optics,
photon latency and simplified/achromatic shader settings are not imported.
Facet scanout contains the Steam login UI in both distorted eye buffers; the
CPU copy is not proven coherent or optically correct.

At this stage, Facet was not adopted: `GetTimeSinceLastVsync` returns true and an advancing
counter, but its sampled age is 506–526 seconds, matching device monotonic uptime
rather than time since vblank. Both legacy controls return millisecond ages.
A private experiment reports real timestamps from the vendor kernel's read-only
CRTC-0 `vsync_event` attribute through OpenVR driver notifications. It does not
open a DRM node or acquire master. Two of 20 sampled ages still return uptime;
adding explicit driver-vsync ownership leaves five of 20 invalid. Thus neither
workaround is accepted. The first also has one invalid late pose; the ownership
comparison has 2,000 valid poses and none invalid. All three capture components
exit zero in both. Their tracked driver changes are removed; rejected sources,
build manifests and binaries remain private. Competing timestamp updates were a
hypothesis; the subsequent ABI investigation below identifies the missing time output.

A separate comparison enables Frame's `renderSystemLayerInDistortPass` option
on the legacy renderer. The compositor reaches startup and then dies with
SIGSEGV, confirmed by its unit journal and core-dump record. A missing monitor
log also interrupts the private failure collector; this run is not accepted as
a successful tracking or timing test. Its trace, journal, dump and stopped-state
evidence are retained. For this control, the session template pinned both renderer
options false rather than relying on runtime defaults.

The manifest-checked archives below are under
`output/pico-steamvr-session-20261022-v4/`:

| Archive | SHA-256 |
| --- | --- |
| `export-legacy-control.tar.gz` | `ef5260781c38b5a547525587e22a06a8a982eb1814100e438dc5c76cf28cec97` |
| `export-facet-candidate.tar.gz` | `a00608d94efc0eddc972700383c96082f06dfee54001160539d446f81cbc787a` |
| `export-legacy-repeat.tar.gz` | `f957aef7127ca7ce26a03b2e8dfecd77db708d7278c362f1c0abbeee199e32e1` |
| `export-facet-vsync.tar.gz` | `bc8fcc2adc9a44cab73f3be1cf53932f40eb66b24a3d4df2675cb5157c96fd6d` |
| `export-facet-vsync-owner.tar.gz` | `ac6e780a5c6e1ee368ebc01c90be6f679d0a89ae06cb8a133b8059b8e0dff9f8` |
| `export-legacy-fused.tar.gz` | `6e465cc7885ca3aae5f0240b8312c70636abd4f104422a3f1c843e8f6cf977d2` |


With the layer option disabled again, the clean driver and denser probe complete
another 90-second capture. The control submits 72.74 presents/sec in its marked
window, with median GPU time 6.594 ms and a 6.397 ms four-query wait. Its 2,000
vsync-age samples contain zero invalid values against the two-period bound
(16.667 ms). The named Steam dashboard is active and visible. Tracking has
1,999 valid poses and one invalid sample, so this is not accepted as loss-free
tracking; camera, SLAM and IMU nevertheless all exit zero. Disabling the layer
option removes the observed startup crash in this control; its exact failing
internal resource remains unidentified.

The final archive is `export-legacy-dense-control.tar.gz`, SHA-256
`b75f6815a73e61fb9dac003ca699f11a05b02d279ef4df22c68ed14bfb898532`.
The clean ARM64 bundle is `output/pico-steamvr-bundle-20261022-v5/`; all nine
artifact hashes match its manifest. Its driver and live probe are byte-identical
to the final control's binaries. The probe has SHA-256
`e3c95f5fcdcab9ca0e3f0336ff3aea055947c6a12dbfdc0ab6f9842223a2d805`.
Host ASan/UBSan optical-profile and pose tests also pass. The diagnostic adds
renderer, timing-phase and dense vsync-age reporting without changing the
existing pose/dashboard exit criteria. Physical motion, clean lens output and
sustained frame pacing remain separate acceptance gates.

Complete BOOT/DTBO readbacks still match the retained recovery inputs. All VR
cgroups are empty, MCU references are zero, CDSP/SLPI report `OFFLINE`, and the
GPU minimum is restored to 305 MHz before reboot. At 2026-10-22 02:05:28 UTC,
stock b1977 returns with Wi-Fi off, updater disabled and `flash.locked=0`.
The receipt is `output/pico-steamvr-session-20261022-v4/stock-return-final.json`.
No firmware partitions are flashed; the Quest is untouched.

### Frame counter ABI and pose read order

A fresh 2026-10-22 RAM session identifies the Facet uptime-age fault in the
retained ARM64 compositor, SHA-256
`9b1bd5fe4463592cbc71b2517b9ceb0a0fcd66cd6885a19dca4be0784bf6c265`.
Its `PostVsyncEvent` requests private swapchain counter `0x7ffffffd` into a
zero-initialized two-word output. Original Mesa writes only the sequence and
returns success. The compositor subtracts the unwritten zero timestamp from
CLOCK_MONOTONIC. API tracing confirms the private argument; disassembly confirms
the two outputs and subtraction. Valve's official Frame Mesa independently
confirms the paired DRM query, as recorded in the
[Turnip ABI description](turnip.md#frame-compositor-counter-timing).

A private guard-only comparison rejects the unsupported counter and forces the
compositor's public-counter fallback. It removes uptime-sized ages, but its
sampled timestamps differ from the same reported kernel counter by 47–485
microseconds. Turnip patch 0015 instead implements the verified pair behind
`MESA_VK_WSI_FRAME_COUNTER_TIMING=1`, scoped to the compositor. In two native
captures, the absolute sampled discrepancy is at most 7.1 and 8.1 microseconds.
This compares the timestamp of the **reported sequence** against kernel ftrace
and brackets the client call with CLOCK_MONOTONIC reads; comparing against the
latest kernel sequence would incorrectly count one-cycle notification delay as
timestamp error. There are 20 matched samples per capture, not continuous
microsecond-accuracy proof.

The occasional invalid pose has a separate verified cause. The old reader
sampled time before copying the channel. A concurrent writer could then publish
between those operations, making valid current data appear to come from the
future. A deterministic interleaving reproduces it. An instrumented old-order
native control records 13 future-time rejections and nine contention rejections
by its late observation point. The corrected driver samples time after a
coherent copy, preserves all freshness/generation checks and bounds live retries
at 64 without sleeping. It exposes read-only reason counters through
`pose-read-stats`; failed reads still return invalid tracking.

All four 90-second captures below consume 2,249 synchronized camera sets and
return zero from camera, vendor SLAM and IMU. Each late 100 Hz client receives
2,000 valid poses and none invalid. Counter failures below mean unavailable,
non-finite, negative or greater-than-two-period ages. The last two runs no longer
show the original zero-timestamp fault in sampled records, but their aggregate
age checks do not classify each residual failure. Some sampled client counters
are one vblank behind the latest kernel sequence.

| Configuration | Submitted presents/sec | Invalid late vsync ages / 2,000 | Driver future / busy reads at late probe |
| --- | ---: | ---: | ---: |
| Original Mesa, instrumented old-order reader | 90.25 | 2,000 | 13 / 9 |
| Guard-only fallback, old-order reader | 89.79 | 13 | 3 / 5 |
| Paired counter, clock-after-copy reader | 97.60 | 8 | 0 / 4 |
| Same paired configuration, fresh-generation repeat | 104.27 | 10 | 0 / 1 |

These present rates cover the marked approximately 25-second instrumented
window, not physical FPS. Kernel vblank remains 120 Hz. Both paired runs have
zero failed present waits in that active window, with two earlier startup
failures each. Median sampled compositor GPU time is 6.220 and 6.106 ms.
The first paired run's four busy reads occur before its late 20-second client
check; the repeat gains one busy read during that check. The 100 Hz client can
miss short invalid publications by the faster driver. Thus the future-time race
is fixed, but loss-free tracking and sustained 120 Hz presentation remain open.
No stale-pose fallback is introduced.

The tested paired Mesa has SHA-256
`1e14b9b9390e30227ef787f6516c464c85565cda3a35091dd095a78b16e72c5e`.
The final rebuild `output/mesa/pico-frame-counter-20261022-v3/` produces the same
library and passes twelve helper suites plus five Freedreno tests. Before the
capture, native GPU interop and four 4 MiB cross-exec buffer-sharing cases pass:
binary and timeline OPAQUE_FD, each with exportable and import-only receivers.
The tested driver has SHA-256
`2b3f2c937390e966bde8561c78e5664e39a7b8ede1a74fb0f8f26e3bbe86e22c`;
the timing/pose probe has SHA-256
`16d7a09304af17aafcaad173f8faeddecc72591bf35583ee87d9afd5a080d5a3`.
The instrumented old-order control is retained privately, SHA-256
`267c63e6e46e54f9b283c91c11860e36c238d30a7118e95d5fc9712db2d5f3b4`.
It is not the original shipping binary and is not packaged as the candidate.

The manifest-checked archives are in
`output/pico-steamvr-session-20261022-v5/`:

| Archive | SHA-256 |
| --- | --- |
| `export-facet-baseline.tar.gz` | `e6f56acbab3332c0be470c012414d854b35f1544846b22045bd6107af7aafa64` |
| `export-facet-counter-fallback.tar.gz` | `7b2632642b634afc1cc8683125872df0e07d53a990bdfff3e8d50282d8150f60` |
| `export-facet-paired-clock.tar.gz` | `6d319b61b323cdb9af124afc92f30af9da2398d426b65f9656751dafd2d7c7cf` |
| `export-facet-paired-repeat.tar.gz` | `34028dd55132c9103a83951f51a84b28981b3efb4db861ee95a34402fdc67c65` |

The first paired run's hash-checked XR24 scanout contains Steam's login form in
both distorted eye buffers. Its read-only synchronized CPU copy is not proven
coherent or optically correct. Clean lens output, measured motion scale/direction
and sustained compositor pacing remain separate acceptance gates.

The final `output/pico-steamvr-bundle-20261022-v6/` manifest matches all nine
artifacts and 20 source hashes. Its driver and probe are byte-identical to the
native-tested candidate. The opt-in session template now selects Facet and the
compositor drop-in enables paired counter timing; the layer option stays off.
The host optical-profile and pose/channel sanitizer suites also pass.

Full BOOT and DTBO readbacks still match the retained recovery backups. All VR
cgroups are empty, MCU references are zero, CDSP/SLPI report `OFFLINE` and the
GPU minimum is restored to 305 MHz before normal reboot. At 2026-10-22 05:43:33
UTC, stock b1977 returns under a new boot UUID with Wi-Fi off, updater disabled
and `flash.locked=0`. The receipt is
`output/pico-steamvr-session-20261022-v5/stock-return-final.json`.
No firmware partitions are flashed; the Quest remains untouched.

### Two-slot pose publication

A fresh 2026-10-22 native session adds exact vsync-failure reasons and privately
timestamps contended pose reads. The old ABI-1 reader exhausts its 64 attempts
in one observed 260-nanosecond read; the writer has already completed by the
subsequent diagnostic sequence load. A complete old-channel control records
three busy rejections at its late observation point. Thus this failure does not
require a long descheduled writer: the retry count can be shorter than an
ordinary in-progress publication.

ABI 2 uses a 232-byte mapping with two payload slots. The writer updates the
inactive slot and atomically commits its selection. The reader can copy the
committed slot during an in-progress write, checking for a concurrent commit.
The read remains bounded and still rejects expired, malformed, stopped,
wrong-generation and future data. Old ABI-1 mappings are refused; producer and
driver must be rebuilt together and use a fresh mapping.

All seven focused host sanitizer tests pass. Regressions cover a partially
written inactive slot, expiry while publication is interrupted, old-version
refusal and existing concurrent/process transport and lifecycle cases. The
ARM64 driver is built in `output/pico-steamvr-channel-v2-20261022-v1/`, SHA-256
`5c93fad67c03315c36b7c20475e9d0877141c80034aef9f586a083ce4ffb5ef3`.
The two complete native captures each consume 2,249 camera sets and return zero
from camera, SLAM and IMU. Their late clients each receive 2,000 valid poses;
driver counters at those observations show 48,188 and 48,494 successful reads
with all rejection categories zero. These counters are snapshots before session
shutdown, not a proof of indefinite loss-free or physically calibrated motion.

The second capture also attempts a compositor scheduling change; the actual
render thread remains ordinary scheduling, so that attempt is not evidence of
realtime scheduling. The ABI-2 binaries are unchanged between these captures.
An earlier private harness attempt incorrectly assumed the old 136-byte layout
and stopped before SteamVR startup. The corrected harness explicitly checks ABI
and size and selects the committed slot. That failed attempt is not counted as
hardware acceptance.

The archives are in `output/pico-steamvr-session-20261022-v6/`:

| Archive | SHA-256 |
| --- | --- |
| `export-fault-replay.tar.gz` (old-channel control) | `2ae4f02ef7ea8382fcb5d26df0aaf88502d5164eb67e956ad2e23448a884f92f` |
| `export-channel-v2-test.tar.gz` | `1305a2012650c6ad5fe2bf1a0753e3e74975ff2a9640ae6f2d9a8f500a5a7de7` |
| `export-compositor-rr.tar.gz` | `071bc70cea1f164c4aabd6f212f522f22124252fa27f13901e61effeb369fe57` |

A preceding diagnostic capture stops with feed `EPROTO` after about 36 seconds.
The later camera/IMU ring exhaustion follows that stop; the exact rejected input
was not retained. Its archive, `export-fault-baseline.tar.gz`, SHA-256
`433ce4bd4418782d1c6fb7775913b13f2a9ab9e47bf0fd2e675cce225670fdad`,
is retained as a failure. Subsequent captures add exact feed-failure location
diagnostics and complete successfully; this does not explain or dismiss that
earlier protocol failure.

Full BOOT/DTBO readbacks still match recovery inputs. DSP owners stop with
CDSP/SLPI `OFFLINE`, zero MCU references and the original 305 MHz GPU minimum.
Stock b1977 returns at 2026-10-22 07:42:24 UTC under a new boot UUID, with Wi-Fi
off and updater disabled. See this session's `stock-return-final.json`.
No firmware partition is flashed and the Quest remains untouched.

### Classified overdue updates and presentation deadlines

The new live probe brackets every `GetTimeSinceLastVsync` call with monotonic
timestamps and logs each failure with its reason, counter and a read-only kernel
timestamp. The existing aggregate and pose/dashboard exit criteria are retained.
Unavailable, nonfinite, negative, overdue and invalid-refresh cases have separate
counters. All 30 late failures below are overdue; none are negative, unavailable,
nonfinite or caused by a bad refresh property.

| Capture | Submitted presents/sec | Late overdue / 2,000 | Late driver busy reads |
| --- | ---: | ---: | ---: |
| Old-channel control | 102.53 | 9 | 3 |
| ABI-2 channel | 104.01 | 10 | 0 |
| ABI-2, attempted realtime permissions | 102.37 | 11 | 0 |

These rates count submissions in the marked instrumented window, not physical
FPS. All three kernel vblank streams remain approximately 120 Hz, with no trace
overruns. At each of these 30 faults the client counter is two kernel vblanks
behind. In the old-channel control, successive render-thread counter reads have
a median interval of 8.367 ms, a 95th percentile of 16.704 ms and maximum 19.609 ms.
The late faults coincide with a GPU semaphore wait followed by roughly another
refresh-period present wait before the next counter update. The paired timestamp
is correct for its reported sequence; it is the update that arrives late.

Filtered scheduler trace records the render thread's runnable delays as well as
its blocking waits. In that control's marked window, the measured runnable-delay
median is 8 microseconds, 95th percentile 268 microseconds and maximum 4.089 ms.
Between the last counter update and the nine fault queries, total measured
runnable delay ranges from zero to 0.803 ms. Thus CPU scheduling contributes in
some cases, while an exclusively CPU-scheduling diagnosis is unsupported. The
trace does not yet separate the GPU execution, GPU-queue delay and vendor KMS
deadline margins sufficiently to select a graphics-path fix.

The final comparison applies `LimitRTPRIO=80`, a 100 ms realtime CPU-time limit
and an SDL realtime-policy request only to the compositor unit. Its actual
`/proc` limits confirm those limits, but all sampled `RenderThread` tasks remain
policy 0, priority 0. The compositor logs `setschedparam` permission failures;
the comparison therefore does not test an effective realtime render thread.
The built kernel has `CONFIG_RT_GROUP_SCHED=y`; that observation alone does not
explain the permission failures. The later controls below test the actual
priority ceiling. No scheduling change is promoted. The runtime GPU
inventory also confirms 587 MHz is the highest advertised operating point, so
the completed tests already use the supported maximum, restored to 305 MHz at
cleanup. The native probe SHA-256 is
`99a46b5ae07f42d4f7df63e359ae2f60395f6eafba7f2207135b51ed8d49d849`.
The archives and stock-return receipt are listed in the preceding section.

### Matched refresh rates and effective scheduler controls

A further native session uses the same ABI-2 driver, paired Mesa counter fix,
Facet renderer and timing probe. Separate short-lived uid-1000 scheduler probes
accept `SCHED_RR` priority 80 with an RTPRIO ceiling of 80, reject priority 99
under that ceiling, and accept both with a ceiling of 99. Thus
`CONFIG_RT_GROUP_SCHED=y` does not categorically prevent realtime scheduling in
this environment. The retained probe receipts are `inspect-rt-ceiling-result.log`
and `inspect-rt-permission-result.log` in
`output/pico-steamvr-session-20261022-v7/`.

With `SDL_THREAD_PRIORITY_POLICY=rr`, `LimitRTPRIO=99` and
`RestrictRealtime=no` scoped to the compositor, its sampled render and signal
threads reach `SCHED_RR` priority 99. One render-thread sample in the repeated
120 Hz run instead records FIFO priority 40; the other 59 record RR 99.
The first priority-99 attempt with `LimitRTTIME=50ms:100ms` terminates with
`24/XCPU` about 1.15 seconds after compositor startup. The following successful
realtime captures use a 1/2-second soft/hard limit. Ordinary-scheduler controls
retain the existing realtime restriction.

Each complete capture consumes 2,249 camera sets, returns zero from camera,
SLAM and IMU, and records 2,000 valid late client poses. Every driver rejection
category is zero at the late observations. The table reports submissions during
marked windows of approximately 25 seconds within these 90-second sensor
captures; these are not physical FPS measurements. Hardware vblank matches the
selected 90 or 120 Hz, and all retained complete traces have zero overruns or
dropped trace events. GPU frequency is the supported 587 MHz during sampling;
thermal histories differ, so the rate differences do not isolate a scheduler
speedup.

| Configuration | Submitted presents/sec | Late overdue / 2,000 | Successful driver-read snapshot |
| --- | ---: | ---: | ---: |
| 120 Hz, ordinary, nice 0 | 96.53 | 14 | 52,991 |
| 120 Hz, RR 99 | 107.50 | 6 | 48,393 |
| 120 Hz, RR 99 repeat | 105.22 | 10 | 53,271 |
| 90 Hz, RR 99 | 89.59 | 0 | 49,054 |
| 90 Hz, ordinary, nice 0 | 89.52 | 0 | 49,064 |
| 90 Hz, ordinary repeat | 89.59 | 1 | 49,141 |
| 90 Hz, ordinary, nice -10 | 89.29 | 0 | 49,128 |

The ordinary-scheduler 90 Hz repeat's one late sample includes 7.258 ms of
measured runnable delay between counter updates. Its trace directly records the
render thread runnable for 7.169 ms while an equal-priority `vrwebhelper` and
other tasks run. This establishes a CPU contribution to that sample. In the
120 Hz captures, measured runnable delay at most affected queries is much
smaller; their GPU semaphore/presentation waits remain relevant. Neither a
CPU-only nor a GPU-only diagnosis explains the complete set of observations.

The explicit nice=-10 experiment changes the sampled render/signal thread nice
values as intended, without enabling realtime policy. It completes at 90 Hz,
but does not establish a consistent cadence or worst-case runnable-delay gain.
Its 120 Hz comparison fills the native 1.6 GiB `/run` filesystem before the late
observer and is rejected. It is not a compositor-fault or performance result.
The interrupted cleanup is completed explicitly, with VR units stopped and
MCU/GPU state checked. Four older trace files are moved to `/tmp` after exact
hash verification against retained host evidence, preserving their bytes while
freeing `/run`. The private capture preparation now requires at least 256 MiB
of `/run` headroom before camera, trace or compositor startup. No nice or
realtime setting is promoted to the maintained drop-in.

The 90 Hz tests change only `screen.frame_interval_ns` to `11111111` in a private
copy of the optical profile and set `steamvr.preferredRefreshRate=90`; optical
coefficients and geometry remain unchanged. They follow a working 120 Hz
handoff. First-handoff 90 Hz and clean lens output remain unverified, so the
maintained template retains 120 Hz. Occasional counter intervals still span
roughly two refresh periods even when the age probe samples no faults. These
captures establish a promising 90 Hz candidate, not loss-free presentation or
physical motion calibration.

The following archives, including the two rejected captures, are retained in
`output/pico-steamvr-session-20261022-v7/` with verified carriers and member
manifests. Generation 48 is installed but not run; its replacement installer
initially refuses the deliberately absent channel, then verifies the unused
binary, environment identity, absent ring files and stopped processes before
replacement. Neither event is counted as hardware acceptance.

| Archive | SHA-256 |
| --- | --- |
| `export-refresh120-control.tar.gz` | `29a8f457116677382e5067bd7dea7a7027cd200bc5eb161eee352ae7c1d0d111` |
| `export-realtime99-candidate.tar.gz` | `4f044744718309c30b0611e7ecdcb6366cc14d03415c4460ce20fb985b758cb6` |
| `export-realtime99-budget.tar.gz` | `a9f1071744c4c31d213adff776f6e38f8ea3cbebe348da2bc4ed30d685d8c2d0` |
| `export-refresh90-realtime.tar.gz` | `54eb5bd7326c7a5e3db9c8c920163bf260b8eebba252542e58b866dcb64da063` |
| `export-refresh120-realtime-repeat.tar.gz` | `0bd17f6fe787eebed82d7eac10d4faaff50ce31cc296ec2f7219f2ec110e42b7` |
| `export-refresh90-control.tar.gz` | `de9e1b527d2279695f192ffeb5574d2d4b71b7fe295d6302ed453a4b2d312569` |
| `export-refresh90-control-repeat.tar.gz` | `89fcf40d61febab7071044c84eafcc15092d3745124b2f794e060bb9f49403c6` |
| `export-refresh90-nice10.tar.gz` | `72e000cd50acea6c170f9e2ac0e82274bf9098fe5d7873b42a043a04ef45bddd` |
| `export-refresh120-nice10.tar.gz` | `cd7a84927ecdbeca82a238ed859fba28b6cb70c580561bfd23c46f198acafff1` |

Final full BOOT/DTBO readbacks match the recovery inputs. CDSP and SLPI are
`OFFLINE`, MCU references are zero and the original 305 MHz GPU minimum is
restored before reboot. Stock b1977 returns at 2026-10-22 08:43:28 UTC with a new
boot UUID, Wi-Fi off, updater disabled and `flash.locked=0`; see this session's
`stock-return-final.json`. No firmware partition is flashed. The Quest is
untouched. Physical motion, optical acceptance, controls and longer presentation
stress tests remain outstanding.

### Camera queue starvation under compositor load

The 2026-10-22 comparison traces camera request preparation, submission, release
and event service, together with scheduler events that include the camera PID.
Baseline RAM boot `58dd91e5-1bdd-44f0-9b94-9dcc8dae8b9e` shows a
`150240000 ns` interval between refills. Dispatching 112 transport events took
`144978546 ns`; 28 request releases accounted for `131263434 ns` of that wall
time, including any time blocked or descheduled. The old owner drained the
completion batch before replenishing requests. SOFs 1830–1832 then carried
request ID zero on all four cameras: the sensors continued producing frames
without assigned capture buffers. The API trace lost no records. Some scheduler
rings overwrote older entries, so they do not establish complete scheduler
accounting for the run.

This independently reproduces the missing-frame mechanism. The earlier fatal
120 ms camera gap lacked per-request tracing, so its individual missing frames
cannot be attributed retrospectively with the same precision. No feed age,
gap, skew, calibration, display-mode or scheduling limits were changed.

`pico_camera_transport_event_refill()` services free slots immediately after
each event, before another completion is dequeued. It retains the existing
eight-pair capacity, refreshes time around the refill work and propagates
failures. The host fixture drains a full completion batch while checking that
each newly free stereo pair is replenished immediately, that the capacity stays
bounded and that allocation/clock failures stop the generation. All 17 camera
tests passed under ASan/UBSan.

A first same-boot comparison delivered synchronized camera sets without later
request-zero SOFs, but the restarted vendor estimator published no confident
poses. Its failed acceptance and logs remain preserved. The full comparison
therefore used fresh RAM boot `8c51a77b-f086-4543-86f6-c7070e8497d9`, with
the fixed capture built from the current transport source and header.

| Check | Baseline | Immediate refill |
| --- | ---: | ---: |
| Session duration | 91.035 s | 91.006 s |
| SOFs observed | 4,499 | 4,499 |
| Request-zero SOFs after the first two startup SOFs | 3 | 0 |
| Captured frames per camera | 4,494 | 4,497 |
| Head-camera sets consumed | 2,248 | 2,249 |
| Published tracked head poses | 90,145 | 90,062 |
| Valid / invalid head queries in the controller probe | 3,000 / 0 | 3,000 / 0 |

Both runs used the configured 120 Hz Facet path and the same Steam workload.
The fixed run recorded 8,028 successful compositor presentation calls, selected
the 1280×800 Steam overlay and captured the sign-in UI in both distorted eye
views with both DMA planes active. API counts do not measure optical frame
rate; the scanout copy is not guaranteed to be one coherent frame. Physical
motion, lens acceptance and controller pointing remain separate gates. The left
controller was connected/readable for 21 of 30 observations, with zero input
update failures and invalid controller poses throughout. Vsync-age failures
remain: the selected-overlay probe recorded six overdue samples out of 500.

The fixed camera owner exited zero; its final diagnostic queue result `-EAGAIN`
denotes full capacity at the timed stop, with `failed=0`, rather than a capture
failure. The IMU producer joined without a ring failure. Controller RPC stops,
sensor shutdown, MCU reference release and restoration of the GPU minimum
passed. Full boot/DTBO readbacks matched before and after both RAM boots.
The existing SLPI shutdown-acknowledgment timeout and ten camera ION unmap
warnings remain; reported `OFFLINE` state and release ordering are the verified
shutdown boundary. Stock-return and mute receipts are retained with the evidence.

Baseline evidence: `output/pico-camera-gaps-20261022-v1/`; its 196-file export
has SHA-256 `46ac1d8798ebd23ffb0c9f1f530f55d0d81ac115c4d42e83d83960a861aacd13`.
The failed same-boot comparison's 160-file export has SHA-256
`6daa298d28f5f2e10340b56fba434039932a2e1ffd4daf32dfde3790d5e58d4c`.
Fresh fixed evidence: `output/pico-camera-gaps-20261022-v2/`; its 201-file export
has SHA-256 `78bfe02ff8222f84810583fb24400f1757cc9a25a5366b65a68ee849cfa8a7d4`.
Every archive/member hash was verified. `starvation.json` preserves the measured
baseline interval; `comparison.json` and its assertion-based analyzer check both
complete runs, trace continuity, source identity and the acceptance boundaries.

### Fresh 90 Hz handoff and controller tracker calibration

Two further RAM boots retain the current camera refill fix, paired Mesa counter,
Facet renderer and digital controller driver. The first selects 90 Hz directly
from the inherited display state. The first swapchain's atomic test returns
`-22`/`EINVAL`, `vkCreateSwapchainKHR` returns `VK_ERROR_INITIALIZATION_FAILED`,
and the compositor crashes. This run produces no usable timing comparison.
A same-boot control runs the maintained `pico-display-handoff`: it adopts the
advertised 120 Hz mode, observes five vblanks, disables the CRTC and releases its
resources. A following 90 Hz compositor with an OpenVR observer remains active
and records 173 successful atomic commits. An intermediate attempt without a
persistent observer exits normally before that observation and is not counted
as a passing display test. These controls establish a startup dependency on
this unit; they do not identify the vendor driver's internal rejection branch.

The second fresh boot runs the same handoff before any SteamVR session, then
selects a private optical-profile interval of 11,111,111 ns and preferred rate
90 Hz. It uses ordinary scheduling, no negative nice adjustment and the supported
587 MHz GPU floor during the bounded capture. The handoff measures an 8,332,057 ns
120 Hz period and releases its resources. The later hardware vblank samples
measure 89.9998 Hz. All camera, SLAM, IMU and controller-owner processes complete
successfully, including controller RPC close and release after SLPI reports
`OFFLINE`.

| Probe window | Head poses valid / invalid | Overdue vsync ages / samples |
| --- | ---: | ---: |
| First dashboard readiness | 500 / 0 | 5 / 500 |
| Selected dashboard readiness | 500 / 0 | 1 / 500 |
| Late dashboard | 2,000 / 0 | 0 / 2,000 |

The age limit remains two selected refresh periods: 22.222 ms at 90 Hz. None of
these failures are unavailable, nonfinite, negative or invalid-refresh values.
The late driver's read counters show zero rejections in every category.
There are 1,759 successful present API calls across the late sampled interval
of 19.783 seconds, or 88.91 calls/second; this is not measured physical FPS.
Startup ages are still faulty, and one zero-failure late window does not prove
sustained timing reliability. The 120 Hz template remains unchanged pending
physical 90 Hz acceptance.

The 90.96-second tracking session consumes 2,249 synchronized head-camera sets,
92,347 IMU pairs and publishes 90,064 confident head poses. Each camera completes
4,497 frames: 2,249 head and 2,248 hand, with zero controller-class frames.
All 690,527 camera profiling records are retained without profiler drops;
request-zero SOFs are limited to startup frames 1 and 2. This does not imply
complete scheduler ftrace retention. The controller coexistence probe receives
3,000 valid head queries and 21 connected left-controller states among 30
samples; controller pose validity remains zero. A raw scanout copy contains
the Steam sign-in UI in both distorted eye regions. Its horizontal copy bands
and non-coherent capture method do not establish clean optical output.

A separate isolated Bionic probe then loads the exact b1977 controller tracker
and accepts this unit's real cached calibration with the Neo3-specific 85-float
vector. Init, callback registration, left-kind reset and calibration each return
zero. The probe has no motion/image feed and hardware device access is blocked;
it does not produce a tracked controller. The
[controller calibration contract](pico-controller-protocol.md#cached-controller-tracking-calibration)
records the adapter difference from PicoFrame and the live collector tests.

Every archive and member hash is checked. Evidence directories are
`output/pico-vsync-controller-20261022-v1/` and `-v2/`:

| Archive | SHA-256 |
| --- | --- |
| v1 `export-startup.tar.gz` | `da487b67fe59fbeb26bd707ef59e6e58aa854ab827ef118a1818ec50b11e36f5` |
| v2 `export-render.tar.gz` | `2e7dffb9bb5c793a03266db9b90196e4b5412e43025c92da3e878dcfa851e2c4` |
| v2 `export-tracker.tar.gz` | `6913a316610fbe65ed0b71f8ccaa54a1b87430338969ce5ea610d2ef68cfa850` |

Full boot/DTBO readbacks match the recovery inputs after both RAM boots. Cleanup
restores the 305 MHz GPU floor, releases MCU references and confirms SLPI/CDSP
`OFFLINE`; the existing shutdown-acknowledgment/unmap warnings remain. ADSP is
never started and all PCM streams remain closed. At 2026-10-22 21:19:37 UTC,
stock b1977 returns with Wi-Fi off, updater disabled and `flash.locked=0`.
Both stock audio streams are set and read back at zero. Receipts are retained
beside the v2 archives. No firmware partitions are flashed and the Quest is
untouched. Startup timing, controller optical capture/pose integration, physical
motion scale and clean 90 Hz lens output remain acceptance gates.

## Controller motion inputs and late-vsync trace (2026-10-22 UTC)

Two further cold RAM boots retain controller-class camera frames with hand mode
explicitly off. Each run consumes 2,249 synchronized head-camera sets; every
camera delivers 2,248 controller frames and no hand frames. The ADSP remains
unstarted, PCM streams closed, and the GPU floor is restored after each run.
These captures log raw controller/camera data and are not unbiased performance
comparisons.

| Probe | First cold capture | Second cold capture |
| --- | ---: | ---: |
| First readiness overdue ages / 500 | 7 | 9 |
| Selected readiness overdue ages / 500 | 1 | 1 |
| Late overdue ages / 2,000 | 0 | 1 |
| Late head queries valid / invalid | 2,000 / 0 | 2,000 / 0 |

The [controller motion conversion](pico-tracking-protocol.md#controller-imu-records)
passes the 36-test host controller suite, a bit-exact nine-value comparison
against 18,144 retained stock-execution samples, and the boundary/unit harness
on the Pico ARM64 CPU in a device-denied Bionic jail. The first cold capture
provides 5,006 fresh controller samples bracketed by recorded head poses.
The second capture's raw snapshot instead contains ten retained samples aged
17.47–17.48 seconds: the receive stream had stopped earlier. All ten are rejected
by the maintained 100 ms freshness gate without changing the output. Neither
capture establishes optical controller poses or a SteamVR pointer. A warm
tracking restart also failed its confident-head readiness gate and was stopped;
it is not accepted as a working tracking session.

The second cold capture identifies a specific late-vsync sequence, with no
scheduler-trace overruns or dropped events on any of the eight CPUs:

- At monotonic 190.326077 s, the render thread finishes image acquisition.
- It sleeps from 190.326173 to 190.330078 s (`prev_state=S`), accounting for
  3.905 ms of the 4.420 ms before GPU submission begins.
- Hardware vblank 4298 occurs at 190.335898 s. No pageflip completion is
  delivered for that sequence. The render thread's semaphore wait returns at
  190.337459 s; the precise GPU execution interval is not captured.
- Presentation wait completes on vblank 4299. A concurrent client query at
  190.347029 s still observes counter 4297 and age 22.273071 ms. The render
  thread's next paired-counter query starts at 190.347082 s and returns 4299.

This verifies a missed presentation deadline and a pre-submit blocking interval.
It does not identify the blocking syscall or lock, prove a GPU scheduling fault,
or establish that a priority change fixes it. The next timing capture needs
render-thread ioctl/futex entry and exit around this interval. The age threshold
remains two refresh periods; no timing failure is suppressed or counted as fixed.

Evidence is retained in `output/pico-controller-tracking-20261022-v1/` and `-v2/`,
including exact binaries, source hashes, raw snapshots, extracted fault timelines
and manifests. Both export archives and every data member were hash-verified:

| Archive | Data members | SHA-256 |
| --- | ---: | --- |
| v1 `export-render.tar.gz` | 205 | `16785d79e840bfa1fa46f10e6a2410154aced84b5bdc57a088c98089812f80eb` |
| v2 `export-render.tar.gz` | 206 | `db337410e7147d326cb308aa9008beb31c63dd9543fb432e6f1970299c1c3608` |

The Pico4 reference remains PicoFrame's MIT `pico-ctrltrack.c` at revision
`3affbc11ecaae56c56b7bd3eb13344c73a7a03da`. It informs the private tracker replay
ABI/head-history work; the Neo3 uses its own measured clock relationship,
nine-value conversion and 85-float calibration vector. The synchronized optical
replay remains unverified because the recorded images and live controller motion
do not overlap in these captures.

Full boot/DTBO readbacks again match the recovery inputs. Final stock return is
verified at 2026-10-22 22:09:36 UTC with Wi-Fi off and updater disabled. The stock
AudioService reports effective music/system stream volume zero; the generic
stored volume settings still read 8 and are not treated as effective volume.

## Synchronized controller replay and startup CPU stalls (2026-10-22 UTC)

A further cold RAM boot retains the 90 Hz candidate, original physical driver,
paired Mesa counter, ordinary CPU scheduling and quiet audio. The 90.98-second
session consumes 2,249 head-camera sets and publishes 90,101 confident head poses.
It receives 14,710 left-controller input reports. All head queries in the two
500-sample readiness windows and the 2,000-sample late window are valid; overdue
vsync ages are respectively 7, 2 and 0. This does not resolve startup timing or
the previously observed occasional late fault.

The retained controller IMU and camera traces now overlap. Their calibrated
clock offset is -105,621,837,251 ns; the 50 four-camera controller sets have at
most 52 ns of inter-camera skew. After head startup, 6,235 controller IMU samples
are replayed with these images and real cached calibration through the exact
b1977 tracker on the Pico CPU. Head matching uses the maintained bounded history
and measured uncertainty. The isolated replay has no hardware/network access;
its simulated dispatch clock does not validate live arrival order.

All IMU/image calls return zero and the tracker produces 6,235 callbacks, of
which 497 carry confidence 1. Negative controls prevent interpreting those as
optical tracking:

| Image input | Confidence-1 callbacks | Position/orientation compared with real images |
| --- | ---: | --- |
| No image calls | 0 | Different |
| Fifty all-black image sets | 497 | Byte-identical throughout |
| Fifty recorded image sets | 497 | Reference |

The real/black result records differ only at diagnostic byte `0x54`, in 487
records. Its meaning is not established. The b1977 getter multiplies internal
position by 1,000 before writing the raw result; raw controller coordinates
cannot be passed to OpenVR as metres. Controller state 0 also differs from the
head result's accepted state 1. Confidence alone is insufficient to enable a
tracked SteamVR pointer.

A subsequent getter inspection identifies the source of those 497 public
confidence-1 values: internal `0xc4` is copied to diagnostic `0x52` as zero,
while a separate two-zero-byte branch overwrites public confidence with 1.
The [controller result contract](pico-controller-protocol.md#controller-result-confidence)
records the exact binary and instruction range. This explains why the public
flag cannot serve as the optical acceptance gate; it does not establish why
the recorded images fail to correct position or orientation.

A file-open trace identifies a missing controller-specific persist cache in the
isolated runtime. A second control copies the verified stock cache into writable
RAM, restoring its original contents before each trial. Original persist is
mounted read-only with journal replay disabled. The cache and headset serial
then open successfully, but both black and real inputs still produce identical
poses and only one confidence-1 callback each. The cache is not a demonstrated
fix. The earlier run that reused the writable cache between trials is retained
as a confounded diagnostic, not the comparison result. Factory camera YAMLs
open successfully; the optional controller configuration YAML is absent from
the stock system too. Optical correction and grip/aim calibration remain open.

The head-history replay also exposes valid state-1/confidence-1 head results
with opaque status `0x200`. An added nonzero-status rejection incorrectly clears
their history. The corrected implementation preserves that field and passes the
recorded replay, ASan/UBSan host tests and an offline Bionic unit test on the Pico.

Raw syscall entry/exit and scheduler events are captured with zero overruns,
commit overruns or dropped events on all eight CPUs. The 57.935 ms
acquire-to-submit interval at monotonic 266.677802–266.735737 s contains 57.870 ms
on CPU and 0.065 ms runnable off CPU for render thread 1926. Two other startup
intervals measure 28.458 ms entirely on CPU and 15.379 ms with 13.173 ms on CPU.
They do not contain a long captured blocking syscall. There are 39 unmatched
syscall boundary events, so this is not a claim of complete syscall pairing.

A same-boot realtime/monotonic clock correlation places Facet's shader-pipeline
creation logs inside all three intervals, including two pipeline creations in
the 57.935 ms interval. This supports pipeline creation as the startup-stall
cause; CPU starvation does not explain that interval. Mesa's 189-file, 3,434,828
byte shader cache resides in the temporary overlay and is lost on a RAM reboot.
A separate restored-cache comparison is required before adopting cache policy
or claiming a timing fix. The earlier late blocking interval remains a separate
unresolved observation.

Evidence: `output/pico-controller-integration-20261023-v1/`. Archive and member
hashes are verified:

| Archive | Data members | SHA-256 |
| --- | ---: | --- |
| `export-render.tar.gz` | 211 | `9c9f8bb29006412b1aa9e7eab94f74740733e52ba8c1452ec052f350d67498a6` |
| `export-replay.tar.gz` | 6 | `39e56d265fa58aec5a690e04a25a88e4473f0af89d66bfca1e7ec981a32c9820` |
| `export-controls.tar.gz` | 12 | `888b400037448f2aad2db9ce5432f631b946a56e1d7d6a2121555296e5482e97` |
| `export-cachefresh.tar.gz` | 21 | `1079cde6e097253a741c6ab2f5e960a4a57646f28f29f1734c6f8ae682af5627` |
| `export-shaders.tar.gz` | 189 | `71aa71cf37f0c4298c4fc62845fd55420323936385e4abb51048af4660aa4259` |

Hardware owners are quiesced before the recorded replays. SLPI/CDSP report
`OFFLINE`, MCU references return to zero, the GPU floor returns to 305 MHz and
ADSP remains unstarted with PCM streams closed. Final full boot/DTBO hashes match
the recovery inputs. Stock b1977 returns at 22:54:13 UTC with Wi-Fi off and updater
disabled; effective music/system volumes read zero. No partition is flashed,
and the Quest remains untouched. The updated optional SteamVR pose adapter is
built/tested separately on this CPU; these captures do not enable it or establish
a working optical controller pointer.

### Restored Mesa cache comparison

A second cold RAM boot restores the 189 hash-verified Mesa cache files before
starting the same 90 Hz candidate. Initialization has created only `index` and
`marker`; these two files are preserved in a separate RAM directory before the
restore. The physical driver, Mesa library, optical profile, Steam workload,
ordinary scheduling, 587 MHz test floor and capture instrumentation are retained.
The compositor additionally requests cache statistics, but no cache hit/miss
statistics are emitted in its retained log; cache reuse is not established by
a reported hit count.

The same-boot clock correlations place Facet's pipeline-creation messages in
these acquire-to-submit intervals. They measure the containing interval rather
than the individual Vulkan pipeline call:

| Pipeline group | Cold cache | Restored cache |
| --- | ---: | ---: |
| Initial distortion grid | 39.197 ms | 2.060 ms |
| Curved embedded overlay | 28.458 ms | 1.096 ms |
| Flat/reflected embedded overlay | 57.935 ms | 1.728 ms |
| Curved overlay | 15.379 ms | 1.728 ms |

The largest acquire-to-submit interval anywhere in the restored run is still
14.444 ms. Its first readiness attempt sees the selected 1280×800 Steam overlay,
500 valid head poses and zero overdue vsync ages. The late probe adds 2,000 valid
head poses and zero overdue ages. `dashboard-observer.log` duplicates the
successful readiness log and is not an additional 500-query window. The cold
run's two readiness attempts contain 7 and 2 overdue samples. Both late probes
have zero; this comparison does not reproduce or fix the earlier occasional
late blocking fault. The unchanged age bound is two refresh periods.

A later coverage check cannot classify the remaining 14.444 ms interval at
monotonic 232.975341107–232.989785430 s. The trace contains hardware vblanks 76
and 77 nearby, but no scheduler or syscall events for render TID 1897 before
or during that interval. Its first recorded scheduler event is 239.699624 s;
its first syscall event is 239.745808 s. An on-CPU, lock-wait or GPU attribution
for this residual interval would therefore exceed the captured evidence.
The coverage extraction is retained in
`output/pico-controller-motion-20261023-v1/warm-stall-coverage.json`.

The next capture should enable render-process scheduler/syscall coverage before
its first frame. Linux 4.19 documents `set_event_pid` with `event-fork` to inherit
the PID selection into children; this offers a way to prepare the launching
parent before its compositor threads exist. Verify the option and inheritance
on the selected vendor kernel before using the result. Keep the existing
unfiltered DRM-event capture separate so interrupt-side vblanks remain visible.
This is a capture plan, not a compositor fix. See the
[Linux 4.19 ftrace documentation](https://www.kernel.org/doc/html/v4.19/trace/ftrace.html).

The 90.93-second tracking session consumes 2,249 head-camera sets and publishes
90,064 confident head poses. The native scanout copy contains Steam's sign-in
panel in both distorted eye views and both DMA planes remain active. The copy
spans multiple scanouts, so its visible copy boundary and software image do not
establish coherent optical output. Physical 90 Hz acceptance, motion calibration
and optical controller correction remain unverified in this run.

These results support retaining the Mesa cache across sessions and RAM boots,
rather than adopting a CPU-priority workaround for the measured startup stalls.
The maintained compositor drop-in now provisions a private system-service cache
and a 512 MiB bound. Its exact configuration passes `systemd-analyze verify` on
the Pico. A native service running as UID 1000 verifies the cache path, 0700 mode,
ownership, environment and write/read/remove cycle. This configuration test does
not install persistent Linux storage; the performance comparison restores the
cache explicitly into RAM.

Evidence: `output/pico-shader-cache-20261023-v1/`. The 212-file export archive has
SHA-256 `003d0426ee66196bde3fe98a9d90337d822f9e38078d6dccd83f271330f40d53`;
every archive/member hash is verified. `cache-comparison.json` retains all matched
intervals and probe results. Hardware owners stop cleanly, MCU references reach
zero, the GPU floor returns to 305 MHz and ADSP/PCM remain quiet. Full boot/DTBO
readbacks match the recovery inputs. Offline stock b1977 returns at
2026-10-22 23:05:05 UTC, with updater disabled. No partition is flashed and the
Quest remains untouched.

## Live Bionic controller inputs and pre-exec capture (2026-10-23 UTC)

The native Linux boot `dc9cddc0-5cc9-4d56-bc7a-95724328e5e5` runs systemd
as PID 1 without zygote, SurfaceFlinger or system_server. SteamVR owns display
presentation; the Bionic process supplies the vendor tracking ABI. This does
not place Steam inside a running Android system.

The first combined run delivers all 23,352 received left-controller IMU samples
to the stock controller estimator, with raw head poses bracketing each timestamp.
It also submits 64 synchronized four-camera controller sets while head tracking
and SteamVR run. Maximum observed input age is 20.778 ms, head-bracket wait
13.969 ms and estimator-call elapsed time 10.547 ms. These maxima include
scheduling time; they are not measurements of estimator CPU execution alone.
Native radio report counters subsequently stop advancing and the motion producer
terminates with `-ETIMEDOUT`. Bionic consumed every published motion sample before
that stop. This establishes an upstream receive interruption, not its cause or
that the controller was asleep. Optical controller poses remain unpublished.

A second, 241.08-second run consumes 5,999 head-camera sets and publishes 243,651
confident head poses. All 9,806 controller IMU samples published before the
receive interruption reach Bionic. Native input reports later resume, rising
from 9,703 to 40,891, but the stopped motion channel does not rearm. This separates
radio reception from estimator-feed recovery; buttons can work while motion
delivery stays stopped. The owner confirms Steam's sign-in UI through the
lenses and that the left Home button hides it. The owner also reports the image
upside down and apparent reversed head movement: this is physical display
presence, **not calibrated or usable VR acceptance**. The controller model and
pointer remain absent. Audio stays off. Both runs' successful readiness and late
probes contain 500 and 2,000 valid head samples with zero overdue vsync ages at
the unchanged two-refresh-period bound. This does not resolve the intermittent
Facet timing fault.

[`pico-compositor-trace.py`](../tools/pico-compositor-trace.py) now selects its own
PID and enables `event-fork` in an idle dedicated trace instance before dropping
to UID 1000 and executing the compositor. The second run verifies that all nine
observed compositor TIDs are inherited. A pre-exec marker at monotonic
1089.719039 s precedes their startup events. The bounded CPU capture ends at
1120.824908 s, retaining 322,830 events with zero overruns or dropped events on
all eight CPUs. The separate DRM trace remains unfiltered by PID. Raw syscall
filters select ARM64 ioctl, futex, sleep and poll calls; stopping CPU capture
when the dashboard becomes ready preserves startup coverage during the longer
lens test. The earlier unfiltered CPU capture overflowed three buffers and must
not be used to classify an early stall.

The caller owns trace creation, explicit `tracing_on=0` initialization, buffer
size, syscall filters, collection and removal. Two host fixture tests verify
PID inheritance setup and refusal of an occupied or unsupported instance. The
second run reused an old Vulkan API trace filename; that file contains the
previous compositor's TIDs, so it cannot correlate this CPU trace with acquire
or submit calls. Use a new API trace path for every run.

Evidence in `output/pico-live-controller-timing-20261023-v2/` is exported with
per-file SHA-256 verification:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-render.tar.gz` | 233 | `76327dcc8195e2281e444c39fff3e7d02787d979be415badfce5d483be6d2f7a` |
| `export-long.tar.gz` | 281 | `32f793f178a4226a2f285bb9d1b6836b725f5a429b894cd10f5de9d2a415c5db` |

Before the longer run, two diagnostic setup errors are preserved: an existing
exclusive-create camera profiler file prevented startup, and an IMU duration
above the helper's 300-second cap was rejected. Archiving the old profiler and
using a four-minute capture with a five-minute IMU bound corrects those setup
errors. They do not establish a camera or compositor hardware regression.

### Correct the inverse panel mapping

The upside-down report exposes a coordinate-contract error: the shared optical
profile's column-major rotation maps view vertices onto the panel, while
`ComputeDistortion` needs the inverse map from panel coordinates into the view.
The previous implementation applied the forward matrix in both directions.
For the Neo3 quarter-turn, that differs from the inverse by 180 degrees. The
adapter now uses the transpose without changing the profile, head transforms,
projection, chromatic model or panel timing. Corner fixtures distinguish the
forward and inverse maps. Host ASan/UBSan tests and a native ARM64 UBSan run pass
52,272 UV checks across four rotations and two chromatic models.

A RAM-only configuration trial first reverses the quarter-turn with the old
driver. The rebuilt driver then restores the original profile and produces the
same corrected mapping in code. Its SHA-256 is
`046076c4381a3e5c14dc66498db5a6acc0fc924a5c13c2ecf8df5fb16efd70c7`.
Software scanout and SteamVR readiness pass; the owner's later grey-view report
**does not optically validate upright output or head-motion direction**.

That last run exhausts the `/run` tmpfs: its pose recording ends with 176 bytes
of a partial 368-byte record, after 139,987 complete records. The last complete
record remains confident. The diagnostic callback treats a failed recording
write as failure, and the feed ends with `rc=-1`, `bad_results=2`. Subsequently,
receipt writes fail with `ENOSPC` and interrupt the owner's cleanup. This is a
concrete diagnostic failure that stops tracking before the intended four-minute
capture ends; the logs alone cannot prove the precise optical cause of grey.
The unchanged v5 USB host also reaches its documented 1,900-second console
limit, leaving final output unread until reconnect. Future runs need sufficient
per-mount recording space, a live USB-console lease and cleanup independent of
receipt-writing success before another physical acceptance attempt.

After reconnecting to the same boot UUID, seven obsolete RAM copies are removed
only after their sizes and hashes match the already verified host export.
Recovery completes the worker's RPC stop, waits for SLPI/CDSP `OFFLINE`, verifies
worker exit and its DMA-release marker, releases MCU references to zero,
restores the GPU floor to 305 MHz and verifies closed PCM streams. Full boot and
DTBO readback hashes still match the stock recovery inputs. No partition is
written. The final export preserves 271 files in `export-fixed.tar.gz`, SHA-256
`ec66d72f6ebc3b08f4ebe7bbebaeefbe02e855e62fd6b324bdee820bc17aedb5`.

The final late probe has one overdue sample out of 2,000 (22.410 ms against the
unchanged 22.222 ms bound); readiness has zero out of 500. CPU capture ends
before that late sample and the prolonged DRM trace overruns, so this run still
cannot attribute that fault. Neither the display-mapping fix nor the earlier
zero-fault samples establish a compositor timing fix.

Stock return is subsequently verified as boot UUID
`ea575b8d-4f33-456b-8adf-0505dc2c85b5`, with
`ro.pico.ota.version=5.8.4.0-202310092224-RELEASE-user-neo3-b1977`.
The bootloader remains unlocked, Wi-Fi reads zero, the updater package remains
disabled, no network route is reported, and the verified audio helper reads back
zero effective music and system volumes. The Quest is untouched.

## Controller motion restart with shared head tracking (2026-10-23 UTC)

The motion producer can now explicitly restart after a receive timeout or an
ordinary owner-requested stop, without restarting RPC, SLPI or head tracking.
It leaves the old channel permanently stopped, seeds its wire watermark from
the current synchronized DMA snapshots without publishing that backlog, and
initializes a distinct mapping with an increasing motion generation. Protocol
and clock errors remain terminal. The Bionic consumer separately binds the
head/world generation, so resetting a controller need not reset the head frame.
The owner retires the old consumer and resets/recalibrates the estimator before
attaching the new consumer. Restart acknowledgment alone is not sample readiness.

Forty-eight host controller tests pass, including sanitizer coverage of fresh
mapping recovery, rejection of old generations/backlog/conflicts, continued head
history, and parent request/acknowledgment/timeout handling. The native ARM64
worker builds and runs its UBSan unit checks. A separate Bionic UBSan consumer
harness passes on the Pico CPU; its SHA-256 is
`032bce21b1a1c2a19dfc06300deb8a18bd075f18cc5337aafd8e9a732cd7988c`.
The clean run's worker manifest matches the maintained source hashes, with
binary SHA-256
`f341cd106ee447a390ffcc4f0685b8f4c1a160ac3cc5d47aee9abddfe6647800`.

Three bounded native trials distinguish channel initialization from live
recovery. In the first, the owner requests a new generation after controller
reports have already stopped. Reset/rebind succeeds, but the new channel gets
zero samples and times out; this is not successful motion recovery. The second
requests the restart while reports are arriving: generation 104 delivers 1,524
samples, then generation 105 delivers 12,264 through the same Bionic estimator
process and raw head history. Its camera producer outlives the consumer's
diagnostic deadline and exits unsuccessfully with an undrained eight-set ring.
The source rejects a full ring; shortening acquisition fixes the subsequent
capture. That capture-tail error is preserved rather than counted as a passing run.

The clean rerun ends camera acquisition before the consumer's ceiling, allowing
the pending sets to drain. It records:

- 2,499 head-camera sets and 102,661 head callbacks, with 100,303 poses published
  and no output-adapter failure;
- 1,524 controller IMU samples delivered before the explicit stop and all 12,268
  samples delivered after reset/rebind to motion generation 105;
- unchanged head/world generation 104, a successful 1.292 ms estimator reset,
  23.112 ms maximum post-reset input age, 7.741 ms maximum head-bracket wait and
  1.835 ms maximum elapsed estimator-call time;
- 64 four-camera controller sets submitted, with optical pose publication still
  disabled;
- an active Steam VR overlay and 2,500 valid head samples from the readiness and
  late probes. Those probes still report two overdue vsync-age samples.

The controller motion stream later times out again; digital reports subsequently
resume and reach 32,768 while motion stays stopped. The new explicit recovery
path is verified, but automatic owner-driven recovery on renewed reports is not
implemented by this diagnostic owner. The worker's final exit remains
unsuccessful because that last timeout is unrecovered. This does not establish
optical controller tracking, a SteamVR pointer, calibrated movement scale,
upright lens output or correct physical head-motion direction.

The diagnostic head and controller result files now stop recording at 32,768
and 8,192 records respectively, below 20 MiB combined. Head publication continues
after that recording budget is exhausted. Per-mount free-space checks run before
sensor power; receipt writes in cleanup are best effort. CPU/DRM traces stream
into bounded files on `/tmp`. Both trace streams finish without reported
overruns or dropped events, and the console stays within its lease.

Evidence is under `output/pico-motion-recovery-20261023-v1/`. Every exported file
is checked against its size and SHA-256 manifest:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-recovery.tar.gz` | 219 | `e2c69caf9229921d189f19f1c3dab00a37f0c09f0067b6d1b6b6819b240bb29d` |
| `export-early.tar.gz` | 257 | `caa66a1ea95b0851e02d3d07feffa6857ccdf4f7d3f1de2165cf95e06cf551c2` |
| `export-clean.tar.gz` | 245 | `3cbc79c746f51c00470aa83298a46d30354b371c9272c0994b42c8f993a18f64` |

Cleanup verifies RPC stop, SLPI/CDSP offline, DMA release, MCU references zero,
the original GPU floor and closed PCM streams. Full boot/DTBO readbacks still
match the recovery inputs. Stock return is verified as boot UUID
`7806d93a-5079-437e-85d1-6f0f8f6b2062`, b1977, unlocked, Wi-Fi off and updater
disabled. Effective music/system volume is restored to zero. No firmware
partition is written and the Quest is untouched.

### Complete traces of the remaining vsync-age faults

The recovery trials replace the earlier startup-only CPU capture with bounded,
continuously drained CPU and DRM streams on `/tmp`. Each run has its own Vulkan
API trace path. In `export-early`, both overdue samples fall inside complete
pre-exec-to-cleanup trace coverage; all eight CPU buffers report zero overruns
and dropped events. The current compositor PID/TIDs match the API trace.

| Probe | Reported age | Render-thread wait observed around the fault |
| --- | ---: | --- |
| Readiness, sample 176 | 24.865 ms | `vkWaitForPresentKHR` takes 15.101 ms and returns `VK_TIMEOUT`; its futex wait takes 15.055 ms and returns `-ETIMEDOUT` |
| Late, sample 160 | 22.408 ms | A 10.752 ms DRM syncobj timeline wait is followed by a successful 9.798 ms `vkWaitForPresentKHR` call |

For the first fault, the compositor's paired counter query returns sequence
5,359 at monotonic 574.167 s. Kernel vblanks 5,360 and 5,361 occur at 574.176 s
and 574.187 s while the render thread is waiting. The probe reads the old
sequence at 574.190 s; the next compositor query gets 5,361 at 574.192 s.
The second fault similarly reads 5,842 after kernel vblanks 5,843 and 5,844;
the compositor queries 5,844 immediately afterward. The probe calls themselves
take about one microsecond. These samples establish aged compositor timing
data while the scanout clock continues, rather than a stopped vblank source.

The render thread is sleeping in the recorded waits during those intervals.
Its observed wake-to-run delays are tens to hundreds of microseconds, not the
multi-millisecond intervals in question. This does not rule out other scheduler
effects, but it does not support treating CPU starvation as the demonstrated
cause of these two faults. The timeline wait uses `/dev/dri/renderD128`; the
recorded ioctl matches `DRM_IOCTL_SYNCOBJ_TIMELINE_WAIT` in the build header.
Its elapsed duration is not a measurement of GPU execution time alone.

The retained source path recorded by the deployed Mesa build is
`/work/9cbe28c05f473600/mesa-26.1.8/src/vulkan/wsi/wsi_common_display.c`.
Its SHA-256 is
`fa0fb6b9c5961000796892e5c97af0e02b994bfc7f8842e1cf3bbe08f2fd6fb9`.
The present-wait path first waits for its presentation semaphore, then waits for
the requested present ID; the page-flip callback advances that ID and broadcasts
completion. The traces do not yet identify why present 2,309 misses that
completion deadline. The next targeted measurement needs present-ID/flip
completion correlation and the timeline dependency, before changing wait
semantics, scheduling or the two-frame acceptance bound.

The clean repeat still has two overdue samples out of 2,500, so neither motion
recovery nor complete trace coverage constitutes a timing fix. Raw evidence and
the correlated windows are in `export-early/`, `export-clean/` and
`timing-fault-analysis.json` under `output/pico-motion-recovery-20261023-v1/`.


## Automatic controller motion recovery (2026-10-23 UTC)

The maintained receiver now inspects fresh, calibrated IMU captures after a
receive timeout and notifies its serialized owner. `recover_motion` requests an
increasing motion generation, waits for acknowledgment and fresh samples, then
returns its endpoint. The owner publishes that endpoint atomically; the Bionic
consumer resets its controller estimator before rebinding. It does not restart
RPC, release shared DSP buffers or change the head/world generation. Silence,
digital-only activity, stale notifications and protocol failures cannot revive
an old motion channel. Host sanitizer/fixture checks pass all 53 controller
suite tests, including pending acknowledgments and rejected recovery requests.

A native Linux trial on Pico boot UUID
`5bb98e78-5a57-4f2c-ba03-5eb456889b5a` pauses the receive worker for 200 ms with
`SIGSTOP`, then always sends `SIGCONT`. The real DSP/radio and head/camera
processes continue running. This deliberately produces a receive timeout; it
is not a simulated IMU stream or a physical controller sleep/wake test.

- Motion generation 104 stops after one sample. Fresh post-stop IMU data
  triggers automatic generation 105; the endpoint is published 49.948 ms after
  the host resumes reception. The Bionic estimator resets successfully in
  1.248 ms, then delivers all 13,665 new-generation IMU samples. Its maximum
  input age is 21.651 ms, maximum head-bracket wait 13.820 ms and maximum
  elapsed estimator call 7.103 ms. Head/world generation remains 104.
- The combined run drains all 4,499 head-camera sets and processes 184,604
  head callbacks, publishing 182,215 poses with no rejected output result.
  Controller work runs on a separate thread in the retained private Bionic
  frontend, preventing its estimator calls from blocking the head-feed loop.
  This run alone does not prove the cause of an earlier rejected head result.
- Steam's 1280 by 800 VR overlay is active and visible to OpenVR. The readiness
  and late probes accept 3,500 head poses. The late 3,000-query window still has
  one overdue vsync-age sample; it is not a complete compositor timing fix.
- Radio reports later cease again. Motion correctly times out and remains
  stopped without a fresh resumption notification. The worker exits with code
  1 for that unrecovered timeout; all three RPC stop results are zero, SLPI
  reaches offline before DMA release, and MCU references return to zero.

The first serial-feed trial rejects a head result before dashboard readiness.
Its failed result was beyond the bounded raw recording window, so its exact
cause remains unclassified. The separate-thread trial has no rejected head
result, but its late probe incorrectly requests 60 seconds from a binary that
accepts at most 30; the harness stops the run. Both failed trials remain in the
evidence, separately from the corrected automatic-recovery trial above.

Evidence is under `output/pico-auto-recovery-20261023-v1/`. The host validates
each archive and every member against the exported size/SHA-256 manifest:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-auto.tar.gz` | 211 | `7023a9da2b15a24e21bf1141a8ea99b93f3a73bb9a334ec36994b9eeb3a2109b` |
| `export-threaded.tar.gz` | 223 | `6cf2cadd7a74e2b7de15ae8c07f74963e761d51e01b86ed58e4aeaa9b26d144c` |
| `export-controlled.tar.gz` | 269 | `b480fa8b39dbdf8195b4119cde8e58194f356f52a9354f95ce10eb2685c08bd1` |

The controlled receive pause verifies automatic owner/reset/rebind integration
on hardware. The final baseline below additionally verifies unforced report
resumption. Optical controller poses and pointing, physical head-motion scale,
upright lens output and movement direction remain separate acceptance gates. Audio is not opened during these runs. No firmware
partition is written.


### Present-ID correlation

Turnip patch 0016 records present IDs at queue, atomic commit, page flip,
presentation-semaphore completion and final wait completion. The corrected
controlled-recovery trial captures 106,890 events. Its CPU trace reports zero
overruns/dropped events on all eight CPUs.

The sole late-window age fault is sample 1,263: OpenVR reports counter 9,917,
aged 22.356 ms, at monotonic 2,005.300374 s. Present 3,802 was queued at
2,005.283132 s; its nonblocking atomic commit returned successfully at
2,005.283214 s. The kernel advances through 9,918 at 2,005.289039 s without a
flip completion, then delivers completion at 9,919 at 2,005.300177 s. Mesa's
page-flip callback runs at 2,005.300384 s and wakes the requested present ID;
the wait returns success at 2,005.300415 s. The next compositor counter query
returns 9,919 at 2,005.300441 s.

The presentation-semaphore phase takes only 17 microseconds. The final wait
blocks 10.659 ms for the actual page flip; it is not waiting on the wrong
present ID or failing to wake after completion in this sample. A preceding
render-thread DRM timeline wait returns at 2,005.289544 s, after the missed
boundary. This is consistent with a late rendering dependency, but those
traces alone do not identify GPU execution time or the exact KMS fence that
held that commit. They do establish delayed cached timing while scanout
continues. The two-period age bound and synchronization semantics are unchanged.

Raw evidence is in `export-controlled/`; the correlated event window is in
`present-completion-analysis.json`, both under
`output/pico-auto-recovery-20261023-v1/`. Clock notifications and reducing the
rendering workload require independent controls; repairing a reported age
would not by itself repair a missed scanout boundary.


### Timing controls and unforced controller resumption

The independent clock-notification candidate is not adopted. Its corrected
read-only sysfs variant completes a three-minute combined capture, but still
has 12 overdue ages in 3,000 late queries versus one in the traced baseline.
Median runtime-reported compositor GPU time is 6.138 versus 6.149 ms; traced
successful present submission rates are 87.59 versus 89.31 per second. These
are diagnostic workload measurements, not physical display FPS. Earlier
primary-node variants fail startup: opening that node can acquire DRM master,
and this kernel restricts dropping master to root. Their sources/binaries stay
private. No clock experiment is included in the maintained driver.

Enabling `renderSystemLayerInDistortPass` on Facet starts the compositor, but
camera acquisition stops during dashboard startup. At monotonic 3,098.668 s,
the kernel reports request-manager workqueue congestion and rejects request
1,703 because both ISPs are still in `APPLIED`. Capture ends with `failed=1`;
head output records no rejected result. The probe consequently receives 471
invalid head samples. This control is rejected; it does not establish that
the layer option itself caused the congestion, and the option remains off.

The final baseline restores the original driver and layer setting, disables
the Vulkan API trace layer, WSI presentation tracing and CPU/DRM trace events,
and verifies zero-byte CPU/DRM streams. It completes all 4,499 camera sets and
184,601 head callbacks, publishes 182,214 poses without output failure, and
accepts all 4,000 readiness/late head-pose samples. Its late 3,000-query window
still contains one overdue age; readiness contains three out of 1,000. Heavy
tracing is therefore not required to reproduce the fault. The two-period bound
is unchanged. The remaining KMS rendering/fence deadline needs further work;
no complete timing fix is claimed by these controls.

This final baseline also verifies the requested automatic recovery during
unforced report resumption. After the initial controlled pause, generation 105
delivers all 13,580 samples before timing out. The receiver then observes an
89.203-second gap between its last received IMU sample and the new resumption
cue. No further host pause or manual restart is issued. Fresh data triggers
generation 106: the endpoint is published 38.698 ms after the receiver's fresh
snapshot, the Bionic estimator resets successfully in 1.214 ms, and all 17,460
new samples are delivered. Maximum input age is 31.035 ms; maximum elapsed
estimator call is 12.304 ms. Head/world generation remains 104 and its stream
continues throughout. This verifies recovery from renewed reports, without
establishing why radio traffic stopped or what caused it to resume. Final
silence stops motion again; the receiver exits 1 for that unrecovered timeout,
with all three RPC stop results zero and DSP/DMA ownership released in order.

The following additional manifest-verified archives are under
`output/pico-auto-recovery-20261023-v1/`:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-clock.tar.gz` | 208 | `64d8d95e57ed8e84d5d8e321d5738440f0c98dbd4a312f7ab789ea84d603be5e` |
| `export-clock2.tar.gz` | 199 | `51b5bfa1322309ba59bbfddc5b5332c79d559f30b7ebbf2a9bd95364721fcb95` |
| `export-clock3.tar.gz` | 275 | `2d78b00cb4ad4f5fe7177fb218eaccbd0b532e7a7005df0a37ef0a10328b9fa0` |
| `export-fused.tar.gz` | 229 | `bd494d842904378a9df9dd23f88a48fa62aef32341d3feb7b597d140c4f7b3b7` |
| `export-untraced.tar.gz` | 282 | `4b8c0a66480a588e7f83afe0bc3d36f6ce22089426ec110894ff49db3e838d7d` |

Full BOOT/DTBO readbacks match the pre-test stock hashes. Both sensor owners
are stopped, SLPI/CDSP are offline, MCU references are zero and the original
GPU floor is restored before return. The v5 console lease ends after this
quiescence; the already-armed bounded return timer boots stock normally.
ADB verifies boot UUID `e0dd8ec2-e096-4ef7-92e1-153d60829055`, b1977, unlocked,
Wi-Fi off, no network route and updater disabled. The hash-verified quiet
helper confirms effective music/system volumes zero. No firmware partition
is written and the Quest is untouched. Receipts are `final-readback-result.log`,
`quiesce-result.log`, `stock-return-final.json` and `stock-quiet-final.log`.


### KGSL fence callback dispatch (2026-10-23 UTC)

A targeted GPU/DMA-fence trace identifies a missed rendering dependency on
native boot `e33448a3-911f-44b1-bc05-ec1af509c487`. For present 6,041, KMS starts
waiting on compositor GPU context 1, timestamp 6,057, DMA-fence context 27 at
monotonic 256.726219 s. The kernel records that job retired at 256.732630 s,
but its fence signals at 256.736197 s. Vblank 6,207 occurs between them at
256.735639 s; the flip completes on 6,208. This is a 3.567 ms delay after the
software retirement trace, not a measurement of GPU execution time. The head
stream is still valid at the associated overdue-age query.

The retained Neo3 kernel source explains the next measurement. In
`drivers/gpu/msm/kgsl_events.c`, `signal_event` queues `_kgsl_event_worker` on
`kgsl-events`; that worker promotes its scheduling priority only after entering
its callback handler. `drivers/gpu/msm/kgsl.c` creates the queue with
`WQ_UNBOUND | WQ_MEM_RECLAIM | WQ_SYSFS`, without `WQ_HIGHPRI`. Native readback
reports `nice=0`, `cpumask=ff`, `max_active=256`, `numa=1`. Existing Neo3 patches
do not modify these paths. The source is ByteDance commit
`9cacc1c1356dd32a048f4cb13bc84af402bd3326`; the pinned archive SHA-256 is
`88fb81480eb02f1e958a57a818e6b3fc699e5156a223ea53a5cc1b037abe7063`.

A subsequent control adds workqueue queue/start tracepoints filtered to that
one handler. It matches all 36,817 queue/start/callback records, with no
unmatched records or trace overruns/drops on any of the eight CPUs. Both
late-window faults have a delayed worker dispatch after retirement:

| GPU timestamp / DMA context | Retirement | Callback queued | Worker starts | Missed vblank |
| --- | ---: | ---: | ---: | ---: |
| 4,480 / 56 | 1242.858979 s | 1242.859027 s | 1242.864069 s | 13,633 at 1242.862385 s |
| 4,717 / 56 | 1245.536628 s | 1245.536644 s | 1245.540427 s | 13,874 at 1245.540140 s |

KMS waits on those exact compositor fences. Their notifications spend 5.042
and 3.783 ms queued before execution. Across 24,989 compositor sync callbacks,
queue-to-start p99 is 1.763 ms and maximum 6.655 ms; worker-entry-to-callback
p99 is 0.023 ms. These observations establish callback dispatch as a cause of
the two missed boundaries, without attributing every timing fault to it.
The control accepts all 9,500 readiness/late head queries, with two overdue
ages in the 9,000 late queries. The Steam overlay is visible at 1280 by 800.

The first trace uses a 90-second camera capture, shorter than the requested
three timing windows; only its live-head interval is used above. The first
longer repeat builds the camera entry point without controller publishing and
exits before compositor startup. The corrected control completes all timing
windows, then its inherited 150-second camera alarm terminates acquisition;
its final feed timeout is therefore not a passing full-capture result. These
harness failures are retained separately. The priority repeat extends both the
capture deadline and its watchdog, and changes only `kgsl-events` nice to
-20 during the measured workload, with restoration afterward.

Raw traces, source-file hashes, analysis and per-file manifest receipts are
under `output/pico-gpu-deadline-20261023-v1/`. The initial archive is
`export-gpu.tar.gz`, 255 verified files, SHA-256
`b2c46b87e58e31a997cf664633b5048ac5cd9484f1546010d30a45d0a245a77a`;
the filtered control is `export-wq-control2.tar.gz`, 276 verified files,
SHA-256 `1a347cc6538941fd82ab9d16b00fa0f62790b602f5d18323f1e13a3993217138`.


The priority repeat completes all 4,499 camera sets, processes 184,569 head
callbacks and publishes 182,214 poses without rejected output or feed failure.
All 9,500 readiness/late head queries are valid and all vsync-age queries pass
the unchanged two-period bound. Its filtered trace matches all 44,807
queue/start/callback records and reports zero drops/overruns on all eight CPUs.
For the comparable three late windows (about 93 seconds including probe
startup), the compositor's sync-callback dispatch measurements are:

| Measurement | Original queue nice 0 | Queue nice -20 |
| --- | ---: | ---: |
| Matched callbacks | 16,712 | 16,774 |
| Queue-to-start p99 | 1.770 ms | 0.411 ms |
| Queue-to-start p99.9 | 5.024 ms | 0.807 ms |
| Maximum queue-to-start | 6.655 ms | 2.651 ms |
| Queue-to-start over 2 ms | 158 | 4 |
| Overdue ages / late queries | 2 / 9,000 | 0 / 9,000 |

This supports the queue-policy change for the measured workload; it does not
establish that every presentation deadline is solved. The retained kernel's
`kernel/workqueue.c` maps `WQ_HIGHPRI` to nice -20 for unbound pools, and its
sysfs nice attribute applies the same worker-pool selection mechanism. The
maintained helper applies this policy without requiring a kernel rebuild.
The run leaves `cpumask=ff`, `max_active=256` and `numa=1` intact, then reads
back the original nice 0. All three controller RPC stop results are zero,
SLPI is offline before DMA release and MCU references return to zero. The
controller delivers all 24,541 motion samples before later radio silence;
no fresh resumption cue occurs in this run, so it does not add a recovery
transition proof beyond the earlier verified resumption trial.

`export-wq-priority.tar.gz` contains 289 manifest-verified files, SHA-256
`4dc4842d42b71d536dd343e890309ebc66a970de0a38d39054a4aa8da2d480cb`.
`tools/pico-gpu-events.py` adds device/boot checks, exclusive ownership and
exception/termination restoration. Its five host fixtures cover failed
workloads, overlapping owners, previous nondefault priority, rejected device
identity and a symlink lock. Native sysfs tests additionally verify restoration
after both the CLI timeout and SIGTERM; see `install-policy-result.log`.


The final three-minute repeat uses the committed helper's context around the
entire workload and shutdown, with Vulkan API/WSI tracing and all kernel trace
events disabled. Both retained kernel streams are zero bytes, there are no
WSI trace records and no Vulkan API trace file is produced. It accepts all
9,500 head and vsync-age queries with zero overdue ages, consumes all 4,499
camera sets and publishes 182,215 head poses without rejected output or feed
failure. All 13,719 controller motion samples are delivered before later
radio silence; no resumption cue occurs. RPC stops succeed and SLPI goes
offline before controller DMA release. The helper restores nice 0 and the
unchanged CPU mask, concurrency and NUMA values after cleanup. These two
passing captures total 19,000 age checks; sustained timing and physical VR
acceptance still require longer and visually observed sessions.

The untraced archive `export-wq-untraced2.tar.gz` contains 273 verified files,
SHA-256 `8b4ed251c01a8023bd6bf7ede19ab2f2096cce355dc2d56520e0884b1fc6368e`.
A preceding no-tracing harness attempt writes a disabled trace marker and
returns `EBADF` before capture/VR startup; its cleanup indexes an empty stream
list. The maintained outer policy context restores nice 0 despite this error,
verified before the corrected repeat. This failed attempt is not counted in
the passing captures. Host script/result receipts remain in the evidence.


Final full BOOT/DTBO readbacks match the retained stock hashes. Before reboot,
CDSP/SLPI are offline, MCU references are zero, the GPU floor is 305 MHz and
kgsl-events nice is 0. Explicit stock return verifies boot UUID
`0f633602-4f67-45e8-b0c7-dc565059928a`, b1977, unlocked, updater disabled, Wi-Fi off and
empty IPv4/IPv6 routing tables. The pinned quiet helper reads back effective
music/system volumes zero. Native audio was not opened during the tests; no
firmware partition was written and the Quest was untouched. Receipts are
`final-readback-result.log`, `quiesce-result.log`, `stock-return-final.json`,
`stock-network-final.json` and `stock-quiet-final.log` in the evidence directory.

### Synchronized controller image observation

Evidence: `output/pico-controller-pointing-20261023-v1/`, native boot
`49f00487-798c-409c-a479-8781deb2cb02`. Earlier raw result capture filled its
8,192-record budget before the controller image feed began at 25 seconds. The
new diagnostic samples every eighth result and captures camera pixels only
after the controller image ring is ready, covering the actual image calls.
This changes observation coverage, not the tracker or its pose acceptance.

The first combined run consumes all 4,499 head camera sets and publishes
182,214 head poses with zero rejected results or feed failures. Of 10,000
vsync-age checks, seven are overdue in the first readiness window; the second
readiness window and all three later windows pass. Thus the earlier passing
warm captures do not establish fault-free cold startup.

The observer decodes 13,750 controller callbacks. Its retained 1,718 raw pairs
span 27.124 seconds and include 299 observations after the first of 64
four-camera image submissions. All those later left results have state,
public confidence and diagnostic bytes `0x52`/`0x54` equal to zero. Image calls
return zero, but there is still no demonstrated optical correction or tracked
SteamVR pointer. Later radio silence does not establish that the controller
was asleep. The 256 synchronized camera images are almost black: mean scene
intensity is approximately 3.8/255 and none contains a pixel above 200. This
does not distinguish controller visibility, LED operation or exposure timing.

The native decoder fixtures and replay of all 6,235 earlier negative-control
records pass with UBSan traps enabled; host ASan/UBSan checks pass as well.
`observed-consumer-build.json` records the exact current observer build;
older build receipts included in the export describe the preceding carrier.
All controller RPC stops succeed, SLPI is offline before DMA release, MCU
references return to zero, and GPU minimum/queue nice return to 305 MHz/0.
Audio is not opened.

`export-pointing.tar.gz` contains 267 manifest-verified files, SHA-256
`82f9cdac535371230dbe59a65fb702cb00de72ce526cbdd0f1d48c2d880fe469`.

### Deployed view-coordinate check

In the same RAM boot, the new read-only `pico-steamvr-live --view-frames`
mode samples raw/standing HMD matrices and the raw-to-standing transform without
changing the dashboard or tracking origin. With Steam's 1280×800 overlay active,
all 1,000 head queries are valid. All ten origin matrices are identity. Comparing
20 raw/standing matrices with the nearest timestamped calibrated-channel
observations gives a maximum element difference of `4.39e-6` and translation
difference of `1.79e-6` metres. The observations are at most 2.57 ms apart and
the headset is stationary; this checks the deployed conversion, not measured
movement or physical calibration. No extra standing-origin reversal is present
in this session.

The head-pose regression now covers both yaw/pitch directions and lateral
translation through the existing stock-SDK basis conversion. A world-fixed
point moves opposite head yaw/pitch in view space. Host ASan/UBSan and the
Pico's Bionic CPU harness with UBSan traps pass. The existing inverse panel-map
correction remains deployed; these checks do not establish upright lens output,
correct physical motion direction or a usable controller pointer.

This combined run consumes all 4,499 head camera sets, publishes 182,215 head
poses with no bad results/feed failure, and passes 2,000 dashboard vsync-age
queries. The controller's 64 image calls return zero, but all 304 retained
post-image result observations still have four zero state/confidence/diagnostic
bytes. No controller pose is published. All RPC stops succeed and cleanup
restores SLPI/MCU ownership and GPU policy. The archive `export-view.tar.gz`
contains 274 manifest-verified files, SHA-256
`40b92aeb852fb2ae95ec6efdded3d4c7e997c9c32c42ddea8708ff098b887366`.
Exact probe source/binary hashes are retained in `install-view-result.log` and
the archive. `view-frame-comparison.json` records the timestamp-only matching
rule and numerical comparison.

Full BOOT/DTBO readbacks still match the stock backups. After stopping CDSP and
SLPI, verifying MCU references zero, closed audio devices and restored GPU
minimum/nice, explicit reboot returns to b1977 stock boot
`fa4a5887-1d19-4c88-baf3-7da96f25a39f`. Stock completes startup with music/system
volume zero, Wi-Fi off, empty IPv4/IPv6 main routing tables, updater disabled
and bootloader unlocked. Other routing tables contain only loopback/dummy
interface routes. Receipts are `final-readback-result.log`, `quiesce-result.log`,
`stock-return-final.json`, `stock-network-final.json` and `stock-quiet-final.log`
in the same evidence directory. No firmware partition was written; the Quest
was untouched.

### Physical Steam UI and head-tracking check

Evidence: `output/pico-controller-input-contract-20261023-v1/`, native RAM boot
`376f77a7-8b27-470e-819c-ae2967c53d44`. The owner reports visible Steam sign-in UI
and working 6DoF through the lenses. Home on the left controller hides/shows the
window, but no controller model or pointer is visible, other buttons do not
produce visible actions, and sign-in text is barely readable. This establishes
visible rendering and a qualitative head-motion check; measured position scale,
controller pointing and acceptable sharpness remain open.

The viewing run passes its 500-query readiness window and all 15,000 late
vsync-age queries, with no invalid head query in those windows. Earlier captures
in the same boot still have startup-age failures, so this does not establish a
general timing fix. The Steam overlay is 1280×800. The compositor log reports
1832×1920 recommended per eye, automatic target 1552×1628 and system-layer
textures 1544×1616. Those are concrete resolution limits to compare in the next
sharpness test, not proof of the complete optical cause. The deployed driver
uses fixed per-eye poses and lens calibration; it does not consume eye tracking.

Unlike preceding captures, the retained controller results include 273 samples
with `(state, public confidence, diagnostic 0x52) == (1, 1, 1)` between 26.061
and 32.907 seconds after consumer startup. Their positions vary and quaternion
norms are finite and approximately one. Some result timestamps are up to
43.325 ms ahead of their observation time. These are promising acquisition
samples, not a verified optical-validity rule or a controller calibration. The
diagnostic explicitly keeps `optical_pose_publication=0`, including for these
samples, so no controller pose reaches SteamVR. Publication still needs the
coordinate/prediction-time contract, image-content and tracking-loss controls,
and a safe continuous-image ownership contract. A preceding 512-set image trial
without these samples rules out the earlier 64-set limit as the sole cause.

The viewing harness returns zero, but its separate controller worker exits 1
after reporting successful RPC stops; the camera log also records terminal
result `-11` despite process status zero. This is not a fully clean lifecycle
pass. SLPI is nevertheless verified offline before worker DMA release, MCU
references return to zero, PCM devices remain closed and GPU minimum/nice are
restored. The later explicit quiesce verifies both SLPI and CDSP offline.

The archives and all member manifests were verified after transfer:

| Archive in `native/` | Files | SHA-256 |
| --- | ---: | --- |
| `export-pointing.tar.gz` | 267 | `27cb5e21aa179935867b31388712ffdda5a2cfcc164b85f06c8e7335d34b6315` |
| `export-extended.tar.gz` | 243 | `234f87755e1122e14c27c44f7666438fbcc5753fbf00f5b9e266303bce34edc7` |
| `export-live-preview.tar.gz` | 291 | `8b87553b78b8c0de32d58fef96cb610f45dd614ae03aa4a9b87bbfd2b0725338` |

BOOT/DTBO readbacks still match the preserved stock backups. The explicit
return reaches b1977 stock boot `eb86aae5-d9d1-4ecf-918f-91c350fd63b8`, with
music/system volume zero, Wi-Fi off, updater disabled and no routable network
interface. The version-2 stock observer then verifies the QTimer timestamp
domain while the headset is awake; its fresh results have zero left tracking
flags. This is not a positive stock optical reference for the placed controller.
The hash manifest and README identify the authoritative receipts; copied older
templates and receipts are not results from this boot. No firmware partition
was written and the Quest was untouched.

## UI resolution, render models and camera startup (2026-10-23)

Evidence: `output/pico-ui-quality-20261023-v1/`, with separately verified export
archives and member manifests. All comparisons used one native RAM boot, the
same driver/optics, 90 Hz, Facet, the retained paired-counter Vulkan path,
587 MHz GPU minimum and prioritized KGSL event workqueue. GPU minimum and
workqueue priority were restored after each run. Audio stayed closed. The
headset was stationary; no new lens, motion-scale or controller-pointing
acceptance was requested from the absent owner.

The driver and probe rebuilt on native ARM64 Linux. Both attributed WebXR Neo3
render models loaded through SteamVR's render-model and texture APIs: 3488
triangles per hand and 512×512 textures. SteamVR adds two automatic components
to the four supplied components, so the probe checks required names rather than
requiring exactly four. Model loading does not establish tracked controller
visibility or calibrated aim/grip transforms.

### Resolution and measured pacing

These are overlapping compositor histories from three late 30-second windows
per successful run, deduplicated by frame index; each spans about 94 seconds
with no missing indices. GPU times are compositor render times. Reported drops
and frame intervals are software observations, not measured panel cadence or
photon latency. These single runs do not establish a statistically repeatable
performance difference.

| Configuration | Steam source | Internal layer per eye | GPU p99, ms | Reported drops | Interval p99, ms |
| --- | --- | --- | ---: | ---: | ---: |
| Automatic scale | 1280×800 | 1544×1616 | 6.61 | 21 | 12.47 |
| Manual application scale | 1280×800 | 1544×1616 | 6.62 | 15 | 12.42 |
| Native internal layer | 1280×800 | 1832×1920 | 7.68 | 39 | 12.63 |
| Larger Steam surface | 1600×1000 | 1832×1920 | 7.94 | 111 | 20.31 |

Application supersampling alone did not change the internal system layer. The
runtime's explicit `systemLayerWidth`/`systemLayerHeight` controls changed its
allocation to 1832×1920. Both native-layer runs stayed below the 11.11 ms GPU
frame budget in these late windows, but missed-frame intervals remained. The
larger source showed worse pacing, and one of its 9000 late vsync-age queries
was overdue. Do not call this timing fault resolved or claim sharper lens
output from the software capture. The optional `steamvr-ui-90hz.vrsettings`
profile packages the tested layer dimensions; neither the default profile nor
the Steam source size is changed automatically.

A separate 1920×1200-source attempt aborted gamescope: its pinned upload buffer
is `1920 * 1080 * 4` bytes (`rendervulkan.hpp:849,872`), smaller than that source.
The compositor and cached overlay survived, and the original diagnostic runner
still exited zero. That run is rejected as live-Steam acceptance. A subsequent
short run was also rejected: its assertion read the previous run's appended
gamescope log. After rotating that log and requiring the overlay service to
remain active after readiness and every late window, the final 1600×1000 run
completed with a live visible overlay. All failed attempts are retained.

### Controller and lifecycle boundaries

The manual-application-scale comparison delivered zero controller image sets.
Its raw camera trace starts with IDs 0 and 3 from frame 1228, then ID 1 from
1230: enabling the consumer partway through a set triggered the old collector's
strict incomplete-set failure. The maintained frame-sequence helper now permits
incomplete startup sets to be discarded before synchronization. Afterward,
partial current sets remain pending, while duplicates, regressions and advancing
past an incomplete set are errors. Native unit tests cover all
24 arrival orders and four entry positions. The rebuilt capture completed its
final full run with 64 retained controller image sets, controller-image error
zero, 4499 head-camera sets consumed and 182213 head poses published without a
rejected head result. This remains a bounded retained-pixel diagnostic.

The controller IMU stream later timed out (`-110`); controller pose publication
remained disabled. The final observer decoded 13787 controller results, only
one with public confidence 1. This does not provide a usable tracked pointer.
Continuous vendor image ownership/completion, origin conversion, prediction
timestamps and tracker-loss handling remain open. The stock conversion's third
pose argument was verified to come from `getPoseOffset`, rather than a live
head pose; see the controller protocol record.

The camera's terminal `result=-11` with `failed=0`, accepted stops and process
exit zero is its nonfatal queue-empty diagnostic at the capture deadline. The
controller worker's exit 1 includes the separately recorded IMU timeout even
when all three RPC-stop results are zero; it must not be described as a failed
DSP release solely from that exit code. Before stock return, both DSP owners
were stopped, MCU references were zero, audio PCMs were closed, and full boot
and DTBO readbacks matched the retained stock hashes.

Stock return was verified in a new b1977 boot, with Wi-Fi off, the updater
disabled, no external-interface routes, and music/system volume zero. Receipts
are `native/stock-return-final.json` and `native/stock-network-final.json` in the
evidence directory. No firmware partition was written and the Quest was untouched.

## Native Steam VR UI (2026-10-24)

Evidence: `output/pico-modern-ui-20261024-v7/`. The final RAM boot used the
maintained UI launcher, opt-in 90 Hz profile, seatd, and the gamescope Vulkan
forwarding patch. Earlier attempts are retained separately; v6 established
valid main/bar textures but returned to stock before its full capture could be
exported. The v7 archive is 5,696,557 bytes, SHA-256
`3a38e2ad3aa428829e6e382633d62354c8d30e5fae84a23a640d87e47215ee16`;
all 108 manifest members were checked after receipt. The deployed gamescope
hash matches `diagnostic_artifacts.ui_forwarding_sha256` in its source profile.

All three late probes report the selected main panel active and visible, with
a valid 1920×1080 texture. The separate native toolbar has a valid, visible
1800×120 texture. The 1600×1000 desktop fallback is hidden, and the old custom
`reframed.pico.steam` overlay is absent. A missing selected overlay returns 9
with frame history enabled. A synchronized DMA-buffer readback of the shared
1920×3664 scanout contains the stereoscopic sign-in panel and toolbar. The
stored-pixel preview does not establish a coherent single frame, through-lens
clarity or physical interaction with settings. It retains visible seams, whose
optical significance was not checked in this unattended run.

The stationary native head pipeline consumed 4,499 synchronized head-camera
sets and published 182,217 confident head poses, with no rejected vendor head
results. Three late 30-second OpenVR probes received 9,000 valid head samples,
zero invalid samples and zero overdue vsync-age queries. These checks establish
the live stream alongside the modern UI; they are not a fresh physical
motion-scale or controller-pointing acceptance.

Deduplicating the overlapping late histories yields 8,300 consecutive frame
indices spanning 94.50 seconds. Compositor GPU p99 is 7.89 ms, but reported
drops total 186 and frame-interval p99 is 20.74 ms, above the 11.11 ms 90 Hz
budget. Frame pacing remains open. This single offline sign-in scene does not
establish a performance improvement over the earlier flat UI or gaming load.
The forwarding fix adds no CPU readback; the existing software-browser upload
path remains enabled.

Before stock return, MCU references reached zero, SLPI and CDSP were offline,
and audio PCMs were closed. Full BOOT/DTBO hashes still matched the retained
stock backups. `native/stock-return-v2.json` verifies a new b1977 boot with
Wi-Fi off, no external routes, updater disabled and music/system volume zero;
the final Bluetooth query also reports OFF. No firmware partition was written
and the Quest was untouched. Signed-in library operation, controller optical
acquisition and a new lens clarity check remain unverified.

### Optical reference, readback stability and startup guard

The owner reports that stock Pico Android has clean display and correct head
and controller tracking. The native Linux physical clarity/IPD, jitter and
controller failures remain software acceptance gaps, tracked in the
[VR acceptance checklist](pico-vr-acceptance.md).

A fresh b1977 optical-getter read matches the deployed radial and chromatic
coefficients in both eyes exactly. Comparing the current SteamVR callback with
retained stock mesh/GLES results over 17,136 synthetic-geometry points checks
102,816 RGB coordinate components; the maximum visible coordinate difference
is 0.00051 pixels at a 1920-pixel reference dimension. This checks the equations,
not the user's active eye origins, full stock rendering policy or lens clarity.
The current profile supplies static eye poses approximately 63.4 mm apart; no
live eye-tracking/IPD update is implemented in this driver.

The first new native attempt aborts gamescope before its main UI becomes ready:
explicit non-Steam windows override forced composition and reach a subview
path that asserts with modifiers disabled. Patch `0003` preserves composition
when those DMA imports are unavailable. The next attempt installs that rebuild,
but a stale expected binary hash in the diagnostic harness correctly rejects it
before SteamVR starts. Both attempts are retained as failures, with verified
stock returns; neither is capture or UI acceptance.

The corrected third attempt is in
`output/pico-optics-validation-20261024-v3/`. Its 9,889,486-byte export has SHA-256
`d2bc5ec29c42865195c23d3f807b4452e1fc3bcbe6c72d58eeee852e5b13e3a0`;
all 112 manifest members were verified. The deployed renderer matches
`diagnostic_artifacts.nonsteam_composition_sha256` in `profiles/gamescope.json`.

The paired unpaused scanout contains interior black bands at rows 1285–1311 and
3155–3174. With a guarded compositor pause, two readbacks of all 28,139,520 bytes
match SHA-256
`2a5f1aa6748314118033c438babda0488b7d6b82ffe92403390c313684b37881`.
The same two active planes and framebuffer remain selected, and neither
interior band is present. Existing viewport-edge
masking remains. The compositor resumes and continues producing frames.
`stable_readback_verified` is true while `coherent_single_frame_verified`
remains false; matching bytes are not a GPU completion-fence measurement.
The published tool additionally requires a waiting timer with zero last-trigger
time: an elapsed timer can still be active. That stricter expiry guard has a
unit regression test; this Pico boot used the earlier active-state check, not
that final guard revision. Its exact capture source is retained in the payload.

Both early pixel captures contain only the skybox, despite active main-panel
and visible toolbar API textures. This run therefore establishes stable readback
and startup/API acceptance, not renewed visible Steam UI acceptance. The
optics-aware host preview removes the configured colour pre-correction from
the earlier v7 sign-in capture without changing device pixels; it does not close
the owner's through-lens clarity or IPD failures.

After a five-second exclusion following the capture pause, three late windows
deliver 9,000 valid head samples, zero invalid head samples and one overdue
vsync-age query. The 8,309 consecutive sampled frame indices span 94.40 seconds,
with compositor GPU p99 7.49 ms, 168 reported drops and interval p99 20.45 ms.
Jitter/frame pacing remains open; these stationary observations do not prove
comfortable head-motion prediction.

Before stock return, MCU references reach zero and SLPI/CDSP are offline. Full
BOOT/DTBO readbacks match the backups. `native/stock-return-v2.json` verifies a
new b1977 boot, Wi-Fi off, no external routes, updater disabled and audio streams
1/3 at zero. No firmware partition was flashed and the Quest was untouched.

### UI visibility, stereo measurements and tracking-loss rejection

`output/pico-ui-geometry-20261024-v2/` completes the same bounded native stack
with 32 successful setup recipes. The early capture precedes main/bar overlay
visibility. Both later stable captures contain the modern sign-in panel and
native toolbar in both eyes, rather than only successful texture API results.
The main texture is 1920x1080, toolbar 1800x120 and main alpha 1. This establishes
stored UI content in that run, not the cause of the preceding skybox-only run.

The extended live probe records eye-to-head matrices, raw projection tangents,
render dimensions and overlay transforms/errors. Runtime IPD is 63.4 mm, with
identity eye rotations and X origins at -/+31.7 mm. Each recommended render is
1832x1920; X projection tangents are -/+1.09130847 and Y -/+1.14372945. These
match the deployed profile. They do not independently validate stock's active
SDK geometry or the owner's through-lens IPD/clarity report.
The recorded transform samples overlay coordinate `(0.5, 0.5)` in the overlay's
own coordinate space. The diagnostic originally labels it `centre_head`, but
that coordinate is not established to be the panel centre. The final source
labels it `point_head` and includes the input coordinate explicitly; that
output-label correction follows the hardware build recorded below.

The final capture timer guard is exercised on hardware: its resume timer is
waiting and untriggered, and two full-buffer reads agree before automatic
resume. Stable and late raw SHA-256 values are respectively
`76215d250886e9c9ba4fe6df8bf111893a9cc4a2e8c2e2deb83c788db089397e` and
`4cf1b8bd89b1fb65013172cd5d7e4baee6820b511570092d7951faa9a2b11890`.
Coherent-frame and physical optical acceptance remain false.

The host preview accepts the retained schema-2 and schema-3 optical profiles
and linear 8-bit or 10-bit XR/AR/XB/AB scanout. It derives its per-eye aspect
from each profile's `display` dimensions rather than assuming a landscape
eye image. This is a resampled inverse of the configured pre-correction;
neither the preview nor a stable buffer read validates physical optics.

Three stationary late windows record 9,000 valid head queries, zero invalid
and zero overdue vsync-age queries. Frame histories retain 193 reported drops
in 8,274 consecutive sampled indices, GPU p99 7.885 ms and interval p99
21.345 ms at a 90 Hz target. This is not clean frame-pacing or head-motion
acceptance. The feed completes 4,499 camera sets. A preceding failed v1 run
instead reaches its unchanged camera freshness limit at 250.547 ms while the
latest IMU is 1.692 ms old; its full scheduling/producer cause remains open.

The checker previously returned success after any 100 valid head queries,
even when later queries were invalid. It now rejects any invalid head query
in the measured window. In the separate v3 hardware regression, three normal
30-second windows pass the corrected binary with 9,000 valid queries and zero
invalid. Across the feed's scheduled shutdown, the previous binary returns
zero with 1,017 valid and 1,983 invalid queries; the corrected binary returns
status 8 with 1,026 valid and 1,974 invalid. Neither tracking thresholds nor
runtime pose policy was relaxed. The ARM64 checker SHA-256 is
`8d6d7b83ee10215418e4d651a33aa6585d87241cd6963dc5303f42132e4a05ab`.

That v3 negative test is **not** a complete successful stack run: the harness
keeps the IMU producer alive while waiting for the post-shutdown queries, fills
its unconsumed ring and fails the final producer assertion. The checker
regression is separately established by its recorded counters/exit statuses.
The original payload manifest and a supplemental hash record retain the
relocation of the previous checker outside the root-only staging directory.

The v2 export is 15,572,954 bytes, SHA-256
`2c6df05baf4c603cbbeed4404dd17bdf5cbf0b2a0fcbe6ea7856b27c119c3223`,
with all 122 selected members verified. The v3 export is 15,589,072 bytes,
SHA-256 `b18fc95c786917d47768e986ac371f6943f22eea903b802cceb1aff85514eea5`,
with all 126 members verified. Both full BOOT/DTBO readbacks match the retained
backups, DSP owners stop with zero MCU references, and their
`native/stock-return-v2.json` receipts verify offline, muted stock return.
No firmware partition was flashed; Quest untouched. See the
[acceptance record](pico-vr-acceptance.md) for remaining physical and controller
requirements.

### Forwarded overlay layout correction

`output/pico-overlay-layout-20261024-v1/` isolates one renderer change against
the passing geometry-v2 payload. Forwarded surface images remained in Vulkan
`GENERAL`, while OpenVR requires `TRANSFER_SRC_OPTIMAL`. The fourth gamescope
patch copies into reusable local output images, waits for the copy and lets the
existing output barrier transition to the required layout. Source sampling and
external ownership remain unchanged. The exact deployed ARM64 renderer hash is
`facef831ab4c99c750ac208b6e1c06f21fb083fdd2455116a67a091b51fd9ac9`.

All 32 setup recipes and the bounded feed complete. Gamescope logs the new
presentation-copy path. The stable scanout and its host reconstruction contain
the modern sign-in panel and native toolbar in both eyes. Stable and late full
buffer hashes are respectively
`2ce9f87d06d383813eca4bdb6733dc96d3a73e0bad1e9ac18e3a72f22b57e312` and
`267928766584b1fd5484e24cd2c366c02d710d5dcec89f8b220bbc332547b8e7`;
both have two matching readbacks. This exercises the corrected transport but
does not establish that the layout bug caused every earlier visibility failure.

The three late stationary windows contain 9,000 valid head queries, zero invalid
queries and zero overdue vsync ages. They cover 8,293 consecutive frame indices
with 180 reported drops, interval p99 21.186 ms and compositor GPU p99 7.923 ms
at a 90 Hz target. The earlier five-second observer reports nine overdue vsync
queries. The prior run's 193 drops and 7.885 ms GPU p99 are observational
comparisons, not a controlled performance result. Frame pacing and head-motion
latency remain open.

The feed consumes all 4,499 camera sets and publishes 182,215 confident head
outputs. Controller output still has zero public confident optical poses;
ownership or radio reports do not establish tracked pointing. No optical, IPD,
physical-motion or controller acceptance is claimed.

`native/export-receipt.json` verifies the 15,599,739-byte archive, SHA-256
`56b6b0d8af3020b791caae17007ee4c7dfb40c9efd8a9a87860db7ad0de5f058`,
and all 122 selected members. `native/provenance.json` binds the replacement
binary to the outer source/build receipts; the copied payload's older gamescope
metadata describes the baseline. MCU references reach zero, SLPI/CDSP stop,
BOOT/DTBO match their full backup hashes and offline, muted b1977 return is
verified. The exact staged test archive is removed after hash verification.
No firmware partition was flashed; Quest untouched.

### Controller coexistence and rejected CFS promotion (2026-10-24)

`output/pico-optical-acquisition-20261024-v4/` retains a diagnostic CPU trace
starting before compositor exec, with inherited PID selection for its threads.
The 256 MiB collector budget stops it after about 69.95 seconds; the retained
error and truncated scope are part of the evidence. It is not a full-session
trace or a performance baseline. In its final available 20 seconds, render-thread
runnable delay reaches 6.088 ms, and the main thread reaches 11.487 ms. GPU
syncobj waits also occur; observing a blocking wait does not establish a fence
implementation defect.

A separate untraced same-session ABBA comparison uses nice 0, -10, -10, 0 for
20-second probe windows after two-second settles. Only ordinary compositor
threads are promoted; existing positive background nice values remain intact.
Original priorities are restored and verified, with realtime policy still blocked.

| Ordinary-thread nice | Sampled frames | Reported drops | Drops / 1,000 sampled frames |
| --- | ---: | ---: | ---: |
| 0 | 3,485 | 73 | 20.95 |
| -10 | 3,475 | 90 | 25.90 |

The four frame-interval p99 values remain 20.68–21.39 ms at the 90 Hz target;
GPU p99 remains 7.79–7.97 ms. Each window has 2,000 valid head queries and zero
overdue vsync-age queries. This stationary comparison supplies no evidence of
benefit from promotion, so no persistent priority setting is adopted. It is
neither a general regression claim nor motion/photon acceptance.

The feed consumes all 4,499 camera sets and publishes 182,254 confident head
outputs. Controller optical confidence stays zero, and the radio worker exits
unsuccessfully after its motion reports stop. Controller pointing remains open.
The 146-member export and full BOOT/DTBO readbacks verify; shutdown and muted,
offline stock return pass. Evidence is `output/pico-frame-pacing-20261024-v8/`;
the earlier v6/v7 rejected harnesses are recorded separately.

The trace launcher accepts repeatable `--syscall ID` filters for a dedicated
idle instance. It applies and reads back the filter on both entry and exit
events before enabling tracing; scheduling events retain the inherited compositor
PID selection without the syscall-ID filter. Existing syscall or scheduler
filters are refused. This permits focused GPU ioctl diagnostics without
retaining the unrelated high-volume syscalls that exhausted the previous capture.
IDs must match the target kernel ABI; see the kernel's
[event filtering documentation](https://docs.kernel.org/trace/events.html#event-filtering).

The next capture, `output/pico-frame-pacing-20261025-v1/`, verifies this filter
on the headset. It retains 159,465,364 bytes spanning the full 171.781-second
compositor interval, with zero collector errors or per-CPU lost events. During
one recorded timeline wait, the render thread sleeps for 7.224 ms, wakes, then
remains runnable for another 9.464 ms before running. The 16.724 ms ioctl returns
success. This identifies scheduler delay within an observed wait; it does not
prove a fence defect or the cause of every dropped frame. OpenVR frame history
and kernel trace use different epochs, so they are not aligned frame by frame.

The bounded native feed completes 4,499 camera sets and 182,256 confident head
outputs with no bad result; controller public optical confidence remains zero.
All 136 export members and full BOOT/DTBO readbacks verify, and muted offline
stock return passes. Staging-manifest and continuation-script errors occurred
before setup and are retained with their verified in-RAM repairs. No priority,
affinity or rendering policy is adopted from this instrumented result.
### GPU-thread affinity and camera failure isolation (2026-10-25)

The untraced ABBA comparison in `output/pico-frame-affinity-20261025-v3/`
identifies the compositor's GPU render thread from 111 observations of its
DRM render-node timeline wait. Its original CPU affinity is 4–6. Only that thread
is allowed onto CPU 7 in the middle two 20-second windows, after two-second
settles; other observed affinities and nice values remain unchanged. The exact
original affinity is restored and verified.

The original-mask windows report 88 drops in 3,460 sampled frames; the candidate
reports 75 in 3,473. Interval p99 remains 20.55–21.35 ms at 90 Hz, and the final
original-mask window is comparable to both candidate windows. This small,
inconsistent difference does not justify a persistent affinity change. All
8,000 measured head queries and 8,000 vsync-age queries pass. The feed consumes 4,499 camera
sets, publishes 182,216 confident head outputs and has no camera refusal. All
13,747 controller callbacks lack public optical confidence; pointing remains
unverified. All 147 export members, shutdown, full BOOT/DTBO readbacks and muted,
offline stock return verify. Earlier v1/v2 affinity harness failures are retained
separately and supply no performance comparison.

A cold Facet system-layer-in-distortion-pass retry, with the current forwarded
overlay layout correction, fails before dashboard readiness. In
`output/pico-layer-pass-20261025-v1/`, the kernel rejects camera request 1,945 for
congestion at monotonic 160.959844 s. At 161.038007 s, frame 1,949 arrives while
head frame 1,947 is incomplete; the collector refuses it and stops tracking.
The readiness probe correctly rejects its 436 invalid head queries. No late
measurement window is reached. The selected runtime settings are exported and
hash-matched independently of the source profile. The early stable readback
contains a dark grid in both reconstructed eyes, not an accepted Steam panel.
The 120-member export, full firmware readbacks, shutdown and offline muted stock
return verify. This establishes the failure sequence, not its scheduling cause
or a general fault in the layer option; the maintained option remains off.

The v2 retry restores the 189 hash-verified Mesa cache files to a new private
RAM cache. It reaches dashboard readiness, then accepts 3,000 head queries in
the first 30-second window but records 24 overdue vsync ages. Its retained
1,346 frames each report a drop; GPU median/p99 are 13.167/13.763 ms, above the
11.111 ms budget, and interval median is 22.282 ms. The stable scanout contains
fragmented geometry in both reconstructed eyes despite visible-overlay flags.
The harness rejects the timing result and does not run later windows. Its
head-ring-full message occurs after that rejection during cleanup, so it is
not evidence for the initial timing failure. All 134 export members, firmware
readbacks, shutdown and quiet offline stock return verify. This candidate is
not promoted. The matched v3 cold control changes only that option back to off;
all other payload member hashes match v2, including the restored cache. All three
late windows pass 9,000 head queries and 9,000 vsync-age queries in total.
GPU medians return to 7.24–7.27 ms and both stable and late readbacks contain
the modern sign-in panel and toolbar in both reconstructed eyes. Thus the
restored cache is usable with the retained rendering path. This separate-boot
comparison rejects the candidate configuration, without establishing its internal
renderer/driver cause or a general performance claim.

The control still reports 194 drops in 7,970 sampled frames, with interval p99
21.01–21.91 ms. Controller output has 13,751 decoded callbacks and zero public
confident poses. Neither frame-pacing nor pointing acceptance is complete.
All 144 export members, full firmware readbacks and MCU/DSP shutdown verify.
An initial post-reboot ADB UUID query fails with a protocol fault; its receipt
is retained, and an unchanged verification retry confirms muted offline stock.
No firmware partition was flashed. Eleven exact duplicate staging archives are
removed only after matching their remote/retained-host hashes; recovery,
calibration and host evidence remain intact.

### Paired counter and display-fence correlation (2026-10-25)

`output/pico-vsync-correlation-20261025-v1/` completes all three diagnostic
windows and retains two overdue queries. The WSI/present log and kernel vblank
trace verify, but the requested external Vulkan layer produces no CSV. That
missing stream is not used to infer API wait durations.

The next rebuild adds counter observations to the existing optional Mesa trace.
Its v2 run passes GPU interop, all four cross-exec binary/timeline buffer-sharing
cases and the complete camera/head feed. It retains two overdue queries. The
recorded metadata says paired timing is enabled, but no successful paired-counter
trace is emitted. That metadata alone does not verify the selected counter path.
In this v2 run, kernel delivery of sequence 4,763 precedes its Mesa callback by
about 16 ms; this is a userspace delivery interval, not a stopped panel clock.

The v3 harness explicitly supplies the production
`MESA_VK_WSI_FRAME_COUNTER_TIMING=1` setting and verifies it in the actual
`vrcompositor` child's environment. The systemd main process is `runuser` and
must not be mistaken for that compositor when collecting its environment/maps.
The rebuilt library's hash is verified before deployment; its private-query
arguments and 14,862 successful paired queries are observed directly. The
extracted-function sanitizer test passes, and native GPU sharing passes again.
No GPU fence, presentation-completion or timing-acceptance semantics change.

The v3 diagnostic windows pass all 9,000 head queries and retain six overdue
vsync ages, ranging from 22.252 to 23.022 ms. Their pending presents wait on
the display worker's KGSL buffer fences for 7.498–9.257 ms before completion.
The corresponding commit-to-Mesa-flip intervals are 14.164–20.358 ms; kernel
event delivery to the Mesa callback takes 0.032–0.516 ms for these six events.
This distinguishes the buffer dependency, flip and notification intervals. It
does not split GPU queue delay from execution, establish a defective fence or
justify changing completion semantics. The kernel scanout clock keeps advancing.
Measured cadence over the retained trace is approximately 89.784 Hz for the
nominal 90 Hz mode.

Within each late window, deduplicated software frame histories report
2,774/76, 2,780/63 and 2,788/53 frames/drops respectively, with GPU medians
7.2567, 7.1762 and 7.1919 ms. Interval p99 remains about 22.26 ms. The histories
include the initial pre-window snapshot and are not disjoint frame cohorts.
These instrumented observations do not establish clean pacing or photon latency.

All 4,499 camera sets are consumed and 182,212 confident head outputs are
published with no bad result. All 13,746 decoded controller callbacks still lack
public optical confidence. The 153-member export verifies; full BOOT/DTBO
readbacks, MCU/DSP shutdown and muted offline stock return pass. The restored
build toolchain and its initial missing-dependency failures are retained in the
private build evidence. No firmware partition or Quest device is modified.

### Optional 72 Hz UI profile (2026-10-25)

The next cold RAM boot, `output/pico-vsync-correlation-20261025-v4-72hz/`, keeps
the same optics, render resolution, trace-enabled Mesa library, paired-counter
path and camera/controller feed. It selects the 72 Hz mode and changes the
private optical interval to 13,888,889 ns. The kernel trace measures 71.827 Hz
over monotonic 180–260 seconds, with a median vblank interval of 13.922 ms.
Actual compositor environment/maps and thread samples use the `vrcompositor`
child, rather than its `runuser` wrapper. The WSI callback thread remains ordinary
nice 0; no priority or affinity policy is added.

All three late windows pass: 9,000 valid head queries and no overdue vsync ages
against the unchanged two-selected-period bound. The trace contains 12,131
successful paired queries and 24,221 matched display-worker fence waits. It
does not establish GPU execution/queue separation or photon latency.

| Late window | Sampled frames | Reported drops | Frame-interval p99 | GPU p99 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2,288 | 8 | 14.081 ms | 7.770 ms |
| 2 | 2,281 | 9 | 14.114 ms | 7.670 ms |
| 3 | 2,288 | 9 | 14.194 ms | 7.645 ms |

Each window includes its initial pre-window history snapshot; these are not
disjoint cohorts. The matched 90 Hz run above still has six overdue queries
and 53–76 drops per sampled window. This single separate-boot comparison supports
an optional lower-refresh configuration, not a fix for 90 Hz or proof of lower
motion latency. Lens acceptance and longer-run pacing remain open.

The build bundles `steamvr-ui-72hz.vrsettings`; it matches the exported selected
settings, including explicit `disableLinuxWaitForPresent=false`. The base template
and 90 Hz option remain unchanged. Driver timing must also use the matching
private optical interval; selecting the settings file alone is insufficient.

All 4,499 camera sets complete, with 182,255 confident head outputs and no bad
result. The 13,767 decoded controller callbacks still have zero public optical
confidence. The 153-member export is 17,436,265 bytes, SHA-256
`80ec3ad81c8332719024f6def3f7146c0ae55d652ff865545d7ee8bdb3a717ee`.
Member hashes, full BOOT/DTBO readbacks, MCU/DSP shutdown and muted offline stock
return verify. No firmware partition was flashed; Quest remains untouched.

### GPU command timing at 90 Hz (2026-10-25)

`output/pico-gpu-dispatch-20261025-v1/` retains 91,102 KGSL queue, submit, clock
sync and retirement events, together with paired counters, display-worker fences
and vblank notifications. The exact kernel already inserts command start/retire
profiling reads on this GPU; enabling these tracepoints does not add a new
profiling policy. The trace collector reports no errors, overruns or dropped
events. Sync-pair measurements agree with a 19.2 MHz always-on GPU counter.

All six late vsync-age faults map from the display fence's KGSL timeline name
and timestamp to a unique queued/submitted/retired compositor command. Their CPU
dispatch intervals are 0.022–0.132 ms; GPU submission-to-start intervals are
0.014–0.063 ms. GPU start-to-retire intervals are 7.389–7.835 ms. This is elapsed
command time, including any preemption or interleaving, rather than shader-active
time. Estimated GPU retirement to display-fence completion takes 0.195–0.458 ms.
These six samples do not show a long GPU queue stall or establish a fence defect.

Across the late 175–265-second interval, the compositor's median/p99 command
intervals are 7.214/7.910 ms; its GPU submission-to-start p99 is 1.443 ms. Gamescope
has separate commands with median/p99 intervals of 0.657/2.902 ms. These are
instrumented stationary observations, not a general scheduling diagnosis.
GPU completion versus the nearby kernel vblank notification suggests limited
presentation margin, but does not measure the panel latch deadline or photons.
No priority, completion or timing-acceptance rule is changed from this result.

All 9,000 late head queries pass; the six overdue ages remain failures of the
unchanged two-period bound. All 4,499 camera sets complete with 182,215 confident
head outputs and no bad result. All 13,795 decoded controller callbacks still
lack public optical confidence. The fresh ordered image/IMU subset and its
separate calibrated CPU rejection replay are recorded in the
[controller protocol notes](pico-controller-protocol.md#observed-position-gate-rejection-2026-10-25).

The 157-member export is 43,210,269 bytes, SHA-256
`4729adfde06979c09d198063697926866d0877ff88f13b0d825f42b2d0972fda`.
Member and complete compressed-stream hashes, full Pico BOOT/DTBO readbacks,
MCU/DSP shutdown and the Pico's muted offline stock return verify. The owned USB
helper is joined after return. No firmware partition is modified; Quest remains
untouched.

### Render-pass mode comparison at 90 Hz (2026-10-25)

`output/pico-tile-pacing-20261025-v1/` compares automatic rendering with forced
system-memory rendering in one native boot: automatic, SYS, SYS, automatic.
Each observation lasts 20 seconds after a two-second settle. Pixels, optics,
Mesa, tracking feeds and the two-period vsync-age bound remain unchanged.
The exact retained Mesa source supports the private `TU_DEBUG_FILE` override;
GPU render-pass records confirm that the requested modes actually run.

| Window | Policy | Sampled frames | Reported drops | GPU median / p99 |
| --- | --- | ---: | ---: | ---: |
| 1 | automatic | 1,853 | 82 | 7.271 / 8.020 ms |
| 2 | forced SYS | 1,868 | 43 | 7.468 / 8.066 ms |
| 3 | forced SYS | 1,845 | 72 | 7.458 / 8.063 ms |
| 4 | automatic | 1,864 | 48 | 7.175 / 7.826 ms |

Histories include their initial pre-window snapshot and are not disjoint cohorts.
Interval p99 remains approximately 22.27 ms in all four windows. All 8,000 late
head queries are valid, but three vsync-age faults remain. The override increases
median GPU cost slightly and provides no consistent pacing improvement. It is
rejected and automatic rendering is restored; no maintained policy is changed.

The trace retains 14,771 complete frame objects and 59,084 render passes. Its
final enclosing-array bracket is absent at shutdown; parsing complete objects
requires appending only that bracket in memory, leaving the original intact.
Five GPU clock regressions around paused captures prevent a global GPU-to-CPU
time mapping. Four passes occur per frame, two eye-sized and two panel-sized;
framebuffer dimensions alone do not establish fragment coverage without viewport
and scissor data. All report one sample. This does not measure photons.

Host previews show the Steam sign-in panel and modern toolbar in both eyes for
both policies. They do not establish through-lens clarity, IPD or motion quality.
All 4,499 camera sets complete. The 165-member export is 25,907,543 bytes,
SHA-256 `ac53dd1bce9772649a9fa0810a96b547147eeb46a376fa0a550e01c2f83b4d01`.
Member and compressed-stream source hashes, full BOOT/DTBO readbacks, MCU/DSP
shutdown, muted offline stock return and owned USB helper join verify. No firmware
partition or Quest device is modified.

### Render-thread scheduling control at 90 Hz (2026-10-25)

`output/pico-render-priority-20261025-v3/` compares the exact KGSL-submitting
render thread at OTHER/0, RR/2, RR/2 and OTHER/0 in one native boot. Each window
lasts 20 seconds after a two-second settle. The external owner checks executable,
service membership, thread start identity and unchanged affinity before each
change. RR uses reset-on-fork; the application retains its realtime syscall
restriction and zero realtime-priority limit. A 100 ms continuous realtime CPU
limit remains armed. The original policy is read back after restoration.

| Window | Base policy | Runnable-delay p99 | Sampled frames / drops | GPU median |
| --- | --- | ---: | ---: | ---: |
| 1 | OTHER/0 | 1.503 ms | 1,841 / 84 | 7.341 ms |
| 2 | RR/2 | 0.340 ms | 1,874 / 40 | 7.258 ms |
| 3 | RR/2 | 0.336 ms | 1,878 / 36 | 7.268 ms |
| 4 | OTHER/0 | 0.833 ms | 1,873 / 44 | 7.263 ms |

Scheduler distributions contain complete runnable-to-switch-in intervals within
each observation. Frame histories include their initial pre-window snapshot and
are not disjoint cohorts. Trace priorities predominantly match each requested
base policy; short effective-priority changes also occur, whose source is not
captured. A trace priority alone does not establish a different base policy.

All 8,000 late head queries pass, but five vsync-age faults remain: three in the
first normal window, one in the second realtime window and one in the final
normal window. Frame-interval p99 remains about 22.25–22.28 ms. The realtime
control reduces runnable delays without establishing a complete pacing fix;
no maintained launch policy is changed. The remaining realtime-window fault
includes a measured 2.697 ms GPU submission-to-start interval followed by
7.174 ms elapsed command execution. This establishes a GPU queue delay in that
sample, not the cause of every missed deadline or the physical panel latch time.

The first attempt stops before any priority change after the compositor receives
SIGKILL; the sender/cause is not established. Its sensor shutdown and stock return
verify. The next attempt completes the comparison but its syscall-heavy CPU trace
reaches the 64 MiB cap at 209.95 seconds. Those results retain explicit partial
coverage. Version 3 omits raw syscall tracing and raises the bounded cap to
128 MiB; its 37,710,672-byte stream covers all four windows with no collector
error, overrun or dropped events. These earlier attempts are retained, not
reclassified as complete trace captures.

All 4,499 camera sets complete, with 182,255 confident head outputs and no bad
result. All 13,770 decoded controller callbacks still lack public optical
confidence. The 163-member export is 21,009,475 bytes, SHA-256
`5554a71bb308a6afbc36153f707c5b814d27ccf938ef2b0fbf194cf56d04a4ec`.
Member/source hashes, full BOOT/DTBO readbacks, MCU/DSP shutdown, original render
policy restoration, muted offline stock return and USB helper join verify.

### KGSL GPU priority path (2026-10-25)

`output/pico-gpu-priority-20261025-v1/` tests a Mesa candidate that connects
Vulkan global priority to KGSL context flags. It also includes the already
verified counter-query swapchain identity correction. Rendering, optics, the
90 Hz mode and timing bounds match the preceding scheduler comparison. The
same four CPU policy windows run in a new cold RAM boot. This is a separate-boot
comparison, not a same-boot GPU-priority crossover.

The exact retained kernel accepts priority bits in context creation and allocates
multiple rings when its preemption support is active. The actual trace places
the compositor at priority 1/ring 0; gamescope and other observed contexts remain
at their default priority 8/ring 2. The compositor environment requests
`TU_DEBUG=hiprio`, but that hint does not override an application's chained global
priority. The request structure itself was not traced. Kernel priority 1 is
therefore the verified tier, rather than an assumed HIGH/4 selection.

Across the late 175–265-second interval, compositor submission-to-GPU-start p99
is 0.477 ms, versus 1.430 ms in the preceding medium-priority run; maxima are
0.969 and 2.868 ms respectively. Median elapsed compositor command time is
7.278 versus 7.303 ms. Gamescope's elapsed command p99 rises from 2.931 to
10.872 ms; these elapsed intervals include preemption/interleaving and do not
measure shader-active time. Prioritizing the compositor does not establish an
improvement to application throughput or overall input latency.

| CPU window | Sampled frames / drops | Frame-interval p99 | Overdue vsync samples | Timing acceptance |
| --- | ---: | ---: | ---: | --- |
| OTHER/0 | 1,866 / 56 | 22.269 ms | 0 | pass |
| RR/2 | 1,906 / 12 | 11.455 ms | 2 | fail |
| RR/2 | 1,892 / 24 | 22.231 ms | 0 | pass |
| OTHER/0 | 1,881 / 39 | 22.259 ms | 3 | fail |

Timing acceptance means all 2,000 age queries in that window return valid values
within the unchanged two-selected-period bound. It is separate from head-pose
validity and reported frame drops. The 3/0/1/1 fault distribution in the preceding
CPU-only control belongs to that earlier boot, not this GPU-priority run.

Each history includes its initial pre-window snapshot. All 8,000 late head
queries pass, but five vsync-age faults remain. Their GPU submission-to-start
intervals are 0.062–0.147 ms, followed by 7.362–7.955 ms elapsed command intervals.
This supports the priority path's operation without establishing clean 90 Hz
pacing. No CPU realtime policy or priority hint is promoted into a default profile.

The incremental library is SHA-256
`93d1df744a9946c6f33ecf15822f95b90994327a9bb06f51d4f85fae0b1ad9d9`.
The exact functions pass focused ASan/UBSan tests, and the priority patch matches
its compiled source with a fuzz-zero forward/reverse roundtrip. The rebuilt
native stack passes all four 4 MiB cross-exec binary/timeline semaphore and
buffer-sharing cases. This is incremental-build and device evidence; a fresh
full bundle build is not represented by its private incremental receipt.

All 4,499 camera sets complete, with 182,216 confident head outputs and no bad
result. All 13,750 decoded controller callbacks still lack public optical
confidence; tracked controller pointing remains unverified. The complete CPU/GPU
trace is 36,779,553 bytes with no collector error, overrun or dropped events.
The 163-member export is 20,951,034 bytes, SHA-256
`94ca15036ce8c54c3d8bbfb853e357719457ee840092f7f1183f98ac4a2695d9`.
Member/source hashes, full BOOT/DTBO readbacks, MCU/DSP shutdown, original CPU
policy restoration, muted offline stock return and USB helper join verify.

### Combined-layer control on the rebuilt stack (2026-10-25)

`output/pico-facet-combined-20261025-v1/` selects
`renderSystemLayerInDistortPass=true` before compositor startup, retaining the
new Mesa priority path, pixels, optics and 90 Hz mode. The render thread uses
RR/2 throughout three 30-second late windows. This separate-boot control checks
whether the older camera failure reproduces on the current ownership/feed stack.

It does not reproduce: all 4,499 camera sets complete, with 182,218 confident
head outputs, no bad result and all 9,000 late head queries valid. However, GPU
median time rises to 13.163, 13.124 and 13.156 ms. Frame histories report
1,475/1,475, 1,481/1,481 and 1,476/1,476 frames/drops respectively, with interval
p99 around 22.38–22.40 ms. There are 211 vsync-age faults. Histories include the
initial pre-window snapshot and are not disjoint cohorts.

The stable late scanout's host inverse-optics preview contains large fragmented
triangles in both eyes instead of the Steam panel. Dashboard visibility reported
through OpenVR does not establish correct rendering. This control is rejected
for both output corruption and performance; it does not establish the cause of
the shader/geometry failure. The maintained setting remains false. No optical
controller pose is accepted in any of the 13,756 decoded callbacks.

The complete 20,182,116-byte CPU/GPU trace has no collector error, overrun or
dropped events. The 161-member export is 4,797,679 bytes, SHA-256
`57e8ca95576bff4df6d2f36c8c10ec2898c01b7f3c693a0e0e315e84b5abb201`.
Member/source hashes, full BOOT/DTBO readbacks, MCU/DSP shutdown, original render
policy restoration, muted offline stock return and owned USB helper join verify.
No firmware partition or Quest device is modified.


### Guarded priorities and bounded camera grouping (2026-10-25)

`output/pico-camera-reorder-20261025-v1/` validates the opt-in guarded Mesa library,
SHA-256 `7a37eeeb925c429b46c0ac233be47990692da27c8308459654df0e1e9367ef01`,
on the same pinned Pico RAM kernel. Actual compositor environment includes
`TU_KGSL_CONTEXT_PRIORITIES=1`; trace priorities remain 1 for the compositor and
8 for gamescope. Default interop passes all four cross-exec cases. The ordinary
rendering path remains selected, with identical pixels/optics, nominal 90 Hz and
render RR/2 in all three 30-second late windows.

| Window | Sampled frames / drops | Frame-interval p99 | GPU median | Overdue age queries |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2,815 / 42 | 22.225 ms | 7.270 ms | 0 / 3,000 |
| 2 | 2,833 / 22 | 11.499 ms | 7.205 ms | 0 / 3,000 |
| 3 | 2,831 / 16 | 11.363 ms | 7.202 ms | 0 / 3,000 |

All 9,000 head queries are valid and all three age windows pass the unchanged
two-period bound. Frame histories include their initial pre-window snapshot.
Reported drops remain, and one bounded stationary run does not establish clean
pacing, physical tracking/lens quality or the cause of the improved age results.
Host previews show the Steam sign-in panel and toolbar in both eyes.

All 4,499 camera sets complete, with 182,215 confident head outputs and no bad
result. The two-slot collector is wired into the owned native diagnostic, but
its live interleave counters are zero; its boundary change is tested by exhaustive
host replay, not attributed as the cause of this run's timing results. All
13,770 decoded controller callbacks still lack public optical confidence.

The selected SDE trace contains 180,082 balanced markers and 90,041 begin/end
spans, with no unmatched boundary. These selected spans exclude the separately
traced MSM commit worker's GPU-fence wait. Coarse frequency samples report the
performance governor and maximum current frequency for all three CPU policies;
they are not per-frame clock measurements. Complete CPU/GPU and DRM/SDE streams
are 37,395,548 and 30,983,222 bytes, with no collector errors, overruns or drops.

Two earlier attempts remain failures: one compositor startup ends with a
kernel-originated SIGKILL of unverified cause; the fatal-attribution retry instead
stops on the 949-set camera interleave described in the controller notes. No
watchdog limit is relaxed. The successful follow-up retains those diagnostics
and restores `print-fatal-signals` to its original value afterward.

The 168-member export is 22,153,504 bytes, SHA-256
`56adac7cbbd0df339067406bb1d3a6375f63cded57826022fa3c8ccb23db514c`.
Member/source hashes, full Pico BOOT/DTBO readbacks, MCU/DSP shutdown, original CPU
policy/debug-setting restoration, muted offline stock return and USB helper join
verify. No firmware partition or Quest device is modified.

### Display-event thread delay (2026-10-25)

Exact present IDs, KGSL fence context/timestamps, DRM sequences and scheduler
events in `output/pico-camera-reorder-20261025-v1/` identify a remaining CPU
delay before the next render. Before missed sequences, the display-event thread
has median runnable waits of 1.526/1.728/1.369 ms across the three windows,
versus 0.006–0.007 ms on ordinary frames. GPU execution is not the only remaining
boundary: some commands retire before the observed vblank, but their fence wait
or encoder kickoff finishes afterward. Those trace events do not establish the
physical panel latch deadline or photon timing.

`output/pico-wsi-event-priority-20261025-v1/` holds the render thread at RR/2 and
compares only the exact display-event TID in four 20-second probe requests:

| Event policy | History frames / drops | In-window DRM skipped sequences | Interval p99 |
| --- | ---: | ---: | ---: |
| OTHER/0 | 1,901 / 18 | 16 | 11.556 ms |
| RR/2 | 1,911 / 2 | 2 | 11.300 ms |
| RR/2 | 1,914 / 0 | 0 | 11.285 ms |
| OTHER/0 | 1,900 / 9 | 9 | 11.306 ms |

History snapshots include frames before each observation window; the DRM column
counts only consecutive flip pairs fully inside that window. These counts must
not be treated as identical cohorts. All 8,000 head and unchanged two-period
vsync-age queries pass. All 4,499 camera sets complete, with 182,214 confident
head outputs and no bad result. Optical controller publication remains zero.

The two RR-window misses have different recorded boundaries: one has 6.717 ms
blocked before GPU submission; the other has 1.210 ms between estimated GPU
retirement and fence-wait completion, crossing the observed vblank. Their deeper
blocking/callback causes remain unverified. The comparison supports event-thread
scheduling as a contributor; it does not establish universally clean 90 Hz.
The trace has one unfinished fence wait at 303.221 seconds, after the final
window ends at 267.742 seconds; all compared intervals are complete. Both trace
collectors report no lost events, and source/member hashes verify.

The export contains 172 members, 21,758,662 bytes, SHA-256
`14e794fbf952c521aa2d3dfd97b3e3fbacef9b274e3e6fe47135c4a5629abda5`.
Exact event/render scheduling restoration, full Pico BOOT/DTBO readbacks,
MCU/DSP shutdown and muted offline stock return verify. The owned USB host
wrapper is joined after the expected reboot disconnect. No Quest is modified.

A first library-startup test in `output/pico-wsi-event-startup-20261025-v1/`
verifies graceful `EPERM` fallback: the original compositor service explicitly
disallows realtime scheduling and its event thread remains OTHER/0. Its assertion
stops before UI acceptance; its recovery and firmware readbacks still verify.

The `v2` startup test verifies event RR/2 with a native `User=vr` service, priority
ceiling 2, no capabilities and realtime requests permitted. It then fails before
UI acceptance with a confirmed kernel `CPU Watchdog Timeout (hard)` for the
render thread. This establishes the SIGKILL cause for this run, not for earlier
unattributed kills. The pinned KGSL fast-submission path temporarily promotes the
caller to FIFO/40; the RT watchdog counter resets on RT wakeup. Counter
accumulation across temporary boosts while restoring OTHER is a source-backed
explanation to investigate, not a directly recorded counter trace.

`output/pico-wsi-event-startup-20261025-v3/` changes only the timing of the existing
exact-render RR/2 selection, applying it before Steam UI startup. It keeps the
same library, event policy, affinity and 100 ms watchdog. Actual startup readbacks
verify both selected threads. The full run completes without a watchdog timeout:

| Window | History frames / drops | Interval p99 | GPU median | Overdue age queries |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2,859 / 5 | 11.281 ms | 7.243 ms | 0 / 3,000 |
| 2 | 2,843 / 3 | 11.276 ms | 7.173 ms | 0 / 3,000 |
| 3 | 2,845 / 3 | 11.272 ms | 7.179 ms | 0 / 3,000 |

All 9,000 head queries are valid, all 4,499 camera sets complete, and head output
has 182,217 confident callbacks with no bad result. All four 4 MiB cross-exec
interop cases pass. The host inverse preview shows Steam sign-in and its toolbar
in both eyes; physical sharpness, IPD and moving-head acceptance for this build
are pending.
All 13,748 controller callbacks still lack public optical pose confidence.
The camera reorder counters remain zero, so this run does not exercise live
cross-frame recovery. One completed startup does not establish a general
watchdog fix or eliminate the 5/3/3 remaining dropped frames.

The opt-in library SHA-256 is
`d8413b8c5802ce85977bbd6a630ae9d9fbae7059222141e9fc39ab8792ad473b`.
Its retained-source incremental build and actual-helper sanitizer tests pass;
this is not a fresh full-bundle build. All 18 patches apply with zero fuzz to the
checksum-pinned Mesa archive, and all 13 patched targets match the compiled
source byte for byte. Full CPU/GPU and DRM/SDE streams are 34,782,471 and
31,335,475 bytes with no collector errors or lost events; the one unfinished
fence wait is outside the compared windows.

The 172-member export is 21,927,883 bytes, SHA-256
`801c7c07288e6c2541f0c15a0df7b5883891188e027375814855a1b4488e6829`.
Source/member hashes, full Pico BOOT/DTBO readbacks, MCU/DSP shutdown, original
render-policy/debug-setting restoration, muted offline stock return and owned
USB host join verify. The event policy ends with its owned compositor process.
No firmware partition or Quest device is modified.

### Completed-present scheduling and callback boundaries (2026-10-25)

`output/pico-callback-latency-20261025-v2/` validates Mesa's opt-in presentation
caller scheduling without an external render/event thread priority setter. The
event thread reports RR/2 with reset-on-fork, and the presentation caller reports
RR/2 without that bit. The process remains UID 1000 with no effective
capabilities, priority ceiling 2 and the unchanged 100 ms CPU watchdog. The same
kernel, optics, pixels, camera grouping and GPU context priorities are retained.

An earlier first-GPU-submit policy request in the version-1 experiment fails
during initialization with a confirmed hard CPU-watchdog timeout. Its source is
excluded from the maintained patch set. Patch 0019 instead waits for a completed
nonzero presentation; actual-function sanitizer tests cover that condition,
mutex release, per-thread activation, preserved policies and permission failures.

The completed-present run finishes all 4,499 camera sets with 182,208 confident
head outputs and no bad result. All 9,000 head queries are valid. One vsync-age
query is overdue at 22.284 ms against the unchanged 22.222 ms bound; the three
age windows therefore fail/pass/pass. Four default 4 MiB cross-exec GPU interop
cases pass, and no CPU-watchdog timeout occurs. Controller decoding yields
13,770 callbacks and zero public optical confidence; tracked pointing is open.

| Window | History frames / drops | Fully in-window DRM skips | Interval p99 |
| --- | ---: | ---: | ---: |
| 1 | 2,853 / 8 | 9 | 11.342 ms |
| 2 | 2,854 / 1 | 1 | 11.301 ms |
| 3 | 2,850 / 0 | 0 | 11.274 ms |

History snapshots and fully contained DRM flip pairs have different observation
boundaries. This run adds substantial diagnostic traffic and is not a matched
performance comparison with the preceding uninstrumented run.

The existing KGSL queue/start/fire tracepoints match all 34,270 callback jobs;
692,372 selected syscall pairs are recorded. There are no collector errors or
lost events. One missed frame has an exact matching fence callback queued for
3.746 ms before execution, while the GPU had retired 2.313 ms before the
observed vblank. Callback dispatch accounts for most of its 3.954 ms GPU-to-fence
interval; the trace does not split pool availability from CPU scheduling.
Other misses overlap 5.762 ms and 2.506 ms futex waits in mappings of
`/dev/shm/u1000-ValveIPCSharedObj-SteamVR`. Their internal mutex owners and lock
reasons are not yet established. Overlap alone does not identify the code that
holds those locks.

The tested library SHA-256 is
`d6617841175064bce7759f0833247ac8bee3e81e6ee519af4311c52f8b47b6cf`.
Its incremental build passes actual-function sanitizer tests; all 19 patches
apply to the checksum-pinned archive with zero fuzz and all 13 patched targets
match the compiled source. This is not a fresh full-bundle build. Complete
CPU/GPU/syscall and DRM/SDE streams are 173,308,875 and 31,325,234 bytes.

The 180-member export is 31,872,666 bytes, SHA-256
`de18c9fb68a522c8ed1340e04264c6bd03351eabb6f7d7f1ef616f0cba80c08e`.
Member/source hashes, full Pico BOOT/DTBO readbacks, MCU/DSP shutdown, diagnostic
restoration and muted offline stock return verify. Both thread policies end with
the owned compositor, and the owned USB host wrapper is joined. No firmware
partition or Quest device is modified.

### Callback CPU eligibility comparison (2026-10-25)

`output/pico-callback-affinity-20261025-v1/` keeps the preceding tested library,
kernel, GPU priorities and render/event scheduling. Only the `kgsl-events`
workqueue CPU mask changes, in order `ff/f0/f0/ff`; nice stays -20,
`max_active` 256 and `numa` 1. All eight CPUs are online. Readback confirms that
CPUs 4–7 have higher capacity than CPUs 0–3; trace events confirm that the `f0`
windows execute callbacks only on CPUs 4–6. Renderer affinity is unchanged.

| Window / mask | History frames / drops | Fully in-window DRM skips | Callback queue-to-start p50 / p99 / max |
| --- | ---: | ---: | ---: |
| 1 / `ff` | 1,917 / 4 | 3 | 0.060 / 0.498 / 1.240 ms |
| 2 / `f0` | 1,911 / 3 | 3 | 0.157 / 0.551 / 2.417 ms |
| 3 / `f0` | 1,915 / 6 | 5 | 0.161 / 0.543 / 3.312 ms |
| 4 / `ff` | 1,908 / 0 | 0 | 0.059 / 0.455 / 1.029 ms |

Restricting eligibility does not improve overall pacing and increases callback
dispatch latency in both middle windows. The original `ff` mask is restored;
this experiment does not change the maintained policy. History snapshots and
fully contained DRM flip pairs still have different observation boundaries.
The 34,354 callback jobs all match queue/start/fire records, and the streamed
traces have no collector errors or dropped events. This instrumented comparison
does not establish a general scheduler optimum or physical latency.

All 8,000 head and vsync-age queries pass the unchanged checks. The capture
finishes 4,499 head camera sets with 182,214 confident outputs and no bad result.
Thread snapshots include diagnostic clients as well as SteamVR; they do not
establish the internal owners of its shared-memory locks.

The controller SDK decodes 38,679 callbacks, including 1,163 public-confidence-1
reports. In the retained every-eighth-callback sample, all 4,834 results still
have state zero; all 146 confidence-1 results have diagnostic `0x52 == 0`.
This is consistent with the getter's documented synthesized confidence and
does not establish optical acquisition. Controller pose publication stays off.

The 186-member export is 32,223,377 bytes, SHA-256
`5aacc836c10ee5fd64fc03ba4184588b533de6671e22da5174dd2ee010b3f14e`.
Member/source hashes, full BOOT/DTBO readbacks, workqueue restoration, MCU/DSP
shutdown, muted offline stock return and the owned USB wrapper's exit verify.

### Controller input publication cost (2026-10-25)

`output/pico-controller-input-updates-20261025-v1/` tests the driver that caches
successful boolean publications. Every component is initialized after each
activation; later unchanged values make no input API call. Failed publications
remain retryable, active controls are released on disconnect/deactivation, and
pose updates continue on every controller update. Sanitizer fixtures cover
100 unchanged updates with continued pose publication, a single-control change,
failed initialization, failed active publication, recovery and reactivation.

The native ARM64 driver SHA-256 is
`2b2bfd7ecf724a2f71d8e5d1fae6e4b920f2a18145d336f422bc1bf1bbcbc528`.
Only that driver and its composition receipt change in the staged payload;
the preceding probe, settings, models, Mesa and capture stack are retained.
The native controller/head coexistence probe passes, as do all four 4 MiB
cross-exec GPU interop cases. The compact export omitted the controller counter
log, so the API-call reduction is established by the host fixture, rather than
quantified on hardware. No frame-pacing improvement is claimed.

All 9,000 late head and vsync-age queries pass the unchanged checks. The head
capture completes 4,499 camera sets and 182,218 confident outputs without bad
results. History frames/drops are 2,849/7, 2,844/5 and 2,846/4; fully contained
DRM flip pairs skip 8/5/4 vblanks. Missed refreshes therefore remain despite the
passing age samples. Controller image ownership reports 4,441 complete sets
and three drops; all 13,786 decoded controller callbacks lack public confidence.
Optical pose publication stays off and tracked pointing remains unverified.

The 180-member export is 31,978,743 bytes, SHA-256
`e715d4e095d41f349d85216ea5a2ef485315b73018966e239e011f0bd6e0b7e0`.
Member/source hashes, full BOOT/DTBO readbacks, workqueue/GPU restoration,
MCU/DSP shutdown, muted offline stock return and owned USB-wrapper exit verify.

### Diagnostic client presence comparison (2026-10-25)

`output/pico-observer-cost-20261025-v1/` retains the same driver, Mesa, pixels,
kernel, tracking and scheduling. The bounded late client is present/absent/
absent/present. Both absent windows retain the independent DRM/GPU/callback
traces and running camera/SLAM/SteamVR stack; no head-query or vsync-age API
acceptance is claimed for them.

| Window | Client | Measured duration | Fully contained flip pairs / skipped vblanks |
| --- | --- | ---: | ---: |
| 1 | present | 21.101 s | 1,887 / 7 |
| 2 | absent | 20.000 s | 1,793 / 1 |
| 3 | absent | 20.000 s | 1,793 / 1 |
| 4 | present | 20.976 s | 1,881 / 1 |

Misses remain without the client. The final present window resembles the absent
windows; the first present window alone does not establish a repeatable observer
penalty. This rules out that client as the sole cause, not all tracing overhead.
All 4,000 late head/vsync-age queries in the two measured client windows pass.
The capture completes 4,499 head camera sets, 182,217 confident outputs and no bad
result. Controller optical publication remains off; its 13,786 decoded callbacks
have zero public confidence, and controller image ownership reports nine drops.

This export also retains the driver counters omitted in the preceding run.
Across 30 samples spanning 30.542 s, controller updates advance from 325 to
3,206, while boolean input calls stay at the initial 12, with zero changes or
errors. This verifies suppression of redundant calls on the Pico, including
unchanged connected/disconnected states. It does not exercise physical button
transitions or establish a frame-pacing gain.

The 183-member export is 31,596,869 bytes, SHA-256
`75ab4c3ae83cf3a5400afc6449856a62e71012506288da34cb0aa5edb96f2a80`.
Member/source hashes and all 34,417 callback jobs verify without trace loss;
full BOOT/DTBO readbacks, policy restoration, MCU/DSP shutdown, muted offline
stock return and the owned USB-wrapper exit verify.
### Pre-submit IPC stall outside Mesa's wait (2026-10-25)

The observer-free phase of
`output/pico-observer-cost-20261025-v1/` contains a missed refresh whose earlier
syscall analysis began too late: at the preceding Mesa wait's return. The new
`tools/analyze-pico-present-stalls.py` examines the interval from the preceding
observed vblank through GPU queueing, retaining overlapping calls that started
earlier. It streams and verifies the complete source trace against its byte
count and SHA-256, distinguishes futex waits from wake operations, and records
overlap separately from the full syscall duration. Its regression fixture
covers a wait that ends before the old analysis window begins.

For present 6208, render TID 2015 spends 8.605 ms in ARM64 futex syscall 98,
from 200.960049 to 200.968654 seconds. The supplied process map places its address
in `/dev/shm/u1000-ValveIPCSharedObj-SteamVR`. A `sched_wakeup` event from TID
2380 (`CVRAPIITask::Ru`) occurs at 200.968645 seconds. This identifies the
observed waker, not a proven lock owner or the reason it held or signalled the
object. The trace filters did not capture that thread's own execution.

The preceding present flipped at 200.961739974 seconds, while SteamVR entered
Mesa's wait only at 200.968937109 seconds. Mesa returned at 200.968979193
seconds, about 42 microseconds after entry. GPU queueing for the next command
followed at 200.970952 seconds; estimated GPU retirement was 5.983 ms after the
next observed vblank. This instance therefore includes a substantial SteamVR
IPC delay **before entering** Mesa's wait. It does not justify changing Mesa's
wait completion semantics, weakening the age bound, or attributing all other
misses to the same cause. The retained expanded result is
`pre-submit-stalls.json`; tracing the waker and the IPC critical section remains
necessary before selecting a scheduling or lock fix.

### Steam UI API worker scheduling (2026-10-25)

`output/pico-ipc-worker-20261025-v1/` adds scheduler and futex tracing for the
owned `steamwebhelper` thread named `CVRAPIITask::Ru`, after checking its UID,
service group, executable and process/thread start identities. Its scheduling
and affinity remain unchanged; 79 identity snapshots agree. All 4,000 measured
head/vsync-age queries pass. The four windows have 4/2/0/0 contained DRM skips;
these six misses do not include the API-worker stall below.

Eleven renderer futex waits are woken by this worker. Nine have complete worker
scheduler coverage; two earlier observations precede filter readiness and their
worker execution is explicitly unobserved. The largest covered wait is 1.830 ms,
including 1.646 ms of worker runnable delay. Its full preceding runnable interval
is 10.387 ms, of which only the tail overlaps the renderer's wait. After scheduling
in, the worker wakes the renderer 27 microseconds later. Another 157 microseconds
elapses before the renderer's futex returns. The worker's 0.184 ms scheduled-in
overlap must therefore not be called measured lock-hold work.

The worker's `FUTEX_WAKE` returns one and brackets the renderer wakeup. Both
addresses resolve to the same shared device/inode/file offset, despite different
virtual addresses. This supports exact futex correspondence, not the proprietary
critical section's purpose or ownership inferred from a name or expected word.
The original 8.605 ms case is not reproduced. Verified CPU/DRM trace sizes are
186,138,148 / 31,315,408 bytes, with no collector error or reported overruns/drops.

The same-boot comparison in `output/pico-ipc-nice-20261025-v1/` changes only that
worker's CFS niceness. The diagnostic observer is present in every window; RT
policies, affinity, kernel, graphics and tracking settings stay fixed. Identity
and actual per-thread niceness snapshots verify every window.

| Window | Worker nice | History frames / drops | Contained DRM skips | Frame-interval p99 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0 | 1,925 / 10 | 9 | 11.457 ms |
| 2 | −20 | 1,916 / 2 | 2 | 11.277 ms |
| 3 | −20 | 1,912 / 1 | 1 | 11.302 ms |
| 4 | 0 | 1,910 / 7 | 7 | 11.362 ms |

The first control reproduces a 6.575 ms shared-IPC wait before GPU queueing for
present 5607, which misses its next observed vblank. Worker runnable intervals
account for 5.043 ms of that wait; its exact shared-futex wake is retained. The
two boosted windows contain no observed renderer wait woken by this worker.
However, only two such waits occur in the measured controls, and the last control
has none. This supports testing the narrow mitigation, not a claim that it
eliminates long tails or explains every drop. GPU medians are
7.302/7.199/7.190/7.204 ms. All 8,000 head/vsync-age queries pass; niceness is
restored, and other sampled UI threads retain their original niceness.

One ioctl-exit record in that CPU trace has an unexpected syscall number and
cannot be paired. The failed full-syscall parser result is retained; complete
syscall-pairing acceptance is not claimed. The malformed record is outside the
6.575 ms event. The worker's 22,288 futex pairs and independent presentation
records are checked separately. The trace anomaly's cause remains unknown;
no field is truncated or rewritten to force a match.

The exports contain 187 members / 33,020,586 bytes, SHA-256
`e6b4327c94f6998e691e1b7559d779d8362356205308cac0dc6d6c62165bc8fd`,
and 189 members / 33,421,296 bytes, SHA-256
`fd9240eeb1770dbd9eb4f6aef0ae45a232250e36aa9aefc2941e9674fe538c9d`.
Both verify member hashes, full BOOT/DTBO readbacks, GPU/workqueue restoration,
MCU/DSP shutdown and muted offline stock return. The first capture's initial
console-framing syntax error is retained; setup resumes in the same boot after
locally validating corrected hash-framed delivery.

### Opt-in API worker priority helper

`tools/pico-steamvr-ipc-priority.py` provides the tested CFS −20 request as a
bounded, explicit-PID/TID helper. It requires the native Pico boot identity,
UID 1000, the owned Steam UI service, the expected executable/thread role and
ordinary initial scheduling. It checks start identities and readback, preserves
RT policy and affinity, and restores niceness on normal exit, handled SIGTERM/
SIGINT, or Python failure.
Known identity/policy changes refuse restoration writes; an exited worker needs
no write. This is not atomic PID-reuse protection or a worker-restart manager.
It installs no default policy and does not start Steam with root privileges.

Run it only from the owner of an already verified native session, after the
Steam UI API thread exists:

```sh
python3 tools/pico-steamvr-ipc-priority.py \
  --boot-serial DEVICE_BOOT_SERIAL --boot-id CURRENT_BOOT_UUID \
  --pid STEAMWEBHELPER_PID --tid CVR_API_WORKER_TID --seconds 300
```

Eight focused host tests cover role/identity refusal, restoration, applied-then-
failed writes, readback errors, exited tasks and failed restoration. Physical
lens latency, sustained application load and broader production scheduling
acceptance remain separate.

`output/pico-ipc-helper-20261025-v1/` tests the actual maintained helper, whose
deployed bytes match source SHA-256
`b88ea7b8148e9061210c1b7cfebfe1887fcaad0513aeb15d825b20c700e8fffa`.
Both boosted contexts verify the same process/thread identities, ordinary
scheduling and affinity, then restore their complete snapshots exactly. Cleanup
reports no helper error. All 8,000 head/vsync-age queries pass again. The
0/−20/−20/0 windows report 4/2/0/2 history drops and 4/1/0/2 contained DRM skips;
their frame-interval p99 values are 11.282/11.305/11.290/11.272 ms. There is only
one measured API-worker-woken renderer wait, 0.034 ms in the first control.
This verifies application/restoration and another bounded workload comparison,
not reliable elimination of a rare IPC tail. Other deadline misses remain.

The 192-member export is 33,207,987 bytes, SHA-256
`a4c3c3459554c58867c3b0ac2f914c197b6fb63f8d548d66c7afbd98d1879daa`.
Full BOOT/DTBO readbacks, GPU/workqueue restoration, MCU/DSP shutdown, muted
offline stock return and the owned USB helper's exit verify. No controller
confidence gate, pose conversion or calibrated display setting changes.

### Shared callback-pool tracing and the remaining startup watchdog (2026-10-25)

`tools/pico-compositor-trace.py` now supplies filters based on the running
`kgsl-events/pool_ids`, rather than assuming that the queue owns private workers.
The pinned kernel shares unbound pools by niceness and CPU mask. The filters
include all executions on those workers, the queue's rescuer and the separate
KGSL dispatcher. This kernel's activation/end events expose only a work pointer;
activation is retained unfiltered within the bounded recording. Generic current
task filters use `COMM`, scheduler target filters use `comm`, and worker names
use the kernel's glob operator. Eleven focused host tests pass, and native filter
readback verifies acceptance.

The cold run in `output/pico-callback-pool-20261025-v1/` captures 5,901 complete
KGSL queue/activate/start/fire/end generations and 32,256 matched pool execution
spans. Queue-to-activation has a 13 µs maximum; queue-to-start has a 2.087 ms
maximum. The observed shared work includes camera request-manager and USB work.
The longest callback wait overlaps neither. For 1.917 ms of that 2.087 ms wait,
at least one observed worker is runnable and none is scheduled on CPU. This
supports scheduling/dispatch delay rather than complete pool occupancy for this
case. The eventual worker alone must not be assigned the whole queue delay.
Another callback for the same GPU context/timestamp wakes the renderer earlier,
so the longest callback is not independently identified as a critical compositor
fence or a missed-frame cause.

The first 1,201 callbacks precede scheduler coverage. Worker state before its
first observation remains unknown; filtered tracing does not prove a complete
worker inventory. The verified 37,634,507-byte CPU trace reports no collector
error or lost events. Detailed generation accounting, raw numbered excerpts and
coverage limits are retained in
`output/pico-callback-pool-analysis-20261025-v1/`.

This run fails during dashboard shader creation, before the four steady timing
windows. RenderThread runs continuously for 103.625 ms after its last blocking
wake, then receives a kernel SIGKILL. Its recorded RT CPU limit is 100,000 µs,
CPU time is otherwise unlimited and there is no recorded OOM. The pinned
kernel's RT watchdog checks the hard limit on a 250 Hz tick. Together these
observations support watchdog exhaustion; its internal counter is not directly
traced. Patch 0019's completed-present boundary therefore does not establish a
general startup-watchdog fix. The unchanged watchdog is retained while testing
patch 0020's ordinary-scheduling alternative.

The export contains 172 verified data members plus its manifest, 8,658,784 bytes,
SHA-256
`de1eef77c6cf9401a69531f0c4beda0c873a992f8a5e37dc43600749df0ece9c`.
Member/source hashes, full BOOT/DTBO readbacks, GPU/workqueue restoration,
MCU/DSP shutdown and muted offline stock return verify despite the failed test.
No steady pacing or optical controller acceptance is claimed.

### Ordinary caller scheduling exposes watchdog accounting across classes

`output/pico-callback-pool-20261025-v2/` tests patch 0020's ordinary scheduling
alternative with the API worker still nice −20, display-event thread RR/2 and
the existing 100 ms RT watchdog. The deployed library SHA-256 is
`f6a6b87a9bd862f05a17aa3203b37ae7aa2d28deb93f27cbd8ccd6fbb63c1553`.
Actual-function ASan/UBSan tests pass, including mutual exclusion with the RT
option and unchanged presentation results. All 20 patches apply with zero fuzz
to the pinned archive and all 13 patched targets match the incremental build's
source. This is not a fresh full-bundle build.

Startup confirms caller policy OTHER/priority 0 and nice −20. All 6,014 observed
caller scheduling boundaries have priority 100. Nevertheless, the exact kernel
message identifies an RLIMIT_RTTIME hard-limit kill of that caller during GPU
submission, after only 1.215 ms scheduled since its latest blocking wake. This
does not implicate the display-event thread, which woke 38 µs before the signal.
No fatal stack frames were captured despite an accepted stack-trigger setting.

Source inspection finds that KGSL temporarily promotes its current submitter to
FIFO/40 and restores its prior class. The RT timeout counter survives policy
restoration, while the blocking-wake reset lives only in RT-class enqueue. A
restored CFS sleeper therefore misses the reset on waking. The timer check can
act on that retained counter. This is consistent with the recorded kill; the
trace does not directly observe the counter or every temporary policy change.
The narrow correction under evaluation moves the existing reset to common
blocked-task activation, preserving limits and accumulation without blocking.

The failed run captures no steady timing windows or optical tracking acceptance.
Its 20,943,114-byte CPU trace verifies against source SHA-256
`3024edd8aea477b17c747c360b8330f97def50ad135c3a864d07de277eab6fc4`,
with no recorded trace loss. The 2,270,747-byte export contains 162 verified data
members plus its manifest, SHA-256
`c5ad1ea00b1cde5a986070fbaec3439c8203421f3f332634f8aca0a08bbe7e53`.
Full BOOT/DTBO readbacks, resource shutdown, muted offline stock return and the
owned USB host's termination verify. The detailed audit is retained in
`output/pico-callback-pool-analysis-20261025-v2/`.

### Reset the RT budget on actual blocking wake across scheduling classes

Pico Linux patch 0015 moves the existing `rt.timeout` reset from RT-class
enqueue to `ttwu_activate`, guarded by `ENQUEUE_WAKEUP`. A restored CFS sleeper
now receives the same reset as an RT sleeper. Failed/light wakes, runnable
migration, policy changes, preemption and yield do not gain a reset. The
watchdog stamp, tick accounting and configured limits are preserved.

`tests/pico-rttime-regression.c` runs four bounded child-process controls with an
80 ms RT limit, 30 ms CPU bursts and eight rounds. The blocking case changes to
CFS before each 20 ms sleep. `wait4` records child CPU use; nonblocking controls
must receive SIGKILL within a tick-accounting tolerance of 60–120 ms. Children
also have a two-second CPU limit and a five-second parent deadline. The test
requires root and ordinary initial scheduling; use `--expect-legacy` on the
baseline and `--expect-fixed` on the corrected kernel.

| Case | Original kernel | Corrected kernel |
| --- | --- | --- |
| Ordinary scheduling | Eight rounds, 240.099 ms CPU | Eight rounds, 240.088 ms CPU |
| Short RT bursts, then blocking CFS sleep | Killed after two rounds, 80.176 ms CPU | Eight rounds, 240.374 ms CPU |
| RT/CFS changes without blocking | Killed at 83.733 ms CPU | Killed at 87.016 ms CPU |
| Continuous RT execution | Killed at 84.392 ms CPU | Killed at 99.722 ms CPU |

These physical Pico results reproduce the class-change bug and verify its
blocking-wake correction while retaining nonblocking enforcement. They do not
claim precise wall-clock enforcement from the kernel's sampled tick accounting.
The baseline's collection-wrapper errors and recovered results are preserved in
`output/pico-rttime-kernel-20261025-v1/baseline/`; hashes, firmware readbacks and
muted offline stock recovery are checked independently.

The corrected kernel retains the baseline configuration and exported module
CRCs. Its Image SHA-256 is
`b435df8b9fc5456a8726fcbfaa6202fc3636ff41781ce83f828d19626585b71a`;
the diagnostic RAM-boot container SHA-256 is
`586ffa72338bd6ced2d4ac799880fbdeebce268086418f2b2cf7746f2ef8dcb2`.
Initramfs, DTB and command line match the prior working container. The build
uses the retained native baseline plus this correction, regenerates reclaimed
build artifacts, validates the linked Image extent and restores the original
source tree. It is not a fresh build of every current profile patch.

`output/pico-callback-pool-20261025-v3/` runs those controls before the graphics
setup, retaining ordinary caller nice −20, event RR/2 and the 100 ms compositor
watchdog. An initial private launch guard expected 32 setup steps; the added
regression makes 33. That guard is corrected before graphics starts in the same
boot. The compositor survives until normal cleanup; 30/30 scanout samples are
valid and include 13 sampled framebuffer changes. No compositor watchdog kill
is recorded.

The combined run nevertheless fails before steady timing windows. The camera
sequence guard receives camera 1 frame 1901 while older frame 1899 still lacks
that camera, then invalidates capture. Feed timeout and tracking shutdown follow.
The guard correctly refuses a missing per-camera frame; increasing reorder
capacity alone does not address this condition. The source of that gap remains
under investigation. No new pacing or tracked-controller acceptance is claimed.

The 8,343,706-byte export contains 173 verified data members plus its manifest,
SHA-256 `7150ba3389162d9037218b88488e4fe5101dcf4221d958910cf55ce9c4ade4e1`.
Source/member hashes, full BOOT/DTBO readbacks, GPU/workqueue restoration,
MCU/DSP shutdown, muted offline stock return and owned USB host exit verify.

### Post-dashboard renderer scheduling (2026-10-25/26)

`output/pico-camera-gap-20261025-v1/` completes 180 seconds with 4,499 complete
camera sets and 182,232 confident head outputs, without a bad SLAM result. A
private bounded camera journal and camera-task scheduler selection add failure
coverage. No refusal occurs and no journal is dumped; this does not establish
that the preceding camera gap is fixed. The deployed diagnostic source closure,
trace bytes and cleanup verify.

Ordinary caller nice −20 still has 40/26/22/23 reported drops and three age
queries above the unchanged 22.222 ms bound. Of 111 contained DRM misses, 87
overlap more than 1 ms of renderer runnable delay between the prior flip and
next GPU queue; 72 include that delay before the previous wait returns. Four
fence-late misses also have callback dispatch tails above 1 ms. This supports a
post-startup scheduling comparison, without assigning all misses to one cause.

`output/pico-render-post-ui-20261025-v1/` changes the renderer policy only after
the dashboard is visible and scanout/tracking checks pass. Affinity, nice −20,
event RR/2, API-worker nice −20, GPU configuration, camera journal and observer
presence remain fixed. The ordinary/RR2/RR2/ordinary windows give:

| Measurement | Ordinary | RR/2 | RR/2 | Ordinary |
| --- | ---: | ---: | ---: | ---: |
| Reported history drops | 35 | 3 | 1 | 26 |
| Contained DRM skips | 35 | 2 | 1 | 27 |
| Frame interval p99 | 22.252 ms | 11.281 ms | 11.266 ms | 22.230 ms |
| Renderer runnable interval p99 | 1.274 ms | 0.325 ms | 0.344 ms | 1.044 ms |
| Overdue age queries | 1 | 0 | 0 | 1 |

History snapshots and fully contained DRM pairs use different observation
boundaries. GPU medians stay near 7.19–7.27 ms. CFS scheduler traces include
brief kernel priority boosts; RR windows consistently show priority 97. One
on-time stub fence has no GPU-command identity and remains explicitly
unclassified. Its failed original parser result is retained. No missed frame
is discarded to make the comparison pass.

The startup collector now enables/expands syscall exits before entries. This
avoids creating an entry-only setup window; initial unmatched exits remain
explicit boundary observations. Strict selected-renderer and API-worker futex
parsers pass in this comparison. The earlier capture's failed pairing result
remains retained.

[`pico-steamvr-render-priority.py`](../tools/pico-steamvr-render-priority.py)
provides the measured policy as an explicit, bounded context or CLI. It requires
the selected native Neo3 boot, UID-1000 compositor service and RenderThread,
matching process/thread start identities, ordinary nice −20, RTPRIO 2 and the
existing 100,000 µs soft/hard RT limit. A private root-owned readiness JSON must
match that GPU-submitter identity, the visible `valve.steam.gamepadui.main`
dashboard and an observation within 120 seconds. This is an assertion by the
owning validated session; the helper does not independently query SteamVR or
identify a GPU submitter from its thread name. It adds no default activation.

The helper requests RR/2 with reset-on-fork and accepts the driver's observed
loss of that bit. It preserves limits, niceness and affinity. Normal exit,
handled SIGTERM/SIGINT and Python failures restore the original policy; changed
identity or unexpected live state refuses a restoration write. An exited task
needs none. These checks are not atomic TID-reuse protection.

```sh
python3 tools/pico-steamvr-render-priority.py \
  --boot-serial DEVICE_BOOT_SERIAL --boot-id CURRENT_BOOT_UUID \
  --pid COMPOSITOR_PID --tid GPU_SUBMITTER_TID \
  --ready-json /run/pico-controller-owned-test/renderer-ready.json --seconds 300
```

Seventeen focused host tests pass. `output/pico-render-helper-20261026-v1/`
then deploys the exact maintained source and repeats the matched workload.
Both actual helper contexts restore their complete snapshots exactly, including
affinity and limits; RR/2 readback exercises both reset-bit forms. The repeated
history drops are 37/3/2/26, contained DRM skips 35/4/2/24 and interval p99
22.257/11.345/11.299/22.237 ms. Three overdue age queries occur in the first
ordinary window and none in the RR windows. All 4,499 camera sets complete,
the four default cross-exec GPU interop cases pass, and no compositor watchdog
kill occurs. Rare RR misses, broader application/shader workloads, physical
latency and lens clarity remain separate acceptance work.

Both comparisons verify source/member hashes, full traces without recorded
loss, original renderer restoration, GPU/workqueue restoration, MCU/DSP
shutdown, full BOOT/DTBO readbacks and muted offline stock return. Their exports
are 43,119,665 bytes, SHA-256
`ffdfafb6d7aaf54b41adddbaf0c1f67d1eaaecf8660b46527fc5fa73ee4835b0`,
and 43,235,853 bytes, SHA-256
`eb040a2b71458065df5d8b1da2f7c47baf31e6d78c48912ec61a9eab6deb1598`.
Optical controller tracking is not accepted: the preceding two complete sampled
controller files cover only about 27 seconds before motion delivery stops, and
every recorded left SDK state is zero. A full head/camera run must not be
presented as 180 seconds of live controller motion or proof of producer health.

## Consumer-only motion timeout recovery (2026-10-26)

The receiver's receipt-age watchdog and the consumer's capture-age guard can
expire at different times. A consumer can latch `-ETIMEDOUT` while the receiver
remains active; later fresh input then produces no receiver STOP/RESUMED event.
The previous owner only recovered that event sequence, leaving the consumer
stopped. A deterministic host fixture reproduces this gap with capture/receipt
times separated by 20 ms. The maintained session helper now accepts the owning
consumer's generation and first monotonic failure observation, requiring fresh
post-failure receipt before requesting a new epoch. All 32 focused session tests
pass, including stale reports, protocol errors and pending restart retries.

Native boot `7e001eab-eea1-4cfe-b112-43c6889f5ab3` tests the exact maintained
helper with a private Bionic frontend that deliberately latches one timeout
after 1,500 successful IMU deliveries. This injects an owner-side error; it does
not pause the receiver, alter capture timestamps or establish the cause of the
earlier natural cutoff.

- The failure snapshot and fresh-input snapshot both show active generation 104,
  with no receiver STOP or RESUMED event. New receipt occurs after the failure.
  The healthy receiver retires generation 104 with `-ESHUTDOWN`, acknowledges
  generation 105 and retains the same worker process and shared DSP ownership.
- The new endpoint is published 34.253 ms after injection. Estimator reset and
  calibration succeed in 1.266 ms; a status with seven new deliveries is visible
  by 42.870 ms. The new epoch delivers all 12,272 published IMU samples before a
  later receive timeout. Head/world generation remains 104.
- All 2,999 camera sets complete over the 120-second capture. Head processing
  reports 123,082 callbacks, 120,779 confident results and no rejected result.
  Steam's dashboard and scanout checks pass. The single post-dashboard RR/2
  context and API-worker priority context restore their complete snapshots.

The later cutoff remains unresolved: the consumer again expires, the receiver
then records `-ETIMEDOUT` with 12,272 samples, and the final channel is inactive
without a fresh-resumption event. No restart is attempted without fresh data.
Worker exit 1 records that timeout; RPC close results are zero, SLPI goes offline
before buffer release, and MCU references return to zero. This proves a separate
source stoppage in this run, not its cause or controller sleep. The complete
sampled controller file covers only 27.204 seconds; all 1,721 left SDK states are
zero. Optical pointing and physical controller tracking remain unaccepted.

Evidence is `output/pico-consumer-recovery-20261026-v1/`. Its export contains
226 verified members, 33,618,187 bytes, SHA-256
`aa24eae75178e4ba82b6538e0ce9ccbc43f98e8753d04b5ed6ac442dec4704b5`,
including worker status logs, before/after process and channel snapshots, the
actual session helper and the consumer's complete 110-file compiled source
closure. Full traces have no recorded loss; scheduler enforcement controls,
full BOOT/DTBO readbacks and muted offline stock return pass. No firmware was
flashed and no lens or physical-motion acceptance is inferred.

## Camera request assignment gap before timing comparison (2026-10-26)

Boot `053c9729-1159-4d1b-83a2-efe2c8427e12` attempts a fixed-RR/2 observer
on/off/on comparison, but stops before dashboard readiness. No measurement
window, renderer RR context or API-worker priority context starts; this run
provides no observer or pacing comparison. The camera completes 934 head sets
before its unchanged incomplete-set guard rejects frame 1875, with pending
frames 1873/1875 and masks 3/1. SLAM subsequently returns `-ETIMEDOUT`, with no
rejected head result.

The captured failure journal records request assignment before the missing
image: physical cameras 0 and 1 receive frame-1873 SOFs with request ID zero;
cameras 2 and 3 receive that frame with request 1870 and deliver head-class
headers. Cameras 0 and 1 instead receive request 1870 on frame 1874 and deliver
controller-class headers. Header decoding agrees with classification, and the
retained event suffix has no observed CRM/sync sequence discontinuity. A later
frame-1875 head image therefore encounters the incomplete frame-1873 set.
This establishes asymmetric frame/request assignment. The driver reason for
request ID zero is unproven; request-submit ioctl boundaries and driver
application decisions need measurement before changing queue depth, scheduling
or the guard.

Evidence is `output/pico-observer-contention-20261026-v1/`; offline decoding is
under `output/pico-camera-gap-20261026-v1/`. The complete journal is 1,126,716
bytes, SHA-256 `845d71d0e821da71833a1236ac72240eb2cb7b9ff3eb8dc4c9c0076a6d6e16a8`.
The 9,428,431-byte export has 182 verified members, SHA-256
`a4003af3ac7ef65ce0b3860512e4ccf9e48ec7aa1a68023007d5b3b1a996547f`.
Source/trace integrity, all 33 setup steps, firmware readbacks, MCU/DSP shutdown
and muted offline stock return pass. Worker release 1 and diagnostic-probe
termination by SIGTERM remain explicit cleanup results of this failed run.

## Capture refill headroom under Steam startup load (2026-10-26)

The next native trace separates submission from deferred CRM readiness.
SCHED_REQ followed by sensor and IFE configure is valid for this driver: CRM
creates the slot synchronously before device add-request callbacks look it up.
Both device pipeline delays are one. Request ID zero alone does not establish
an empty queue; several RDI IRQ states can report it. The captured IRQ order
is normal SOF-before-RUP, with no RUP-before-SOF anomaly.

In control boot `5af8bdab-c337-4ee5-b66e-2dedefa00c97`, physical cameras 2/3
finish request-1895 IFE configuration at 160.030962229/160.031011500 seconds.
The relevant SOF/RUP handling follows around 160.032 seconds, but their deferred
readiness callbacks run at 160.034519/160.034538. The first CRM worker spends
3.613 ms runnable before executing. Its FIFO drain, including the queued
trigger, ends eight microseconds before peer readiness is processed. The pair
applies request 1895 one trigger later, producing the incomplete head frame 1897.
The source's peer-not-ready synchronization skip explains this ordering; that
specific branch is source-derived, not directly logged. No submit-order,
synchronization or missing-frame guard change is justified.

The capture loop also loses substantial refill time while runnable under its
ordinary nice-zero policy. The owning session now has an explicit
[`pico-camera-priority.py`](../tools/pico-camera-priority.py) context to select
ordinary CFS nice −20 for this capture task. It checks the native boot, exact
root-owned executable bytes, single main thread, command and service identity.
Only niceness changes; policy, affinity and resource limits remain identical.
Exit restores the original value for an unchanged live task. A reaped task needs
no write; unexpected state refuses restoration. Proc checks are not atomic PID
reuse protection. The helper adds no default activation. Thirteen host tests
cover binding refusals, activation failures, exceptions, state drift and cleanup.

Boot `dfb4755b-bee0-40b5-8322-42a0df8459bd` runs the exact maintained helper,
SHA-256 `73ff54f57ecb32c7615749c98fb1faa5f363f0705dad901218f1048b971287b3`.
The camera executable is unchanged from control, SHA-256
`4598e0109e1ad8287b00f320b4c95c0de9d8f8cf87766394877ac3c15e633970`.
Kernel, workload, diagnostic instrumentation and other priority settings are
unchanged. The helper verifies nice 0→−20 with identical policy, affinity and
limits; the caller reaps the capture before context exit. Cleanup has no error.

Paired readiness headroom is measured before the first expected trigger after
the preceding request's application, so a delayed application cannot inflate it:

| Camera pair | Control minimum | Nice −20 minimum | Treatment skipped triggers |
| --- | ---: | ---: | ---: |
| 0/1 | 2.388 ms | 79.699 ms | 0 |
| 2/3 | −2.584 ms | 90.282 ms | 0 |

The treatment covers 8,990 complete requests per pair. All 35,992 checked
frame/request associations across frames 3–9000 match, with no mixed request-zero
frame. The sole all-zero frame is the startup frame 2. All 4,499 head-camera sets
complete over 180 seconds, with 184,546 head callbacks, 182,298 confident results
and no rejected result. In the same logged frame-10–1900 cohorts, sampled camera
delivery-age p99 falls from 106.988 to 22.057 ms. These are camera delivery ages,
not a complete head-pose age distribution or physical display latency.

This fixes the observed refill-headroom failure in the tested startup workload;
broader load and longer-duration acceptance remain separate. The four display
windows still report overlapping history drops 36/3/4/17, contained native skips
31/3/3/19 and vsync-age faults 1/0/0/0 for OTHER/RR2/RR2/OTHER. No optical controller
pose is accepted. Its receiver delivers 13,951 motion samples, then times
out; subsequent activity reports stay unchanged. Neither a controller sleep state
nor the cause of that receive stoppage is established.

Evidence: `output/pico-camera-request-trace-20261026-v1/` and
`output/pico-camera-priority-20261026-v1/`, including the pinned kernel audit,
request/IRQ chronology, complete traces, exact compiled sources and runtime
worker receipts. Control export: 10,639,706 bytes, 193 verified members, SHA-256
`0364e39827eb3a902981edcb9bfd5936e81f96550f88beca15e449151055594e`.
Priority export: 48,535,034 bytes, 232 verified members, SHA-256
`1bda63ec4cec969d70984865fc31015de5013d51a119f1a790b0a8eec7bb3b41`.
All trace readers join without recorded loss, helper contexts finish, full
BOOT/DTBO readbacks match, MCU/DSP ownership shuts down and muted offline stock
return is verified. No firmware was flashed.

### Separate stale-head failure with lighter camera tracing (2026-10-26)

Boot `487c748e-0b76-419e-a99a-32c3efd2b5bd` keeps the verified capture nice −20
context but uses the earlier camera executable without the additional ioctl-phase
recorder or separate camera kernel trace. It also adds bounded controller RX
metadata. This is not an identical-workload replication of the preceding success.
It ends before the planned observer on/off/on windows; no pacing comparison is
available.

The first recorded rejection is a head result timestamped 159.870374093 seconds,
read at 159.999561709–159.999563688 seconds: its age is 129.189595 ms, while the
result read itself takes 1.979 microseconds. The controller head-history consumer
stops 0.901250 ms after that read returns, and the feed reports cancellation
4.286719 ms after the return. Only then, 349.962135 ms after the read returns,
does capture refuse
`head-ring-full` at frame 1915. Its eight-set ring contains 956 published and
948 consumed sets. The terminal camera counts agree across all four cameras;
this is not another recorded request-assignment refusal.

The existing CPU trace selects capture, renderer and GPU workers, but not the
tracking consumer or IMU reader. Incidental consumer events cannot reconstruct
the complete interval. Thus 129.189595 ms is a result age, not a proven scheduler
stall or algorithm-call duration. The next diagnostic must cover those tasks
before changing their priorities. Freshness and incomplete-frame guards remain
unchanged.

Evidence is `output/pico-observer-camera-priority-20261026-v1/`, including the
ordered failure timeline and controller RX analysis. The 9,587,187-byte export
has 189 verified members, SHA-256
`0e7abe9c05d9364c8c86a151fa2895c5efb2fd26dfd9333d93fb3c6d068dc2bd`.
Both trace readers join without recorded loss, capture priority cleanup succeeds,
and full BOOT/DTBO readbacks, MCU/DSP shutdown, muted offline stock return and
owned USB-host termination verify. Failed tracking is not accepted as a usable
VR session.

### IMU reader scheduling delay during Steam startup (2026-10-26)

The next diagnostic keeps the application and policies unchanged and adds static,
identity-bound scheduler coverage for the existing tracking consumer, its SDK
threads and the native IMU producer. Process start times, executable bytes,
consumer program mappings, task policies and initial filters are retained.
Coverage starts before GUI load; later-created or transient threads are not
claimed, and the added tracing has measurement overhead.

Boot `f321ff38-602c-4016-ac22-e40156091d35` reproduces the stale result with
timestamp 161.381570395 seconds. `get_result` runs at
161.514119625–161.514120771 seconds, taking 1.146 microseconds; the returned
result's age is 132.550376 ms. The following table covers the distinct interval
from that input timestamp to the beginning of the result read, 132.549230 ms:

| Selected task | Running | Runnable, awaiting CPU | Blocked |
| --- | ---: | ---: | ---: |
| Consumer main, TID 1944 | 12.575625 ms | 47.996000 ms | 71.977605 ms |
| SSC IMU reader, TID 1940 | 5.787625 ms | 126.761605 ms | 0 ms |

These tasks have complete scheduler state coverage for this interval. Clipped to
the cohort boundaries, the SSC reader's runnable spans are 64.302, 43.976 and
18.483605 ms.
It is ordinary CFS nice zero; the trace therefore establishes substantial reader
scheduling delay, rather than a 132 ms result-read call. It does not prove that
reader scheduling explains every part of the result age or every pacing fault.
The callback/feed guard again stops the session before the observer windows;
the subsequent camera-ring overflow is not request-assignment acceptance or a
pacing comparison.

Evidence is `output/pico-tracking-consumption-20261026-v1/`. The 13,469,760-byte
export has 193 verified members, SHA-256
`85c5bd6a98973700e7da8b02966d50d2444c440007619fcad603fa415ad34189`.
The full 90,478,963-byte CPU trace has no recorded loss. Source, selection,
capture-priority cleanup, both firmware readbacks and muted offline stock return
verify. No scheduling or freshness change was made in this diagnostic.

The opt-in [`pico-imu-priority.py`](../tools/pico-imu-priority.py) context addresses
the measured reader delay by changing only the existing `ssc-imu` thread from
ordinary CFS nice 0 to −20. It requires explicit native serial, boot UUID,
producer PID, reader TID and executable SHA-256. It binds the exact root-owned
producer command and service, the unique reader's membership and start identity,
and every existing producer thread's scheduler state. Only the reader's nice
value may differ on activation; policies, real-time priorities, affinities, limits and
other threads stay unchanged. Cleanup restores the original value for an
unchanged live target, skips writes to an exited owned target and refuses
unexpected drift. Proc checks do not make PID/TID reuse atomic.

There is no default activation, real-time promotion, SDK-thread selection or
freshness relaxation. Fifteen host tests cover actual proc fixtures, explicit
target refusals, other-thread preservation, partial activation/readback errors,
identity drift, lock overlap, exited readers with live parents, zombies, CLI
bounds and signal cleanup.

The reader-only treatment, boot `d912eeae-96a8-4432-89f0-c3f78330d472`, uses the
exact maintained helper, SHA-256
`d23995be9ed6baeb0dde6439250f318e49abc92469ea959e48a7a1500f78e1f6`.
Application, kernel, camera priority, task-selection helper and observer workload
match the preceding diagnostic. Native before/active snapshots verify that only
reader TID 1934 changes nice 0→−20; the other three producer tasks and every
recorded policy, real-time priority, affinity and limit match. The producer exits
zero and is reaped before context cleanup, which records `owned-producer-exited`
without writing to an expired identity. Cleanup errors are empty.

The bounded workload completes in 181.051521858 seconds: all 4,498 head-camera
sets are consumed, 184,449 head callbacks produce 182,215 confident results with
zero rejected result, and the IMU ring ends without failure. Both observed
20-second SteamVR windows have 2,000 valid head queries, zero invalid queries and
zero vsync-age faults. The observer-free window intentionally makes no API
acceptance claim. This verifies the reader adjustment through the previously
failing startup and this complete workload; it does not establish a universal
scheduling fix or physical motion-to-photon latency.

The separate complete, loss-free DRM trace measures these contained flip pairs:

| Observer | Pairs | Missed presentations | Flip interval p99 |
| --- | ---: | ---: | ---: |
| On, first window | 1,793 | 2 | 11.459739 ms |
| Off | 1,795 | 3 | 11.489948 ms |
| On, final window | 1,790 | 5 | 11.475885 ms |

Frame pacing remains unfinished. The first on/off pair supplies no reduction in
misses when the observer is removed, and the third window is not a controlled
reversal: the CPU trace reader exhausts its 384 MiB budget, with its last retained
event at 239.615467 seconds inside that window. That timestamp is not a measured
reader-exit time. Final CPU overrun counters are nonzero and one retained row has
an unexpected event format. The CPU recording is therefore rejected for precise
IPC or scheduler comparisons; its gaps are not silently parsed around. Complete
DRM/present evidence and workload acceptance remain separate from that failed
CPU diagnostic. The first two windows precede the last retained CPU event, but
this does not establish loss-free CPU coverage for them.

The first early dashboard probe exits 9 before successful readiness; the later
readiness probe, early/late scanout captures and live server/compositor checks
pass. There is no new lens check. Controller optical publication remains zero:
13,744 motion samples are followed by a receive timeout, and sampled mailbox
contents then remain unchanged for 150.879 seconds despite 109,198 further
polls. No fresh-input recovery or controller-sleep explanation is established.

Evidence is `output/pico-imu-priority-20261026-v1/` and the separate RX analysis
under `output/pico-controller-rx-metadata-20261026-v1/analysis/`. The
52,944,965-byte export has 234 verified members, SHA-256
`63d5ad471afa781ada21f4b6631f67c6d80cd85456b8e7acf327b2848226954b`.
All source/build bindings, full BOOT/DTBO readbacks, MCU/DSP shutdown, muted
offline stock return and owned USB-host termination verify. No firmware was
flashed. The accepted scope is full workload and DRM evidence with a partial,
unaccepted CPU diagnostic, not an end-to-end tracked-controller session.

### Bounded steady tracing and remaining deadline boundaries (2026-10-26)

The next private profile separates a small queued-event-only GPU identity trace
from the steady CPU trace. It drains and joins the identity reader before GUI
startup, keeps CPU tracing off through startup, then records only the three
measurement windows. Selection includes the exact display commit worker and
critical tracking tasks; other SDK task identities remain snapshot-only.
The explicit tracer is `nop`. This repairs the previous capture-budget problem
without increasing its 384 MiB cap or changing rendering/scheduling policy.

Its first run, boot `61de562e-9300-4e16-b143-3de793366017`, stops before the
windows with camera I/O error −5. The consumer has 39,354 callbacks, 954 camera
sets and no rejected head result. Kernel logs show request 1909 in the RDI
bubble path on ISP contexts 1/3, followed by the branch that calls error-fence
signaling. That does not establish signal delivery, physical camera mapping or
the first userspace failure. The private caller only dumped its bounded camera
journal on a frame-callback refusal, leaving this lower-layer failure without
a journal. Source/cleanup, both firmware readbacks and quiet stock return verify.
Its 5,761,002-byte, 200-member export has SHA-256
`9739b811adb06c7c6c284069900b49742df4e3d155878810094dda9e5391543c`.

The repeat adds only `camera_gap_dump("loop-end", clock_now())` after the capture
loop and before exposure readbacks. Registered snapshot owners are still alive;
the existing idempotent dump preserves an earlier first refusal if one exists.
No camera gate, queue, timeout or recovery policy changes. Boot
`873f6700-376b-496b-a2ca-e76c137103e6` completes 4,499 head-camera sets and
184,609 callbacks with zero bad results. Its successful terminal journal does
not explain the preceding intermittent bubble. Both measured OpenVR windows
return 2,000 valid head/vsync queries with zero age faults; the off window has
no API measurement. Audio remains off.

The identity trace is 142,162 bytes and the steady trace 237,070,570 bytes over
68.3 seconds; both readers join without errors, cleanup failures or loss-counter
increments. However, CPU row 449,380 has malformed event formatting. A later
DRM row also has unknown event formatting. Full-stream grammar acceptance is
rejected. The analysis instead verifies explicit clean prefixes, without
repairing either row or carrying scheduler state through them. The CPU prefix
ends before 197.751152 seconds; the DRM prefix extends beyond all three windows.
Cross-CPU text merge inversions are retained and handled using timestamps and
per-CPU ordering, not mistaken for event loss.

The verified DRM prefix measures 4/3/1 missed presentations. Only the first
16.059-second on-cohort has clean CPU coverage. Its four missed presents have
complete GPU/callback chains. The commit worker is FIFO/99 on CPU 7; its
181–263 microseconds from fence return to kickoff are entirely running, with no
recorded runnable or blocked time. Those intervals do not support increasing
commit-worker priority. Callback queue-to-execution times for these frames are
39–366 microseconds. Two callbacks share each context/timestamp; this is not
proof of duplicate work or of which callback signals the selected DRM fence.
The 170 contained shared-IPC waits have maximum 0.484 ms. The earlier 8.605 ms
tail does not reproduce in this short cohort; it is not declared eliminated.

Evidence and exact prefix hashes are under
`output/pico-camera-terminal-20261026-v1/analysis/`. The source audit and earlier
complete DRM boundary analysis are under
`output/pico-display-deadlines-20261026-v1/`. The repeat export has 245 verified
members, 38,499,674 bytes, SHA-256
`90a5be869fb0d2a0aef93525cfb73090b61b7a8216d09c4c41152ffa890d23a3`.
Source/build bindings, priority restoration, MCU/DSP shutdown, full BOOT/DTBO
readbacks, muted offline stock return and owned host termination verify. No
firmware was flashed. Optical controller publication remains zero.

### Reusing exported queue completions (2026-10-26)

The source audit finds that the DRM bridge already exports one GPU completion
for all signals in a submission. The redundant export instead occurs when an
ensuing empty submission reconstructs that same queue timestamp. Patch 0021
retains one owned completion descriptor per queue and preserves every explicit
wait; [rendering notes](pico-rendering.md#gpu-completion-reuse) describe its
lifecycle and fallback. Native callback counts below are observed events, not
direct counts of registration ioctls.

The composed fixture executes the actual native submission, DRM bridge,
merge/export and queue lifecycle functions with modeled GPU/DRM primitives.
Baseline and corrected candidate each pass 399 ownership cases and 54 real
`RLIMIT_NOFILE` cases. The candidate avoids an extra no-signal duplication,
moves its private FD completion, and can retry a failed cached merge once using
the original timestamp. Tests preserve dependencies under failures and compare
equal free descriptor headroom; the cache still intentionally owns one extra
resident descriptor per queue. All seven focused Linux suites pass. The
retained-source incremental build verifies all 21 ordered patches and 14
patched targets; this is not a fresh full-image build.

The initial candidate in `output/pico-completion-cache-20261026-v1/` completes
4,499 head-camera sets and 184,576 callbacks with zero bad results. All 1,184
source, workload and recovery checks pass. Both CPU and DRM traces are complete,
with accepted grammar and zero loss. Matched first-on 16.059172435-second
cohorts contain 1,437 renderer commands/2,874 callbacks in the preceding baseline
and 1,439/1,439 in this candidate. Every complete candidate command cohort has
one callback per context/timestamp, compared with two in that baseline.

Its on/off/on windows have 2/0/0 missed presentations versus the preceding
baseline's 4/3/1. This is a single-run descriptive comparison. One remaining
miss has 1.349 ms from callback queueing to execution, including 1.143 ms of
executor runnable time. The selected scheduler trace cannot attribute all that
time to the task seen preempting it. Neither missed frame has a scheduling gap
after fence return and before kickoff. Shared IPC waits peak at 0.442 ms in the
three windows; the earlier 8.6 ms tail is not declared eliminated.

The corrected library, SHA-256
`1c8a5a834f92f1a0bb39a7b040075924dbf91baea418202e86827f93b8d1453b`,
is first tested in `output/pico-completion-cache-20261026-v2/`. It passes the four
cross-exec checks and reaches SteamVR, but the renderer-priority helper rejects
its immediate policy/identity readback before the measurement windows. Its
original error omits the compared states, so the mismatching field is unknown.
Subsequent feed cancellation and camera ring exhaustion follow harness shutdown;
they are not established independent failures or a cache synchronization cause.
This run is retained as partial evidence, without full-workload acceptance.
The maintained helper now includes both snapshots on that failed comparison;
its guards, scheduling and restoration are unchanged, and 18 focused tests pass.

The diagnostic-only repeat in `output/pico-completion-cache-20261026-v3/`, boot
`b1fd1d63-2801-4537-a6fb-73c49e9ee30f`, uses that same corrected library and
completes the 181.012-second head/camera workload: 4,498 sets, 184,562 callbacks,
182,256 confident outputs and zero bad results. All four cross-exec checks and
1,186 source, workload and recovery checks pass. Both measured OpenVR windows
have 2,000 valid head queries and 2,000 vsync queries without age faults. The
observer-free window makes no API acceptance claim. The earlier dashboard probe
still has one overdue vsync out of 500 queries, before successful readiness;
startup timing is not declared fixed.

The complete, loss-free DRM recording measures:

| Observer | Contained flip pairs | Missed presentations | Flip interval p99 |
| --- | ---: | ---: | ---: |
| On | 1,795 | 0 | 11.441563 ms |
| Off | 1,795 | 0 | 11.466615 ms |
| On | 1,795 | 0 | 11.472865 ms |

These are bounded native windows, not sustained or through-lens pacing
acceptance. CPU row 606,075 has unknown event formatting, so the full CPU stream
is rejected despite zero loss counters. Its explicit clean prefix ends before
205.519800 seconds. The first on-window contains 1,795 renderer commands and
1,795 callbacks; only 87.197735 ms of the off window and none of the final window
have accepted CPU coverage. No causal scheduler comparison spans all three.
The 16.059172435-second matched cohort contains 1,442 commands/1,442 callbacks,
confirming the callback reduction in the final build.

The renderer-priority failure did not recur in v3. Pinned Pico sources show that a
normal GPU submission can temporarily promote its submitting thread to FIFO40
and restore its saved policy. A race with the external RR2 setter is therefore
source-supported, but v2's missing readback states prevent assigning that cause
to its failure. No priority guard is relaxed and no new policy fix is claimed.

Controller receive still times out after 13,794 motion samples; public optical
confidence and publication remain zero. The later worker exit 1 reflects its
retained motion error, also present in the baseline, rather than successful
controller acceptance. Stop RPC results are zero, MCU references reach zero,
and required SLPI/CDSP states 7/3 are OFFLINE. Subsystem 2 is only OFFLINING in
the saved snapshot; complete shutdown of every DSP is not claimed.

The v3 export has 254 verified members, 37,697,273 bytes, SHA-256
`9ba9681a7b8a9100b5243fab06668cc3a94923a0124a3e285f49b12ee554a071`.
Exact source/build and both deployed ICD-path hashes, restoration of owned
priority/GPU settings, full BOOT/DTBO readbacks, muted offline stock return and
owned host termination verify. No firmware was flashed and no new lens or
physical motion acceptance was collected. Analysis receipts preserve all three
runs, the failed v2 entry and the rejected CPU suffix.

### Startup counter publication gap (2026-10-26)

The retained v3 startup fault is outside its three clean measurement windows.
Probe sample 69 reports counter 3025 with age 25.805313 ms, while both bracketing
kernel reads are only 3.5462–3.5467 ms old. Its logged API interval is 469 ns.
The complete DRM trace advances through sequences 3026 and 3027 in that gap.

WSI traces bind the timing queries to the actual RenderThread: its paired
counter update remains at 3025 for 33.388594 ms, until the query after the next
completed present returns 3028. The previous counter-to-next-queue interval is
18.297187 ms; that queue arrives after 3026, and its fence returns after 3027.
Its flip therefore skips two refresh sequences. The exact compiled Pico driver
has a pose worker but no vblank polling worker or `VsyncEvent` call to adjust.

This localizes the stale timing publication without identifying the work that
delayed submission. CPU/GPU scheduler tracing was off during this startup
interval, so running, runnable, IPC and GPU/callback causes are not separated.
No timing bound is relaxed. The next useful capture is the existing selected
renderer/event/commit and futex trace limited to the first 500-sample dashboard
probe, with no additional API client or scheduling change. Exact raw rows,
hashes and source-ownership limits are in
`output/pico-completion-cache-20261026-v3/analysis/startup-vsync-analysis.json`.

### Startup renderer CPU work (2026-10-26)

The follow-up in `output/pico-startup-counter-20261026-v1/` adds a bounded CPU
trace around attempt 0 of the existing 500-sample dashboard probe. It preserves
the Mesa library, 33 setup recipes, application commands and scheduling policy.
It adds no API client. Trace-enable/filter states are restored exactly before
the later measurement windows. The extra capture has measurement overhead;
this is an attribution diagnostic, not a clean performance comparison.

All four overdue samples, 117–120, share one stale-counter interval, 3028→3034.
Their API calls take 1.510–2.864 µs while the kernel vblank ages remain
4.53–6.61 ms. The previous counter update to next present queue takes
52.071302 ms. Over that interval the CFS nice −20 renderer runs for
50.732302 ms, is runnable for 1.339 ms and has zero blocked or unknown time.
Its seven traced futex calls are wake operations. This establishes predominantly
on-CPU work before queueing; no additional priority change is justified.

The matching GPU command queues approximately 51.804 ms after the old counter
update, then submits, retires and fires its completion callback. The callback's
queue-to-execution interval is 114 µs. Four refresh boundaries pass before the
present queue and a fifth during its fence wait; present 2860 flips at sequence
3034. The complete startup probe contains 486 flip pairs, 17 missed
presentations and 21 skipped DRM sequences. The four overdue API samples
describe one of those gaps, not four independent stalls.

No callstack was captured. Running time does not distinguish compilation,
command preparation, spinning or other synchronous work. Facet pipeline-creation
messages are retained, but their realtime log timestamps lack a precise saved
monotonic calibration. The 189 restored cache files also do not establish hits.
The retained Turnip entry headers use driver ID
`270e6a677076a7f92882e477e70268da`; the same library build's Steam Vulkan-query
bucket uses `d9efc6cf789056ddd14fc6e7875bcc48`. That is a namespace mismatch for
the query process, not a directly observed compositor UUID. A cache comparison
must preserve the exact library and actual cache environment; rewriting cache
keys or headers would not establish compatibility.

The complete short CPU trace is 17,702,492 bytes, SHA-256
`ba7eef869aaea0dded6447c3987ce20880c09a9397670f3f454765d34416b1f2`.
It and the full 31,176,835-byte DRM trace pass grammar and loss checks. The later
steady CPU stream contains `Unknown type 56` at row 172,725 and is rejected.
The independent complete DRM stream measures 5/0/2 missed presentations across
1,792/1,794/1,793 contained flip pairs in the on/off/on windows; there is no
accepted steady CPU/IPC comparison across those windows.

The full workload completes 4,499 camera sets and 184,579 head callbacks with
zero bad results. Controller motion still ends with `-110` after 13,784 samples,
and its worker exits 1; optical acquisition and pointing remain open. All four
cross-exec cases, exact source/library deployment, priority restoration,
BOOT/DTBO readbacks, muted offline stock return and owned USB-host join verify.
The archive has 261 verified data files plus its manifest, 39,246,031 bytes,
SHA-256 `36e063381a19b8c3b7d47ec38ed19b16a4f227f07bd75933d6ff25692a34581e`.
The 1,208-check receipt and raw-row attribution remain in its private `analysis/`
directory. No new physical clarity, motion or controller acceptance follows.

### Build-matched cache control (2026-10-26)

`output/pico-cache-harvest-20261026-v1/` preserves the same workload and collects
the cache only after all seven owned VR units become inactive with zero PIDs.
The complete snapshot contains 354 files: the original 189 entries and 165 new
Turnip entries in namespace `d9efc6cf789056ddd14fc6e7875bcc48`. The verified
2,557,983-byte carrier has SHA-256
`950dd659496104645f8f242983fa9a05fa0c86f48c9341bccf3d04f7e5c67333`.

`output/pico-cache-warm-20261026-v1/` restores every file literally before
tracking/VR starts. Native readback verifies all 354 hashes, UID/GID 1000,
file/directory modes 0600/0700, the unchanged Mesa library/build ID and all
13 recorded compositor cache/driver environment values. It preserves all
33 recipes, application commands, policies and measurement scopes. No cache
key or header is rewritten. The original carrier remains retained.

| Existing startup probe | Original 189-entry restore | Build-matched 354-entry restore |
| --- | ---: | ---: |
| Overdue vsync reads out of 500 | 4 | 0 |
| Counter-to-queue maximum | 47.652813 ms | 6.587291 ms |
| Counter-to-queue p99 | 5.125677 ms | 2.740573 ms |
| Contained counter-to-queue intervals | 475 | 478 |
| Contained flip pairs | 474 | 477 |
| Missed presentations / skipped sequences | 14 / 18 | 4 / 4 |
| Later on/off/on missed presentations | 4 / 0 / 0 | 0 / 1 / 1 |

The cold maximum contains 45.944813 ms of renderer running time; that long
on-CPU gap is absent from the warm cohort. Its maximum instead contains
1.314291 ms running and 5.273 ms runnable. This single sequential comparison
supports a cache-related startup effect, without proving cache hits, a specific
compilation function or a universal pacing fix. The post-run warm snapshot has
no added, missing or byte-changed cache files. Both later on-window probes have
2,000 valid head and vsync queries with zero age faults; off-window API behavior
is unmeasured.

The cold run's full CPU trace independently associates two late frames with
callback queue-to-execution delays of 1.681/3.300 ms, predominantly runnable time.
No complete shared IPC wait overlaps the four late-frame prequeue intervals.
The warm full steady CPU stream is rejected at row 1,007,698; its independently
qualified prefix covers only the first on window. Both remaining warm misses
occur after that cutoff, so their causes remain unassigned. The pinned kernel
source also shows that ordinary timestamp waits use the same event workqueue
and do not replace merged/imported DRM-fence dependencies; no kernel bypass or
new priority policy is justified by this comparison.

The warm head/camera workload completes 4,499 sets and 184,505 callbacks with
zero bad results. Controller motion still ends with `-110` after 13,790 samples
and worker exit 1. Input, source, cleanup, full BOOT/DTBO readbacks, quiet offline
stock return and owned USB-host closure verify. The warm archive has 290 data
files plus its manifest, 44,348,345 bytes, SHA-256
`f09178511618e36f0d2cfa55200284792748bc04489ea78979cda27a69029e7c`.
Its private `analysis/` directory retains the comparison and acceptance limits;
the callback source audit is `output/pico-callback-context-audit-20261026-v1/`.

### Independent timing windows (2026-10-26)

`output/pico-window-traces-20261026-v2/` captures each existing 20-second
on/off/on CPU window separately, preserving the workload, cache, application
commands and policies. The complete trace-enable/filter map is restored after
each joined reader. An initial v1 harness incorrectly requires every disabled
event to read `0`; the existing fatal-signal stacktrace trigger reads `0*`.
Pinned kernel source confirms that soft-disabled state. v2 preserves only that
exact trigger, with its receipt/expression/readbacks, and rejects other marker
or filter drift. All three restorations pass natively. Capture setup costs
approximately 0.24–0.26 seconds and finish/restoration 1.15–1.47 seconds per
window, outside the measurement cohorts; this is not a clean performance
comparison with the preceding continuous trace.

The full workload completes 4,499 camera sets and 184,526 head callbacks with
zero bad results. Both later on-window API probes have 2,000 valid head/vsync
queries with zero overdue reads. The earlier startup probe has one overdue
sample with a 573 ns query. Full DRM records 2/1/0 missed presentations across
1,793/1,794/1,799 contained flip pairs.

The first-on and off CPU epochs pass complete hash, grammar, loss and semantic
checks. The third contains an impossible PID/priority record and is rejected
wholly despite complete hashes and zero loss counters. The validator now uses
pinned PID/CPU/priority bounds, including the vendor's deadline-priority
encoding and workqueue special CPU values. Twenty-two fixtures exercise those
semantics. No scheduler state continues through the invalid record, and the
record alone does not establish system-memory corruption.

The three late frames have distinct qualified boundaries:

- Present 4490: its fence returns 196 µs before the next DRM trace; 206 µs of
  running commit-worker work puts kickoff 10 µs after that trace.
- Present 4975: the renderer blocks for 7.017 ms inside a 7.266 ms shared Steam
  IPC wait before GPU queueing. A wake emitter is observed, without a paired
  mapped wake or lock-owner proof. GPU retirement is already late; its completion
  callback adds only 61 µs.
- Present 6844, with the observer off: callback dispatch takes 3.521 ms,
  including 3.475 ms runnable. The executor runs on CPU 0; its fence return and
  kickoff follow the DRM boundary. The trace does not identify the task occupying
  that CPU throughout the runnable interval.

GPU retirement times use the retained clock interpolation; a DRM trace is not
the physical latch deadline. These results support separate IPC, commit-margin
and callback-placement investigations. They do not justify one universal
scheduling fix. Controller motion still ends with `-110`; optical acquisition
and physical motion acceptance remain open.

All 33 recipes, library/cache inputs, owned priority restoration, BOOT/DTBO
readbacks, quiet offline stock return and USB-host join verify. The archive has
309 data files plus its manifest, 43,250,673 bytes, SHA-256
`da6f69604ca19bfc649930ab6bb78b0e42766a3a2eb3bf605ea991eb187ae1f3`.
Its private `analysis/` directory retains the exact invalid row, semantic source
proof, individual frame chains and superseded regex-only analysis receipts.

### Optional callback affinity (2026-10-26)

`output/pico-callback-affinity-20261026-v2/` tests queue mask `f0` with the
existing nice −20 policy. Native preflight verifies all eight CPU MIDRs,
relative capacities, maximum frequencies, online/possible masks and global
workqueue mask. The active queue maps to pool 18, after original pool 16 and
intermediate nice-only pool 17. All original attributes are restored afterward;
individual worker scheduling policies and IRQ handling are not changed.

The initial v1 diagnostic stops after its first window. Its snapshot guard
incorrectly treats the complete `/proc` worker name as stable identity. Pinned
`workqueue.c` shows that these names append mutable `+desc`/`-desc` text. The
lost partial snapshot prevents identifying which field changed in that specific
failure. v2 retains raw names/stat records and compares PID, start time and the
stable pool/worker prefix; a native suffix change is retained successfully.
Its 23 private fixtures cover identity changes and restoration failures. The
maintained helper retains only the policy core, with 17 focused affinity cases
and the seven existing default/device/signal cases passing. Its core definitions
match the native-tested implementation, with the default context preserved.

The incomplete v1 CPU epoch also contains mismatched workqueue start/end
pointers and is rejected wholly for causal analysis. Its independent DRM/API
results are retained as partial evidence, without adopting its callback subset.
All three v2 CPU epochs pass full hashes, grammar, numeric bounds, loss and
scheduler/workqueue association checks. Complete before/after worker identities
and source-supported pool lifetimes also bind four trace names printed as
`<...>`. All 6,874 selected callback generations execute, fire and finish on
CPUs 4–7 in pool 18; no old-pool or unjoined generation is silently removed.

The same 33 recipes, library, warmed 354-file cache, GPU floor and three
20-second on/off/on observer calls are retained. Expanded pool filters and
passive snapshots add instrumentation overhead, so this is one sequential
experiment rather than a clean or repeated performance comparison.

| Measurement | Earlier per-window baseline | Optional affinity |
| --- | --- | --- |
| Missed presentations, on/off/on | 2 / 1 / 0 | 0 / 0 / 0 |
| Contained flip pairs | 1,793 / 1,794 / 1,799 | 1,795 / 1,797 / 1,795 |
| Queue-to-execution p99, ms | 0.514 / 0.416 / unqualified | 0.628 / 0.559 / 0.697 |
| Queue-to-execution maximum, ms | 1.665 / 3.521 / unqualified | 1.621 / 1.382 / 1.438 |

The candidate's maximum fully known runnable portions are
1.598/1.360/1.427 ms. Its p99 delays increase, so callback tails do not uniformly
improve. Both steady on-window probes have 2,000 valid head/vsync queries and
zero overdue ages; off-window API behavior is unmeasured. Startup still has
two overdue ages, 23.039270 and 22.609739 ms, with query durations of only
521 and 1,614 ns. The longest shared IPC waits are 0.740/0.445/0.453 ms;
server wake emitters still lack mapped-wake coverage and no lock owner is
established. This run does not prove the earlier IPC stall is fixed.

The full workload consumes 4,499 head-camera sets and produces 184,481 head
callbacks with zero bad results. Optical controller pose publication remains
zero and its worker ends with status 1. Real tracked pointing and physical
motion/lens acceptance remain open. The helper's `--cpu-mask f0` option is
therefore retained for further experiments, with the default mask unchanged.

All native source/cache/cleanup checks, full BOOT/DTBO readbacks, quiet offline
stock return and owned USB-host join verify. The archive has 321 data files plus
its manifest, 45,663,452 bytes, SHA-256
`087099975a832c64324f2043c25bd977d7555d5417bac74c1394cc4acda9a833`.
The private `analysis/` directory retains complete placement, pacing and
rejected-v1 evidence; `maintained-core-proof.json` binds the published policy
core to the native-tested source.

### Callback cluster comparison (2026-10-27)

A fresh `f0` control in `output/pico-frame-baseline-20261027-v2/` repeats the
preceding carrier. It records 1/2/1 missed presentations across
1,793/1,792/1,793 contained flip pairs. Thus the preceding run's zero misses do
not establish a reliable pacing fix. Its first two CPU epochs pass complete
source, grammar, numeric-bound, loss and workqueue-association checks. The third
has a malformed record and is rejected wholly. Three qualified misses include
callback-worker wake-to-run delays of 1.522/0.454/0.466 ms; commit-worker dispatch
takes only 5/4/4 µs. The commit worker is already FIFO priority 99. Those traces
support investigating callback dispatch rather than increasing commit priority.

`output/pico-callback-little-20261027-v1/` changes only the callback queue's
selected mask to `0f`, retaining nice −20, the compositor policy and the full
tracking/UI workload. The maintained helper now accepts this second explicit
experiment. Its preflight checks the requested cluster against the global mask;
the default nice-only path, concurrency and restoration rules are unchanged.
All 982 repository tests, shell syntax and Justfile formatting checks pass.

| Measurement | Fresh `f0` control | `0f` experiment |
| --- | --- | --- |
| Missed presentations, on/off/on | 1 / 2 / 1 | 0 / 1 / 1 |
| Contained flip pairs | 1,793 / 1,792 / 1,793 | 1,795 / 1,794 / 1,794 |
| Startup overdue API ages, 500 samples | 0 | 0 |
| Steady on-window overdue API ages, 2,000 samples each | 0 / 0 | 0 / 0 |
| Off-window context-1 callback median / p99 / maximum, µs | 31 / 462 / 942 | 36 / 425 / 1,204 |

These are single sequential, instrumented runs. The off window is the only
matching phase with qualified CPU traces in both. Its callback p99 falls while
its median and maximum rise. The candidate's startup and first-on CPU epochs
contain an invalid scheduler record and an unknown event respectively; both are
rejected wholly. Its remaining epochs pass all 21,315/22,086 workqueue execution
pairs and 2,287/2,316 overlapping callback generations, with source-bound worker
identities and actual execution on CPUs 0–3 in pool 18. Both complete DRM streams
pass independently, so their missed-presentation counts remain usable despite
the rejected CPU epochs.

The candidate's two missed presents still consume callback headroom. Present
7867 has a 520 µs queue-to-execution interval and 402 µs runnable delay; present
9965 has 2.362 ms queue-to-execution and 2.288 ms runnable. Commit dispatch takes
13/4 µs. Both kickoffs precede the recorded vblank marker by only 95/54 µs, yet
the flip sequence advances an extra vblank. That marker is not a measured panel
latch deadline; these traces do not establish its exact latch condition or
separate IRQ time from scheduled-task time. The default queue mask is therefore
unchanged, and neither experimental cluster is accepted as a pacing fix.

Both 180-second workloads complete 4,499 head-camera sets, with
184,583/184,538 head callbacks and zero bad results. Both deliver 4,445 owned
controller image sets but publish zero optical poses. Controller motion ends
with `-110` after 13,791/13,787 delivered samples. The earlier geometry/range
rejection remains unresolved; no calibrated physical near-position reference,
tracked pointing, loss/reacquisition or lens acceptance is obtained here.
Passing sampled vsync-age calls also does not establish clean presentation.

All exported members are rehashed, the queue attributes restore to their
original values, and full BOOT/DTBO readbacks match the retained stock hashes.
Both runs return to verified muted, offline stock with the updater disabled.
The owned host wrapper joins with status 0; its underlying USB helper exits 1
after reboot disconnect and is no longer running. The control/candidate archives
contain 321 data files each and have these byte lengths and SHA-256 values:

- 45,613,233:
  `938fb179e7b58aacfba2adff06d389a3b6fe59954c849bb04d645ee0d82b114f`
- 45,713,013:
  `08a64fc12dffd657ce0b383d54977395ba32a0f33284f10bd2f0c044f9a44bb3`

Their private `analysis/` directories retain full-stream qualification,
individual frame chains and the source-pinned placement comparison. The
candidate's `maintained-core-proof.json` binds its native-tested topology and
queue metadata checks to the published helper.

### Callback execution context (2026-10-27)

`output/pico-callback-dispatch-20261027-v2/` uses the combined scheduler/CNSS
kernel described in `pico-native-wireless.md`. It retains mask `0f` and nice
−20, adding every scheduler switch and hard/soft interrupt entry/exit on CPUs
0–3. The kernel's generic `CPU` event-filter field selects that cluster while
the existing role filters retain the commit/render observations elsewhere.
Capture is bounded to 256 MiB per epoch. This added instrumentation is a causal
diagnostic, not a clean performance comparison.

The full DRM stream passes hash, grammar, bounds and loss checks. It records
2/1/2 missed presentations over 1,792/1,794/1,793 contained pairs. All sampled
startup and steady vsync-age queries pass. The first-on CPU epoch contains an
impossible scheduler priority and is rejected wholly. Off and final-on epochs
pass complete validation, workqueue-generation joins, all four CPU switch
chains and nested interrupt pairing. Their missed frames have different causes:

- Present 7423: queue-to-execution takes 301 µs, but the interval from the
  callback's fire marker to its emitted commit wake is another 3.521 ms. The
  callback worker is preempted runnable and remains off CPU for 3.446 ms while
  `qrtr_rx`, `do_devfreq_notify` and `_deferred_destroy` work execute. Captured
  interrupt time overlaps 139 µs of that interval. The commit worker dispatches
  in 7 µs after its wake. A fire marker is therefore insufficient evidence that
  fence notification has already completed.
- Present 9495: callback queue-to-execution is 47 µs and fire-to-commit-wake is
  34 µs. Kickoff precedes the vblank trace by 39 µs, but the flip advances an
  extra sequence. Its physical latch condition remains unmeasured.
- Present 9711: queue-to-execution takes 2.248 ms, including 2.189 ms runnable
  on CPU 0 while `ssc-imu` is scheduled. Captured interrupts occupy 454 µs of
  that runnable interval. After execution starts, fire-to-commit-wake takes
  only 23 µs and commit dispatch takes 7 µs. This motivates testing callback
  exclusion from CPU 0 while preserving the IMU reader's priority.

Scheduled intervals include interrupt and untraced exception time; these are
not pure per-function CPU costs. Native readback has wakeup preemption enabled
and a 4 ms CFS wakeup granularity. No particular CFS decision or universal
priority fix follows from those settings alone.

The 180-second workload completes 4,498 head sets and 184,566 callbacks with zero
bad results. It has one fewer head set than the earlier control; that difference
is retained without claiming a measured camera drop or matched-workload pacing
acceptance. Controller ownership completes 4,444 image sets but publishes zero
optical poses. Motion ends with `-110` after 13,786 delivered samples. The
physical near-position acquisition check remains outstanding.

The initial v1 stops before graphics because its bootstrap recipe retains the
previous kernel-note hash. Its five-file preflight archive, failed assertion,
full partition after-hashes and quiet stock recovery are preserved. v2 updates
that one recipe and verifies that no previous kernel-note pin remains in the
staged payload. Its full source/cache/cleanup checks, queue restoration,
BOOT/DTBO after-readbacks, muted offline stock return and owned host exit pass.
The verified v2 archive has 323 data files, 71,414,498 bytes, SHA-256
`ffff06d96f6015e2a3ebe54c78c7fcb8203fc5d16fe503959e94fcf16aeb062e`.
The private `analysis/` directory retains strict epoch qualification, complete
callback generations, CPU/interrupt intervals and the explicit camera-count
boundary adaptation; no subset of the rejected first epoch is accepted.

### Excluding CPU 0 does not establish a pacing fix (2026-10-27)

`output/pico-callback-exclude0-20261027-v1/` compares mask `0f` with `fe` on
the combined kernel using the earlier lighter tracing. Both carriers have the
same member set and identical bytes except `run-test.sh`, whose requested mask
and declared executor list differ. Both use the same private helper extension,
recipes, cache and on/off/on observer sequence. Mask `fe` permits CPUs 1–7;
its execution placement verifies across all three complete epochs. It remains
a private experiment; the maintained helper and default policy are unchanged.

| Measurement | Control `0f` | Candidate `fe` |
| --- | --- | --- |
| Missed presentations, on/off/on | 1 / 2 / 1 | 1 / 2 / 2 |
| Contained flip pairs | 1,794 / 1,793 / 1,795 | 1,794 / 1,796 / 1,792 |
| Queue-to-execution p99, on/off, µs | 368 / 331 | 301 / 379 |
| Queue-to-execution maximum, on/off, µs | 1,555 / 2,419 | 1,064 / 2,757 |
| Queue-to-work-end p99, on/off, µs | 945 / 1,013 | 730 / 838 |
| Queue-to-work-end maximum, on/off, µs | 2,634 / 4,562 | 2,365 / 3,352 |

The control's final CPU epoch has a malformed record and is rejected wholly;
both full DRM streams pass independently. Work-end intervals include the whole
joined item and preemption, rather than measuring hardware completion or one
callback's CPU cost. The candidate's final queue-to-execution maximum is still
3.362 ms. Both startup and steady API age checks pass, and both workloads
complete 4,499 head sets with zero bad results. Optical pose publication stays
zero. Callback tails improve in some measurements but missed presentations do
not; these single sequential runs do not justify adopting `fe`.

Controller history also differs. The control stops after 13,790 motion samples.
The candidate recovers genuine input into a new generation after its first
8,963-sample timeout, then the SDK consumer stops with `-71` after another
6,273 delivered samples while the producer continues. That transition has a
separate [controller analysis](pico-controller-protocol.md#consumer-rejection-after-genuine-resumption-2026-10-27).
Neither its cause nor the extra missed presentation is attributed to the CPU
mask from this comparison.

Source, cache, restoration, full BOOT/DTBO readbacks, muted offline stock return
and owned USB-host exit verify. The control archive has 321 data files,
45,735,123 bytes, SHA-256
`8c068b5aa6b816d48a855a1864e7e69c3ff014c2d51583607b77d689ced2ad57`.
The candidate has 322 data files, 45,772,215 bytes, SHA-256
`cde7cdda5d271c9740a3c6bc8af412d5db56578163861517851925815b3042e7`.
`comparison.json` retains full generation counts, per-window placement,
distributions, rejected epochs and the matched-payload proof.

### Rebuilt controller diagnostic control (2026-10-28)

`output/pico-motion-rejection-20261028-v2/` repeats the existing `0f`, nice −20
callback policy with the combined scheduler/CNSS kernel. Only the rebuilt
motion-rejection diagnostics and their artifact pins change; no new scheduling
policy is adopted. All three complete CPU epochs and the complete DRM stream
pass the retained grammar, hash, bounds and loss checks.

The observer on/off/on windows contain 1,792 / 1,794 / 1,794 flip pairs and
3 / 1 / 1 missed presentations. The 500 startup queries and both 2,000-query
steady observation windows have no invalid vsync-age results. The unobserved
window has no API-age acceptance claim. These results retain the distinction
between valid API ages and missed presentation deadlines; they do not establish
a pacing improvement.

Head tracking completes 4,499 camera sets and 184,483 callbacks with zero bad
results. The motion consumer's stale-history stop and continued controller image
ownership are described in `pico-controller-protocol.md`. The 324-file archive,
full BOOT/DTBO after-readbacks, callback-policy restoration, muted offline stock
return and owned host exit verify. The v1 stale-binary-pin failure is retained
separately and supplies no SteamVR timing result.

### HRTICK mechanism experiment remains negative (2026-10-28)

`output/pico-cfs-hrtick-20261028-v1/` requests only the existing `HRTICK`
scheduler feature around the three post-UI observer windows and verifies its
reported flag. The later diagnostic below establishes that this readback did
not activate the scheduler mechanism on that kernel. The kernel,
callback mask `0f`, nice −20 policy, workload and rebuilt motion diagnostics
match the preceding control. The private context manager verifies the exact
feature-set change and restores `NO_HRTICK`; no maintained default changes.

All three complete CPU epochs and the full DRM stream qualify. Missed
presentations are 0 / 1 / 3 over 1,795 / 1,794 / 1,792 contained flip pairs,
versus the control's 3 / 1 / 1. The candidate's queue-to-execution p99 values
are 322 / 359 / 368 µs, with maxima 973 / 4,214 / 1,655 µs. Valid startup
and steady API ages still do not establish presentation acceptance. These
single sequential runs do not demonstrate a pacing fix.

One qualified missed presentation retains a callback worker runnable on CPU 2
for 4.154 ms before selection. After the RT KGSL dispatcher sleeps, a normal
priority foreground task is selected for the next recorded interval. The
role-filtered trace cannot prove uninterrupted occupancy by that task or
account for all intermediate CPU activity. It therefore does not establish a
scheduler defect, a missing high-resolution interrupt or a failed HRTICK arm.
The next diagnostic must capture the actual slice decisions and timer lifecycle.

Head tracking completes 4,499 sets and 184,609 callbacks with zero bad results.
Controller images complete 4,445 sets, but optical pose publication remains
zero. The motion consumer delivers 13,793 updates before its freshness guard
stops it. Full BOOT/DTBO after-readbacks, policy/feature restoration, muted
offline stock return and owned host exit verify. The 326-file archive is
45,752,557 bytes, SHA-256
`de38efb2bfc03db69d129c3a8fc7b78848774c88428482ea65c8bcc494c472ea`.
The private `analysis/` directory retains complete epoch qualification and
source-pinned workqueue/presentation associations.

A separate fresh RAM-shell check in
`output/pico-clockevents-20261028-v1/` reads two `/proc/timer_list` snapshots.
Both report `hres_active=1` on all eight online CPUs, with `NO_HRTICK` retained.
This establishes the runtime prerequisite in that boot; it cannot retroactively
prove that a timer was armed during the earlier graphics run. Before/after
firmware hashes, muted offline stock return and owned host exit verify. The
4,936-byte compressed observation has SHA-256
`f7ec5e88b3bef2341b68907aed73480edb72f7208921b05e3048efd11ac97a20`.

### Scheduler feature control backport (2026-10-28)

`output/pico-hrtick-lifecycle-20261028-v3/` adds disabled-by-default, bounded
scheduler diagnostics to the same kernel. The complete final CPU epoch passes
source, grammar, hash and loss checks and its workqueue associations qualify.
It records 281,265 fair-selection decisions taking the HRTICK-disabled branch,
with no timer lifecycle events, while the reported feature flag is enabled.
The first epoch's callback association is rejected for an unmatched work end;
the middle CPU epoch is rejected wholly for one invalid numeric payload. Neither
supplies callback-tail evidence. The independent complete DRM stream qualifies.

The exact vendor source has `CONFIG_SCHED_DEBUG=y`, `CONFIG_JUMP_LABEL=n` and
separate `sysctl_sched_features` copies in scheduler translation units. A write
to the debug interface changes its reported copy without changing the copy used
by fair scheduling. This matches upstream
[`a73f863af4ce`](https://github.com/torvalds/linux/commit/a73f863af4ce9730795eab7097fb2102e6854365).
Patch `0016-scheduler-feature-runtime-bits.patch` backports Juri Lelli and Daniel
Bristot de Oliveira's conditional-declaration fix, preserving the upstream
changed lines and author attribution. It leaves the default feature bits,
including `NO_HRTICK`, unchanged.

Eight separate-translation-unit host checks reproduce the old disconnected
reader/writer and verify the correction across debug/jump-label configurations.
The full kernel build passes with unchanged configuration and exported module
CRCs; initramfs and DTB are unchanged. Source restoration and image layout verify.
Build and fixture receipts are in
`output/pico-sched-features-kernel-20261028-v1/`.

The diagnostic RAM run in `output/pico-sched-features-20261028-v1/` verifies
real timer requests, starts and expirations in two complete CPU epochs, with
valid whole-epoch grammar/loss/source checks and complete callback associations.
It does not complete the 180-second workload: `vrserver` records a 10.927078 s
`server_main` watchdog timeout in `WaitNextEvent`, and its Steam webhelper IPC
process disappears before the third window. The retained evidence does not
attribute that failure to HRTICK, tracing or a particular scheduler operation.
Feature/policy restoration, full BOOT/DTBO readbacks, muted offline stock return
and owned host exit verify. This is mechanism verification, not pacing acceptance
or a reason to enable HRTICK by default.

The lighter follow-up in `output/pico-effective-hrtick-20261028-v1/` completes
the original 180-second tracking/SteamVR workload on the corrected kernel. Its
member set matches the earlier light carrier; only kernel identity and dependent
artifact pins change. All three complete CPU epochs, callback associations and
the full DRM stream qualify. The on/off/on observer windows have zero missed
presentations across 1,795 / 1,794 / 1,794 contained flip pairs. Queue-to-execution
p99 values are 316 / 359 / 376 µs and maxima are 989 / 655 / 971 µs.

Both steady 2,000-query API windows pass. One of the 500 startup queries still
reports overdue age: 22.450052 ms at 168.016332434 s, before HRTICK becomes active
at 177.605997743 s. Thus overall timing acceptance remains open. One sequential
candidate with no missed presentations does not establish repeatability or
justify changing the default policy. The earlier heavy run's watchdog failure
also remains unisolated.

Head tracking completes 4,499 sets and 184,521 callbacks with zero bad results.
Controller images complete 4,445 sets, but confident optical publication remains
zero; the motion consumer stops at its unchanged freshness guard after 13,751
updates. These results do not establish tracked pointing or lens acceptance.
Feature and scheduling policies restore exactly, full BOOT/DTBO after-readbacks
match, muted offline stock return verifies and the owned USB host exits. The
326-file archive is 45,710,139 bytes, SHA-256
`29fee3a47117bcb6593f3f0e3d46fab9e3128f83006ca42c9387ceb79e75808d`.

### Pacing repeat and startup dispatch boundary (2026-10-28)

An exact-payload repeat, `output/pico-effective-hrtick-20261028-v2/`, does not
repeat the first run's zero missed presentations. The complete DRM stream
qualifies independently of CPU tracing. All startup and steady API-age queries
pass, but there is one missed presentation in each observer window. CPU epochs
0/1 and their complete callback associations qualify; epoch 2 is rejected wholly
for one invalid scheduler payload. No callback latency is accepted from that
rejected epoch.

| Run | Contained flip pairs, on/off/on | Missed presentations | Invalid startup / steady API ages |
| --- | --- | --- | --- |
| Effective HRTICK v1 | 1,795 / 1,794 / 1,794 | 0 / 0 / 0 | 1 / 0 / 0 |
| Identical repeat v2 | 1,795 / 1,793 / 1,793 | 1 / 1 / 1 | 0 / 0 / 0 |
| HRTICK covering startup | 1,799 / 1,796 / 1,794 | 1 / 0 / 1 | 0 / 0 / 0 |

The repeat's two qualified missed presentations retain complete fence/callback
associations. Callback queue-to-execution is 29 µs and 429 µs respectively;
fire-to-commit-wake is 23 µs and 28 µs. Fence return to encoder kickoff takes
188 µs and 206 µs while the commit worker stays scheduled. Kickoff precedes the
vblank trace marker by only 49 µs and 51 µs, yet the flip advances one sequence.
These software markers do not identify the physical flush/latch deadline. There
is no multi-millisecond renderer scheduling gap at these two presentations.
`output/pico-repeat-deadlines-20261028-v1/` retains the qualified boundaries and
source analysis; no further priority change follows from these measurements.

The original startup fault has a different preceding boundary. The selected CFS
render thread is runnable for 3.408 ms before its next submission. The following
GPU job's calibrated start-to-retirement estimate is 7.689 ms, ending about
374 µs after the next recorded vblank. Its callback dispatch is only 42 µs.
After the later delivered flip, the already-RR/2 event thread takes 203 µs to run;
the API query precedes the compositor's next paired-counter query. Exact compiled
Mesa source directly calls `drmCrtcGetSequence` for that pair. The custom headset
driver has no independent `VsyncEvent` publisher. This evidence supports testing
startup render dispatch; it does not establish an additional API-cache defect
or justify adding another vsync publisher. CPU occupancy outside the selected
roles remains incomplete.

`output/pico-startup-dispatch-20261028-v1/` retains those source pins and within-
epoch GPU calibration gates. Recipe 31 installs the executed geometry probe,
SHA-256 `462e78e82157430ba2a1670f83d6920dac2994b62ed21ea3dc1dd8d5c0415e41`;
the earlier nested driver probe is overwritten. The retained geometry build
receipt names its source hash, but an exact matching source snapshot is not
established. Clock/query values above are retained execution output rather than
an assertion that current probe source is identical to that binary.

`output/pico-startup-hrtick-20261028-v1/` moves the same guarded feature context
before graphics launch and restores it after cleanup. Only `run-test.sh` changes;
the observer loop is AST-identical and all binaries, kernel, cache, priorities,
affinities and acceptance thresholds are unchanged. HRTICK is active before the
startup probe. The 180-second workload completes, all three complete CPU epochs
and callback associations qualify, and all 4,500 startup/steady API queries pass.
Callback queue-to-execution maxima are 763 / 639 / 670 µs. Two missed
presentations remain. These sequential samples do not establish a repeatable
pacing fix or change the default `NO_HRTICK` policy. Optical controller confidence
remains zero.

Both new runs verify feature/policy restoration, full BOOT/DTBO readbacks, muted
offline stock return and owned USB-host exit. Their archive receipts are:

| Run | Data files | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| Identical repeat | 326 | 45,783,390 | `75ede042f4561456886b427848e24e1403db633e8ef2de82846ec4b123fa168e` |
| Startup-wide context | 327 | 45,711,392 | `b165580e67130d1a099366d11656d871a73790cc766db341ecb75c0513706c1e` |

### SDE flush decisions and startup readiness (2026-10-28)

`output/pico-sde-consumption-20261028-v2/` records the existing filtered
`sde/sde_evtlog` video-IRQ and flush-trigger events. The runtime format and
source-line schemas match the retained vendor sources and target preprocessing.
The existing logger mask stays 11; its configuration is not changed. Event
filters and enables restore after the joined reader. No kernel, render policy,
binary or quality threshold changes from the preceding startup-wide control.

The first attempt stops before compositor launch: its initial head observer
has 300 invalid poses, while later retained head records become confident.
Version 2 adds a separate startup barrier requiring one second of fresh,
progressing channel poses, bounded to 20 seconds. It waits 16.376 seconds in
this run, then the unchanged three-second OpenVR probe returns 300 valid and
zero invalid poses. Eight host fixtures cover the additional barrier. A missing
monitor log no longer masks an initial-observer failure. This barrier does not
exclude faults from any subsequent timing measurement.

The full 180-second head/camera/SteamVR workload completes: 4,499 head camera
sets, 184,571 callbacks and zero bad head results. All 274,501 DRM trace rows
qualify with complete hashes and zero recorded loss. CPU window 0 contains a
malformed row and is rejected wholly; windows 1 and 2 independently qualify.
The on/off/on windows contain 1,792 / 1,795 / 1,795 adjacent presentation pairs
with 2 / 0 / 6 software-sequence skips. One of 4,500 sampled vsync queries is
overdue in the last window. Thus neither cadence nor API acceptance passes.
Accepted-window callback queue-to-execution maxima are 748 and 721 µs.

All 13,917 video IRQ and 13,704 trigger records use observed encoder 28/interface
1. Source-order, same-CPU/TID candidates associate six skipped sequences with
kickoffs after their expected handler candidate; one kickoff overlaps that
candidate's decision. The remaining candidate records old pending 1, hardware
flush `0x30200c0` and no completion, followed by zero flush/completion `0x19`
on the next candidate. That nonconsumption decision is direct driver evidence.
None of the eight expected candidates selects completion. These observations
support investigating readiness before the display deadline; they do not select
a delayed-metadata-only fix or justify changing timestamps.

Exact handler boundaries and encoder-object-to-CRTC mapping remain unproven:
the capture lacks `vblank_irq` B/E markers, and its display state has only the
encoder mask. The consistent hardware-counter correlation corroborates the
candidate joins, without proving physical latch timing or pixels. The qualified
source/report is `output/pico-sde-joins-20261028-v1/`. Rejected CPU window 0
supplies no CPU/GPU inference. Controller processing stops earlier, as documented
in `pico-controller-protocol.md`; this is not complete controller coexistence
acceptance.

The handoff receipt now also records its selected connector/encoder object IDs
and CRTC index, retaining the IDs already queried during handoff. Its ARM64 build,
wrong-board refusal and existing display-shutdown fixture pass; this additive
receipt change is not yet deployed or hardware-tested. The initial handoff
mapping alone cannot attest a later active mapping. A fresh capture should retain
the active mapping and the existing IRQ B/E markers before assigning exact
handler/present causality. The current-source OpenVR probe also builds separately
under `output/pico-openvr-probe-20261028-v1/`; it is not yet hardware-tested and
does not retroactively close the retained binary's source-provenance gap.

The completed v2 export contains 330 data files, 45,423,517 bytes, SHA-256
`5c91428f5105163a0963506865552e1671cbda1266b8331b503c0f7523fc695d`.
Complete BOOT/DTBO after-readbacks, muted offline stock return and owned USB-host
exit verify. The failed preflight v1 remains separate: 168 files, 3,223,454 bytes,
SHA-256 `909092fb7e63347cdb54e683517099218bf020e82ba6bb5761adce4873273625`;
its recovery also verifies and it supplies no compositor timing acceptance.

### Controller notification regression and wake-path boundary (2026-10-28)

The 180-second notification regression in
`output/pico-controller-notify-20261028-v2/` preserves the kernel, pixels,
priorities and pose limits. Its main complete DRM stream qualifies. The
on/off/on windows contain 1,796 / 1,791 / 1,793 adjacent presentation pairs and
0 / 3 / 2 software-sequence skips. All 4,500 startup/steady vsync samples pass.
CPU window 0 has a malformed row and is rejected wholly; windows 1 and 2
independently qualify. The separate controller-worker trace exhausts its budget
and is rejected wholly. These observations do not establish a pacing fix or a
clean performance comparison. Head/controller feed completion and archive/stock
recovery are recorded in `pico-controller-protocol.md`.

Further analysis of the earlier accepted SDE windows 1/2 is retained in
`output/pico-sde-readiness-20261028-v1/`. The unchanged GPU calibration gates pass
for 4,321 samples. Six skipped-sequence cases and 3,583 on-time controls show
longer renderer/GPU intervals around the misses. Three cases additionally spend
409–472 µs between `sched_waking` and `sched_wakeup`, followed by only 8–73 µs
runnable delay. Their paired wake events stay in the same waker/CPU context;
the long interval is inside synchronous wake processing, not established as
remote-IPI delay or worker runqueue contention. For present 10,103, preceding
event-thread runnable delay is 317 µs, renderer interval 1.741 ms and estimated
GPU elapsed 8.065 ms. The late API query overlaps the next Mesa counter query
before its new counter returns; it does not show discarded fresh results.

The pinned scheduler already exposes `sched/sched_task_util` latency for the
EAS-selection subset of this path. A bounded capture filtered to the verified
KGSL waker can test that subset. Early-return paths omit the event, so absence
would remain inconclusive. The source/format/overhead plan is retained in
`wake-diagnostic.md` within that analysis folder. No scheduler feature toggle,
priority change or claim of a specific WALT/lock/idle cause follows yet.

### Head-camera startup failure before EAS capture (2026-10-28)

`output/pico-eas-latency-20261028-v1/` stops before dashboard readiness and
before enabling the proposed EAS capture. The head-camera producer refuses a
publication at monotonic 159.715706552 s; final camera-ring counters are 884
written and 876 consumed, filling its eight slots. The consumer reports 36,002
IMU pairs, 876 image sets and zero bad head results. A subsequent runtime sample
still observes the IMU producer active with its failure flag clear. Controller
notifications drain 36,002/36,002 with no queue or notification error.

The later feed error `-125` is cleanup cancellation. Its printed clock is the
last time supplied to the feed, rather than the time cleanup observed failure.
The controller's 642.936 ms maximum wait belongs to its separate worker. Neither
value measures the main head-feed thread's sleep or SDK call. Its scheduler
state was not captured, so this run does not distinguish a delayed wake,
runnable delay or slow vendor call. No scheduler or pose-limit change follows
from this evidence, and there is no compositor timing or optical acceptance.

The received archive verifies all 265 data files: 11,414,703 bytes, SHA-256
`3eb01805339a5b17034586448d7fb8ea303d07602a656382dffeb28024271c53`.
DSP shutdown, complete BOOT/DTBO hash comparisons, muted offline stock return
and owned USB-host termination verify. The next diagnostic brackets the main
feed's operations and captures its verified TID before dashboard startup.

### Head-feed polling wake captured (2026-10-28)

The subsequent `output/pico-head-startup-20261028-v2/` diagnostic qualifies its
entire 288,497-row main-thread scheduler/syscall stream: 34,413,065 source bytes,
SHA-256 `6cbaaa4d368d6b80a199a0e006e5113e0fb4ba310ab0e3ef4d38c63ef472bbe2`,
with zero recorded loss. PID/start-time/executable checks and a unique process
exit followed by its final zombie-state switch bind the captured interval to
that process.

Source and disassembly select the main feed's `usleep(500)` branch. Its matched
`nanosleep` syscall enters at 150.919708 s and returns zero at 159.793264 s:
8.873556 seconds. It schedules out interruptibly at 150.919720 s, with no
intervening selected events until waking at 159.793229 s. Wakeup follows 17 µs
later, execution another 9 µs later and syscall return another 9 µs later.
The camera producer refuses publication at 151.237466659 s, during that sleep.
IMU capacity also fills before the consumer resumes. This selects delayed polling
resumption as the starvation boundary, rather than long runnable dispatch or a
vendor feed call. The recorded waker has hardirq flags; its current task name
does not identify a userspace component responsible for the wake.

The initial timer slack is 50,000 ns and no captured main-thread syscall changes
it. The requested timespec, timer deadline, expiry and CPU-idle state are absent;
the underlying timer mechanism and HRTICK causality remain unproven. No timer,
idle or scheduler-feature change is selected. The fix under test replaces the
empty-input sleep with publication-driven wake hints, retaining all ring sizes,
ABI, freshness limits and SDK ordering.

All 273 exported data files verify: 13,559,331 archive bytes, SHA-256
`7bed4245546bcb17cb6639d096f6813bd3c7c062910c1668bbd0f2d53b44970e`.
Trace selection/instance cleanup, DSP shutdown, complete BOOT/DTBO hashes,
muted offline stock return and owned host shutdown verify. This failed startup
supplies no compositor pacing or controller-pointing acceptance.

### Publication-driven head-feed wake hints (2026-10-28)

[`pico-pipe-notify.c`](../src/pico-pipe-notify.c) provides coalescing wake hints
through an owned nonblocking FIFO. The native IMU producer signals after release
publication and invalidation; the head consumer waits only after observing empty
inputs, then rereads the existing rings. A full FIFO already guarantees a pending
hint. The parent retains both ends until publisher and reader join, verifies the
FIFO inode, then closes/unlinks it. Explicit ring flags and process lifecycle
remain authoritative for publisher failure. Ring ABI, capacities, freshness,
SDK call ordering and scheduling remain unchanged.

ARM64 Linux ASan/UBSan fixtures pass for a 20,000-record cross-process queue,
publication between empty-check and wait, coalescing/full pipe and descriptor
failures. The native setup also passes that fork/FIFO fixture. Producer source,
compiler, library, binary and source-closure receipts bind the rebuilt executable;
the maintained Bionic consumer has its own pinned closure. Evidence is in
`output/pico-head-notify-20261028-v1/` and `v2/`.

Version 2 processes 70,957 IMU pairs and 1,724 head image sets without a bad head
result or notification error. Its 113,955 waits include 106,985 notifications;
the observed maximum wait is 15.455 ms, including scheduling. The run then fails
the unchanged 250 ms camera freshness check at 192.518702113 s, with last image
time 192.268582180 s. Thus the former head polling sleep is removed and native
waking works, while the full 180-second regression remains unaccepted. Controller
optical confidence is still zero. No frame-pacing or tracked-pointing fix is
claimed from this shortened workload.

All 323 data files verify: 26,237,193 archive bytes, SHA-256
`3648dbf4f606109aad230c151e5851f3368e196aedb59c0eb6cbfd3e0ddbd0ac`.
FIFO ownership, trace/DSP cleanup, BOOT/DTBO hashes, muted offline stock return
and owned host termination verify. Failed preflights remain separate; version 1
also retains the corrected 34-step launcher receipt.

### Camera event readiness and default-feature regression (2026-10-28)

The head-notification run's complete CPU window 0 independently qualifies. Camera
PID 1981 schedules out interruptibly at 192.296221 s, with no later wake or
execution through 205.642216 s. Nineteen runtime samples report
`hrtimer_nanosleep` and unchanged scheduling counters. Its preceding sleeps match
the capture loop's 2 ms cadence. This establishes a second delayed polling wake;
the camera freshness failure follows during that interval.

[`pico_camera_event_wait`](../src/pico-camera-control.c) waits on the same owned,
subscribed sync/CRM descriptors for `POLLPRI`. The existing alternating
nonblocking drains, request scheduling and 2 ms timeout checks remain. Both
vendor poll functions register their V4L2 waitqueues and report pending events;
event arrival wakes those queues. Exact vendor sources are retained under
`output/pico-eas-window0-20261028-v1/camera-source/`; the
[V4L2 event contract](https://kernel.org/doc/html/v5.19/userspace-api/media/v4l/dev-event.html)
also specifies `POLLPRI`. Focused readiness/error/interruption and existing
control-ioctl fixtures pass with ASan/UBSan on macOS and ARM64 Linux.

The first combined run reaches the Steam UI software-ready state, then resets
before export. Its persistent kernel log records a watchdog bark at 200.192553 s,
with the previous pet at 180.192110 s. The alive mask does not identify a hung
CPU: this vendor driver may skip idle/isolated CPUs. No specific failed pet stage
or HRTICK cause is established. Persistent logs and subsequent matching full
BOOT/DTBO readbacks remain in `output/pico-camera-event-wait-20261028-v1/`.

A fresh control in `output/pico-hrtick-default-control-20261028-v1/` retains the
same kernel, native binaries, watchdog and idle settings. It makes no scheduler
feature writes and verifies default `NO_HRTICK` before and after the workload.
Routine regression stays at that default; HRTICK has no stability
or performance acceptance from these observations.

The complete workload lasts 181.023 seconds: 4,499 head image sets, 184,669 head
callbacks, zero bad head results, 4,445 controller image sets and no notification
or deferred-queue errors. The maximum observed head wait is 13.696 ms, including
scheduling. All three CPU epochs and all 302,081 DRM rows qualify. The on/off/on
windows contain 1,793 / 1,795 / 1,793 adjacent presentation pairs with 2 / 0 / 2
software-sequence skips. All 4,500 vsync-age queries pass, but the four cadence
gaps remain; this is not complete frame-pacing acceptance or a matched policy
comparison. No EAS tuning follows from the earlier shortened window either:
its 700 head-active callback joins have EAS p99/max 19.219/33.907 µs and do not
reproduce the earlier 409–472 µs synchronous wake tail.

Controller publication remains disabled. All 5,163 recorded result pairs have
left state zero. The 125 sampled confidence-one results also have diagnostic
`0x52 == 0`, matching the getter overwrite documented in
`pico-controller-protocol.md`; they do not establish optical acquisition.

All 357 data files verify: 50,824,806 archive bytes, SHA-256
`857dafd978ba94fca91544f6132056146b2e931f4ba3645c002e30862995e9f7`.
Deployed camera source/binary hashes, FIFO/trace/DSP cleanup, full BOOT/DTBO
after-readbacks, muted offline stock return and owned host termination verify.
Lens output, position scale, pointing and a permanent installed image retain
their separate physical/integration acceptance requirements.

### KGSL waker placement diagnostic (2026-10-28)

The complete default-feature recording supplies 5,381 unique frame/fence/callback
joins, including 5,377 on-time controls. For skipped presents 4,678 and 6,093,
the real-time KGSL waker remains the scheduled task on the callback CPU for
454 and 328 µs after waking the callback worker. The switch filters explicitly
select both directions of `kgsl_worker_thr` transitions. This is elapsed
scheduled context, including unmeasured interrupts, rather than IRQ-excluded
execution. EAS selection takes only 25.885 and 6.041 µs in those cases.
The waker's policy 1 denotes `SCHED_FIFO`; its actual priority is 25.

`output/pico-kgsl-waker-placement-20261028-v1/` tests disjoint placement: KGSL
waker CPUs 4–7 and the existing callback queue CPUs 0–3. A boot/task-identity
guard preserves class/priority/nice and restores the original all-eight-CPU
affinity. Kernel, native binaries, default `NO_HRTICK` and quality limits remain
unchanged. Placement also changes retirement speed, remote-wake locality and
competition with other big-core tasks. The owner powers the right controller
before this run, so input conditions also differ from the preceding control.

The full head/camera workload completes and all three CPU epochs and 301,869 DRM
rows qualify. On/off/on windows contain 1,793 / 1,799 / 1,794 adjacent pairs with
2 / 1 / 1 sequence skips. One of the 4,500 vsync-age queries is overdue. This
does not establish an accepted pacing improvement; the placement remains a
diagnostic and is not adopted as the routine policy. Original affinity and
all other owned settings restore before the verified muted stock return.

The export has 358 verified data files, 50,297,795 archive bytes, SHA-256
`04f03e4c55601d63f7d1d3e471a8f2d35b9c2fb932a4e534dab38b751069a7c9`.
Full BOOT/DTBO after-readbacks, trace/DSP cleanup and owned host termination
verify. Detailed default-control joins and source caveats remain in
`output/pico-default-eas-firewake-20261028-v1/`.

### Driver consumption and upstream readiness (2026-10-28)

The same default-feature recording already contains 30,371 selected SDE event
records. No additional device capture is needed for this boundary. The complete
302,081-row DRM stream, archive members, monotonic clock, eight CPU loss counters,
source line IDs, logger gate and restoration verify again.
[`pico-sde-events.py`](../tools/pico-sde-events.py) validates the complete runtime
field layout and print-argument order, then decodes the source-specific payloads.
Its fixtures reject swapped flush/completion fields, unknown source lines,
truncation, overflow and nonzero padding.

All 15,287 video-handler records associate with the preceding same-CPU/task
hardirq DRM record; the selected encoder/interface is consistently 28/1. There
is one trigger per skipped present. This association uses complete ordering and
context, not an IRQ invocation ID, which the event does not contain. Source
places the flush/pending sample before the DRM callback and log emission;
cross-CPU triggers can interleave between those operations.

| Present | Expected handler's sampled state | Following handler |
|---:|---|---|
| 4,678 | Flush `0x30200c0` still pending; no completion | Flush zero; completion `0x19` |
| 6,093 | No pending kickoff; trigger logged 75 µs after the DRM record | Completes the new frame |
| 8,715 | No pending kickoff; trigger logged 960 µs after the DRM record | Completes the new frame |
| 9,495 | Sampled pending zero; pending becomes one by log emission | Completes the new frame |

For 9,495, the trigger precedes the DRM record by 28 µs, yet follows the
handler's earlier sampled state. For 4,678, a trigger 40 µs before that record
still leaves hardware flush bits pending at the sample. The software vblank log
therefore cannot serve as the hardware-consumption deadline. None of these
events identifies a physical latch or photon timestamp. Exact rows, source pins
and sentinel checks remain in `output/pico-sde-handler-20261028-v1/`.

Present 8,715 separately qualifies through all 1,793 window-2 frame/GPU chains and
the original GPU clock-calibration gates. The renderer remains in an earlier
futex wait after delivery of the preceding flip. A `vrserver` wake is followed
by 309 µs runnable time; entry to the WSI present wait is 2.469 ms after that
flip. The WSI wait itself takes only 34.896 µs. GPU elapsed time is 7.294 ms,
within the on-time range; estimated completion is already late before callback
dispatch. This selects an upstream readiness boundary, not a proven server bug
or a scheduling fix. The futex's user-space object/callsite and server condition
remain unidentified. Reproduced source/calibration/trace receipts are in
`output/pico-gpu-readiness-20261028-v1/`.

### Dual-hand registration and IPC callsite capture (2026-10-29)

`output/pico-dual-driver-20261029-v2/` completes 181 seconds, 4,499 head camera
sets and 184,698 head callbacks with zero bad results. All CPU epochs and the
complete DRM stream qualify. On/off/on windows have 1,794 / 1,795 / 1,794
adjacent flip pairs and 1 / 0 / 1 sequence skips. One startup query is overdue;
all 4,000 steady queries pass. Both controllers register and load their models;
the right-hand input probe passes. Optical publication remains disabled.

A guarded 90-second perf capture accepts 35,696 futex entries without loss or
ABI errors; 697 shared-IPC waits identify the `vrclient.so` robust-mutex call at
LR `0x241dc0`. Whole ordered syscall joins identify present 5,462's 9.549 ms wait:
its owner/waker is the API observer, which remains runnable for 9.449 ms.
This establishes priority inversion at that observed lock, with incomplete
whole-CPU occupancy coverage. Present 9,695 has no such wait before queue;
its 1.728 ms renderer scheduled elapsed time includes unmeasured interrupts.
No priority change or general pacing fix follows. Exact source/format/rounding
gates, fixtures and joins are in `output/pico-ipc-callsite-20261029-v1/`.

The overdue startup query takes 1.406 µs while the kernel vblank timestamp is
only 118.959 µs old. API publication remains a separate boundary; API/DRM counter
equivalence and physical timing are unproven. Query/event anchors are in the
run's `startup-vsync-boundary.json`. Instrumentation overhead precludes treating
this recording as a clean performance comparison.

The 372-file archive is 51,236,412 bytes, SHA-256
`78511ff6f1254bba2588e548f5ef2254766df80971340b1e680015ed49bcc760`.
Trace/FIFO/DSP cleanup, full BOOT/DTBO readbacks, muted offline stock return and
owned host termination verify. Version 1's final recipe reinstalls a legacy
probe; version 2 corrects that artifact. The failed run supplies no pacing result.

The observer-free control in `output/pico-no-api-observer-20261029-v1/` stops
before measurement at the scheduler-state check. RR2 activation, CFS restoration
and stock recovery verify, but the failed check's actual tuple was not saved.
Its shortened perf stream is unqualified. No observer-free pacing comparison or
transition cause is established; the scheduler check remains strict.

### Observer-free windows and callback dispatch (2026-10-29)

The second control, `output/pico-no-api-observer-20261029-v2/`, saves the actual
renderer/event scheduler tuples before checking them. All three renderer checks
retain RR2/priority2/nice−20. The initial bounded setter trace qualifies its
complete two-record request/return pair and is stopped before settling and the
steady windows. It does not reproduce or explain the earlier check failure.
Pinned vendor sources permit transient FIFO40 during GPU submission; that remains
a possible explanation, with no new scheduler-policy change adopted.

The full 181-second workload completes 4,499 head camera sets and 184,720
callbacks with zero bad results. All 300,437 DRM rows qualify. Three observer-free
windows have 1,794 adjacent flip pairs each, with sequence skips 1 / 1 / 0.
Startup's 500 API queries have zero overdue samples; steady API acceptance is
unmeasured. Removing the observer therefore does not remove every sequence skip.
CPU window 0 is wholly rejected for one malformed scheduler row; windows 1 and 2
qualify. No CPU cause is assigned to window 0's skipped present 4,831.

In accepted window 1, present 6,945's fence callback queues 2.214 ms before the
expected software vblank. Its worker is awake but waits runnable for 2.503 ms
before scheduling, accounting for most of the 2.550 ms queue-to-execute delay.
The head-feed main thread occupies the same CPU 2 for 2.496 ms during that wait.
Earlier work on this callback worker has already completed; neighboring callback
runnable waits are 9 and 17 µs. Callback fire-to-commit wake is only 18 µs.
These are scheduled intervals including possible interrupts, not measured user
CPU time or proof of the exact CFS decision. The head-feed's premeasurement mask
is CPUs 0–3 and 7; moving it away from the callback pool requires a separate
control retaining head/camera freshness checks. Exact joins and source/identity
pins are in `output/pico-scheduler-readback-20261029-v1/observer-free/`.

The 381-data-file archive is 50,069,191 bytes, SHA-256
`ed763e148f52000f2dbb9232edc7bc7d3304304d938f44c96758e2b2b91500d3`.
Complete source/archive checks, trace/FIFO/DSP cleanup, full BOOT/DTBO readbacks,
muted offline stock return and owned USB-host termination verify. Optical
controller publication remains disabled; the independently recorded right-hand
IMU gap is described in `pico-controller-protocol.md`.

### Renderer baseline readiness (2026-10-29)

`output/pico-acquisition-cfs-20261029-v2/` refuses the initial renderer scheduler
check after observing `(SCHED_FIFO, 40)` instead of `(SCHED_OTHER, 0)`. The pinned
vendor `sched_save_priority_and_promote`/`sched_restore_priority` path can change
the stored class to FIFO40 during GPU submission. The observation is consistent
with that path; this failed run does not trace the transition or establish its
caller. It supplies no steady timing or CFS hierarchy acceptance.

`wait_cfs_baseline` in `tools/pico-steamvr-render-priority.py` adds a read-only
readiness gate for the owning diagnostic. Within 500 ms it requires two
consecutive OTHER0 observations with unchanged process/thread identity,
executable, affinity, nice−20 and resource limits. Separate policy/parameter
getters can straddle promotion/restoration; their intermediate values never
qualify as the baseline. Unknown classes/priorities, attribute drift, exhausted
observation budget or a read completed after the deadline fail. The caller
retains the record on success and failure. Timeout return can exceed the bound
by sleep/dispatch latency; successful acceptance cannot.

Twenty-six renderer tests pass on macOS and Linux ARM64, including eight
readiness fixtures. The existing priority setter, RR2 checks and restoration
contract remain unchanged and can reject a later transient. This gate avoids
refusing a supported temporary observation; it does not prevent a subsequent
kernel transition, fix a CFS scheduling decision or establish improved pacing.

### Complete scheduler capture and repeated callback delay (2026-10-29)

`output/pico-acquisition-cfs-20261029-v3/` accepts the renderer baseline in
8.127 ms and completes 4,499 head-camera sets and 184,722 head callbacks with
zero bad results. All three CPU epochs and 298,658 DRM rows qualify. The three
observer-free windows have 1,795 / 1,801 / 1,793 adjacent flip pairs and sequence
skips 1 / 0 / 1. Startup's 500 API queries pass; steady API remains unmeasured.
This diagnostic does not establish improved frame pacing.

The corrected scheduler reader retains complete source-shaped sections for all
eight online CPUs and verifies all selected task identities. It explicitly
refuses complete selected context: the head main thread is absent from the
non-atomic task tables, so its effective group is unobserved. SSC's row selects
autogroup 68; all four selected callback workers have root-group rows. A missing
head row does not prove migration, and the snapshot does not reconstruct a
historical scheduling decision. Raw/source pins and complete-context exclusions
remain in `output/pico-cfs-context-20261029-v2/live-v3/`.

Window-0 present 6,182's callback queues 2.418 ms before the expected software
vblank but executes after a 2.349 ms queue delay, including 2.323 ms runnable.
Head, SSC and the KGSL waker run on other CPUs during that wait. CPU 0's final
42 µs is covered by another selected worker; its preceding 2.281 ms occupancy
is unknown because the Steam IPC task switching out is unselected. Its final
switch-out cannot establish that entire interval's occupant. Moving the head
thread would test the earlier overlap, but cannot explain this new delay.
Present 9,706 separately has only 121 µs callback dispatch delay; kickoff before
the software-vblank record still misses a flip, reinforcing the physical-deadline
limits documented above. No scheduler policy change follows from these results.

The 497-data-file archive is 58,291,139 bytes, SHA-256
`804d367bf75d6689709c33a2ecb36676363f5325495977247525d2a5b72a43b8`.
Every member rehashes. Complete BOOT/DTBO readbacks, trace/FIFO/DSP cleanup,
muted offline stock return and owned USB-host termination verify.

### Complete callback occupancy recording (2026-10-29)

`output/pico-callback-occupancy-native-20261029-v4/` adds an unfiltered,
window-0-only scheduler recording on CPUs 0–3. Its 98,905,393 bytes contain
559,345 switches; all four complete PID chains, event counts, zero-loss checks,
measurement coverage, source/instance identities and restoration checks pass.
The complete main CPU window 0 and whole DRM recording qualify independently.
The original main window 1 remains wholly rejected for a malformed scheduler
row at line 332,672; window 2 qualifies. No rejected prefix is used.

All 175,416 main-window-0 switches on CPUs 0–3 have a unique, ordered, exact
full-body correspondence in the added stream after applying the recorded main
filter. The paired record timestamps differ by 0–593 microseconds; no timestamp
tolerance, clock correction or fallback match is applied. Scheduled residency
includes possible interrupts, and cross-stream boundary ordering still needs
the corresponding event brackets. This is not exclusive task CPU time or proof
of a CFS scheduling decision.

Present 6,406's unique fence callback queues and starts only 34 microseconds
apart, then is switched out runnable for 1,966 microseconds before firing fence
6,424, 178 microseconds after the expected software-vblank record. Four ordered,
closed CPU-2 intervals have printed durations 19 / 254 /
1,648 / 45 microseconds: `qrtr_rx`, two workqueue workers, then
`irq/366-smp2p`. The two workers' uniquely associated work spans execute
`do_devfreq_notify` and `_deferred_destroy`. Those spans include off-CPU time;
the scheduled intervals include interrupts. The retained KGSL source shows a
priority-promotion helper around the devfreq notifier, but this recording does
not trace that transition. Two different KGSL functions share the symbol
`_deferred_destroy`, so its printed name cannot distinguish memory-entry from
pagetable destruction. The CFS selection and any unrecorded migration remain
unexplained. The separate maximum 3.802 ms runnable interruption occurs after
its target fence fire and commit wake; it is excluded as that fence's delay.

The added recorder's 24-second resource bound includes startup, the unchanged
20-second measurement and shutdown. Earlier 22-second attempts expire during
shutdown and remain wholly rejected. An early stop hook runs after the original
main capture finishes, before wrapper restoration; all readers must join before
any shared-nop instance removal. The original main capture, 256 MiB text cap,
freshness limits, kernel, SDK and scheduling policy are unchanged. Thirty-three
collector fixtures and thirteen stop-hook fixtures pass; the native added
recorder joins in 22.487 seconds with no discarded bytes or cleanup errors.

The full workload completes 4,499 head-camera sets and 184,498 callbacks with
zero bad results. All 298,657 DRM rows qualify; observer-free sequence skips are
4 / 0 / 2. Additional tracing precludes a clean performance comparison. These
results establish recording completeness, not improved pacing, physical latch
timing or optical controller tracking.

All 504 exported data files rehash. The 56,106,052-byte archive has SHA-256
`44b0f716419ad9efb10dc20ad8080afadd3b2a1902d25ed14c7bb0931152579f`.
Complete BOOT/DTBO readbacks, trace/FIFO/DSP cleanup, muted offline stock return
and owned USB-host termination verify. Strict qualification is retained in
`output/pico-callback-occupancy-analysis-20261029-v1/`.

### Scoped KGSL maintenance placement control (2026-10-29)

`tools/pico-gpu-maintenance.py` is opt-in. Its default control performs no queue
writes. Enabled placement changes only `kgsl-workqueue` and `kgsl-mementry`
CPU masks to `70` (CPUs 4–6), leaving the renderer's CPU 7 outside that mask and
the existing `kgsl-events` policy at `0f`/nice −20. Nice, concurrency, NUMA policy,
thread scheduling classes and the global workqueue mask remain unchanged.
Identity/topology/source guards and before/active/after receipts surround the
operation; partial writes unwind in reverse order. Thirty-one focused fixtures
and all 57 GPU-policy tests pass.

The experimental kernel patch exposes only `kgsl-mementry` through `WQ_SYSFS`;
the general queue is already exposed. The vendor's unbound/max-active-one
devfreq queue is implicitly ordered. Applying its attributes clears the internal
ordering flag, which restoring the visible mask cannot recover. It is therefore
excluded entirely from the helper and kernel change. Its source stays
byte-identical, pinned as
`c7f213e9ef6ebefa8d6bf4d94fb809b344c2d2bf841e7e4e923a2b5854e2bc9a`.

The v3 kernel build in `output/pico-kgsl-maintenance-kernel-20261029-v3/`
compiles, verifies image layout and restores its retained source tree. Config,
module CRCs, DTB and initramfs are unchanged. Its first hardware control,
`output/pico-kgsl-maintenance-native-20261029-v2/`, verifies the new interface
with zero maintenance writes and complete restoration. It then stops before
steady measurement at a stale consumer-binary pin in `tracking-selection.py`.
All 244 exported data files and firmware readbacks verify, followed by muted
offline stock return and owned host termination. This failed control provides
no full-workload or pacing acceptance; the pin must name the exact rebuilt
consumer before retrying, retaining the original mapping checks.

Corrected control v3 and placed v4 use 204-member payloads whose source files
differ only in the explicit maintenance `enabled` boolean. Both complete 4,499 head-camera
sets with zero bad results. The original main CPU epochs and whole DRM streams
qualify independently: 299,503 control rows and 299,297 placed rows. Across the
three unchanged 20-second windows, missed presents are 2 / 0 / 1 for control
and 1 / 0 / 3 for placement. This single comparison does not establish an
improvement; live radio activity also differs between boots.

Control's complete additional occupancy stream qualifies with 95,445,817
bytes and 539,848 switches. Placement's additional stream is wholly rejected
for a PID residency-chain break. No rejected prefix or selected interval is
used for interruption attribution, and the independently accepted main
recordings do not repair that missing evidence. The placement policy remains
experimental; it is not a verified callback-interruption fix.

Placement changes exactly the two allowed masks and restores them in reverse
order to `ff`, with no restoration errors or unrelated attribute changes.
All 537 control and 523 placed archive data files rehash. Both firmware
readback sequences, DSP/FIFO cleanup, muted offline stock returns and owned
USB-host joins verify. Archive hashes are respectively
`77e41375fb72ac4035ff2ade16b5ccab5865fbb83f47acfcf89a39fa1e6da911` and
`38279ec9bb6ef4f6c8e023bbedf2ecb7190465b41047781b5e412fd01b6efacb`.
Qualification receipts and the separate controller outcomes are retained in
`output/pico-kgsl-maintenance-analysis-20261029-v1/`.

### Callback priority boundary (2026-10-29)

The retained vendor `kgsl_events.c` emits `kgsl_fire_event` before calling
`sched_save_priority_and_promote`, then invokes the callback and restores its
previous policy. The scheduler helper requests `SCHED_FIFO` priority 40. The
GPU devfreq notifier and immediate command-issue path also call that helper.
Their exact sources and the unchanged helper-body comparison against the
executed v3 kernel are retained in `output/pico-kgsl-promotion-20261029-v1/`.

In accepted control window 0, callback worker 2743 is observed at normal
priority 100, then effective priority 59, then 100 around one guarded event
work item. Snapshots independently observe FIFO priority 40 before the window
and normal scheduling afterward. A constant-CFS assumption for this pool is
therefore invalid. Among the guarded display-context work items, the largest
proven pre-fire runnable gap is 1,001 µs at normal priority, starting six
microseconds after `workqueue_execute_start`.
That tracepoint precedes the actual function call, so this does not establish
which instruction was interrupted. The overlapping devfreq worker is sampled
at priority 120; its promotion cannot be inferred for this interval. No
millisecond normal-priority gap between fence fire and commit wake is found
in this window. Moving the existing promotion is not yet a verified fix.

The rejected placed occupancy row has header PID 1985 but body previous PID
2813. Its independently recorded main-trace counterpart consistently names
1985. This localizes the inconsistency to the additional recording; it does
not establish a kernel-memory or scheduler fault. Both original streams are
preserved without repair.

### Callback phase boundaries and collector fixes (2026-10-29)

The opt-in `experimental/0018-kgsl-delayed-callback-phases.patch` separates
worker entry, the existing fire trace, promotion, callback and restoration.
It emits one record after restoration and preserves the callback's operational
order. Generated AArch64 code confirms that disabling the event skips the new
clock/scheduler samples. Configuration, DTB, initramfs and module CRCs remain
unchanged. This diagnostic is excluded from the default kernel profile.

Two diagnostic defects are fixed and covered by focused fixtures. First,
instances share the vendor kernel's `nop` tracer reader reference count:
removing the phase instance before the separate DRM reader joins returns
`EBUSY`. Cleanup now disables/drains its reader; removal follows the common
all-readers-joined gate. A no-event Pico probe reproduces the failure and then
removes both instances after closing the reader. The first failed cleanup
receipt remains rejected. Second, `ns2usecs()` rounds rather than truncates:
printed timestamps represent `[printed-500, printed+499]` ns. The analyzer now
uses that interval when joining exact samples, including a verified boundary
where the fire marker prints 31 ns after the sampled trace-call return.
No captured timestamps or rows are rewritten.

The corrected run `output/pico-kgsl-phase-native-20261029-v2/` completes 4,499
head-camera sets with zero bad results, removes its phase instance, joins the
owned USB host and returns to muted offline stock with unchanged BOOT/DTBO.
The complete sparse recording and middle CPU epoch qualify independently:
2,499 phase rows, with 39 before and 171 after the measured interval explicitly
excluded from the join. All 2,289 contained work generations match exactly,
including 1,796 display-context callbacks. Promotion/restoration return zero,
with observed priority 100 → 59 → 100 throughout that measured population.

No millisecond execute-to-entry, fire-trace, promotion or callback envelope
reproduces in this middle window. Its largest display-context restoration
interval is 2.572084 ms, after the callback, with an enclosed 2.551 ms runnable
gap. This does not establish a cause for earlier pre-fire delays. The whole
DRM stream independently records 2/0/2 missed presentations in the three
20-second windows; no performance improvement or observer neutrality follows.
CPU window 2 is wholly rejected for one malformed scheduler payload. Its
prefix and CPU comparisons remain excluded; the malformed row's origin is
unresolved.

The maintained analyzer and collector are `tools/pico-kgsl-phases.py` and
`tools/pico-kgsl-phase-capture.py`. Thirty focused fixtures cover structural,
source-bound timestamp, generation-join, CLI and reader-lifecycle rules.
Build/generated-code evidence is in `output/pico-kgsl-phase-kernel-20261029-v1/`;
complete-file gates, exact joins and uncertainty limits are retained in
`output/pico-kgsl-phase-analysis-20261029-v2/`. Full trace-option and trigger
snapshots were not collected, so no claim covers those unrecorded settings.
No scheduling-policy change is adopted.

### Dispatch attribution and CPU-observer control (2026-10-29)

Complete CPU windows 0/1 from the preceding phase run localize two separate
delays. Across 1,793/1,796 display callbacks, the eventual worker's preceding
work has ended before queueing, its last switch-out is `TASK_IDLE`, and each
queued generation activates within 11/18 µs. This shows an available sleeping
executor, not pool exhaustion or a previous callback's restoration blocking it.
Exact pool idle-list counts were not recorded. The worst dispatch takes
1,177 µs, including 1,151 µs from runnable wakeup to the first switch selecting
that worker; only 8 µs follows that switch.

The two missed window-0 presents differ. Present 4914 queues its callback
2,093 µs after the expected vblank, then dispatches in 30 µs; its earlier
upstream lateness remains unexplained. Present 5470 queues 702 µs before that
boundary but executes after 842 µs. Its 697 µs selecting-switch-to-execute
interval contains interrupt-context activity. The scheduler tracepoint precedes
the actual context switch, and no handler duration is recorded; that interval
cannot be assigned entirely to CFS waiting or callback CPU work. Printed deltas
have the existing conservative ±999 ns envelope. Rejected CPU window 2 remains
excluded. Source pins and exact event chains are in
`output/pico-kgsl-queue-cause-20261029-v1/`.

The subsequent `output/pico-cpu-observer-native-20261029-v1/` tests CPU trace
events on/off/on across three 20-second windows. Kernel, workload, worker
policy, affinity and continuous DRM capture are unchanged; API observation and
phase records are disabled throughout. Each arm settles for one second.
Control arms make zero tracefs writes. The middle arm disables the owned event
registrations and exact existing stack trigger, verifies the selected events
disabled across the root and five instances, then restores every journaled
change. It is intentionally unmeasured and ineligible for CPU attribution,
even where the original structural parser accepts it. Other perf/BPF
registrations were not inventoried.

The whole 298,688-row DRM recording qualifies, with 0/1,797, 0/1,795 and
0/1,795 missed/contained presents. Queue-to-flip p99 is respectively
10.446/10.510/10.464 ms. These sequential short windows show no consistent
off-arm improvement; zero misses do not establish equivalence or resolve the
earlier rare faults. Other logging, DRM capture and polling remain present.
No scheduling-policy fix follows from this control.

All 540 exported data members rehash; the archive SHA-256 is
`42e7dbdd657de25e222201c03716bc1cefc4ef1a26836845e5421feb33bd36e9`.
The 180-second workload, complete control CPU epochs, restoration, firmware
readbacks, muted offline stock return and owned USB-host join verify.
Analysis and exact source-equivalence checks are in
`output/pico-cpu-observer-analysis-20261029-v1/`. Neither this control nor
the queue analysis validates optical controller tracking or physical display
latch timing.

### Private fence worker comparison (2026-10-30)

The [fence-dispatch record](pico-kgsl-fence-dispatch.md) contains the matched
kernel control, complete capture qualifications and route-specific timings.
The private worker lowers the observed dispatch tails; two presentation misses
remain. It stays opt-in and disabled by default. This does not close steady API,
physical motion or optical controller acceptance.
## Shutdown diagnostics (2026-10-30)

Clean SteamVR shutdown remains unverified. The new
`tools/pico-steamvr-shutdown.py` records systemd's `SERVICE_RESULT`, `EXIT_CODE`
and `EXIT_STATUS` from each owned unit's `ExecStopPost`, before transient-unit
collection can remove that information. Receipts are published atomically and
bound to the unit, boot and shutdown time. The coordinator waits for a caller's
quit request, then stops remaining services sequentially, keeping seatd/Xvfb
until last. A successful stop request cannot substitute for a successful final
core-process exit. This optional diagnostic is not installed in the OS image.

Native runs in `output/pico-steamvr-orderly-shutdown-20261030-v2/` and `v3/`
capture vrserver exiting 1 and vrcompositor terminating with SIGSEGV. The
driver-requested quit event was emitted but did not produce a runtime shutdown;
the normal X11 close test found no window belonging to vrmonitor. Both attempts
are retained as rejected approaches. Their driver/probe/window experiments were
not promoted to maintained runtime code.

Both compositor minidumps have an unmapped PC and LR at `vrcompositor+0x106a3c`,
immediately after an indirect call through an object's vtable at `0x106a38`.
The enclosing retained binary releases shared resources. This narrows the
failure to resource teardown; it does not prove why the object became invalid.
A [related upstream report](https://github.com/ValveSoftware/SteamVR-for-Linux/issues/990)
describes a shared-resource cleanup crash on another SteamVR build. Exact dump,
module and frame-pointer evidence is in
`output/pico-upstream-delay-analysis-20261030-v1/shutdown-crashes.json`.

The v2 workload stopped at a race-prone pre-measurement check of its 30-second
controller probe; the probe later exited zero. The next harness waits for its
bounded completion before attempting observer-free measurement. The v3 run
instead hit a camera-feed timeout before dashboard readiness. Neither run
supplies a new frame-pacing or optical-tracking acceptance result. Version 3
does verify automatic failure export, DSP/MCU release, unchanged BOOT/DTBO,
muted offline stock return and USB-host join.

Diagnostic archives: v2 SHA-256
`1517d3404df40afb7dce8a079d9972ed34579d0f03dc71dae33157d1b2502b58`;
v3 SHA-256
`3debffb292aea626e6ce9279d5b2695b614c81f42d80ceec9c7b562059d359a2`.

### Failed-start and trace-reader cleanup (2026-10-30)

The RR1 comparison repeat exposed two diagnostic cleanup defects. The old
trace factory marked itself finished before joining its reader; a timed-out
join therefore could never be retried or refreshed. The maintained
`tools/pico-trace-stream.py` retries that join, retains the timeout as a capture
rejection even if the reader later exits, and records its native thread ID,
kernel stack, wait channel and syscall when available. It never closes another
thread's descriptor or removes its trace instance. Six host regression cases
include a real nonblocking FIFO drain and reproduce the old premature-finished
failure. The cause of the native reader's original stall is still unverified.

The next attempt rejected the new factory at a dependent source pin before
SteamVR startup. Its error handler then called the shutdown coordinator with
an incomplete unit list, raising before DSP/MCU cleanup. Explicit
`close_session(..., allow_partial=True)` now stops only the registered owned
units when startup is incomplete; it skips the quit request and cannot qualify
a clean core exit. Strict complete-session validation remains the default.
Ten shutdown tests cover empty and partially started sessions, ownership
refusals, retained failures and ordinary shutdown receipts.

This rejected attempt is retained in
`output/pico-ipc-rr1-native-20261030-v3/`; it supplies no pacing comparison or
optical result. After verifying that camera clients had exited and both DSPs
were offline, recovery released the single MCU reference. The 72-data-member
failure archive SHA-256 is
`9757ab451f789d45e3d2e792cac7ce49951ccb80cfd357de8626c1bf065e32ea`.
Firmware readbacks and muted offline stock return were verified afterward;
the exact USB helper was retired, without an orderly wrapper-join receipt.

The subsequent completed native workload in
`output/pico-ipc-rr1-native-20261030-v4/` records successful sequential systemd
stops without the earlier vrserver exit 1 or compositor SIGSEGV. Both core
receipts instead report `result=success`, `code=killed`, `status=TERM`; the Steam
UI process exits zero. This verifies bounded service termination in that run.
The coordinator still reports `natural_core_exit=false` and
`clean_core_shutdown=false`; a graceful in-runtime quit remains unverified.
Its [CFS/RR1/CFS comparison](pico-kgsl-fence-dispatch.md) and export-recovery
limits are documented separately. No new optical controller or physical lens
acceptance follows.
