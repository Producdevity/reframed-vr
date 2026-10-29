# Pico kernel experiments

These patches are excluded from the default kernel profile. Keep their source,
configuration, build, runtime identity and restoration evidence with each test.
A successful build alone does not establish a performance improvement.

- `0017-kgsl-maintenance-workqueue-sysfs.patch` exposes the memory-entry queue's
  existing attributes. The implicitly ordered devfreq queue is unchanged.
- `0018-kgsl-delayed-callback-phases.patch` adds a disabled-by-default diagnostic
  event. It preserves the existing fire marker, FIFO40 promotion, callback,
  restoration and resource-release order. Input/result source hashes are in
  its header. Apply only to those inputs, with zero fuzz.

The phase event records six monotonic samples and emits once after restoration.
Elapsed intervals include interrupts, preemption and instrumentation; they are
not exclusive CPU time or display-latch measurements. The disabled branch skips
new clock/scheduler samples, but the extra branch and changed machine layout
still require controls on the same candidate kernel.

`trace_kgsl_event_phases_enabled()` follows probe registration. Off arms require
the event disabled in every instance; `tracing_on=0` alone does not disable the
sampling path. Keep the sparse phase stream separate from the original CPU/DRM
streams and qualify each complete recording independently.

The native helper is `tools/pico-kgsl-phase-capture.py`. Its caller supplies the
bounded reader factory and must join **all** trace readers before calling
`remove(all_readers_joined=True)`. In this vendor kernel, instances share the
`nop` tracer's reader reference count. `cleanup()` only stops the owned reader
and disables events; it does not remove an instance while another reader lives.

`tools/pico-kgsl-phases.py TRACE [--output NEW_FILE]` checks whole-file structure.
Its CLI deliberately reports `capture_accepted=false`. Runtime/source/format,
loss, read-count, cleanup and identity checks belong to its separate capture
gate; exact callback-generation association is another gate. Never repair a
failed row or qualify a rejected recording from a selected prefix. See
[the verification record](../../../../docs/pico-steamvr-verification.md) for
hardware results and limits.

The retained Neo3 formatter rounds nanoseconds to the nearest microsecond.
An unchanged printed timestamp therefore represents `[printed-500, printed+499]`
nanoseconds. Preserve this interval when joining printed events to exact phase
samples; treating the timestamp as truncated rejects valid boundary matches.
