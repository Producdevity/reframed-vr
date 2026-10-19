# Neo3 direct-display research, October 19

## Decision

Pause parameter changes. Compare the complete working stock composition and
display routing with the first corrupted direct takeover before selecting another
fix. The cause remains unproven. Changing VR runtime cannot explain a fault
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
This is a proposal; it has not been implemented or run by this research task.

## Retained source identity

Evidence directory: `output/pico-recovery-bringup-20261018-v1/`.
The research was offline except for browsing primary sources; no builds or
device actions were performed. Exact local references used above:

| Retained file | Lines | SHA-256 |
|---|---|---|
| `drm-atomic-helper-current-reference-v1.c` | 2904–3015 | `50c0f7c81e19d31a91cb783bb9dcf30f5add69fda8b60a1fb55b4c89d8fe0b9b` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_encoder_phys_vid.c` | 1121–1152 | `d4b04c4f0b1705ee9ab0821259f7f91fe064bcc98ca68afa915131828ae9fbd9` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_plane.c` | 1364–1425 | `3060857a7d63709c459264cdb9c4d2d83162df6146c560916de2156443f17a7b` |
| `panel-noise-source-v1/techpack/display/msm/sde/sde_crtc.c` | 1497–1585 | `1eb5516ab702aee4107a2b3a74bab16c9b392a883d0a0d287fd1116a26d24bc7` |
