# Pico native VR acceptance

Updated 2026-10-24. The owner confirms that this Neo3 Pro Eye has clean display,
head tracking and controller tracking in stock Pico Android. Stock is the
working reference. The physical clarity, jitter and controller failures reported
below are Reframed software acceptance failures; do not repeat hardware-fault
questions without new contrary evidence.

The target is a usable native Linux Steam VR session with calibrated stereo,
readable text, stable head tracking, visible tracked controllers and responsive
pointing. Runtime startup, valid API textures, button reports and model loading
are intermediate checks. None substitutes for that complete experience.

## Required work

| Area | Current evidence / gap | Acceptance required |
| --- | --- | --- |
| Visible modern Steam UI | The earlier v7 scanout contains sign-in and toolbar. The latest optical-validation v3 boot has valid/visible main and bar API textures, but both early captures contain only the skybox. | Verify actual panel content and its placement in the head view; capture the late UI and overlay/head transforms. Keep visibility failures open despite successful API probes. |
| Sharpness, colour and stereo/IPD | Owner reported poor lens clarity, coloured outlines and incorrect-feeling IPD. Radial/chromatic coefficients match stock getters, and callback maths matches the retained stock reference. That does not validate the full eye geometry. | Match stock's active per-eye origins, projection/FOV, optical offsets and IPD policy; verify neutral text/lines through both lenses and readable Steam text. An undistorted debug preview is not lens acceptance. |
| Head stability and frame pacing | Owner reports jitter while looking around. Latest stationary probes have 9,000 valid head samples, but one overdue vsync-age query and 168 reported drops in 8,309 sampled frame indices. | Correlate camera/IMU timestamps, pose prediction and contention with compositor submits/presents during motion. Verify room-fixed UI without visible jitter and sustained frame pacing under simultaneous tracking, controllers and UI load. |
| Controller 6DoF and pointing | Stock controller tracking works. Native radio/Home input and static render-model loading have worked; valid optical poses, visible controller placement and pointing remain missing. | Reproduce stock image/SDK initialization and pose conversion, publish fresh calibrated 6DoF with correct confidence/timestamps, render the attributed Neo3 model in the right hand location, and verify aim/grip, trigger, buttons, analog controls, loss and wake recovery. |
| Eye tracking and user calibration | No live eye-tracking stream or adaptive eye-origin/IPD updates are integrated in the Pico SteamVR driver. | Bring up the Neo3 Pro Eye eye-camera/SDK path with retained factory calibration; verify gaze origins/directions, validity, timing and calibration lifecycle against stock, then expose it to the runtime. |
| Foveated rendering | No accepted gaze-driven rendering path exists. | Verify capabilities of the actual Turnip/KGSL stack and compositor/application path, integrate calibrated low-age gaze, preserve central text quality and handle gaze loss. Measure GPU cost, latency and pacing against a full-quality baseline. Fixed foveation alone does not close gaze-driven support. |

## IPD model boundary

PICO's [Neo3 Pro Eye specifications](https://www.picoxr.com/global/products/neo3-pro-eye/specs)
distinguish this model from the ordinary Neo3 Pro: the Pro Eye has no physical
lens-spacing adjustment and advertises optical adaptation over 55–71 mm. It has
two eye-tracking cameras. This is not evidence that eye tracking automatically
updates the stock renderer's IPD; that relationship must be traced on this
firmware rather than inferred from a different PICO model.

The currently deployed profile's two static eye poses are approximately
63.4 mm apart. `pico-steamvr-driver.cpp` publishes the profile-derived IPD at
activation; it has no live eye-tracking update path. Preserve the distinction
between physical lens separation, the user's pupil distance, eye-to-head poses,
projection centres and distortion centres. Changing one scalar is not a verified
replacement for stock calibration.

## Capture and evidence boundary

The raw scanout is already RGB-pre-corrected for the lenses. The host
[rendering/preview guide](pico-rendering.md) explains why its coloured outlines
are not by themselves proof of an optical defect. The owner also saw poor
clarity through the lenses, so that physical failure remains open.

The paused double-read diagnostic removes the interior bands present in its
paired unpaused skybox capture. Both records lack the Steam panel in the stored
pixels even though overlay APIs report it visible. Treat this as capture
stability evidence, not Steam UI visibility or correct IPD. Latest evidence is
`output/pico-optics-validation-20261024-v3/`; the earlier v7 UI pixels and the two
rejected attempts are retained separately.

Continue with software measurements while the owner is away. Physical text,
stereo comfort, head-motion and controller aim/grip acceptance remain pending
until a live lens/motion check is possible. Preserve recovery/calibration data,
keep audio quiet, and commit only the verified scope of each change.

Related implementation records: [SteamVR driver](pico-steamvr.md),
[controller protocol](pico-controller-protocol.md),
[UI session](pico-steamvr-ui.md), and
[hardware verification](pico-steamvr-verification.md).
