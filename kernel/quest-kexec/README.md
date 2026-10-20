# Quest 3 kexec preparation

`probe.c` is a separate read-only interface probe for Eureka's
`5.10.246-gd7102a837402` kernel. It contains no loader, reset, MMIO mapping,
secure call, CPU shutdown or jump code. Its deliberate `-ECANCELED` return
leaves no resident module. Ordinary module loading can still add kernel taint
and log records.

Build with the captured stock configuration, the exact Android Clang 14.0.7
build `8508608`, and a hash-verified stock vmlinux `Module.symvers`:

```sh
python3 -B tools/build-quest-kexec-probe.py \
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

This validates a limited module interface. RAM staging, the transition,
peripheral handoff, Linux USB access and reset-to-stock remain separate gates
in [the port plan](../../docs/quest-kexec.md).
