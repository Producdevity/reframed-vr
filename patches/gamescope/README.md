# gamescope compatibility patches

These opt-in patches target Valve's gamescope 3.16.29, commit
`8f212644c46460549035971ab914421180f61a7c`. The pinned source package,
Fedora patches, input/output source hashes, build options and measured ARM64
binary hashes are in [`profiles/gamescope.json`](../../profiles/gamescope.json).
The accompanying `LICENSE` preserves upstream's copyright and license notices.
Valve's gamescope is the original work; the upload and VR forwarding changes
are local to Reframed.

## Shared-memory uploads

`import_commit()` memoizes a Vulkan texture by `wlr_buffer`. DMA-BUF imports
refer to shared storage, but the shared-memory path uploads a pixel snapshot.
Xwayland reuses its `wl_shm` buffers with new contents. Reusing the memoized
snapshot therefore presents stale pixels. The patch memoizes only DMA-BUF
imports and creates a fresh upload for each shared-memory commit. It does not
overwrite a texture still referenced by another commit.

The hardware comparison uses the Fedora 44 source RPM from the profile, its
three listed distribution patches and its supplied reshade/vkroots sources.
Prepare that source with the RPM spec's `%prep` stage on ARM64 Fedora with its
build dependencies. Verify `src/steamcompmgr.cpp` against `before_sha256`, then
apply the local patch from that source directory:

```sh
patch --dry-run -p1 < /path/to/reframed-vr/patches/gamescope/0001-refresh-shared-memory-uploads.patch
patch -p1 < /path/to/reframed-vr/patches/gamescope/0001-refresh-shared-memory-uploads.patch
```

Verify the result against `after_sha256`. Configure a new Meson build directory
with the profile's `meson_options`, then run `ninja -C BUILD -j4 src/gamescope`.
The diagnostic build used the distribution's system wlroots, stb and glm.
Dependency/toolchain changes may change binary hashes; retain a build manifest.
This recipe does not install or enable the binary. Keep the control binary and
run the candidate from a private session path for comparison.

The Fedora source package supplies `pkgconfig/stb.pc`. Include that directory
when configuring the build:

```sh
export PKG_CONFIG_PATH="$PWD/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
```

The unmodified rebuild retained Steam's initial loading logo while the client
had reached login. The patched rebuild rendered the login form into the Pico's
stereo scanout. See the [hardware record](../../docs/pico-steamvr-verification.md)
for evidence and remaining tracking, interaction and timing limits. This is a
software browser-upload compatibility path, not evidence that wl_shm is the
desired final high-performance rendering path.

On the measured Neo3 stack, pair the patched binary with
`gamescope_vr_use_modifiers=false` and `--force-composition`. Fresh shared-memory
uploads otherwise create per-buffer DMA imports whose storage remains held in
the compositor. Selecting gamescope's existing Vulkan overlay transport avoids
that measured growth. The opt-in service environment is bundled as
[`gamescope.conf`](../../system/steamvr-pico/gamescope.conf); it applies to the
gamescope service, separately from Valve's compositor service. This is a tested
transport workaround, not a claim that all DMA-BUF presentation is defective.

## Native VR UI forwarding

Apply `0002-forward-vulkan-ui-textures.patch` after `0001`. Its five input/output
source hashes, patch hash and measured ARM64 binary hash are recorded separately
as `ui_forwarding_patch` and `diagnostic_artifacts.ui_forwarding_sha256` in the
profile. Use the same Meson options and build procedure above.

The original forwarding path always imports a shared DMA texture, even when
`gamescope_vr_use_modifiers=false` makes that import unavailable. Ordinary
overlays already use Vulkan textures in this mode, but Steam's native VR panels
therefore remain without a valid texture. The second patch uses the same Vulkan
transport for forwarded panels, supplies transfer-source image usage, retains
queued/visible textures through the page flip, and retries a rejected texture
submission. It preserves the shared-texture path when modifiers are enabled.

The native main panel and toolbar were tested on the Pico with modifiers
disabled. The modifier-enabled branch compiled but was not hardware-tested in
this change. No extra CPU readback is introduced by forwarding; Steam's current
software-browser/shared-memory compatibility path remains. See
[native VR UI setup and acceptance](../../docs/pico-steamvr-ui.md).

## Non-Steam windows without DMA imports

Apply `0003-compose-nonsteam-without-dma.patch` after `0002`; its source and
binary hashes are `nonsteam_composition_patch` and
`diagnostic_artifacts.nonsteam_composition_sha256` in the profile. It uses the
same builder and Meson options.

The connector forces full composition when modifiers are disabled, but an
explicit non-Steam window overrides that decision. Its individual layers then
reach a subview presentation path that requires DMA imports and asserts in
Vulkan-only mode. A native startup reproduced this abort before the Steam main
panel appeared. The third patch keeps full composition for those windows when
DMA imports are unavailable, preserving their existing policy when modifiers
are enabled. This fixes a presentation prerequisite; it does not alter the Pico
optical calibration.

The rebuilt candidate survived native startup and the three late main/bar API
probes in `output/pico-optics-validation-20261024-v3/`. Its early pixel captures
contain only the skybox, so this is startup/API acceptance, not renewed visible
Steam UI acceptance. See the [rendering and capture guide](../../docs/pico-rendering.md).

## Forwarded Vulkan image layout

Apply `0004-transition-forwarded-overlay-images.patch` after `0003`; the profile
records `overlay_layout_patch` and `diagnostic_artifacts.overlay_layout_sha256`.
[OpenVR's Vulkan contract](https://github.com/ValveSoftware/openvr/wiki/Vulkan)
requires submitted images in `TRANSFER_SRC_OPTIMAL`, with transfer-source and
sampled usage. The forwarded surface uploads remain in `GENERAL`; adding usage
flags in `0002` does not transition them.

The fourth patch copies each changed forwarded texture into a local output
image and completes the existing command-buffer submission before handing it
to SteamVR. Gamescope's output-image barrier selects the backend's presentation
layout. The source retains its existing sampling and external queue ownership
rules. A pool of at most four images per plane follows the composite-target
pattern and retains queued/visible references across page flips; exhaustion
leaves forwarding pending. The modifier-enabled path is unchanged.

This adds a GPU copy, with no CPU pixel readback. A bounded native Pico run
exercises the new path and stores the modern main panel and toolbar in both
eyes. Late frame pacing remains imperfect; the single stationary run does not
establish a performance improvement, physical clarity or motion latency.
See `output/pico-overlay-layout-20261024-v1/` and the
[verification record](../../docs/pico-steamvr-verification.md).
