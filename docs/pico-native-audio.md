# Neo3 native Linux audio

As of 2026-10-22, the physical Neo3 Pro Eye registers `kona-mtp-snd-card`
under the retained 4.19.81-perf kernel. Frame's PipeWire stack routes the native
ARM64 Steam client's startup audio through the speaker PCM, and the owner
confirmed hearing Steam's startup sound. Microphone capture, protected speaker
calibration, sustained playback under concurrent SteamVR/6DoF load and an
installed audio session remain unverified.

The earlier zero-valued PCM tests establish transport and restoration only.
The requested WSA digital mute values did **not** prevent audible Steam output
in the later test. Do not use those control readbacks as a guarantee of silence.

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

## Verified speaker-route diagnostic

The physical unit reports hardware revision `B4`. Analysis of its hash-pinned
`audio.primary.kona.so` shows the `B4`/`B6` fallback selecting
`mixer_paths_pro.xml` and enabling speaker protection. The retained stock file
inventory contains no more specific MTP variant. This establishes the selected
fallback from the binary and installed files; it is not a trace of the Android
HAL opening the XML. The Pro variant's speaker route selects the
`WSA_CDC_DMA_RX_0` backend's `S24_LE` format; the base XML does not.

| Stock input | SHA-256 |
| --- | --- |
| `audio.primary.kona.so` | `a33021954bd576ad661a66eb20181d3b9a5b3c7732c60b94584e9e8075e26559` |
| `mixer_paths_pro.xml` | `3eae1996a38943878160bc455851a1429212a289535df57fd7260132d061589d` |

[`pico-audio-route.py`](../tools/pico-audio-route.py) requires that XML, the tested
kernel's notes hash, the B4 hardware revision, the expected sound card and an
explicit native boot identity. Its default mode resolves the controls and
checks types, counts, ranges and enum labels without writing mixer values.
The opt-in `--test-silence` mode requires an idle sound card and an exclusive
diagnostic lock. It applies two digital mutes, the 18 direct Pro `speaker`
controls and one `deep-buffer-playback` control. It restores all 21 original
values after closing PCM, including on a failed write or playback interruption.
SIGINT/SIGTERM are deferred during mixer restoration.

The frontend `WSA_CDC_DMA_RX_0 Audio Mixer MultiMedia1` advertises a two-value
boolean control, but the pinned
[routing callbacks](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/audio-kernel/asoc/msm-pcm-routing-v2.c)
use only `value[0]`. The diagnostic allows this exact exception and rejects
other multi-value controls. A separate native check reproduced the signed
digital-volume control returning `256` after a requested `0`; its original
`84` was restored. The diagnostic uses digital mute instead and does not
change those volume controls.

On one native boot, matched tests negotiated a 2,400-frame buffer comprising
four 600-frame periods. Fixed 480-frame writes timed out after 1,920 frames,
before reaching ALSA's start threshold. The vendor
[`msm_pcm_playback_copy`](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/audio-kernel/asoc/msm-pcm-q6-v2.c)
consumes a whole DSP slot even for a partial-period copy. Writing full negotiated
periods completed 48,000 frames at 48 kHz, stereo `S16_LE`, through the stock
`S24_LE` speaker backend. This is a client workaround; no kernel code changed.

The pinned
[4.19 drain implementation](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/sound/core/pcm_native.c)
returns `EAGAIN` for nonblocking drain even after completion. The test observed
`snd_pcm_wait` returning `EIO` as the stream reached `SETUP`. The diagnostic
accepts that transition only with zero delay and hardware/application pointers
both exactly equal to the submitted frame count. The successful native result
recorded `48000` for both pointers, restored all 21 mixer values and left every
PCM closed. Missing AFE/ASM calibration warnings persisted in that successful
run; they do not explain the earlier short-write startup timeout.

Example, within an already owned native audio test session with ADSP online:

```sh
python3 tools/pico-audio-route.py \
  --boot-serial c980c8d4 --boot-id "$(cat /proc/sys/kernel/random/boot_id)" \
  --mixer-xml /path/to/private/mixer_paths_pro.xml \
  --output /tmp/NEW_AUDIO_PREFLIGHT
```

Add `--test-silence` for the bounded muted test, or `--test-ucm` for the
per-session UCM enable/playback/disable test described below. These switches
are mutually exclusive. The tool does not start ADSP,
install routes globally, unmute the speakers or capture microphone audio.
Thirteen host tests cover rollback, deferred termination, full-period writes,
drain completion, input refusal and UCM failure/restoration paths.

Private HAL/XML selection evidence is retained in
`output/pico-audio-routing-20261022-v1/`. Additional verified carriers:

| Capture | Carrier SHA-256 |
| --- | --- |
| Route shape, volume readback and muted short-write failure | `73e8cdaaa90601fb96f6b200ff86f3484eb8f3520ddad7246d9e0f12ead9cc51` |
| Same-boot partial/full-period comparison and completed silent PCM | `d933a21f8e3e193022bd719a0793f6be914f8686df51ed9f7c44472e716222ab` |

These carriers and their member manifests are in
`output/pico-audio-routing-session-20261022-v1/` and
`output/pico-audio-period-session-20261022-v1/`. The tested tool SHA-256 is
`af8d2583416c92c36494279f086b3184f7a2da62f2f0232014c231674660fb5b`.
Full BOOT and DTBO readbacks match the retained hashes after both sessions.

## Frame PipeWire backend test

The retained official
[Steam Frame repair image](https://steamdeck-images.steamos.cloud/recovery/steamframe-oobe-repair-20260922.5153644-0.3.0.img.zip)
supplies PipeWire/libpipewire/pipewire-pulse `1:1.6.8-1.2` and their native
dependencies. The diagnostic exports 175 files, totaling 27,280,203 bytes, from
that image into a private prefix. The source archive SHA-256 is
`672df1b9c5c6b849df506c995a32fe136b53c4db688f924e6727639dd8b963a9`;
the extracted root partition matches
`668da2b1d32e9b779a1ee27ed570961ceaaf83a5dfeadd8129b62603223c319d`.
The temporary root copy was removed after verification; the original repair
archive and selected-file manifest remain retained. The current diagnostic root
is Fedora 44 with selected Frame components; full Frame base integration remains.

Container validation establishes private PipeWire IPC, an explicitly linked
silent client and a responding PulseAudio compatibility server. The physical
test uses the same private libraries under a bounded systemd unit, while the
existing diagnostic owns the speaker route and both digital mutes. Links are
created explicitly in that earlier test; no UCM or WirePlumber policy is installed
by it. The private
root-only socket uses the documented
[`access.legacy` mode](https://github.com/PipeWire/pipewire/blob/1.6.8/src/modules/module-access.c).
That access policy is specific to this diagnostic, not a desktop-session policy.

The native comparison exposed two further timing requirements:

- Read/write mode repeatedly underruns with this PipeWire client. The vendor
  mmap path recycles complete DSP periods, bypassing the partial-copy path.
- PipeWire rounds a requested 600-frame graph quantum down to 512 by default,
  while the hardware retains 600-frame periods. The captured graph log and
  hardware parameters confirm that mismatch. Disabling
  [`clock.power-of-two-quantum`](https://docs.pipewire.org/page_man_pipewire_conf_5.html)
  preserves 600 frames. A ten-second run then has one startup underrun followed
  by 197 RUNNING samples. One period of headroom still records a startup reset.
  Two periods of headroom pass the strict repeated test.

The verified candidate values are:

| Setting | Value |
| --- | --- |
| Graph rate; quantum/minimum/maximum | 48,000 Hz; 600 frames each |
| `clock.power-of-two-quantum` | `false` |
| ALSA path; format; channels | `hw:0,0`; `S16_LE`; stereo |
| `api.alsa.period-size`; `api.alsa.period-num` | `600`; `4` |
| `api.alsa.headroom` | `1200` frames |
| `api.alsa.disable-mmap` | `false` |
| `api.alsa.soft-mixer`; `api.alsa.disable-mixer-path` | `true`; `true` |

[Headroom](https://docs.pipewire.org/page_man_pipewire-props_7.html) adds buffering
to protect the hardware queue. The configured 1,200 frames equal 25 ms at
48 kHz; end-to-end audio latency has not been measured. These values remain a
diagnostic candidate rather than an installed production policy.

On the same native boot, two identical ten-second tests each submit 480,000
zero-valued client frames. Their 198 hardware-status samples each remain RUNNING,
with monotonic hardware progress of 478,200 and 479,400 frames during observation.
Neither captured PipeWire log records `XRun!`; neither status capture records
XRUN. Both PulseAudio compatibility servers respond, all 21 mixer controls are
restored, and every PCM is closed afterward. These are light-load audio tests;
concurrent SteamVR/6DoF load, audible output and microphone capture remain
unverified.

All attempts, including the rejected configurations, are retained under
`output/pico-frame-audio-session-20261022-v1/`. The final carrier is
`export-frame-audio-final.tar.gz`, 668,553 bytes, SHA-256
`c07fdf44773230d4049298cc3975126e3406415eebaaf6524e0160b12d6c9353`;
all 130 member hashes verify. The tested session script SHA-256 is
`f4686ab71a231151df8b8e760580d6e6f74560f49325e52ae6222c1dbfa82938`.
The ADSP owner releases cleanly, full BOOT/DTBO readbacks remain unchanged,
and stock b1977 returns with Wi-Fi off and the updater disabled.

## Per-session UCM and Steam-user routing

The optional `--test-ucm` mode generates a private UCM configuration from the
same 21 resolved controls and their live original values. It enables the `HiFi`
verb and `Speaker` device, verifies every applied value, and requires the
selected PCM to be `hw:konamtpsndcard,0`. After playback it disables the device,
verifies that UCM restored the originals, and sets the verb inactive. An
independent reverse-order restoration still runs if enabling, playback,
disabling or manager cleanup fails. Both digital mute controls are requested during
the test; the later Steam test below shows that this does not guarantee silence. These snapshots are per-session data, not portable mixer defaults.

The first physical attempt failed before playback because ALSA's numeric-ID
parser consumed the following value as part of the ID. The generated sequences
now delimit it explicitly, for example `numid=205,iface=MIXER 1`, matching the
[ALSA control parser](https://github.com/alsa-project/alsa-lib/blob/master/src/control/ctlparse.c).
All 21 original values were restored after that failure. The corrected test
completed 48,000 silent frames, with matching completed hardware/application
pointers, successful UCM disable and full fallback readback.

The candidate session configuration is maintained in
[`system/pico/audio`](../system/pico/audio/):

- `pipewire.conf.in` retains the physically verified PCM and graph timing and
  accepts the UCM-selected PCM in `@PLAYBACK_PCM@` as a quoted configuration
  string. It exposes a single static `ReframedPicoSpeaker` sink.
- `client.conf` provides the private PipeWire client configuration.
- `wireplumber.conf.d/50-reframed-pico.conf` defines a `pico` policy profile for
  default-node selection and stream linking. It does not enumerate audio,
  Bluetooth or camera hardware; the root UCM owner selects the route, and the
  static sink owns playback PCM.

These files are opt-in templates, not installed services. The tested deployment
uses Frame's private PipeWire 1.6.8 and WirePlumber `0.5.14-1.3` with their
matching configuration, modules and dependencies. The expanded selected-file
manifest contains 275 files, totaling 29,567,966 bytes, from the same verified
repair image. The retained library prefix is selected explicitly; host or
system libraries are not replaced.

The physical test starts PipeWire, WirePlumber and a normal PulseAudio `pacat`
client as Steam's `vr` user, UID/GID 1000, with supplementary `audio` group 63.
Their private runtime directory has mode 0700. The root UCM owner holds the
route separately. WirePlumber selects `ReframedPicoSpeaker` as the default sink
and creates both active stereo links without an explicit target or manual
link command. The client submits 480,000 zero-valued frames over ten seconds.
Observed hardware progress is 462,600 frames, monotonic, with no captured ALSA
XRUN state or PipeWire `XRun!` message. The actual hardware parameters are
MMAP_INTERLEAVED, stereo S16_LE, 48 kHz, 600-frame periods and a 2,400-frame
buffer. UCM disable restores all 21 controls, the independent readback passes,
and every PCM closes. This validates a client under Steam's user; it does not
establish that Steam itself played audio.

Private evidence is in `output/pico-peripheral-session-20261022-v1/`.
`export-policy.tar.gz` is 222,575 bytes, SHA-256
`ce37922ba80bc0306cae410f88b394e5eecc4c5e64fb929884ef96da21787bcd`;
all 112 member hashes verify, including the failed first UCM attempt. The tested
route tool SHA-256 is
`7cede99dfd5d79612a88ab35f58c3a50778b688d45cbcb13a643d811b3e359b1`.
The ADSP owner releases to OFFLINE, MCU references remain zero, and full BOOT
and DTBO hashes match the retained originals. Stock return is recorded
separately in that session's receipt.

## Remaining integration

Install the bounded route and Frame audio policy into the production Steam
session with explicit ADSP lifetime management, and validate a real Steam
client under concurrent compositor/6DoF load. Calibration and
speaker protection still need validation before an audible route is accepted.
Speaker, headset-jack, microphone and suspend/resume behavior need separate
hardware acceptance. The silent test establishes PCM progress and teardown,
not audible quality or a working Steam audio device.

## Native Steam startup audio

A fresh native RAM boot (`b0c23392-e3f4-4cdd-8d50-5c300ecc70df`) ran the
installed ARM64 Steam client under user `vr`, using Xvfb to isolate audio from
the VR display and tracking workload. The first attempt lacked
`/home/vr/.steam/steam`; Steam refused startup, and all 21 mixer controls were
restored. Creating the standard link to its existing data directory allowed
the second attempt to start.

The private UCM/PipeWire/WirePlumber session automatically selected
`ReframedPicoSpeaker`. The recorded Pulse stream identifies `steamwebhelper`,
UID user `vr`, stereo float32 audio at 48 kHz, and sink 18. Its 94 observations
include uncorked playback and subsequent corking; the hardware PCM advanced
771,000 frames during observation. No sampled ALSA XRUN or PipeWire `XRun!`
was recorded. The owner independently reported hearing **Steam's startup
sound** from the Pico. This verifies actual Steam audio output, rather than
only a synthetic Pulse client.

The user then requested quiet operation. Playback was stopped, every PCM was
closed, all 21 controls were restored, and the owned ADSP reached OFFLINE.
The test requested both digital mute controls, but audible output disproves
that these values guarantee silence through stream startup. The exact cause
of that behavior is still unverified. Future quiet session tests must enforce
and verify software sink mute before launching Steam; stopping playback and
releasing the owned ADSP remains the verified quiet state.

Private evidence: `output/pico-peripheral-session-20261022-v2/`, including the
failed attempt, successful stream/PCM captures and audio-stop receipt.
`export-peripherals.tar.gz` is 420,923 bytes with SHA-256
`d3a021f22e22f80781f17b272c8cae4da6b0d813123fea718a8a33c1dca88871`;
all 199 member hashes verify. The user's listening confirmation is separate
from the machine-generated result, whose `audible_output_verified` field
correctly remains false. This run does not establish microphone operation,
audio quality, end-to-end latency, or simultaneous SteamVR/6DoF performance.
