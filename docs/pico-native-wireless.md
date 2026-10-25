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
Wi-Fi/tracking coexistence and installed startup remain open. Bluetooth is
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
