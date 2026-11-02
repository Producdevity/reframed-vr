# Pico native VR acceptance

Updated 2026-11-02. The owner confirms that this Neo3 Pro Eye has clean display,
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
| Visible modern Steam UI | UI-geometry v2 contains sign-in and toolbar in both later stable scanouts. The early capture precedes overlay visibility. Overlay transforms and opacity are recorded; the sampled overlay coordinate is not assumed to be its centre. | Verify repeatable startup and physical lens output. API texture visibility alone remains insufficient; the preceding skybox-only run is not retrospectively accepted. |
| Sharpness, colour and stereo/IPD | Owner reported poor lens clarity, coloured outlines and incorrect-feeling IPD. Radial/chromatic coefficients match stock getters, and callback maths matches the retained stock reference. That does not validate the full eye geometry. | Match stock's active per-eye origins, projection/FOV, optical offsets and IPD policy; verify neutral text/lines through both lenses and readable Steam text. An undistorted debug preview is not lens acceptance. |
| Head stability and frame pacing | Owner reports jitter while looking around. The [private fence-worker comparison and signal follow-up](pico-kgsl-fence-dispatch.md) establish lower dispatch tails but retain presentation misses, including late upstream queues and unresolved callback/selection intervals. It remains opt-in. Steady API probing was absent; stationary head data and bounded DRM checks do not establish motion quality. The pose adapter previously reported zero velocity, leaving SteamVR no basis to extrapolate to photon time; an opt-in finite-difference velocity estimator (`PICO_STEAMVR_PREDICT_VELOCITY=1`, see [driver setup](pico-steamvr.md)) now supplies linear/angular velocity, with the math validated offline. | Resolve the upstream and presentation-boundary delays; narrow the measured post-selection and fire-to-signal gaps before further scheduling changes. Verify steady API timing, timestamp alignment and prediction during motion, then sustained pacing under simultaneous tracking, controllers and UI load. Validate the live velocity fields' units, scale and timestamp alignment against the stock prediction reference before promoting the estimator to a default. |
| Controller 6DoF and pointing | Stock controller tracking works. Native radio/Home input and render models work. The SDK's tracked results are now published to SteamVR in the head's world (frame, millimetre units and model alignment established on-device; see [controller protocol](pico-controller-protocol.md#tracked-result-frame-and-render-model-alignment-2026-11-01)), with stock-derived aim/grip components, analog trigger/grip/stick values and a haptics route to the station. In every unattended recording the controllers lay still about 1.1 m away, beyond the SDK's 0.8 m initialization gate, so no optical pose has been acquired and nothing has been published. | Reproduce stock image/SDK initialization and pose conversion, publish fresh calibrated 6DoF with correct confidence/timestamps, render the attributed Neo3 model in the right hand location, and verify aim/grip, trigger, buttons, analog controls, loss and wake recovery. |
| Eye tracking and user calibration | No live eye-tracking stream or adaptive eye-origin/IPD updates are integrated in the Pico SteamVR driver. The stock service, its Tobii/CDSP dependencies and camera route are inventoried in [eye tracking](pico-eye-tracking.md). | Bring up the Neo3 Pro Eye eye-camera/SDK path with retained factory calibration; verify gaze origins/directions, validity, timing and calibration lifecycle against stock, then expose it to the runtime. |
| Foveated rendering | No accepted gaze-driven rendering path exists. | Verify capabilities of the actual Turnip/KGSL stack and compositor/application path, integrate calibrated low-age gaze, preserve central text quality and handle gaze loss. Measure GPU cost, latency and pacing against a full-quality baseline. Fixed foveation alone does not close gaze-driven support. |
| Wi-Fi and Bluetooth | Wi-Fi association, DHCP, DNS, HTTPS, reconnect and saved-profile restore pass, and Wi-Fi now runs inside the native VR session at about 210 Mbit/s while SteamVR renders. Bluetooth passes cold starts, power cycles and public GATT data. One Wi-Fi stop after a VR session hung on a kernel bus-scaling lock held by another task, wedging the unit until a physical power-off. See [wireless evidence](pico-native-wireless.md). | Validate NetworkManager activation, configured-network association, DHCP, discovery/pairing, traffic, Bluetooth audio and suspend/resume. Test powered radio coexistence with cameras, tracking and SteamVR, and sustained startup reliability. |
| Session lifecycle | An [attended session harness](pico-native-session.md) holds the full stack for a requested time; a 120 s hold completed and returned to verified stock. SteamVR stops by bounded unit termination with success results; no in-runtime quit exists because vrmonitor never connects to vrserver. One run's controller worker crashed during release and its later Wi-Fi stop hung the unit. | Establish graceful client/compositor/server shutdown ordering, capture actual final unit/process statuses, and verify repeatable startup/recovery without stale handles or crash dumps. |

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

The 2026-10-24 stock-code inspection starts Pro Eye lens separation at 63.4 mm
regardless of IPD state, before screen-gap correction. The new native measurement
confirms identity eye orientations, X origins at -/+31.7 mm, symmetric projection
tangents X -/+1.09130847 and Y -/+1.14372945, and a recommended 1832x1920 render
per eye. Those values match the deployed profile. Stock's *active* SDK projection,
eye-origin policy and optical offsets still need an independent comparison.

The fresh stock service dumps report automatic IPD disabled, an IPD getter value
of `6800`, and eye tracking switched off. The getter's units and relationship to
rendering are unverified; do not interpret it as a replacement virtual IPD. These
session flags do not negate the model's eye-tracking hardware capability.

## Capture and evidence boundary

The raw scanout is already RGB-pre-corrected for the lenses. The host
[rendering/preview guide](pico-rendering.md) explains why its coloured outlines
are not by themselves proof of an optical defect. The owner also saw poor
clarity through the lenses, so that physical failure remains open.

The paused double-read diagnostic removed interior bands in the earlier
optical-validation v3 skybox comparison. The subsequent
`output/pico-ui-geometry-20261024-v2/` run retains actual main-panel and toolbar
pixels in both eyes at two later captures. The final capture guard verifies that
its independent resume timer is still waiting and has not triggered. Two
identical full-buffer reads establish stable readback, not a proven coherent
rendered frame or physical optical alignment. The previous rejected attempts
remain separate records.

The preceding UI-geometry v1 feed ended at a camera age of 250.547 ms against
the existing 250 ms limit; the latest IMU was only 1.692 ms old. v2 completed all
4,499 camera sets under the same freshness policy. This establishes an
intermittent camera-delivery/processing deadline failure, not its full cause.
The SteamVR pose adapter currently supplies no linear or angular velocity; its
display-time prediction inputs need validation before treating stationary pose
success as motion-jitter acceptance.

A CPU-only oracle against the unchanged stock prediction library verifies that
its target time is absolute nanoseconds. Fifty synthetic calls also establish
the identity-orientation response of its motion fields, including a 0.01-radian
rotation for a unit angular input over 10 ms. This is function-level evidence,
not validation of live raw-field units, moving-head coordinate frames or final
head-origin velocities. The linear response requires further scale validation;
no unverified motion fields were enabled. Evidence is
`output/pico-prediction-oracle-20261024-v1/`.

Controller ownership in v2 completes 4,445 image sets with no drops, but still
publishes zero confident optical controller poses. The missing-right-calibration
warning also occurs in the successful synthetic SDK initialization control, so
that warning alone cannot explain left-controller acquisition failure. Keep the
stock/native image, IMU and head-frame comparison open.

Continue with software measurements while the owner is away. Physical text,
stereo comfort, head-motion and controller aim/grip acceptance remain pending
until a live lens/motion check is possible. Preserve recovery/calibration data,
keep audio quiet, and commit only the verified scope of each change.

Related implementation records: [SteamVR driver](pico-steamvr.md),
[controller protocol](pico-controller-protocol.md),
[UI session](pico-steamvr-ui.md), and
[hardware verification](pico-steamvr-verification.md).
