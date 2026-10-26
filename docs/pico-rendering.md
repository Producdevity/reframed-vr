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

## GPU completion reuse

The opt-in `TU_KGSL_DRM_SYNC` bridge exports a GPU timestamp once and imports
that completion into the requested DRM signal objects. An ensuing empty queue
submission still depends on the last GPU timestamp. Re-exporting that timestamp
registers another KGSL callback, even though its completion was already exported.

Turnip patch `0021-kgsl-drm-completion-cache.patch` retains one queue-owned
CLOEXEC descriptor for a pure GPU completion. Empty submissions with signals
can merge that cached completion with every explicit wait. Merged completions
are never cached as pure timestamps. Every successful GPU or sparse submission
invalidates the old cache, including submissions without signals; queue teardown
closes it after the submit thread has joined. Native synchronization outside the
DRM bridge retains its original path.

Cache population is optional. A failed cached merge releases the cache and
retries once with the original timestamp dependency. The bridge moves its
private FD completion rather than duplicating it again. Empty submissions with
no waits or signals do not allocate a completion descriptor. The cache
intentionally costs one resident descriptor per queue; it does not guarantee
identical behavior under an identical absolute process descriptor limit.

The composed actual-function fixture checks dependencies, lifecycle, failures
and real descriptor limits. Hardware callback counts, complete tracking load and
remaining missed refreshes are recorded separately in the
[verification record](pico-steamvr-verification.md). Reducing callback traffic
does not establish physical frame pacing or eliminate all deadline failures.

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
Reconstruction cannot remove this uncertainty.

For a stable diagnostic snapshot in a prepared native Pico session, the
capture tool accepts an explicit compositor unit:

```sh
python3 tools/capture-pico-scanout.py \
  --boot-serial c980c8d4 --boot-id CURRENT_NATIVE_BOOT_UUID \
  --output /run/pico-stable-scanout \
  --pause-compositor-unit pico-steamvr-compositor-controller-render-v1
```

It arms an independent three-second resume timer, pauses the selected compositor
unit, waits 100 ms, and requires two identical framebuffer readbacks with the
same active planes. It also checks the unit's identity and that the timer has
not expired, then resumes the compositor in a `finally` block. Capture failures
also resume it; a failed resume leaves the watchdog armed. The option briefly
freezes the view, so exclude it and its frame-history tail from pacing tests.

Successful metadata records `stable_readback_verified=true` separately from
`coherent_single_frame_verified`, which remains false: no GPU completion-fence
or through-lens measurement is inferred from matching CPU reads. The default
capture continues without a compositor pause. Frame pacing and physical clarity
still require separate acceptance; see the
[verification record](pico-steamvr-verification.md#native-steam-vr-ui-2026-10-24).

In the native optical-validation v3 comparison, the unpaused read contains
interior black bands at rows 1285–1311 and 3155–3174. The paused capture has two
identical complete-buffer reads and neither interior band; the outer viewport
masking remains. Both early captures contain only the skybox. This validates
the readback-stability option for that scene, not visible Steam panel content.
The [VR acceptance checklist](pico-vr-acceptance.md) keeps visibility, physical
IPD/clarity, jitter, controllers, eye tracking and foveation open.

The subsequent UI-geometry v2 run captures the modern sign-in panel and toolbar
in both eyes at two later stable readbacks. Its early capture precedes overlay
visibility. It also exercises the final waiting/untriggered resume-timer guard.
This establishes stored UI pixels for that run; it does not explain the previous
run's missing panel or establish through-lens sharpness and stereo comfort.
