# Quest 3 kexec preparation

`probe.c` is a separate read-only interface probe for Eureka's
`5.10.246-gd7102a837402` kernel. It contains no loader, reset, MMIO mapping,
secure call, CPU shutdown or jump code. Its deliberate `-ECANCELED` return
leaves no resident module. Ordinary module loading can still add kernel taint
and log records.

Build with the captured stock configuration, the exact Android Clang 14.0.7
build `8508608`, and a hash-verified stock vmlinux `Module.symvers`:

```sh
python3 -B tools/build-quest-kexec-module.py --module probe \
  --source EXACT_QUEST_SOURCE \
  --config CAPTURED_PROC_CONFIG_GZ \
  --stock-symvers STOCK_MODULE_SYMVERS \
  --stock-symvers-sha256 VERIFIED_SHA256 \
  --toolchain ANDROID_CLANG_R450784E_8508608 \
  --output NEW_BUILD_DIRECTORY
```

The builder uses an existing pinned Linux container without network or device
access. It records source/config/compiler hashes, retains strict CFI and shadow
call stacks, and checks every imported symbol against both the supplied stock
table and freshly compiled source exporters. Only three build-tool capability
normalizations are accepted. The output is not automatically loaded.

The October 20 build passed all 19 import comparisons. Its unchanged binary
passed a diskless VM test using the authenticated stock kernel with synthetic
board-compatible strings, then a physical Quest load. The physical probe
reported EL1, 4 KiB pages, 4,366 DT nodes and the bound DWC3 device. It returned
`-ECANCELED`, left no resident module, and preserved the boot ID, RAM root and
offline updater state. The staged module file was removed.

Module SHA-256:
`865c5c5df2521c7f8c8c897c9ea8f7a190ea3bf231995a483dadf7200a702b64`.
Private evidence lives under `output/quest-kexec-port-20261020-v1/` in
`probe-build-v5`, `probe-vm-v1` and `probe-device-v1`.

The subsequent probe also reports the typed EFI state and the MSM USB parent.
It passed all 20 import comparisons, the stock-kernel VM and the physical Quest
load. EFI flags were zero and runtime services inactive, so the ARM64 EFI reset
branch does not bypass restart handlers in this boot. Both `a600000.ssusb`
(`msm-dwc3`) and its `a600000.dwc3` child (`dwc3`) were bound. Boot identity,
root and offline state were unchanged. This binary is
`a42f68bbce66d70d54bff5eafef775c3686e8270e24705a1ef3793478065c2ee`;
its receipts are `probe-build-v6`, `probe-vm-v2` and `probe-device-v2`.

This validates a limited module interface. RAM staging, the transition,
peripheral handoff, Linux USB access and reset-to-stock remain separate gates
in [the port plan](../../docs/quest-kexec.md).

## Separate no-jump reset rehearsal

The same builder accepts `--module reset-test` for `reset-test.c`. Its default
mode checks the board, release, uid and EFI gate, then returns `-ECANCELED`.
Only the explicit load parameter `execute=1` enables the reset path. The
operator must first verify the matching firmware, offline state, enabled GH
watchdog and runtime `qcom_dload_mode.download_mode=0` on the selected unit.

The reset path registers a typed, command-gated restart handler, sets a
45-second GH watchdog deadline and calls normal `kernel_restart()`. If reached,
the late handler refreshes that deadline and waits without jumping to another
kernel. Stock's pet thread can still run before late entry; this is not a
general shutdown-hang timeout.

Build `reset-test-build-v2` passed all 12 import comparisons and the inert
stock-kernel VM/device tests. Binary SHA-256:
`6326617a149b9536132c4d8aeea6dda447dc4ea700a30957282cdffc24821f29`.
The enabled rehearsal returned to completed stock Android in 66.702 seconds,
with the same build, slot and locked/green state. No late-handler record was
recovered, so the timing is not direct proof of that handler's execution.

The first attempt to restore RAM root failed. An ordinary offline stock reboot
cleared its partial cache changes; after boot settled, the pinned Fugu tool
restored root and `update_engine` was stopped again. The cause of the first
failure is unproved. Receipts are `reset-test-vm-v1`,
`reset-test-device-inert-v1` and `restart-handler-return-v1` under the private
port evidence directory. That rehearsal did not execute a custom kernel.

## RAM ownership test

The builder also accepts `--module memory-test`. The default mode only checks
the board, kernel, credentials and fixture/watchdog topology, then deliberately
returns `-ECANCELED`. `execute=1` allocates up to 64 ordinary 4 MiB buddy blocks
and two additional blocks below 4 GiB. It selects four physically adjacent
owned blocks for the 16 MiB Image region and retains 96 MiB for the target heap,
including the two low DMA blocks. It checks page patterns and releases every
allocation before returning. It never scans or writes unallocated RAM.

The temporary 20-second allocation deadline and 45-second GH fallback require
runtime download mode `0` before physical execution. A clean return restores
the stock 11/14-second bark/bite settings. `fixture=1` omits physical watchdog
calls only on a synthetic `linux,dummy-virt` tree without a GH watchdog node.

The earlier 20 MiB and 16 MiB requests through the default CMA pool failed
cleanly. A scoped CMA trace reported isolation-test failures; those failures
must not be treated as ownership or bypassed by forcing CMA page flags.
The buddy-only implementation passed all 17 stock/source import comparisons,
the diskless stock-kernel VM, and the physical Quest on October 20. It held
112 MiB, passed all 28 block-pattern checks, then released all allocations in
12.109 ms in-kernel. The boot ID, root and offline state stayed unchanged.

Module SHA-256:
`711dfeeb2f77aa5b3a3d445d445ca9e9695d9c5ac2ab0e75136c012f5b76749b`.
Receipts are `memory-test-build-v4`, `memory-test-vm-v4` and
`memory-test-device-v5` under the private port evidence directory.

The image region may be above 4 GiB; the current target Image declares support
for arbitrary physical placement. An actual loader must allocate again, use
the newly returned addresses and keep those allocations alive through handoff.
The successful test freed its pages and reserves no future staging address.

## USB halt and rebind observer

Build with `--module usb-test`. Its default mode validates the bound MSM parent,
DWC3 child and register resource, then returns `-ECANCELED` without MMIO access.
`execute=1` takes runtime-PM references on both devices, maps the existing USB
registers for reads and arms the bounded GH/timer fallback. It leaves both
platform drivers bound and pins the module until a verified rebind.

The read-only `snapshot` parameter reports GCTL, DCTL, DEVTEN and DSTS. It marks
`halted=1` only in device mode with RUN_STOP clear, DEVTEN zero and DEVCTRLHLT
set. After the gadget runs again, writing `1` to `finish` verifies those running
conditions, cancels the deadline, restores stock watchdog timing and permits
normal module removal. No controller register is forcibly written by the test.

On October 20 the binary passed all 31 stock/source import comparisons, its
inert physical load and a reversible physical shutdown/rebind test. A detached
root shell briefly paused the existing USB gadget HAL, unbound only configfs
gadget `g1`, captured five halted samples, rebound the same gadget and resumed
the HAL. Both kernel drivers remained bound. The test completed in 1.755 s,
unloaded the module and retained the same boot ID, rooted adbd PID, firmware
and offline state. No reset or root reacquisition occurred.

Module SHA-256:
`e8f2d3a09299223ca34a11c61c3ca9d5d5121b9c7baa14c7405a8167a7ff957e`.
Private receipts: `usb-test-build-v2`, `usb-test-device-v1` and
`usb-shutdown-device-v1`. This establishes the observed gadget halt/rebind;
the final loader must repeat the register checks after CPU shutdown. It does
not yet establish a custom-kernel USB handoff or stock return from that kernel.

## Returning MMU test

`--module mmu-test` builds `mmu-test.c` with `transition.S`; the builder records
the assembly input hash and verifies its additional stock imports. The default
load is inert. `execute=1` allocates a control page and three identity-table
pages, cleans them to PoC using the exported sanitized cache geometry and runs
the return test on CPU 0 under `stop_machine()`.

The private identity table maps only the owned 4 KiB code page. Its copied
assembly sets the stock MMU-off SCTLR baseline, reports the physical PC and
M/C/I flags, then returns through a BTI landing pad. The wrapper preserves x18,
callee-saved registers and the original translation/interrupt context before
returning to C. The test compares TTBR0, TCR, SCTLR, DAIF and the shadow call
stack pointer, restores stock watchdog timing and frees its pages. It contains
no replacement-kernel jump.

The October 20 binary passed 23 stock/source import comparisons, the exact
stock-kernel VM and the physical Quest. The physical return reported the
expected PC `0x911935018`, zero M/C/I flags and restored context in 29.479 µs.
The same boot ID, RAM root, rooted adbd process and offline state remained;
no module or scratch allocation remained resident.

Module SHA-256:
`60970e88a9a5d20416d293a12930aa6f2fc71857ca5ad20827f6c5683b68f5c9`.
Receipts: `mmu-test-build-v3`, `mmu-test-vm-v2`, `mmu-test-device-v1`.

The returning assembly is adapted from
[YusufOzmen01/quest-kexec](https://github.com/YusufOzmen01/quest-kexec) and
[Mac898 revision 057cb9ec](https://github.com/Mac898/quest-kexec/blob/057cb9ecf76a14d940f808a5b6d0094050a5c05a/module/transition.S).
Cache maintenance follows Linux `arch/arm64/mm/cache.S`. Their GPL-2.0 terms
are retained in source headers and [COPYING](COPYING).

## Resident RAM payload staging

`--module ram-stage` builds a separate module without a kernel jump path. Its
default load is inert; `stage=1` retains the owned 16 MiB Image region and
96 MiB heap using the shared `ram.c` allocator. Root can read the allocation
inventory from `/sys/kernel/reframed_quest_ram/info` and transfer at most
16 MiB through the mode-0600 `payload` file. The interface accepts offsets
within that allocation only. Normal removal removes sysfs and frees every bank.

The shared allocator regression passed 18 stock/source import comparisons,
the stock-kernel VM and the physical Quest. The stager passed 28 comparisons
and a stock-kernel VM test covering initially zeroed memory, a full patterned
16 MiB roundtrip, boundary rejection and module removal.

The physical stager then allocated its banks in 48 ms, received the actual
Image/initramfs/prepared-DTB payload and returned all 16 MiB byte-identically.
The payload SHA-256 was
`3250620436180af7ea95e999eca8444df163dc3030c0103e740b81cb4a794bae`.
It was removed afterward; those addresses are no longer reserved. Root, boot
identity, firmware and offline state stayed unchanged.

Stager module SHA-256:
`d006ac94126cb8c024090d96c31ff43c48fbe650464bdc7320a137ace86a0950`.
Private receipts: `ram-stage-build-v2`, `ram-stage-vm-v1`,
`ram-stage-device-v1`, `memory-test-build-v5`, `memory-test-vm-v5` and
`memory-test-device-v6`.

The host-only [assembler](../../tools/assemble-quest-ram.py) requires a fresh
resident allocation inventory, raw ARM64 Image, native gzip initramfs and the
matching live DTB. It restricts RAM to the owned banks, preserves fixed
reservations, disables dynamic reserved-memory pools, bounds the bounce
buffer, and selects fixed high-speed USB peripheral mode. The Image's full
declared memory extent is zero-padded before the initramfs and DTB. Eight
regression tests cover the physical placement contract, overlaps, payload
bounds and real FDT edits. Assembly/readback does not prove kernel entry,
physical USB enumeration or reset from the new kernel.

## Explicit RAM boot module

`--module boot` builds `boot.c`, shared staging code and the one-way assembly
entry. Its default load remains inert. `stage=1` creates the same bounded
payload interface and additionally takes typed runtime-PM references on the
existing USB parent and child. It does not launch a kernel on module load.
The staging-only module remains a separate build with no jump path.

The root-only `status` file reports the USB halt and launch state. Writing a
hexadecimal DTB offset and full payload SHA-256 to `launch` requires halted
device-mode USB, valid bounded ARM64/FDT headers and a matching hash over all
16 MiB. It seals payload writes and enters normal `kernel_restart()`. The
command-specific late restart handler requires CPU 0 alone online, interrupts
disabled and USB still halted. A refused gate leaves stock reset handlers
available. A successful gate refreshes the 45-second GH deadline, cleans all
owned target banks and control tables to PoC, and enters the Image with the
physical DTB in x0 and x1–x3 zero.

The October 20 build passed 56 stock/source import comparisons. The diskless
stock-kernel VM rejected an incorrect payload hash, passed the late gate,
entered the separate minimal kernel, ran static native ARM64 userspace and
rebooted. The physical Quest passed inert loading, staging/readback, removal
and root/boot preservation; no physical kernel launch is established by those
staging tests. Module SHA-256:
`162778c9d1b77fbbab21c46ae102f21b97e3a57930b8fac631ef8958620d7ee1`.
Private receipts: `boot-build-v3`, `boot-vm-v2` and `boot-device-stage-v1`.

The shared staging-only refactor separately passed `ram-stage-build-v3` and
`ram-stage-vm-v2`, retaining its full payload/bounds/removal regression.

Build the native USB initramfs with
`tools/build-quest-ram-initramfs.py`, supplying a hash-verified static ARM64
BusyBox. Its [init script](../../system/quest/ram-usb-init) mounts only kernel
and RAM filesystems, binds a normal ACM gadget and starts a serial shell. It
requires `reframed.ram_usb=1`, does not pet the inherited watchdog, and requests
a reboot on setup failure or shell exit. The maintained builder reproduces the
previously checked initramfs byte-for-byte. `boot-usb-init-vm-v1` verified this
exact archive's startup and bounded reboot when the VM has no UDC. Physical
enumeration and stock return remain separate acceptance gates.
