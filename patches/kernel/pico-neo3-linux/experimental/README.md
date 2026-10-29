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
- `0019-kgsl-fence-rt-dispatch.patch` depends on `0018`. It optionally routes
  only GPU timestamp fence-signalling callbacks to a private FIFO40
  `kgsl-fence` kernel thread. Other callbacks and final event/context release
  stay on the existing reclaim-capable workqueue. Shared worker policy is
  unchanged. The read-only boot parameter `msm_kgsl_core.fence_rt` defaults to
  `0`; compiling the patch does not enable the route.

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

Build the fence experiment with:

```sh
tools/build-kernel.sh pico-neo3 output/kernel/pico-fence-experiment fence-rt
```

The Python equivalent is the existing Pico Linux-userspace build with
`--pico-fence-rt`. The flag adds `0018` then `0019`, rejects other profiles and
incompatible variants, and includes both patches in the build-cache identity.
It does not add `0017`, change the default profile, enable the boot parameter,
bind CPUs, or boot a device. The first private hardware comparison also included
the separate memory-queue sysfs and HRTICK diagnostics; this generic build flag
does not reproduce that private image byte for byte.

Use the same built kernel for `msm_kgsl_core.fence_rt=0` and `=1` controls.
The experimental route serializes fence callbacks on one thread; this can
introduce head-of-line delay and does not remove interrupt or higher-priority
interference. Submission closes before worker flush/stop, and cleanup work is
drained afterwards. Extracted lifecycle tests do not establish unload,
suspend, memory-pressure or long-duration runtime safety.

`tools/pico-kgsl-fence-affinity.py` requires caller-supplied serial and kernel
notes pins, verifies the exact PID/start time and FIFO40 policy, and restores
only the owned task's affinity. The control arm makes no affinity writes.
`tools/pico-kgsl-fence-capture.py` uses the same split cleanup/removal lifecycle
as the phase collector. `tools/pico-kgsl-fence-dispatch.py` separately qualifies
complete sparse records, capture provenance, and contained windows. A literal
`<...>` command name is the vendor ftrace command-cache miss representation;
acceptance still requires matching PID and independent stable task guards.
Contradictory known names or changed task start times fail qualification.

The sparse event records queue/start/done elapsed time for the private route.
Its boundaries differ from workqueue queue/execute events: never synthesize
workqueue generations for it. Completed sparse rows cannot independently count
unfinished callbacks across every context. The first matched-image experiment
showed lower dispatch tails, with presentation misses still present. Keep the
route experimental and default-off; one short comparison does not establish a
pacing fix, observer neutrality or physical controller tracking.
