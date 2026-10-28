# Native Neo3 wireless bring-up

## Verified boundary

On 2026-10-24, the Neo3 Pro Eye's QCA6390 (`17cb:1101`) created a managed
interface under native Linux and completed a passive scan returning 211 BSS
entries. It remained unassociated, unloaded the WLAN driver cleanly and returned
to offline b1977 stock with audio muted. Full BOOT and DTBO readbacks match
before and after the successful test. No partition was flashed or erased.

This establishes firmware startup, managed-interface creation and passive
reception. It does not establish association, DHCP, throughput, power management,
coexistence with tracking/SteamVR, or persistent image integration. The test
driver used a fallback MAC. A later test provisions this unit's verified stock
address before bringing the managed interface up, reads it back and completes a
passive scan returning 214 BSS entries. It remains unassociated and unloads
cleanly. The stock source reports permanent address assignment while Wi-Fi is
disabled; the unit-specific address stays in private evidence. This is a bounded
test, not an installed address-provisioning service. BSS entries are observations,
not a count of distinct networks.

Evidence: `output/pico-wireless-20261024-v1/native-single-client-scan/`, especially
`managed-scan-result.json`, `bluetooth-transport-result.json`, `console.log` and
`stock-return-v2.json`. The directory-level README and hash manifest distinguish
earlier failed attempts from this acceptance.

## Firmware-client policy

The stock device tree enables `cnss-daemon-support`. CNSS consequently advertises
two WLFW clients, although this native Linux session has no Android CNSS daemon.
With that policy, the physical test connects the MHI/QRTR transport and QMI
service but times out waiting for firmware readiness.

`0053-cnss-optional-daemon-support.patch` adds the built-in parameter
`cnss2.daemon_support=0`. It selects the kernel-only client arrangement without
changing the stock device tree or firmware. The default remains true and honors
the existing device-tree policy. The single-client physical test advances through
firmware memory requests and target capabilities, then brings up WLAN when the
independent firmware-loader delay below is removed.

The Pico runtime assemblers now include `cnss2.daemon_support=0` in their shared
Pico service arguments. Plain and Quest runtime arguments retain their existing
policy. The matching kernel must include patch 0053; a boot argument alone
cannot add the missing parameter to an older kernel.

The driver and this policy use the pinned ByteDance Neo3 kernel; this is not a
PICO 4 device-tree substitution. Source provenance is
`profiles/kernel/pico-neo3.json` and the retained source/build receipts.

## Optional firmware fallback

CNSS tries `qca6390/regdb.bin` before the board-data and M3 downloads. This file
is absent from the retained stock radio bundle. The pinned source treats its
failure as optional, but its generic firmware sysfs fallback waits 60 seconds for
a userspace loader. Native userspace does not supply that loader; the wait
exceeds CNSS's firmware-ready deadline.

The successful bounded test sets
`kernel.firmware_config.ignore_sysfs_fallback=1` before loading WLAN and restores
the previous value after unloading. Direct loading of the retained authentic
firmware and Qorvo board-data file continues normally. No regulatory payload or
calibration is fabricated. This is currently a test-session setting, not an
installed system policy. Normal image integration must explicitly handle this
fallback policy as well as the CNSS boot parameter.

The nine selected Fedora runtime RPMs pass signature and dependency checks on
the Pico and install only into its RAM overlay. NetworkManager and BlueZ remain
stopped for the passive test. No SSIDs, credentials or network configuration are
installed. The test selects the `managed` interface from `iw dev`; P2P and NAN
interfaces also exist and are unsuitable substitutes.

## Modules and recovery

The signed QCA6390 WLAN module has 480 imported symbol versions matching the
kernel. The signed H4 transport has 42. The retained 38 kernel/audio modules also
match the test kernel's imports, configuration and embedded signing certificate.
The test deliberately reuses the verified read-only root/initramfs; its receipt
still identifies the original kernel, and a separate compatibility/assembly
receipt records the new kernel. It is not represented as a rebuilt full image.

An initial isolated build regenerated its signing certificate because the
copied key's preserved timestamp predated generated build prerequisites. Its
RAM boot failed before the root handshake. The corrected build retains the
known-good embedded certificate, verified directly in both kernel images before
boot. Private signing keys remain inside the build volume. Firmware-ready
timeouts and the failed scan-harness attempt remain in the evidence.

## Bluetooth

The native QCA6390 TTY path now passes ROM-version reading and firmware
initialization on the physical Neo3. The original vendor protocol dereferences
the absent serdev device in TTY-reachable paths and its firmware helper lacks
QCA6390 handling. Installing BlueZ alone does not resolve either problem.

The opt-in diagnostic patch
`patches/kernel/pico-neo3/experimental/0054-qca6390-tty.patch` retains the vendor
UART core, guards those accesses and backports `btqca.c`/`btqca.h` from
[Linux v5.10, commit 2c85ebc](https://github.com/torvalds/linux/tree/2c85ebc57b3e1817b6ce1a6b703928e113a90442/drivers/bluetooth).
It preserves upstream copyright and GPL-2.0-only notices. The ordinary TTY
default remains ROME; QCA6390 requires `qca6390_tty=1`. Serdev still supplies its
own chip type. The optional `qca_version_only=1` returns `ECANCELED` immediately
after reading the ROM version, before firmware download; this diagnostic does
not produce a fully initialized adapter.

An isolated external-module build against the retained kernel produces signed
`btqca.ko` and `hci_uart.ko` with 18 and 72 matching imports respectively. Their
signatures verify against the actual kernel's embedded certificate; tampering
with an ELF byte makes verification fail. The baseline kernel configuration,
symbol versions, linked image and signing keys remain unchanged. The patch
applies without fuzz to the pinned vendor files and reproduces the compiled
sources exactly. It remains outside the default kernel patch set until normal
startup and the remaining functionality are integrated and tested.

The first bounded native run unblocks the stock `bt_power` rfkill device and
attaches `/dev/ttyHS0` using `btattach -P qca -S 115200` with hardware flow
control. It receives product `0x10`, SoC `0x400a0200` and ROM `0x0200`. The second
run downloads the authentic `htbtfw20.tlv` and `htnv20.bin` from the retained
b1977 Bluetooth firmware partition image into controller RAM, then reports
`QCA setup on UART is completed`. BlueZ management lists one HCI adapter with
BR/EDR and LE capabilities, left unpowered for normal use. No discovery, pairing
or Bluetooth audio test is performed.

The stock Bluetooth HAL's `FormRegularPaths` reads
`persist.pvr.bluetooth.firmware.load`, defaulting to `0`, which selects the
ordinary NVM. The observed property is unset. The alternative `htnv20swift.bin`
is therefore not substituted. Firmware hashes, HAL hash and selection analysis
remain in private evidence; no unit identity or firmware binary is committed.

The initial adapter reports the firmware's default Bluetooth address. The later
unit-identity test below verifies provisioning before normal use. One initial frame
reassembly error (`-84`) occurs before the successful version exchange; sustained
UART reliability remains unverified. Pairing, audio, power management,
Wi-Fi/tracking coexistence and automatic UART transport startup remain open. Bluetooth is
separate from the Pico controllers' MCU/DSP receive path and does not resolve
optical controller tracking.

Both runs restore platform rfkill state and unload the test modules. The second
also restores the firmware search path; its first cleanup wrote a newline as the
path, then an explicit empty-string write and readback corrected it before
returning to stock. NetworkManager and BlueZ are masked only in the RAM overlay.
Full BOOT/DTBO hashes remain unchanged. Evidence is
`output/pico-bluetooth-20261024-v1/`, particularly `native-version/`,
`native-firmware/`, `patch-validation.json`, `signature-validation.json` and the
directory README/hash manifest. The unit-MAC Wi-Fi scan shares the second boot;
the two radios are exercised sequentially, not concurrently.

## Unit identity collection

`tools/pico-wireless-config.py` reads the stock WLAN address and the Bluetooth
address reported by both the secure setting and Bluetooth manager. It requires
the exact b1977 fingerprint and Bluetooth HAL hash, disabled Wi-Fi, Bluetooth
OFF, empty IPv4/IPv6 main route tables and permanent WLAN assignment. Two complete
snapshots, their surrounding boot IDs and the native boot serial must agree. Missing, multicast or known
placeholder addresses are rejected. It issues no radio setters or firmware
commands and refuses to overwrite an existing output.

```sh
python3 tools/pico-wireless-config.py --serial DEVICE_SERIAL \
  --output output/pico-radio-identities.json
```

The mode-0600 receipt contains private unit addresses, source identity and read
results. It has been tested on the offline physical Pico; stock Bluetooth manager
and its cached setting agree while Bluetooth is OFF. This is a stock identity
collection boundary, not independent factory-address attestation or a native
Bluetooth address-programming test. The native WLAN test above uses the same
stock address, with successful Linux readback. Automatic installed startup
remains unverified.

## Native Bluetooth unit identity

`tools/pico-bluetooth-identity.py` consumes the private stock receipt and requires
its boot serial to match the selected native Neo3 and boot UUID. It checks the
QCA6390 TTY transport, a stopped BlueZ service, public-address support and an
unpowered adapter before using the standard Bluetooth management command. It
verifies the resulting address and leaves discovery, pairing and advertising
disabled. A matching address requires no write. Receipts are private mode 0600;
no unit address or calibration is embedded in source.

If a write or its verification fails, the helper attempts to restore and verify
the pre-write address. Restoration rechecks the same boot, adapter identity and
unpowered state; it refuses to write across a boot change or to a powered adapter.
The receipt distinguishes verified restoration from incomplete recovery, and
the original provisioning attempt still fails. Host fault-injection tests cover
timeouts, wrong readback, failed restoration and unchanged-address failures.
This recovery path has not been exercised against the physical adapter.

The first physical test exposes an endian bug in the backported QCA helper:
the management command succeeds, but all 73 later readable adapter snapshots
contain the byte-reversed unit address. The unchanged checker rejects this result.
The cause matches upstream Linux commit
[77f45cca8bc5](https://github.com/torvalds/linux/commit/77f45cca8bc55d00520a192f5a7715133591c83e).
Experimental patch `0055-qca-public-address-byte-order.patch` backports its
`btqca.c` correction after `0054`, retaining Johan Hovold's attribution. It swaps
the kernel's little-endian address at the non-ROME vendor-command boundary;
the ROME callback is unchanged. The userspace helper still supplies the ordinary
unit address, without an endian workaround.

Only `btqca.ko` changes in the second payload. Its 19 imported symbol versions
match the retained kernel; the module signature verifies against that kernel's
embedded certificate, and a tampered ELF is rejected. The linked kernel,
configuration, symbol table and signing material remain unchanged. On the Pico,
the standard command now yields the correct unit address, a second call performs
no address write, and ten subsequent management snapshots retain that address
with the adapter unpowered. This is address/configuration lifecycle acceptance,
not Bluetooth pairing, traffic throughput or sustained UART-load acceptance.

Evidence is `output/pico-radio-integration-20261025-v1/` for the rejected
readback and `output/pico-radio-integration-20261025-v2/` for the fix, module build,
signature checks and native receipts. Both retain the original failure/success
boundaries, restore platform rfkill and the firmware search path, unload the
test modules, verify full BOOT/DTBO readbacks and return to quiet offline stock.
Host tests exercise the actual callback's wire bytes and error paths, reject the
unpatched helper, and verify that ROME's byte order remains unchanged.

## Passive scanning with native VR active

The next physical test uses the single-client CNSS kernel and its retained
module-ABI compatibility receipt with the existing camera, tracking and SteamVR
stack. The graphics profile, restored shader cache and scheduling settings match
the preceding layer-off control. Bluetooth initializes with the verified unit
address and stays unpowered; the WLAN managed interface receives its verified
stock address. NetworkManager, BlueZ and wpa_supplicant remain runtime-masked.

A passive scan overlaps the first late SteamVR measurement window for 2.291 s,
returns 60 BSS observations and leaves the interface unassociated. All four
cameras continue supplying head and controller classes. The window passes all
3,000 head queries, but one of 3,000 vsync-age queries is overdue. That query
occurs 19.275 s after the scan finishes, so this recording does not establish a
causal relationship with scanning. Its 2,771 deduplicated software frame records
report 82 drops, GPU median/p99 7.273/8.060 ms and interval p99 21.590 ms.
The prior separate-boot control has comparable GPU times and still reports drops;
this is integration evidence, not controlled acceptance of wireless performance.

The strict timing assertion stops the run after that first window. The planned
second and third windows are not collected. Controller output has 13,788 decoded
callbacks and zero public confident optical poses; tracked pointing remains open.
The camera/SLAM termination diagnostics follow the harness's early cleanup and
do not establish an independent camera failure. Physical lens clarity, motion
accuracy, active Bluetooth traffic, network association and power-management
acceptance remain unverified.

Evidence is `output/pico-radio-coexistence-20261025-v1/`, including the sent
payload manifest, module compatibility boundary, partial timing analysis and
143 verified exported members. Setup retains a readiness-check `KeyError` and
its same-boot correction before graphics starts. Cleanup restores the original
interface address/flags, platform rfkill, firmware search path and fallback
sysctl, then unloads all three radio modules. MCU references reach zero,
SLPI/CDSP stop, full BOOT/DTBO hashes match and muted offline stock return passes.

## Wi-Fi unit identity and startup

[`pico-wifi-identity.py`](../tools/pico-wifi-identity.py) makes the verified stock
WLAN address available before network startup. It consumes the private stock
identity receipt, binds the native board, boot serial and UUID, and requires a
managed QCA6390 interface under the `cnss_pci` driver with `wlan` loaded.
NetworkManager and wpa_supplicant must be stopped. The interface must be down
and unassociated; the helper never brings it up or supplies network credentials.

The helper checks address readback, interface index, device/driver paths and
unchanged flags. A matching unit address needs no write. A failed write or
verification attempts restoration of the previous address, provided the same
boot/interface remains down and unassociated. A changed boot, interface, driver
or flags prevents further writes and reports incomplete restoration. The private
lock and receipts prevent overlapping provisioners and accidental evidence
replacement. Interrupted writes enter the same restoration path; repeated
termination is deferred during that cleanup.

Within an already prepared native Pico session:

```sh
python3 tools/pico-wifi-identity.py \
  --boot-serial DEVICE_BOOT_SERIAL --boot-id "$(cat /proc/sys/kernel/random/boot_id)" \
  --identity /path/to/private/stock-radio-identities.json \
  --interface wlan0 --output /run/NEW_WIFI_IDENTITY.json
```

The opt-in CMake option `REFRAMED_PICO_WIFI_IDENTITY=ON` packages the helper,
its identity-validation dependency, a launcher and
`reframed-pico-wifi-identity@.service` in component `PicoWifiIdentity`. It does
not enable a service. The installed launcher reads the selected boot serial
from `/etc/reframed-vr/pico-boot-serial` and the private root-owned mode-0600
receipt `/etc/reframed-vr/pico-radio-identities.json`.

The service instance is the interface name. It binds to that network device,
uses a private runtime directory and only `CAP_NET_ADMIN`, and runs before
NetworkManager/wpa_supplicant. In a prepared image, enabling
`reframed-pico-wifi-identity@wlan0.service` creates a required dependency of
NetworkManager, so a failed identity step prevents its startup. Installation
and dependency enablement do not themselves associate with a network.

The image must still initialize the verified firmware/modules and CNSS client
policy before this device-bound service can run. Network association, DHCP,
throughput, suspend/resume and complete installed-image acceptance remain open.

Eight host tests cover matching identities, failed writes/readback, restoration
failure, interrupted writes, changed boot/interface/driver/flags, private receipt
validation, actual ioctl packing and device-state refusals. A native test in
`output/pico-wifi-identity-20261025-v1/` verifies address change and readback with
unchanged down flags, then a repeated call without an address write. Its passive
scan returns 161 BSS observations while remaining unassociated. Bluetooth
initialization and its unit-address checks also pass with the adapter unpowered.
Original interface state, rfkill, firmware path and fallback policy are restored,
all three radio modules unload, full BOOT/DTBO readbacks match and muted offline
stock returns. Host rollback tests do not establish physical rollback acceptance.

### Distinct vendor interface names

The vendor driver creates `wlan0`, `p2p0` and `wifi-aware0` under the same PCI
path. The default path naming policy therefore proposes `wlp1s0` for all three.
In the rejected version-2 startup test, the kernel records `wifi-aware0` winning
that name while the managed-interface device dependency fails. In version 3,
`wlan0` wins and the other two fail renaming. udev itself is running correctly.
The failure is a naming collision, not a reason to remove the device dependency.

The packaged `10-reframed-pico-wifi.link` matches this Neo3 PCI path,
`cnss_pci` driver and vendor interface names. It selects no rename policy and
leaves the initial driver MAC unchanged; the identity service separately applies
the verified unit address. Its first-match behavior follows the
[systemd link policy](https://www.freedesktop.org/software/systemd/man/257/systemd.link.html).
Install this file before loading WLAN. Reload udev configuration when installing
it into an already running development root. Other PCI paths and drivers do not
match the rule. Include the policy in initramfs too if that image initializes WLAN.

The version-4 native test installs this policy before module loading. All three
interfaces keep their kernel names, select the new link file, receive the
`systemd` tag and have active device units without replaying an add event.
The installed `reframed-pico-wifi-identity@wlan0.service` reaches active/exited
with status zero, `NoNewPrivileges=yes` and only `CAP_NET_ADMIN`. Its restart
performs no address write; its private runtime directory is removed on stop.
A passive scan returns 162 BSS observations without association. The normal
image still needs firmware/module startup and connection policy integration.

Evidence is `output/pico-wifi-identity-20261025-v4/`. The failed dependency case
and the unmodified-policy comparison remain separately retained in versions 2
and 3. Component-only CMake installation, installed launcher guards and ARM64
ioctl ABI checks pass; the full XR/image build is not claimed.

The 11-member native export is 143,262 bytes, SHA-256
`80e1a8c0bc32a4b17334395af0a6972f60a6e580ebaf44c396ef41068029600d`.
Member/source hashes, interface/rfkill/firmware-path/fallback restoration, radio
module unloading, full BOOT/DTBO readbacks, muted offline stock return and the
owned USB helper's exit all verify. Bluetooth remains unpowered, and pairing,
association and active-traffic acceptance remain open.

## Bluetooth identity startup component

`-DREFRAMED_PICO_BLUETOOTH_IDENTITY=ON` installs the `PicoBluetoothIdentity`
CMake component: the identity helper, launcher and
`reframed-pico-bluetooth-identity.service`. The default is OFF; installation does
not enable the service. It uses the same private mode-0600
`/etc/reframed-vr/pico-radio-identities.json` and `pico-boot-serial` as Wi-Fi.
No unit address or firmware binary is installed from this repository.

This component assumes the verified QCA6390 modules and UART firmware setup
have already produced an unpowered `hci0`, with BlueZ stopped. The helper now
checks that the selected HCI sysfs device is a direct child of the actual
`ttyHS0` device before writing an address and after successful information reads.
Having an unrelated Bluetooth adapter alongside the loaded UART module is
insufficient. SIGTERM/SIGINT enter the existing verified rollback path; repeated
termination signals are ignored during that recovery. Host fault injection
verifies restoration and subsequent signal-handler restoration. Physical
interrupted-write recovery remains untested.

Within that prepared native session, `systemctl start
reframed-pico-bluetooth-identity.service` verifies identity without powering the
adapter. The unit runs with `CAP_NET_ADMIN`, `NoNewPrivileges=yes`, a private
runtime directory and only AF_UNIX/AF_BLUETOOTH sockets. Enabling it creates a
`bluetooth.service.requires` dependency; ordering places identity before BlueZ.
A normal image must first integrate the transport owner and its startup/teardown
ordering. Do not enable this dependency in an image whose transport startup is
still missing. This oneshot is not a UART lifecycle or adapter reconnect manager.

The physical test runs the actual installed component. Its first call verifies
the unit address, a restart performs no address write, and stopping it removes
the runtime receipt directory. After transport teardown, starting BlueZ with
the enabled identity dependency fails; BlueZ remains inactive with no main PID.
The adapter remains unpowered throughout. The accompanying Wi-Fi identity
receipts pass again; the passive-scan result from this run was not retained and
is not accepted retrospectively.

Evidence is `output/pico-bluetooth-startup-20261025-v2/`. The initial version
returned to stock before the console appeared; its cause remains unproven.
Version 2 reached the console, but a long heredoc was truncated during USB
delivery, interrupting the final report after service execution and transport
cleanup. The console was resumed, and a separate bounded recovery script
verified the retained service receipts, installed asset hashes, missing-transport
dependency behaviour, firmware path, rfkill state and module unloading. The
original delivery failure remains in the evidence. No third boot was needed.

The recovered 12-member archive is 6,910 bytes, SHA-256
`53c45f31a084e539ebee63fb43b0562f8a3956f763af1b6826d5320bbee87159`.
All member hashes, full BOOT/DTBO readbacks, muted offline stock return and the
owned console helper's exit verify. Twenty Wi-Fi/Bluetooth helper tests and the
component-only CMake installation pass; the installed wrapper refuses a
non-Pico Linux environment and invalid argument counts. This does not establish
pairing, Bluetooth audio, active radio throughput, suspend/resume or complete
installed-image acceptance.

## UART startup integration remains blocked (2026-10-27)

The four diagnostics in `output/pico-wireless-session-20261027-v{1,2,3,4}/`
attempt automatic UART ownership before the graphics workload. They use the
current scheduler-corrected RAM kernel, with kernel-notes SHA-256
`2e1922a20cf71c2894f095f0b559fd3b95fddab0bd9666b88121bbf30cbb7e64`.
Firmware initialization can complete, but the subsequent unit-address update
fails: the kernel records command `0xfc14` timing out and the address callback
returning `-110`; management information then remains unavailable. This is
failed integration, not a working BlueZ startup chain or a pairing result.

The first diagnostic also exposes a management-readiness gap: an HCI sysfs
device can exist before management information is available. Waiting for that
information, checking `hciconfig` state, explicitly closing startup HCI, and
retaining the earlier manual path's 18-second interval do not establish a
successful complete startup. These alternatives must not be described as fixes.
The pinned kernel masks `HCI_UP` during auto-off in both management and
`HCIGETDEVINFO`, so a displayed unpowered/down state alone is insufficient to
prove that startup has finished.

The successful October 25 identity-service reference used
`single-client-boot-v2/boot-live-single-client.img`, whereas these attempts use
the later scheduler-corrected kernel and the full tracking/display preparation.
Those differences remain unisolated. Reproduce the working minimal reference
on the current kernel before attributing this failure to scheduling, firmware,
startup ordering or the service sandbox. The unverified transport service and
its sources remain in ignored experimental output; they are not installed by
the repository's CMake components.

The failed guards prevent the combined graphics test from starting. A separate
graphics-only control is recorded in `pico-steamvr-verification.md`. All four
wireless attempts retain verified full BOOT/DTBO after-readbacks and muted,
offline stock return. One early UART teardown also times out; successful native
transport teardown is not claimed. The private archives have verified member
manifests and the following SHA-256 values:

| Attempt | Bytes | SHA-256 |
| --- | ---: | --- |
| v1 | 53,550 | `1e983e1c7f9b50f3728e62a959ebe5b53505a74078f221932de7c0380aae39e5` |
| v2 | 2,849,144 | `263b3ba23da717350f4c76d0f493bcec262f674aea79b473b13bf619d48f4d75` |
| v3 | 2,849,192 | `bbe5c32917423d06a2ebd4ff214c8dcdb5ac03e17c88c2271a4bdff09fd1f3b0` |
| v4 | 2,849,765 | `28b7689d1167d7a166b46872d8286ac05b00d8060ba61f27df525f726469cea8` |

## Combined scheduler/radio kernel control (2026-10-27)

The minimal replay in `output/pico-wireless-minimal-20261027-v1/` stops before
starting Bluetooth: its precondition cannot read the CNSS `daemon_support`
parameter. The retained scheduler-kernel build omits patch 0053 and its boot
argument. This is a verified integration gap, not a reproduction of the HCI
command timeout above. Its failed-precondition evidence and unchanged BOOT/DTBO
readbacks are retained, and muted offline stock return verifies.

`output/pico-radio-rttime-kernel-20261027-v1/` combines the existing blocked-wake
scheduler correction with patch 0053 and the explicit native CNSS argument.
Configuration and the complete exported module-CRC table match the previous
kernel; the retained initramfs and DTB are unchanged. Two patch-record hash
differences only relocate identical lockdep compatibility replacements between
patches 0012/0013. Applying both recorded and current sequences, including patch
0014, produces byte-identical `drm_syncobj.c`; the private
`patch-order-equivalence.json` retains that proof. This remains a RAM-boot
diagnostic, not an accepted installation image.

The exact minimal radio sequence then passes in
`output/pico-wireless-minimal-20261027-v2/`, without graphics, cameras, SLAM or MCU
startup. The installed Bluetooth identity service writes the unit address and
restarts without a second address write. Ten later management reads remain
available and unpowered. Wi-Fi identity setup/restart and a passive scan pass,
with 131 BSS observations. Native interface, rfkill and firmware-loader state
restore; radio modules unload. Full BOOT/DTBO after-readbacks match, muted offline
stock return verifies, and the owned USB host exits.

The diagnostic boot image has SHA-256
`d3607ed25e5d50533dc728f93fca22b50dd03f2a5c9402abcf5bd3f56f8c14e7`;
kernel notes are
`7e83359bb98ccbc7bb210a554ee1e074a498e87b5fafc7c417826b2b1471c2f5`.
The verified archive has 11 data files, 144,695 bytes, SHA-256
`baf94bfa18849dc05ac2c1031a65e643ffcd582c9d9f62c37f6da9317746f71f`.
This restores a working minimal control on the scheduler-corrected kernel. The
automatic UART owner, full graphics/tracking coexistence, Bluetooth pairing,
Wi-Fi association/DHCP and active radio throughput remain unaccepted.

## Optional UART owner and BlueZ lifecycle (2026-10-28)

`REFRAMED_PICO_BLUETOOTH_TRANSPORT=ON` now installs the tested native UART owner,
its wrapper and service, and the identity-service dependency drop-in. It is off
by default and requires `REFRAMED_PICO_BLUETOOTH_IDENTITY=ON`. The owner validates
the native Pico/boot binding before loading the QCA transport, refuses an
existing adapter or active BlueZ daemon, and signals readiness only after the
bound UART and management endpoint are initialized. Identity provisioning still
requires the verified unpowered adapter. Enabling the identity unit makes BlueZ
require that sequence; stopping BlueZ propagates to both owned units.

The native control uses the combined scheduler/CNSS RAM kernel. It performs
three automatic UART starts and three verified stops, including explicit
identity-only ownership, a real BlueZ start/stop, and an unpowered owner held
through the 180-second graphics/tracking workload. Every stopped owner records
adapter detachment and restoration of its original rfkill state. Head tracking
completes 4,499 camera sets and 184,595 callbacks with zero bad results; controller
images continue through 4,445 sets, with no confident optical controller poses.
This is coexistence with an unpowered Bluetooth adapter, not active radio-traffic
or controller-pointing acceptance.

Two preceding diagnostics isolate test-lifecycle assumptions. In the first,
identity provisioning succeeds but stopping an inactive BlueZ unit does not
stop manually started ownership. The next explicitly stops manual ownership,
then observes a real BlueZ stop complete while its dependent UART unit remains
`deactivating`. The completed test waits up to 25 seconds for that already
propagated teardown to finish before checking HCI removal/rfkill or restarting;
the observed dependent wait is about 0.296 seconds. Active, failed or indefinitely
deactivating owners are rejected. Cleanup is registered before setup. These
harness corrections do not reclassify the earlier failures as passes or prove
the cause of the older HCI command timeouts.

Twenty-one maintained host Bluetooth tests, eight native transport fixtures,
four host teardown-wait cases and fresh component-only installation checks
pass. Installed files match all seven native-deployed assets byte-for-byte;
configuration refuses transport without identity support. The unit owner is
available as a component, while inclusion in a complete installed root image
remains a separate integration step.

Evidence is `output/pico-wireless-session-20261028-v3/`: 335 data files,
45,637,576 bytes, archive SHA-256
`0d8f96fb24671b88466d445b753a578a4779ea8e0a6c18a3f982eab8a16043c4`.
Service/module/rfkill/source cleanup, full BOOT/DTBO after-readbacks, muted offline
stock return and the owned USB-host exit verify. Pairing, Bluetooth audio,
active traffic, Wi-Fi association/DHCP/throughput and complete installed-image
acceptance remain open; the earlier passive Wi-Fi control is unchanged.

## Powered adapter boundary (2026-10-28)

The guarded test in `output/pico-bluetooth-power-20261028-v2/` uses the maintained
UART/identity services and the corrected scheduler/CNSS kernel. BlueZ has no peer
objects, and discovery/pairing remain disabled. The first D-Bus power-on succeeds:
BlueZ and management information both report powered, retaining this unit's
verified address. Power-off also succeeds with matching unpowered readbacks.
This establishes one cold powered/unpowered transition, rather than repeatable
warm power cycling or radio traffic acceptance.

The second power-on exceeds the diagnostic subprocess's 10-second bound. The
kernel reports opcode `0x0c56` timing out; the retained vendor HCI header identifies
it as Write SSP Mode. An unexpected event for that opcode follows. The attempted
D-Bus power-off during failure handling also returns an error. Source and logs do
not identify the first delay boundary, establish an IBS-state bug or justify a
longer kernel timeout. Capture command timestamps and HCI/transport state before
changing the driver. No pairing was attempted.

The first diagnostic version fails before power-on because its private parser
expects one HCI header, while `btmgmt info` also prints this same adapter's
configuration-options header. Version 2 accepts the recorded primary/configuration
headers for HCI0 and uses that actual output as a fixture. It retains strict unit
identity checks; the three host/native lifecycle fixtures pass. This parser
correction is separate from the subsequent real power-cycle failure.

Both attempts stop before the graphics workload. Both verify the existing
service/module/rfkill cleanup, complete BOOT/DTBO after-readbacks, muted offline
stock return and owned USB-host exit. The earlier unpowered-coexistence acceptance
is unchanged. Powered coexistence, repeatable power cycling, pairing, Bluetooth
audio and Wi-Fi association remain unaccepted.

| Attempt | Data files | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| Parser preflight v1 | 99 | 2,962,376 | `1e125902b8146dd14a6e1c1ba2fcaa27ff7e5234141ca3225da7b37ebbcfdbfa` |
| Power-cycle v2 | 99 | 2,963,275 | `875742ec8f2efb18b1f2abb93bb36d07b3f70315de505cd0b0e7bad5489d955e` |
