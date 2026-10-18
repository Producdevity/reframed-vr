# Bootloader-unlock roadmap for reframed-vr

Updated October 18, 2026, after the owner-authorized Quest root and Pico unlock
sessions. The project goal remains a SteamOS-like Linux OS running standalone
on Meta Quest 3 and Pico Neo3 Pro Eye, with unlocked bootloaders as a
requirement. A custom kernel entered through rooted Android is a fallback.
Root, bootloader unlock, custom-kernel acceptance and recovery are separate
milestones.

The device results below come from retained session records and the owner's
report. The original documentation review was offline; the subsequent October
18 Pico recovery/bring-up added live checks described below. No new Quest
access was performed. Private evidence remains under ignored `output/`.

## Pico Neo3 Pro Eye — persistent unlock completed

The October 18 session retained build `smartcm.1696861506` (5.8.4.0 b1977).
After engineering ABL/devinfo installation, fastboot authorization and ordinary
and critical unlock commands, the owner completed the consented factory reset
and offline setup. The recorded post-reset state is orange Verified Boot,
`ro.boot.flash.locked=0`, `test-keys` and Permissive SELinux. Unlock persists
across reboot; it does not require a per-boot exploit. The owner reports the
updater was re-disabled before networking.

The completed sequence and original/readback hashes are retained in
`output/pico-edl-reads-20261018-v1/`:

1. `adb reboot edl` entered software EDL over an ordinary USB data cable.
   The authenticated programmer completed Sahara and Firehose reads/writes.
   No 9008 cable was needed for that session. This does not establish cold EDL
   entry without working Android.
2. Live ABL, ABL backup, XBL, XBL backup, XBL configuration and devinfo matched
   the retained October 9 originals. A new pre-unlock `misc` backup closed
   that acquisition gap.
3. The tool release's engineering ABL matched the independently acquired
   early-4.6.3 ABL. Engineering devinfo was acquired and retained. The ABL
   readback matches the 151,552-byte payload and preserves the original tail
   of the 1 MiB partition; devinfo readback matches its payload exactly.
4. Fastboot token authorization, unlock commands, `oem setenforce 0`, reboot
   and factory reset completed. The earlier unlock-effect trace describes
   the authenticated 4.6.3 ABL and saved XBL, not a b1977 unlock implementation.

The saved community sources and earlier ABL analysis remain in
`output/pico-unlock-research-20261012-v1/` and
`output/pico-flash-path-20261013-v1/`. EDL entry, engineering-devinfo acquisition
and the unlock wipe are completed steps, not pending prerequisites to repeat.

### First custom-kernel milestone

The bounded, KMS-disabled custom Linux RAM diagnostic now executes with stock
DTBO and returns to stock. The owner established hardware fastboot entry under
the engineering ABL. A stock RAM boot and complete 96 MiB boot restoration with
independent matching readback were also completed. Autonomous Android →
fastboot → Android and Android → EDL → restored Android were demonstrated.
This does not establish cold EDL, recovery from arbitrary early-boot damage or
ABL/devinfo restoration. Restoring their bytes is not proven to restore deleted
secure keys.

The current evidence is in `output/pico-recovery-bringup-20261018-v1/`.
Corrected diagnostic images exposed the physical USB gadget with serial
`c980c8d4`; this establishes unsigned custom kernel/init execution through the
guarded USB bind. After owner accessory approval, the same v3 image transferred
a complete 74,891-byte kernel report and returned to stock Android; hashes and
observations are in `diagnostic-usb-approved-verification.json`. Earlier macOS
attempts had left the gadget unregistered/unconfigured. The old diagnostic's `qcom,kona`
guard rejected the ABL-final identity (`qcom,kona-iot-mtp`, `qcom,kona-iot`,
`qcom,mtp`); the corrected guard matches both live stock and stock DTBO zero.
No DTB relocation or early boot-chain rewrite was needed. The diagnostic uses
the 38-module kernel build but contains no modules and does not test their
physical loading.

`output/quest-offline-parity-20261015-v1/pico-boot-v4/` is a later full-runtime
container, not the initial diagnostic. Its kernel, initramfs, external-root
inputs and boot-image roundtrip pass offline checks. The root filesystem is
separate, and that historical container's USB-root transport remains unverified.
The later display stage needs its matched DTBO. Its receipt leaves physical boot, DTB
compatibility, root transport and recovery unverified. Unlock alone does not
establish that this runtime can boot immediately. Follow
[Pico first boot](pico-first-boot.md) for the staged acceptance boundaries.

A newer `live-root-v5` assembly reached a full native Linux root on this exact
Pico, with systemd PID 1, an authorized USB root console, nine matching modules
loaded, and active QRTR/PD-mapper services. Its hash-verified root image is
temporarily backed by a read-only file on userdata with a writable RAM overlay.
It returned to stock successfully. These observations do not promote the older
`pico-boot-v4` receipt or establish panel/GPU operation. The final installation
must replace Android and use Linux-owned persistent storage. The owner permits
discarding Android user data; retain firmware, calibration and recovery backups.

The subsequent `live-root-v7` assembly boots the matching new kernel and full
root from a hash-verified payload delivered over USB into RAM. Its native panel
DTBO passed an independent complete 24 MiB readback and a stock return test.
Native Turnip GPU execution and initial/repeated KMS enable/disable tests now
pass; the KMS test must preserve the inherited 120 Hz mode for the first frame.
These are bounded hardware milestones, not a usable desktop or verified optical
stereo output. The subsequent `live-root-v8` boots native Linux, renders Steam
inside Xorg and passes binary GPU synchronization tests, but the owner sees
grey/noisy panel output even during direct KMS colour tests. Physical graphical
acceptance remains failed. Raw IMU delivery has separate physical evidence;
head-frame/optical calibration, tracked VR and persistent Linux installation
remain outstanding. The first-boot document names the associated receipts and
physical logs.

## Quest 3 — temporary root obtained; bootloader remains locked

On October 18, Fuguquest at `2324ce262e674504ad41ec82abcda3bf09dd01e6`
obtained root on build `52433670036000520`, kernel
`5.10.246-gd7102a837402`: new ADB shells were uid 0 with `u:r:kernel:s0`
context and SELinux was Permissive. The privilege change is RAM-only; reboot
restores ordinary shell access and Enforcing. The bootloader remains locked.
The session and nine read-only partition dumps are retained in
`output/fugu-root-20261018-v1/`, with artifact, carrier and partition hashes.

Those dumps include both ABL and XBL slots, devinfo, misc and selected verified
boot metadata. No `xbl_config` dump is recorded in that inventory. The retained
authenticated 524360 OTA independently contains complete `abl`, `xbl` and
`xbl_config` payloads. Offline reconstruction verified their payload hashes;
the ABL and XBL payloads match the corresponding prefixes of the new slot-A
dumps. OTA payloads and live partition dumps have different sizes and roles;
neither establishes an unlock surface by itself.

Fastboot query access was already established through cold USB Update Mode
on October 11: the saved queries report `secure: yes`, `unlocked: no` and
active slot A. Evidence is in `output/quest-cold-boot-menu-20261011-v1/` and
[device installation requirements](device-installation.md). Query access does
not imply unlock authorization or unsigned-image acceptance. No Quest unlock
route is established by the retained evidence.

The next Quest work is offline ABL/XBL/devinfo analysis using these inputs.
The Quest 3 kexec fallback still requires its own memory, peripheral-handoff
and recovery validation; temporary root does not make a Quest Pro loader
compatible with Quest 3.

Two constraints remain relevant:

- **Preserve the vulnerable firmware window.** The earlier updater-disable
  failure concerned unprivileged ADB on the user build; it is not proof of
  what the newly rooted session can change. No verified Quest updater-disable
  result is recorded here. Keep the unit offline until update control is
  verified. Fugu's documented fixed-build boundary is `52433670048800520`.
- **Do not switch to slot B.** Its saved fastboot flag is unbootable. It is
  not a verified fallback, and no restore path has been demonstrated.

The CPU-timer work remains a separate research fallback. The inspected 488
source retains the bug, but that does not establish a working root exploit,
the shipped 488 binary's behavior or coverage of later releases. See the dated
[Quest boot-route investigation](quest3-boot-route.md).

## Remaining execution boundary

Pico unlock, custom diagnostic startup, stock boot restoration/return and Quest
temporary root are completed owner-authorized results. The remaining Pico work
is display/runtime bring-up and installation onto Linux-owned storage. Complete
USB log transfer, file-backed native root boot, and the subsequent USB-delivered
RAM root with bounded GPU/KMS tests are verified.
Quest unlock analysis proceeds offline. Device operations stay within the
owner-authorized exact-device scope and verified backup/recovery boundaries;
the completed Pico boot restoration does not validate arbitrary firmware writes.
