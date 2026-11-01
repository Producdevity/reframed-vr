# Neo3 Pro Eye eye tracking: stock baseline

No native eye-tracking stream exists yet. This records the stock b1977 (5.8.4.0)
implementation observed read-only on this unit on 2026-11-01, as the reference
for a native port. Nothing here was started, enabled or changed.

## Stock service

`pxreyetrackingservice` runs as root from `/system/bin` (class `core`) and
registers the Binder service `pvr.IEyeTrackingService`. Its dump reports the
eye camera present, eye tracking (ET) and face tracking (FT) switched off, no
latency samples for its cameras 4 and 5, and neither ET nor lip sync started.
`persist.pvrservice.eyetracking_autorun` is 1 and `ro.pxr.eyetracking.support`
is 1. The Tobii user-calibration app (`com.tobii.usercalibration.neo3`) and
`com.picovr.PicoEyeTracking` are installed.

The IPD properties differ from the earlier stock dump recorded in the
[acceptance notes](pico-vr-acceptance.md): `persist.pxr.ipd.enable=1`,
`persist.pxr.ipd.status=2`, `sys.pxr.ipd.distance.value=0.136820` and four
`sys.pxr.ipd.offset.*` values. Their units and their relationship to rendering
are not established; they must not be used as a replacement IPD.

| Library | Role from its dependencies |
| --- | --- |
| `libpxreyetrackingservice.so` | Service core: camera provider HIDL, HMD service client, notifications |
| `libpxreyetrackingcamera.so` | Eye-camera capture through the camera provider HAL 3.x and the shared `libpvrtrackingcamera.so` |
| `libpxreyetrackingcamctl.so` | Camera control front end |
| `libpxreyetrackingbuffer.so` | Frame buffering |
| `libpxreyetracking.tobii.so` | Tobii integration; uses `libcdsprpc.so`, `ioctl` and `mmap` |
| `libtobii_stream_engine.so` | Tobii Stream Engine |
| `libeyetrackingclient.pxr.so` | Client API for applications |

The camera provider exposes five devices (`legacy/0`–`3` and `legacy/6`).

## Native route

The dependencies mirror the head-tracking path that already runs natively:
camera frames from the shared tracking-camera stack, and a vendor algorithm
library that offloads to the compute DSP through FastRPC. A port therefore
needs the two eye sensors brought up in the native camera pipeline with their
IR illumination, the Tobii libraries hosted under the Bionic linker with CDSP
access, and the factory eye calibration located and preserved. Gaze must then
be exposed to SteamVR with validity and timestamps, before any IPD or
foveation use.

The stock binaries and their hashes are retained privately in
`output/pico-eye-tracking-inventory-20261101-v1/`.
