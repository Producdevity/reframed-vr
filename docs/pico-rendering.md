# Pico rendering and scanout captures

The tested Neo3 native Linux session uses Valve's ARM64 Steam client and SteamVR
compositor. Steam's browser currently renders the UI in software, sending shared
memory buffers through Xwayland. The patched gamescope uploads those buffers
and forwards native VR UI panels as Vulkan textures to SteamVR.

SteamVR's Facet compositor draws the stereoscopic scene, places the overlays,
applies the Pico driver's per-eye projection and RGB lens correction, and
submits the panel image through Vulkan. Mesa Turnip executes the GPU work on
Adreno 650 through Qualcomm's KGSL kernel interface. The Vulkan display path
uses DRM/KMS to configure and present the shared 1920×3664 framebuffer through
the display controller's two DMA planes and the DSI links. DRM/KMS handles
display ownership, modes and scanout; Vulkan and the compositor perform the
rendering. This is the direct-display path, without a desktop framebuffer copy.

## Why raw panel pixels have coloured outlines

[`ComputeDistortion`](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md)
supplies separate source coordinates for red, green and blue. The panel image
is pre-corrected for the lenses' geometric distortion and chromatic aberration.
A raw scanout capture therefore contains displaced colour edges before light
passes through the lenses. A normal monitor displaying those bytes does not
apply the headset's optical transformation.

The 2026-10-24 sign-in crop has measured red/green displacement of approximately
−2 pixels and blue/green displacement of +4 pixels horizontally. The deployed
profile predicts −1.76 and +3.58 pixels at the sampled location. Each isolated
channel contains one glyph; this sample does not show repeated temporal images
within a channel. Motion smoothing was disabled in that session.

A fresh read of the b1977 stock optical getters matches both deployed eyes'
radial and chromatic coefficients exactly. The current SteamVR callback was
also compared with retained stock mesh/GLES-shader outputs: 17,136 points,
102,816 RGB coordinate components, maximum visible coordinate difference
0.00051 pixels at a 1920-pixel reference dimension. These reference cases use
synthetic resolved geometry; they do not establish the active stock renderer's
complete settings or correct physical lens alignment. Evidence remains in
`output/pico-optics-validation-20261024-v1/`.

Colour fringes in raw panel bytes alone are not a reason to remove the display
driver's chromatic correction. Fringes through the lenses would require a
separate check of the active calibration, geometry and physical alignment.

## Human-readable preview

Use the host-side preview tool with the exact optical profile retained from
the captured session. It verifies the raw size/hash, layout and headset serial,
then numerically inverts each colour channel's configured lens mapping:

```sh
python3 tools/preview-pico-scanout.py \
  --capture /path/to/export/scanout \
  --optics /path/to/export/neo3-optics.json \
  --output /path/to/new-preview
```

It requires NumPy and Pillow, reads saved files only, and produces:

- `panel-stereo.png`: rotated raw panel pixels, with the pre-correction intact.
- `undistorted-stereo.png`: resampled per-eye views with that mapping undone.
- `preview.json`: source hashes, inverse-solver residuals, coverage and output hashes.

The default output is 916×960 per eye; `--eye-width 1832` selects the native
internal-layer dimensions. Out-of-panel or unconverged samples become black.
The preview preserves existing black seams and other defects; it does not
repair missing pixels. It is a reconstructed diagnostic view, not measured
through-lens sharpness or a new rendering result.

The original capture copied the live framebuffer over 47.85 ms. DMA-buffer CPU
read synchronization was used, but a coherent single frame was not established.
Reconstruction cannot remove this uncertainty. Frame pacing, physical clarity
and the remaining black seams require separate acceptance; see the
[verification record](pico-steamvr-verification.md#native-steam-vr-ui-2026-10-24).
