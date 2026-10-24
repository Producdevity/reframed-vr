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
driver used a fallback MAC; the unit's proper address must be provisioned from a
verified stock source before association. BSS entries are observations, not a
count of distinct networks.

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

The physical tests load and unload the signed H4 `hci_uart` transport cleanly.
No HCI adapter is registered: chipset power/firmware initialization, attachment,
pairing, audio and coexistence remain unverified. Installing BlueZ alone does
not provide those missing steps.

Do not attach the pinned vendor QCA UART protocol blindly. Its setup path
dereferences the serdev device and lacks QCA6390 handling; a TTY-only attachment
does not satisfy that contract. Bluetooth is also separate from the Pico
controllers' MCU/DSP radio path and does not resolve optical controller tracking.
