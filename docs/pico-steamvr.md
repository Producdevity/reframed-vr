# Native Neo3 SteamVR driver

`reframed_pico` is the physical Neo3 Pro Eye driver for Valve's native ARM64
SteamVR server and compositor. It is separate from `reframed_virtual` and does
not use Monado. Nothing enables or installs it automatically.

Peripheral integration is tracked separately: the
[controller receiver](pico-controller-protocol.md#native-fastrpc-input-worker)
has verified physical left-controller button, touch and analog reports through
the native FastRPC path. Digital legacy and dashboard bindings are provided
below; analog calibration and controller poses remain separate work. The
[native audio diagnostic](pico-native-audio.md) routes the native Steam client through Frame PipeWire to the Pico speakers;
the owner confirmed hearing Steam's startup sound. Installed session wiring,
microphone capture and concurrent SteamVR/audio load remain unverified. The
WSA digital mute readbacks did not guarantee silence; audio is currently stopped.

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
the Frame sensor driver and motion smoothing. It selects Facet with the paired
counter timing support in Turnip patch 0015 and disables
`renderSystemLayerInDistortPass`. The layer option crashed the legacy compositor
and remains unvalidated on Facet. These settings are specific to the retained
runtime and Neo3 path; Frame's renderer settings are not interchangeable defaults.
Provide all of:

| Environment variable | Required value |
| --- | --- |
| `PICO_STEAMVR_BOOT_SERIAL` | Exact native `androidboot.serialno` |
| `PICO_STEAMVR_OPTICS` | Private, validated Neo3 optical-profile file |
| `PICO_STEAMVR_POSE_CHANNEL` | Readable mapping created by this capture owner |
| `PICO_STEAMVR_INSTANCE` | Nonzero process-instance identifier, 16 lowercase hex digits |
| `PICO_STEAMVR_GENERATION` | Nonzero estimator generation, 16 lowercase hex digits |
| `PICO_STEAMVR_MAX_AGE_NS` | Explicit maximum pose age, at most 100 ms |

## Optional controller input

The physical driver can register a left Neo3 controller when both
`PICO_STEAMVR_CONTROLLER_CHANNEL` and `PICO_STEAMVR_CONTROLLER_INSTANCE` are
provided. The instance is a nonzero 16-digit lowercase hex identifier. Without
these variables, the driver retains its HMD-only behaviour.

The channel is a separate 128-byte `pico_controller_channel` mapping. Its owner
initializes a new file once and publishes samples accepted by the maintained
controller decoder, with the host monotonic receipt time. The driver requires a
regular, exact-sized file owned by root or its own user and not writable by
group/others. The mapping and instance remain bound until driver shutdown.
A restarted producer must use a new instance and file and restart the driver.
The channel implementation does not open hardware or start a DSP.

The adapter exposes twelve digital button/touch components through the
[OpenVR input profile](https://github.com/ValveSoftware/openvr/wiki/Input-Profiles).
Input older than 250 ms, a stopped producer or an invalid channel clears the
components and marks the controller disconnected. A rejected SteamVR input
update also attempts to release every component and marks it disconnected;
the debug response counts rejected calls. The timeout uses host receipt time,
not an established controller capture-clock mapping.

The controller reports `poseIsValid=false` throughout. No controller position,
orientation, haptics, analog calibration or render model
are supplied by this step. Raw analog endpoints were captured but axis sign,
center and dead zone still need physical calibration. Enabling this adapter
does not yet provide a tracked dashboard pointer.

Host tests exercise real adapter methods against mocked OpenVR callbacks under
ASan/UBSan, including stale input, failed updates, disconnect/reconnect and
invalid pose. The same callbacks pass native UBSan on the Pico. Native ASan
cannot start on the current kernel: its requested shadow/heap address exceeds
the supported user address space. The separate IPC test replays all 27,794
physical records and exercises concurrent publication without changing fields.

The bundled `pico-steamvr-live` probe accepts `--left-controller` instead of
`--dashboard` for a bounded shared-session check:

```sh
pico-steamvr-live PATH_TO_LIBOPENVR_API BOOT_SERIAL 30 --left-controller
```

Run it with the existing session's OpenVR environment. It identifies the physical
left controller by serial, samples its legacy input and driver diagnostics once
per 100 head-pose queries, and timestamps those observations with host monotonic
time. Success requires more than 100 valid head-pose queries and at least one
connected, readable controller state; exit code 10 indicates a missing controller
interface or no such state. It reports controller pose validity without inventing a pose.
It does not open the dashboard or start sensors. Correlate its timestamps with
the separate compositor trace to establish concurrent presentation; this probe
alone does not prove rendering, button interaction or wake-from-idle.

### Digital default bindings

The profile supplies a Neo3-specific legacy binding and a driver default for
`openvr.component.vrcompositor`, using Valve's
[input-profile mechanism](https://github.com/ValveSoftware/openvr/wiki/Input-Profiles#default-bindings).
User or application bindings take precedence. Both JSON resources are packaged
and hashed by the driver builder; no SteamVR installation files are modified.

| Physical control | Legacy application input | Dashboard laser-mouse action |
| --- | --- | --- |
| Trigger click / touch | Axis 1 press / touch | Left click |
| Stick click / touch | Axis 0 press / touch | Right click |
| Grip click | Grip press | Middle click |
| X / A click / touch | A press / touch | Home |
| Y / B click / touch | Application-menu press / touch | Back |
| Menu click | Application-menu press | Back |
| PICO / Home click | System press | Toggle dashboard, in the system action set |

The retained runtime also includes pressed buttons in the legacy touch mask;
the grip touch bit in that API does not establish a physical grip-touch sensor.

The compositor binding also supplies digital room-setup accept/back and
dual-analog click/touch actions. It does not supply analog values, scrolling,
haptics or skeleton actions. Right-hand paths reserve the corresponding A/B
layout; the current driver registers only the left controller, and right-hand
hardware acceptance remains pending. Thumbrest touch remains available to
applications through explicit bindings but has no legacy/dashboard mapping here.

The laser-mouse pointer binds `/pose/tip`, which SteamVR registers for tracked
devices. Its pose stays invalid until controller tracking and the pointing
transform are implemented and validated. A digital binding alone therefore does
not provide dashboard pointing or establish rendered dashboard interaction.

### Native binding verification

RAM-only Pico boot `a014287d-2c4f-4869-bd16-ac24b4b1e752` tested the defaults in
native ARM64 SteamVR 2.17.10 with fresh session configurations and the retained
27,794 physical left-controller records. The server selected the driver's legacy
binding automatically. Legacy button/touch masks matched the expected mappings,
including the runtime's inferred grip-touch bit. The final connected sample was
released; after disconnect, `GetControllerState` correctly returned false.

A background diagnostic identified its explicit process ID as
`openvr.component.vrcompositor`, verified that identity, and loaded the unchanged
runtime action manifest. SteamVR selected `neo3_compositor_bindings.json` without
an explicit binding override. Binding introspection confirmed the six physical
source paths, and `IVRInput` returned all five laser-mouse actions: left/middle/right
click, Home from X, and Back from Y/menu. It observed 72 transitions and released
all actions after replay. Both runs had zero driver input errors and 144 accepted
component changes. This validates automatic binding selection and recorded-input
actions, not a new simultaneous physical button test or rendered dashboard use.

The passing runs started no compositor or audio, and the driver continued to
report invalid controller poses. Home-button dashboard toggling, right-hand input,
physical wake-from-idle, analog calibration and tracked pointing remain pending.
Earlier diagnostic pose queries unexpectedly started the compositor; those failed
probe attempts are retained separately and do not establish compositor readiness.

Evidence: `output/pico-controller-bindings-20261022-v1/export-bindings.tar.gz`,
147 files, SHA-256
`9096de0c8c4f143cfb33751d91f8c0b892a5cad2042b0bfecd6c457a229de045`.
The archive and all member hashes were verified. All 28 final driver-build inputs
match the repository; packaged bindings match the loaded resources. Native UBSan
callback/IPC tests and 26 host controller/SteamVR tests passed. The unchanged
driver binary has the hash recorded in the earlier verification below.
Full boot/DTBO readbacks remained unchanged, all DSPs remained unbooted and MCU
references were zero. `stock-return-final.json` records the return to b1977 with
Wi-Fi off and the updater disabled; `stock-mute-final.json` confirms media/system
volume zero. No partitions were written.

### Native controller input verification

A fresh RAM-only Pico session loaded the new physical driver in native ARM64
SteamVR 2.17.10. A diagnostic receiver using the maintained FastRPC wrapper and
MCU pacing request delivered 14,991 valid left-controller records. An independent
OpenVR client observed the controller connected, with successful legacy state
reads, for 30 one-second samples. After stationary delivery stopped, both the
driver and client reported it disconnected. Driver input updates had zero errors.
No button presses occurred in this stationary run.

A separate replay sent the earlier 27,794 physical movement/button records
through a new channel and instance. With explicit diagnostic action bindings,
SteamVR's `IVRInput` returned all eleven tested controls: X/Y, menu, grip,
stick click, trigger click, and X/Y/stick/thumbrest/trigger touches. The client
observed 126 action transitions; the driver accepted 144 component changes with
zero update errors. All actions were released after replay stopped. Home was
exposed by the driver but was not pressed in that physical capture.

This is live transport acceptance plus recorded-input action acceptance, not
a new simultaneous physical button test. The diagnostic uses an inactive head
pose and starts neither the compositor nor audio. Controller pose remains
invalid. This earlier run used the stock generic legacy fallback, which requested
unsupported analog/trackpad/haptic components. The digital defaults below replace
that fallback.
The maintained receiver's subsequent shared-sensor test is recorded below.
Installed session orchestration and controller pose remain pending.

Evidence is in `output/pico-controller-steamvr-20261022-v1/`:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-input.tar.gz` | 45 | `233f960f8dd4883647207a507825dddbbdc59ab78f7c475af86b5bfb81088b93` |
| `export-replay.tar.gz` | 20 | `40b595d468fee51c4744831ed8a612ab5dd3647d957e076dd9932ac5d85e7bb4` |

Both archive inventories, member hashes and extracted bytes were verified.
`analysis.json` summarizes the client observations. The tested driver SHA-256 is
`eeb45594112e4de2a9194686a3d7ad5a980444208881d8232150e13401a4deac`;
its build manifest matches every tracked build input. The diagnostics ran with
ADSP/CDSP unbooted and closed audio devices. DMA allocations remained owned until
SLPI was confirmed offline; MCU power references returned to zero. Full boot and
DTBO readbacks still matched their pinned hashes. The headset returned to b1977
stock with Wi-Fi off and the updater disabled, recorded in
`stock-return-final.json`. No partitions were written.

### Maintained receiver and shared sensors

The maintained [FastRPC input worker](pico-controller-protocol.md#native-fastrpc-input-worker)
was built and tested on the Pico in RAM-only boot
`478af459-223d-47dd-8587-1e5a6423cfc2`. Its SHA-256 is
`391be406899a664541a6be2b157eb52ed0fa36853fdec4ad285ca7473ffb9d8a`;
all 21 recorded build inputs match the retained source. Native UBSan ring tests
and RPC tests passed, including 128 mocked RPC cycles and six injected error
stages. The existing driver callback and physical-record IPC replay tests passed
again. The host controller/SteamVR suites passed 22 tests under their configured
sanitizers.

Two 120-second receive runs shared SLPI with a live head accelerometer/gyroscope
session and briefly ran all four tracking cameras. Each camera delivered 247
frames with successful stop calls. The MCU command connection had one owner;
camera startup supplied pacing, while the controller worker opened no SPI device.

| Configuration | Left input publications | SteamVR connected samples | Rejected driver updates |
| --- | ---: | ---: | ---: |
| Head IMU plus slow companion accelerometer | 14,983 | 30 / 130 | 0 |
| Head IMU, no companion accelerometer | 14,989 | 30 / 130 | 0 |

The head-only configuration therefore needs no additional slow accelerometer
subscription. Both streams produced approximately 500 input publications per
second during active delivery. The stationary controller again stopped delivering
after about 30 seconds; the driver then disconnected and kept its components
released. No physical buttons were pressed during these runs. These results
neither resolve wake-from-idle nor replace the earlier recorded-input action test.

Both workers disconnected input, closed RPC clients and retained their DMA
buffers while the head client stopped and joined. SLPI then reached `OFFLINE`
before the workers released registrations and exited successfully. MCU references
returned to zero. The head stream remained active throughout each receive run
and reported no session/ring failure; its diagnostic mount-matrix fallback does
not validate head calibration. The SteamVR HMD channel was intentionally inactive,
controller poses stayed invalid, and neither compositor nor audio was started.
This verifies concurrent sensor/input transport, not simultaneous rendered 6DoF
or a tracked dashboard pointer.

Evidence is in `output/pico-controller-worker-20261022-v1/`; both archives and
every member hash were verified after export:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-worker.tar.gz` | 96 | `93f68878f8c57e45b15e5bba72db161cf2448247046696b840254759c051af2e` |
| `export-head-only.tar.gz` | 94 | `7d190a7479e393811820324d66df24c57c4f533e0190db93ab504b30a9c02300` |

Full boot and DTBO readbacks after both tests still matched the pre-test hashes.
The Pico returned to stock b1977 with Wi-Fi off, updater disabled and music/system
volume verified at zero. The return and mute receipts are retained alongside
the archives. No partitions were written.

### Parent-controlled worker shutdown

The maintained [session helper](pico-controller-protocol.md#parent-session-lifecycle)
was tested in RAM-only boot `fce28462-0f36-451a-9d41-33e1c7763c6e`.
Its build packaged the helper with SHA-256
`d0f55992a856b675af60681d1118b0e7e3799b9c8fe06adefe9aa571bcb6278e`;
all 22 worker inputs and 28 driver inputs matched the current source. The worker
and SteamVR driver binaries retained their previously verified hashes. Native
ring/RPC tests and the retained physical-record channel replay passed again.
The host controller/SteamVR suites passed 34 tests, including eight subprocess
fixtures for the new session lifecycle.

The parent requested SIGTERM after 20.036 seconds of the input-client run,
before the worker's 120-second duration limit. The worker delivered 7,250 left
input publications; SteamVR reported a connected left controller at ticks 6–19
of 55 one-second observations, then remained disconnected. Driver rejection
counts stayed zero, and digital components stayed released. No new physical
button presses or sleep/wake checks were performed.

The head stream delivered 26,058 accelerometer and 26,058 gyroscope samples,
with no session/ring failure. Each tracking camera delivered 247 frames and
stopped successfully. The parent verified that the controller process was still
alive and retained its buffers after all three RPC result codes returned zero,
while SLPI remained `ONLINE`. At that point, the helper rejected a request for
the stopped channel's SteamVR settings. The head client then joined, SLPI reached
`OFFLINE`, and the worker acknowledged buffer release and exited zero. MCU power
references returned to zero and every audio PCM remained closed.

Shutdown still logged the existing ten-second SLPI shutdown-acknowledgment
timeout, also present in both earlier receiver runs. The pinned kernel calls
peripheral shutdown after the graceful request, then publishes `OFFLINE`; this
test verifies that observed state and release ordering, not a successful
firmware acknowledgment. It also retained the earlier camera ION-unmap warnings
(ten per camera session). These issues remain separate from the zero controller
RPC return codes. Source excerpts and provenance are retained in the evidence
directory's `kernel-shutdown-source/`.

This verifies the helper with concurrent live sensors and SteamVR input. The
diagnostic head stream still used its mount-matrix fallback; the SteamVR HMD
channel was inactive, controller poses stayed invalid, and the compositor was
not started. Installed orchestration of a rendered session remains separate.

Evidence: `output/pico-controller-session-20261022-v1/`. The 93-file archive
`export-session.tar.gz` has SHA-256
`f49e0ff7d32e573dc028cb328bcfa6ae9d1f6a29346bc9a227fbf938572a343f`;
its inventory and every member hash were verified. `analysis.json` records the
asserted lifecycle order and counts. Full boot/DTBO readbacks matched before and
after the test. Stock-return and mute receipts record b1977, Wi-Fi off, updater
disabled and music/system volume zero. No partitions were written.

### Controller, live head tracking and compositor coexistence

RAM-only boot `b1d94af3-6102-4e95-b04e-02192a9f5c96` ran the same worker
and driver alongside the vendor head estimator, four cameras and Valve's Facet
compositor at the configured 120 Hz mode. The new `--left-controller` probe
observed a connected, readable left controller and valid head pose in 21 of 30
observations. The compositor trace contains 2,080 successful presentation calls
between the first and last connected observations, a 20.729-second interval.
These are API submissions, not measured optical frames or proof of Steam UI
visibility. The worker published 14,685 left records with zero RPC errors;
SteamVR input-update failures stayed zero. No physical button interaction was
verified, controller poses remained invalid, and sleep/wake acceptance is still pending.
The last nine observations reported the controller disconnected.

The full session failed at the head-camera feed, before successful dashboard
selection or scanout capture. The probe recorded 2,536 valid head queries and
464 invalid queries after tracking stopped. The retained camera ring and feed
failure record identify the rejected transition: frame 1741 at
`302419154468 ns` to frame 1747 at `302539157958 ns`, a `120003490 ns` gap
against the configured `100000000 ns` limit. The rejected set was only
`20421196 ns` old on arrival, with `52 ns` inter-camera skew and increasing
frame numbers and timestamps. Thus the gap check caused `-EPROTO`; camera
desynchronization and stale delivery did not cause that rejection. The cause
of the missing frames is still unverified. Do not raise the gap limit and call
this fixed: the next capture investigation needs request-refill timing and
complete scheduling coverage of the camera process under compositor load.

The parent closed the controller RPC clients, stopped the shared sensors and
SLPI, then verified worker buffer release and exit zero. MCU power references
returned to zero and the GPU minimum returned to 305 MHz. Audio stayed off.
Boot and DTBO readbacks retained their pre-test hashes; stock boot
`f5e84f7b-cf6c-4260-9264-364460f50e9a` was verified on b1977 with Wi-Fi off,
the updater disabled and music/system volume zero.

Evidence: `output/pico-controller-render-20261022-v1/`, including `analysis.json`
and its assertion-based analyzer. The 171-file `export-render.tar.gz` has
SHA-256 `4c2112cdf3592e1d381b332063c5f0fa76fef7495a6a56ac169d29c2f9998441`;
`export-camera.tar.gz` preserves the stopped camera ring with SHA-256
`0f771c115cdb800f2283d44542d3fcd08a1270f5f2b2a13dbde4ff69af955b76`.
The 59-file camera-source archive has SHA-256
`248386c7322879fbe376c2535a873ec44d3ef993872a26a58505c9d9a4896a05`.
All three archive inventories and member hashes were verified. The native probe
build matches its current source; 35 host controller, SteamVR and SLAM-feed tests
passed with no skips, and its host syntax check passed with warnings as errors.
This remains partial session acceptance, with no new optical or physical-motion
validation.

## Compositor and server setup

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

The drop-in also carries the tested diagnostic scheduling policy:
`SDL_THREAD_PRIORITY_POLICY=other`, `LimitRTPRIO=0`, `LimitNICE=-20` and
`RestrictRealtime=yes`. These avoid the observed SDL realtime-limit termination;
they do not constitute a finished low-latency scheduling profile. Transient
launches need the same properties and environment explicitly.

The compositor drop-in also sets `MESA_VK_WSI_FRAME_COUNTER_TIMING=1`. It requires
Turnip patch 0015 from this tree: the retained Frame compositor requests a private
two-word vblank counter/time pair. Unpatched Mesa reports success after writing
only the counter, causing uptime-sized vsync ages. Keep this opt-in scoped to
the compositor; the public Vulkan counter remains a one-word output. See the
[ABI and evidence](turnip.md#frame-compositor-counter-timing).

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

## Current hardware status

The current RAM diagnostic root is Fedora 44 with Frame's native ARM64 Steam and
SteamVR components. Migration to the installed Frame-based userspace remains
separate work; this is not a completed Frame OS image.

The native ARM64 Valve compositor renders Steam's setup UI into both eye views
with live vendor-SLAM head poses. The manual startup sequence needs `vrdashboard`
and an explicit dashboard selection; process startup alone does not show the UI.
The monitor uses the compatible Frame Qt 5.15 bundle. Both DMA planes and the DRM
timeline backport are required by the measured configuration.

Presenting the subsequent Linux login form also requires the opt-in
[gamescope shared-memory upload patch](../patches/gamescope/README.md) on the
measured Xwayland software path. An unmodified source rebuild remains on the
loading logo while the patched build puts the login form into stereo scanout.
The diagnostic client uses `-cef-disable-gpu` for its browser; Valve's compositor
remains GPU accelerated. This browser workaround alone does not fix stale
presentation, and it is not the final graphics-performance configuration.

Use the bundle's `gamescope.conf` only as a drop-in for the patched gamescope
overlay service. It sets `gamescope_vr_use_modifiers=false`, selecting gamescope's
Vulkan overlay texture transport. The measured launch also supplies
`--force-composition -e --backend openvr` and the named dashboard arguments.
This is separate from `compositor.conf`; the environment setting belongs to
gamescope. The per-buffer DMA import route retained gigabytes of gamescope-created
buffers in the compositor during the comparison. The Vulkan route bounds that
allocation in the 90-second test and presents an actual login-toggle change.
The driver builder bundles these opt-in files but does not install or enable
either service. See the verification record for exact results and limits.

Compositor scheduling remains diagnostic. At the supported 587 MHz GPU operating
point, sampled GPU work falls below the 120 Hz frame budget, but presentation
pacing remains unresolved. An API trace identifies a blocking four-query read
between each present submission and its present wait. Setting
`disableLinuxWaitForPresent=true` does not suppress these waits on the measured
direct-display path, even though OpenVR reads that setting successfully; it is
not added to the template. The original GPU policy is restored after each test.
A separate light direct-display test completes approximately 120 presents per
second. The compositor's lower cadence therefore needs investigation with its
actual rendering and scheduling workload; the query read alone is not proven
to explain it.

The legacy/Facet/legacy comparison raised submitted presents from 66–72 to about
103 per second while exposing a private counter ABI mismatch. Turnip patch 0015
fixes that mismatch. Two subsequent Facet runs submit about 98 and 104 presents
per second; sampled timestamps match the reported kernel vblank sequence within
9 microseconds. The template selects this corrected path. Some client counters
lag the latest kernel vblank, and 8 and 10 of 2,000 age checks still fail. The
subsequent reason-classifying probe identifies overdue updates in all 30 late
failures across three complete captures. The live
probe records renderer selection, timing phases, vsync age/counter and a bracketed
read-only kernel timestamp. `PICO_STEAMVR_VSYNC_RESULT` counts unavailable,
non-finite, negative or greater-than-two-period ages as invalid. These diagnostics
do not change its pose/dashboard exit criteria or establish physical display FPS.

The live pose reader now samples time after copying the channel, preventing a
concurrent publication from being mistaken for future data. Both corrected runs
receive 2,000 valid late client poses and no future-time driver rejections.
The subsequent ABI-2 two-slot channel removes the observed writer-contention
failure in its first native capture: the late observer records 48,188 successful
driver reads without rejections. Readers use the committed sample during an
in-progress write, with the same age and generation checks. Both processes need
the new ABI and a fresh mapping; see the [transport contract](pico-slam.md#pose-transport-to-steamvr).

The timing trace places those overdue updates after GPU completion and a wait
for another presentation boundary; the reported counter is two vblanks behind.
Ordinary-scheduler delay varies between the affected frames and is not the sole
established cause. The first realtime-permission experiment leaves the actual
render thread on ordinary scheduling. Later tests achieve `SCHED_RR` priority 99,
but still record late updates at 120 Hz. Matched 90 Hz tests with ordinary
scheduling submit about 89.5 presents/second and record zero and one overdue
sample per 2,000 late checks. The repeat's fault includes a measured 7 ms CPU
scheduling delay. Neither realtime permissions nor an experimental negative nice
value is adopted. The 90 Hz candidate changes both the optical profile's frame
interval and SteamVR's preferred rate; only transitions after a working 120 Hz
handoff have been tested. The template retains 120 Hz until first-handoff and
physical acceptance are verified. Sustained 120 Hz presentation remains unresolved.

Measured physical motion, clean lens output, controls and sustained performance
are still acceptance gates. Nothing installs or enables the driver automatically.

The [verification record](pico-steamvr-verification.md) contains the tests,
negative controls, measured limits and hash-verified evidence archives.
