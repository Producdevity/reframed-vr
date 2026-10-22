#include <openvr.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>

static int64_t monotonic_ns()
{
    timespec now{};
    return clock_gettime(CLOCK_MONOTONIC,&now)?0:static_cast<int64_t>(now.tv_sec)*1000000000+now.tv_nsec;
}

static uint64_t kernel_vsync(int fd)
{
    char text[64]={0};
    ssize_t size=fd>=0?pread(fd,text,sizeof(text)-1,0):-1;
    if (size<8 || std::strncmp(text,"VSYNC=",6)) return 0;
    char *end=nullptr;
    auto value=std::strtoull(text+6,&end,10);
    return end==text+size-1 && *end=='\n'?value:0;
}

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
    if ((argc!=4&&argc!=5&&argc!=6) || !board(argv[2])) return 22;
    char *end=nullptr;long seconds=std::strtol(argv[3],&end,10);
    if (!*argv[3] || *end || seconds<1 || seconds>30 ||
        (argc>=5&&std::strcmp(argv[4],"--dashboard")) ||
        (argc==6&&(!*argv[5] || std::strlen(argv[5])>128 ||
                   std::strspn(argv[5],"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")!=std::strlen(argv[5])))) return 22;
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
    auto *settings=static_cast<vr::IVRSettings *>(get(vr::IVRSettings_Version,&error));
    if (settings&&error==vr::VRInitError_None) {
        vr::EVRSettingsError setting_error=vr::VRSettingsError_None;
        bool disabled=settings->GetBool("steamvr","disableLinuxWaitForPresent",&setting_error);
        std::printf("PICO_STEAMVR_SETTINGS present_wait_disabled=%d error=%d\n",disabled,setting_error);
        setting_error=vr::VRSettingsError_None;
        bool facet=settings->GetBool("steamvr","useFacetRenderer",&setting_error);
        std::printf("PICO_STEAMVR_RENDERER_SETTING use_facet=%d error=%d\n",facet,setting_error);
    }
    vr::IVROverlay *overlay=nullptr;
    if (argc>=5) {
        auto *chaperone=static_cast<vr::IVRChaperone *>(get(vr::IVRChaperone_Version,&error));
        std::printf("PICO_STEAMVR_SESSION calibration=%d activity=%d\n",
                    chaperone&&error==vr::VRInitError_None?static_cast<int>(chaperone->GetCalibrationState()):-1,
                    static_cast<int>(system->GetTrackedDeviceActivityLevel(0)));
        overlay=static_cast<vr::IVROverlay *>(get(vr::IVROverlay_Version,&error));
        if (!overlay||error!=vr::VRInitError_None) {shutdown();return 6;}
        const char *key=argc==6?argv[5]:"";
        std::printf("PICO_STEAMVR_DASHBOARD_REQUEST key=%s\n",key);
        overlay->ShowDashboard(key);
    }
    auto *compositor=overlay?static_cast<vr::IVRCompositor *>(get(vr::IVRCompositor_Version,&error)):nullptr;
    int vsync_fd=compositor?open("/sys/devices/platform/soc/ae00000.qcom,mdss_mdp/drm/card0/sde-crtc-0/vsync_event",
                                O_RDONLY|O_CLOEXEC|O_NOFOLLOW):-1;
    auto stats=[&](const char *phase) {
        if (!compositor) return;
        vr::Compositor_CumulativeStats value{};
        compositor->GetCumulativeStats(&value,sizeof(value));
        timespec now{};clock_gettime(CLOCK_MONOTONIC,&now);
        std::printf("PICO_STEAMVR_APP_STATS phase=%s monotonic_s=%.9f app_pid=%u presents=%u dropped=%u reprojected=%u\n",
                    phase,static_cast<double>(now.tv_sec)+now.tv_nsec/1e9,value.m_nPid,
                    value.m_nNumFramePresents,value.m_nNumDroppedFrames,value.m_nNumReprojectedFrames);
    };
    stats("begin");
    unsigned valid=0,invalid=0;double first[3]={0},max_distance=0;
    unsigned vsync_samples=0,vsync_invalid=0;
    unsigned vsync_unavailable=0,vsync_nonfinite=0,vsync_negative=0,vsync_overdue=0,vsync_bad_refresh=0;
    property=vr::TrackedProp_Success;
    float refresh=system->GetFloatTrackedDeviceProperty(0,vr::Prop_DisplayFrequency_Float,&property);
    double max_vsync_age=property==vr::TrackedProp_Success&&std::isfinite(refresh)&&refresh>0?2.0/refresh:0;
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
        float since_vsync=0;uint64_t vsync_counter=0;bool vsync_available=false;
        uint64_t kernel_before=0,kernel_after=0;int64_t query_before=0,query_after=0;
        if (compositor) {
            if (i%100==0) kernel_before=kernel_vsync(vsync_fd);
            query_before=monotonic_ns();
            vsync_available=system->GetTimeSinceLastVsync(&since_vsync,&vsync_counter);
            query_after=monotonic_ns();
            ++vsync_samples;
            const char *reason=nullptr;
            if (!vsync_available) {++vsync_unavailable;reason="unavailable";}
            else if (!std::isfinite(since_vsync)) {++vsync_nonfinite;reason="nonfinite";}
            else if (since_vsync<0) {++vsync_negative;reason="negative";}
            else if (max_vsync_age<=0) {++vsync_bad_refresh;reason="refresh";}
            else if (since_vsync>max_vsync_age) {++vsync_overdue;reason="overdue";}
            if (i%100==0 || reason) kernel_after=kernel_vsync(vsync_fd);
            if (reason) {
                ++vsync_invalid;
                std::printf("PICO_STEAMVR_VSYNC_FAULT sample=%ld reason=%s age_s=%.9f counter=%llu query_before_ns=%lld query_after_ns=%lld kernel_before_ns=%llu kernel_after_ns=%llu\n",
                    i,reason,since_vsync,static_cast<unsigned long long>(vsync_counter),
                    static_cast<long long>(query_before),static_cast<long long>(query_after),
                    static_cast<unsigned long long>(kernel_before),static_cast<unsigned long long>(kernel_after));
            }
        }
        if (compositor&&i%100==0) {
            vr::Compositor_FrameTiming timing{};timing.m_nSize=sizeof(timing);
            bool available=compositor->GetFrameTiming(&timing,1);
            std::printf("PICO_STEAMVR_FRAME_TIMING available=%d index=%u system_s=%.9f presents=%u mispresented=%u dropped=%u compositor_gpu_ms=%.6f compositor_cpu_ms=%.6f wait_present_cpu_ms=%.6f compositor_idle_cpu_ms=%.6f render_start_ms=%.6f update_start_ms=%.6f update_end_ms=%.6f vsync_ready=%u vsync_first_view=%u vsync_available=%d since_vsync_s=%.9f vsync_counter=%llu\n",
                        available,timing.m_nFrameIndex,timing.m_flSystemTimeInSeconds,
                        timing.m_nNumFramePresents,timing.m_nNumMisPresented,timing.m_nNumDroppedFrames,
                        timing.m_flCompositorRenderGpuMs,timing.m_flCompositorRenderCpuMs,timing.m_flWaitForPresentCpuMs,
                        timing.m_flCompositorIdleCpuMs,timing.m_flCompositorRenderStartMs,
                        timing.m_flCompositorUpdateStartMs,timing.m_flCompositorUpdateEndMs,
                        timing.m_nNumVSyncsReadyForUse,timing.m_nNumVSyncsToFirstView,
                        vsync_available,since_vsync,static_cast<unsigned long long>(vsync_counter));
            std::printf("PICO_STEAMVR_VSYNC_REFERENCE query_before_ns=%lld query_after_ns=%lld kernel_before_ns=%llu kernel_after_ns=%llu\n",
                static_cast<long long>(query_before),static_cast<long long>(query_after),
                static_cast<unsigned long long>(kernel_before),static_cast<unsigned long long>(kernel_after));
        }
        usleep(10000);
    }
    stats("end");
    if (compositor) std::printf("PICO_STEAMVR_VSYNC_RESULT samples=%u invalid=%u max_age_s=%.9f unavailable=%u nonfinite=%u negative=%u overdue=%u bad_refresh=%u\n",
                                vsync_samples,vsync_invalid,max_vsync_age,vsync_unavailable,
                                vsync_nonfinite,vsync_negative,vsync_overdue,vsync_bad_refresh);
    if (vsync_fd>=0) close(vsync_fd);
    auto *debug=static_cast<vr::IVRDebug *>(get(vr::IVRDebug_Version,&error));
    if (debug&&error==vr::VRInitError_None) {
        char response[320]={0};
        uint32_t count=debug->DriverDebugRequest(0,"pose-read-stats",response,sizeof(response));
        std::printf("PICO_STEAMVR_DRIVER_READ_STATS chars=%u %s\n",count,response);
    }
    bool dashboard_visible=!overlay||overlay->IsDashboardVisible();
    if (overlay) {
        std::printf("PICO_STEAMVR_DASHBOARD visible=%d\n",dashboard_visible);
        if (argc==6) {
            vr::VROverlayHandle_t selected=vr::k_ulOverlayHandleInvalid;
            auto found=overlay->FindOverlay(argv[5],&selected);
            bool active=found==vr::VROverlayError_None&&overlay->IsActiveDashboardOverlay(selected);
            bool visible=found==vr::VROverlayError_None&&overlay->IsOverlayVisible(selected);
            std::printf("PICO_STEAMVR_DASHBOARD_SELECTED key=%s find=%d active=%d visible=%d\n",
                        argv[5],found,active,visible);
            dashboard_visible=dashboard_visible&&active&&visible;
        }
        const char *keys[]={"valve.steam.gamepadui.main","reframed.pico.steam"};
        for (const char *key:keys) {
            vr::VROverlayHandle_t handle=vr::k_ulOverlayHandleInvalid;
            auto found=overlay->FindOverlay(key,&handle);
            uint32_t width=0,height=0;
            auto texture=found==vr::VROverlayError_None?
                overlay->GetOverlayTextureSize(handle,&width,&height):found;
            std::printf("PICO_STEAMVR_OVERLAY key=%s find=%d texture=%d size=%ux%u visible=%d\n",
                        key,found,texture,width,height,
                        found==vr::VROverlayError_None&&overlay->IsOverlayVisible(handle));
        }
    }
    shutdown();dlclose(library);
    std::printf("PICO_STEAMVR_LIVE_RESULT valid=%u invalid=%u max_position_delta_m=%.6f physical_motion_acceptance=0\n",valid,invalid,max_distance);
    return valid<=100?8:dashboard_visible?0:9;
}
