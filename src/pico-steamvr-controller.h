#ifndef REFRAMED_PICO_STEAMVR_CONTROLLER_H
#define REFRAMED_PICO_STEAMVR_CONTROLLER_H

#include "pico-controller-channel.h"
#include <openvr_driver.h>
#include <mutex>

class PicoSteamvrController final : public vr::ITrackedDeviceServerDriver {
    const pico_controller_channel *channel;
    const uint64_t instance;
    const unsigned hand;
    std::mutex mutex;
    vr::TrackedDeviceIndex_t index = vr::k_unTrackedDeviceIndexInvalid;
    vr::VRInputComponentHandle_t inputs[12]{};
    bool connected = false, values[12]{};
    uint64_t updates = 0, changes = 0, failures = 0;
    void publish(const pico_controller_sample &sample, bool active);
public:
    PicoSteamvrController(const pico_controller_channel *channel, uint64_t instance, unsigned hand);
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
