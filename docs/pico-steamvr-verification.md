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
