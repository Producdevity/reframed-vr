# DMA-buffer synchronization

Mesa's display WSI imports rendering-completion sync files into DMA buffers
before presenting them. The Quest 5.10.246 vendor source lacks the standard
`DMA_BUF_IOCTL_IMPORT_SYNC_FILE` and `DMA_BUF_IOCTL_EXPORT_SYNC_FILE` ioctls.
Its SDE driver imports DMA buffers and waits on their exclusive reservation
fences in `msm_atomic_prepare_fb()` and `complete_commit()`.

`patches/kernel/linux-userspace/0002-dma-buf-sync-file.patch` backports the
[Linux 6.0 ioctl ABI](https://github.com/torvalds/linux/blob/v6.0/include/uapi/linux/dma-buf.h)
and [ioctl handling](https://github.com/torvalds/linux/blob/v6.0/drivers/dma-buf/dma-buf.c)
to the Quest vendor reservation API. The kernel builder selects it for the
Quest Linux userspace configurations; Neo3 uses a separate patch set.

The October 18 Neo3 `linux-native-panel-20261018-v2` kernel (Image SHA-256
`fa99caa82c272832013354abb14bd4677ac26515ed9c5ddc1417a26eed97e583`)
does not contain this backport. Its build receipt selects
`patches/kernel/pico-neo3-linux/0001` through `0008`, and its corresponding
cached source has neither ioctl definitions nor handlers. The separate Neo3
4.19 port and its QEMU results are described below. The Quest results do not
establish Neo3 support, and the older Neo3 artifact remains unchanged.

Read exports wait on writers; write exports wait on readers and writers.
Imported writers preserve earlier independent writers, while readers remain
separate shared dependencies. The patch uses the vendor tree's existing fence
unwrapping implementation to keep merged fences flat. The ordinary driver
submission API, `dma_resv_add_excl_fence()`, retains its existing behavior.

The older core assumed shared fences already depended on the exclusive writer.
Independent imports require correcting that assumption in DMA-buffer polling,
`dma_resv_test_signaled_rcu()` and `dma_resv_wait_timeout_rcu()`. A completed
reader must not hide a pending writer, and completing a writer must not skip a
pending reader. Validation and allocation failures leave the reservation
unchanged; failed export copy-back releases its descriptor.

## Diskless tests

```sh
python3 -B tools/test-dma-buf-sync.py QEMU_KERNEL --output NEW_TEST_DIRECTORY
```

The runner requires a checksummed QEMU transport kernel with built-in software
fences, debugfs and udmabuf. It compiles the fixture in the kernel build's
immutable ARM64 compiler image, then boots QEMU without disks, networking or
hardware passthrough. The fixture additionally checks the QEMU device tree and
an explicit test command-line flag before exercising the API.

The suite covers ABI and descriptor flags, empty reservations, invalid requests,
export copy-back failures, independent writers, separate read/write dependencies,
combined polling, immutable snapshots, cross-process descriptor transfer, 1,024
imports, descriptor exhaustion and recovery. Every normal case requires clean
power-off and rejects test failures or kernel warnings in the boot log.

`--expect-unsupported` verifies that an unpatched baseline rejects both ioctls.
`--reservation-module` additionally loads `dma_buf_resv_test.ko` when its hash is
recorded in that kernel's build artifacts. Its source is in
`tests/kernel-dma-buf/`; it exercises the real reservation query and wait helpers
with kernel software fences, including a writer signaled during a wait while a
reader stays pending. The module refuses non-QEMU device trees.

## Recorded results and limits

`output/dma-buf-sync-baseline-v1/` confirms both ioctls are absent in
`output/kernel/quest3/qemu-abi-v7/`. The first backport passed its initial ioctl
suite, but the added polling regression reproduced premature readiness in
`output/dma-buf-sync-poll-regression-v1/`. Those artifacts and the earlier patch
are preserved.

`output/dma-buf-sync-v2/` passes the corrected ioctl suite, polling regression and
both reservation tests using `output/kernel/quest3/qemu-dmabuf-v3/`. It performs
1,024 imports without file-descriptor growth and powers off cleanly. These are
real kernel DMA-buffer/software-fence results, with no GPU or panel execution.
The physical configuration also compiles as
`output/kernel/quest3/physical-dmabuf-v3/` with the same corrected source patch;
that kernel has not run on a headset.

The incremental build uses private copy-on-write source/build layers over the
existing kernel cache mounted read-only. Build records contain the baseline,
patch, complete source-tree identity, compiler commands and output hashes.
Those incremental test directories retain their recorded overlay-cache
requirement. Complete exports are now available at
`output/kernel/quest3/linux-build-v10/` and `qemu-abi-v10/`; packaging their
Image, 272 modules and 14 device trees no longer requires access to the cache.
Compiling additional external test modules still requires the original matching
source/build layers; older runners that infer a plain cache path from
`olddefconfig` commands do not consume these export records.

The exports read both original and incremental caches through read-only mounts.
Module installation and stripping run in RAM, with checksummed output copied to
the host only after verifying its size and remaining headroom. Source identity,
Image, configuration and cached module hashes are checked around the export.
The full new SDE module differs from the older bundle; the other 271 module
hashes and all device trees match. Export logs and provenance remain in each
build directory. The v8 missing-Python-path and v9 insufficient-RAM failures are
preserved; v10 completes successfully.

Matching startup artifacts are `output/headset-initramfs-quest-v4/` and
`headset-initramfs-quest-qemu-v6/`. The new QEMU package passes actual module load
and QRTR/QMI readiness in `output/quest-startup-dmabuf-v1/`, with modeled peripheral
state and clean power-off. This does not repeat or replace the earlier DMA-buffer
ioctl tests, whose kernel Image is identical. The existing v3 full roots remain
unchanged and still need the new kernels/modules and graphics/runtime bundles.

This API closes one synchronization prerequisite. KGSL execution, SDE buffer
import and scanout, physical panel timing, tracking, thermal behavior and the
exact-device boot/recovery gates remain unverified. These results do not
establish installation or flash readiness.

## Exported memfd mapping lifetime

October 8 diagnosis isolates another vendor-kernel issue. A native ARM64 process
exports an 8 KiB memfd through udmabuf, maps it, closes the source descriptor and
then unmaps it. On the old QEMU kernel, closing the source produces `Bad page
cache` warnings for that exact memfd inode and taints the kernel. Unmapping before
closing the source succeeds. The reproducer runs without Steam, FEX or a GPU.
Ordinary memfd and System V shared-memory lifecycle tests also pass separately.

`patches/kernel/qemu-abi/0002-udmabuf-pfn-mapping.patch` backports
[upstream Linux's PFN mapping fix](https://github.com/torvalds/linux/commit/7d79cd784470395539bda91bf0b3505ff5b2ab6d)
to the vendor 5.10 API. It applies only to the QEMU transport variant, where
udmabuf is enabled. The existing physical KGSL/SDE path remains a separate test
requirement.

The maintained diskless test now performs 256 two-page mapping/fault/fork cycles,
covering source-close order, faults after descriptor close, shared child writes,
unmapping, descriptor cleanup and kernel taint. The runner verifies either the
builder's `resolved.config` artifact or older `.config` exports.

`output/kernel-udmabuf-20261008-v1/` passes these cycles and the full existing
synchronization suite, including 1,024 imports and descriptor exhaustion, with
clean power-off and no kernel warning. Its complete maintained kernel build is
`output/kernel/quest3/qemu-udmabuf-v1/`, Image SHA-256
`1d9f5c180b247aa63b16f15080aeb1c4660775907daa95d91147a722a5e29911`.
This closes the isolated udmabuf regression. It does not establish the cause of
Steam's independent renderer restarts or prove physical rendering.

## Neo3 4.19 port

`patches/kernel/pico-neo3-linux/0003-dma-buf-sync-file.patch` implements the
same ioctl ABI using 4.19's `reservation_object` and WW-mutex APIs. Independent
writers retain preceding writers and readers. The reservation wait, query and
poll paths account for both kinds of dependency. Ordinary ordered driver
submissions retain their existing reservation behavior.

This tree lacks the newer fence-unwrapping helper. The port instead flattens
AND arrays iteratively, merges ordered fences from the same context, and keeps
OR arrays as intact dependencies. Fence arrays record their immutable
`signal_on_any` setting so merging cannot turn an OR dependency into an AND.
The reservation update retains 4.19's preemption guard around its seqcount.

The QEMU variant has a separate test-only memfd exporter, adapted to the 4.19
DMA operations and mapping APIs. Its PFN mapping preserves the source-close
lifetime fix above. The physical variant includes neither this exporter nor
the virtual-board patches. QEMU has no Qualcomm secure firmware: its config
disables early Qualcomm entropy and QHEE memory-protection calls, and its QTEE
initcall declines the virtual board. The test command additionally skips
`socinfo_init`, `remoteqdss_init` and `hwinfo_init`, whose hardware is absent.
These omissions do not apply to a physical boot.

For Neo3, the runner prepares QEMU's generated two-CPU device tree with
`tools/prepare-pico-qemu-board.py`. Modern QEMU adds a socket wrapper that the
vendor topology parser cannot understand. Preparation removes that wrapper,
checks both CPU references, and verifies that every property outside the CPU
map is unchanged. It refuses physical board identities and inconsistent maps.
The host needs `fdtget` and `fdtput` from the device-tree compiler tools. An
explicit virtual board can instead be supplied with `--dtb`.

```sh
python3 -B tools/test-dma-buf-sync.py PICO_QEMU_KERNEL \
  --reservation-module --output NEW_TEST_DIRECTORY
```

`output/pico-recovery-bringup-20261018-v1/dma-buf-qemu-test-v10/` passes the
complete ioctl suite, 256 mapped-buffer lifetime cases, reservation wait/query
tests, OR-array preservation and a single flat aggregate of 1,024 independent
fences. The guest powers off cleanly without kernel warnings. The signed test
module loads only after the mapping tests; its expected out-of-tree module
taint is distinct from a kernel warning. The runner records the virtual board,
firmware exclusions, source identities and input hashes.

The compiled test kernel is
`output/kernel/pico-neo3/qemu-dmabuf-20261019-v6/`. Its incremental build uses
private source/build layers over the read-only, fully compiled v2 baseline;
records retain the baseline, source changes, configuration differences and
matching signed test-module inputs. It exports a test kernel and that module,
not a physical firmware or vendor-module bundle. The physical build and its
headset results are recorded separately below.

Host ASan/UBSan checks of the actual merge function also pass 8,192 AND/OR
truth-table cases, allocation-failure cleanup, sequence wrap, duplicate fences,
empty dependencies and 1,024-import ownership checks. Those use modeled fence
objects; the QEMU results above exercise the real kernel implementation.
Neither result proves KGSL execution, SDE buffer import, presentation, optical
quality, stereoscopic VR or persistent Linux installation.

## Neo3 physical presentation

On October 19, `output/kernel/pico-neo3/linux-dmabuf-20261019-v1/` and its
38 matching modules booted the native Linux RAM root on the inventoried Pro Eye.
Its Image SHA-256 is
`684f09b7d33ba3f042741028ea67a4c74071023d1fd82dde5badc8fd0c719529`.
The physical build retains the Qualcomm entropy and secure-firmware configuration;
it contains neither the QEMU exporter nor the virtual-board adaptations.

With the matched Turnip driver, a direct Vulkan test clears the actual display
swapchain images on the GPU, verifies a pixel readback from each image, and waits
for present-ID completion. Twelve RGB frames produce eleven changes of the
active DRM plane framebuffer, with successful DRM vblank checks. A second run
without an application delay completes 64 frames and 63 framebuffer changes;
the mean completion interval after the initial interval is 8.328 ms, about
120 Hz. This is a simple clear/readback test, not compositor or game performance.
No CPU copy supplies the full presentation image.

Both DSI video engines remain enabled with zero ACK error status. The matching
signed read-only driver snapshot records a stable 1920-pixel DSC PPS width.
The complete current DTBO carrier readback also matches its retained hash.
Headless GPU readback and binary semaphore/buffer IPC controls pass on the same
boot. The receipts are `dmabuf-v1-physical-presentation-verification.json` and
`dmabuf-v1-physical-cadence-verification.json` under
`output/pico-recovery-bringup-20261018-v1/`.

These results establish the native KGSL-to-SDE presentation path on this unit.
The owner has not inspected lens output after the PPS correction; clean optical
output, calibrated stereo, tracking accuracy and persistent Linux installation
remain separate acceptance checks.
