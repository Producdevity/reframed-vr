# Pico sensor RPC runtime

The native ARM64 library combines Qualcomm FastRPC at the revision pinned in
`profiles/pico-fastrpc.json` with Pico's vendor ioctl ABI and ION allocator.
The upstream listener, module loading and buffer registry remain in use.
It is built as a separate bundle; the builder neither installs it into a
headset root nor starts a device service.

```sh
docker build --platform linux/arm64 -f Containerfile.fastrpc -t localhost/reframed-vr:fastrpc-tools .
tools/build-fastrpc.sh source.tar.gz output/fastrpc
```

Use the source URL and SHA-256 in the profile. An existing source archive can
be reused. The wrapper verifies it before creating the output directory and
runs the build without network access. It records the immutable compiler
image, input hashes, tests, dependency versions and bundle contents in
`bundle/build.json`. The bundle contains source, patches and licenses under
`opt/reframed-vr/fastrpc/share`; runtime libraries are under `lib64`.

The sensor process must select `createstaticpd:sensorspd` through Qualcomm's
`ITRANSPORT_PREFIX` interface before opening its sensor module. Sensor
attachment errors are fatal. Other process-creation modes are unsupported.
The adapter translates the mainline NOVA bit to the vendor bit, packs separate
FD and attribute arrays, and supports legacy static mappings. Newer delayed
FD mapping modes return unsupported instead of being reinterpreted.

For default `rpcmem` allocations, `PICO_ION_HEAP_ID` must name an independently
verified heap from 0 through 31. There is no implicit physical-device default.
Set it before loading the runtime library: initialization caches the heap choice,
so setting it after `dlopen` can leave default allocation failing with `ENODEV`.
The VM uses its deliberately configured system heap 25; that does not establish
the correct heap or cache policy for the headset's sensor DSP. Explicit heap
arguments remain available. Cached, uncached, default-heap and no-registration
flags are supported; other allocation flags are rejected.

Registration failures release the allocation. Deregistration or unmapping
failures retain buffer ownership, and allocator shutdown does not free buffers
that could still be used by the DSP. Consumers must finish DSP operations and
release their buffers before unloading the library. Direct CPU access to a
stream buffer still requires DMA-BUF synchronization through its descriptor.

The build runs allocator and upstream adapter tests with ASan/UBSan, checks
dynamic symbol resolution, and confirms that the runtime test refuses to run
outside its VM fixture. `tests/pico-fastrpc-runtime.c` exercises the full library
against the real kernel's virtual ION heap: allocation, buffer registration,
cache synchronization, release and failed startup with no DSP attached.

Live sensor attachment, reverse RPC from the physical DSP, stream layout,
SUID selection, calibration and tracking remain separate acceptance steps.
These tests do not establish boot/recovery or flash readiness. The bounded
physical controller check below establishes module attachment and channel
lifecycle separately from sample delivery.

`libpico-sensors.so.1` connects the low-latency stream encoder to FastRPC's
domain-aware handles, explicitly selecting SDSP and the sensor process. The
`pico-sensor-rpc.h` interface borrows a registered ION buffer; it does not choose
a heap, allocate memory, select a SUID, start a service or interpret samples.
Keep each client on one thread and keep its buffer and runtime library alive
until close succeeds. Configuration can add multiple sensors to one channel.

Close stops configured streams, deinitializes the channel and releases the RPC
handle in that order. A failed operation leaves the last confirmed state and
does not retry. A failed or malformed initialization has an uncertain channel
state, so close refuses to discard it. Its buffer must remain owned until an
independently confirmed DSP teardown; this recovery path is not yet verified.
The client never equates a failed RPC with proof that the DSP released memory.

## Physical controller module loading

On the Neo3 Pro Eye running b1977, the legacy module name
`sns_low_lat_stream&_dom=sdsp` reaches the DSP loader unchanged and fails with
`0x80000406` (`AEE_EUNABLETOLOAD`). The stock stub instead opens the bare
`sns_low_lat_stream` name through the legacy API. Its success does not establish
that appending a domain suffix to that name works.

The source wrapper now uses the explicit URI
`file:///libsns_low_lat_stream_skel.so?sns_low_lat_stream_skel_invoke&_dom=sdsp`.
The entry point matches the stock DSP skeleton export, and domain selection
remains explicit. On 2026-10-22, stock-style legacy open/close and this URI's
64-bit open/close both succeeded on the physical headset. The rebuilt wrapper
then completed buffer initialization, controller configuration, stop,
deinitialization and close with zero return codes. The bounded 20-second
capture delivered no valid controller records; this is a loader and lifecycle
fix, not verified controller input or SteamVR tracking.

Host ASan/UBSan and native ARM64 lifecycle tests each passed 128 cycles and
failure handling at six stages with three error codes. The native build and
capture receipts are in `output/pico-peripheral-session-20261022-v3/`.
The hash-verified `export-controller.tar.gz` contains 67 files and has SHA-256
`cb1838c004a5c9fb86a5220c6217eddd3cabac54ba93e7dbbc1263895cb1c0fb`.
The private probe and rebuilt library stayed in RAM; the installed bundle was
unchanged. Audio remained inactive throughout these controller tests.

A second bounded capture saved the synchronized final ring: all ten slots
remained zero. MCU debug packets reported increasing left-controller packet
counts, but that does not prove delivery from the MCU to SLPI or coherent DSP
writes into this allocation. That final snapshot did not establish a key-decoder
fault; the subsequent isolation checks below distinguish buffer visibility
from controller delivery.
The follow-up again configured and closed successfully, released the MCU power
reference to zero, and stopped the owned SLPI to `OFFLINE`. The audio and compute
DSPs were never started. Its 98-file `export-controller-final.tar.gz` has SHA-256
`fdf448f134e8b61525815ba235b342ed74896642027b25e784bb48e5dfa3b06d`.

## Controller delivery isolation

Further RAM-only tests on 2026-10-22 used the same b1977 Neo3 Pro Eye. These
results narrow the failure; they do **not** establish working native controller
input or SteamVR integration.

| Check | Observed result | Limit |
| --- | --- | --- |
| Cached and uncached ION buffers | Both 20-second controller captures retained 1,000 zero bytes | Cache policy alone did not restore delivery |
| Accelerometer through the same low-latency wrapper | Previously zero memory contained nonzero data in every 100-byte region; one double-read mismatch was observed | Establishes DSP-to-CPU writes for that stream, not controller records or validated accelerometer decoding |
| Live SSC discovery | `ble_mcu` SUID matched stock: low `f8d9a8908e5f4f1b`, high `f3e0cdbb766d3625` | Discovery does not prove controller interrupt or sample delivery |
| Stock Bionic allocator, FastRPC runtime and low-latency stub | Initialization, configuration, stop and deinitialization returned zero; all 1,000 bytes stayed zero throughout 20 seconds | Replacing the glibc port alone is insufficient in the tested native environment |
| Stock Android after return | Left controller connected; tracking service logged changing IMU samples | Radio pairing and the controller work in stock; native delivery remains unresolved |

The accelerometer probe's textual result survives as
`pico-controller-delivery-20261022-v1/capture-accel-result.log`; its raw ring was
not exported before a later reboot. It used a different sensor layout, so the
controller decoder's zero accepted records are expected. Do not treat its
printed controller timestamps or CRC results as accelerometer measurements.

The stock-library comparison used the readonly stock system/APEX files copied
into RAM. Its manifest identifies every copied library. The system and vendor
copies of `libsns_low_lat_stream_skel.so` matched SHA-256
`bdf5cbe7328bf772eb143a38c214121847ddf7f97a11cae83301f2057e35830f`.
The probe held its allocation until the parent stopped SLPI and independently
verified `OFFLINE`, then freed it and exited successfully. This verifies that
private probe's teardown sequence, not the maintained wrapper's failure path.

Two separate legacy 32-bit-handle probes returned zero from close, then lost
USB and returned to stock before printing buffer-release completion. The
second reproduction omitted the first run's debugfs inspection. The retained
partial logs do not identify which subsequent cleanup operation caused the
reboot; clean teardown of that variant is unverified. It is not a replacement
for the maintained domain-aware wrapper.

The [optional IMU command](pico-controller-protocol.md#controller-imu-command)
also failed to restore delivery. Stock logs report `hmd-freq:0` alongside live
controller IMU samples, so that debug field alone is not evidence of a missing
native prerequisite. GPIO snapshots taken before the native subscription and
during stock tracking are not equivalent operating states and cannot justify
a pinmux change. The subsequent v4 checks below examine the active subscription.

Evidence roots are `output/pico-controller-delivery-20261022-v1/`, `v2/` and
`v3/`. Each archive's complete member inventory, sizes and SHA-256 hashes were
checked against its embedded manifest and extracted files:

| Session / archive | Files | SHA-256 |
| --- | ---: | --- |
| v1 / `export-cache.tar.gz` | 51 | `a15f464a3b5adc2777c99ab8ac2ec124d892465bdb3ea0617b73557aa3c338c0` |
| v2 / `export-stream-enabled.tar.gz` | 40 | `1dc392b77e9993a2247c808868a8754c0773f3d4167302a7ae80411c26182e6d` |
| v3 / `export-stock.tar.gz` | 14 | `15c31ac5aaf3e78d813a858fab71838b8fdddaba57e3cd47821f5a3941794dc0` |

The final v3 run verified zero MCU power references and SLPI `OFFLINE`. Audio
and compute DSPs were never started in that native session. Full boot and DTBO
partition readbacks matched the retained stock hashes. The controlled return
verified stock b1977, Wi-Fi off, updater disabled and speaker music/system/ring
volumes zero. No controller fix is installed.

### Active receive-path checks

The v4 session used the same stock Bionic probe and added these comparisons:

| Check | Verified result | Limit |
| --- | --- | --- |
| Sensor firmware identity | All 21 native `slpi.*` files matched files on the readonly stock modem partition byte for byte by SHA-256 | Excludes a different packaged SLPI firmware set, not a runtime configuration difference |
| Active pin state | GPIO 111 became an input with keeper during the subscription, matching the stock snapshot | Pin configuration does not prove interrupt delivery |
| Host SPI ownership | Pinctrl identifies GPIOs 0–3 as `894000.spi`, which owns `/dev/spidev0.0` | These are the host-to-MCU pins; their state does not establish the DSP SPI path |
| Stock startup queries | Firmware-type `AA0100` and version `AA0101` requests did not change the zero controller ring; a valid `BB0101` version reply arrived | No `BB0100` reply was captured; this is not proof that both commands were acknowledged |
| Simultaneous accelerometer control | A separate stock-library channel started five seconds into the controller capture and repeatedly changed its own buffer; the controller buffer remained entirely zero | Verifies DSP shared-memory writes in the same process, not decoded accelerometer samples or every head-tracking prerequisite |

The simultaneous test retained both final buffers. At the last periodic sample,
the accelerometer buffer had changed 177 times and contained 866 nonzero bytes;
the controller buffer had no changed slots or valid records. Both channels
stopped and deinitialized successfully. Both allocations remained alive until
SLPI was independently confirmed `OFFLINE`, then the probe freed them and exited
zero. MCU power references returned to zero.

The controller DSP's diagnostic SSID 124 also confirmed sensor-instance
initialization, `ble_mcu_register_interrupt`, and one initial notification/ISR
handler invocation. No recurring controller notifications appeared during the
20-second capture before MCU pacing was enabled. The later comparison below
identifies a missing startup command; this initial trace alone did not identify
that cause.
The collector restored the prior logging mask before closing. Its first mask
query exposed a collector assumption: this kernel returns the entire containing
mask table, even for a single-SSID request. The corrected collector queries the
table's start and reads the corresponding entry before changing or restoring it.

Evidence is retained in `output/pico-controller-delivery-20261022-v4/`.
Archive inventories and every member's size and SHA-256 were verified against
the embedded manifests and the extracted files:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-stock.tar.gz` | 22 | `e61e9719203b1bdaa8f4930a4088472f315c0a3ce50c76f596afa4ee44678c7f` |
| `export-query.tar.gz` | 22 | `2b819f5188ccb3e9dd8835e51a60251c84f2185cbffe85880c4bd5922950ea44` |
| `export-dual.tar.gz` | 23 | `f6344fa029247eed0fb1b459536015ff4504cea197618a39a78376c8d91efe69` |
| `export-diag-v2.tar.gz` | 24 | `5cdb46c8e4c7e1e856662f7a0e2e6b88f826adc4c682278b397f6d38f1438289` |

The full firmware comparison is in `compare-firmware-result.log`; the active
pin samples, raw rings and decoded diagnostic frames are in the archives.

### Controller delivery enabled by MCU pacing

Starting the verified five-second camera capture during a stock-library
controller subscription changed its previously zero ring into 7,230 CRC-valid
records. Delivery continued after the cameras stopped. The maintained key and
IMU decoders accepted every record as left-hand data, with advancing controller
microsecond timestamps. This establishes native receive transport and decoding;
no button presses, analog endpoints, controller poses or SteamVR input were
validated in this stationary capture.

A subsequent isolated test sent only the existing
`pico_station_camera_pacing(1)` command (`AA 01 19 01`, padded and CRC-checked)
five seconds into a fresh subscription. Its `BB 01 19` reply was captured and
acknowledged. Records began immediately without starting the cameras: 1,734
valid left-hand records arrived before delivery stopped about 3.4 seconds later.
The MCU continued reporting increasing left-radio packet counts after the ring
stopped. Those counters do not establish continuing controller motion reports;
the later activity test below limits conclusions about sleep or idle behaviour.

A third test combined that command with a concurrent head-accelerometer
channel. It received 7,567 valid left-hand records continuously for the remaining
15 seconds, approximately 507 records per second. The accelerometer-only
negative control above stayed empty on the controller channel. Together these
checks establish the missing MCU pacing request and a working two-channel
startup combination. Whether the pacing-only stall is a DSP idle-state problem
remains an inference requiring isolation; camera streaming is not required by
this successful capture.

All three captures retained their DMA buffers until SLPI was independently
confirmed `OFFLINE`; MCU power references returned to zero. Audio and compute
DSPs remained off. The camera run's verbose diagnostic collector reached its
1.5 MB logging limit after collection, causing the enclosing command to fail.
Its exception cleanup stopped SLPI and released the retained buffers safely.
The raw records and manifest remain valid, but that run did not verify the
logging-mask restoration acknowledgement. The two pacing tests used no
verbose diagnostic collector and exited zero.

Additional v4 archives, verified with the same per-file manifest checks:

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-diag-v3.tar.gz` | 25 | `53d19d6f586ceb2a21106fe0e96dc697be19d44da6761e33fb89ae066ef40799` |
| `export-with-cameras.tar.gz` | 25 | `1b1ad796b0292beb8417923c667a3a199596dc23b507885bd06ed21624d3832e` |
| `export-pacing-only.tar.gz` | 23 | `ec62702d154fe4ef3627202c5f84f95d202679adda03d6dbb3618acdeb0516a3` |
| `export-pacing-accel.tar.gz` | 24 | `17591bd9367bf3a2ca9fd9974cb405e46569c0871f0f0c1174959c870d94d985` |

The decoder receipts are `decode-camera-records.txt`, `decode-pacing-only.txt`
and `decode-pacing-accel.txt`.

### Native receive path and physical input

The maintained native FastRPC wrapper subsequently received controller records
with the same pacing request, a 1,000-byte controller ring and the concurrent
head-accelerometer channel. Longer stationary captures stopped after about
30 seconds of delivery. Starting head IMU or cameras, changing accelerometer
startup order, and repeating the pacing request did not extend those stationary
captures. At the transition, the DSP diagnostic trace stopped showing controller
notifications and ISR callbacks without a logged SPI/CRC error in that interval.
This narrows the observation to incoming delivery; it does not prove a DSP fault.

During a user-operated movement/button test, the unchanged receiver accepted
**27,794 CRC-valid left-controller records over 54.904193 seconds**, continuing
to the end of the 60-second capture after pacing began at five seconds.
The maintained key decoder accepted every record. Recorded input included
X/Y, menu, stick click, trigger and grip changes, plus the five touch fields.
Trigger, grip and both stick bytes each reached 0 and 255. The replay counted
82 button-state changes. These endpoints do not establish axis direction,
center, dead zones or pose calibration.

This supports activity-dependent idle behaviour as an explanation for the
longer stationary captures. It does **not** establish the exact sleep mechanism,
recovery after a previously idle stream, or the cause of the shorter pacing-only
stall. A missing polling call is not supported by the stock tracking library:
its active reader waits on `/dev/stationdev`, while its loaded low-latency RPC
entry points omit `sns_low_lat_stream_poll`.

The receiver retained both DMA allocations until SLPI was confirmed `OFFLINE`.
MCU power references returned to zero; audio and compute DSPs remained unbooted.
The recovery timer returned the headset to b1977 stock firmware with Wi-Fi off
and the updater disabled. The final readback request missed that timer, so this
run has no new post-test full partition readback; it performed no partition
writes. Controller pose and live SteamVR input remain unverified.

| Archive | Files | SHA-256 |
| --- | ---: | --- |
| `export-transition.tar.gz` | 59 | `92c2bf11f707a0fc85743806016004d8c4c6b39bcb80887efdc66b70bcec4485` |
| `export-motion.tar.gz` | 47 | `8def996497dfa2300dceed61423813522a246537d2988a426c2a0a5e21926e74` |

Both archives are in the same v4 evidence directory. Their inventories, every
member hash and extracted bytes were rechecked. Physical-input analysis is in
`export-motion/analysis.json`; stock return is in `stock-return-final.json`.

## Offline root installation

Pass `--fastrpc /path/to/verified/bundle` to `tools/build-headset-root.py` when
building a Pico root with its DSP startup services. The installer verifies the
source and profile hashes, complete library inventory, ARM64 ELF headers,
permissions, licenses and relative library links before copying the bundle.
The libraries stay under `/opt/reframed-vr/fastrpc`; installation does not select
a heap or start a sensor stream.

The root builder checks symbol resolution using the target root's dynamic
loader and libraries, then reads the installed files back from the resulting
ext4 image. The build record binds these checks to the bundle and kernel.
These checks establish offline packaging and dependency compatibility only.
