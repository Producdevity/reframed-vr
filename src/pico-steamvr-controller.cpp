#include "pico-steamvr-controller.h"
#include "pico-steamvr-pose.h"
#include <cstdio>
#include <ctime>

static int64_t monotonic_ns(void *)
{
    timespec t{};
    return clock_gettime(CLOCK_MONOTONIC, &t) ? 0 :
        static_cast<int64_t>(t.tv_sec) * 1000000000 + t.tv_nsec;
}

PicoSteamvrController::PicoSteamvrController(const pico_controller_channel *c, uint64_t i, unsigned h,
                                             pico_steamvr_controller_tracking t)
    : channel(c), instance(i), hand(h), tracking(t) {}

PicoSteamvrController::~PicoSteamvrController() { Deactivate(); }

vr::EVRInitError PicoSteamvrController::Activate(uint32_t id)
{
    std::lock_guard<std::mutex> lock(mutex);
    if (index != vr::k_unTrackedDeviceIndexInvalid || hand < 1 || hand > 2)
        return vr::VRInitError_Driver_Failed;
    if (tracking.channel ? (!tracking.instance || !tracking.generation || !tracking.universe ||
        tracking.instance == tracking.universe || tracking.max_age_ns <= 0 || tracking.max_age_ns > 100000000) :
        (tracking.instance || tracking.generation || tracking.universe || tracking.max_age_ns))
        return vr::VRInitError_Driver_Failed;
    auto *properties = vr::VRProperties();
    auto container = properties->TrackedDeviceToPropertyContainer(id);
    bool ok = true;
    auto string = [&](vr::ETrackedDeviceProperty p, const char *v) {
        ok = (properties->SetStringProperty(container, p, v) == vr::TrackedProp_Success) && ok;
    };
    string(vr::Prop_TrackingSystemName_String, "reframed_pico");
    string(vr::Prop_ModelNumber_String, "Pico Neo3 controller");
    string(vr::Prop_ManufacturerName_String, "PICO");
    string(vr::Prop_ControllerType_String, "reframed_pico_neo3");
    string(vr::Prop_RenderModelName_String, hand == 1 ? "{reframed_pico}neo3_left" : "{reframed_pico}neo3_right");
    string(vr::Prop_InputProfilePath_String, "{reframed_pico}/input/neo3_profile.json");
    ok = (properties->SetInt32Property(container, vr::Prop_ControllerRoleHint_Int32,
        hand == 1 ? vr::TrackedControllerRole_LeftHand : vr::TrackedControllerRole_RightHand)
        == vr::TrackedProp_Success) && ok;
    ok = (properties->SetBoolProperty(container, vr::Prop_DeviceIsWireless_Bool, true)
        == vr::TrackedProp_Success) && ok;
    if (tracking.channel)
        ok = (properties->SetUint64Property(container, vr::Prop_CurrentUniverseId_Uint64, tracking.universe)
            == vr::TrackedProp_Success) && ok;
    const char *paths[12] = {
        "/input/system/click", "/input/application_menu/click",
        hand == 1 ? "/input/x/click" : "/input/a/click",
        hand == 1 ? "/input/y/click" : "/input/b/click",
        "/input/grip/click", "/input/joystick/click", "/input/trigger/click",
        hand == 1 ? "/input/x/touch" : "/input/a/touch",
        hand == 1 ? "/input/y/touch" : "/input/b/touch",
        "/input/joystick/touch", "/input/thumbrest/touch", "/input/trigger/touch"};
    for (unsigned i = 0; i < 12; i++)
        ok = (vr::VRDriverInput()->CreateBooleanComponent(container, paths[i], &inputs[i])
              == vr::VRInputError_None) && ok;
    if (!ok) return vr::VRInitError_Driver_Failed;
    index = id;
    vr::VRDriverLog()->Log("Reframed Neo3 controller: live digital inputs; pose requires a bound fresh tracking channel");
    return vr::VRInitError_None;
}

void PicoSteamvrController::publish(const pico_controller_sample &sample, bool active)
{
    static const unsigned masks[12] = {1, 2, 4, 8, 16, 32, 128, 1, 2, 4, 8, 16};
    bool failed = false;
    for (unsigned i = 0; i < 12; i++) {
        bool next = active && ((i < 7 ? sample.buttons : sample.touches) & masks[i]);
        if (vr::VRDriverInput()->UpdateBooleanComponent(inputs[i], next, 0) != vr::VRInputError_None) {
            failures++;
            failed = true;
        } else {
            changes += next != values[i];
            values[i] = next;
        }
    }
    connected = active && !failed;
    if (failed && active) publish({}, false);
}

void PicoSteamvrController::Update()
{
    std::lock_guard<std::mutex> lock(mutex);
    if (index == vr::k_unTrackedDeviceIndexInvalid) return;
    pico_controller_sample sample{};
    bool active = pico_controller_channel_read(channel, instance, hand, monotonic_ns, nullptr,
                                               250000000, &sample);
    publish(sample, active);
    updates++;
    auto pose = read_pose();
    vr::VRServerDriverHost()->TrackedDevicePoseUpdated(index, pose, sizeof(pose));
}

void PicoSteamvrController::Deactivate()
{
    std::lock_guard<std::mutex> lock(mutex);
    if (index != vr::k_unTrackedDeviceIndexInvalid) publish({}, false);
    index = vr::k_unTrackedDeviceIndexInvalid;
}

vr::DriverPose_t PicoSteamvrController::GetPose()
{
    std::lock_guard<std::mutex> lock(mutex);
    return read_pose();
}

vr::DriverPose_t PicoSteamvrController::read_pose()
{
    pico_controller_sample sample{};
    bool active = connected && index != vr::k_unTrackedDeviceIndexInvalid &&
        pico_controller_channel_read(channel, instance, hand, monotonic_ns, nullptr, 250000000, &sample);
    if (tracking.channel)
        return pico_steamvr_pose_now(tracking.channel, tracking.instance, tracking.generation,
            tracking.max_age_ns, active, monotonic_ns, nullptr, nullptr);
    vr::DriverPose_t pose{};
    pose.qWorldFromDriverRotation.w = pose.qDriverFromHeadRotation.w = pose.qRotation.w = 1;
    pose.deviceIsConnected = active;
    pose.result = vr::TrackingResult_Uninitialized;
    return pose;
}

void PicoSteamvrController::DebugRequest(const char *, char *response, uint32_t size)
{
    if (!size) return;
    std::lock_guard<std::mutex> lock(mutex);
    auto pose = read_pose();
    std::snprintf(response, size, "PICO_CONTROLLER_INPUT hand=%u connected=%d updates=%llu changes=%llu failures=%llu pose_valid=%d",
        hand, connected, static_cast<unsigned long long>(updates),
        static_cast<unsigned long long>(changes), static_cast<unsigned long long>(failures), pose.poseIsValid);
}
