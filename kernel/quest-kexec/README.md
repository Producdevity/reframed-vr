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
port evidence directory. No custom kernel has executed.

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
