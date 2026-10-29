# Pico fence dispatch

The opt-in `0019-kgsl-fence-rt-dispatch.patch` routes only
`kgsl_sync_fence_event_cb` onto a private FIFO40 kernel worker. Previously, the
callback received FIFO40 only after a shared CFS worker had started executing
it. Memory callbacks and final context/event cleanup retain the original
reclaim-capable workqueue. The boot parameter `msm_kgsl_core.fence_rt` defaults
to zero and is read-only after boot.

The [experimental build instructions](../patches/kernel/pico-neo3-linux/experimental/README.md)
describe the explicit `fence-rt` variant. This is a tested corrective candidate,
not the default kernel profile or a completed frame-pacing fix.

## Native comparison, 2026-10-30

Both arms use identical kernel bits and payload bytes, differing in the boot
parameter and the guarded private worker's CPU binding. The existing callback
CPU mask is 0–3 in both arms. The enabled arm restores its original worker mask
after the test; the disabled arm makes no task-affinity writes. Each runs the
180-second camera, head-tracking, controller and SteamVR workload. API probing
is disabled in the three steady windows; startup probing is a separate check.

| Window | Control WQ queue → execution p99 / max, µs | Private queue → wrapper p99 / max, µs | Control missed / contained presents | Private missed / contained presents |
| --- | --- | --- | --- | --- |
| 0 | 369 / 1,511 | 211 / 588 | 1 / 1,793 | 0 / 1,795 |
| 1 | 488 / 2,207 | 212 / 504 | 1 / 1,794 | 2 / 1,793 |
| 2 | 480 / 3,576 | 210 / 703 | 2 / 1,793 | 0 / 1,797 |

These dispatch boundaries differ: the private queue mark precedes actual
insertion, while the control uses workqueue tracepoints. Report each route's
measurements separately. Neither interval is exclusive CPU time. The results
support further testing of the private route; two versus four presentation
misses in one short comparison do not prove a sustained pacing improvement.

Whole DRM streams qualify independently: 298,689 control rows and 298,974
enabled rows. All three control CPU/workqueue populations qualify. The enabled
sparse streams contain 2,294 / 2,294 / 2,330 complete records, including
1,796 / 1,794 / 1,798 contained display-context callbacks. They are never joined
as workqueue generations; the candidate's workqueue cleanup is not callback
execution. Completed sparse records alone cannot prove that every submitted
callback across every context completed.

The enabled middle-window misses remain open. One kickoff occurs 71 µs before
the software vblank trace but presents on the following vblank. In the other,
the fence wait returns 1.405 ms after that trace. These are software boundaries,
not physical panel-latch measurements. The private worker does not eliminate
interrupt interference, late GPU completion or late upstream submission.

## Evidence and qualification

The compiled kernel's 41 retained headset/audio/WLAN/Bluetooth module imports
and embedded signing trust were checked before boot. Complete archive/source,
reader closure/loss, worker identity/policy/affinity, restoration, BOOT/DTBO
readback, muted offline stock return and owned USB-host closure checks pass.

| Arm | Native boot UUID | Evidence archive SHA-256 |
| --- | --- | --- |
| Control | `70f33a26-012b-49bf-911f-fb81efa7b28a` | `45e3e43171bfb0a27e4daa4fee11bffcfc67a8e9f64ee070d1afccbedb878746` |
| Private worker | `49266d8c-cd31-48ef-97b0-65ebeae53359` | `ecbce9c09896b66390a719b4e80d77633d1169132023c79f66d6f279e4ad0d17` |

Raw evidence is in `output/pico-kgsl-fence-rt-native-20261029-{control,on}/`.
Accepted analysis is in
`output/pico-kgsl-fence-rt-analysis-20261030-v1/{control-corrected,on-corrected}/`.
The earlier rejected receipt is retained: one raw row uses `<...>`, the pinned
vendor ftrace command-cache miss representation. The parser now permits that
missing name only with the exact independently guarded PID and stable start
time. Known contradictory names still fail. No raw row was removed or changed.

The first enabled preflight also remains recorded. It stopped before reboot
because the byte-identical payload already occupied the control's staging
filename. The retry used a separate hash-verified staging path; kernel and
payload bytes were unchanged.

Long-duration operation, memory pressure, suspend/unload, steady API timing and
physical motion/lens checks remain necessary. Optical controller acquisition
and pointing are still unverified; connected radio input and successful head
tracking do not establish controller 6DoF. Keep these boundaries separate from
the [overall VR acceptance checklist](pico-vr-acceptance.md).
