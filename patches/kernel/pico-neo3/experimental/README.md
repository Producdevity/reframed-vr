# Neo3 diagnostic patches

These patches are retained for review and explicit diagnostic builds. They are
not part of the default Neo3 kernel patch set: `tools/kernel-build.py` selects
only `*.patch` directly inside the parent directory.

- `0049-dsi-v24-lane-swap-selector.patch` tests the legacy lane-map selector
  on DSI controller v2.4.
- `0050-dsi-noncontinuous-hs-request.patch` selects host HS requests when
  non-continuous clocks are configured. Its header credits the PicoFrame
  diagnosis and source commit.

Neither change independently resolved the observed static/banding. The clean
solid-green observation came from a subsequent dual-DMA-plane display test.
These candidates must not be described as the verified display fix or silently
added to a normal kernel build. Historical diagnostic images may contain them;
use each image's retained build provenance when reproducing a result.

Apply these GPL-2.0 kernel changes only to a separate diagnostic source copy,
record both patch hashes, and revalidate the result on the target headset.

## QCA6390 Bluetooth

`0054-qca6390-tty.patch` backports the Linux v5.10 Qualcomm firmware helper and
adds explicit QCA6390 TTY attachment to the Neo3 vendor UART driver. The patch
header records upstream provenance; original copyright and GPL notices remain.
It is independent of the display candidates above and is also excluded from
normal kernel builds.

Signed modules built from this patch read the physical controller's ROM version,
download the authentic Hastings 2.0 patch/NVM into controller RAM and expose a
BlueZ management adapter. Power restoration and unload pass. This is firmware
initialization acceptance, not pairing, audio, coexistence or persistent system
integration. See [native wireless bring-up](../../../../docs/pico-native-wireless.md).
