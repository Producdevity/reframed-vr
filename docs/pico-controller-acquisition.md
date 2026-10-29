# Controller SDK input recordings

The version-3 writer in `src/pico-controller-acquisition.c` records a serialized
prefix of SDK calls. It borrows two new output streams, writes little-endian
records and stops both streams at a capacity, reset, explicit stop or error.
The owner assigns the fresh estimator epoch before recording starts and stops
recording before resetting that estimator. It calls `finish`, inspects status,
then closes the files. Recording errors do not imply a tracking error.

Both files begin with four unsigned 64-bit words: magic, version, record size
and record capacity. Motion magic is `0x52564354494d0001`; image magic is
`0x5256435443410002`. Version 3 allows at most 16,384 motion records and 150 image
sets. The paired files must use the same version and a single nonzero estimator
generation. Captured pixels, calibration and unit identities stay in ignored
evidence directories.

The motion record is 840 bytes:

| Offset | Field |
| ---: | --- |
| 0 | Capture timestamp, unsigned 64-bit nanoseconds, within signed 64-bit range |
| 8 | Estimator generation, unsigned 64-bit |
| 16 | Shared SDK dispatch order, unsigned 64-bit, starting at one |
| 24 | Hand, unsigned 32-bit: 1 left, 2 right |
| 28 | Reserved unsigned 32-bit, zero |
| 32 | Nine finite binary64 SDK IMU values |
| 104 | Tracked head result immediately before the capture, 368 bytes |
| 472 | Tracked head result immediately after the capture, 368 bytes |

Capture timestamps increase per hand. Equal or interleaved timestamps between
hands are permitted; replay uses recorded dispatch order. The analyzer never
sorts SDK calls by capture time or assigns the missing hand in a legacy record.

The image record retains the 1,229,816-byte layout: the same first three 64-bit
words, two head results at offset 24, then four camera metadata/pixel pairs
starting at offset 760. Each metadata block is 64 bytes, followed by 640×480
RAW8 pixels. The camera index is 0–3, width/height 640/480, format `0x123`, type
zero, exposure 1–4095, gain 1–255, positive SOF at least the shared capture time,
a common frame number and pixel size 307,200. The writer serializes metadata
explicitly; it does not serialize process pointers or compiler padding.

`tools/analyze-pico-controller-acquisition.py` validates bounds, complete records,
per-hand ordering, contiguous cross-stream dispatch order, one generation,
finite IMU values, tracked head brackets and the four-camera metadata. It
rehashes both inputs after reading. Its report includes hand counts and byte
offsets for replay. This validates the retained input subset; it does not prove
SDK acquisition, optical pose validity, full live-input coverage or reproduced
wall timing.

Version 2 remains readable: its 832-byte motion record has no hand field,
values at offset 24 and head results at offset 96. Its motion capacity is at
most 4,096. Version-2 image records have the same size as version 3. Mixing
versions is rejected. Existing image-geometry analysis can read either image
version through the shared record validator.

### Native recorder check (2026-10-29)

`output/pico-acquisition-v3-20261029-v1/` validates the deployed writer with
1,583 left-hand motion records and 78 four-camera sets. Both files retain
estimator generation 104 and contiguous shared dispatch order 1–1,661. The
writer reports no errors and stops both streams at its duration limit. The
6.5-second bound includes post-initialization readiness waiting; the retained
input span is shorter. Right-hand radio is outside this control, although both
SDK estimators are calibrated. Mixed-hand ordering is covered by fixtures.

The full native workload completes 4,499 head-camera sets and 184,610 head
callbacks with zero bad results. All three CPU windows and 300,587 DRM rows
qualify. Observer-free flip-sequence skips are 1 / 0 / 2; steady API timing is
unmeasured. Optical controller publication remains disabled. Input-recording
writes and diagnostic captures preclude a clean performance comparison.

All 494 exported data files rehash, as do both complete input streams. The
63,010,848-byte archive has SHA-256
`fa8b57131b049a32fed88bf3500f54ae28b3124e377a2b98def61fa910f1c62e`.
Full BOOT/DTBO readbacks, trace/FIFO/DSP cleanup, muted offline stock return and
owned USB-host termination verify. `acceptance.json` and the complete analyses
remain beside the ignored evidence.

The scheduler-context collector used in this run performs one raw read and
retains only the 762-byte `sched_debug` header. Its reported completeness flag
is invalid for effective CFS-group analysis. Per-task getters remain observations;
they do not supply the missing group hierarchy. The corrected reader must read
through EOF, enforce its byte bound, and validate every online CPU section and
selected task/group before accepting scheduler context. Thirty-three offline
fixtures include the actual short-read regression, overflow and missing-context
cases; native validation of that correction is separate from this recording.
