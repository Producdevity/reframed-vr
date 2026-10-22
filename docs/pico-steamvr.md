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
the Frame sensor driver and motion smoothing. It explicitly selects the tested
legacy renderer and disables `renderSystemLayerInDistortPass`: the measured
Facet path has invalid client vsync ages, and the layer option crashes the legacy
compositor. These settings are specific to the retained runtime and Neo3 path;
Frame's renderer settings are not interchangeable defaults. Provide all of:

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

The drop-in also carries the tested diagnostic scheduling policy:
`SDL_THREAD_PRIORITY_POLICY=other`, `LimitRTPRIO=0`, `LimitNICE=-20` and
`RestrictRealtime=yes`. These avoid the observed SDL realtime-limit termination;
they do not constitute a finished low-latency scheduling profile. Transient
launches need the same properties and environment explicitly.

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

The subsequent legacy/Facet/legacy comparison raises submitted presents from
66–72 to about 103 per second at the same bounded 587 MHz request, while exposing
the Facet client-timing failure. That candidate and two ineffective driver-vsync
workarounds are not adopted. The physical probe now records renderer selection,
GPU/CPU timing phases and vsync age/counter, and checks vsync age at its 100 Hz
sampling rate. Its `PICO_STEAMVR_VSYNC_RESULT` counts unavailable, non-finite,
negative or greater-than-two-period ages as invalid. These diagnostics do not
change its pose/dashboard exit criteria or establish physical display cadence.

Measured physical motion, clean lens output, controls and sustained performance
are still acceptance gates. Nothing installs or enables the driver automatically.

The [verification record](pico-steamvr-verification.md) contains the tests,
negative controls, measured limits and hash-verified evidence archives.
