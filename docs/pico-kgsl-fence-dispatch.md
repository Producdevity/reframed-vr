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

Exact timeline/sequence matching associates those misses with private ctx1
timestamps 7491 and 8622. Their dispatch envelopes are only 35.625 and
35.313 µs. The latter event is already queued 1.340 ms after software vblank;
its userspace queue also follows the previous present's wait end by 4.700 ms,
versus an on-time median of 0.997 ms and p99 of 1.745 ms in the same window.
The other callback completes 273 µs before vblank. Neither miss justifies
another private-worker priority or affinity change.

The enabled middle CPU recording fails its original whole-epoch scheduler
validation on one invalid priority. It remains rejected; no selected GPU or
scheduler rows were salvaged. Accepted DRM/WSI and sparse data locate lateness
relative to the private worker, but do not identify the upstream blocking owner
or split GPU execution from retirement observation. Identity matching also
does not prove exclusive signal origin: this kernel has an inline
already-retired timeline path. The detailed follow-up is
`output/pico-kgsl-fence-misses-20261030-v1/`.

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

## Follow-up signal timing

`output/pico-kgsl-fence-signal-native-20261030-v1/` adds an independent sparse
`dma_fence_signaled` stream to the same enabled kernel and workload. Compiled
source puts this marker after the first successful signalled-bit transition
and timestamp assignment, before wake-callback traversal. It is not the exact
transition instant or GPU completion time. All source/whole-stream, eight-CPU
loss/read, worker, restoration and stock/host closure gates pass. The workload
completes in 180.953 seconds with 4,499 camera sets and zero bad head results.

All five measured misses have a unique full driver/timeline/context/sequence
identity and signal in task context inside the exact guarded RT callback.
This resolves signal attribution for this new run, without retroactively
identifying actors in earlier recordings. The three windows miss 2 / 1 / 2
presentations, totaling 5 / 5,379. Added instrumentation has observer cost;
this is not a controlled pacing-regression or neutrality result.

Two frames have upstream previous-wait-to-queue gaps of 8.428 and 8.099 ms;
their events reach the RT queue 4.856 and 4.258 ms after software vblank and
dispatch in about 30 µs. Another frame's 634 µs dispatch envelope includes
approximately 478 µs after the recorded selecting switch. That switch precedes
the actual context switch and worker loop, so this is not a proved priority
failure. A different callback has approximately 479 µs between its fire marker
and signal. Phase tracing is disabled, and IRQ/preemption, promotion helpers,
timeline locking and observer work are not separated. The CPU recordings pass,
but their scheduler filters omit the RT task; they cannot establish its complete
intervening state. No new scheduling-policy change is justified.

The whole DRM stream has 298,929 valid rows. Its terminal row opens fence 14945
without a captured end at 303.980000 seconds, after all measured windows end
at 260.261409 seconds. The inherited zero-unmatched-waits check rejected this;
that rejection is retained. Measured associations explicitly exclude only this
terminal out-of-window open wait, with all raw rows still validated. No claim
that every workload fence completed follows.

There is also a real post-workload SteamVR shutdown failure. The harness's
nonblocking stop request returns zero, then the server log reports disconnected
cross-thread pipe fatal assertions and its service-stop audit reports failure.
The final process exit code/signal was not exported. This remains a session
cleanup issue; it is not declared harmless or attributed to KGSL.

Boot UUID is `7c971203-e37b-4573-aae8-afe87be05191`; the 570-data-member archive
SHA-256 is `7c21e6e36954e4904b58e83da0fec59b4a13006fb4064a3e5e5ef1fa848ce87d`.
Qualified identities, rounding bounds, source proofs, original rejection and
shutdown logs are indexed by
`output/pico-kgsl-fence-signal-analysis-20261030-v1/result.json`.

### Upstream shared-memory waits (2026-10-30)

Further analysis of that same accepted recording narrows the two 8 ms gaps.
Present 5447 spends 7.162 ms in a successful shared futex wait; present 9398
spends 7.043 ms. Wakeup-to-select time is only 8 and 4 microseconds respectively.
These are render-thread sleep intervals before GPU submission, not fence-worker
dispatch delays.

Both addresses map to the retained Valve SteamVR shared-memory inode. The
independently qualified 35,379-record syscall/register capture yields unique
same-task/address/expected-word/timeout/CPU candidates within 2 microseconds of
the ftrace entries (actual timestamp differences +704 and −542 ns). Their
low-29-bit expected owners match the observed waking threads: Steam's
`CVRAPIITask::Ru` and a vrserver IPC thread. Nearby task snapshots retain stable
process/thread start identities. This supports robust-mutex owner attribution;
it does not establish a named pose lock.

The second saved LR selects the pinned vrclient robust-lock call at ELF
`0x241dbc`. The first returns into the pinned compositor at `0x16f658`, immediately
after its NR98/op0 syscall call. Neither result justifies changing the mutex
protocol or promoting all server threads to real time. The next capture selects
the actual server tasks rather than relying on incidental scheduler rows.

Whole-capture checks, exact joins, disassembly and input hashes are retained in
`output/pico-upstream-delay-analysis-20261030-v1/result.json`. This is a narrower
diagnosis, not a verified frame-pacing fix.

The API owner is selected on all CPUs in the qualified scheduler recording. It
switches out runnable at 197.980050 s and next runs at 197.987745 s: 7.695 ms
descheduled while holding the observed mutex. It wakes the renderer about
27 microseconds after resuming. Its recorded policy is CFS/nice −20. This
establishes runnable descheduling, without identifying a particular fairness
defect or excluding voluntary rescheduling. The server owner's complete run
state remains unqualified. Exact rows and selector/identity checks are in
`output/pico-upstream-delay-analysis-20261030-v1/owner-state.json`.

The optional `tools/pico-steamvr-ipc-priority.py --realtime` experiment assigns
only the selected Steam API worker RR1 with reset-on-fork, below the renderer's
RR2. It requires RTPRIO 0 and both RTTIME limits of 100,000 microseconds; other
UI threads retain their policy. Default operation remains CFS/nice −20 and
neither mode is installed as session policy.

`output/pico-ipc-rr1-native-20261030-v1/policy-acceptance.json` verifies the exact
helper source, a 20-second RR1 window, unchanged identity/affinity/limits, and
restoration to the original policy and nice value. Its 345-data-member archive
SHA-256 is `9f33620c24e13880a9aab895fbe7319ded4dc5ae4ce40d06592be30fb0a93cd4`.
The planned final CFS control failed a harness guard before restoration; the
context subsequently restored correctly. The repeat instead failed to join
trace readers during its first CFS control, before reaching RR1. Neither run
qualifies a performance comparison, so no frame-pacing improvement or default
policy change follows. The first run verifies firmware readbacks, muted offline
stock return and host join. The repeat reached stock through the fallback timer;
stock identity, offline state and mute were checked afterward, but its final
firmware readbacks, evidence export and orderly host join were not completed.

### Completed CFS/RR1/CFS diagnostic (2026-10-30)

`output/pico-ipc-rr1-native-20261030-v4/` completes the 180-second native workload
and three 20-second windows using the same kernel, driver and renderer policy.
Sparse fence-dispatch and fence-signal observers are omitted equally in all
three windows; DRM and CPU/IPC tracing remain active. All five complete CPU
epochs qualify, with zero malformed records and no loss-counter rejection.
Whole-DRM grammar, semantic bounds, hashes and loss checks also pass.

| API worker policy | Contained presentation pairs | Missed presentations |
| --- | ---: | ---: |
| CFS, nice −20 | 1,792 | 2 |
| RR1, nice −20 | 1,795 | 0 |
| CFS, nice −20 | 1,801 | 1 |

The same API thread retains its process/thread identity and affinity throughout;
each context restores its original CFS/nice 0 state. RR1 retains RTPRIO 0 and
100,000-microsecond RTTIME limits. This is one short sequential diagnostic and
does not establish sustained improvement or observer neutrality. No default
policy is changed.

The earlier 7 ms API-owner stall is absent in all three windows. At the sampled
Valve IPC mappings, complete shared-futex waits whose expected word identifies
the API worker have maxima of 349, 4 and 3 microseconds. The middle and final
groups contain only `-EAGAIN` returns; they do not establish equivalent lock
contention. A server-owner-word wait reaches 1.880 ms in the first control.
These rounded ftrace timings are not new per-wait owner/callsite proofs. The
comparison therefore does not verify that RR1 fixes the previously observed
stall. Exact classifications and return codes are in `analysis/waits.json`.

The workload finishes 4,499 head-camera sets with zero bad results and both
controllers connected, but publishes zero optical controller poses. Firmware
readbacks, DSP/MCU release and muted offline stock return verify. The exporter
initially expected raw files for the deliberately omitted observers; a corrected
export explicitly marks both unmeasured and retains the CPU/DRM data unchanged.
All 578 data members rehash; archive SHA-256 is
`5b317a89ea3dd683117f5b29f55e7e9fa5db00fad6c8e755d998021f5eb1f74b`
(56,806,605 bytes), boot UUID `6fe6c7b7-5bdc-46bb-9059-b3b1688da5df`.
The owned USB helper's exit is independently observed; an orderly host-wrapper
join is not claimed. Physical display-boundary analysis is not accepted by this
run. The scoped verification and its source adapters are retained in `analysis/`.
