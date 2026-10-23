# Neo3 SteamVR verification

These records distinguish source and VM checks from bounded native Pico tests.
Private calibration, binary artifacts and hash manifests remain in gitignored
`output/`. See [driver setup](pico-steamvr.md) for the opt-in configuration.

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
on hardware. Natural radio sleep/wake, optical controller poses and pointing,
physical head-motion scale, upright lens output and movement direction remain
separate acceptance gates. Audio is not opened during these runs. No firmware
partition is written.
