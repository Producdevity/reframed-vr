# Pico first boot

The inventoried Neo3 Pro Eye now boots a full native Linux root with systemd
PID 1 and an authorized USB root console, and returns to stock without physical
handling. Native GPU execution, initial panel modesets and the native Steam
welcome UI work; desktop integration and tracking bring-up remain ahead. This is not yet an
installation procedure. The intended installation replaces Android; stock
Android is temporarily retained for recovery and staging.

## October 18 device status

The owner-authorized session completed normal-cable software EDL, engineering
ABL/devinfo installation, fastboot token authorization, ordinary and critical
unlock, and a consented factory reset. The retained post-reset report records
build `smartcm.1696861506` (5.8.4.0 b1977), orange Verified Boot,
`ro.boot.flash.locked=0`, `test-keys` and Permissive SELinux. Unlock is persistent;
the owner reports offline setup and updater re-disabling were completed.
Evidence and original/readback manifests are in
`output/pico-edl-reads-20261018-v1/`. These are saved session results, not a new
device check performed for this documentation update.

The engineering ABL readback matches the earlier preserved-tail candidate, and
a pre-unlock `misc` original is now available. The unlock transition and wipe
are completed steps. They do not need to be repeated for a Linux boot test.
The subsequent bring-up session established stock RAM boot, a complete stock
boot restoration/readback, autonomous stock return, and unsigned custom-kernel
startup. The owner also entered fastboot with Power + Volume Down + headset
Home under the engineering ABL. `pico-boot-v4` remains a later runtime with a
separate external root. See the
[updated roadmap](bootloader-unlock-roadmap.md).

Fresh evidence is in `output/pico-recovery-bringup-20261018-v1/`. Only the boot
partition was restored: all 96 MiB read back with stock SHA-256
`bf42eb997b58a335ae4c59c034dd3b0adfc83855c7f5f5887635f0a468b533b7`.
No early boot firmware, GPT or device-state partition was changed by that
restoration. The corrected diagnostic RAM images in `diagnostic-board-v2-boot`
and `diagnostic-board-v3-boot` exposed `Reframed VR Pico diagnostic`, serial
`c980c8d4`, on the physical USB bus and subsequently returned to boot-completed
stock Android. This proves custom kernel/init execution through the guarded
USB bind. After the owner approved the accessory on macOS, the same v3 image
transferred its complete 74,891-byte report and returned to boot-completed
stock Android. The log identifies the custom 4.19.81-perf kernel and explicit
DTB index 3 / DTBO index 0. See `diagnostic-usb-approved-verification.json` and
`diagnostic-approved-v1-live.log` for hashes and observations. Earlier attempts
were unregistered/unconfigured under **Ask for new accessories**; approval
resolved that observed transport gate.

A bounded read of 114 live stock device-tree properties additionally confirms
`androidboot.dtb_idx=3`, `androidboot.dtbo_idx=0`, and the command-line Sharp
493 panel override. The acquired primary-display, Sharp-panel, VXR7200 and
GPIO-controller properties agree with the prepared display tree except for
its three intended binding edits. Kernel-synthesized `name` properties were
checked separately. See `live-display-binding-verification.json` in the same
evidence directory. This verifies selection and property correspondence;
that comparison alone does not verify scanout. A subsequent native boot read
all five VXR7200 control pins as input-low. Patch `0025-native-panel-mux.patch` now
checks every pin before initializing input-low pins as output-low; it refuses
high or unknown states and retains the strict output-low power-on check.
The rebuilt native kernel subsequently owns all five pins as outputs and
registers the intended DSI panel. Optical output was not inspected at that stage.

The file-backed `live-root-v5` assembly subsequently reached the full Linux
root: `systemd-detect-virt` returned `none`, the root console ran as UID 0,
nine matching audio/DSP modules loaded, and QRTR/PD-mapper services were active.
The verified ext4 image was mounted through read-only SquashFS and F2FS backing
with a writable RAM overlay. This staging arrangement still uses a file on
the old userdata filesystem; it is not the final Linux storage installation.
See `live-root-v5-reconnect.log`, `userdata-root-install-v2.json` and
`live-root-v5-stock-return-final.json` for physical observations and the
independent payload readback. The owner confirmed that Android user data does
not need preserving; firmware, calibration and recovery originals remain required.

The first native logs expose a separate panel parsing failure: the stock Sharp
GPIO panel omits the optional DCS backlight subtype. The public driver installs
its default but returns the stale lookup error when the enable GPIO is valid.
Patch `0048-panel-backlight-defaults.patch` returns success on that completed
path while preserving PWM and GPIO probe-defer errors. Source-matched sanitizer
tests reproduce the original failure and pass with the patch. Compilation and
these tests do not establish physical panel operation.

The matching `live-root-v7` image subsequently booted from a hash-verified
USB-delivered RAM payload. Its full kernel and root receipts are separate from
the earlier `pico-boot-v4` assembly. The installed display DTBO passed an
independent complete 24 MiB readback, and stock recovery still booted with that
DTBO. The live tree confirms the expected panel/mux phandles. See
`dtbo-native-display-readback-verification.json` and
`native-dtbo-stock-return-verification.json`.

Native Turnip on the Adreno 650 passes sixteen GPU buffer fills and complete
4 MiB host readbacks. The KMS test also completes its initial modeset, five
vblanks, output disable and a subsequent enable/disable cycle when it uses the
inherited 120 Hz mode. The vendor driver refuses a different refresh rate on
the first continuous-splash frame; requesting 72 Hz first caused DMS errors
and subsequent PLL failures. Those failed attempts are retained in
`native-v7-kernel-after-kms.log`; they do not prove a standalone PLL defect.
The corrected test and physical log are `tests/pico-kms-smoke.c` and
`live-root-v7-first-mode.log`. Vblank events do not establish optical quality,
stereo mapping, or a usable Steam UI.

The subsequent Xorg test exposed two generic modesetting-driver incompatibilities:
an unexposed vendor property had no atom table, and mode conversion dropped the
kernel-supplied refresh field. The source-matched patches and build recipe are
documented in [Pico Xorg compatibility](../patches/xorg/README.md). With both
patches, Xorg and Openbox stayed active and the kernel accepted the 120 Hz mode.
The native ARM64 Steam client and web helper then rendered the gamepad welcome
screen; the owner-approved screen capture is `pico-steam-desktop.png`,
bound by `native-steam-first-ui-verification.json` in the same evidence directory.
This test uses CPU rendering and captures the raw portrait desktop. It establishes
neither correct physical panel output, calibrated stereo output nor native desktop GPU acceleration. No Wi-Fi
interface is registered in this boot, and Android has not yet been replaced on
persistent storage.

The subsequent `live-root-v8` RAM boot confirms this distinction. Xorg's captured
Steam welcome screen is correct, but the owner reports grey output through the
lenses. A direct KMS checkerboard and slow solid-colour test produce visible
noise, corroborated by `owner-panel-noise-20261018.jpg`. The active linear XR24
framebuffer reads back as uniform red and then green at all 400 sampled positions
per capture. The failure is therefore beyond those producer pixels; its exact
display/DSC/link cause remains unresolved. See `owner-panel-noise-verification.json`
and `live-root-v8-native.log`. Successful modesets, vblanks and screen captures
must not be reported as a usable physical graphical session.

The owner subsequently confirmed that the stock Android interface looks clean.
Separate native request-selection and lane-selector experiments changed their
intended controller bits but did not remove the visible noise. Combined link,
EOT and spread-spectrum clock experiments have no owner-confirmed optical result.
The stock/native comparison covers 300 compression registers, which match, and
84 routing registers, whose differences are the expected 72/120 Hz periods.
Those register checks do not inspect the panel's generated DSC parameter packet.

A bounded, read-only diagnostic module built and signed for the running kernel
then snapshots that packet under the display and panel locks. After Xorg enables
the display, the current mode has 960 pixels per controller and two controllers,
but the generated PPS describes a **3840-pixel-wide** picture. The encoder and
stock E6 panel parameters use 1920 pixels. See `native-pps-width-mismatch-v1.json`
and `dsi-pps-snapshot-v2/` in the evidence directory. This is a driver-buffer
snapshot, not an electrical capture of the transmitted packet.

Patch `0051-dsi-idempotent-pps-picture-width.patch` derives the full PPS width from
the current per-controller mode instead of multiplying retained mode state.
Tests of the extracted driver function reproduce the original 3840/7680 width
growth and keep the patched width at 1920 across repeated enables. They also
cover the splash/FPS guards, backend errors and single-controller case under
ASan/UBSan. See `pps-width-regression-v1/result.json`.

The corrected kernel (`8667da5440b600ba1535f88ea434133bfaa6f6af5a82b04682e67954402c5f40`)
and its 38 matching modules subsequently boot in the native RAM root. Driver
snapshots keep the PPS width at 1920 after the full KMS color-test cycle, Xorg/
Steam startup, and stopping/recreating the graphical session. The three packets
are identical and differ from the original captured packet only in the two width
bytes. Xorg, Openbox and Steam are active after the final cycle. See
`pps-width-v1-first-packet-verification.json`,
`pps-width-v1-xorg-packet-verification.json` and
`pps-width-v1-restart-packet-verification.json`. The owner was away during those
tests, so clean physical output, stereo and optical calibration were unverified.
This packet fix does not establish a usable physical graphical session by itself.

The SSC isolation test also installs a narrowly changed DTBO carrier with
SHA-256 `a784b74fc998e91b3080068ab1c00c40543e5670584d80ae1ed7c3baffb69c2b`.
A fresh full readback first verified the retained previous carrier; the new
24 MiB carrier then passed independent full readback. Its two removed overlay
SSC-enable properties leave the installed stock boot's merged tree identical,
because the stock base already supplies those properties. The native RAM base
removes them too, and both live PLLs report SSC disabled. The unchanged installed
stock boot subsequently reaches boot-complete with both display engines active,
Wi-Fi off and the updater disabled. See `ssc-off-v1/report.json`,
`dtbo-after-ssc-independent-verification.json` and
`ssc-neutral-dtbo-stock-return-verification.json`. Optical output after this
change has not been inspected; the original and previous DTBO carriers remain
retained for recovery.

Binary DRM synchronization and GPU semaphore/buffer sharing across processes do
pass on this boot, separately from panel output. See
[Turnip's physical binary-sync evidence](turnip.md) and
`native-v8-binary-sync-verification.json`. That older kernel lacks the Neo3
DMA-buffer fence ioctls; the subsequent build below supplies them.

## October 19 owner-visible direct display retest

The owner subsequently inspected the native direct KMS colour test with the
PPS-width correction included. The same static/banding/grid remained at both
120 Hz and 72 Hz. Neither Monado nor SteamVR participates in this test. Lowering
the refresh rate after the required 120 Hz splash handoff therefore does not
remove the corruption; the PPS-width fix is also insufficient to establish clean
panel output.

The bounded test completes the inherited 120 Hz handoff, disables and re-enables
that mode, then switches to 72 Hz. Both controllers remain active with zero
reported ACK and timeout errors. At 72 Hz, 22 selected controller registers match
the retained stock reference; the reported byte/pixel clocks differ slightly.
The 7,200 sampled producer pixels match the requested solid colours, which does
not establish correct downstream fetch, compression, link transmission or panel
decoding. See `display-mode-v1-physical-verification.json`,
`owner-direct120-72-static-20261019-v1.json` and `display-mode-v2-native.log` under
`output/pico-recovery-bringup-20261018-v1/`. Clean physical output remains a
blocking requirement for a usable VR session.

The subsequent guarded stock-kernel RAM comparison uses the same CPU colour
producer, with the stock kernel, DTB and boot parameters preserved. Its initial
legacy modeset fails because the primary plane retains a scaler configuration
for a smaller source. Clearing that plane's `scaler_v2` property allows all nine
72 Hz colour phases, 3,600 sampled producer pixels and display cleanup to pass.
A subsequent normal stock boot is independently verified by its changed boot
ID and device identity. This diagnostic makes no firmware partition writes;
the stock direct test has no owner-confirmed optical result. See
`stock-kms-v4-rejection-analysis.json`, `stock-kms-v7-physical-verification.json`
and `stock-kms-v7-session.json` in the same evidence directory.

The stock comparison also records varying controller-zero frame signatures.
The driver's checksum reader does not poll a ready/latch status, so signature
variability alone cannot locate the native corruption. Neither these signatures
nor successful producer readbacks establish clean downstream panel output.

Matched native 120 Hz tests then compare the first splash handoff with a full
display re-enable, using the same colour producer. Both complete 3,600 sampled
pixels and cleanup. Eight of 238 captured PHY words change between those paths:
one clock configuration word and three timing words per PHY. The retained stock
master settings match the inherited values; its slave settings match the
re-enabled values. This establishes a startup difference, not its causal role
in the banding. See `warm-cold-kms-v1-physical-verification.json`.

A separate signed diagnostic uses the vendor's receive path to obtain one-byte
panel replies: command `05` returns `00`, `0a` returns `1c`, and `0c` returns `77`.
Clock-reference and command-engine cleanup succeed, and the module is unloaded.
These readings do not establish correct DSC decoding or clean optical output.
See `dsi-panel-status-v2-physical-verification.json` and
`warm-kms-v1-final-evidence.json`; the latter also binds the unchanged full boot
and DTBO readbacks and verified return to normal stock.

## October 19 native GPU presentation

The new physical kernel `linux-dmabuf-20261019-v1`, its 38 matching modules,
`runtime-initramfs-v9` and `live-root-v13` boot the full native RAM root.
The direct Vulkan test now presents GPU-rendered swapchain images through SDE,
with pixel readbacks, present-completion waits, active plane-framebuffer changes
and DRM vblank checks. A 64-frame test without an application delay measures
about 120 completed presentations per second. Both DSI video engines remain
enabled, ACK error status is zero, and the DSC PPS width remains 1920 pixels.
See the [physical DMA-buffer results](dma-buf-sync.md#neo3-physical-presentation)
for hashes, receipts and proof limits. This boot makes no partition writes.

Monado also initializes its direct-display target on the actual GPU with
explicitly simulated head tracking. Before the refresh correction, Vulkan
reports 48.358 Hz for the driver-labelled 120 Hz mode, and Monado consequently
selects a 20.679 ms frame period. The corrected Turnip bundle reports the
advertised 120/90/72 Hz modes, and Monado selects 8.333333 ms. A native OpenXR
client then submits 120 two-eye projection frames and exits successfully.
Tracking is simulated and optics uncalibrated; missed-deadline warnings remain.
This does not establish sustained VR performance, physical tracking or correct
stereo alignment through the lenses. Both DSI engines and the 1920-pixel PPS
width remain correct in the final snapshot.

The controlled normal reboot subsequently reaches stock boot-complete with the
exact Pico serial, Wi-Fi off and the updater disabled. See
`dmabuf-v1-native-xr-verification.json` and
`dmabuf-v1-normal-stock-return-verification.json`. The native root remains
temporary; Android has not yet been replaced on persistent storage.

## Earlier boot integration and recovery

Generic `v4l_id` probing also blocked native boot by opening vendor codec and
camera control nodes. The observed codec stack waited for `venus.mdt` firmware.
The Pico rule now skips `cam_req_mgr`, `cam_sync` and `msm_vidc_v4l2` while
retaining ordinary video-device identification. The new initramfs stops udev
normally without the previous 90-second timeout. This avoids incidental
probing; codec firmware and camera-session bring-up remain separate work.

## Recovery and authorization

1. The owner's hardware fastboot entry and the demonstrated stock return now
   cover this failed-boot recovery. Software EDL still depends on running
   Android; arbitrary early-boot corruption and cold EDL remain untested.
2. Retain verified original bytes, GPT extents and replacement sizes/hashes for
   the completed transition. ABL/devinfo EDL read/write is demonstrated, but
   restoration of their originals has not been rehearsed. Preserve XBL, XBL
   configuration, GPTs, stock recovery and unrelated firmware.
3. Stock boot restoration and independent full readback are demonstrated.
   ABL/devinfo restoration and recovery of deleted secure keys remain unproven.
   No deliberate bootloader corruption is required.
4. Stock RAM boot and unsigned custom diagnostic startup under the engineering
   ABL are demonstrated. The diagnostic's bounded exit returns to the verified
   on-disk stock boot. Unlock and factory reset are already completed;
   do not rerun them merely to test boot command availability.

The authenticated early-4.6.3 ABL is now installed. Its saved command table
registers a boot handler after authorization for each fastboot session. The
later physical diagnostic establishes unsigned-image acceptance on this unit.
The original community procedure replaces ABL, while the
fork also replaces devinfo. Both were replaced in this session; whether devinfo
replacement was necessary was not isolated. Authorization, unlocking and
unsigned-image authentication remain separate operations.
[Original procedure](https://github.com/264312431/more-picohaxx/blob/f911e67f1714e189ba1dd8a46111065482dd6681/more-picohaxx.py),
[fork](https://github.com/chaixshot/more-picohaxx-tool/blob/c182399937107dd290cbc1ec2fdb06116af83a9d/picounlock.ps1).

A 9008 cable is a candidate for cold entry, not a guaranteed solution for Pro
Eye. Community Neo3 results are mixed. The EDL client's deep-flash cable method
depends on intact XBL/SBL, so a successful test would establish recovery within
that preserved early boot chain, not recovery from arbitrary storage damage.
[Device reports](https://github.com/chaixshot/more-picohaxx-tool/issues/5),
[EDL client](https://github.com/bkerler/edl#run-edl-examples).

## Available originals

The historical October 15 audit passes for all 21 saved partitions and all six
pairs of GPT copies. ABL, ABL backup, devinfo, boot, recovery and calibration originals
are available. That audit predates the October 18 `misc-live.bin` acquisition;
its missing-`misc` result is historical. `live-hashes.txt` in the new evidence
directory binds all seven pre-write acquisitions, including `misc`. The other
state originals still absent from the retained inventory are `frp`, `metadata`,
`uefivarstore` and `secdata`. Their absence does not establish that unlock writes
them. Audit the actual write set before any further transition. The existing
`bootbak`/`vbmetabak` mismatch remains preserved; those partitions are not a
verified fallback.

`tools/verify-pico-backup.py` reports missing partitions with their independently
checked LUN, GUIDs, sector size, LBA range and byte offset. Missing entries have
no backup path or content hash. This supports preparing a bounded acquisition
without treating a known partition layout as an acquired backup.

The same auditor accepts `--replacement PARTITION IMAGE SHA256` for an offline
comparison against a required, verified original. It requires an exact full
partition image and never guesses padding or a partial-write policy. The report
binds the proposed bytes and restore original to the checked LUN, GUIDs and
sector extent, and lists which sectors differ. Only ABL, boot, DTBO and vbmeta
partitions and their named backups are supported; early boot firmware, GPTs,
recovery and device/key state are excluded. A replacement of one member does
not imply that its backup should also change.

This is byte/layout correspondence, not image authentication, rollback
acceptance or a restoration rehearsal. The report contains no flash commands
and keeps those physical acceptance flags false. A raw candidate shorter than
the partition is refused until its exact intended complete bytes are defined.

For the retained Pro Eye originals, an offline candidate copies the 37-sector
older ABL payload and retains the original bytes through the end of the 1 MiB
partition. The comparison finds 36 differing sectors; ABL backup is untouched.
This defined one candidate's complete bytes before the transition. The raw
shorter payload is refused by the auditor. The candidate and comparison are
private in `output/pico-display-recovery-20261014-v1/`. The October 18 full ABL
readback is byte-identical to that candidate, and the changed loader returned
to Android after unlock/reset. This establishes acceptance of that ABL on this
unit, not an unsigned Linux boot or a physical restoration rehearsal. Secure-key
restoration remains unverified.

The earlier `misc` acquisition plan is retained privately in
`output/pico-state-backup-20261013-v1/`, using the revalidated stock GPT extent.
The compiled helper permits only UFS configuration, six geometry queries,
bounded GPT reads, the single `misc` extent after host confirmation, and reset.
Its sanitizer fixture passes 532 allowed and 315 rejected commands without USB
access. The reader was rebuilt with the renamed checkout paths, and its 847 outgoing
command guard cases pass under ASan/UBSan using a fake transport. The device
reader has not run and is stored without execute permission; the October 18
original was instead acquired through qdl. Historical binaries and receipts are
in `output/pico-usb-power-20261014-v1/recovery-tools/`. Recheck live ROM identity, geometry
and both GPT copies before using it. A successful reset after failed acquisition
must still report acquisition failure.

The owner completed the expected factory reset on October 18. Raw userdata
alone is not a proven way to restore usable data after key changes, and there
was no full userdata backup. A Pico4 owner's failed userdata restoration is a
relevant limitation, not proof of identical Pro Eye behavior.
[Owner report](https://github.com/chaixshot/more-picohaxx-tool/issues/4).

## Confirmed unlock effects

Static analysis of the authenticated 4.6.3 ABL and this unit's saved XBL narrows
the transition requirements:

| Operation | Confirmed implementation | Recovery implication |
| --- | --- | --- |
| Command authorization | Adds the restricted fastboot handlers in memory | Handler registration does not itself unlock or establish unsigned-image acceptance |
| Ordinary or critical unlock | Writes the corresponding flag through the Verified Boot protocol | Either command can change persistent state; do not assume critical unlock is needed for a RAM-boot test |
| Device-state storage | XBL uses Keymaster/RPMB when its security checks and secure reads succeed; other branches use `devinfo` | A raw `devinfo` backup is not a complete backup of the possible state stores |
| State reset | Calls Keymaster with request `0x10e` before scheduling recovery | Treat this as destructive key-state reset, independently of filesystem erasure |
| Recovery request | Writes a 1,088-byte message containing `--wipe_data` to `misc` | The pre-unlock original was acquired October 18; the traced helper read-modifies-writes one 4,096-byte sector |

The protocol header identifies the reset operation as a delete command to
Keymaster. Both unlock paths in the exact older ABL reach it; its build-time
guards enable the call. Reset or subsequent `misc` failure does not guarantee
unchanged state. Restoring ABL, devinfo or userdata bytes is not proven to
restore deleted secure keys.
[Qualcomm protocol definition](https://gitlab.com/Codeaurora/abl_tianocore_edk2/-/blob/797918c3bf59e2d65b4acb2acdfd6883a0605ee1/QcomModulePkg/Include/Protocol/EFIVerifiedBoot.h).

The preserved raw `devinfo` already has both flag bytes set, despite the
observed locked, green stock boot. This is consistent with a separate state
source but does not identify the live secure-storage branch. Replacing that
partition is therefore not an established prerequisite or sufficient unlock.
The older ABL's initialization also writes defaults if the state magic is
invalid. The raw backup has valid magic; the live secure record remains
unverified. Merely starting a different ABL must not be described as read-only.

These findings cover the traced authorization, initialization and unlock paths,
not every bootloader side effect or the secure application's implementation.
No direct write to `frp`, `metadata`, `uefivarstore` or `secdata` was established
by this trace. Do not erase or replace them speculatively. Private module
extractions, function exports, GPT correspondence and hashes are retained in
`output/pico-flash-path-20261013-v1/{abl-state,xbl-state}/`.

## Initial Linux acceptance

Use the compiled Pico kernel and authenticated stock DTB pack with an
initramfs-only diagnostic. It should reach init, provide bounded USB diagnostics
and reboot to stock, without mounting internal filesystems or starting the VR
runtime. Verify USB controller operation and controlled return before adding
the external root filesystem, display/mux, DSP and tracking services.

`tools/build-pico-diagnostic.py` now builds that separate initramfs. It packages
one static ARM64 init executable and an explicit bootloader serial; no shell,
modules, firmware, root filesystem or disk-mount service is included. Init
requires PID 1, a RAM root, the exact live compatible list
`qcom,kona-iot-mtp`, `qcom,kona-iot`, `qcom,mtp`, an exact diagnostic command-line token
and matching `androidboot.serialno`. Missing or conflicting identity refuses
USB setup. The virtual test requires a separate `qemu` serial and test token.
Read `ro.boot.serialno` on the identified stock device for this input. On the
inventoried Pro Eye it differs from `ro.serialno`, the serial shown by ADB.
Using the ADB serial would make the diagnostic refuse startup.
The former `qcom,kona` guard rejected this headset before USB setup. Its base
DTB contains that generic compatible, but ABL applies the stock DTBO's root
identity. The live list and stock overlay zero agree byte-for-byte; changing
the stock DTB/DTBO to satisfy the old guard is unnecessary.

```sh
python3 -B tools/build-pico-diagnostic.py PHYSICAL_PICO_KERNEL_DIRECTORY \
  --boot-serial BOOT_SERIAL --output NEW_DIAGNOSTIC_DIRECTORY
```

Assemble the unsigned Android boot container from that diagnostic and the
authenticated full stock boot-partition backup:

```sh
python3 -B tools/assemble-pico-diagnostic.py STOCK_BOOT_BACKUP \
  PHYSICAL_PICO_KERNEL_DIRECTORY NEW_DIAGNOSTIC_DIRECTORY \
  --reference-sha256 RETAINED_STOCK_SHA256 --mkbootimg PINNED_AOSP_TOOL_DIRECTORY \
  --output NEW_CONTAINER_DIRECTORY
```

The assembler requires the diagnostic's physical serial, current source and
matching kernel receipt. It reconstructs the ramdisk to reject extra payloads
or substitution of the virtual test ramdisk, verifies the stock payload
roundtrip, and checks the new kernel/ramdisk/stock DTB sections after unpacking.
It preserves and checks the stock OS version/patch-level header field
(`0x14000154`, Android 10.0.0 / April 2021 on this reference).
The reference hash must come from independently retained authentication or
backup evidence. The output remains unsigned, with boot/recovery and physical
DTB compatibility explicitly unverified; this command never accesses a device.

The later full runtime has a separate maintained assembler:

```sh
python3 -B tools/assemble-pico-boot.py STOCK_BOOT_BACKUP \
  PHYSICAL_PICO_KERNEL_DIRECTORY INITRAMFS_DIRECTORY ROOT_DIRECTORY \
  --reference-sha256 RETAINED_STOCK_SHA256 \
  --root-manifest-sha256 VERIFIED_ROOT_MANIFEST_SHA256 \
  --mkbootimg PINNED_AOSP_TOOL_DIRECTORY --output NEW_RUNTIME_CONTAINER
```

Take the root manifest hash from the completed offline root verification. The
assembler verifies every recorded artifact, the matching kernel, initramfs and
firmware, current Pico startup sources, and the ext4 label and geometry. It
binds the installed component receipts and rechecks inputs after assembly.
Both assemblers unpack the supplied stock backup themselves; neither depends
on another build's extracted DTB or saved command arguments. The full runtime
container leaves display enabled and requires its separately verified external
root image. Assembly does not establish that root transport, DTB selection,
physical drivers or recovery work, and it does not replace the initial bounded
diagnostic.
New Pico runtime command lines use `rd.emergency=reboot` so a root-mount
failure requests a return to the retained stock boot. That specific failure
path still requires physical verification; kernel hangs can prevent reboot.

The optional `--recovery-boot-serial BOOT_SERIAL --initramfs-image IMAGE_ID`
adds a guarded emergency hook that instead requests fastboot. It requires the
exact Neo3 compatible list, one matching boot serial and explicit Pico/recovery
tokens. The builder derives a new initramfs and records both source hashes and
its own payload hash; the baseline root and initramfs stay unchanged.
Add `--recovery-probe` only for a RAM-boot test: its distinctly named
`boot-recovery-probe.img` deliberately requests a missing root label and disables
KMS. **Never flash this probe.**

The October 18 `recovery-probe-v3` RAM boot returned to fastboot autonomously in
40.36 seconds, followed by another successful `live-root-v7` native RAM-root
boot. No partitions were written. See `recovery-probe-v3-session.json` and
`recovery-probe-v3-verification.json`. The subsequent boot exposed no pstore
records, so the hook's kernel-log marker was not independently recovered.
This verifies the observed missing-root test's return; it does not establish
recovery from a hung kernel or every service-failure path. Persistent root
installation still needs those applicable startup/recovery checks.

A separate native systemd 257 service-failure test deliberately executed
`false` with `FailureAction=reboot-force` and `RebootArgument=bootloader`.
These settings are described in the
[systemd 257 unit documentation](https://www.freedesktop.org/software/systemd/man/257/systemd.unit.html#RebootArgument=).
The host observed fastboot again after 22.11 seconds, including the test's
eight-second startup delay. Its receipt is
`native-service-failure-recovery.json`. The generic service-failure test does
not establish that every hardware-specific startup failure follows that path.

A subsequent RAM-only missing-root probe with additional QRTR/PD-mapper
failure actions entered Qualcomm crash mode (`05c6:900e`) instead of returning
to fastboot. The cause is unresolved; those additional unit settings have not
been incorporated. Its receipt is `recovery-probe-v4-session.json`. A bounded
Sahara-only reset could not read the device descriptor and timed out. Stock
`boot` was not changed by either probe. This failure means autonomous recovery
is not yet reliable enough for unattended persistent installation.
The owner subsequently returned the device to fastboot with the hardware
buttons, and the unchanged `live-root-v7` native Linux RAM image booted again.

`build-pico-live-root.py --disable-panic-download` opts a RAM image into the
vendor kernel's `msm_poweroff.download_mode=0` command-line setting. The v8
boot read back `0` from the module parameter and `10` from the panic timeout;
a controlled native reboot returned to the identified fastboot session.
See `native-v8-binary-sync-verification.json` and
`native-v8-controlled-fastboot-return.json`. Panic-triggered recovery has not
been exercised with this option, so it does not resolve the v4 recovery failure
or satisfy unattended persistent-installation acceptance.

It configures the kernel's existing `gser` USB function, waits for the primary
`a600000.dwc3` UDC, and verifies its device-tree compatible, register extent and
USB core ID before binding. Stock firmware selects this controller for the
primary port; the enabled secondary `a800000.dwc3` controller may also register
a UDC. The diagnostic ignores that secondary controller and refuses mismatched
primary metadata. After binding, it waits for the primary UDC to reach the
configured state before opening the serial device. The kernel can buffer a
short report before configuration and discard it when the serial device closes.
The diagnostic transmits bounded kernel/system diagnostics and accepts no host
commands.
A 90-second alarm is armed before mounting the virtual filesystems or reading
identity. Mount and identity failures immediately request reboot before USB
setup; a validated virtual test shortens the alarm to 10 seconds. Neither the
timer nor a shutdown request can recover a hung kernel or replace independent
recovery. The `1d6b:0104` Linux gadget identifier is for this development diagnostic only.
The host collector additionally requires the exact manufacturer, product,
serial and interface descriptors, without detaching a kernel driver:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror tools/pico-diagnostic-log.c \
  $(pkg-config --cflags --libs libusb-1.0) -o NEW_LOG_RECEIVER
NEW_LOG_RECEIVER --serial BOOT_SERIAL > NEW_LOG_FILE
```

The receiver waits up to 90 seconds for enumeration. It checks configuration
one's descriptors before selecting an unconfigured device, and only configures
and claims a unique identity match. It refuses duplicate matching devices and
rejects incomplete or wrong-device reports. A received report proves neither physical reboot nor
return to stock; those require separate observation. The diagnostic does not
load an SELinux policy, so the enforcing kernel arguments alone are not a
claim of userspace policy enforcement.

## Offline verification

The historical October 14 diagnostic uses the physical Pico kernel
`3588cea6461e9807f92fe559884ee313686fffec7eb2afd0d44ba5d3b0c0f513`
and the then-current Reframed init. That artifact was not booted on a headset. The unsigned
Android-v2 image was assembled and unpacked with matching kernel, initramfs and
unmodified stock DTB hashes. Build, assembly and VM receipts are in
`output/pico-usb-power-20261014-v1/`; use `diagnostic` and `diagnostic-boot`.
The October 18 corrected diagnostic instead uses Image SHA-256
`4e9035de7fddf7179e2e99e6bc46a005d5033b2770b9f3cff9e041eb28eb864e`
from `linux-camera-sensor-stop-20261015-v2`; its physical evidence is described
above. The diagnostic contains no modules, so this does not establish physical
loading of the kernel build's 38 modules. The private historical `first-boot-set.json`
binds the diagnostic, host log receiver, runtime root and display overlay to
exact hashes. It records the physical gates as pending and contains no flash
commands.

Seven diskless QEMU boots use that same init binary and physical-config kernel:
normal startup, wrong serial, missing serial, wrong diagnostic token, missing
`/proc`, and missing/conflicting KMS-disable options. Each reaches controlled
power-off. Normal startup creates the real configfs serial function and finds
no UDC. The earlier identity-refusal hang was reproduced before the fix and its
evidence is retained. These tests do not exercise physical USB enumeration,
log transfer, display or recovery.

Linux ARM64 sanitizer tests cover early mount failures, missing or invalid
identity, a non-RAM root, alarm setup failure, PID refusal, USB controller
selection, display guards and bounded report storage. Run them with the existing
Mesa compiler image:

```sh
just test-pico-diagnostic-init NEW_TEST_DIRECTORY
```

Host tests cover log identity, truncation and thirteen USB discovery/configuration
scenarios, including delayed descriptors, unconfigured devices, configuration
failure and duplicate identities. These use mocked USB. The October 18 native
sanitizer tests additionally cover the observed board identity and the shipped
kernel's lack of devtmpfs, using a RAM tmpfs fallback with explicit device nodes.

The initial diagnostic requires `msm_drm.modeset=0`. Pico's vendor display
configuration enables MSM DRM separately from the top-level kernel
configuration; normal registration can restore continuous splash and enable
panel regulators before userspace. The existing modeset parameter stops MSM
DRM master registration and that splash path. After validating identity, init
checks the exact command-line option, the kernel's `N` parameter value and
absence of the `msm_drm` platform driver. Other platform drivers still probe;
this does not establish an untouched physical display.

The authenticated older ABL's default ARM64 placement also passes the updated
diagnostic size check, with more than 39 MiB between the kernel runtime extent
and calculated DTB boundary in its default 86 MiB allocation. Actual UEFI
`KernelBaseAddr`/`KernelSize` and live RAM reservations remain unverified.
Stock DTB/DTBO selection is now observed as described above; the custom
historical diagnostic had not transferred its own complete live report. The
October 18 corrected diagnostic has now done so, as recorded above.
Container header addresses do not describe this dynamic
placement. The full runtime retains display support and needs a separate,
verified external root filesystem.

The historical `pico-boot-v4` full-root container is assembled and roundtrip-verified
offline with the Reframed paths and matched packages. Its QEMU counterpart
passes fresh read-only startup and package checks over emulated USB storage.
Earlier builds separately passed the virtio transport checks.
That historical artifact's physical root transport and display-tree compatibility
remain untested; its kernel/VM results do not replace those checks. The newer
October 18 diagnostic and `live-root-v7` assemblies have separate physical
evidence described above, with rebuilt identity guards, initramfs and root
receipts. Their results do not retroactively validate the older container.

Private October 13 audit and source receipts:
`output/pico-flash-path-20261013-v1/`. Those receipts predate the October 18
engineering ABL/devinfo writes; they do not record a custom Linux boot.


## Prepared artifact set

The retained October 15 private runtime set is
`output/quest-offline-parity-20261015-v1/pico-first-boot-set.json`; its matching
recovery references are in `pico-recovery-session-set.json` in the same directory.
Its missing-original and device-transition flags predate the October 18 session.
Its recorded runbook hashes bind the earlier documentation, not this updated
text. Preserve those historical receipts; a future device plan must bind current
state and instructions rather than promote the old flags to current acceptance.
The set includes the retained native runtime, a read-only USB-root VM
check and matching boot/display assembly. The earlier
`output/pico-camera-sensor-stop-20261015-v1/first-boot-set.json` remains preserved.
Its bounded diagnostic and kernel with signed modules are unchanged.
The set binds the diagnostic, kernel, runtime container, external root, panel
overlay, native package receipts and verification reports by size and SHA-256.
Recheck those identities before use; do not combine a historical root with a
newer runtime receipt. The diagnostic uses the rebuilt kernel in a KMS-disabled
RAM-only stage with stock DTBO. The Sharp120 overlay belongs to the later
display stage.

The current root includes display-time head-orientation prediction, raw
controller IMU decoding, Basalt and the native stereo camera/6DoF runtime.
The kernel now [reports camera shutdown failures](pico-tracking-protocol.md#kernel-camera-stop-failures).
Camera startup, continuous request refill and IMU-to-pose delivery pass the
[offline replay](pico-slam.md#continuous-capture). The replay also exercises
tracked HMD poses and stereo views through the installed driver library, with
simulated hardware and reference calibration. Camera silence with continuing
IMU input and a regressing poll clock both invalidate poses before explicit
shutdown in that installed-library replay. The packaged-root VM loads the same
library, requires the live event-clock entry point and checks its refusal of
missing configuration. Physical HMD and camera activation still require
explicit, verified configuration. The opt-in
`pico-controller-config.py --motion-status` getter is prepared for a later stock
capture. It has only been tested offline. Capture connected controllers'
configuration before selecting their scale and axis branches; do not copy
synthetic test settings into the runtime.

Those historical prepared receipts do not establish physical recovery, native
USB power/role, panel scanout, Adreno buffer sharing or sensor clock/axis
acceptance. The newer physical results above establish specific recovery,
USB-device, GPU execution and KMS milestones. GPU sharing/synchronization,
optical output and sensor acceptance remain separate gates.

## Camera bring-up inputs

Before activating native camera capture, retain the device build and establish
these inputs from the active stock configuration or measured device data:

| Input | Required correspondence |
| --- | --- |
| Sensor selection | Physical sensor and PHY slots, module hash, configuration/group/mode/init indices, stereo order and synchronization role |
| Sensor programming | Probe identity, power sequences, I2C address, CSI lane map, per-lane data rate and clock/bandwidth votes |
| Tracking calibration | Intrinsics, distortion, IMU-to-camera transforms, sensor axes/units and the estimator's camera order |
| Timing | Camera and SSC clock origins, measured conversion uncertainty/expiry, frame period and exposure-center offsets |

The retained kernel skips chip-ID reads for ordinary tracking cameras, so a
successful probe is not hardware identification. The saved module variants and
older XML also do not establish the active pair or calibration. Do not enable
the native camera path with the replay's synthetic configuration.

The first physical camera milestone is bounded, timestamped stereo capture with
verified stop/quiescence, followed by IMU alignment and real-motion tracking.
It comes after the boot/recovery and essential USB/DSP bring-up gates; a replay
trajectory cannot establish any of those physical results.

## USB host startup cleanup

The pinned Pico kernel registers a global USB host-death callback before creating
its xHCI device. If creation fails, the original error path leaves that callback
registered. Subsequent startup attempts trigger the notifier core's duplicate
registration warning. Patch `0042-usb-host-notifier-cleanup.patch` unregisters the
callback before unwinding a failed start. Normal startup and shutdown retain
their existing registration order.

Patch `0043-usb-host-power-cleanup.patch` also checks runtime-resume errors before
notifying PHYs or accessing the controller. Failed resumes balance their usage
reference without requesting another idle transition. Both successful return
values, zero and one, are accepted even when the optional VBUS supply is absent.
VBUS-enable and xHCI-creation failures now disconnect the PHYs before clearing
host flags and releasing the power reference.

The source-matched regression executes the actual host start/stop functions and
notifier list insertion/removal, with hardware operations, callback bodies and
locking modeled. Across 608 failure/retry/lifecycle cases, the original fails
6,208 checks; the notifier-only patch still fails 2,624 power/PHY checks. Both
patches pass on macOS and native ARM64 Linux under ASan/UBSan. An unrelated
controller remains registered throughout. The suite covers negative resume
results, already-active success, both USB speeds, optional VBUS and retries.

```sh
python3 -B tools/test-pico-usb-host.py PINNED_UNMODIFIED_KERNEL_SOURCE \
  --output NEW_TEST_DIRECTORY
```

This does not verify interrupt concurrency, physical USB operation or recovery.
The saved stock device tree connects the primary controller to the USB-PD PHY
and EUD extcon providers; its USB-PD node gets VBUS from the SMB5 regulator.
The QEMU xHCI storage tests bypass those physical drivers and power negotiation.
A working emulated USB root therefore does not establish a usable root medium
on the headset.


## Checking the runtime display pair

The runtime boot assembler preserves the complete stock base-DTB pack. Its boot
image alone does not install the candidate panel selection or native mux binding;
those changes are in a separate unsigned DTBO image. The first KMS-disabled
RAM diagnostic continues to use the stock display configuration.

For the later display bring-up, `tools/verify-pico-display-set.py` verifies the
actual boot image and DTBO together against independently hashed stock originals.
It extracts the explicitly selected base and original overlay, rebuilds the
requested panel/mux binding, and requires the entire candidate DTBO to equal that
result. Every other base tree, overlay and table identifier must remain stock.
It refuses mismatched hashes, indices, extra trailers and unrelated tree changes.
The resulting merged tree retains the stock memory and reservation description.
Explicit `msm_drm.dsi_display0` or `dsi_display1` command-line overrides are
refused because they bypass the verified default panel. Bootloader-added
arguments remain a separate live verification requirement.

All four container paths and hashes, the two indices, and the panel, bridge,
display and expected previous panel are required CLI inputs; `--help` lists them.
The report establishes offline correspondence only. It does not establish live
board selection, panel operation, signature acceptance, recovery or flash readiness.
