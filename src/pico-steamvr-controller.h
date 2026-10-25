#ifndef REFRAMED_PICO_STEAMVR_CONTROLLER_H
#define REFRAMED_PICO_STEAMVR_CONTROLLER_H

#include "pico-controller-channel.h"
#include "pico-slam-channel.h"
#include <openvr_driver.h>
#include <mutex>

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
    vr::VRInputComponentHandle_t inputs[12]{};
    bool connected = false, values[12]{}, initialized[12]{};
    uint64_t updates = 0, changes = 0, failures = 0, input_calls = 0;
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
};

#endif
