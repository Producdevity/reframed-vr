# Bootloader-unlock roadmap for reframed-vr

Written October 18, 2026, after re-anchoring on the project goal: a
SteamOS-like Linux OS running standalone on the Meta Quest 3 and the Pico
Neo3 Pro Eye, with **unlocked bootloaders as a requirement** — soft-boot
strapped on top of Android each boot (kexec, root-on-boot) is the
fallback, not the design.

This reframes the priority stack: root exploits are tools on the way to
unlock and custom boot, not end results. Evidence references are all
retained in `output/`.

## Pico Neo3 Pro Eye — unlock is a concrete, evidence-backed sequence

State verified this session (read-only): build `smartcm.1696861506`
(5.8.4.0 b1977), locked/green, soc serial `172059610` readable from
Android — exactly the input the community unlock uses for its
serial-derived OEM token.

The community route (more-picohaxx; upstream and fork sources, issues,
and the full PowerShell implementation are snapshotted in
`output/pico-unlock-research-20261012-v1/` with hashes):

1. Enter EDL (the tool's own path; our stock b1977 command table also
   has `oem reboot-edl`, but a previous live reboot-edl stuck the unit
   in Sahara and needed a manual power-hold — do not repeat without the
   recovery procedure rehearsed; the 9008 button cable remains the
   safer entry and normal-cable cold EDL already failed).
2. Via the authenticated programmer we already retain
   (`prog_firehose_ddr.elf`, root-of-trust verified October 8): back up
   current ABL and devinfo, then write the early-4.6.3 ABL (already
   acquired and hash-verified locally) and an engineering devinfo.
3. Fastboot OEM authorization with the serial-derived token, ordinary +
   critical unlock requests, SELinux boot config change — the b1977 ABL
   analysis (October 13) confirmed the unlock wrappers are compiled in
   and enabled; their effect is a wipe scheduled through `misc` and
   recovery, plus Keymaster/RPMB state reset.
4. Factory reset is expected and acceptable for this dev unit.

Prerequisites status: ABL ✓ retained, programmer ✓ authenticated,
command tables ✓ extracted, devinfo backup ✓ (our own, October 9),
tool sources ✓ snapshotted, token algorithm ✓ in retained source.
Outstanding: (a) physical EDL entry — decision between the 9008 button
cable (needs user confirmation of availability) and a carefully
rehearsed `oem reboot-edl`; (b) the engineering devinfo payload the tool
ships (acquire and audit it before writing anything); (c) a `misc`
partition backup — the unlock path writes `misc` and our backup audit
explicitly lists `misc` among the absent originals; the tool backs it up
as part of its flow, but that requires EDL read access to be working
first.

After unlock: the project already has unsigned boot containers, a
verified boot assembly (`pico-boot-v4`) and QEMU-verified roots — an
unlocked Pico can boot our existing kernel immediately. The Pico is
therefore the fastest route to the first real "SteamOS on a standalone
headset" milestone.

## Quest 3 — unlock is gated on root; the root window is time-limited

The retained 524360 OTA authenticates boot, vendor_boot, dtbo, vbmeta,
vendor, vendor_dlkm, odm, odm_dlkm — **no abl/xbl bootloader partitions;
Quest OTAs never ship them**, and this project has never established
fastboot access on the Quest. So there is no offline artifact to analyze
for a Quest unlock surface, and no known unlock command exists publicly.

The only lever: obtain root on 524360 (Fugu — documented working on
exactly this build; our static audits passed; see
`docs/quest3-boot-route.md`), then dump `abl`/`xbl`/`xbl_config`/
`devinfo` from the device for the same kind of offline unlock analysis
that produced the Pico route. Root also unblocks the kexec soft-boot
fallback (`quest-kexec` port) if unlock research dead-ends.

Two hard constraints on that window:

- **The update window.** The headset is still on 524360 (verified
  October 17–18), auto-updates are NOT disabled, and adb provably cannot
  disable them on this user build (`updater-status-20261018.md`). Fugu
  dies on 524488. The Settings-UI toggle (then our settings-diff to make
  it adb-verifiable) or keeping the headset offline is required before
  any multi-session root work.
- **Slot B is unbootable; never switch slots.** Any boot-chain work on
  Quest happens with slot A only until a verified restore path exists.

Execution order for Quest: flip the UI update toggle → run audited-
source Fugu (bounded, crash-tolerant) → dump boot-chain partitions →
offline ABL unlock analysis → either an unlock path or the kexec
soft-boot architecture. The CPU-timer exploit stays the documented
fallback for post-524360 firmware (its bug persists in 488+ source) and
is not on the critical path while Fugu's window is open.

## What this changes about earlier recommendations

The previous "root first, decide later" framing is superseded: root is
now explicitly instrumental (partition dumps, boot-chain research), and
both unlock gates are sequenced above it. No flashing of either device
happens until the existing recovery/restore gates are satisfied; the
Pico unlock wipe is the single destructive step currently on the roadmap
and requires explicit user confirmation plus the EDL-entry decision
before execution.
