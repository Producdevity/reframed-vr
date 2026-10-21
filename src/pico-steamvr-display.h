#ifndef REFRAMED_PICO_STEAMVR_DISPLAY_H
#define REFRAMED_PICO_STEAMVR_DISPLAY_H

#include <openvr_driver.h>
#include <cstdint>

struct pico_steamvr_view {
    uint32_t viewport[4], render[2];
    double rotation[4], fov[4], eye_pose[7];
    double tangent_scale[2], tangent_offset[2], radial[11], chromatic[6];
};

struct pico_steamvr_display_config {
    char serial[128];
    uint32_t width, height;
    int64_t frame_interval_ns;
    pico_steamvr_view views[2];
};

bool pico_steamvr_display_valid(const pico_steamvr_display_config &config);
bool pico_steamvr_display_load(const char *path, pico_steamvr_display_config &config);
vr::HmdMatrix34_t pico_steamvr_eye_to_head(const pico_steamvr_view &view);

class PicoSteamvrDisplay final : public vr::IVRDisplayComponent {
    const pico_steamvr_display_config config;
public:
    explicit PicoSteamvrDisplay(const pico_steamvr_display_config &value) : config(value) {}
    void GetWindowBounds(int32_t *x, int32_t *y, uint32_t *width, uint32_t *height) override;
    bool IsDisplayOnDesktop() override { return false; }
    bool IsDisplayRealDisplay() override { return true; }
    void GetRecommendedRenderTargetSize(uint32_t *width, uint32_t *height) override;
    void GetEyeOutputViewport(vr::EVREye eye, uint32_t *x, uint32_t *y, uint32_t *width, uint32_t *height) override;
    void GetProjectionRaw(vr::EVREye eye, float *left, float *right, float *top, float *bottom) override;
    vr::DistortionCoordinates_t ComputeDistortion(vr::EVREye eye, float u, float v) override;
    bool ComputeInverseDistortion(vr::HmdVector2_t *, vr::EVREye, uint32_t, float, float) override { return false; }
};
#endif
