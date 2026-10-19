# Neo3 direct-display research, October 19

## Decision

Pause parameter changes. The matched stock-kernel comparison below preserves
the mode but changes two half-width DMA planes to one full-width VIG plane.
A subsequent two-DMA-plane test produces owner-confirmed clean direct green.
The native diagnostic now accepts the same DMA layout in software; integrate it
with GPU/VR presentation before changing panel parameters.
The cause remains unproven. Changing VR runtime cannot explain a fault
already reproduced without a VR runtime; a new kernel is not yet justified by
this symptom. The completed controls and their optical boundaries are recorded
in [pico-first-boot.md](pico-first-boot.md).

## What the sources establish

The direct hardware-fill producer uses `DRM_IOCTL_MODE_SETCRTC` and changes the
selected primary plane. This is **not** a separate non-atomic kernel path:
`drm_atomic_helper_set_config()` calls `drm_atomic_commit()` in our retained
4.19 source. Its request configures the primary plane, CRTC and connectors;
it does not explicitly reset every other plane or every vendor property.
See `drm-atomic-helper-current-reference-v1.c:2904–3015` in the evidence directory
below and the [pinned upstream helper](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/drivers/gpu/drm/drm_atomic_helper.c).
Simply rewriting the producer to use the atomic ioctl is therefore not a demonstrated fix.

SDE solid fill is generated in the source pipe. `_sde_plane_color_fill()` still
programs rectangles, scaling and pixel extension; `_sde_crtc_blend_setup_mixer()`
iterates all attached planes and configures their mixer stages. A verified green
source-pipe register does not prove that the final mixer output is green.
Sources: [Neo3 sde_plane.c](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/techpack/display/msm/sde/sde_plane.c),
`_sde_plane_color_fill`, and [sde_crtc.c](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/techpack/display/msm/sde/sde_crtc.c),
`_sde_crtc_blend_setup_mixer`. This agrees with the documented
[plane → CRTC blending → output pipeline](https://docs.kernel.org/gpu/drm-kms.html#overview).
The exact proprietary b1977 HWC transaction has not been reconstructed here.

PicoFrame's pinned README now reports correct native dual-DSI DRM output at
90 Hz, rather than only framebuffer output. Its patch 0018 fixes a mainline
slave timing-engine enable. Our Neo3 downstream code **already** enables timing
only for the master in `sde_encoder_phys_vid_handle_post_kickoff()`; copying that
patch would duplicate existing behavior. Its resync-FIFO patch 0014 likewise
derives from the vendor `dsi_post_clkon_cb` path already present here.
Sources: [PicoFrame README](https://github.com/TheReal-Flo/PicoFrame/blob/3affbc11ecaae56c56b7bd3eb13344c73a7a03da/README.md#native-display-drm-status),
[patch 0018](https://github.com/TheReal-Flo/PicoFrame/blob/3affbc11ecaae56c56b7bd3eb13344c73a7a03da/patches/kernel/0018-drm-msm-dpu-leave-the-timing-engine-of-a-split-displ.patch),
and [Neo3 video encoder](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/techpack/display/msm/sde/sde_encoder_phys_vid.c).
PicoFrame's hardware report is its maintainer's report, not an independently
verified Neo3 result. Its two 2160×2160 panels and mainline driver differ from ours.

Upstream has fixed real bonded-DSI slice-count mistakes, and PicoFrame adds
multi-slice packet support. These establish mechanisms worth auditing, not
applicability: Neo3 downstream already calculates bytes-per-packet and
packets-per-line using `slice_per_pkt` in `dsi_panel_dsc_pclk_param_calc()`.
Sources: [upstream per-interface slice-count correction](https://kernel.googlesource.com/pub/scm/linux/kernel/git/stable/stable-queue/+/refs/tags/v6.12.41/releases/6.13.11/drm-msm-dsi-use-existing-per-interface-slice-count-i.patch),
[PicoFrame patch 0002](https://github.com/TheReal-Flo/PicoFrame/blob/3affbc11ecaae56c56b7bd3eb13344c73a7a03da/patches/kernel/0002-drm-msm-dsi-support-more-than-one-DSC-slice-per-pack.patch),
and [Neo3 panel source](https://github.com/bytedance/neo3-kernel/blob/9cacc1c1356dd32a048f4cb13bc84af402bd3326/techpack/display/msm/dsi/dsi_panel.c).

## Ranked remaining mechanisms — inferences, not findings

| Priority | Mechanism | Evidence and counterevidence |
|---|---|---|
| 1 | Composition or routing differs during direct takeover: plane coverage/staging, mixer/CTL/pingpong binding, or vendor CRTC state | Source-pipe fill leaves these stages active. The stock-direct scaler rejection already exposed one inherited-state dependency. No extra active overlay or incorrect route has yet been demonstrated; native reproduction means stale Android overlays alone cannot be assumed. |
| 2 | Full modeset changes a panel/link lifecycle condition absent from normal Android | Working stock versus corrupted stock-direct makes the transition relevant. PicoFrame proves sequencing can matter, but the specific master-only timing and FIFO behavior are already in Neo3's vendor driver; matching XBL QP/type/waits did not remove the noise. |
| 3 | DSC packetization, merge or interface state beyond the compared register subset | Upstream demonstrates per-interface accounting failures. Matching the generated PPS, compression registers and selected DSI registers lowers this lead; those comparisons do not prove complete routing or wire equivalence. The known width/QP changes were insufficient. |

## One proposed next diagnostic

Use one matched **stock-clean → first direct takeover** comparison at an unchanged
refresh rate, without changing kernel, DTBO, PPS bytes, delays or PHY parameters.
Require a contemporary owner-confirmed clean stock baseline; otherwise retain
the capture but do not label it a clean optical control. Before takeover, record
all attached planes and their rectangles, modifiers, z-order, scaling and vendor
properties, plus connector/CRTC properties and the driver-supported SDE snapshot
of LM/CTL/pingpong/DSC/INTF routing. Quiesce the competing composer under controlled
ownership, record the same state immediately before and after takeover, and trace
whether takeover actually triggers panel disable/enable. Use supported snapshot
interfaces, not a new broad MMIO read. End with normal-stock recovery verification.

If composition or route differs, audit that concrete difference before another
parameter test. If those states match but corruption begins with panel/link
restart, prioritize the transition. If takeover cannot preserve and identify the
working state, stop and improve capture rather than count it as another negative.
The software comparison has now run, as recorded below. Its optical result is
unavailable.

## Subsequent stock-state capture

A bounded wake-window capture confirms both physical DSI video engines on
before and after the software-state read. The physical DSI connector uses two
planes sharing one imported framebuffer, each covering a 960×3664 half of the
1920×3664 output. Six other active planes belong to the virtual display. Earlier
screen-off captures are excluded from this live-panel baseline. No contemporary
owner optical observation accompanies this capture.

A temporary stock boot initially leaves an empty root-owned userdata output
file. A revised collector writes to restricted `/dev` tmpfs, proves the first
write to the host before proceeding, and completes a zero-error capture of all
25 DRM objects and 33 distinct property blobs. The original output failure's
cause remains unknown. Stock events identify physical planes 110/113 as distinct
DMA2/DMA3 pipes, dual-pipe DSC, and disabled destination scaling despite reserved
scaler resources. These are software-state observations. Normal stock return is
verified. See `state-route-v1/tmpfs-snapshot-v2/verified-manifest.json`.

## Matched stock-kernel takeover result

The first attempt aborts before stopping composer or changing the display:
stock is at 120 Hz while the diagnostic requires 72 Hz. The corrected diagnostic
preserves the active stock mode, independently verifies its advertised timings,
and captures baseline, composer-stopped and first-direct-frame state in one boot.
Each phase contains 25 objects and 33 distinct blobs with no collector errors.

In this run all three 68-byte mode blobs are byte-identical: 1920×3664 at 72 Hz,
382164 kHz, SHA-256
`5d4d44e6a350fdff455038f397df7cc6ba63560582baceb9df0a56a0fd7682f0`.
Stopping SurfaceFlinger and the vendor composer removes the physical planes
while the CRTC and both video engines remain active at the snapshot boundaries.
The first direct frame changes composition as follows:

| State | Physical planes | Buffer and geometry |
|---|---|---|
| Stock | 110/113, DMA2/DMA3 | Shared imported AB24 buffer, Qualcomm modifier `0x500000000000001`; two 960×3664 source/destination halves |
| Composer stopped | None | CRTC remains active |
| Direct green | 70, VIG0 | Owned linear XR24 buffer; one 1920×3664 source/destination rectangle |

Connector properties remain unchanged. The CRTC's mode blob ID changes, but its
content does not; the direct CRTC state reports `mode_changed=0`. No physical
overlay remains alongside the direct plane. This narrows the next source audit
to the changed source-pipe/mixer path; it does **not** establish the cause or
prove uninterrupted electrical panel state.

The cached event reader resets log counters on open and exposes retained/stale
slots. Its printed indices cannot order separate captures, and missing events
cannot prove that a panel restart did not occur. No fresh committed resource
reservation records appear in the latter phases, so complete LM/CTL/pingpong/
DSC/INTF equivalence remains unproven.

The diagnostic preserves the stock kernel, DTB and non-ramdisk header fields,
checks 400 green buffer samples, completes output-disable cleanup, and returns
to normal stock boot-complete. It writes no firmware partitions. There is no
contemporary lens observation; neither this comparison nor a software screenshot
establishes clean output. See
`state-route-v1/matched-takeover-v2/verified-manifest.json` and `analysis.json`.

## Owner-confirmed clean direct green

The next controlled stock-kernel test replaces Android composition with two
DMA planes, retaining the physical plane IDs 110/113 and their 960×3664 source
and destination halves, rotation, alpha and blend settings. Both share an owned
**linear AB24** green buffer. The vendor exclusion rectangles are explicitly
cleared; pointers originating in the composer process are not replayed.
The driver accepts an atomic `TEST_ONLY` request and then the two-plane commit
without `ALLOW_MODESET`; no CRTC or connector property is written. The owner
answers **“Clean, solid green”** during the verified 90-second hold and then
confirms that it is green again.

All three mode blobs remain byte-identical to the 72 Hz blob above. Captured
programming events identify DMA2/DMA3 in both stock and direct phases, with the
same half-screen geometry. Each capture has 25 objects, 34 distinct blobs and
zero collector errors. Buffer checks cover 400 samples. Plane-disable cleanup
succeeds, followed by verified normal stock boot-complete. Kernel, DTB and
non-ramdisk boot header fields remain stock; no firmware partition is written.

This establishes a clean direct DRM path after Android display services stop.
It also shows that a linear buffer can produce clean output on this hardware.
It does not isolate one causal difference from the earlier VIG path: pipe
selection/count, format, blend state and transaction contents changed together.
It does not establish clean native-Linux output, patterned rendering, stereo,
tracking or Steam acceptance. The next step is to reproduce this DMA layout
under native Linux, then integrate it with GPU presentation and the VR session.
See `state-route-v1/dma-split-takeover-v2/verified-manifest.json`, `analysis.json`
and `owner-result.json`. The preceding DMA attempt guard-aborted before composer
stop; the successful runner waits for the actual stock DMA route to settle.

## Native Linux DMA port: software verification

The existing hash-verified native RAM boot and root subsequently run the DMA
diagnostic under `systemd`, kernel `4.19.81-perf`. DRM object IDs differ from
stock: physical CRTC 140, primary plane 69, and DMA planes 109/112. The diagnostic
discovers the planes and checks their capabilities before use. Captured SDE
blend events independently identify the two active source pipes as DMA2/DMA3,
with the same half-screen geometry and a shared linear AB24 buffer.

After the previously exercised primary-plane initialization at inherited 120 Hz
and then 72 Hz, an atomic `TEST_ONLY` request succeeds. One commit disables the
primary and enables both DMA planes without permitting a modeset. The mode
timings remain unchanged during that takeover, 400 green buffer samples pass,
and the complete software snapshot reports zero errors across 25 objects and
32 distinct blobs. DMA-plane cleanup and CRTC disable both succeed. A guarded
normal reboot returns to stock with Wi-Fi off and the updater disabled; no
firmware partition is written.

The owner is away for this native run. It therefore establishes native DMA
programming and cleanup, **not clean Linux output through the lenses**. The
GPU swapchain and VR compositor still need this scanout integration, followed
by patterned/stereo output, tracking and presentation-cadence verification.
See `state-route-v1/native-dma-v1/verified-manifest.json`, `analysis.json` and
`device-report.json`. The tested stripped native diagnostic SHA-256 is
`ab9e948a0d0e1015296e19c115ae136799b93279b1bdd12a782c6b01b781135c`.

## Retained source identity

Evidence directory: `output/pico-recovery-bringup-20261018-v1/`.
The initial source research was offline except for browsing primary sources.
The subsequent capture and takeover sections explicitly describe later builds
and device actions. Exact local references used for the source research:

| Retained file | Lines | SHA-256 |
|---|---|---|
| `drm-atomic-helper-current-reference-v1.c` | 2904–3015 | `50c0f7c81e19d31a91cb783bb9dcf30f5add69fda8b60a1fb55b4c89d8fe0b9b` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_encoder_phys_vid.c` | 1121–1152 | `d4b04c4f0b1705ee9ab0821259f7f91fe064bcc98ca68afa915131828ae9fbd9` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_plane.c` | 1364–1425 | `3060857a7d63709c459264cdb9c4d2d83162df6146c560916de2156443f17a7b` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_crtc.c` | 1497–1585 | `1eb5516ab702aee4107a2b3a74bab16c9b392a883d0a0d287fd1116a26d24bc7` |
