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
a standalone `reframed_pico` driver directory and a physical-headset client probe,
and records source and artifact hashes. OpenVR and cJSON license notices accompany
the bundle. No unit-specific coefficients enter the build or repository.

The cJSON source is the existing vendored dependency in the pinned Monado source
tree; this does not link Monado into the driver. PicoFrame's PICO 4 driver was a
reference for separate Bionic tracking and Vulkan direct-display integration.
Neo3 calibration and pose conventions are established separately.

Register the resulting `reframed_pico` directory in the session's OpenVR path
registry, select `steamvr.forcedDriver = "reframed_pico"`, and provide all of:

| Environment variable | Required value |
| --- | --- |
| `PICO_STEAMVR_BOOT_SERIAL` | Exact native `androidboot.serialno` |
| `PICO_STEAMVR_OPTICS` | Private, validated Neo3 optical-profile file |
| `PICO_STEAMVR_POSE_CHANNEL` | Readable mapping created by this capture owner |
| `PICO_STEAMVR_INSTANCE` | Nonzero process-instance identifier, 16 lowercase hex digits |
| `PICO_STEAMVR_GENERATION` | Nonzero estimator generation, 16 lowercase hex digits |
| `PICO_STEAMVR_MAX_AGE_NS` | Explicit maximum pose age, at most 100 ms |

Use an unprivileged SteamVR user with the required DRM/KGSL access. A root-owned
producer can share its mapping read-only with that user's group. Its private
directory must permit traversal without exposing calibration to other users.
The isolated Bionic filesystem namespace must bind the executable, dependencies
and shared mapping paths explicitly. Never truncate or reuse a mapping held by
an existing driver.

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

SteamVR activation, live HMD queries, compositor presentation, clean lens output,
measured motion scale/direction and usable Steam UI remain hardware acceptance
steps. The default configuration remains disabled until explicitly supplied.
