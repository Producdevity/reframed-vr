# Pico Neo3 controller receive protocol

The b1977 stock system image from the authenticated 5.8.4.0 OTA contains
`libstationopticsservice.so`, SHA-256
`91b45470678ca7d614a7f12ccb21261f3cda273c4ba6b08c1edb153cd5b6286e`.
Ghidra and AArch64 disassembly identify a receive path distinct from the
40-byte MCU command/response protocol on `/dev/spidev0.0`.

`StationService::SlpiDataAnalyze` consumes a **100-byte** record. Byte 99 is
CRC-8 over bytes 0–98, initialized to zero, with reflected polynomial `0x8c`
and no final XOR. Its complete lookup table matches that polynomial. Input
records begin with `0xa5`; `0xbb` heartbeat and `0xaa` test records are separate.
For stock MCU type 1, key data is processed only when byte 1 equals 1. Type 2
requires bit 2 of byte 1. These are observed configuration values, not inferred
hardware model names. The SLPI startup requests a Qualcomm SSC stream named
`ble_mcu`; it is not equivalent to opening the SPI command device.

The service loads `sensors-common-imu.pvr.so`, SHA-256
`0fc16cf6482c852c64be9035c8286c7f467a4518989843aeecce607270070159`,
from the same authenticated system image. Its `SLPIInit("ble_mcu", 480)` route
uses `libssc.so` and `libsns_api.so`. For SSC message ID `0x400`, the library
parses `sns_ble_mcu_data` and copies 25 uint32 words into the 100-byte station
record at offset `0x1018` of a `0x1980`-byte event. This establishes the inner
record boundary. The payload and outer event schemas have been checked offline
as described below. Native subscription and shutdown have since been tested;
connected-controller reports still need validation.

That ordinary SSC route is distinct from the active b1977 tracking reader's
[FastRPC shared-memory controller path](pico-tracking-protocol.md#low-latency-rpc-messages).
`SlpiDataReader::start` requests a 1,000-byte ring of ten 100-byte records,
period `100000` microseconds, flags `0` and sensor handle `1`. Acknowledged
480 Hz SSC requests do not establish operation of that path. The
[physical module-loading check](pico-fastrpc.md#physical-controller-module-loading)
verifies its source wrapper's channel lifecycle. The subsequent
[physical input capture](pico-fastrpc.md#native-receive-path-and-physical-input)
validated 27,794 left-controller records with button, touch and analog changes
through the native FastRPC path. This does not validate the ordinary SSC route,
controller pose or SteamVR input.

The outer event timestamp at offset `0x10` uses SSC ticks multiplied by
`52.083333333333336`, plus an offset measured from Android elapsed real time and
the CPU counter. This is distinct from the timestamps inside the controller IMU
payload. The callback receives a queue-owned pointer, while `pollEvents` copies
an entire event before freeing its queue entry. A receiver must establish buffer
ownership and shutdown ordering; retaining the callback pointer is unsafe.

The same-build device's `libssc.so`, SHA-256
`9adc9c3c6aee833e3566bf3574844c038098385abd7c94c81aeedfd07edc0fa8`,
contains the serialized `sns_ble_mcu.proto` descriptor. Its 309-byte length
also matches the descriptor registration call recovered with Ghidra. Field 1
is repeated `fixed32` controller data; field 2 is a required sample-accuracy
enum with values 0 through 3. It is not a byte-string field. The first 25 words
are the station record consumed by the stock service.

The separate [controller IMU decoder](pico-tracking-protocol.md#controller-imu-records)
now handles raw motion slots from the same station records and SSC payloads.
It preserves capture timestamps separately from the outer SSC report time and
does not enable uncalibrated controller poses.

`pico_controller_decode_ssc` accepts this payload and calls the existing CRC and
key decoder. It requires exactly 25 words and an accuracy value in range,
supports packed, unpacked and mixed word encoding, skips unknown scalar fields,
and refuses groups, malformed lengths and payloads over 4,096 bytes. Both output
values remain unchanged on failure; no payload pointer escapes the call.
The caller must still validate message ID, stream identity, the outer timestamp
and connection lifetime. This receiver does not open a QMI connection or start
the SLPI.

The bounded receive-only implementation is
[`pico_controller_decode`](../src/pico-controller.h) in
[`pico-controller.c`](../src/pico-controller.c). It checks length, header, CRC
and key-data presence before changing the caller's sample.

| Offset | Meaning |
|---:|---|
| 3 | Trigger analog byte |
| 4, 5 | Stick X and Y analog bytes |
| 6 | Grip analog byte |
| 7, bits 0–5 | Home, app/menu, A/X, B/Y, grip, stick click |
| 7, bit 6 | Hand: set means left (1), clear means right (2) |
| 7, bit 7 | Trigger click |
| 8, bits 0–4 | A/X, B/Y, stick, thumb-rest and trigger touch |
| 9 | Battery, interpreted according to the explicit radio type |
| 99 | CRC-8 |

Radio type 1 maps battery values 0–5, 6–25, 26–50, 51–75 and 76–255 to levels
1–5. Radio type 2 keeps the low three bits. The stock service gates touch fields
with its touch-support flag; the decoder takes that flag explicitly. Analog
values remain unsigned bytes. A default value of 128 appears for disabled stick
axes in the service, but does not establish the physical center, dead zone,
range, axis sign or calibration of an enabled controller.

The stock service separately applies per-button configuration masks and a test
hook, checks controller online state, updates shared memory, and emits Binder
notifications. The raw decoder performs none of those lifecycle operations. Its
caller must obtain the active MCU/radio configuration and supply complete records
from a verified transport. It does not pair controllers, send haptics, access a
device, load firmware or produce a tracked pose.

## Controller configuration

The stock MCU selector reads `/sys/hwinfo/version_id`. In station mode 0,
revision bits `0x38` select MCU type 2 when any are set, otherwise type 1.
Mode 1 uses bit `0x10`; a low byte of `0xff` is unknown. Stock constructs
`MCUNRF52832` for type 1 and `MCUIN618` for type 2. This sysfs file is not
readable by the Android shell on the inspected Pro Eye.

The radio type comes from a separate MCU device-info reply: byte 16 equal to
0 selects type 1, and 1 selects type 2. Other values leave the previous value
unchanged. The constructor's zero is therefore not a usable default. These
findings come from `mcuGetType`, `MCUServer::initialize` and
`StationService::MCUCallBackDataProcess` in the hash-pinned stock library.

[`pico-controller-config.py`](../tools/pico-controller-config.py) reads the stock
configuration through verified Binder getters. It checks the device, exact
b1977 fingerprint, station library hash and configuration-service APK hash
before making any Binder call. Station transactions 76 and 74 return radio
type and touch enablement. ConfigurationService transaction 3 reads
`sys_controller_chip` and `sys_controller_prototype`. The latter must agree
with the live radio getter. Two snapshots and the Android boot ID must agree.
Exceptions, unexpected response layouts and unsupported values fail the read.

```sh
python3 tools/pico-controller-config.py --serial DEVICE_SERIAL \
  --output output/pico-controller-config.json
```

The collector issues no setters, resets, sensor subscriptions or firmware
operations. The output contains the device serial and belongs in private
evidence. It describes stock service state, not independently measured silicon
or analog calibration, and must not become a default for another unit.

The optional `--motion-status` switch also calls station transaction 19 twice.
The hash-pinned stock implementation only copies its cached controller status;
it does not connect, pair, reset or subscribe to a controller. The collector
additionally verifies the station client, tracking library and Binder library
before any Binder transaction. Both replies must have a successful status,
present parcelable of type 18, and two complete 48-byte controller records.
It retains both raw records, requires connection states 0 or 1, and rejects a
change in connection, revision byte, scale byte or axis-reversal byte between
reads. Other changing status fields are retained without interpretation.

```sh
python3 tools/pico-controller-config.py --serial DEVICE_SERIAL --motion-status \
  --output output/pico-controller-motion-status.json
```

In each record, the tracking parser reads byte 15 to select a hardware axis
branch, doubles its IMU conversion factors only when byte 42 equals 1, and
bypasses hardware axis reversal when byte 43 is nonzero. These names describe
observed code behavior; they do not establish a particular controller model.
Disconnected status cannot establish a connected controller's calibration.
The collector does not install these values, convert motion samples or enable
controller poses. Native execution of the stock serializer and deserializer
and 256 comparisons with the collector pass offline. Connected-controller
settings require a capture on the device; the left-hand capture below now
establishes those settings for this unit.

The 2026-10-22 physical b1977 capture prints the final Parcel terminator on the
last data row. The reader accepts that form and the separate terminator line,
while still requiring exactly seven addressed rows, a successful header and
two complete 48-byte records. Fourteen host tests and two live snapshots pass.
This unit reports MCU type 1, radio type 2 and touch enabled, with both
controllers disconnected. The zero motion-setting bytes in that state do not
establish connected-controller calibration. The failed original read and
successful receipts are retained in
`output/pico-steamvr-session-20261022-v8/stock-controller-config*.json`.

A later stock capture on the same day, after the owner confirmed the left
controller appeared in the menu, reports the left connected in both snapshots.
Its revision byte is `53`, double-scale byte `0`, and axis-reversal-bypass byte
`0`. MCU type 1, radio type 2 and touch enabled remain unchanged. The right
controller is still disconnected; its zero fields do not establish its
connected settings. The read-only receipt is
`output/pico-peripheral-integration-20261022-v1/stock-controller-connected.json`,
SHA-256 `98678b9403989e1cca70a40b8d3c65053b20642a20c9dbb1f4bec6c88c3589b1`.
This establishes stock configuration only. Later native FastRPC captures
validated connected input, followed by [SteamVR digital-input tests](pico-steamvr.md#native-controller-input-verification).
Analog calibration and controller poses remain unverified. Digital defaults are
described in [SteamVR bindings](pico-steamvr.md#digital-default-bindings).

### Cached controller tracking calibration

The optional `--calibration-hand left|right` collector reads stock station
transaction 12 twice for the selected hand. The hash-pinned b1977 getter copies
its cached 660-byte `CV3_calibration_t`; it does not wake, pair or reconfigure
the controller. The collector requires successful type-14 parcel replies,
Neo3 generation 0, complete valid IMU/IR/IMU-to-IR sections with 24/48/7 floats,
and finite active coefficients. Both calibration replies, both complete station
status records, firmware identity and boot ID must remain consistent. Calibration
failure leaves the report marked failed. Coefficients and device identifiers
belong in ignored evidence, outside Git.

```sh
python3 tools/pico-controller-config.py --serial DEVICE_SERIAL \
  --calibration-hand left --output output/NEW_CONTROLLER_CALIBRATION.json
```

A live read on 2026-10-22 passes with the left controller disconnected and a
complete cached calibration. The raw calibration SHA-256 is
`cf95d29f6109bad3f9a13d0d93d124cfa94f017f1915fe9f03545f69b14a773b`;
the receipt is `output/pico-vsync-controller-20261022-v1/stock-controller-calibration-verified.json`.
Nineteen collector tests pass, including incomplete sections, nonfinite values,
failed getters, changed calibration and changed station records. A cached
calibration does not establish a currently connected controller or a valid pose.

[PicoFrame's controller-tracking research](https://github.com/TheReal-Flo/PicoFrame/blob/3affbc11ecaae56c56b7bd3eb13344c73a7a03da/research/ctrltrack/README.md)
provided the reference for finding this cache and tracker interface. Its PICO 4
5.13.7 adapter cannot be copied unchanged: b1977's
`ControllerSlam::updateCalib` appends only gyro range, accelerometer range and
protocol after the three sections. That makes 85 floats for a complete Neo3
calibration; the newer PicoFrame adapter appends six metadata values. The Neo3
also exports the corresponding controller init, calibration, IMU-with-head and
image-with-head entry points. These library and adapter checks establish an
integration path, not live optical controller tracking. Controller LED images,
capture-clock mapping, head-pose matching and the SteamVR controller pose remain
to be connected and verified.

The collector also brackets calibration with transaction 20, the cached
algorithm-information getter. Its successful type-19 reply contains two
204-byte records. Only their gyro/accelerometer range fields are interpreted;
the remaining fields are not calibration parameters. Supported vendor range
pairs are 4000/32 and 8000/64. Both snapshots must agree. The report's
`tracker_parameters` contains each valid flag followed by its active section,
then those ranges and the verified radio protocol: exactly 85 floats. These
range values retain the vendor API's units; they are not converted IMU samples.

The extended collector passes 22 host tests and a second live read. Its generated
340-byte vector matches the native probe input byte for byte, SHA-256
`857661824fa8086cebbf4950967a92fe8025f75adffd89ce26cf9234be5d84a8`.
On native Linux, an isolated Bionic process loads b1977's controller tracker,
initializes it, registers its result callback, resets the left algorithm to kind
0 and accepts this calibration; each call returns zero. Hardware device access
is blocked for this probe, and it receives no motion or images. Process exit
ends the probe. This proves library/calibration acceptance, not a tracked pose.
The manifest-checked evidence is
`output/pico-vsync-controller-20261022-v2/export-tracker.tar.gz`, SHA-256
`6913a316610fbe65ed0b71f8ccaa54a1b87430338969ce5ea610d2ef68cfa850`;
the live collector receipt is `stock-controller-tracker-parameters.json` beside it.

### Controller image selection

`pico_station_camera_hand_mode` encodes b1977's `StationService::SetHandMode`:
station command 4, payload `[9, enabled]`, followed by the existing frame padding
and CRC. It performs no I/O and is not enabled automatically. The camera owner
must check both the command reply and the mode flag returned by camera status.
The off command reads back flag zero; a caller that still requires flag one
will abort before streaming.

The private head-camera bring-up owner previously forced hand mode on. Its
90-second captures contained alternating head/hand frames and no
controller-class frames. A 2026-10-22 native comparison turns hand mode off with
the maintained encoder and checks the zero readback. In an eight-second,
camera-only capture, each of four cameras delivers 397 frames: 199 head,
198 controller and zero hand. All four controller-class images are retained.
No DSP or estimator runs in that comparison, and no poses are published; head
6DoF and SteamVR with this image mode still require a combined test. It restores
the missing image class, not a working controller pointer. IMU/head matching,
image delivery to the accepted tracker and controller pose publication remain.

The ASan/UBSan station protocol suite passes with both mode packets and the
null-output refusal. The initial native attempt is retained separately: it sent
the off command successfully but stopped at the old on-mode assertion before
streaming. It is not evidence of an estimator regression. The corrected
camera-only export has 16 manifest-verified files:
`output/pico-vsync-controller-20261022-v3/export-classes.tar.gz`, SHA-256
`b0698cd9955796f7992e2e0f4d7e5caea48379ea06bde209b8b8077ffcffcccf`.
MCU references return to zero, boot/DTBO readbacks remain unchanged and stock
return is verified. The source, actual mode/readback and acceptance boundaries
are retained beside that export.

### Controller result confidence

The b1977 controller tracker is SHA-256
`9b9ba5484fc5df8f629fff0f9a1d5b130ae4929860252429614dad64c6a45c4a`.
Its `getAlgorithmControllerResult` does not expose an unmodified optical-valid
flag. For the left result, instructions `0x15f180`–`0x15f1b4` copy internal byte
`0xc4` into public confidence `0x41` and diagnostic `0x52`, then overwrite public
confidence with 1 when internal bytes `0xc4` and `0xd6` are both zero. The right
getter has the corresponding branch. This describes the getter, not the
physical meaning of either internal byte.

In the synchronized negative-control recording, all 497 confidence-1 callbacks
have diagnostic `0x52 == 0`, so their public confidence comes from this
overwrite. Real and all-black images produce byte-identical position and
orientation throughout all 6,235 callbacks. Public confidence 1, accepted image
calls, and pixel-dependent diagnostic `0x54` therefore do not establish optical
correction. Neither `0x52` nor `0x54` has a verified positive acceptance rule yet.
Keep controller pose publication disabled until image-content-dependent pose
correction, loss/recovery and the coordinate conversion are validated.

The disassembly, input hashes and reproduced field counts are retained in
`output/pico-controller-optical-20261023-v1/`; the original controls are in
`output/pico-controller-integration-20261023-v1/export-controls/`.

### Read-only stock pose reference

[`capture-pico-stock-controller.py`](../tools/capture-pico-stock-controller.py)
builds a small NDK ARM64 observer and captures 300 reads from the existing stock
controller shared buffer. It requires an already-offline b1977 headset with its
updater disabled, verifies the stock client hash and boot UUID, refuses the
client's fake-pose mode, verifies the transferred capture hash and removes its
own temporary device files. Its ordinary `CreateClient`/`GetControllerData`/
`GetControllerTrackingRawData` calls attach and read; it never calls an algorithm
start/stop, camera-control or controller setter.

```sh
python3 tools/capture-pico-stock-controller.py --serial DEVICE_SERIAL \
  --cc /path/to/NDK/bin/aarch64-linux-android29-clang \
  --output output/NEW_STOCK_CONTROLLER_REFERENCE
```

The data getter is necessary once to perform b1977's lazy buffer mapping. The
raw getter alone returned `-3` on all 300 initial calls; after that mapping,
300/300 raw reads succeed. Those successful reads are not tracking acceptance.
In the 2026-10-23 check, the left timestamp is unchanged and over five hours old
under both observation clocks. The right timestamp is `-1` despite public
confidence 1. The controller is not supplying a fresh positive reference in this
state. Two separate stock connection-status reads confirm both controllers are
disconnected. No command is sent to wake, pair or reset them.

The report retains public/internal confidence counts, timestamp changes and
ages against both `CLOCK_MONOTONIC` and `CLOCK_BOOTTIME`; it does not assume those
clocks are interchangeable after suspend. Getter copies also do not guarantee a
coherent snapshot. Fresh timestamps alone would still require image-content
controls and physical motion validation before establishing optical tracking.
Four host contract tests and the complete maintained observer pass on stock
Pico Android. Evidence: `output/pico-controller-optical-20261023-v1/stock-capture/`.

The connected Neo3 Pro Eye running 5.8.4.0 reports **MCU type 1, radio type 2,
touch enabled**. The stored touch property is empty while the live getter
returns 1; an empty property must not be interpreted as disabled. The MCU type
is the value published by stock startup into its configuration service; direct
revision readback remains unavailable. The configuration APK is SHA-256
`701ac92f7d5598f0f7dbd7fa5bdd276cbecc19c967e5472c3090396fb39f595f`.
Its getter dispatch and query implementation were inspected offline. Private
analysis and physical read receipts are retained in
`output/pico-controller-config-20261012-v1/`.

## Native Linux SSC transport

### Bounded physical receiver

[`build-pico-controller-capture.py`](../tools/build-pico-controller-capture.py)
builds the opt-in [`capture-pico-controller.c`](../tools/capture-pico-controller.c)
receiver on native ARM64 Linux. It verifies the installed SSC profile, source
archive and patched sources, compiles libssc into a separate executable, and
copies its GPL license. The installed tracking library is unchanged. Each build
also runs nine report-callback cases without accessing hardware, covering
attribute events, stream identity, shutdown, configuration replies, accepted
input, duplicate timestamps and corrupt records.

```sh
python3 tools/build-pico-controller-capture.py --output /tmp/controller-build
/tmp/controller-build/capture-pico-controller \
  BOOT_SERIAL SUID_HIGH SUID_LOW MCU RADIO TOUCH SECONDS
```

Supply the boot serial from the native kernel command line, the discovered
`ble_mcu` SUID, and this unit's verified stock configuration. The receiver
requires a matching boot serial, exact SUID, available continuous sensor,
calibrated monotonic clock and duration of 1–120 seconds. An owning service must
start SLPI and hold the MCU power reference separately. It does not start DSPs,
power the MCU, pair controllers or modify firmware.

The stock station service's SSC route requests 480 Hz although the `ble_mcu` metadata
omits the supported-rate list. The receiver sends that explicit standard
continuous configuration through the pinned SSC client, rather than changing
the generic library's rate-selection policy. A transport acknowledgement is
reported separately from configuration events and CRC-checked data. Normal
shutdown, signals and output errors drain pending work, disable an attempted
subscription and release the sensor/client objects. Timeout or incomplete
cleanup fails the process. Raw records are bounded; decoded axes remain
uncalibrated bytes and are not controller poses.

On 2026-10-22, release and UBSan builds compiled on the physical Neo3 Pro Eye.
Both passed the nine callback cases. The UBSan receiver also passed normal
subscription/shutdown, `/dev/full` output failure, cancellation during sensor
discovery, and absent-SUID refusal. All four cases ended with zero live SSC
objects; cases that attempted a subscription acknowledged its disable. The
test owner released the MCU power reference to zero. AddressSanitizer could
not start in this native environment because its own memory mapping failed
before `main`; that run provides no receiver validation.

Both controllers were disconnected in the preceding stock capture. Native
requests were acknowledged, but no controller reports arrived. This proves
bounded transport ownership, not working buttons, analog calibration,
controller tracking, haptics or SteamVR controller integration. Source-pinned
builds and test evidence are in
`output/pico-steamvr-session-20261022-v8/export-controller-final/`;
the verified carrier SHA-256 is
`12502fb65fe5e5734295167b08e57074d13c35145dd4a00ebdcb0c1436141e06`.

### Library and clock ownership

The native [libssc](https://codeberg.org/DylanVanAssche/libssc) source is pinned
in [`profiles/ssc.json`](../profiles/ssc.json), including its GPL-3.0-or-later
license. The complete library, CLI and test executables build on ARM64 Linux
with GLib 2.88.3, libqmi 1.36.0 and protobuf-c 1.5.2. Its QMI service 400 and
small/large report IDs `0x21`/`0x22` agree with the same-build Pico library's
recovered IDL tables. This establishes protocol overlap; it does not prove DSP
startup, SUID discovery or a physical `ble_mcu` subscription.

Upstream's `report` signal discards the outer DSP timestamp and frees its mutable
array after callbacks return. The pinned
[`report-timestamps` patch](../patches/libssc/0001-report-timestamps.patch) adds
`report-timestamped` with message ID, SUID high/low, raw 64-bit timestamp and
immutable `GBytes`. Consumers can retain the bytes with `g_bytes_ref`. The
original signal remains available with its existing arguments. The new payload
is copied independently, so a legacy callback cannot mutate retained data.
Timestamps remain raw DSP ticks; clock alignment is still the receiver's job.

The [main-context patch](../patches/libssc/0004-own-sensor-main-context.patch)
keeps synchronous client cleanup and the registry-discovery deadline on the
calling thread's GLib context. Upstream cleanup iterates the global context
instead, which can run unrelated callbacks and leave its own completion waiting
on another context. Its registry timer also uses the global context. The patch
retains the selected context, waits for its completion without busy polling,
and owns the timer as a source that can be destroyed on its actual context.

The original wrong-context dispatch is reproduced under native ARM64 sanitizers.
The patched source passes 128 private-context completions, registry timeout and
timer disposal checks. The packaged library also completes three real QRTR
discovery/open/report/close cycles on a private context in the Pico-kernel VM;
the default-context and protocol negative controls pass too. Evidence is under
`output/pico-ssc-context-20261012-v1/`. This verifies context ownership, not all
cancellation and DSP-loss paths or a production sensor worker.

The [pending-operation patch](../patches/libssc/0005-own-pending-sensor-operations.patch)
fixes a reproduced crash when an enable request fails and a late measurement
uses the freed task. Discovery, attributes and enable now share explicit
operation ownership: completion removes the report handler, deadline and
cancellation source exactly once, while outstanding transport callbacks retain
their own reference. A thirty-second deadline covers the complete discovery
sequence and each enable. Cancellation is dispatched on the owning context;
a concurrent enable is refused, and close cancels a pending enable.

Fourteen native sanitizer cases cover transport errors, cancellation and timeout
at each phase, a report arriving before its acknowledgement, and a second enable
while one is pending. The previous revision's crash and missing cancellation and
enable deadline are retained as negative controls. The packaged library passes
five diskless Pico-kernel suites, including actual QRTR cancellation on a private
context, both-hand device inputs and three reconnects on each context. All 397
host tests pass. Evidence is under `output/pico-ssc-operation-20261012-v1/`.
The DSP endpoint remains mocked; physical startup and transport loss still need
device validation.

The [close-error patch](../patches/libssc/0006-log-close-errors-before-transfer.patch)
fixes a further use-after-free found by removing the mock SSC server during a
live subscription. The close callback logged an error after transferring it to
a task; the caller can consume and free that error synchronously. Logging now
precedes the ownership transfer. The original failure reproduces under ARM64
AddressSanitizer, and the patched source passes 100 alternating successful and
failed closes. The server-loss case also exits cleanly on the exact Pico kernel
in QEMU. Failed runs, the crash backtrace and passing results are retained under
`output/pico-ssc-session-20261012-v1/`.

[`ssc-clock`](../src/ssc-clock.h) maps the outer 19.2 MHz timestamp into an
explicitly selected host-clock domain. Initialization takes a CPU QTimer read,
its measured frequency and two host-clock readings bracketing that read. It
rejects an excessively wide bracket and carries its uncertainty into each
sample. Integer arithmetic preserves small deltas above double's precision
and checks the entire timestamp interval for stale or future data. Rejected
input preserves state and output. The caller must recalibrate and reset stream
ordering after resume, reconnect or a DSP reset; no hardware clock origin is
inferred. This does not align the separate timestamps inside controller IMU
payloads.

The mapper passes macOS and ARM64 Linux sanitizer fixtures, including the full
64-bit range, mismatched CPU/DSP frequencies and calibration boundaries. An
independent exact-rational comparison covers 30,000 timing intervals. The
native SSC controller client also uses it on both-hand reports in the Pico
kernel VM. Evidence is under `output/pico-ssc-clock-20261012-v1/`; its clock
calibration and DSP reports are synthetic, so physical timing remains unverified.

[`ssc-clock-linux`](../src/ssc-clock-linux.h) provides explicit Linux ARM64
counter acquisition for a session's calibration callback. It brackets
`CNTVCT_EL0` with `CLOCK_MONOTONIC`, checks `CNTFRQ_EL0` on both sides, and keeps
the narrowest acceptable bracket from a bounded number of attempts. Counter
resolution is added to the uncertainty. Invalid clock results, reversed time,
frequency changes or an excessive bracket fail without changing the output.
The target kernel must permit userspace counter access; this is not an automatic
probe or proof that the CPU and DSP share an origin.

Injected clock failures and 64 real captures pass native ARM64 sanitizers. The
same capture fixture passes on the exact Pico kernel in diskless QEMU, along
with the eight SSC session scenarios. The native lab reports a 24 MHz counter
and QEMU reports 62.5 MHz, exercising conversion to the SSC 19.2 MHz domain.
Evidence is under `output/pico-ssc-counter-20261012-v1/`. These are host and
virtual counter measurements; physical Pico sensor timing remains unverified.

[`pico-controller-stream`](../src/pico-controller-stream.h) combines the payload
decoder and clock mapper with subscription identity. Each new subscription has
a generation number; callbacks must retain their original number. Reports from
an old generation, another SUID, or another message type are refused. Timestamp
ordering is independent for each hand, so a newer left-hand report does not
discard a valid right-hand report. Duplicate, reversed, stale, future and
host-clock-regressing reports leave both stream state and output unchanged.
Disconnect invalidates the stream immediately; consumers must release active
controls and obtain a fresh calibration before resubscribing.
macOS and ARM64 sanitizer tests cover 3,058 refusals and 1,000 subscription
generations. The native QRTR client completes three discovery/open/delivery/close
cycles with the packaged library on the Pico kernel; all ten suites pass.
Evidence is under `output/pico-controller-stream-20261012-v1/`. DSP reports and
clock calibration remain synthetic.

[`pico-monado-device`](../src/pico-monado-device.h) creates left and right
`xrt_device` objects using the pinned runtime's device helpers. A separately
owned producer publishes accepted stream events under a mutex; `update_inputs`
copies complete snapshots into the runtime-owned arrays. Each hand times out
independently, clearing values and deactivating inputs. Transport disconnect or
producer destruction also clears the next snapshot. Devices and the producer
can be released in either order; a new connection requires a newer generation.
The source clock must be calibrated to Monado's `CLOCK_MONOTONIC` domain.
No pose tracking or output capabilities are advertised. Pose queries return an
invalid relation, not a simulated controller position.

The device callbacks, upstream allocation-independent device helpers and unique
IDs pass macOS and ARM64 AddressSanitizer/UndefinedBehaviorSanitizer tests.
ThreadSanitizer also passes on macOS, including 20,000 events across 1,000
generations with concurrent per-hand snapshots and device destruction. The
runner is `tools/test-pico-monado-device.py`; evidence is retained under
`output/pico-monado-device-20261012-v1/`. These tests use synthetic events.
The exact Pico kernel also passes SSC discovery, decoded both-hand reports,
device callbacks, disconnect clearing and three reconnect cycles in diskless
QEMU. The fixture uses synthetic DSP reports and an explicit monotonic clock
anchor with a ten-second test age limit; it does not establish hardware latency.
The factory is connected to the session owner and opt-in runtime prober below.
No controller subscription is enabled automatically in a headset image.

[`pico-ssc-session`](../src/pico-ssc-session.h) owns discovery, subscription and
shutdown on a dedicated GLib context and thread. It discovers the `ble_mcu` SUID,
calls an explicit monotonic-clock calibration provider, and publishes validated
reports to the two device objects. MCU/radio configuration and analog
calibration remain explicit inputs. Invalid calibration fails startup.
Missing valid reports cancel the subscription and release controls; malformed
traffic cannot keep the session alive. There is no automatic reconnect using
an old clock calibration.

Stopping cancels pending operations, attempts sensor disable, disconnects report
callbacks and drains the context until the sensor and client are destroyed.
It then joins the worker before releasing the producer. Devices can be released
independently and may outlive the session. Status and counters are copied under
a mutex; a failed startup or lost stream remains visible to the runtime owner.
This source does not register a runtime builder or start the DSP.

[`pico-monado-prober`](../src/pico-monado-prober.h) adapts the session to Monado's
auto-prober interface. It stays inactive unless `PICO_SSC_CONFIG` names a
successful b1977 receipt from the collector above and `PICO_SSC_COUNTER=1`
explicitly enables ARM counter calibration. This is a developer opt-in; the
receipt is not proof of the identity of the machine running Monado or of a shared
CPU/DSP clock origin. It must only be used with the corresponding headset.
No configuration file or environment setting is installed automatically.

The prober accepts a bounded regular JSON file, rejects ambiguous or unsupported
configuration, opens at most one session, and creates only the two controllers.
It owns the session until prober destruction; devices may outlive it. The
initial limits are 100 ms sample age and 500 ms stream/hand timeout, pending
physical latency validation. Analog calibration remains absent, so only digital
and enabled touch inputs can become active. It creates no HMD or tracked pose.
The optional Pico build registers this prober in Monado's legacy device discovery.
Other system builders do not acquire the controllers through that path.

`tools/test-pico-monado-device.py` also compiles the actual prober with upstream
Monado headers and cJSON. Its 123 checks include 100 create/destroy cycles,
explicit opt-in, session-start failure, bad/duplicate configuration fields,
binary/trailing data, oversized files and nonregular paths. The session and
counter calls are stubbed in this boundary test; transport is tested separately.
macOS and Linux ARM64 sanitizer results are retained under
`output/pico-monado-runtime-20261012-v1/`.

The packaged runtime also passes a full OpenXR IPC test on the exact Pico
Linux-userspace kernel. `tests/pico-monado-runtime-vm.py` runs Monado against
the real QRTR stack and a synthetic SSC producer, with a simulated HMD and
Lavapipe null compositor. The OpenXR client waits for session focus and action
synchronization, then checks the native Pico interaction profile, independent
left/right button and touch states, releases, and deactivation after malformed
reports. Uncalibrated analog inputs and unimplemented poses remain inactive.
Two service/client lifecycles pass with clean shutdown. Counter timestamps use
the virtual CPU counter; this does not establish a physical CPU/DSP clock origin.

The October 13 runtime was rebuilt against the eleven-patch SSC bundle,
including calibration startup, rigid-body identity, exact SUID selection and
supported-rate selection. Existing controller discovery keeps its default behavior.
All 25 upstream test executables and the display regressions pass. The OpenXR
test also passes both lifecycles on the rebuilt FastRPC kernel; evidence is in
`output/pico-native-sensors-20261013-v1/runtime-vm-v1/`.

The derived root `output/headset-root-pico-native-sensors-20261013-v1/` passes
exact Monado/SSC readback, permissions, filesystem checks and symbol resolution
across 485 ELF dependencies. Kernel modules, firmware and FastRPC remain intact;
its parent remains unchanged. The unsigned boot container in
`output/pico-boot-container-20261013-v1/` binds that root and passes assembly
and unpacking checks. Native head-IMU session code is tested separately and is
not started by this runtime. None of these tests establish physical boot,
recovery, panel output, tracking, controller pairing or flash readiness.

`tools/test-pico-ssc-session.py` builds against the pinned Monado source and a
verified SSC bundle. On native ARM64, 100 alternating immediate-cancellation
and unavailable-QRTR cycles pass AddressSanitizer/UndefinedBehaviorSanitizer.
`tests/ssc-session-vm.py` tests the actual session over QRTR on the Pico kernel:
three both-hand start/stop cycles, immediate stop, absent service, invalid clock,
delayed enable acknowledgement, loss of valid reports, all-malformed reports,
and abrupt server termination. All eight scenarios pass and the VM shuts down
normally. The DSP producer and clock anchor are synthetic; the two-second
fixture time limits are not physical latency measurements. Evidence is under
`output/pico-ssc-session-20261012-v1/`.

[`pico-monado-input`](../src/pico-monado-input.h) maps accepted events to Monado's
existing Neo3 input names: X/Y on the left, A/B on the right, menu/system,
trigger, stick and grip, plus supported touch inputs. It clears values and
deactivates inputs on disconnect. Analog calibration supplies explicit released
and pressed endpoints, stick centers, ranges, dead zones and axis inversion.
Without calibration, analog inputs remain inactive. The stock service's disabled
axis value of 128 is not used as physical calibration. Grip and aim pose inputs
remain inactive; no tracking result is invented.

Run the adapter tests against the hash-verified Monado archive:

```sh
python3 tools/test-pico-monado-input.py /path/to/monado-source.tar.gz \
  --output /path/to/new-results
```

macOS and native ARM64 sanitizers pass 6,912 mapping checks using actual Monado
headers. Evidence is under `output/pico-monado-input-20261012-v1/`. The adapter
also receives both-hand events through the native SSC client on the Pico kernel,
including three reconnect cycles and disconnect clearing (`controller-vm-v1/`).
Its calibration and DSP producer are synthetic. The adapter
still needs a verified physical calibration source and live headset validation.

On a Linux host with the listed development dependencies, run:

```sh
python3 tools/test-ssc-reports.py /path/to/pinned/libssc --output /path/to/new-results
```

The runner verifies source hashes, applies the patches with zero fuzz, generates
protobuf-C bindings, and tests the actual original and patched dispatchers with
AddressSanitizer and UndefinedBehaviorSanitizer. It checks multiple reports,
SUIDs, zero and maximum timestamps, malformed outer messages, legacy mutation,
and payload decoding after the wire buffer and client have been destroyed.
The encoded events also pass an independent Google protobuf parser loaded with
the exact Pico `sns_client.proto` and `sns_ble_mcu.proto` descriptors.

The [`object cleanup` patch](../patches/libssc/0003-release-partial-and-repeated-disposal.patch)
also releases a partially initialized client's QRTR bus and makes repeated
sensor disposal safe. The same runner reproduces the original bus leak and
double-free, then checks the patched source with sanitizers and GObject weak
references. The rebuilt library passes all 15 upstream cases and the three
controller cases on the Pico kernel. Evidence is under
`output/pico-ssc-lifetime-20261012-v1/`; `controller-vm-v1/verification-v2.json`
rechecks the saved kernel records after the original host checker incorrectly
expected three suites instead of ten. This does not verify physical reconnects.

The dispatcher test does not open QRTR or start a DSP. Docker's current kernel
does not provide AF_QIPCRTR. A separate diskless VM runs the exact Pico kernel
with a userspace QRTR name service: all 15 upstream cases in seven suites pass,
including discovery and sensor samples against the upstream DSP mock. See
[Qualcomm services](qcom-services.md) for the missing name-service dependency.
Live stream lifetime, suspend/resume, physical clock calibration and controller
input delivery remain open integration work.

[`ssc-build.py`](../tools/ssc-build.py) builds the pinned source archive on native
ARM64 Linux, runs the source regression tests, and packages the installed library
and CLI under `/opt/reframed-vr/ssc`. Four pinned Fedora runtime dependencies are
included with their licenses; the bundle uses the root's GLib and C library.
RPM verification checks those dependency files before copying. The original SSC
source archive, local patches and license accompany the runtime. The builder
requires an immutable container image ID for its provenance record and performs
no downloads:

```sh
python3 tools/ssc-build.py /path/to/libssc-source.tar.gz \
  --output /path/to/new-bundle --image-id sha256:CONTAINER_IMAGE_ID
```

`build-headset-root.py --ssc /path/to/new-bundle` installs the validated bundle
for a Pico root with QRTR services. It checks exact inventory, hashes, permissions
and links, verifies native relocations using the root's loader, runs the CLI's
version command, and reads the installed files back from ext4. This adds no
automatic sensor subscription or DSP startup. Consumers must select the bundle's
`lib64` directory explicitly.

The offline root at `output/headset-root-pico-ssc-20261012-v1/` contains this
bundle. Its parent image was preserved and rehashed unchanged. Native loader,
missing-dependency refusal and ext4 readback evidence are retained under
`output/pico-ssc-root-20261012-v1/`. Physical sensor operation and custom boot
acceptance remain unverified.
The exact packaged library and CLI also pass the ten-suite Pico kernel VM run
in `controller-vm-v2/`, including 15 upstream tests and both-hand controller
delivery. The earlier fixture omitted a parent directory; its failure is retained
in `controller-vm-v1/`.

Pico controller samples also expose an upstream subscription-startup mismatch:
`ble_mcu` reports message `1024`, while libssc normally completes sensor opening
on measurement `1025`, proximity measurement `769`, or a configuration event.
[`ble-mcu-startup`](../patches/libssc/0002-ble-mcu-startup.patch) recognizes `1024`
only for the `ble_mcu` data type. It does not treat arbitrary vendor message IDs
as a successful subscription.

The public-API client in [`tests/ssc-controller.c`](../tests/ssc-controller.c)
and [`SSC mock extension`](../tests/ssc-controller-mock.py) exercise discovery,
subscription, timestamped delivery, both-hand decoding and close over real QRTR
in the isolated Pico kernel VM. The mock advertises a 480 Hz stream and sends
the existing stock-validated synthetic records, malformed payloads, another
SUID and an unrelated message ID. Both programs require the explicit VM marker;
they are not physical-device test launchers.

With the timestamp patch alone, the client receives 19 valid samples and rejects
seven malformed payloads, but opening never completes. With both patches,
opening and closing succeed after four valid samples from both hands and one
malformed-payload rejection. A different data type emitting `1024` still cannot
complete opening. The same library passes the 15 generic upstream cases and
the dispatcher sanitizer checks. Evidence is retained under
`output/pico-ssc-transport-20261012-v1/research/controller-vm-v2/` and
`controller-vm-v1/generic-verification.json`. A real Pico stream may require
additional configuration; these results establish the virtual protocol path.

## Station interrupt driver

The authenticated b1977 kernel supplies the separate `/dev/stationdev` interface
missing from the published source. Recovered symbols, relocations and instruction
analysis identify a platform driver with compatible `bytedance,station`, GPIO
property `station-sync`, and a rising-edge, one-shot threaded IRQ. Its file
operations are open, poll and release; there is no read, write or ioctl data path.
An interrupt makes poll return `POLLIN | POLLRDNORM`; polling consumes that
notification. Multiple interrupts can coalesce into one readiness result.

[`0024-station-notifications.patch`](../patches/kernel/pico-neo3/0024-station-notifications.patch)
implements this interface and adds `CONFIG_PICO_STATION`, requested by the Pico
Linux profile. The GPIO direction remains owned by the device tree, as in stock.
Each open file tracks its own event sequence, so opening or polling another file
cannot erase its notification. Removal unregisters and drains the IRQ, wakes
waiters with `POLLERR | POLLHUP`, and retains state until existing files close.
Rebinding creates independent state; old descriptors keep reporting disconnect.
Probe errors release resources and retain deferred-probe error codes.

The patched source compiles as an ARM64 kernel object with `-Werror` against the
headers and recorded flags from the accepted physical-configuration Pico build.
All 26 imported symbols exist in that kernel, and the kernel's configuration
resolver retains `CONFIG_PICO_STATION=y` with its OF and GPIOLIB dependencies.
The fault harness compiles the actual driver functions with kernel API stubs:
**74 cases** pass with AddressSanitizer and UndefinedBehaviorSanitizer on macOS
and Linux ARM64, including 64 concurrent IRQ/poll/removal races. It checks probe
failures, independent readers, counter wrapping, detach and rebind. `just check`
runs this harness; `tools/test-pico-station.py SOURCE_MISC --output NEW_DIRECTORY`
also verifies the pinned build files and applies the patch with zero fuzz.

The complete physical-configuration kernel now builds with this driver enabled.
All 38 module signatures, 2,715 imported symbol versions and dependencies pass
verification. A diskless virtual boot checks the full loaded Image and passes
the Android ABI regression before shutting down normally. This virtual board
does not exercise the station GPIO or its interrupt handler.

Physical GPIO routing, interrupt delivery, suspend and stock-service
interoperability remain unverified. The driver supplies notifications only;
SSC controller data and optical tracking remain separate requirements. The new
kernel and the previously accepted image are both retained; see
[kernel verification](pico-firmware.md) for the artifact identity.

## Native station SPI

On the b1977 Neo3 Pro Eye, the stock SPI device tree supplies the data interrupt
and RFIC IO3 line but omits `rfic-io2-gpio`. The resource-lifetime patch initially
required all three, causing native `spidev_probe` to fail with `-ENOENT` and
preventing `/dev/spidev0.0` from appearing.

`0052-controller-optional-rfic-io2.patch` makes only an absent IO2 property
optional. A present malformed or deferred property remains an error. Its GPIO
control ioctl returns `-ENODEV` when the line is absent; subsequent ioctls still
work. No substitute GPIO is selected. The actual driver functions pass 166
sanitizer lifecycle/fault cases, including 64 concurrent removal races and a
reproduction of the original missing-property failure.

The rebuilt kernel binds this SPI device on the headset at stock mode 0, 6 MHz,
8 bits. After acquiring one normal MCU power reference at the existing 1.8 V
setting, native Linux receives CRC-valid firmware-version and camera-status
responses. The absent-IO2 rejection and subsequent ioctl also pass on hardware.
The kernel configuration, signing certificate, symbol versions and all 38
installed modules remain byte-identical to the preceding native kernel.

`pico-station-protocol` encodes bounded camera-control commands and validates
fixed-size responses without opening a device. Its packet layout and CRC match
70,937 cases against the exact Neo3 stock encoder; 1,310,720 single-bit-corrupted
frames are rejected. PicoFrame's MIT `rootfs/pico-station.c` was also used as
protocol reference; its PICO 4 GPIO and device-tree configuration were not used.
Evidence is retained in
`output/pico-recovery-bringup-20261018-v1/neo3-6dof-v1/`. These checks establish
station transport, not camera capture, physical controller tracking or 6DoF.

### Controller IMU command

`pico_station_controller_imu` encodes command `AA 01 07` with payload
`[hand, enabled]`. Neo3 uses hand **1 for left, 2 for right**. The b1977
`libstationopticsservice.so` (SHA-256
`91b45470678ca7d614a7f12ccb21261f3cda273c4ba6b08c1edb153cd5b6286e`)
passes roles 2/3 from `GetCalibration` at `0x549e8`, then subtracts one in
`_SetImuStreaming` at `0x53f3c`. PicoFrame's MIT
[`pico-station.c`](https://github.com/TheReal-Flo/PicoFrame/blob/3affbc11ecaae56c56b7bd3eb13344c73a7a03da/rootfs/pico-station.c)
was a reference for this command; its PICO 4 hand selectors 0/1 do not apply
to this Neo3 implementation.

The encoder does no I/O and is not enabled automatically. Host ASan/UBSan and
native ARM64 tests pass all 12 packet vectors, invalid selectors, null outputs
and 320 corrupted response frames. The staged native sources match the
maintained sources; receipts are in
`output/pico-controller-delivery-20261022-v2/export-stream-enabled/`.

The physical PR0513 station returned a valid version response, but no `BB 01 07`
acknowledgment to the tested left enable/disable requests. Enabling did not
populate the controller ring. Fresh stock logs in the `v2` and `v3` delivery
sessions also report an IMU-enable failure, followed by live left-controller
IMU samples. This verifies the packet encoding only; a successful response to
this command is not an established prerequisite for controller delivery.

## Verification

An isolated ARM64 Linux process executed the stock CRC and key parsing functions
against synthetic buffers, with both controllers online, service key masks
enabled, the test hook disabled, and callbacks/logging avoided. It did not run
ELF constructors, Android service initialization or hardware operations. The new
decoder matched all eight output fields on **16,384** records covering both
hands, all button bits, both MCU/radio modes, touch enabled/disabled and all
256 battery values. CRC bytes for those comparisons came from the original
function rather than the new implementation.

Sixteen fixed records and expected outputs are retained in
[`tests/pico-controller.c`](../tests/pico-controller.c). The fixture passes
**51,946** decoding and rejection checks on macOS ARM64 and Linux ARM64 with
AddressSanitizer and UndefinedBehaviorSanitizer. It tests unaligned buffers,
every short length, overlong records, unsupported configuration, records without
key data, every single-bit corruption in each complete record, and SSC framing,
word counts, accuracy and unknown fields. Rejection preserves both outputs.
`just check` compiles and runs this fixture.

An independent Google protobuf parser loaded with the device's exact descriptors
agrees on 4,096 payloads, including mixed encodings and reordered fields. A
separate 200,000-case mutation run passes both sanitizers on macOS and ARM64
Linux. The libraries, descriptors, bounded Ghidra analysis and comparison scripts
are retained in `output/pico-ssc-transport-20261012-v1/`. No live sensor stream
was started for these checks.

The private firmware, analysis, comparison runner and results are retained in
`output/pico-block-ota-20261011-v1/`. Physical button/axis captures, SSC transport
startup and lifetime, physical station-driver operation, pairing, haptics and optical
controller tracking remain unverified. This decoder establishes offline parsing
compatibility, not a working physical controller driver or flash readiness.

## Input transport to SteamVR

`pico-controller-channel` is a separate 128-byte shared-memory input channel.
It stores the latest decoded sample for each hand in two alternating slots.
A single producer owns a new mapping and nonzero instance for its lifetime;
restarting it requires a new file and instance. Atomic publication lets readers
retain the last completed slot while the writer is preempted, with bounded
retries if another publication occurs during a read.

A producer validates complete reports with `pico_controller_decode` and supplies
host `CLOCK_MONOTONIC` receipt times that increase per hand. The channel rejects
unsupported hands/fields, duplicate or regressing times, and a writer already
publishing. A reader binds the instance and hand, samples its clock after a
consistent copy, and rejects inactive, future or stale data without changing
its output. Disconnect clears activity while retaining the last receipt time.
Receipt age does not establish capture latency or controller clock calibration.

This module neither starts the MCU/DSP nor derives a controller pose. The native
FastRPC worker below supplies its records. Production session orchestration and
application bindings remain separate from this channel API. See
[SteamVR input integration](pico-steamvr.md#optional-controller-input).

### Native FastRPC input worker

[`pico-controller-input.c`](../tools/pico-controller-input.c) maintains the native
b1977 receive path separately from the earlier ordinary-SSC capture tool. Its
[`builder`](../tools/build-pico-controller-input.py) verifies the pinned Qualcomm
SDK archive and a caller-supplied, previously verified FastRPC runtime manifest,
builds current RPC wrappers into the executable, and runs ring/RPC tests under
UBSan. It records source and binary hashes; it neither installs nor starts a
receiver. The runtime manifest maps relative prefix paths to `sha256` or
`symlink` records, including every symlink target. It must come from verified
runtime evidence, not hashes generated from an unknown installation.

```sh
python3 tools/build-pico-controller-input.py \
  --runtime-manifest VERIFIED_FASTRPC_MANIFEST.json --output BUILD_DIRECTORY
```

The worker requires native Linux, this unit's boot serial `c980c8d4`, an explicit
current boot UUID, root and an already-online SLPI. The session owner must first
verify the b1977 firmware/configuration and supply `DSP_LIBRARY_PATH` and the
verified FastRPC `LD_LIBRARY_PATH`. The worker uses the measured MCU type 1,
radio type 2, touch support, controller SUID and 1,000-byte buffer contract. It
does not infer those settings for another unit or firmware revision.

```sh
BUILD_DIRECTORY/pico-controller-input \
  --boot-id CURRENT_BOOT_UUID --channel /run/NEW_CONTROLLER_CHANNEL \
  --instance NEW_NONZERO_16_DIGIT_HEX --seconds 120
```

The new file is created exclusively and a process lock excludes another worker.
The receiver owns its FastRPC clients, registered DMA buffers and input channel.
It does not open the MCU command device, pair controllers, power a DSP or change
audio. The session retains exclusive MCU ownership and must send the verified
`pico_station_camera_pacing(1)` request; camera startup already does this.
`--companion-accel` reproduces the tested slow accelerometer stream after one
second for a standalone controller diagnostic. The shared head-IMU/camera test
works without that additional subscription; it is omitted by default. This does
not establish controller delivery with every head sensor subscription absent.

[`pico-controller-ring`](../src/pico-controller-ring.h) compares two CPU-synchronized
snapshots, validates each record with the maintained decoder and selects only
the newest station timestamp per hand. Changed slot order cannot rewind input.
Duplicate, torn, CRC-invalid, zero-time or regressing records cannot refresh
channel activity. A restarted DSP needs a fresh reader, mapping and instance;
the timestamp at byte 56 is used only for ordering, not host-clock conversion.

The separate `pico_controller_ring_read_motion` API retains up to 20 new IMU
slots per snapshot rather than collapsing them into the newest digital report.
It sorts by wire timestamp, deduplicates per hand and refuses conflicting
measurements at the same hand/timestamp without advancing either hand. It also
filters the explicitly connected hands. Initialize a fresh motion reader after
connection, resume or DSP restart. Torn/CRC-invalid slots are skipped; missing
samples and stale data still require downstream clock, age and gap checks.
The default digital worker retains its newest-only behavior. Its optional motion
mode below publishes this ordered history separately.

Host ASan/UBSan tests and an Android ARM64 UBSan CPU test pass ordering, full-ring
wrap, duplicate/conflicting samples, sequence-byte wrap and torn/corrupt records.
Replaying 7,402 saved physical snapshots on both CPUs yields exactly the same
7,446 samples as the independently decoded recording, including all IMU fields.
The replay does not start sensors or establish live optical tracking. Evidence:
`output/pico-controller-optical-20261023-v1/motion-ring-native-result.json`.

### Ordered motion channel

[`pico-controller-motion-channel`](../src/pico-controller-motion-channel.h) is
a separate 32,832-byte channel for the native receiver and Bionic controller
tracker. One producer retains 256 converted IMU events, including the raw
microsecond timestamp, calibrated monotonic capture interval, receipt time,
hand, sequence byte, flags and all nine stock tracker values. Capture times
increase per hand; events in one receive snapshot may share a receipt time.
The producer never waits for a consumer.

Each reader binds the process instance and estimator generation and maintains
its own sequence cursor. It copies the next event consistently, then samples
the clock and enforces an explicit age bound of at most 100 ms, including
timestamp uncertainty. A stopped stream cannot publish again. Missing unread
history returns `EOVERFLOW`; stale data returns `ETIMEDOUT`. Neither refusal
advances the cursor or changes its output. Restart the tracking stream explicitly
rather than silently skipping those failures. Consumers still need per-hand gap
checks and fresh head-history brackets before calling the vendor estimator.

The channel does not infer factory calibration, connection state or an optical
pose, and does not enable a live motion producer automatically. Host
ASan/UBSan and stock-Pico ARM64 UBSan tests pass timestamp/identity boundaries,
overrun detection, torn publication, permanent stop and 100,000 cross-process
events with every payload field checked. The native test uses recorded/synthetic
inputs only; it does not start sensors. Evidence:
`output/pico-controller-motion-20261023-v1/motion-channel-native-result.json`.

### Optional worker motion producer

The receiver accepts an explicit `--motion-channel` path, a nonzero 16-digit
`--motion-generation`, and `--left-motion-config` and/or `--right-motion-config`.
Each hand argument contains the verified revision, double-scale and axis-bypass
bytes in lowercase hexadecimal, separated by colons. These are caller-supplied
stock settings, not connection discovery or defaults. Use a fresh verified
connected-controller status; disconnected cached settings are insufficient.

[`pico-controller-motion-producer`](../src/pico-controller-motion-producer.h)
joins stable snapshots, ordered raw slots, calibrated timestamp conversion,
the nine stock tracker values and channel publication. It validates every event
in a snapshot before publishing that batch. Any conflict, invalid clock/input,
or later silence over 100 ms permanently stops motion. A selected hand that
never supplies input within two seconds also stops it. Late data cannot revive
that stream. Digital input may continue; normal shutdown still closes RPC
clients and retains DMA buffers until the shared SLPI is offline. A motion
failure is logged separately and makes the worker's eventual exit unsuccessful.

The parent `ControllerSession` accepts an optional `motion` dictionary with the
estimator's hexadecimal `generation` and each selected hand's complete connected
stock byte settings. It records them and supplies the worker's arguments.
`motion_endpoint()` declares the future path and binding before startup; it is
not readiness. Prepare the Bionic consumer before starting the receiver so
library/calibration startup cannot consume the bounded history window.
`wait_motion_ready(timeout)` then requires initialization and samples from all
selected hands. `motion_binding()` additionally checks file identity, generation,
active state and capture age. The consumer must use the C channel reader to copy
events and check uncertainty/overruns, then obtain fresh head brackets before
calling the estimator. These settings do not enter SteamVR's pose environment.

Host sanitizer tests, 12 parent-session lifecycle fixtures, and ARM64 Linux
builder/unit/dependency checks pass. On both host and Pico ARM64 CPUs, 7,402
saved snapshots pass through the complete producer/channel/reader path, yielding
the same 7,446 samples and bit-identical nine-value conversions. The replay uses
the recording's measured offset and a declared conservative 51,002 ns capture
uncertainty. It tests recorded delivery, not a new live DMA session or an optical
controller pose. A subsequent
[combined live test](pico-steamvr-verification.md#live-bionic-controller-inputs-and-pre-exec-capture-2026-10-23-utc)
verifies IMU delivery into Bionic; optical pose publication remains unverified. Evidence:
`output/pico-controller-motion-20261023-v1/producer-native-result.json` and
`worker-final-build/build.json` beside it.

Duration expiry or SIGINT/SIGTERM disconnects both hands and closes RPC clients.
`PICO_CONTROLLER_WAIT_DSP_OFFLINE` tells the session owner to stop its remaining
head/camera clients and shut down SLPI. The worker retains DMA registrations until
the subsystem reports `OFFLINE`, including after RPC errors. The owner must not
kill the worker while SLPI can still access its buffers. Only
`PICO_CONTROLLER_RELEASED_DSP_OFFLINE` and process exit complete shutdown. This
deliberately shares the head session's DSP lifetime rather than independently
restarting the controller worker during head tracking.

The [shared-sensor hardware test](pico-steamvr.md#maintained-receiver-and-shared-sensors)
verifies this worker with native SteamVR, head IMU and four-camera capture,
including ordinary shutdown. Fault-injected RPC lifecycle tests remain separate
from physical failure recovery.

### Bionic motion consumer

[`pico-controller-motion-consumer`](../src/pico-controller-motion-consumer.h)
drains the ordered motion channel into a caller-supplied estimator callback.
It borrows the generation's raw head history; the caller serializes history
updates and polling on the tracking thread. Prepare the estimator before the
receiver starts, then create the consumer after the channel is initialized.

A missing future head bracket retains one pending event and preserves delivery
order. It does not extrapolate a head pose or discard an old event to catch up.
Channel identity, overruns, observed stops, per-hand capture gaps, input age,
clock regression and estimator errors terminate this consumer permanently.
Head tracking and the receiver remain owned by their existing lifecycle. A
head-tracking loss cannot produce an identity fallback. Polling performs no
allocation or wakeup syscall and drains a bounded batch. Status records input
age, time waiting for a head bracket and elapsed estimator-call time. A call
that returns after the age limit also stops the consumer.

Host ASan/UBSan tests and a Pico Bionic UBSan CPU harness pass delayed-bracket
delivery, ordered batches, loss, channel stop, overrun, wrong hand, capture gap,
clock regression, stale input and estimator failure/overrun cases. This verifies
the adapter contract, not a live controller estimator or optical pose.
Evidence: `output/pico-live-controller-timing-20261023-v1/controller-tests.log`
and `motion-consumer-native-result.json` beside it.

The subsequent native SteamVR/head-camera test delivers all 23,352 received
left IMU samples into the stock Bionic controller estimator with matching raw
head brackets. A longer run delivers all 9,806 samples published before a
receive interruption. In that longer run, native input-report counts later
resume and rise from 9,703 to 40,891, while the motion channel remains stopped.
This is the current fail-closed contract, not automatic controller recovery:
button reception can resume without reviving motion delivery. A production
recovery path must reset/rebind estimator state and publish a new motion
generation before accepting fresh samples; it must preserve the shared SLPI
DMA lifetime. No optical controller pose or SteamVR pointer is established by
these input-delivery measurements.

### Bionic boundary and performance

The controller estimator requires the stock Bionic ABI and executes native
ARM64 code. That choice does not establish its performance against another
estimator. The motion channel above carries small IMU records; camera transport,
head-history waiting, estimator execution and pose delivery need separate
measurements. Keep estimator work outside the compositor thread and avoid
additional copies of camera frames where the vendor ownership contract permits.

A CPU-only test on this stock b1977 Pico passes synthetic events from a static
glibc producer to a Bionic consumer through the unchanged motion channel. It
compares 0.5 ms consumer polling with a nonblocking `eventfd` notification for
every event. Three three-second trials per configuration deliver all 54,000
events without an overrun or read refusal. Rates are total synthetic events per
second, not measurements of a connected controller. The table reports the range
of each trial's 99th percentile, its worst observed delivery interval, and combined
producer/consumer thread CPU time as a percentage of one core.

| Wakeup | Events/s | Delivery p99 | Worst delivery | CPU, one core |
|---|---:|---:|---:|---:|
| 0.5 ms polling | 1,000 | 0.430–0.562 ms | 1.66 ms | 6.5–6.9% |
| 0.5 ms polling | 2,000 | 0.492–0.607 ms | 8.25 ms | 9.1–9.2% |
| Per-event notification | 1,000 | 0.257–0.438 ms | 5.31 ms | 14.2–15.0% |
| Per-event notification | 2,000 | 0.173–0.335 ms | 9.75 ms | 28.2–29.0% |

Polling-mode publication and successful reads have median elapsed operation
times of approximately 2 and 3 microseconds respectively. Those operations
exclude waiting for the next polling deadline. Per-event notification lowers
typical delivery latency but raises measured CPU use and does not eliminate
outliers; it is not adopted by the maintained receiver. Evaluate batching or
draining from the existing tracking loop before adding a per-sample wakeup.
The channel's 100 ms age ceiling rejects stale input; it is not a buffering delay
or an acceptable target for normal tracking latency.

This test uses ordinary stock Android scheduling, without affinity or frequency
overrides. It does not run cameras, the vendor estimator or SteamVR and does not
isolate the cause of the scheduling outliers. It is neither a Bionic-versus-glibc
comparison nor proof of native Linux performance. Before accepting the live
integration, measure capture-to-consume age, head-bracket waiting, estimator
call/callback time and pose age together with compositor CPU/GPU timing and
missed vblanks under the same workload. Include sustained CPU/power behavior
and worst-case latency; small ring-operation times alone are insufficient.
Evidence: `output/pico-bionic-performance-20261023-v1/ab-summary.json`, with
source/binary hashes, per-trial logs and the bounded device runner beside it.
The Pico stays in the same offline stock boot with music/system volume zero;
all uploaded benchmark files are removed. No sensor or firmware state changes.

### Parent session lifecycle

The builder also packages [`pico-controller-session.py`](../tools/pico-controller-session.py)
and records its hash. Its `ControllerSession` class coordinates one worker within
an already verified native sensor session. It does not boot the headset, own the
MCU, start head tracking, change audio or install a service.

Construct it with the verified build directory, a new absolute session directory,
current boot UUID, bounded `seconds`, and the verified worker environment. Keep
that object available through cleanup, including when startup raises an error.

1. `start()` verifies the worker against `build.json`, generates a fresh instance
   and starts it with private log files. `session.json` records the process,
   command, instance and binary hash. Regular files avoid blocking the receiver
   on an undrained stdout/stderr pipe.
2. `wait_ready(timeout)` checks the worker's identity and result, then verifies
   channel size, owner, permissions and header. `steamvr_environment()` supplies
   the two controller environment settings to merge into the SteamVR server's
   environment before starting it. Later calls reject a replaced channel inode.
3. `request_stop()` sends SIGTERM. `wait_rpc_stopped(timeout)` waits for the RPC
   close result and buffer-retention acknowledgment. Inspect all three result
   codes; a received acknowledgment does not itself mean every RPC succeeded.
4. Stop and join the other head/camera clients, then stop the shared SLPI owner.
   `finish(timeout)` requires the worker's release acknowledgment and process
   exit. Check its return code before declaring a successful session.

A timeout or failed startup does not kill or restart the worker: it can still
own DSP-visible memory. The caller must complete the shared-sensor shutdown
sequence. The helper deliberately offers no automatic restart or context-manager
cleanup that could terminate a worker while another head client still uses SLPI.
Host fixtures exercise these paths without hardware; live verification is
recorded separately in the [SteamVR test notes](pico-steamvr.md).

### Head history for the controller tracker

[`pico-controller-head`](../src/pico-controller-head.h) owns a bounded history
of 512 raw b1977 head results. Its caller serializes access and supplies the
current generation, monotonic time and measured timestamp uncertainty. It
requires 20 consecutive state-1/confidence-1 results,
matching the stock head-history startup threshold. A tracking loss or excessive
head gap clears readiness; malformed or regressing input stops that generation.

A match copies the last head result wholly before the input's uncertainty
interval and the first wholly after it. Both results must remain fresh and
within the configured gap. Missing brackets refuse the input without changing
the output buffers. There is no extrapolation, identity fallback, image-type
mutation or head-to-eye transform. Stop invalidates the history permanently.

ASan/UBSan host tests and a device-denied Bionic unit harness on the Pico cover
startup, wraparound, duplicates, uncertainty boundaries, tracking-loss recovery,
regressions and stop. A recorded-time check brackets 5,005 of 5,006 retained
controller samples; one awaits a later head result. This is a recording replay,
not evidence of live callback arrival order or a SteamVR controller pose.
Evidence: `output/pico-controller-integration-20261023-v1/`.

The vendor field at `0x44` is preserved without interpretation, as in the head
pose converter. The recording contains consecutive tracked head results with
value `0x200`; treating every nonzero value as a fatal error incorrectly empties
the history. A replay reproduced that refusal, and the regression test retains
the exact status bytes through matching. This field is not a readiness gate.
