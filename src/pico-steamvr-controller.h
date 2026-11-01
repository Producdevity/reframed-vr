#ifndef REFRAMED_PICO_STEAMVR_CONTROLLER_H
#define REFRAMED_PICO_STEAMVR_CONTROLLER_H

#include "pico-controller-channel.h"
#include "pico-controller-haptics.h"
#include "pico-slam-channel.h"
#include <openvr_driver.h>
#include <mutex>

/* Trigger, grip, joystick x/y from raw bytes: 0 released, 255 pressed, stick
 * centre 128. Joystick +y is assumed up; values inside the radial dead zone are
 * zero and the remainder is rescaled to reach full deflection. */
void pico_steamvr_controller_analog(const pico_controller_sample &sample, float values[4]);

struct pico_steamvr_controller_tracking {
    const pico_slam_channel *channel = nullptr;
    uint64_t instance = 0, generation = 0, universe = 0;
    int64_t max_age_ns = 0;
};

class PicoSteamvrController final : public vr::ITrackedDeviceServerDriver {
    const pico_controller_channel *channel;
    const uint64_t instance;
    const unsigned hand;
    const pico_steamvr_controller_tracking tracking;
    std::mutex mutex;
    vr::TrackedDeviceIndex_t index = vr::k_unTrackedDeviceIndexInvalid;
    vr::VRInputComponentHandle_t inputs[12]{}, scalars[4]{}, haptic_component{};
    bool connected = false, values[12]{}, initialized[12]{}, scalar_initialized[4]{};
    float scalar_values[4]{};
    uint64_t updates = 0, changes = 0, failures = 0, input_calls = 0, haptic_requests = 0;
    void publish(const pico_controller_sample &sample, bool active);
    vr::DriverPose_t read_pose();
    vr::DriverPose_t read_pose(bool active);
public:
    PicoSteamvrController(const pico_controller_channel *channel, uint64_t instance, unsigned hand,
                          pico_steamvr_controller_tracking tracking = {});
    ~PicoSteamvrController();
    vr::EVRInitError Activate(uint32_t id) override;
    void Deactivate() override;
    void EnterStandby() override {}
    void *GetComponent(const char *) override { return nullptr; }
    void DebugRequest(const char *, char *, uint32_t) override;
    vr::DriverPose_t GetPose() override;
    void Update();
    /* Converts a vibration event for this controller's /output/haptic component. */
    bool haptic(const vr::VREvent_HapticVibration_t &event, pico_controller_haptic &request);
};

#endif
