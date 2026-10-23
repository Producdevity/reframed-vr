#include "pico-steamvr-controller.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <ctime>
#include <map>
#include <string>
#include <thread>
#include <chrono>
using namespace vr;
struct MockIVRProperties final : IVRProperties {
    int32_t role = 0;
    std::string model;
    ETrackedPropertyError ReadPropertyBatch(PropertyContainerHandle_t ulContainerHandle,
                                            PropertyRead_t *pBatch, uint32_t unBatchEntryCount) override
    {
        assert(false);
        return TrackedProp_UnknownProperty;
    }
    ETrackedPropertyError WritePropertyBatch(PropertyContainerHandle_t ulContainerHandle,
                                             PropertyWrite_t *pBatch,
                                             uint32_t unBatchEntryCount) override
    {
        for (uint32_t i = 0; i < unBatchEntryCount; i++) {
            pBatch[i].eError = TrackedProp_Success;
            if (pBatch[i].prop == Prop_ControllerRoleHint_Int32)
                std::memcpy(&role, pBatch[i].pvBuffer, sizeof(role));
            if (pBatch[i].prop == Prop_RenderModelName_String)
                model = static_cast<const char *>(pBatch[i].pvBuffer);
        }
        return TrackedProp_Success;
    }
    const char *GetPropErrorNameFromEnum(ETrackedPropertyError error) override { return "mock"; }
    PropertyContainerHandle_t TrackedDeviceToPropertyContainer(TrackedDeviceIndex_t nDevice) override
    {
        return 10 + nDevice;
    }
};
struct MockIVRDriverInput final : IVRDriverInput {
    std::map<uint64_t, std::string> names;
    std::map<std::string, bool> values;
    bool fail_create = false, fail_update = false;
    pico_controller_channel *invalidate = nullptr;
    EVRInputError CreateBooleanComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                         VRInputComponentHandle_t *pHandle) override
    {
        if (fail_create)
            return VRInputError_InvalidParam;
        *pHandle = names.size() + 1;
        names[*pHandle] = pchName;
        values[pchName] = false;
        return VRInputError_None;
    }
    EVRInputError UpdateBooleanComponent(VRInputComponentHandle_t ulComponent, bool bNewValue,
                                         double fTimeOffset) override
    {
        assert(fTimeOffset == 0 && names.count(ulComponent));
        if (invalidate) {assert(pico_controller_channel_disconnect(invalidate,1));invalidate=nullptr;}
        if (fail_update) {
            fail_update = false;
            return VRInputError_InvalidParam;
        }
        values[names.at(ulComponent)] = bNewValue;
        return VRInputError_None;
    }
    EVRInputError CreateScalarComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                        VRInputComponentHandle_t *pHandle, EVRScalarType eType,
                                        EVRScalarUnits eUnits) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError UpdateScalarComponent(VRInputComponentHandle_t ulComponent, float fNewValue,
                                        double fTimeOffset) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError CreateHapticComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                        VRInputComponentHandle_t *pHandle) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError CreateSkeletonComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                          const char *pchSkeletonPath, const char *pchBasePosePath,
                                          EVRSkeletalTrackingLevel eSkeletalTrackingLevel,
                                          const VRBoneTransform_t *pGripLimitTransforms,
                                          uint32_t unGripLimitTransformCount,
                                          VRInputComponentHandle_t *pHandle) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError UpdateSkeletonComponent(VRInputComponentHandle_t ulComponent,
                                          EVRSkeletalMotionRange eMotionRange,
                                          const VRBoneTransform_t *pTransforms,
                                          uint32_t unTransformCount) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError CreatePoseComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                      VRInputComponentHandle_t *pHandle) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError UpdatePoseComponent(VRInputComponentHandle_t ulComponent,
                                      const HmdMatrix34_t *pMatPoseOffset, double fTimeOffset) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError CreateEyeTrackingComponent(PropertyContainerHandle_t ulContainer, const char *pchName,
                                             VRInputComponentHandle_t *pHandle) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
    EVRInputError UpdateEyeTrackingComponent(VRInputComponentHandle_t ulComponent,
                                             const VREyeTrackingData_t *pEyeTrackingData,
                                             double fTimeOffset) override
    {
        assert(false);
        return VRInputError_InvalidParam;
    }
};
struct MockIVRDriverLog final : IVRDriverLog {
    void Log(const char *pchLogMessage) override { assert(pchLogMessage); }
};
struct MockIVRServerDriverHost final : IVRServerDriverHost {
    DriverPose_t pose{};
    unsigned calls = 0;
    bool reject_controller = false;
    ITrackedDeviceServerDriver *registered_hmd = nullptr;
    bool TrackedDeviceAdded(const char *pchDeviceSerialNumber, ETrackedDeviceClass eDeviceClass,
                            ITrackedDeviceServerDriver *pDriver) override
    {
        if (reject_controller) {
            if (eDeviceClass == TrackedDeviceClass_HMD) {
                registered_hmd = pDriver;
                return true;
            }
            assert(eDeviceClass == TrackedDeviceClass_Controller);
            return false;
        }
        assert(false);
        return {};
    }
    void TrackedDevicePoseUpdated(uint32_t unWhichDevice, const DriverPose_t &newPose,
                                  uint32_t unPoseStructSize) override
    {
        assert(unWhichDevice == 3 && unPoseStructSize == sizeof(DriverPose_t));
        pose = newPose;
        calls++;
    }
    void VsyncEvent(double vsyncTimeOffsetSeconds) override { assert(false); }
    void VendorSpecificEvent(uint32_t unWhichDevice, vr::EVREventType eventType,
                             const VREvent_Data_t &eventData, double eventTimeOffset) override
    {
        assert(false);
    }
    bool IsExiting() override
    {
        assert(false);
        return {};
    }
    bool PollNextEvent(VREvent_t *pEvent, uint32_t uncbVREvent) override
    {
        if (reject_controller) return false;
        assert(false);
        return {};
    }
    void GetRawTrackedDevicePoses(float fPredictedSecondsFromNow,
                                  TrackedDevicePose_t *pTrackedDevicePoseArray,
                                  uint32_t unTrackedDevicePoseArrayCount) override
    {
        assert(false);
    }
    void RequestRestart(const char *pchLocalizedReason, const char *pchExecutableToStart,
                        const char *pchArguments, const char *pchWorkingDirectory) override
    {
        assert(false);
    }
    uint32_t GetFrameTimings(Compositor_FrameTiming *pTiming, uint32_t nFrames) override
    {
        assert(false);
        return {};
    }
    void SetDisplayEyeToHead(uint32_t unWhichDevice, const HmdMatrix34_t &eyeToHeadLeft,
                             const HmdMatrix34_t &eyeToHeadRight) override
    {
        assert(false);
    }
    void SetDisplayProjectionRaw(uint32_t unWhichDevice, const HmdRect2_t &eyeLeft,
                                 const HmdRect2_t &eyeRight) override
    {
        assert(false);
    }
    void SetRecommendedRenderTargetSize(uint32_t unWhichDevice, uint32_t nWidth,
                                        uint32_t nHeight) override
    {
        assert(false);
    }
};

struct Context final : IVRDriverContext {
    MockIVRProperties properties;
    MockIVRDriverInput input;
    MockIVRDriverLog log;
    MockIVRServerDriverHost host;
    void *GetGenericInterface(const char *name, EVRInitError *error) override
    {
        if (error)
            *error = VRInitError_None;
        if (!std::strcmp(name, IVRProperties_Version))
            return &properties;
        if (!std::strcmp(name, IVRDriverInput_Version))
            return &input;
        if (!std::strcmp(name, IVRDriverLog_Version))
            return &log;
        if (!std::strcmp(name, IVRServerDriverHost_Version))
            return &host;
        assert(false);
        return nullptr;
    }
    DriverHandle_t GetDriverHandle() override { return 1; }
};
static int64_t now_ns()
{
    timespec t{};
    assert(!clock_gettime(CLOCK_MONOTONIC, &t));
    return static_cast<int64_t>(t.tv_sec) * 1000000000 + t.tv_nsec;
}
int main()
{
    Context context;
    VRDriverContext() = &context;
    OpenVRInternal_ModuleServerDriverContext().Clear();
    pico_controller_channel channel;
    assert(pico_controller_channel_init(&channel, 123));
    {
        PicoSteamvrController driver(&channel, 123, 1);
        assert(driver.Activate(3) == VRInitError_None);
        assert(driver.Activate(3) == VRInitError_Driver_Failed);
        assert(context.properties.role == TrackedControllerRole_LeftHand);
        assert(context.properties.model == "{reframed_pico}neo3_left");
        assert(context.input.names.size() == 12);
        driver.Update();
        assert(!driver.GetPose().deviceIsConnected);
        pico_controller_sample sample{};
        sample.hand = 1;
        sample.buttons = 4 | 128;
        sample.touches = 1 | 16;
        assert(pico_controller_channel_publish(&channel, &sample, now_ns() - 300000000));
        driver.Update();
        assert(!driver.GetPose().deviceIsConnected);
        assert(!context.input.values.at("/input/x/click"));
        assert(pico_controller_channel_publish(&channel, &sample, now_ns()));
        driver.Update();
        assert(driver.GetPose().deviceIsConnected);
        assert(context.input.values.at("/input/x/click"));
        assert(context.input.values.at("/input/trigger/click"));
        assert(context.input.values.at("/input/trigger/touch"));
        assert(!context.input.values.at("/input/y/click"));
        assert(!context.host.pose.poseIsValid &&
               context.host.pose.result == TrackingResult_Uninitialized);
        context.input.invalidate=&channel;
        driver.Update();
        assert(context.host.pose.deviceIsConnected && context.input.values.at("/input/x/click"));
        assert(!driver.GetPose().deviceIsConnected);
        assert(pico_controller_channel_publish(&channel,&sample,now_ns()));
        context.input.fail_update = true;
        driver.Update();
        assert(!driver.GetPose().deviceIsConnected);
        for (auto &entry : context.input.values)
            assert(!entry.second);
        driver.Update();
        assert(driver.GetPose().deviceIsConnected);
        assert(pico_controller_channel_disconnect(&channel, 1));
        driver.Update();
        assert(!driver.GetPose().deviceIsConnected);
        for (auto &entry : context.input.values)
            assert(!entry.second);
        assert(pico_controller_channel_publish(&channel, &sample, now_ns()));
        driver.Update();
        assert(driver.GetPose().deviceIsConnected);
        driver.Deactivate();
        assert(!driver.GetPose().deviceIsConnected);
        for (auto &entry : context.input.values)
            assert(!entry.second);
        char debug[256];
        driver.DebugRequest("", debug, sizeof debug);
        assert(std::strstr(debug, "failures=1") && std::strstr(debug, "pose_valid=0"));
    }
    {
        context.input.names.clear();
        context.input.values.clear();
        PicoSteamvrController wrong(&channel, 456, 2);
        assert(wrong.Activate(3) == VRInitError_None);
        assert(context.properties.role == TrackedControllerRole_RightHand);
        assert(context.properties.model == "{reframed_pico}neo3_right");
        assert(context.input.values.count("/input/a/click"));
        wrong.Update();
        assert(!wrong.GetPose().deviceIsConnected);
    }
    {
        context.input.fail_create = true;
        PicoSteamvrController failed(&channel, 123, 1);
        assert(failed.Activate(3) == VRInitError_Driver_Failed);
        unsigned before = context.host.calls;
        failed.Update();
        assert(context.host.calls == before);
    }
    {
        context.input.fail_create = false;
        context.input.names.clear(); context.input.values.clear();
        pico_slam_channel poses;
        assert(pico_slam_channel_init(&poses, 789));
        assert(pico_slam_channel_begin(&poses, 9));
        pico_controller_sample sample{}; sample.hand = 1;
        assert(pico_controller_channel_publish(&channel, &sample, now_ns()));
        PicoSteamvrController driver(&channel, 123, 1, {&poses, 789, 9, 456, 100000000});
        assert(driver.Activate(3) == VRInitError_None);
        driver.Update();
        assert(driver.GetPose().deviceIsConnected && !driver.GetPose().poseIsValid);
        auto publish_pose = [&] {
            int64_t now = now_ns();
            pico_slam_channel_sample pose{};
            pose.pose.orientation[3] = 1;
            pose.pose.position[0] = .2; pose.pose.position[1] = 1.3; pose.pose.position[2] = -.4;
            pose.generation = 9; pose.timestamp_ns = now - 1000000; pose.published_ns = now;
            assert(pico_slam_channel_publish(&poses, &pose));
        };
        publish_pose(); driver.Update();
        auto pose = driver.GetPose();
        assert(pose.poseIsValid && pose.deviceIsConnected && pose.result == TrackingResult_Running_OK);
        assert(pose.vecPosition[0] == .2 && pose.vecPosition[1] == 1.3 && pose.vecPosition[2] == -.4);
        assert(pose.qRotation.w == 1 && pose.qWorldFromDriverRotation.w == 1);
        assert(pose.poseTimeOffset <= -.001 && pose.poseTimeOffset > -.1);
        assert(context.host.pose.poseIsValid);
        std::this_thread::sleep_for(std::chrono::milliseconds(105));
        pose = driver.GetPose();
        assert(pose.deviceIsConnected && !pose.poseIsValid && pose.vecPosition[0] == 0);
        publish_pose();
        assert(driver.GetPose().poseIsValid);
        assert(pico_slam_channel_invalidate(&poses, 9));
        assert(!driver.GetPose().poseIsValid);
        publish_pose();
        assert(driver.GetPose().poseIsValid);
        assert(pico_controller_channel_disconnect(&channel, 1));
        assert(!driver.GetPose().poseIsValid && !driver.GetPose().deviceIsConnected);
        assert(pico_controller_channel_publish(&channel, &sample, now_ns()));
        driver.Update(); assert(driver.GetPose().poseIsValid);
        assert(pico_slam_channel_stop(&poses, 9));
        assert(pico_slam_channel_begin(&poses, 10));
        assert(!driver.GetPose().poseIsValid);
        driver.Deactivate(); assert(!driver.GetPose().deviceIsConnected);
    }
    {
        pico_slam_channel poses;
        PicoSteamvrController wrong(&channel, 123, 1, {&poses, 456, 9, 456, 100000000});
        assert(wrong.Activate(3) == VRInitError_Driver_Failed);
        PicoSteamvrController partial(&channel, 123, 1, {nullptr, 789, 9, 456, 100000000});
        assert(partial.Activate(3) == VRInitError_Driver_Failed);
    }
    CleanupDriverContext();
    std::puts("PICO_STEAMVR_CONTROLLER_PASS callbacks=mock hardware_access=0");
    return 0;
}
