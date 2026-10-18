#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define DRM_DISPLAY_MODE_LEN 32
typedef struct {
    uint32_t clock;
    uint16_t hdisplay, hsync_start, hsync_end, htotal, hskew;
    uint16_t vdisplay, vsync_start, vsync_end, vtotal, vscan;
    uint32_t vrefresh, flags;
    char name[DRM_DISPLAY_MODE_LEN];
} drmModeModeInfo;
typedef struct {
    int Clock, HDisplay, HSyncStart, HSyncEnd, HTotal, HSkew;
    int VDisplay, VSyncStart, VSyncEnd, VTotal, VScan;
    unsigned Flags;
    char *name;
} DisplayModeRec, *DisplayModePtr;
typedef struct { int count_modes; drmModeModeInfo *modes; } drmModeConnectorRec, *drmModeConnectorPtr;
typedef struct { drmModeConnectorPtr mode_output; } drmmode_output_private_rec, *drmmode_output_private_ptr;
typedef struct { void *driver_private; } xf86OutputRec;
typedef struct { int num_output; xf86OutputRec **output; } xf86CrtcConfigRec, *xf86CrtcConfigPtr;
typedef struct { xf86CrtcConfigPtr config; } ScrnInfoRec, *ScrnInfoPtr;
#define XF86_CRTC_CONFIG_PTR(scrn) ((scrn)->config)

#include "driver.inc"

int main(void)
{
    drmModeModeInfo modes[] = {
        {.clock=382164, .hdisplay=1920, .hsync_start=2032, .hsync_end=2056,
         .htotal=2144, .vdisplay=3664, .vsync_start=3678, .vsync_end=3679,
         .vtotal=3686, .vrefresh=120, .flags=0x100000, .name="native120"},
    };
    drmModeConnectorRec connector = {1, modes};
    drmmode_output_private_rec private = {&connector};
    xf86OutputRec output = {&private}, *outputs[] = {&output};
    xf86CrtcConfigRec config = {1, outputs};
    ScrnInfoRec scrn = {&config};
    DisplayModeRec mode = {382164, 1920, 2032, 2056, 2144, 0,
                           3664, 3678, 3679, 3686, 0, 0x100000, "native120"};
    drmModeModeInfo result;
    drmmode_ConvertToKMode((ScrnInfoPtr)&scrn, &result, &mode);
#ifdef EXPECT_OLD
    assert(result.vrefresh == 0);
    return 0;
#else
    assert(result.vrefresh == 120);
    int *fields[] = {&mode.Clock, &mode.HDisplay, &mode.HSyncStart, &mode.HSyncEnd,
        &mode.HTotal, &mode.HSkew, &mode.VDisplay, &mode.VSyncStart, &mode.VSyncEnd,
        &mode.VTotal, &mode.VScan};
    for (unsigned i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
        (*fields[i])++;
        drmmode_ConvertToKMode((ScrnInfoPtr)&scrn, &result, &mode);
        assert(result.vrefresh == 0);
        (*fields[i])--;
    }
    mode.Flags ^= 1;
    drmmode_ConvertToKMode((ScrnInfoPtr)&scrn, &result, &mode);
    assert(result.vrefresh == 0);
    mode.Flags ^= 1;
    mode.name = "renamed";
    drmmode_ConvertToKMode((ScrnInfoPtr)&scrn, &result, &mode);
    assert(result.vrefresh == 120);
    private.mode_output = NULL;
    drmmode_ConvertToKMode((ScrnInfoPtr)&scrn, &result, &mode);
    assert(result.vrefresh == 0);
    puts("kernel refresh preserved only for matching complete timings and flags");
    return 0;
#endif
}
