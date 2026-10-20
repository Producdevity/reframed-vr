# Quest 3 RAM-only Linux boot

The first target is a native Linux USB shell followed by a verified return to
the unchanged stock Quest firmware. Steam Frame's ARM64 userspace is the
subsequent OS base, as recorded in the [base-system decision](steam-frame.md).
No Quest 3 kernel handoff or return from a custom kernel has passed yet.

## Current verified inputs

On October 20 the development Quest 3 still reports build
`52433670036000520`, kernel `5.10.246-gd7102a837402`, slot A and locked/green
Verified Boot. It had rebooted since the preceding snapshot; the pinned
[Fuguquest source](https://github.com/Henry1887/fuguquest/tree/2324ce262e674504ad41ec82abcda3bf09dd01e6)
restored uid 0, kernel SELinux context and Permissive mode. Root is temporary.
The offline source, rebuilt tool, target and stock carriers are retained with
hashes under `output/quest-kexec-port-20261020-v1/recovery/`.

Wi-Fi is off and the observed routing tables are empty. `update_engine` was
stopped after root restoration. Android rejects disabling the protected updater
package; this is not a persistent update block. Keep the Quest offline and
recheck the updater after every return to stock. Do not switch to slot B: its
earlier bootloader query reported it unbootable.

The live device tree, memory resources, exact running configuration and USB
inventory are captured privately. The configuration enables full Clang LTO,
strict CFI, shadow call stacks and module versioning. The retained Android
Clang 14.0.7 build `8508608` matches `/proc/version`. Static extraction of the
authenticated stock kernel's export table agrees with 19,710 matching-module
import records and all 280 independently source-generated export CRCs. This
establishes expected symbol versions, not every structure layout or physical
module-load compatibility.

## Loader port boundaries

The source reference is
[Mac898's mainline-support revision](https://github.com/Mac898/quest-kexec/tree/057cb9ecf76a14d940f808a5b6d0094050a5c05a),
derived from [YusufOzmen01's Quest-KeXec](https://github.com/YusufOzmen01/quest-kexec).
Retain attribution and the upstream license when adapting code. Its porting
requirements include CPU/GIC state, SMMU ownership, power-controller adoption,
USB/PHY handoff, safe RAM staging and reset recovery.

The source cannot run unchanged on Eureka/Anorak:

- The 4.19 SCM, task-affinity, IOMMU and DWC3 interfaces differ from Meta's 5.10
  source. The old ION helper also lacks its required headers.
- The returning trampoline overwrites x18 without restoring it. Quest 3 uses
  that register for the shadow call stack; fix returning paths before rehearsals.
- AOP/QMP structure layouts and topology differ. The core-hang registers also
  differ; do not reuse the Quest Pro MMIO addresses or private-structure casts.
- USB's device-tree IOMMU stream ID is `0x40`. Shared SMMU register geometry
  does not establish compatible stream ownership or a safe bypass.
- Upstream `execute=0` still permits hardware-changing diagnostics. The first
  module must be a separately built probe with no jump, reset, CPU-offline,
  secure-call or device-register write paths.

The detailed source audit and exact pins are in the private
`output/quest-kexec-port-20261020-v1/` evidence directory.

## Read-only module acceptance

The [separate probe](../kernel/quest-kexec/README.md) now passes exact-compiler
build checks, all 19 stock/source import-version comparisons, an isolated test
on the authenticated stock kernel and a physical load on the development Quest.
It reports EL1 and the bound DWC3 resource, returns deliberately without a
resident module, and preserves the boot ID, root and offline updater state.
This does not exercise relocation, shutdown or a kernel transition.

A follow-up read-only probe passed 20 import comparisons, the stock-kernel VM
and a physical load after the watchdog calibration. It reported no active EFI
runtime services and identified both the bound MSM USB parent and DWC3 child.
The stock ARM64 restart path can therefore reach the restart-handler chain in
this boot. Device shutdown alone still does not run these drivers' remove
callbacks; their coherent teardown needs separate validation.

The fresh tree uses `qcom,gh-watchdog`; the bound driver is `gh-watchdog`.
Its controls are on `hypervisor:qcom,gh-watchdog`, rather than the empty
`/sys/class/watchdog`. The current command line enables minidump-to-eMMC and
`qcom_dload_mode.download_mode=1`. A watchdog bite bypasses the normal clean
reboot path, so a source-level watchdog recipe alone cannot promise a return
to stock. Download-mode control, a bounded timeout and the actual reset outcome
must be checked before relying on that path for an unattended kernel jump.

## Stock watchdog return calibration

On October 20 the runtime download-mode parameter was set to `0`, its Linux
readback was checked, and no new SCM/download error was reported. Triggering
the stock Gunyah watchdog through its existing `apps_wd_trigger` file returned
automatically to completed stock Android in 38.791 seconds. The build, slot A
and locked/green state were unchanged; the boot ID changed, uid returned to
2000 and SELinux to Enforcing. Wi-Fi stayed off, with empty routing tables.
The pinned offline Fugu tool restored RAM root, and `update_engine` was stopped
again. No physical handling, EDL, flash, erase or factory reset was used.

The private receipt is `watchdog-return-v1/result.json` beneath the port evidence
directory. This proves the reset outcome while stock Android owns the hardware.
It does not yet prove a preserved watchdog deadline, successful USB shell or
stock return after our loader changes CPU/peripheral state. Recheck and clear
download mode before each such test; the stock boot configuration enables it.

## Minimal USB target kernel

The separate `ram-usb` configuration now compiles from the pinned Meta source:

```sh
bash tools/build-kernel.sh quest3 output/kernel/quest3/ram-usb-build ram-usb
```

This seeds `allnoconfig` rather than the full vendor configuration. It retains
strict CFI and shadow call stacks, includes the USB gadget and required
clock/regulator/IOMMU providers, and excludes block support, system suspend,
CPU hotplug and the watchdog driver. The first target must not pet the inherited
watchdog deadline. Its configuration does not establish safe inherited hardware
state or complete device-tree preparation.

Three narrow source fixes give disabled WALT stubs internal linkage, guard
sleep-only USB callbacks and preserve the function body needed by the MSM
connection-done kretprobe. The existing ARM64 unwind-layout fix is also applied.
The initial VM run caught that missing functional USB hook; the corrected build
registers all hooks without the earlier error.

The October 20 clean build passed configuration resolution and Image layout
validation: all 21 allocated ELF sections fit its 13,893,632-byte declared
memory extent. Image SHA-256:
`a318f9cd69a4551851c0b1f78a29ce26c4eaa8304632bb61b36f54010abc7d22`.
A diskless VM using a synthetic board tree reached native static ARM64
userspace, created ACM and ECM configfs functions, and rebooted. This proves
neither physical USB enumeration nor a Quest kexec transition. Private receipts
are `usb-target-build-v2` and `usb-target-vm-v2` under the port evidence directory.

## Acceptance sequence

The separate [RAM ownership test](../kernel/quest-kexec/README.md#ram-ownership-test)
now passes on the physical Quest. It uses ordinary buddy allocations rather
than forcing the busy default CMA pool: four adjacent owned 4 MiB blocks form
the Image region, with 96 MiB of separate heap RAM including two low DMA banks.
All patterns and cleanup passed without losing RAM root or changing the boot.
These allocations were released; their reported addresses are not reserved.

A separate [USB observer](../kernel/quest-kexec/README.md#usb-halt-and-rebind-observer)
also passed the physical configfs gadget shutdown/rebind check. Five register
samples confirmed device-mode hardware halt with event interrupts disabled;
both platform drivers stayed bound. Rebinding, module cleanup and watchdog
restoration passed without rebooting or restarting rooted adbd. The remaining
transition still needs the returning MMU test and a final USB halt check after
CPU shutdown.

A separate [no-jump reset module](../kernel/quest-kexec/README.md) passed its
default inert tests and an enabled stock-return rehearsal. Completed stock
Android returned in 66.702 seconds with unchanged firmware and boot state.
The late-handler log was not recovered, so its execution remains unproved.
RAM root required a clean stock reboot and a second Fugu attempt after the
first restoration failed. This narrows reset preparation without establishing
a custom-kernel handoff or guaranteed one-attempt root recovery.

1. Preserve and independently hash-check the stock boot inputs and unit data;
   retain offline re-root assets and the known stock button/USB entry procedure.
2. Build against the captured configuration and exact compiler. Verify module
   imports, CFI/SCS instrumentation and deliberate return without a resident
   module before adding any shutdown or jump code.
3. Establish safe staging allocations and preserve firmware-owned memory from
   both the live device tree and allocator/resource state. A System RAM label
   alone does not reserve an address range for our loader.
4. Port platform shutdown/adoption and a bounded recovery path. Prove a minimal
   RAM initramfs, USB shell access and return to the same stock build/slot.
   Do not mount or modify headset block devices in the first target.
5. Integrate the adapted Frame userspace and headset-specific graphics/tracking
   providers, then validate Steam/SteamVR and the Reframed update mechanism.

The owner's 9008 cable is a physical fallback asset. It does not establish Quest
EDL programmer authorization or an unattended recovery path. Do not make a
kernel experiment depend on an unverified EDL restoration procedure.
