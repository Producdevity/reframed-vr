#include <openvr.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <unistd.h>

static bool board(const char *serial)
{
    if (!serial || !*serial || std::strlen(serial)>64 ||
        std::strspn(serial,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")!=std::strlen(serial)) return false;
    FILE *file=std::fopen("/proc/cmdline","r");if(!file)return false;
    char text[16384]={0};bool read=std::fgets(text,sizeof(text),file)!=nullptr;
    std::fclose(file);if(!read)return false;
    char expected[100];std::snprintf(expected,sizeof(expected),"androidboot.serialno=%s",serial);
    char *save=nullptr;
    for (char *p=strtok_r(text," \r\n",&save);p;p=strtok_r(nullptr," \r\n",&save))
        if (!std::strcmp(p,expected)) return true;
    return false;
}

int main(int argc,char **argv)
{
    setvbuf(stdout,nullptr,_IOLBF,0);
    if ((argc!=4&&argc!=5) || !board(argv[2])) return 22;
    char *end=nullptr;long seconds=std::strtol(argv[3],&end,10);
    if (!*argv[3] || *end || seconds<1 || seconds>30 ||
        (argc==5&&std::strcmp(argv[4],"--dashboard"))) return 22;
    alarm(static_cast<unsigned>(seconds+40));
    void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if (!library) {std::fprintf(stderr,"%s\n",dlerror());return 1;}
    auto init=reinterpret_cast<uint32_t(*)(vr::EVRInitError *,vr::EVRApplicationType,const char *)>(dlsym(library,"VR_InitInternal2"));
    auto get=reinterpret_cast<void *(*)(const char *,vr::EVRInitError *)>(dlsym(library,"VR_GetGenericInterface"));
    auto shutdown=reinterpret_cast<void (*)()>(dlsym(library,"VR_ShutdownInternal"));
    if (!init||!get||!shutdown) return 2;
    vr::EVRInitError error=vr::VRInitError_None;
    uint32_t token=init(&error,vr::VRApplication_Background,nullptr);
    std::printf("PICO_STEAMVR_CLIENT_INIT token=%u error=%d\n",token,error);
    if (!token||error!=vr::VRInitError_None) return 3;
    auto *system=static_cast<vr::IVRSystem *>(get(vr::IVRSystem_Version,&error));
    if (!system||error!=vr::VRInitError_None) {shutdown();return 4;}
    char tracking[128]={0};vr::ETrackedPropertyError property=vr::TrackedProp_Success;
    system->GetStringTrackedDeviceProperty(0,vr::Prop_TrackingSystemName_String,tracking,sizeof(tracking),&property);
    if (property!=vr::TrackedProp_Success||std::strcmp(tracking,"reframed_pico")) {shutdown();return 5;}
    if (argc==5) {
        auto *overlay=static_cast<vr::IVROverlay *>(get(vr::IVROverlay_Version,&error));
        if (!overlay||error!=vr::VRInitError_None) {shutdown();return 6;}
        overlay->ShowDashboard("");
    }
    unsigned valid=0,invalid=0;double first[3]={0},max_distance=0;
    for (long i=0;i<seconds*100;++i) {
        vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
        system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseRawAndUncalibrated,0,poses,vr::k_unMaxTrackedDeviceCount);
        const auto &head=poses[0];
        if (head.bDeviceIsConnected&&head.bPoseIsValid&&head.eTrackingResult==vr::TrackingResult_Running_OK) {
            double distance=0;
            for (unsigned j=0;j<3;++j) {
                double p=head.mDeviceToAbsoluteTracking.m[j][3];
                if (!std::isfinite(p)) {shutdown();return 7;}
                if (!valid) first[j]=p;
                distance+=(p-first[j])*(p-first[j]);
            }
            max_distance=std::fmax(max_distance,std::sqrt(distance));++valid;
        } else ++invalid;
        usleep(10000);
    }
    shutdown();dlclose(library);
    std::printf("PICO_STEAMVR_LIVE_RESULT valid=%u invalid=%u max_position_delta_m=%.6f physical_motion_acceptance=0\n",valid,invalid,max_distance);
    return valid>100?0:8;
}
