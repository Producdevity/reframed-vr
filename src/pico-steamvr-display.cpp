#include "pico-steamvr-display.h"
#include <algorithm>
#include <cmath>
#include <cstring>

bool pico_steamvr_display_valid(const pico_steamvr_display_config &c)
{
    if (!c.serial[0] || !std::memchr(c.serial, 0, sizeof(c.serial)) ||
        !c.width || !c.height || c.width > 16384 || c.height > 16384 ||
        c.frame_interval_ns < 1000000 || c.frame_interval_ns > 100000000) return false;
    for (const auto &v : c.views) {
        if (!v.viewport[2] || !v.viewport[3] || v.viewport[2] > c.width || v.viewport[3] > c.height ||
            v.viewport[0] > c.width - v.viewport[2] || v.viewport[1] > c.height - v.viewport[3] ||
            !v.render[0] || !v.render[1] || v.render[0] > 16384 || v.render[1] > 16384) return false;
        for (double r : v.rotation) if (!std::isfinite(r)) return false;
        const double *r = v.rotation;
        if (std::fabs(r[0]*r[0] + r[1]*r[1] - 1) > .0001 ||
            std::fabs(r[2]*r[2] + r[3]*r[3] - 1) > .0001 ||
            std::fabs(r[0]*r[2] + r[1]*r[3]) > .0001 ||
            std::fabs(r[0]*r[3] - r[1]*r[2] - 1) > .0001) return false;
        for (double f : v.fov) if (!std::isfinite(f) || std::fabs(f) >= 1.57) return false;
        if (v.fov[0] >= 0 || v.fov[1] <= 0 || v.fov[2] <= 0 || v.fov[3] >= 0) return false;
        double norm = 0;
        for (unsigned i = 0; i < 7; ++i) {
            if (!std::isfinite(v.eye_pose[i])) return false;
            if (i < 4) norm += v.eye_pose[i]*v.eye_pose[i];
            else if (std::fabs(v.eye_pose[i]) > .2) return false;
        }
        if (std::fabs(norm - 1) > .0001) return false;
        for (unsigned i = 0; i < 2; ++i)
            if (!std::isfinite(v.tangent_scale[i]) || !std::isfinite(v.tangent_offset[i]) ||
                std::fabs(v.tangent_scale[i]) < .000001 || std::fabs(v.tangent_scale[i]) > 32 ||
                std::fabs(v.tangent_offset[i]) > 32) return false;
        for (double k : v.radial) if (!std::isfinite(k) || std::fabs(k) > 1000000) return false;
        for (double k : v.chromatic) if (!std::isfinite(k) || std::fabs(k) > 1000000) return false;
        double extent[2]={0,0};
        for (double x : {-1.,1.}) for (double y : {-1.,1.}) {
            double u=(r[0]*x+r[2]*y+1)*.5, w=(1-r[1]*x-r[3]*y)*.5;
            extent[0]=std::max(extent[0],std::fabs(v.tangent_scale[0]*u+v.tangent_offset[0]));
            extent[1]=std::max(extent[1],std::fabs(v.tangent_scale[1]*w+v.tangent_offset[1]));
        }
        double rsq=extent[0]*extent[0]+extent[1]*extent[1],bound=0;
        for (int i=10;i>=0;--i) bound=bound*rsq+std::fabs(v.radial[i]);
        const double *k=v.chromatic;
        bound*=std::max(1.,std::max(1+std::fabs(k[0])+rsq*std::fabs(k[1])+std::sqrt(rsq)*std::fabs(k[4]),
                                   1+std::fabs(k[2])+rsq*std::fabs(k[3])+std::sqrt(rsq)*std::fabs(k[5])));
        if (!std::isfinite(bound) ||
            (extent[0]*bound+std::fabs(std::tan(v.fov[0])))/(std::tan(v.fov[1])-std::tan(v.fov[0]))>1000000 ||
            (extent[1]*bound+std::fabs(std::tan(v.fov[2])))/(std::tan(v.fov[2])-std::tan(v.fov[3]))>1000000) return false;
    }
    const auto &a = c.views[0].viewport, &b = c.views[1].viewport;
    return a[0] + a[2] <= b[0] || b[0] + b[2] <= a[0] ||
           a[1] + a[3] <= b[1] || b[1] + b[3] <= a[1];
}

vr::HmdMatrix34_t pico_steamvr_eye_to_head(const pico_steamvr_view &v)
{
    const double x=v.eye_pose[0], y=v.eye_pose[1], z=v.eye_pose[2], w=v.eye_pose[3];
    vr::HmdMatrix34_t m{};
    const double r[9] = {1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),
        2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),
        2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)};
    for (unsigned row=0; row<3; ++row) {
        for (unsigned col=0; col<3; ++col) m.m[row][col]=static_cast<float>(r[row*3+col]);
        m.m[row][3]=static_cast<float>(v.eye_pose[4+row]);
    }
    return m;
}

void PicoSteamvrDisplay::GetWindowBounds(int32_t *x, int32_t *y, uint32_t *width, uint32_t *height)
{
    *x=*y=0; *width=config.width; *height=config.height;
}

void PicoSteamvrDisplay::GetRecommendedRenderTargetSize(uint32_t *width, uint32_t *height)
{
    *width=std::max(config.views[0].render[0],config.views[1].render[0]);
    *height=std::max(config.views[0].render[1],config.views[1].render[1]);
}

void PicoSteamvrDisplay::GetEyeOutputViewport(vr::EVREye eye, uint32_t *x, uint32_t *y, uint32_t *width, uint32_t *height)
{
    const auto &v=config.views[eye==vr::Eye_Left?0:1];
    *x=v.viewport[0]; *y=v.viewport[1]; *width=v.viewport[2]; *height=v.viewport[3];
}

void PicoSteamvrDisplay::GetProjectionRaw(vr::EVREye eye, float *left, float *right, float *top, float *bottom)
{
    const auto &v=config.views[eye==vr::Eye_Left?0:1];
    *left=static_cast<float>(std::tan(v.fov[0])); *right=static_cast<float>(std::tan(v.fov[1]));
    *top=static_cast<float>(-std::tan(v.fov[2])); *bottom=static_cast<float>(-std::tan(v.fov[3]));
}

vr::DistortionCoordinates_t PicoSteamvrDisplay::ComputeDistortion(vr::EVREye eye, float u, float v)
{
    vr::DistortionCoordinates_t invalid{{-1,-1},{-1,-1},{-1,-1}};
    if ((eye!=vr::Eye_Left && eye!=vr::Eye_Right) || !std::isfinite(u) || !std::isfinite(v) ||
        u<0 || u>1 || v<0 || v>1) return invalid;
    const auto &view=config.views[eye==vr::Eye_Left?0:1];
    const auto &r=view.rotation;
    const double px=2*u-1, py=1-2*v;
    const double logical_u=(r[0]*px+r[2]*py+1)*.5;
    const double logical_v=(1-r[1]*px-r[3]*py)*.5;
    const double x=view.tangent_scale[0]*logical_u+view.tangent_offset[0];
    const double y=view.tangent_scale[1]*logical_v+view.tangent_offset[1];
    const double rsq=x*x+y*y, radius=std::sqrt(rsq);
    double scale=0;
    for (int i=10; i>=0; --i) scale=scale*rsq+view.radial[i];
    const double *c=view.chromatic;
    const double factors[3]={1+c[0]+rsq*c[1]+radius*c[4],1,1+c[2]+rsq*c[3]+radius*c[5]};
    vr::DistortionCoordinates_t result{};
    float *channels[]={result.rfRed,result.rfGreen,result.rfBlue};
    const double left=std::tan(view.fov[0]),right=std::tan(view.fov[1]);
    const double up=std::tan(view.fov[2]),down=std::tan(view.fov[3]);
    for (unsigned i=0; i<3; ++i) {
        channels[i][0]=static_cast<float>((x*scale*factors[i]-left)/(right-left));
        channels[i][1]=static_cast<float>((up-y*scale*factors[i])/(up-down));
        if (!std::isfinite(channels[i][0]) || !std::isfinite(channels[i][1])) return invalid;
    }
    return result;
}
