# PicoFrame cross-reference

[PicoFrame](https://github.com/TheReal-Flo/PicoFrame) brings up SteamVR natively on
the Pico 4, which shares the XR2 (SM8250) platform and PICO's tracking libraries
with the Neo3 Pro Eye but uses a different kernel, panel, lenses and controller
generation. This records what its commit
[`42ea2b7`](https://github.com/TheReal-Flo/PicoFrame/commit/42ea2b787471f93d750a891e0410a5519b2123ec)
(2026-11-02) means for Reframed VR. Its code may be reused with permission;
nothing below was copied verbatim.

## Adopted

| Item | PicoFrame source | Here |
| --- | --- | --- |
| Distortion mesh resolution | `research/vrtiming/distortpass-notes.md`: the compositor's mesh defaults to 49×49 unless the driver sets `Prop_DistortionMeshResolution_Int32` | The driver requests 193×193, measured to keep the Neo3 lens model under 0.5 render pixels ([details](pico-steamvr.md#distortion-mesh-resolution)) |
| Vsync-to-photons time | `research/display-timing/notes.md`: PICO predicts to vsync plus a per-panel `TimeToHalfExposure` | Optional `screen.vsync_to_photons_ns` profile field; the Neo3 value still has to be read from stock ([details](pico-steamvr.md#vsync-to-photons-time)) |

## Confirmed by both projects

- libSlam's frame turns 90° about z into PICO's head frame (`x' = -y`,
  `y' = x`), which is the `world_from_slam` rotation used here.
- The head centre sits at `config_head.txt` line 1 from the IMU. PicoFrame calls
  `0.05412 0.01361 0.0537` another headset's fallback; it is the Neo3's own stock
  file and is already this project's `body_from_head`.
- Controller tracker positions are in millimetres in libSlam's world, with the
  same `algo_result_t` layout as the head.

## Worth testing on the Neo3

- **Controller result timestamps.** PicoFrame measured Pico 4 tracker results
  stamped about 33 ms after their arrival, i.e. already predicted ahead.
  Here, a result stamped later than its reading time is refused. No tracked
  Neo3 result has reached that check yet; the consumer's raw result recording
  (arrival time plus both results) will show the offset on the first tracked
  session.
- **Motion fields of the result.** Doubles `0x1c–0x1e` hold velocity,
  `0x1f–0x21` acceleration and `0x22–0x24` angular velocity; PICO's
  `getPredictResult` extrapolates with them. They could replace the opt-in
  finite-difference estimator once validated live, for example with
  PicoFrame's ratio of reported velocity to position difference.
- **Steam Frame UI settings.** The Frame's own `frame_hmd_additional.vrsettings`
  sets `steamMatchesHMDFramerate: false` and `omitDesktopWebhelpers: true`, which
  bear on the Steam UI's CPU cost here, and `overlayMips`/`overlayMipbias` and
  sharpening, which bear on text readability. Each needs a measured A/B.
- **Room setup.** Without a chaperone, SteamVR reports it uninitialized and
  OpenXR games misplace the floor. PicoFrame publishes a driver-provided
  chaperone and verified SteamVR's sign convention for its translations. This
  project's world origin is libSlam's start pose at head height, so it also
  needs a floor-height policy.
- **Relocalisation steps.** PicoFrame fades libSlam steps over 4 cm in over
  0.7 s instead of jumping. Whether the Neo3's fused pose shows such steps has
  not been observed.

## Not adopted

- `enableAchromaticDistortion`: it drops per-channel lens correction, which the
  Neo3's fresnel lenses need.
- 1504-pixel eye buffers: that is the Pico 4's stock value; the Neo3's own has
  not been read.
- Their IMU-fused head pose (gyro bias refinement, heading-drift correction) and
  controller heading alignment: this project consumes the vendor tracker's
  fused head pose and the controller SDK's orientation directly.
- Pico 4 audio, panel, device-tree and kernel configuration: different hardware
  and kernel.

## Later, for an installed image

Clock save and restore across boots, a battery guard that also acts on
"Not charging", Steam updater stubs, and the `pico-perf`/`vrtop` profiling tools.
