# Native Steam VR UI on the Pico Neo3

The maintained opt-in launcher is [`tools/steamvr-gamepadui.sh`](../tools/steamvr-gamepadui.sh).
It launches Steam's native VR Gamepad UI through gamescope's VR session manager.
The main panel and toolbar are separate Steam-owned overlays; the desktop
fallback is not sufficient evidence that either works.

## Session requirements

Prepare the native ARM64 SteamVR compositor, Pico display driver, calibrated
head tracking and runtime environment described in [driver setup](pico-steamvr.md).
Use the opt-in [`pico-steamvr-ui-90hz.json`](../profiles/pico-steamvr-ui-90hz.json)
settings, both [gamescope patches](../patches/gamescope/README.md), and
`gamescope_vr_use_modifiers=false`. The UI profile enables Steam overlays and VR
Gamepad UI forwarding; it leaves the base Pico profile unchanged.

Gamescope's session manager requires an input seat. In the bounded RAM test,
seatd ran with `SEATD_VTBOUND=0`, a socket owned by the session user/group, and
mode `0770`; gamescope used `LIBSEAT_BACKEND=seatd`. A normal installed session
may instead provide a suitable logind seat. The UI launcher assumes that the
seat and compositor already exist. It does not boot Linux, start tracking,
change audio levels or install device services.

Within that prepared session:

```sh
export VR_OVERRIDE=/opt/reframed-vr/steamvr
export gamescope_vr_use_modifiers=false
export LIBSEAT_BACKEND=seatd
export LIBGL_ALWAYS_SOFTWARE=1
/path/to/reframed-vr/tools/steamvr-gamepadui.sh -cef-disable-gpu
```

`REFRAMED_GAMESCOPE_BIN` can select the privately built patched gamescope binary.
The launcher defaults to the ARM64 runtime above and refuses a missing native
`vrclient.so`. Steam receives `-gamepadui -vrgamepadui`, without `-vrdisable`.
Gamescope uses `--vr-session-manager`, `PerAppId`, two Xwayland servers,
`valve.steam.gamepadui.fallback`, and `valve.steam.desktopgame`. These launch
contracts were adapted from Valve's `/usr/share/deckard/RUNSTEAM.sh` and
`/usr/lib/steamos/gamescope-session`, read from the official
[Frame repair image](https://steamdeck-images.steamos.cloud/recovery/steamframe-oobe-repair-20260922.5153644-0.3.0.img.zip).
The vendor scripts were used as reference and were not executed on the Pico.
Gamescope's upstream license and copyright are retained with the patches.

## Cause of the old UI

The previous diagnostic session explicitly disabled Steam's native VR UI and
displayed a flat Gamepad window under `reframed.pico.steam`. Changing dashboard
settings alone did not fix it. Enabling the Frame session contract first exposed
the missing input seat, then a separate texture-forwarding failure.

With modifiers disabled, gamescope's ordinary overlay path uses Vulkan textures.
Its native VR-panel forwarding path still required a DMA import that this mode
rejects. The second gamescope patch forwards those panels using the existing
Vulkan transport. The live probe now lists main, bar and fallback separately,
and rejects a selected panel that is missing, inactive, hidden or textureless,
including when frame-history reporting is enabled.

The test uses Frame-derived Steam components and SteamVR 2.17.10 on the native
Fedora 44 diagnostic root. It is not a complete Frame OS installation, and this
change does not update the pinned Steam or SteamVR packages. Those packages
already contain the modern VR UI. Software browser rendering remains a
compatibility setting; a CPU/GPU optimization pass is still needed.

## Acceptance boundaries

Hardware evidence and frame-timing results are recorded in
[the verification record](pico-steamvr-verification.md#native-steam-vr-ui-2026-10-24).
Require both `valve.steam.gamepadui.main` and `valve.steam.gamepadui.bar` to have
valid, visible textures. Verify captured scanout pixels as well as the API
results. A hidden fallback is expected when the native UI owns presentation.

The current offline sign-in scene does not establish a signed-in library,
controller interaction, physical text clarity or end-to-end latency. Controller
optical acquisition remains a separate open issue. A scanout capture is not a
coherent single-frame or through-lens measurement.

The [rendering and capture guide](pico-rendering.md) explains the Vulkan,
KGSL and DRM/KMS path, the raw panel's RGB pre-correction, and the host-side
undistorted preview. Use that preview when inspecting UI content on a monitor.
