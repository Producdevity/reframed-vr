#include <assert.h>
#include <stdbool.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <xf86drmMode.h>

struct list_head { struct list_head *next, *prev; };
#define MAX2(a, b) ((a) > (b) ? (a) : (b))
#include "display-refresh-under-test.h"

int main(void)
{
    unsigned checks = 0;
    for (unsigned rate = 72; rate <= 120; rate += 6) {
        for (unsigned opt = 0; opt < 2; ++opt) {
            for (unsigned scan = 0; scan < 3; ++scan) {
                drmModeModeInfo drm = {
                    .clock = 123456, .hdisplay = 1920, .hsync_start = 1930,
                    .hsync_end = 1940, .htotal = 2000, .hskew = 2,
                    .vdisplay = 3664, .vsync_start = 3670, .vsync_end = 3680,
                    .vtotal = 3700, .vscan = scan, .flags = DRM_MODE_FLAG_PHSYNC,
                    .vrefresh = rate,
                };
                struct wsi_display_mode mode = {0};
                wsi_display_mode_set_drm(&mode, &drm, opt);
                assert(wsi_display_mode_matches_drm(&mode, &drm));
                double calculated = 123456000.0 / (2000.0 * 3700 * MAX2(scan, 1));
                assert(fabs(wsi_display_mode_refresh(&mode) - (opt ? rate : calculated)) < 1e-9);
                drm.vrefresh++;
                assert(wsi_display_mode_matches_drm(&mode, &drm) == !opt);
                drm.vrefresh = 0;
                wsi_display_mode_set_drm(&mode, &drm, opt);
                assert(fabs(wsi_display_mode_refresh(&mode) - calculated) < 1e-9);
                assert(wsi_display_mode_matches_drm(&mode, &drm));
                drm.hsync_start++;
                assert(!wsi_display_mode_matches_drm(&mode, &drm));
                checks += 6;
            }
        }
    }
    drmModeModeInfo ntsc = {.clock = 148352, .htotal = 2200, .vtotal = 1125, .vrefresh = 60};
    struct wsi_display_mode mode = {0};
    wsi_display_mode_set_drm(&mode, &ntsc, false);
    double refresh = wsi_display_mode_refresh(&mode);
    assert(refresh > 59.93 && refresh < 59.95);
    printf("MESA_DISPLAY_REFRESH_PASS checks=%u fractional_refresh=%.8f\n", checks + 1, refresh);
    return 0;
}
