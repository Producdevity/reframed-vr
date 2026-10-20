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
