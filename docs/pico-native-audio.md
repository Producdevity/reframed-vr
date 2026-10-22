# Neo3 native Linux audio

As of 2026-10-22, the physical Neo3 Pro Eye registers `kona-mtp-snd-card`
under the retained 4.19.81-perf kernel. The fresh-boot test exposes 35 PCM
entries and 5,035 ALSA controls. Speaker playback, microphone capture and
Steam/PipeWire routing have not been verified.

## Verified startup blockers

The original native boot had no ALSA cards, even after the stock ADSP firmware
authenticated and reached ONLINE. APR's platform device existed, but its
Q6/audio children were absent.

The pinned [vendor audio PDR source](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/audio-kernel/dsp/audio_pdr.c)
delivers the service-locator result once and does not replay it in
`audio_pdr_register`. The [audio notifier](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/audio-kernel/dsp/audio_notifier.c)
waits for that framework announcement before registering its ADSP clients.
The source is pinned by [`pico-neo3.json`](../profiles/kernel/pico-neo3.json).

The baseline mapper announced its service at approximately 2.42 seconds;
out-of-tree audio module loading followed at approximately 2.58 seconds.
Masking only the root mapper left the earlier initramfs mapper active and
did not restore the audio graph. A control masking both instances, then
starting the mapper after audio notifier registration, produced `apr_adsp_up`
and populated the Q6 and codec devices on ADSP boot. This control used the
same kernel, DTB, ramdisk and root filesystem; only the kernel command line
changed. The temporary masks use the documented
[systemd generator parameters](https://www.freedesktop.org/software/systemd/man/latest/systemd-debug-generator.html).

Card registration then encountered separate missing codec dependencies.
The RX, TX and VA macro modules and WCD938x slave module lacked autoload aliases.
Explicit loads allowed the codec graph to bind; the final missing
`msm-stub-rx` DAI required `stub_dlkm`. Loading that matching signed module
registered the card. No kernel patch or new device-tree settings were needed.

## Maintained startup change

[`reframed-pico-pd-mapper`](../system/pico/reframed-pico-pd-mapper) now finishes
these module loads before publishing the first mapper service:

```text
q6_notifier_dlkm
rx_macro_dlkm
tx_macro_dlkm
va_macro_dlkm
wcd938x_slave_dlkm
pinctrl_wcd_dlkm
stub_dlkm
```

The helper runs in both initramfs and the normal root. Repeated `modprobe`
calls are idempotent. A failed load aborts mapper startup. The helper already
checks the Neo3 device tree, requested Pico services, service-map hashes and
absence of another mapper. The dracut module explicitly requires and installs
`modprobe`. These names target this vendor kernel and its 38-module bundle;
a future mainline kernel needs a separate audio startup policy.

This prepares module ownership and discovery; it does not boot ADSP or select
an audio route. The diagnostic uses a bounded owner of the existing
`/sys/kernel/boot_adsp/boot` interface to boot and release stock ADSP firmware.
Production ADSP lifetime management remains to be integrated with the audio
session.

## Validation and evidence

Thirteen host tests pass: the existing service installer suite and two audio
startup tests. The latter verify initialization before mapper publication and
that failure of any listed module prevents publication.

The physical fresh-boot test changed only the initramfs mapper helper. Kernel,
DTB, root image, command line and stock OS-version fields were retained.
Both normal mapper services started, without masks or manual module loads.
After the bounded ADSP boot, ALSA registered the card and its controls could
be enumerated read-only. No mixer values were written and no sound was played
or recorded. One fresh boot with the fix has passed; repeated-boot reliability
and a rebuilt full root/initramfs release are not established by this test.

Private evidence carriers and verified member manifests:

| Capture | Carrier SHA-256 |
| --- | --- |
| Root-only mask; earlier initramfs announcement remains | `6b4810a29fd35003ee17333dff2815e2bedf1e7cbe1a20581050cec4884888b6` |
| Both masks; explicit module dependency isolation | `870feae00df9023fe2868960834958b7532d9f2676f8b92b72b9f4ba9169b8a2` |
| Fresh boot with automatic startup fix | `581f996c9d75fedbb9b25db2275bfb18891b40e47fa5df44495876c2e36f440a` |

They are retained under `output/pico-audio-order-session-20261022-v1/`,
`output/pico-audio-order-session-20261022-v2/` and
`output/pico-audio-startup-session-20261022-v1/`, respectively. Boot assembly
and payload comparisons are in `output/pico-audio-ordering-20261022-v1/`.

## Remaining integration

The saved stock mixer XML's 17 direct `speaker` control names all exist in
the native inventory. That is a useful mapping check, not permission to
blindly apply every stock mixer default: the HAL-selected XML variant,
enumerated values, gain limits, calibration requirements and route teardown
still need verification. Build a Neo3 ALSA/UCM policy from those verified
routes, expose it to the Frame audio session with appropriate device
permissions, and validate bounded playback and capture. Speaker, headset-jack,
microphone and suspend/resume behavior need separate hardware acceptance.
