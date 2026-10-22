#include "pico-steamvr-display.h"
#include "pico-steamvr-pose.h"
#include "pico-steamvr-controller.h"
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <sys/mman.h>
#include <sys/stat.h>
#include <thread>
#include <time.h>
#include <unistd.h>

static int64_t monotonic_ns(void *)
{
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC,&t)) return 0;
    return static_cast<int64_t>(t.tv_sec)*1000000000+t.tv_nsec;
}

class PicoHeadset final : public vr::ITrackedDeviceServerDriver {
    const pico_steamvr_display_config config;
    PicoSteamvrDisplay display;
    const pico_slam_channel *channel;
    const uint64_t instance, generation;
    const int64_t max_age;
    std::atomic<vr::TrackedDeviceIndex_t> index{vr::k_unTrackedDeviceIndexInvalid};
    std::atomic<bool> running{false};
    std::thread worker;
    std::atomic<uint64_t> reads[PICO_SLAM_READ_RESULTS]{};
public:
    PicoHeadset(const pico_steamvr_display_config &c, const pico_slam_channel *poses,
                uint64_t i, uint64_t g, int64_t age)
        : config(c), display(c), channel(poses), instance(i), generation(g), max_age(age) {}
    ~PicoHeadset() { Deactivate(); }

    vr::EVRInitError Activate(uint32_t id) override
    {
        if (running.load()) return vr::VRInitError_Driver_Failed;
        auto *properties=vr::VRProperties();
        auto container=properties->TrackedDeviceToPropertyContainer(id);
        bool ok=true;
        auto string=[&](vr::ETrackedDeviceProperty p,const char *v) {
            ok=(properties->SetStringProperty(container,p,v)==vr::TrackedProp_Success)&&ok;
        };
        auto boolean=[&](vr::ETrackedDeviceProperty p,bool v) {
            ok=(properties->SetBoolProperty(container,p,v)==vr::TrackedProp_Success)&&ok;
        };
        string(vr::Prop_TrackingSystemName_String,"reframed_pico");
        string(vr::Prop_ModelNumber_String,"Pico Neo3 Pro Eye");
        string(vr::Prop_ManufacturerName_String,"PICO");
        string(vr::Prop_RenderModelName_String,"generic_hmd");
        double dx=config.views[1].eye_pose[4]-config.views[0].eye_pose[4];
        double dy=config.views[1].eye_pose[5]-config.views[0].eye_pose[5];
        double dz=config.views[1].eye_pose[6]-config.views[0].eye_pose[6];
        ok=(properties->SetFloatProperty(container,vr::Prop_UserIpdMeters_Float,
                                         static_cast<float>(std::sqrt(dx*dx+dy*dy+dz*dz)))==vr::TrackedProp_Success)&&ok;
        ok=(properties->SetFloatProperty(container,vr::Prop_DisplayFrequency_Float,
                                         static_cast<float>(1e9/config.frame_interval_ns))==vr::TrackedProp_Success)&&ok;
        ok=(properties->SetFloatProperty(container,vr::Prop_SecondsFromVsyncToPhotons_Float,0)==vr::TrackedProp_Success)&&ok;
        ok=(properties->SetUint64Property(container,vr::Prop_CurrentUniverseId_Uint64,instance)==vr::TrackedProp_Success)&&ok;
        boolean(vr::Prop_IsOnDesktop_Bool,false);
        boolean(vr::Prop_HasDisplayComponent_Bool,true);
        boolean(vr::Prop_HasDriverDirectModeComponent_Bool,false);
        boolean(vr::Prop_HasVirtualDisplayComponent_Bool,false);
        if (!ok) return vr::VRInitError_Driver_Failed;
        vr::VRServerDriverHost()->SetDisplayEyeToHead(id,pico_steamvr_eye_to_head(config.views[0]),
                                                       pico_steamvr_eye_to_head(config.views[1]));
        index.store(id);
        running.store(true);
        try { worker=std::thread([this] {
            while (running.load()) {
                auto id=index.load();
                if (id!=vr::k_unTrackedDeviceIndexInvalid)
                    vr::VRServerDriverHost()->TrackedDevicePoseUpdated(id,GetPose(),sizeof(vr::DriverPose_t));
                std::this_thread::sleep_for(std::chrono::microseconds(1000));
            }
        }); } catch (...) {
            running.store(false);index.store(vr::k_unTrackedDeviceIndexInvalid);
            return vr::VRInitError_Driver_Failed;
        }
        vr::VRDriverLog()->Log("Reframed Neo3: physical display configured; poses require the bound live SLAM generation");
        return vr::VRInitError_None;
    }
    void Deactivate() override {
        bool active=running.exchange(false);
        if (worker.joinable()) worker.join();
        index.store(vr::k_unTrackedDeviceIndexInvalid);
        if (active) {
            char log[320];
            DebugRequest("pose-read-stats",log,sizeof(log));
            vr::VRDriverLog()->Log(log);
        }
    }
    void EnterStandby() override {}
    void *GetComponent(const char *name) override {
        return name&&!std::strcmp(name,vr::IVRDisplayComponent_Version)?static_cast<vr::IVRDisplayComponent *>(&display):nullptr;
    }
    void DebugRequest(const char *request,char *response,uint32_t size) override {
        if (!size) return;
        if (!request || std::strcmp(request,"pose-read-stats")) {
            std::snprintf(response,size,"No calibration or origin changes during a live generation");
            return;
        }
        std::snprintf(response,size,"PICO_STEAMVR_POSE_READS ok=%llu refused=%llu busy=%llu inactive=%llu future=%llu stale=%llu malformed=%llu",
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_OK].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_REFUSED].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_BUSY].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_INACTIVE].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_FUTURE].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_STALE].load()),
            static_cast<unsigned long long>(reads[PICO_SLAM_READ_MALFORMED].load()));
    }
    vr::DriverPose_t GetPose() override {
        pico_slam_read_result result;
        auto pose=pico_steamvr_pose_now(channel,instance,generation,max_age,
            index.load()!=vr::k_unTrackedDeviceIndexInvalid,monotonic_ns,nullptr,&result);
        reads[result].fetch_add(1,std::memory_order_relaxed);
        return pose;
    }
};

static bool identifier(const char *text, uint64_t &value)
{
    if (!text || std::strlen(text)!=16 || std::strspn(text,"0123456789abcdef")!=16) return false;
    char *end=nullptr; errno=0;
    unsigned long long v=std::strtoull(text,&end,16);
    if (errno || *end || !v) return false;
    value=v;return true;
}

class PicoProvider final : public vr::IServerTrackedDeviceProvider {
    std::unique_ptr<PicoHeadset> headset;
    std::unique_ptr<PicoSteamvrController> left_controller;
    pico_slam_channel *channel=nullptr;
    pico_controller_channel *controller_channel=nullptr;
    pico_slam_channel *left_pose_channel=nullptr;
public:
    vr::EVRInitError Init(vr::IVRDriverContext *context) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(context);
        pico_steamvr_display_config optics{};
        uint64_t instance=0,generation=0;
        const char *file=std::getenv("PICO_STEAMVR_POSE_CHANNEL");
        const char *age=std::getenv("PICO_STEAMVR_MAX_AGE_NS");
        const char *serial=std::getenv("PICO_STEAMVR_BOOT_SERIAL");
        char *end=nullptr;errno=0;
        long long max_age=age?std::strtoll(age,&end,10):0;
        if (!file || !age || !*age || errno || *end || max_age<=0 || max_age>100000000 ||
            !serial || !*serial || std::strlen(serial)>64 ||
            std::strspn(serial,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")!=std::strlen(serial) ||
            !identifier(std::getenv("PICO_STEAMVR_INSTANCE"),instance) ||
            !identifier(std::getenv("PICO_STEAMVR_GENERATION"),generation) ||
            !pico_steamvr_display_load(std::getenv("PICO_STEAMVR_OPTICS"),optics)) return vr::VRInitError_Driver_Failed;
        FILE *cmdline=std::fopen("/proc/cmdline","r");
        if (!cmdline) return vr::VRInitError_Driver_Failed;
        char line[16384]={0};bool read=std::fgets(line,sizeof(line),cmdline)!=nullptr;
        bool complete=std::feof(cmdline)||std::strchr(line,'\n'); std::fclose(cmdline);
        char expected[100];std::snprintf(expected,sizeof(expected),"androidboot.serialno=%s",serial);
        bool board=false;
        char *save=nullptr;
        for (char *token=strtok_r(line," \r\n",&save);token;token=strtok_r(nullptr," \r\n",&save))
            if (!std::strcmp(token,expected)) board=true;
        if (!read || !complete || !board) return vr::VRInitError_Driver_Failed;
        int fd=open(file,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
        if (fd<0) return vr::VRInitError_Driver_Failed;
        struct stat st;
        bool valid=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_size==sizeof(*channel) &&
                   (st.st_uid==0 || st.st_uid==geteuid()) && !(st.st_mode&0022);
        void *mapping=valid?mmap(nullptr,sizeof(*channel),PROT_READ,MAP_SHARED,fd,0):MAP_FAILED;
        close(fd);
        if (mapping==MAP_FAILED) return vr::VRInitError_Driver_Failed;
        channel=static_cast<pico_slam_channel *>(mapping);
        const char *controller_file=std::getenv("PICO_STEAMVR_CONTROLLER_CHANNEL");
        const char *pose_file=std::getenv("PICO_STEAMVR_LEFT_POSE_CHANNEL");
        const char *pose_instance=std::getenv("PICO_STEAMVR_LEFT_POSE_INSTANCE");
        if ((pose_file || pose_instance) && (!controller_file || !pose_file || !pose_instance)) {
            Cleanup();return vr::VRInitError_Driver_Failed;
        }
        if (controller_file) {
            uint64_t controller_instance=0;
            if (!identifier(std::getenv("PICO_STEAMVR_CONTROLLER_INSTANCE"),controller_instance)) {
                Cleanup();return vr::VRInitError_Driver_Failed;
            }
            int input_fd=open(controller_file,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
            struct stat input_stat{};
            bool input_valid=input_fd>=0 && !fstat(input_fd,&input_stat) &&
                S_ISREG(input_stat.st_mode) && input_stat.st_size==sizeof(*controller_channel) &&
                (input_stat.st_uid==0 || input_stat.st_uid==geteuid()) && !(input_stat.st_mode&0022);
            void *input_mapping=input_valid?mmap(nullptr,sizeof(*controller_channel),PROT_READ,
                                                 MAP_SHARED,input_fd,0):MAP_FAILED;
            if (input_fd>=0) close(input_fd);
            if (input_mapping==MAP_FAILED) {Cleanup();return vr::VRInitError_Driver_Failed;}
            controller_channel=static_cast<pico_controller_channel *>(input_mapping);
            pico_steamvr_controller_tracking tracking;
            if (pose_file) {
                uint64_t pose_id=0;
                if (pose_file[0]!='/' || !identifier(pose_instance,pose_id) || pose_id==instance) {
                    Cleanup();return vr::VRInitError_Driver_Failed;
                }
                int pose_fd=open(pose_file,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
                struct stat pose_stat{};
                bool pose_valid=pose_fd>=0 && !fstat(pose_fd,&pose_stat) && S_ISREG(pose_stat.st_mode) &&
                    pose_stat.st_size==sizeof(*left_pose_channel) &&
                    (pose_stat.st_uid==0 || pose_stat.st_uid==geteuid()) && !(pose_stat.st_mode&0022) &&
                    (pose_stat.st_dev!=st.st_dev || pose_stat.st_ino!=st.st_ino);
                void *pose_mapping=pose_valid?mmap(nullptr,sizeof(*left_pose_channel),PROT_READ,
                                                   MAP_SHARED,pose_fd,0):MAP_FAILED;
                if (pose_fd>=0) close(pose_fd);
                if (pose_mapping==MAP_FAILED) {Cleanup();return vr::VRInitError_Driver_Failed;}
                left_pose_channel=static_cast<pico_slam_channel *>(pose_mapping);
                tracking={left_pose_channel,pose_id,generation,instance,max_age};
            }
            left_controller=std::make_unique<PicoSteamvrController>(controller_channel,controller_instance,1,tracking);
        }
        headset=std::make_unique<PicoHeadset>(optics,channel,instance,generation,max_age);
        if (!vr::VRServerDriverHost()->TrackedDeviceAdded(optics.serial,vr::TrackedDeviceClass_HMD,headset.get())) {
            Cleanup();return vr::VRInitError_Driver_Failed;
        }
        if (left_controller) {
            char controller_serial[256];
            int length=std::snprintf(controller_serial,sizeof(controller_serial),"%s-left",optics.serial);
            if (length<0 || static_cast<size_t>(length)>=sizeof(controller_serial) ||
                !vr::VRServerDriverHost()->TrackedDeviceAdded(controller_serial,vr::TrackedDeviceClass_Controller,
                                                             left_controller.get())) {
                Cleanup();return vr::VRInitError_Driver_Failed;
            }
        }
        return vr::VRInitError_None;
    }
    void Cleanup() override {
        left_controller.reset();
        if (left_pose_channel) {munmap(left_pose_channel,sizeof(*left_pose_channel));left_pose_channel=nullptr;}
        if (controller_channel) {munmap(controller_channel,sizeof(*controller_channel));controller_channel=nullptr;}
        headset.reset();
        if (channel) {munmap(channel,sizeof(*channel));channel=nullptr;}
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }
    const char *const *GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    void RunFrame() override {
        if (left_controller) left_controller->Update();
        vr::VREvent_t event;
        while (vr::VRServerDriverHost()->PollNextEvent(&event,sizeof(event))) {}
    }
    bool ShouldBlockStandbyMode() override { return false; }
    void EnterStandby() override {}
    void LeaveStandby() override {}
};

extern "C" __attribute__((visibility("default"))) void *HmdDriverFactory(const char *name,int *error)
{
    static PicoProvider provider;
    if (name&&!std::strcmp(name,vr::IServerTrackedDeviceProvider_Version)) return &provider;
    if (error) *error=vr::VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
