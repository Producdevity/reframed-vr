#include <openvr.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <initializer_list>
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

static void view_matrix(const char *space,const vr::HmdMatrix34_t &matrix,bool valid)
{
    std::printf("PICO_STEAMVR_VIEW_FRAME monotonic_ns=%lld space=%s valid=%d matrix=",
                static_cast<long long>(monotonic_ns()),space,valid);
    for (unsigned row=0;row<3;++row) for (unsigned col=0;col<4;++col)
        std::printf("%s%.9g",row||col?",":"",matrix.m[row][col]);
    std::putchar('\n');
}

static bool board(const char *serial)
{
    if (!serial || !*serial || std::strlen(serial)>64 ||
        std::strspn(serial,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")!=std::strlen(serial)) return false;
    FILE *file=std::fopen("/proc/cmdline","r");if(!file)return false;
    char text[16384]={0};bool read=std::fgets(text,sizeof(text),file)!=nullptr;
    bool complete=std::feof(file)||std::strchr(text,'\n');
    std::fclose(file);if(!read||!complete)return false;
    char expected[100];std::snprintf(expected,sizeof(expected),"androidboot.serialno=%s",serial);
    unsigned serial_tokens=0;bool matches=false;char *save=nullptr;
    for (char *p=strtok_r(text," \r\n",&save);p;p=strtok_r(nullptr," \r\n",&save)) {
        if (!std::strncmp(p,"androidboot.serialno=",21)) ++serial_tokens;
        if (!std::strcmp(p,expected)) matches=true;
    }
    return matches&&serial_tokens==1;
}

static bool check_models(vr::IVRRenderModels *models)
{
    if (!models) return false;
    for (const char *hand : {"left", "right"}) {
        char name[96], body[256] = {};
        std::snprintf(name, sizeof(name), "{reframed_pico}neo3_%s", hand);
        uint32_t components = models->GetComponentCount(name);
        unsigned required = 0;
        for (uint32_t i=0;i<components&&i<32;++i) {
            char component[128]={};
            models->GetComponentName(name,i,component,sizeof(component));
            if (!std::strcmp(component,"body")) required |= 1;
            if (!std::strcmp(component,"tip")) required |= 2;
            if (!std::strcmp(component,"grip")) required |= 4;
            if (!std::strcmp(component,"handgrip")) required |= 8;
        }
        uint32_t body_length=models->GetComponentRenderModelName(name, "body", body, sizeof(body));
        std::printf("PICO_STEAMVR_MODEL_COMPONENTS hand=%s count=%u required=%u body=%s\n", hand, components, required, body);
        if (required != 15 || !body_length || body_length>sizeof(body)) return false;
        vr::RenderModel_t *model = nullptr;
        vr::EVRRenderModelError result;
        int64_t end = monotonic_ns() + 5000000000LL;
        do {
            result = models->LoadRenderModel_Async(body, &model);
            if (result == vr::VRRenderModelError_Loading) usleep(10000);
        } while (result == vr::VRRenderModelError_Loading && monotonic_ns() < end);
        if (result != vr::VRRenderModelError_None || !model) {
            std::printf("PICO_STEAMVR_MODEL_ERROR name=%s body=%s error=%d\n", name, body, result);
            return false;
        }
        bool valid = model->unVertexCount > 0 && model->unVertexCount < 65000 && model->unTriangleCount == 3488;
        for (uint32_t i = 0; i < model->unVertexCount; ++i)
            for (float coordinate : model->rVertexData[i].vPosition.v)
                valid = valid && std::isfinite(coordinate) && std::fabs(coordinate) < .35;
        vr::RenderModel_TextureMap_t *texture = nullptr;
        end = monotonic_ns() + 5000000000LL;
        do {
            result = models->LoadTexture_Async(model->diffuseTextureId, &texture);
            if (result == vr::VRRenderModelError_Loading) usleep(10000);
        } while (result == vr::VRRenderModelError_Loading && monotonic_ns() < end);
        valid = valid && result == vr::VRRenderModelError_None && texture && texture->unWidth && texture->unHeight;
        std::printf("PICO_STEAMVR_MODEL hand=%s components=%u vertices=%u triangles=%u texture=%ux%u valid=%d\n",
            hand, components, model->unVertexCount, model->unTriangleCount,
            texture ? texture->unWidth : 0, texture ? texture->unHeight : 0, valid);
        if (texture) models->FreeTexture(texture);
        models->FreeRenderModel(model);
        if (!valid) return false;
    }
    return true;
}

int main(int argc,char **argv)
{
    setvbuf(stdout,nullptr,_IOLBF,0);
    if ((argc!=4&&argc!=5&&argc!=6&&argc!=7) || !board(argv[2])) return 22;
    bool controllers=argc==5&&!std::strcmp(argv[4],"--left-controller");
    bool view_frames=argc==5&&!std::strcmp(argv[4],"--view-frames");
    bool models=argc==5&&!std::strcmp(argv[4],"--controller-models");
    bool frame_history=argc==7&&!std::strcmp(argv[6],"--frame-history");
    bool dashboard=argc>=5&&!controllers&&!view_frames&&!models;
    char *end=nullptr;long seconds=std::strtol(argv[3],&end,10);
    if (!*argv[3] || *end || seconds<1 || seconds>30 ||
        (dashboard&&std::strcmp(argv[4],"--dashboard")) ||
        (argc==7&&!frame_history) ||
        (argc>=6&&(!*argv[5] || std::strlen(argv[5])>128 ||
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
    if (models) {
        auto *render_models=static_cast<vr::IVRRenderModels *>(get(vr::IVRRenderModels_Version,&error));
        bool passed=error==vr::VRInitError_None&&check_models(render_models);
        shutdown();return passed?0:11;
    }
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
    if (dashboard) {
        auto *chaperone=static_cast<vr::IVRChaperone *>(get(vr::IVRChaperone_Version,&error));
        std::printf("PICO_STEAMVR_SESSION calibration=%d activity=%d\n",
                    chaperone&&error==vr::VRInitError_None?static_cast<int>(chaperone->GetCalibrationState()):-1,
                    static_cast<int>(system->GetTrackedDeviceActivityLevel(0)));
        overlay=static_cast<vr::IVROverlay *>(get(vr::IVROverlay_Version,&error));
        if (!overlay||error!=vr::VRInitError_None) {shutdown();return 6;}
        const char *key=argc>=6?argv[5]:"";
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
    unsigned controller_samples=0,controller_connected=0,controller_states=0,controller_poses=0;
    char expected_controller[80];
    std::snprintf(expected_controller,sizeof(expected_controller),"%s-left",argv[2]);
    auto *input_debug=controllers?static_cast<vr::IVRDebug *>(get(vr::IVRDebug_Version,&error)):nullptr;
    if (controllers&&(!input_debug||error!=vr::VRInitError_None)) {shutdown();return 10;}
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
        if (view_frames&&i%100==0) {
            vr::TrackedDevicePose_t standing{};
            system->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,&standing,1);
            view_matrix("raw",head.mDeviceToAbsoluteTracking,head.bPoseIsValid);
            view_matrix("standing",standing.mDeviceToAbsoluteTracking,standing.bPoseIsValid);
            view_matrix("raw_to_standing",system->GetRawZeroPoseToStandingAbsoluteTrackingPose(),true);
        }
        if (controllers&&i%100==0) {
            ++controller_samples;
            auto id=vr::k_unTrackedDeviceIndexInvalid;
            for (uint32_t candidate=1;candidate<vr::k_unMaxTrackedDeviceCount;++candidate) {
                if (system->GetTrackedDeviceClass(candidate)!=vr::TrackedDeviceClass_Controller) continue;
                char serial[128]={0};vr::ETrackedPropertyError pe=vr::TrackedProp_Success;
                system->GetStringTrackedDeviceProperty(candidate,vr::Prop_SerialNumber_String,serial,sizeof(serial),&pe);
                if (pe==vr::TrackedProp_Success&&!std::strcmp(serial,expected_controller)) {id=candidate;break;}
            }
            bool connected=false,state_ok=false,pose_valid=false;
            vr::VRControllerState_t state{};
            char response[512]={0};
            if (id<vr::k_unMaxTrackedDeviceCount) {
                connected=poses[id].bDeviceIsConnected;
                pose_valid=poses[id].bPoseIsValid;
                state_ok=system->GetControllerState(id,&state,sizeof(state));
                input_debug->DriverDebugRequest(id,"input",response,sizeof(response));
            }
            controller_connected+=connected;
            controller_states+=connected&&state_ok;
            controller_poses+=pose_valid;
            std::printf("PICO_STEAMVR_CONTROLLER_SAMPLE monotonic_ns=%lld tick=%ld id=%u connected=%d state_ok=%d pose_valid=%d head_valid=%d pressed=%llu touched=%llu %s\n",
                static_cast<long long>(monotonic_ns()),i/100,id,connected,state_ok,pose_valid,
                head.bDeviceIsConnected&&head.bPoseIsValid,
                static_cast<unsigned long long>(state.ulButtonPressed),
                static_cast<unsigned long long>(state.ulButtonTouched),response);
        }
        float since_vsync=0;uint64_t vsync_counter=0;bool vsync_available=false;
        uint64_t kernel_before=0,kernel_after=0;int64_t query_before=0,query_after=0;
        if (compositor) {
            kernel_before=kernel_vsync(vsync_fd);
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
            if (frame_history) {
                vr::Compositor_FrameTiming history[128]{};
                for (auto &frame : history) frame.m_nSize=sizeof(frame);
                uint32_t count=compositor->GetFrameTimings(history,128);
                if (count>128) {shutdown();return 12;}
                for (uint32_t j=0;j<count;++j) {
                    const auto &frame=history[j];
                    std::printf("PICO_STEAMVR_FRAME_HISTORY index=%u system_s=%.9f presents=%u mispresented=%u dropped=%u gpu_ms=%.6f cpu_ms=%.6f\n",
                        frame.m_nFrameIndex,frame.m_flSystemTimeInSeconds,frame.m_nNumFramePresents,
                        frame.m_nNumMisPresented,frame.m_nNumDroppedFrames,
                        frame.m_flCompositorRenderGpuMs,frame.m_flCompositorRenderCpuMs);
                }
            }
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
        if (argc>=6) {
            vr::VROverlayHandle_t selected=vr::k_ulOverlayHandleInvalid;
            auto found=overlay->FindOverlay(argv[5],&selected);
            bool active=found==vr::VROverlayError_None&&overlay->IsActiveDashboardOverlay(selected);
            bool visible=found==vr::VROverlayError_None&&overlay->IsOverlayVisible(selected);
            uint32_t width=0,height=0;
            auto texture=found==vr::VROverlayError_None?
                overlay->GetOverlayTextureSize(selected,&width,&height):found;
            std::printf("PICO_STEAMVR_DASHBOARD_SELECTED key=%s find=%d active=%d visible=%d texture=%d size=%ux%u\n",
                        argv[5],found,active,visible,texture,width,height);
            dashboard_visible=dashboard_visible&&active&&visible&&
                texture==vr::VROverlayError_None&&width&&height;
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
    if (controllers) std::printf("PICO_STEAMVR_CONTROLLER_RESULT samples=%u connected=%u states=%u valid_poses=%u physical_input_acceptance=0\n",
        controller_samples,controller_connected,controller_states,controller_poses);
    return controllers&&!controller_states?10:valid<100?8:dashboard_visible?0:9;
}
