# Pico visual-inertial tracking

The offline tracking path uses native ARM64 Basalt through VIT 2.0.1 and the
pinned Monado frame/IMU interfaces. Basalt and its required dependencies are
pinned in `profiles/basalt.json`. This backend is not enabled automatically on
a headset: camera capture, active calibration, sensor axes and clock alignment
must be established first.

## Physical Neo3 capture status

The 2026-10-20 investigation captured all four camera calibration files and the
IMU calibration privately from the Neo3 Pro Eye running b1977. The current cam0
and IMU files match the retained backup hashes. Stock declares its four tracking
cameras as OV7251 devices in slots 2–5, with 8-bit bus addresses `e2/e4/e6/e8`;
the corresponding camera module files match the previously decoded firmware.
These declarations do not establish a successful silicon-ID read or the mapping
from physical slots to SLAM camera indices on their own.

Native Linux matched 134 stock device-tree properties for slots 4/5 and their
PHYs, queried the ISP and camera capabilities, and accepted both probe calls.
Source inspection then established that `cam_sensor_match_id` returns success
without reading the chip ID for tracking-camera SIDs. Probe success must not be
used as evidence of sensor communication. The first actual initialization write
to `e6` failed with a CCI NACK; that direct CCI attempt produced no stream.

The stock camera path uses QuickCamera's MCU control and `cam_virtual_mono`
bridge. That bridge is absent from the retained public kernel. Native capture now
uses MCU sensor control with a bus-info-only kernel configuration packet,
rather than direct CCI initialization against the tracking addresses. The native CDM
context also rejects shared command memory; I/O command mapping passed that
allocation stage before reaching the separate CCI failure. Kernel-generated CDM
commands also require uncached allocations on this kernel.

The maintained setup and shared event dispatcher have now captured 247 frames
from each of all four cameras over five seconds under native Linux. Two stereo
sessions use slots 4/5 on PHYs 2/4 and slots 2/3 on PHYs 5/3; four distinct ISP
inputs were acquired and both groups stopped cleanly before MCU stream-off.
The camera QTimer-to-monotonic mapping was measured against the CPU counter.
The first retained images were almost black. Enabling the MCU's dual exposure
mode and applying both exposure groups revealed scene content in one camera;
the other three views remained dark. That recording was not a usable
four-camera VIO input. Later uncovered-room captures below supersede its image-quality result.
Exposure-center correction and optical camera-to-calibration ordering still
require physical validation.

The maintained station encoder now selects the stock
`CameraInitWithReg4323` mode. Native capture verified 347 frames per camera over
seven seconds: 174 head frames and 173 hand frames each. Embedded RAW8 metadata
identified the alternating frame types and confirmed the requested 600-line
exposure and gain 128. Exposure-only initialization reports a zero type tag and
cannot distinguish these streams. `pico_camera_metadata_raw8` normalizes the
stock type tags and rejects unknown tags and zero exposure/gain. This proves
parameter delivery in the image; the single-register MCU reads remain
insufficient evidence because the firmware ignores their I2C error status.

The module inspector now retains each configuration's 16-bit `camera_id`.
An offline ARM64 oracle loaded the actual Neo3 CamX module parser and called
`ImageSensorModuleData::GetCameraId`; all four results match the inspector:

| Module | Bus address | CamX ID | Expected aggregate SLAM index |
| --- | --- | --- | --- |
| `pico_ov7251_left` | `e2` | 2 | 0 |
| `pico_ov7251_right` | `e4` | 3 | 1 |
| `ov7251_slave` | `e6` | 4 | 2 |
| `ov7251_master` | `e8` | 5 | 3 |

The expected final column follows the Neo3 library path: QuickCamera retains
the module IDs; `PvrCameraManager` traverses its camera map in key order and
collects the tracking module types; aggregate `PvrQuickCamera` assigns successive
native IDs when constructing those devices. Its frame callback writes that
native ID into the frame item. This supports the diagnostic's slot-minus-two
mapping; it is a source-derived mapping, not a physical calibration check.
Individual-camera opens take a different path and must not be assumed to apply
the aggregate remapping. Retained Ghidra addresses from another CamX build were
not used for the oracle; its entry points came from this ELF's symbols.

## Native vendor SLAM bring-up

The actual b1977 `libSlam.so` now starts under native Linux with the headset's
Bionic loader and library dependencies in a separate process. The compute DSP
and its default listener are running, and the algorithm successfully opens both
`libslamDSP_skel.so` and `libpico_cv_dsp_skel.so`. No Android framework services
are started. A private filesystem namespace supplies the original configuration
paths, read-only copies of factory calibration, and writable maps in RAM.
Ordinary calls work through the PicoFrame path shim, but that shim alone did
not satisfy all of this library's filesystem operations.

A live input run paired 8,444 actual accel/gyro samples at matching timestamps
and received 8,444 result callbacks. All results had state 1 and confidence 0;
no images were supplied and no positional tracking was established. The
quaternion norms ranged from 0.999999935 to 1.000000114. The SSC decoder now
retains the optional fourth component without naming its meaning. The vendor
input uses the accelerometer's fourth value, matching the Neo3 service's
seven-double IMU construction; host bias correction is not applied again.

The Neo3 exports `update6AxisIMU` and `destroyHandle` have no meaningful integer
return status. Their disassembly and the live callbacks ruled out treating the
return register as an error code. `stopAlgorithm` and explicit handle destruction
completed in the bounded live run. Unloading the vendor library afterward hung
until the diagnostic alarm fired; the live helper therefore keeps the library
loaded for its process lifetime and exits after explicit destruction. This is
not proof of reusable in-process unload support or CVP image processing.

The first combined native run delivered 249 synchronized four-camera head-frame
sets and 12,540 matched IMU pairs to the vendor algorithm. It reported nonzero
image feature counts, but every pose callback still had confidence 0. Both ISP
groups stopped cleanly, the MCU stream stopped and its power reference was
released, and the SSC producer joined without overflowing its ring. Missing
library messages were traced to system performance reporting and PXR
notifications; they are not evidence of a missing image-processing dependency.
No Android framework services were started to satisfy those optional paths.
Three retained camera views in that run were almost black; that recording did
not establish tracking with a well-lit, uncovered view or physical motion.
The diagnostic does not publish positional poses to a VR runtime.

A second combined run explicitly withheld images until the IMU input covered
their corrected timestamps. All 249 sets were already covered by 12.1–18.4 ms;
none needed to wait. It delivered 12,541 IMU pairs and callbacks, again with
confidence 0, and stopped cleanly. This rules out images arriving ahead of the
IMU in that run, but does not physically validate the exposure-center constants.
In the retained 640×480 images, only 6, 10 and 10 pixels exceeded value 16 in the
three darkest views, respectively. Repeating that unchanged scene could not
validate tracking. The later captures below supplied usable scene detail and included a physical motion check.

After returning to stock b1977, its post-boot SLAM logs also showed nearly zero
keypoints in three views. The last logged four-camera counts were 0, 134, 0, 0,
with all four exposure values at 737 lines. Twenty-eight such frame summaries
were retained with monotonic log timestamps and the new stock boot identity.
This corroborates the lack of usable scene detail beyond the native capture
path; it does not identify darkness or obstruction as the physical cause.
Stock subsequently went to sleep and destroyed its SLAM instance. The sleeping
service's diagnostic pose fields are not used as tracking evidence.

The b1977 result packet is 0x170 bytes: a little-endian nanosecond timestamp,
three position doubles, then a quaternion in **w, x, y, z** order. The state and
confidence bytes are at 0x40/0x41, with a 32-bit error field at 0x44. The maintained
`pico_slam_result_decode` checks timestamp and numeric validity and exposes the
quaternion as x, y, z, w. It preserves status values without assigning meanings
to unknown codes, and successful decoding does not establish tracking validity.
All 12,541 retained results decode; their error field changes from 32 to 4 while
confidence remains zero. Those error values have not been named from evidence.

This quaternion layout was checked against the actual Neo3
`libSlamTools.pxr.so`, called by its service's `newTracker::convertSlamResult`.
An offline ARM64 test passed eight chosen poses and 1,024 additional normalized
quaternions through the library with prediction disabled. Its SDK conversion
maps the quaternion vector part to (-y, x, z) and also applies an orientation-
dependent position offset. The decoder deliberately retains the raw SLAM frame;
the SDK conversion is not evidence of the correct OpenXR world frame or the
physically calibrated head offset. Neither the oracle nor packet replay proves
live positional tracking.

### Uncovered-room and motion captures

Later on 2026-10-20, the owner confirmed working stock positional tracking,
cleared all four outward cameras and faced the headset toward a lit room. A fresh
native Linux RAM boot captured recognizable scene detail in all four head-frame
images. Both camera groups stopped cleanly and released the MCU power reference.
The first capture used 600 exposure lines and gain 128; two views had substantial
saturation. The following combined runs kept 600 lines and lowered gain to 32.
This change and the different physical scene prevent attributing the earlier
failure to one cause alone.

The maintained vendor feed and result decoder then ran against the actual b1977
library, private factory calibration and live CDSP under native Linux:

| Capture | Four-camera head sets | IMU pairs / pose records | Confidence 1 records | First confidence 1 |
| --- | --- | --- | --- | --- |
| Stationary | 249 | 10,776 | 8,148 | 2.567 s |
| Owner motion | 249 | 10,753 | 8,149 | 2.543 s |

Every retained packet decoded, and all timestamps increased. Both runs changed
from `(state, confidence, error) = (1, 0, 32)` to `(1, 1, 512)` without a later
confidence drop. The last tuple also appears in the fresh working stock logs;
the field named error remains opaque, so 512 is not interpreted as a fault.
The result callbacks ran at approximately 1,024 Hz; camera head sets arrived at
25 Hz. Callback rate is not a measurement of independent visual updates.

After initialization, the stationary run covered 7.957 seconds. Maximum
translation from its first confidence-1 pose was 0.000268 in vendor position
units, with axis ranges 0.000213/0.000296/0.000358 and at most 0.0244 degrees of
orientation change. These are short-term estimator stability measurements,
not independently measured physical accuracy.

The owner performed an approximate sideways movement, return and gentle
rotation by feel. The recording contains translation and rotation: confidence-1
axis ranges were 0.0748/0.2270/0.0704 vendor units, with at most 8.93 degrees of
orientation change from its first confidence-1 pose. Its endpoint was still
moving and 0.2419 vendor units from that initial pose; the capture does not
establish a completed return, measured scale, axis alignment or loop closure.
It establishes a live positional response under native Linux, independently of
an Android framework session. No positional pose is published to SteamVR yet.

### Runtime pose conversion

`pico-slam-pose` converts the decoded result to an explicitly configured head
frame without depending on Monado or OpenVR. The caller supplies the raw pose's
transform direction, metres per vendor unit, `T_world_slam`, `T_body_head` and
current monotonic clock uncertainty. It composes the complete transforms,
including the rotating head lever arm; an inverse pose inverts translation as
well as orientation. It does not infer an axis convention, metric scale,
head offset or world origin from a plausible-looking quaternion.

Only the observed b1977 state 1 / confidence 1 combination passes. Unknown
statuses, non-finite or malformed transforms, future/stale times and excessive
uncertainty are refused without changing the caller's output. The opaque
vendor error field is preserved by the decoder and does not become a guessed
failure code. A fresh stationary position at exactly zero remains valid.

Synthetic transform and validity cases pass address/undefined-behavior
sanitizers. Replay of the retained one-minute capture passes all 61,905 records
on the host and under the actual Pico Bionic loader in an isolated ARM64 Linux
container; exactly 59,342 confidence-1 records pass the gate. That replay uses
explicit identity test transforms and does not establish physical OpenXR axes,
metric scale, head extrinsics or live runtime publication. Private build and
replay evidence is retained in `output/pico-pose-runtime-20261021-v1/`.

PicoFrame's separate Bionic SLAM process and SteamVR consumer are useful
architectural references. Its PICO 4 `SlamTracker` uses a different pose contract
and estimates orientation conventions; those guesses and hardware constants
are not used as Neo3 calibration.

The carrier archive in `live-20261020-v1/vio-export.tar.gz` is 4,198,518 bytes,
SHA-256 `75014c026bf06cc067c45acd93b344d559599b4bace093e08412e87ccba1545d`.
Its embedded manifest verifies all 20 exported members, including both complete
pose streams, component logs and eight camera images. The carrier, member
receipts and analysis remain private under the evidence directory below.

### Maintained vendor input feed

`pico-vendor-slam-feed` now owns the input-side behavior previously confined to
the private diagnostic. It accepts raw SSC events, pairs only equal ticks and
mapped times, and preserves the seven-double Neo3 input without applying host
bias correction. Complete four-camera head sets are copied into owned RAW8
storage, including padded rows and stock's metadata-row replacement. Camera
calibration IDs and corrected monotonic times must be supplied explicitly.
There are no built-in camera-order, clock-offset or exposure-center defaults.

Images must follow the first delivered IMU and wait until the lower uncertainty
bound of later IMU covers every camera center's upper bound. Sets preceding the
available IMU history are refused. Stale input, time regressions, stream gaps and
queue exhaustion permanently stop that feed; callbacks from older generations
cannot affect it. Calls are serialized by its process owner. The feed starts no
hardware or vendor algorithm and publishes no poses.

The vendor feed holds at most 256 unpaired IMU samples per sensor. SSC can
deliver accelerometer and gyroscope events in separate bursts: the earlier
32-sample bound stopped a native SteamVR run with `ENOBUFS`. Its counters show
the failure on the 33rd unpaired input, while only one camera set was pending
against an eight-set limit. The retained stream contains the corresponding
gyro burst; the failed record itself was overwritten after the consumer stopped.
The larger queue changes neither sample freshness nor the maximum IMU gap,
matching rules or terminal failure policy. A synthetic regression covers
56-sample bursts in either sensor order, rejects an expired partner batch and
still stops at the new finite capacity. This host check does not establish
sustained headset tracking.

With that change, a subsequent combined run reaches 69,921 matched pairs without
`ENOBUFS`, then fails closed with `ETIMEDOUT` while five camera sets await IMU
coverage. The IMU producer reports stopped accelerometer delivery; both DSPs
remain online. This is a separate unresolved delivery/stall failure, not evidence
that increasing capacity makes the whole session stable. The manifest-checked
archive is `output/pico-steamvr-session-20261022-v2/export-shm-ready.tar.gz`,
SHA-256 `a6f11cc3c483c3ac95178db66e00e3d5529d6010fa008e0807334828823eb66b`.

The default lifetime policy keeps pixel storage and vector metadata until the
caller has stopped and destroyed the vendor backend. It retains at most 384
sets (about 450 MiB of pixels) and eight pending sets, stopping at either limit.

`PICO_VENDOR_SLAM_COPY_ON_RETURN` permits continuous delivery only when the
selected backend has a verified synchronous copy contract. In the actual b1977
`libSlam.so` (SHA-256
`1e3d9ee89d17cc9ddbb6939f12a289391ded15bde54121b81308a6db6f184594`),
the `updateImage` call path copies image rows and scalar metadata into internal
storage before returning; its image-copy dispatcher calls the copy body
synchronously. A native guard test supplied each of 249 sets from separate
page-aligned storage and changed both pixels and vector metadata to `PROT_NONE`
immediately after the call. Those pages stayed protected through backend
shutdown: 10,720 pose packets decoded, 8,148 reached confidence 1, and no late-read
fault occurred. This evidence applies to that library build, not arbitrary
PicoFrame, Neo3 or future vendor libraries. Elapsed time alone never establishes
safe buffer retirement.

In copy-on-return mode, the feed releases each delivered set after the call and
keeps undelivered sets in its bounded queue. An initial longer diagnostic stopped
at 35 seconds because its systemd service still carried the short-run time
limit; the camera ring then filled after its consumer stopped. The corrected
service limit allowed the intended 60-second camera run to finish normally:

- All 1,499 four-camera head sets were consumed, with 61,905 decoded pose records.
- Confidence reached 1 after 2.503 seconds and remained 1 for the other 59,342
  records, covering 57.956 seconds. Every timestamp increased.
- After warmup, 53 one-second process samples showed 57,436–58,160 KiB RSS and
  15 threads. Delivered sets were not retained; the final pending count was zero.
- The stationary position varied by at most 0.000541 vendor units from its first
  confidence-1 pose, with at most 0.0195 degrees of orientation change.
- Both ISP groups stopped, MCU stream-off succeeded, the MCU power reference
  returned to zero, and the SSC producer joined without a ring overflow.

The corrected run's private `soak-export.tar.gz` carrier is 9,514,181 bytes,
SHA-256 `56dc0030fa220f46183a19f1570d2f6d4a44dd0d1aae79082e275f78007dc05f`.
All 18 exported members match the embedded manifest. This establishes a bounded
one-minute native tracking session, not long-session stability, measured
position accuracy, relocalization or SteamVR pose integration.

The feed passed 100 delayed-read ownership cycles and 50 failure scenarios
under host address/undefined-behavior sanitizers and again under the actual
stock Bionic loader in an offline ARM64 container. The private diagnostic
consumer links this feed and the maintained result decoder; the two physical
runs above now validate that combination against the actual vendor backend.
The sanitizer checks themselves use a modeled backend. The new lifetime mode
also passed 1,000 deliveries through a two-set budget, including queued delivery
order and cleanup with an undelivered set, under host sanitizers and the actual
Bionic loader on the headset. Run the host checks with:

```sh
python3 -B -m unittest discover -s tests -p test_pico_vendor_slam_feed.py
```


Evidence, private calibration hashes, exact library versions, diagnostic sources
and native logs are retained under
`output/pico-recovery-bringup-20261018-v1/neo3-6dof-v1/`. BOOT and DTBO readbacks
still match the preserved originals. Native camera DMA/fence delivery and a
positional estimator response are now established for short captures and a one-minute continuous session. Longer
operation, calibrated head/world conversion, loss/recovery and runtime pose
publication remain unverified.

## Build

Build an ARM64 compiler image from the project's Monado tools image, then pass
its immutable image ID to the builder:

```sh
docker build -f Containerfile.basalt -t localhost/reframed-vr:basalt-tools .
python3 -B tools/build-basalt.py prepare --output output/basalt-source-new
python3 -B tools/build-basalt.py build output/basalt-source-new/source \
    --image sha256:LOCAL_IMAGE_ID --output output/basalt-build-new
```

Source preparation fetches exact commits and verifies the complete source tree,
including the pinned Eigen archive. Hash-pinned patches are applied to a separate
copy; the original sources are preserved. Compilation runs without network access,
with a read-only patched source tree, one build job, two CPUs and a 4 GiB memory limit.
The build requires all 187 upstream tests to pass. The staged install contains
the native library, VIT header, corrected pkg-config file, dependency license
files and source provenance. It does not install or select a host runtime.

## Recorded-data test

`profiles/slam-replay.json` identifies the public Collabora Monado dataset
`MIO09_short_1_updown`, its exact archive hash and matching upstream Basalt
calibration. Download that archive separately. The test needs NumPy on the host
and the Basalt compiler image; it does not need a connected headset.

```sh
python3 -B tools/test-pico-slam-replay.py \
    --monado-archive PINNED_MONADO_ARCHIVE \
    --dataset-archive MIO09_short_1_updown.zip \
    --basalt-source output/basalt-source-new/source \
    --basalt-build output/basalt-build-new \
    --image sha256:LOCAL_IMAGE_ID --output output/pico-replay-new
```

The harness puts real recorded grayscale images into synthetic Pico snapshot
headers, reverses camera callback order and overwrites the source buffers after
each call. `pico-slam-input` delivers owned Monado frames and calibrated IMU
samples to the actual Basalt VIT library. Both fresh backend runs must finish,
produce the expected poses and meet the reference trajectory thresholds. The
adapter and harness run with address/undefined-behavior sanitizers; the Release
Basalt library itself is not sanitizer-instrumented.

Before replay, 70 lifecycle cases exercise empty, IMU-only, incomplete-camera,
stereo-without-IMU, queued-camera and normal startup, including repeated stop
and destruction before startup. The pinned patches join optical flow before
its derived buffers are destroyed, handle the end-of-stream pose sentinel and
correct the upstream grayscale format query. The unpatched backend crashed
when stopped after receiving stereo images without IMU input.

The checked recording contains 186 stereo frames and 3,467 IMU samples. Its
first image pair precedes the first IMU and is correctly withheld because it
cannot be bracketed. Both tested runs delivered 370 images and all IMU samples,
produced 185 finite poses, and stopped cleanly. Position RMS error was 6.4 mm
and maximum error 16.6 mm after rigid alignment to the recording's reference
trajectory. Alignment changes rotation and translation only; it does not fit
scale. Monado's independent `slambatch` replay also completed.

These results validate a short recorded-data pipeline with Valve Index
calibration. They do not measure Pico accuracy, latency, camera availability,
relocalization, thermal behavior or sustained on-device performance. Reference
calibration is never substituted for Pico calibration.

## Input pressure and image formats

For live capture, set `nonblocking-input=1` and `deterministic=0` in the Basalt
configuration. The VIT input contract requires nonblocking delivery, but the
pinned upstream implementation waits when an input queue fills. With no camera
frames, its IMU producer stopped at sample 302 in the isolated reproduction.
The patch reports queue exhaustion and refuses further input until the owner
stops and recreates the tracker. It does not silently discard sensor samples
and continue reporting tracking. Offline accelerated replay retains the legacy
blocking mode to pace its producer against the estimator.

Six queue-exhaustion and 24 malformed-image cases stop cleanly under native
sanitizer instrumentation of the caller. The image copy also honors row stride
and reads full 16-bit grayscale samples; upstream's advertised L16 path instead
read bytes. Padded, unaligned L8 and L16 replays now produce identical trajectories
for the checked recording. Basalt itself remains a Release build.

## Offline root package

Pass `--basalt VERIFIED_BUNDLE` to `tools/build-headset-root.py` to include the
native library in an offline root. The builder verifies its pinned source,
patches, tests, architecture and staged contents, tests dynamic loading, and
reads the installed files back from the completed image. `test-pico-root.py`
also checks the installed package and VIT version in the Pico-kernel VM.
This does not start a tracker or supply headset calibration.

## HMD pose output

`pico-slam-tracking` accepts timestamped estimator IMU poses and explicit
`T_openxr_slam` and `T_imu_head` transforms. It keeps Monado relation history,
estimates head linear/angular velocity, and caps prediction at 50 ms including
clock uncertainty. Initialization requires two estimates. Stale, nonfinite,
regressing or discontinuous poses are rejected; a newer generation clears
history after the owner resets the estimator.

The Pico HMD factory can borrow this provider through `visual_tracking`.
It then uses full head poses without starting a second IMU session or switching
to an unrelated orientation-only world frame. The caller owns the provider and
must stop capture and destroy the HMD before freeing it. The automatic prober
does not create this path: active camera calibration and a capture/VIO owner
are still needed.

Native sanitizer tests cover transforms, interpolation, prediction limits,
1,000 stream generations, 10,000 poses and 20,000 concurrent reads. Recorded
Basalt replay additionally yields 184 usable head poses after initialization
in each run and clears the provider on stop. These tests use synthetic transforms
and replay time, not measured Pico axes or on-device latency.

## Capture session ownership

`pico-slam-session` owns the input adapter, VIT estimator and HMD pose provider.
It recreates the estimator for each newer stream generation and invalidates
poses on camera/IMU gaps, expired clock mappings, rejected input, exhausted
backend queues or invalid output. Obsolete callbacks cannot reset a newer
stream. Its owner serializes capture calls and polls regularly, including when
capture is silent; HMD readers use the provider's independent lock. Stop capture
and release the HMD before destroying the session. The backend library and
explicit configuration must remain available, with nonblocking input enabled.

Host and ARM64 sanitizer tests cover 1,013 generations and balanced estimator,
frame and pose lifetimes. A separate native recorded-data run through this owner
produces all 185 estimator poses and 184 usable head poses, then invalidates the
provider on shutdown. Its producer is paced against the estimator, using recorded
time. This establishes session integration, not real-time Pico throughput.

The owned stereo transport now feeds this session in the maintained replay.
It creates real request packets and routes simulated kernel events through the
production request, stream and capture code. All 372 buffers are released after
copying; the estimator receives 370 images and 3,467 IMU samples and returns 185
poses. Reference RMS error is 6.417 mm with rigid alignment and no scale fit.
Physical sensor identities, calibration and capture timing are still required.

## SSC IMU handoff

`pico-slam-imu` transfers bias-corrected SSC samples from the sensor worker to
one serialized capture/SLAM owner. It applies explicit sensor-to-IMU rotation
and unit scales, pairs equal ticks and mapped timestamps, and carries the larger
clock uncertainty into the estimator. It does not infer factory calibration or
subtract bias again. Queues hold at most 32 unpaired samples per sensor and 128
pairs; exhaustion, bad current-generation data and excessive gaps invalidate the
generation. Old callbacks cannot invalidate a newer generation.

The consumer polls even during silence and stops the SLAM session on failure.
Producer and consumer clock reads are tracked independently: a consumer may
read its clock before the producer acquires the mutex. Neither thread calls the
estimator while holding the queue lock. Stop and join producers before freeing
this queue.

Host and ARM64 sanitizer tests cover 200 restarts, 59,800 paired samples,
10,000 concurrent producer/consumer pairs and 22 failure cases. ThreadSanitizer
also passes. The reference replay sends synthetic corrected SSC samples through
this handoff alongside the owned camera transport, delivering all 3,467 IMU
samples and 370 images to Basalt and producing 185 poses. This tests transport
integration; the recording still uses Valve Index calibration.

`pico-slam-runtime` connects the selected SSC raw/bias subscriptions to this
queue and the owned VIT session. The sensor worker never calls the estimator;
it invalidates the pose provider immediately on failure. The capture owner
polls bounded IMU batches and estimator output, starts camera delivery only
after the first accepted IMU pair, and copies completed camera frames through
the session. Startup waits for SSC without consuming the camera gap budget.
All failures require recreating the owner; destruction joins SSC callbacks
before freeing the queue or backend. The HMD must be released first.

The runtime owner passes host/ARM64 sanitizer and thread checks over 200 normal
lifetimes, eight backend failures and seven stream/clock failures. The real SSC
library also passes 100 cancelled startups without QRTR and seven scenarios
under the retained Pico kernel with virtual QRTR endpoints: normal, one bias
update, clock failure, missing service, wrong rigid body, unreliable bias and
malformed gyro. Normal scenarios deliver the expected corrected SI vectors on
the consuming thread; failure cases deliver no IMU to the test backend. These
VM tests use a synthetic estimator, independently of the real Basalt replay.

Its configuration requires explicit SUIDs, supported rates, clock calibration,
axis/unit conversion, camera timing and estimator calibration. Construction
starts those SSC subscriptions; callers can instead prepare the runtime and
activate SSC after camera setup. Deferred startup prevents samples from filling
the bounded queue during configuration. Start is attempted once, and stopping
before activation prevents a later start. Neither entry point opens, configures
or starts cameras.
The auto prober remains disabled for this unverified physical configuration.

## Continuous capture

`pico-slam-live` owns the configured stereo rig, request transport and SSC/SLAM
runtime. The caller provides already probed sensors and exclusive nonblocking
CRM/sync descriptors. Preparation validates tracking, configures the rig, creates
the transport, subscribes events and only then activates SSC. It does not open
nodes or infer physical camera selection.

Polling waits for the first paired IMU, queues the initial stereo requests and
starts the cameras. Completed frames are copied into the estimator; a request is
refilled only after both cameras complete. The queue holds one to eight pairs,
with an explicit frame period and timeout. Calibrated exposure-center offsets
apply to newly queued requests. The caller must poll during silence too, so
clock expiry, lost IMU and missing fences stop the generation.

Live callers use `pico_slam_live_poll_clock()` with a serialized monotonic-clock
callback. The owner refreshes time after each event dequeue, before request
allocation and before polling the estimator again. A frame can complete during
an ioctl; judging it against the earlier poll-start time would incorrectly
reject it as future input. Clock failure or regression stops the generation,
and empty event queues still receive a fresh timeout check. Timestamp-only
polling remains available for fixed recorded batches.

Stop invalidates poses and attempts all affected stream stops. The caller must
then establish DMA quiescence independently before retiring requests,
unsubscribing events and releasing command buffers and hardware handles. An
uncertain cleanup remains owned and is not retried. Destroy any HMD borrowing
`pico_slam_live_tracking()` before destroying the live owner.

The host and ARM64 lifecycle tests use the actual tracking runtime with camera
lifecycle doubles. They cover 200 lifetimes, all supported queue depths, partial
stereo completion, 20 failures and retained cleanup ownership. ThreadSanitizer
also passes. These tests do not establish physical capture or calibration.

A separate ARM64 sanitizer replay connects the actual rig, request/packet
transport, runtime and Basalt estimator through simulated ioctls, DMA and SSC
reports. It supplies all 3,467 IMU pairs and 370 usable images from the pinned
reference recording, producing 185 poses and 184 tracked head poses. Startup
skips the one image pair preceding the first IMU sample; shutdown retires the
remaining queued pair. The trajectory has 6.41 mm rigid RMS error and 16.60 mm
maximum error without fitted scale, matching the earlier bounded-queue replay.
This recording uses Valve Index calibration and is not Pico accuracy evidence.

## Installed camera runtime

The Pico build installs `libpico_tracking.so` alongside Monado. Both the service
and CLI link to it; the library retains the camera setup, continuous capture,
SSC handoff, pose provider and HMD factory entry points. A static driver archive
was insufficient because the linker discarded capture functions that the
automatic prober does not call. Bundle verification now checks the exported
functions, executable dependencies and a device-free library load.

Add `--monado-bundle VERIFIED_MONADO_BUNDLE --ssc-bundle VERIFIED_SSC_BUNDLE`
to the replay command to test that installed library. This variant links only
the harness and simulated hardware transport locally; camera/runtime/HMD code
comes from the installed library. Its function-resolution check confirms that
origin. The library and Basalt are Release builds; the harness and hardware
fixture use ASan/UBSan.

The installed-library replay also creates the actual HMD with synthetic optics
and the live owner's borrowed pose provider. It checks tracked head poses,
stereo views, current-input activity, accepted and refused predictions, and
pose invalidation after capture stops. The fixture refuses a duplicate SSC
subscription. Input is paced separately for this test so the estimator can
produce poses within the production prediction window; this is not a headset
throughput measurement.

The installed-library replay also injects camera silence while synthetic IMU
reports continue, and a regressing poll clock. Each run first establishes the
reference trajectory and tracked HMD output. Both failures invalidate the pose
provider and HMD before an explicit stop, refuse further polling, and retire all
372 buffers after simulated DMA quiescence. A subsequent fresh-process replay
completes normally. These checks exercise the installed runtime and actual Basalt;
they do not prove recovery of a physical sensor or estimator relocalization.

This is an internal interface tied to the exact Monado headers and driver
revision. It does not enable camera capture in the automatic prober or provide
physical calibration. A physical owner still needs exclusive device access,
verified settings, regular polling and independently established DMA shutdown.
Do not call the quiescence acknowledgment solely because a stop ioctl succeeded.

## Pose transport to SteamVR

`pico-slam-channel` transports converted head poses between the separate Bionic
SLAM producer and a native Linux consumer. Its 136-byte, versioned mapping uses
lock-free atomic words and a bounded sequence check. The owner serializes one
writer, creates a fresh mapping before sharing it, and binds readers to explicit
process-instance and estimator-generation identifiers. It must not truncate or
reinitialize a mapping that readers still hold.

Startup confidence 0 remains untracked. Once a pose has been published,
confidence loss or failed conversion stops that generation. Resuming requires
the owner to establish the world frame again and bind a new generation; an old
callback cannot publish into or stop the replacement generation. Readers reject
stale, future, malformed and clock-uncertain samples without returning an old
pose as tracked.

`pico-steamvr-pose` converts that channel into the actual OpenVR `DriverPose_t`.
It carries the capture age in `poseTimeOffset`, maps quaternion component order,
and supplies no invented height, neck model, velocity or prediction. The input
must already use the calibrated OpenVR head origin and right/up/back world axes.
Tracking loss returns an invalid pose immediately.

`pico-vendor-slam-output` owns result-side callback serialization, including
`getAlgorithmResult`, decoding and channel publication. It rejects invalid
configuration before beginning a generation. A failed result call, malformed
packet, regressing clock or stale tracked result stops publication. Stop waits
for an in-flight result call, then prevents late callbacks from accessing the
vendor handle. The process owner must still join/unregister vendor callbacks
before releasing the output object.

Host sanitizer tests and offline ARM64 tests pass. Concurrent Bionic-to-glibc
and glibc-to-Bionic process tests verify coherent transport with the actual Pico
Bionic loader. The result owner also passes 4,000 concurrent callbacks, eight
fault cases and shutdown during a blocked result read. Replay through the
complete decoder/conversion/publication/OpenVR chain processes all 61,905
retained packets and publishes exactly 59,342 tracked poses; the remaining
startup packets stay invalid. Bionic and glibc result-owner replays agree.
Replay uses explicit identity test transforms, not verified head calibration.
The 2026-10-21 native Pico run subsequently publishes 8,148 live tracked poses
from 10,821 callbacks into the channel. An independent native OpenVR-structure
observer receives them and verifies terminal invalidation. Both camera groups
stop, the IMU worker joins and MCU power references return to zero. This run
uses explicit identity diagnostic transforms; it does not establish calibrated
head poses or a connection through SteamVR's server.

The [physical Neo3 SteamVR driver](pico-steamvr.md) now builds against the pinned
SDK and uses the same private optics contract. The existing `steamvr-headset.h`
remains a simulator. Firmware-derived head-frame binding, actual server/client
publication, compositor presentation and physical acceptance remain separate
integration gates.

## Remaining integration

- Capture native camera buffers with known ownership, format and exposure times.
- Establish active camera identity/order, intrinsics, distortion and IMU-to-camera
  transforms; the retained older XML is not established as the active profile.
- Bind camera and IMU clocks with measured uncertainty, and reset the estimator
  whenever a stream generation changes.
- Supply the continuous capture owner with verified device configuration,
  calibration, clock mapping and regular polling.
- Validate camera coverage, real motion, loss/recovery and display-time prediction
  on the device after the boot/recovery gates pass.

See [camera records and input ownership](pico-tracking-protocol.md#camera-snapshots-and-synchronization)
and [the installation requirements](device-installation.md).
