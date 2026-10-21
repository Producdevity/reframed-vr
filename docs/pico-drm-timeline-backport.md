# Pico DRM timeline-syncobj backport

Research baseline: repository `40b277a2e25dfea6219153b47032f3f529a39c7d`,
2026-10-21. The target is ByteDance Neo3 Linux 4.19.81,
[`9cacc1c1356dd32a048f4cb13bc84af402bd3326`](https://github.com/bytedance/neo3-kernel/tree/9cacc1c1356dd32a048f4cb13bc84af402bd3326),
pinned by `profiles/kernel/pico-neo3.json`. The local patch series and its
verification boundaries are recorded below.

## Selected approach

The backport adds the DRM-core timeline interface while retaining the vendor
submission, camera and DSP drivers. Its core reference is Linux **v5.4.302**, commit
[`9e3157c56ec7917e6a80ea53a8bd752e0037f2cb`](https://github.com/gregkh/linux/commit/9e3157c56ec7917e6a80ea53a8bd752e0037f2cb),
as the core source reference, plus the narrowly selected fence-unwrapping and
transfer corrections below. This is an engineering choice for its older,
compatible interfaces and accumulated fixes, not a claim that 5.4.302 alone
implements every later transfer correction.

The immediate need is an exportable **timeline OPAQUE_FD semaphore**. Session
evidence is in
`output/pico-steamvr-session-20261021-v2/renderer-resource-analysis.json` and
`renderer-2710.asm.txt`; the fatal Mesa message is in that session's
`error-log-export/steamvr/pico-steamvr-compositor-v5.log`. Mesa 26.1.8 selects
semaphore implementations by timeline and external-handle capabilities, and
its DRM provider enables timeline operations after `DRM_CAP_SYNCOBJ_TIMELINE`.
The existing local `0003-kgsl-drm-syncobj.patch` already converts nonzero points
through `SYNCOBJ_TRANSFER` and binary sync files. Thus the missing kernel core
is a concrete candidate to remove this creation failure; subsequent renderer
and presentation behavior still requires measurement. Sources: cached
`output/downloads/mesa-26.1.8.tar.xz`, `src/vulkan/runtime/vk_semaphore.c`,
`vk_drm_syncobj.c`, `src/util/u_sync_provider.c`, and the local patch.

## Smallest upstream dependency groups

The usable implementation first shipped in Linux 5.2. The earlier timeline
attempt was [reverted by `131280a162e7`](https://github.com/torvalds/linux/commit/131280a162e7fc2a539bb939efd28dd0b964c62c).
Do not revive that earlier ABI.

| Group | Exact upstream commits and required effect |
| --- | --- |
| Fence prerequisites | [`078dec3326e2`](https://github.com/torvalds/linux/commit/078dec3326e2244c62e8a8d970ba24359e3464be): shared signaled stub; [`b312d8ca3a7c`](https://github.com/torvalds/linux/commit/b312d8ca3a7cebe19941d969a51f2b7f899b81e2): `u64` fence sequence numbers and affected formatting/signatures; [`5e498abf1485`](https://github.com/torvalds/linux/commit/5e498abf14858945f1249d9cc4ff1e8715a307e3): explicit `dma_fence_ops.use_64bit_seqno` and comparator semantics. |
| Syncobj prerequisites | [`86bbd89d5da6`](https://github.com/torvalds/linux/commit/86bbd89d5da66fe760049ad3f04adc407ec0c4d6): use stub helper; [`61a98b1b9a8c`](https://github.com/torvalds/linux/commit/61a98b1b9a8c7a21a2d666a090dcf5f1c70c659f): replace old callback implementation; [`649fdce23cdf`](https://github.com/torvalds/linux/commit/649fdce23cdf516e69aa8c18f4b44c62127f0e83): lookup flags. |
| Timeline container | [`7bf60c52e093`](https://github.com/torvalds/linux/commit/7bf60c52e093d9309752dbc3569fa213a80fb815): `dma_fence_chain`, its header and Makefile object. |
| Core timeline operations | [`44f8a1396e83`](https://github.com/torvalds/linux/commit/44f8a1396e83f1030eaf18591b3f106235118a64): add point; [`01d6c3578379`](https://github.com/torvalds/linux/commit/01d6c357837918d8186b9f520e167d98e3d560cc): timeline wait; [`27b575a9aa2f`](https://github.com/torvalds/linux/commit/27b575a9aa2ff0358c5f4410a14f6413d5c792e4): completed-value query; [`bc9c80fe01a2`](https://github.com/torvalds/linux/commit/bc9c80fe01a2570a2fd78abbc492b377b5fda068): lookup point; [`ea569910cbab`](https://github.com/torvalds/linux/commit/ea569910cbab980abb42daa603ad4e8f5f9deaaa): binary/timeline transfer; [`50d1ebef79ef`](https://github.com/torvalds/linux/commit/50d1ebef79ef6d09f4fb91f0b424e4f87db1d8a8): CPU timeline signal. |
| Capability gating | [`060cebb20cdb`](https://github.com/torvalds/linux/commit/060cebb20cdbcd3185d593e7194fa7a738201817): timeline capability and separate driver opt-in. |

Treat this as a dependency map, not a blind cherry-pick list. The vendor archive
still has a 32-bit `dma_fence.seqno`, no `dma_fence_get_stub()`, the old
`drm_syncobj_cb`, and three-argument `drm_syncobj_find_fence()`. Importing the
v5.4.302 implementation directly absorbs the syncobj prerequisite changes.
Keep ordinary KGSL fences on 32-bit wrap-aware comparisons; only chain fences
set `use_64bit_seqno`. See the vendor
[`dma-fence.h`](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/include/linux/dma-fence.h)
and upstream comparator commit above.

## Exact source surface and ABI

Use these files at v5.4.302; transplant relevant declarations and cases into
existing headers rather than replacing broad vendor headers:

- `drivers/gpu/drm/drm_syncobj.c`, `include/drm/drm_syncobj.h`.
- `drivers/dma-buf/dma-fence-chain.c`, `include/linux/dma-fence-chain.h`, and
  `drivers/dma-buf/Makefile`.
- Selected stub/64-bit changes in `drivers/dma-buf/dma-fence.c`,
  `include/linux/dma-fence.h`, `drivers/dma-buf/sync_file.c`,
  `drivers/dma-buf/sw_sync.c`; audit trace and driver formatting of `seqno`.
- Syncobj ioctl prototypes in `drivers/gpu/drm/drm_internal.h`, ioctl table and
  capability case in `drm_ioctl.c`, driver feature in `include/drm/drm_drv.h`,
  UAPI in `include/uapi/drm/drm.h` and its tools copy where maintained.
  [Pinned core source](https://github.com/gregkh/linux/blob/v5.4.302/drivers/gpu/drm/drm_syncobj.c),
  [chain source](https://github.com/gregkh/linux/blob/v5.4.302/drivers/dma-buf/dma-fence-chain.c),
  [UAPI](https://github.com/gregkh/linux/blob/v5.4.302/include/uapi/drm/drm.h).

Required UAPI: cap `0x14`; `TIMELINE_WAIT` `0xCA`, `QUERY` `0xCB`, `TRANSFER`
`0xCC`, `TIMELINE_SIGNAL` `0xCD`; the upstream fixed-width argument structs;
`WAIT_ALL` bit 0, `WAIT_FOR_SUBMIT` bit 1, `WAIT_AVAILABLE` bit 2. Retain the
old opaque syncobj FD import/export ABI and binary operations. Point zero in
`TRANSFER` selects the binary/current-fence form. Modern direct timeline-point
sync-file import/export, eventfd and deadline extensions are unnecessary for
the inspected Mesa bridge. Its counter query supplies flags zero, so the later
[`2093dea3def9` last-submitted query extension](https://github.com/torvalds/linux/commit/2093dea3def9d5bf3000697ae3b0ec36c43354e0)
is not required by that path. Its separate fence-reference cleanup is required,
as described below.

The vendor driver-feature bit layout differs from upstream: `0x80000` already
means `DRIVER_PREFER_XBGR_30BPP`; use its free `0x100000` for the local timeline
feature definition, consistently throughout the build. Never copy upstream's
enum numeric value into the old header. Extend the SDE driver opt-in in
`techpack/display/msm/msm_drv.c` only once core support is present. This exposes
CPU/fence-sharing operations; KGSL submission remains connected through the
existing Mesa bridge. The archive's remaining old lookup callers are
`amdgpu_cs.c`, `v3d_gem.c` and `vc4_gem.c`; preserve binary behavior with point
zero and flags zero if those configurations are compiled. No external old
syncobj callback callers were found in the pinned archive.

## Correctness fixes to retain

v5.4.302 already incorporates these fixes; retain their behavior when adapting:

- [`92cb3e598063`](https://github.com/torvalds/linux/commit/92cb3e5980638a37c56091e605aa837d0af05a9d): iterative chain release avoids recursive stack exhaustion.
- [`b33b556ce59b`](https://github.com/torvalds/linux/commit/b33b556ce59b5239a7b73c495209f90ec990e60c): query traversal releases fence references correctly.
- [`a37eef63bc9e`](https://github.com/torvalds/linux/commit/a37eef63bc9e16e06361b539e528058146af80ab): retain syncobj reference throughout wait-for-submit.
- [`b19926d4f3a6`](https://github.com/torvalds/linux/commit/b19926d4f3a660a8b76e5d989ffd1168e619a5c4): completed, garbage-collected points resolve to a signaled stub rather than successful NULL lookup.
- [`101c9f637efa`](https://github.com/torvalds/linux/commit/101c9f637efa1655f55876644d4439e552267527) and [`3c43177ffb54`](https://github.com/torvalds/linux/commit/3c43177ffb54ea5be97505eb8e2690e99ac96bc9): `WAIT_AVAILABLE` accepts a future point and registers a wakeup, returning on submission instead of sleeping until timeout.

**Additional query correction:** v5.4.302 still leaks the owning reference from
`drm_syncobj_fence_get()` on every nonempty query, independently of the iterator
references fixed by `b33b556ce59b`. Select the `dma_fence_put(fence)` immediately
before `copy_to_user()` from
[`2093dea3def9`](https://github.com/torvalds/linux/commit/2093dea3def9d5bf3000697ae3b0ec36c43354e0).
That one-statement correction covers chain and binary fences, including failed
copy-back, without enabling the last-submitted query extension. A scoped manual
ownership pass over the chosen core's creation, FD import/export, point lookup,
wait entries, signal and transfer cleanup found no further obvious unreleased
owning references; this is static inspection, not a leak-test result.

**Additional transfer import:** v5.4.302 lacks the
[`721255b52700` chain-flattening correction](https://github.com/torvalds/linux/commit/721255b52700b320c4ae2e23d57f7d9ad1db50b9).
Prefer its general successor
[`ec8d985ff26f`](https://github.com/torvalds/linux/commit/ec8d985ff26f29d53d9ebff04973e96572fd0285),
with [`f4e3a12bf2d1`](https://github.com/torvalds/linux/commit/f4e3a12bf2d1983b8f352b7719794c52be7e0990)
to report `-ENOMEM` correctly. A small compatible source selection is:

1. Add `dma_fence_array_first/next` and declarations from
   [`caaf2ae712b7`](https://github.com/torvalds/linux/commit/caaf2ae712b7cc3c7717898fe267dbf882a502ef),
   the empty-array guard from [`c42ee39c1e78`](https://github.com/torvalds/linux/commit/c42ee39c1e78224d3a81bdbe0600abe4581226ed),
   and NULL-safe conversion behavior from [`976b6d97c623`](https://github.com/torvalds/linux/commit/976b6d97c62347df3e686f60a5f455bb8ed6ea23).
   The latter does not require importing the whole subclass refactor.
2. Add `dma_fence_chain_contained` from
   [`18f5fad275ef`](https://github.com/torvalds/linux/commit/18f5fad275efef015226ee4f90eae34d8f44aa5e).
   Keep existing zeroed allocation or import the small allocation helpers from
   [`440d0f12b52a`](https://github.com/torvalds/linux/commit/440d0f12b52a920f4c78376b3ce7039ba59244c5).
3. Import `drivers/dma-buf/dma-fence-unwrap.c`, its header and build object as
   settled at [`4fa05a67b558`](https://github.com/torvalds/linux/commit/4fa05a67b558d2cb3acd2bb299b91220d405ca5e).
   Its development dependencies are [`64a8f92fd783`](https://github.com/torvalds/linux/commit/64a8f92fd783e750cdb81af75942dcd53bbf61bd),
   [`01357a5a45ed`](https://github.com/torvalds/linux/commit/01357a5a45ed8eb9543183f5c9c6713ae60fc1f3),
   [`245a4a7b531c`](https://github.com/torvalds/linux/commit/245a4a7b531cffb41233a716497c25b06835cf4b)
   and the iterator-filter revert in `4fa05a67b558`. Do not copy their unrelated
   sync-file merger rewrite merely to enable syncobj transfer.
4. Apply [`949291c53140`](https://github.com/torvalds/linux/commit/949291c5314009b4f6e252391edbb40fdd5d5414):
   release every owned fence reference if output-array allocation fails.
   This small correction applies without newer timestamp/private-stub APIs.
   Also select [`18226ba52159`](https://github.com/torvalds/linux/commit/18226ba52159257d4c2f777a168cc09adb3c1ac0)
   to reject unsupported lookup/transfer flags.

The existing Neo3 DMA-buffer patch deliberately preserves OR arrays. Retain
`dma_fence_merge_all()` unchanged. For the imported iterator, the planned local
compatibility adaptation is to return the OR-array head from `array_first()`
and NULL from `array_next()` when `signal_on_any` is set, preserving that array
as one dependency. This differs from upstream's unconditional child traversal
and requires an unsignaled OR-array transfer regression alongside the AND case.

Preserve upstream SPDX/copyright notices and attribute the selected commits.
The main implementation authors include Christian König, Chunming Zhou and
Jason Ekstrand; retain later fix attribution as recorded in those commits.

## Validation gates

1. Compile the patched physical configuration and a separately marked Neo3
   QEMU configuration. Rebuild affected modules: changing `dma_fence` and its
   ops changes internal kernel ABI. Do not mix old modules with the new Image.
   Compile with warnings visible; test 32-bit fence wrap separately from 64-bit
   timeline values, including values above `UINT32_MAX` and `2^63`.
2. Extend the existing diskless kernel test pattern with a QEMU-only DRM node
   advertising both syncobj features. The current Neo3 QEMU fragment supplies
   software fences/debugfs but does not itself create a usable SDE device.
   The separate `qemu-abi/0001-virtio-cpu-syncobj.patch` targets a 5.10 virtual
   driver and is only a pattern, not evidence for this 4.19 backport. A test
   node plus `sw_sync` can exercise real core ioctls without GPU submission.
3. Require binary regression tests; opaque FD sharing across `exec`; CPU
   signal/query/wait; future-point waits and prompt `WAIT_AVAILABLE` wakeup;
   zero/past/high points; wait-any/all; timeout/interruption; handle destruction
   while a waiter retains the object; completed-point transfer; repeated
   binary↔timeline and timeline→timeline transfers; AND-array dependencies;
   long unsignaled-chain teardown; allocation-failure cleanup and descriptor
   recovery. Fail on kernel warnings, leaks or premature completion. General
   flattening must retain all dependencies and not replace OR-array semantics
   with an AND of its children. The local iterator must return an OR array
   as one opaque fence and stop iteration after it, matching the existing
   DMA-buffer backport; the new transfer path must preserve that difference.
4. Run `tests/vulkan-external-sync.c` in all four existing modes, not only
   `--binary-only`: timeline/binary × exportable/import-only receiver. It checks
   a 4 MiB buffer round trip across `exec` and timeline counter 9. Extend with
   high values and deliberate wait-before-signal ordering; a small standalone
   creation probe should exactly reproduce Valve's timeline + OPAQUE_FD chain.
5. Only after QEMU acceptance, validate the matching kernel/modules on Pico:
   capability query, the standalone semaphore probe, cross-process KGSL
   completion, then the native Valve compositor at the established display
   mode. Record startup, actual frames/page flips, kernel warnings and session
   shutdown separately from live tracking. QEMU/software-fence success does
   not prove KGSL completion, SDE presentation, SteamVR rendering, or headset
   stability.

Concurrency, reference ownership, global fence-layout changes and vendor module
compatibility are the principal regression risks. The backport is bounded in
source area but crosses shared synchronization code; the completed display and
tracking gates do not remove the need to validate those paths together.

## Local implementation and verification

`patches/kernel/pico-neo3-linux/0011` through `0014` contain the fence
prerequisites, stable core, transfer unwrapping and query-reference correction.
The core keeps the vendor `drmP.h`/slab declarations and expresses the newer
lockdep diagnostic through the existing `lockdep_depth()` API. Unsupported
lookup flags are rejected before acquiring the syncobj reference.

The canonical physical configuration builds successfully with all 38 matching
modules under `output/kernel/pico-neo3/linux-timeline-20261021-v1/`. The new
initramfs and native root use those modules; the RAM container preserves the
previously tested display DTB bundle, command line and stock OS-version fields.
These are offline assembly results, not a headset boot result.

`tools/test-drm-syncobj.py` builds a signed test module for a compiled Pico
QEMU variant. The module refuses any board other than `linux,dummy-virt`,
creates a software-only DRM node, and leaves the kernel's module-signature
enforcement enabled. It does not submit virtual or physical GPU work. The
guest exercises the actual core ioctls, software fences and reference counts,
then unloads the fixture and powers off without a disk or network interface.

The negative baseline under
`output/pico-drm-timeline-20261021-v1/vm-query-baseline-v5/` reproduces the
query leak: 512 queries plus eight failed copy-backs increase the retained
fence's reference count from 2 to 522. Future-point wakeups, pending/completed
transfers, opaque-FD sharing between processes, high counters, 1,024 descriptor
cleanup cycles, OR/AND unwrapping, 32-bit wrapping and 8,192-node chain teardown
also pass. Reference counts inspect the actual retained fence; descriptor
counts alone would not expose the query leak.

The corrected canonical QEMU kernel under
`output/kernel/pico-neo3/qemu-timeline-20261021-v5/` passes the same suite in
`output/pico-drm-timeline-20261021-v1/vm-final-v1/`. Query references remain
2 to 2 through the same 520 operations; every other listed case and clean
fixture unload/power-off passes, without kernel warnings. Full GPU interprocess
synchronization, Valve compositor presentation and physical lens acceptance
remain separate hardware gates.
