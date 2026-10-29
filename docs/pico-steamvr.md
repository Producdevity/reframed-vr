# Native Neo3 SteamVR driver

`reframed_pico` is the physical Neo3 Pro Eye driver for Valve's native ARM64
SteamVR server and compositor. It is separate from `reframed_virtual` and does
not use Monado. Nothing enables or installs it automatically.

The [VR acceptance checklist](pico-vr-acceptance.md) tracks the remaining
physical clarity/IPD, jitter, controller, eye-tracking and foveation requirements
against the owner's working stock Android baseline.

For Steam's native VR main panel and toolbar, use the separate
[VR UI session guide](pico-steamvr-ui.md). It describes the required input seat,
gamescope forwarding patches and opt-in UI profile.

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
The column-major `rotation` maps view vertices onto the panel. SteamVR's
distortion query maps panel coordinates back to view coordinates, so the adapter
uses its inverse (transpose); using the forward quarter-turn there rotates the
image by an extra 180 degrees.
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

For a running, explicitly selected native Pico session, the read-only probe
mode `pico-steamvr-live LIBOPENVR BOOT_SERIAL SECONDS --view-frames` (1–30 seconds) logs raw and
standing HMD matrices and their origin transform once per second. It does not
change the tracking origin or show a dashboard. Matrix agreement can isolate a
software conversion error; it does not validate physical view orientation.

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

The physical driver registers separate left and right Neo3 controllers when both
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

The controller reports `poseIsValid=false` throughout. This input-only path supplies no controller position, orientation, haptics or
analog calibration. The bundled static render models are described below. Raw analog endpoints were captured but axis sign,
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
time. Success requires at least 100 valid head-pose queries and at least one
connected, readable controller state; exit code 10 indicates a missing controller
interface or no such state. It reports controller pose validity without inventing a pose.
It does not open the dashboard or start sensors. Correlate its timestamps with
the separate compositor trace to establish concurrent presentation; this probe
alone does not prove rendering, button interaction or wake-from-idle.

Boolean components are initialized once after activation, then updated only when
their requested value differs from the last successful publication. This follows
Valve's [component update contract](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md#updating-components).
Failed writes remain eligible for retry; disconnect and deactivation still
release active controls. Pose updates continue independently. The driver debug
response includes `input_calls` to distinguish input API calls from `updates` of
the controller as a whole. Fewer API calls alone do not establish a frame-pacing
or latency improvement.

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
desynchronization and stale delivery did not cause that rejection. That run
alone did not establish the missing-frame cause. The subsequent
[camera queue comparison](pico-steamvr-verification.md#camera-queue-starvation-under-compositor-load)
traces request starvation and tests immediate refill with the same gap limit.

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

For a system-manager compositor service running as `vr`, the drop-in also
creates the private cache directory `/var/cache/reframed-vr/pico-mesa` with mode
0700 and sets `MESA_SHADER_CACHE_DIR` there. `MESA_SHADER_CACHE_MAX_SIZE=512M`
bounds Mesa's disk cache to 512 MiB. Keep that directory on persistent Linux
storage. In the temporary RAM environment it needs an explicit verified restore
or persistent backing; setting the environment does not preserve RAM across a
reboot. Transient services need the equivalent `CacheDirectory`, mode and
environment properties. Preserve cache contents across normal session restarts;
Mesa keys entries by the relevant driver/shader identity.

The [restored-cache comparison](pico-steamvr-verification.md#restored-mesa-cache-comparison)
reduces the matched startup pipeline interval from 57.935 ms to 1.728 ms, with
zero overdue vsync samples in its first 500-query readiness and 2,000-query late
windows. This is a bounded comparison, not a sustained frame-rate or optical
acceptance result. The separate occasional late blocking fault remains open.

Treat a restored cache as build-specific input. In the later
[build-matched control](pico-steamvr-verification.md#build-matched-cache-control-2026-10-26),
the old 189-entry carrier has a different Turnip namespace from entries generated
by the current library. Restoring the current run's 354 exact files with the
same library and cache environment reduces startup overdue reads from 4/500 to
0/500. Later missed presentations remain. Preserve the library/build and actual
environment receipts when reusing a cache; file presence does not prove hits,
and editing keys or headers does not establish compatibility.

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
scheduling delay. Neither realtime permissions nor the compositor's experimental
negative nice value is adopted. The 90 Hz candidate changes both the optical profile's frame
interval and SteamVR's preferred rate. A fresh Linux boot now starts 90 Hz after
the maintained 120 Hz display-handoff tool initializes and releases KMS; no
120 Hz SteamVR session is needed first. Omitting that handoff produced an
`EINVAL` atomic swapchain test and compositor crash. The fresh 90 Hz run has
zero overdue ages in its late 2,000-query window, but six in its two earlier
500-query readiness windows. This is a stable late sample, not an all-session
timing fix. The template retains 120 Hz pending physical 90 Hz acceptance.
Sustained 120 Hz presentation remains unresolved.

For this 90 Hz candidate, run `pico-display-handoff --boot-serial-file
/etc/reframed-vr/pico-boot-serial` as root before starting the VR server/compositor, or require the packaged `reframed-pico-display-handoff.service`
from the session owner. The helper adopts the advertised 120 Hz mode, verifies
five hardware vblank events, then disables the CRTC and releases its resources.
Set the private optical profile's `screen.frame_interval_ns` to `11111111` and
the session's `steamvr.preferredRefreshRate` to `90.0` together. Preserve the
unit's optical coefficients and eye transforms. Initialization at 120 Hz and
subsequent rendering at 90 Hz serve different purposes. The
[fresh-boot verification](pico-steamvr-verification.md#fresh-90-hz-handoff-and-controller-tracker-calibration)
records the tested limits; clean lens output at 90 Hz remains unverified.

### Bounded GPU callback priority

The Neo3 timing trace identifies late `kgsl-events` callback dispatch after GPU
retirement as a cause of missed presentation boundaries. The opt-in
`tools/pico-gpu-events.py` helper selects nice -20 for that queue's unbound
worker pool while a bounded VR session runs. This is a CFS priority setting;
the default mode retains the existing queue CPU mask and concurrency.
A native combined capture verifies reduced callback latency; see the
[control and acceptance limits](pico-steamvr-verification.md#kgsl-fence-callback-dispatch-2026-10-23-utc).

Run the helper as root in native Pico Linux, using the session's independently
verified serial and boot UUID:

```sh
python3 tools/pico-gpu-events.py --boot-serial c980c8d4 \
  --boot-id 'VERIFIED_NATIVE_BOOT_UUID' --seconds 240
```

Wait for `PICO_GPU_EVENTS_READY` before starting the bounded VR workload. Stop
that workload before the helper's deadline, then send it SIGTERM or let its
bounded wait finish. `PICO_GPU_EVENTS_RESTORED` records the original policy
readback. Session owners can instead wrap their workload and cleanup in
`prioritize_events(serial, boot_id)` from the same module; its context restores
the policy on exceptions. A private exclusive lock prevents overlapping owners.
The helper checks the native Neo3 compatible string, boot serial and UUID before
changing the queue. It is not enabled automatically by the driver bundle.

For the optional CPU-affinity experiment, add `--cpu-mask f0`, or pass
`cpu_mask='f0'` to the same context owner. This selects CPUs 4–7; `--cpu-mask 0f`
selects CPUs 0–3 instead. Both require
checking the native Neo3's MIDRs, relative capacities, maximum frequencies,
online CPUs and whether the global workqueue mask includes the selected cluster.
The original queue must have
nice 0 and mask `ff`. The receipt records intermediate pool mappings; each
attempted attribute write is restored independently on exit, with boot/queue
identity and final readback checks. Individual worker policies and IRQ handling
are outside this operation.

The [native affinity experiment](pico-steamvr-verification.md#optional-callback-affinity-2026-10-26)
verifies callback placement and zero steady-window missed vblanks in one run.
Its p99 callback delay increases and startup-age faults remain, so this option
is experimental. A [fresh comparison](pico-steamvr-verification.md#callback-cluster-comparison-2026-10-27)
records four missed presentations with `f0` and two with `0f`, with mixed callback
latency tails. Neither mask is a verified pacing fix; the default mask policy
is unchanged.

### Optional tracked controller input

The physical driver accepts `PICO_STEAMVR_LEFT_POSE_CHANNEL` and
`PICO_STEAMVR_LEFT_POSE_INSTANCE`, with corresponding `RIGHT` variables for the
other hand, alongside the existing digital-controller settings. Each hand's
path/instance pair is optional independently and must be complete if supplied.
The absolute path must name a regular,
trusted-owner ABI-2 SLAM channel with no group/world write permissions; the
instance is a nonzero 16-digit lowercase hexadecimal identifier distinct from
the HMD and other selected controller instances. The HMD channel's inode and
aliases between controller pose files are refused. Each controller reader binds
the HMD generation and universe, with the same maximum pose age (at most 100 ms).

The producer must supply the controller origin in metres in the current HMD
world. The reader applies no head/eye extrinsic, arm model, prediction or default
position. Both the digital input and pose must be current. Tracking loss,
disconnect, stop or a generation mismatch publishes an invalid pose; `GetPose`
and the debug query recheck freshness instead of reviving a cached result.
Without a hand's optional settings, that controller retains digital-only operation
and an invalid pose.

The 2026-10-29 RAM test registers both hands in the real server, loads both
models and reads fresh right-hand input through the per-hand probe. Fourteen
focused host tests and four ARM64 Linux sanitizer suites pass, including
independent pose bindings, cross-hand alias refusal and one-hand disconnection.
These do not validate optical acquisition: all 3,319 sampled SDK result pairs
still have state zero, and pose publication remains disabled. The full native
regression and its separate timing limits are recorded in
[`pico-steamvr-verification.md`](pico-steamvr-verification.md).

The seven host SteamVR test suites pass, and the updated driver builds on the
Pico's native ARM64 Linux userspace. Its native controller harness passes under
UBSan, including fresh pose values, stale poses with still-connected input,
invalidation/recovery, disconnect, stopped/wrong generations and incomplete
bindings. These are adapter tests with mocked OpenVR callbacks. The separate
recorded-data tracker replay does not establish a live controller pointer or
verified grip/aim calibration. Evidence is retained in
`output/pico-controller-integration-20261023-v1/`.

Measured physical motion, clean lens output, controls and sustained performance
are still acceptance gates. Nothing installs or enables the driver automatically.

The [verification record](pico-steamvr-verification.md) contains the tests,
negative controls, measured limits and hash-verified evidence archives.

## Neo3 controller render models

The driver registers separate left/right Neo3 models from
[WebXR Input Profiles](https://github.com/immersive-web/webxr-input-profiles/tree/f4992299601614adbfefd398dc8e281556bb7444/packages/assets/profiles/pico-neo3).
The asset package's MIT license is retained in
`system/steamvr-pico/resources/rendermodels/LICENSE`. The pinned revision and GLB
hashes are in `profiles/pico-controller-models.json`; converted-file hashes and
modifications are recorded beside the models in `provenance.json`.

The converter requires Pillow (`python3-pillow` in the development container;
`python3 -m pip install Pillow` in a host virtual environment). To reproduce
the static models from those two pinned GLBs, run:

```sh
python3 tools/convert-pico-controller-models.py --source /path/to/pico-neo3 \
  --output /path/to/new/rendermodels
```

The converter preserves the original right-handed, metre-scale grip origin,
flattens the default component transforms, flips texture V for OBJ and decodes
the embedded JPEG into PNG. Each model has 3,488 triangles and about 2,550
vertices. Geometry, normal/index validity, mirrored bounds and provenance hashes
pass host checks. SteamVR's native render-model API loads both meshes and their
512×512 textures on the Pico. The loader adds two components to the four supplied
components, so clients must enumerate names rather than require a count of four.
Evidence: `output/pico-ui-quality-20261023-v1/native/test-models-only-result.log`.

The models have identity `tip`, `grip` and `handgrip` components. These are
explicit placeholders for pose-offset calibration, not calibrated pointing
directions. Registering or loading a render model does not validate a controller
pose, enable pose publication or establish visible tracked pointing.

## UI resolution and frame-history diagnostics

The build also bundles `steamvr-ui-90hz.vrsettings`, from
`profiles/pico-steamvr-ui-90hz.json`. This opt-in profile requests a native-size
1832×1920 internal system layer per eye and manual application scale 1.0. The
normal template remains unchanged. Select the 90 Hz hardware mode and a private
optical profile with `screen.frame_interval_ns=11111111` before using it; the
settings file alone does not change the panel mode or the driver's timing.

An optional `steamvr-ui-72hz.vrsettings` is also bundled. It retains the same
resolution but requests 72 Hz; pair it with a private optical profile using
`screen.frame_interval_ns=13888889` and verify the selected hardware mode.
The [bounded comparison](pico-steamvr-verification.md#optional-72-hz-ui-profile-2026-10-25)
shows improved stationary pacing, without establishing lens clarity or lower
motion latency. Neither option replaces the normal template.

Application supersampling and the internal system-layer size are separate in
this retained Valve runtime. On the Pico, manual supersampling changed the
application recommendation to 1832×1920 while the system layer remained
1544×1616. Explicit `systemLayerWidth` and `systemLayerHeight` settings changed
the allocated textures to 1832×1920. These are runtime-specific controls, checked
against its allocation log, rather than assumptions about other SteamVR builds.

The current gamescope build has a 1920×1080×4-byte upload buffer. A software
Steam surface at 1920×1200 exceeds it and aborts gamescope. Do not use that size
with the pinned build. A surviving compositor, a cached visible overlay or a
zero diagnostic-runner exit code does not establish that Steam is still live.
The session must also retain an active gamescope process and fresh UI content.

The physical probe can record overlapping 128-frame compositor histories once
per second while observing an already running dashboard:

```sh
pico-steamvr-live LIBOPENVR BOOT_SERIAL 30 --dashboard OVERLAY_KEY --frame-history
python3 tools/analyze-pico-frame-pacing.py CAPTURE.log --refresh 90
```

The analyzer deduplicates by frame index, retains the latest presentation counts
and reports missing indices. Do not combine different compositor sessions in
one log. GPU time, presentation intervals and reported drops are software
observations; none measures photon latency or proves legible text through the
lenses. Resolution, pacing and controller-camera acceptance are recorded
separately in the [hardware verification log](pico-steamvr-verification.md).

### Holding the diagnostic probe before sampling

`pico-steamvr-live` accepts the optional environment variable
`PICO_STEAMVR_PROBE_GATE`, an absolute Unix stream-socket path. After OpenVR
initialization and any dashboard request, the probe connects and waits for one
byte, `G`, before its begin statistics and pose/vsync sampling loop. Without the
variable, it starts sampling immediately. Missing, rejected, closed or timed-out
gates fail the probe; they do not silently start an untraced sample window. The
connection and release read each have a five-second socket timeout.

The trace controller should own a private parent directory, grant the `vr` user
access to its socket, accept the connection, and validate the actual peer PID
and UID. While the probe is held, record its process/start identity and tasks,
select the required client/server worker identities, enable tracing, then send
`G`. Initialization before this barrier is outside that capture. The socket is
an observation barrier, not a tracking-readiness or presentation-success signal.

This supports investigating the publication gap seen in the October 26
startup trace: API sample 405 returns counter 3122 even though the retained Mesa
trace already returned 3124 about 122 microseconds earlier. It does not establish
which publication stage delayed the value. The existing runtime-owned display
timing remains the source; the probe does not publish vsync events.

Real Unix-socket tests cover release, rejection, EOF, timeout, disabled operation
and invalid paths on macOS and Linux ARM64. The complete updated probe compiles
on Linux ARM64. Applying the barrier to a headset startup trace and qualifying
its newly selected worker coverage remain the next experiment; the independent
October 27 headset control used the preceding probe binary.
