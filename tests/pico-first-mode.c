#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define DSI_MODE_FLAG_DMS (1u << 0)
#define DSI_MODE_FLAG_VRR (1u << 1)
#define DSI_MODE_FLAG_POMS (1u << 2)
#define DSI_MODE_FLAG_DYN_CLK (1u << 3)
#define DSI_MODE_FLAG_SEAMLESS (1u << 4)
#define DSI_OP_VIDEO_MODE 1
#define DSI_VALIDATE_FLAG_ALLOW_ADJUST 1
#define DSI_ERR(...) ((void)0)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define to_dsi_bridge(ptr) container_of(ptr, struct dsi_bridge, base)

struct drm_display_mode { unsigned refresh, panel_mode, private_flags; int *private; };
struct drm_crtc;
struct drm_crtc_state {
    struct drm_display_mode mode;
    struct drm_crtc *crtc;
    bool enable, active_changed;
};
struct drm_crtc { struct drm_crtc_state *state; };
struct drm_encoder { struct drm_crtc *crtc; };
struct drm_bridge { struct drm_encoder *encoder; };
struct dsi_panel { unsigned num_timing_nodes; };
struct dsi_display {
    struct dsi_panel *panel;
    struct { unsigned panel_mode; } config;
    bool is_cont_splash_enabled;
    const char *name;
};
struct dsi_bridge { struct drm_bridge base; struct dsi_display *display; unsigned id; };
struct dsi_display_mode_priv_info { bool dsc_enabled; int dsc; };
struct dsi_timing { unsigned refresh; bool dsc_enabled; int *dsc; };
struct dsi_display_mode {
    struct dsi_timing timing;
    unsigned dsi_mode_flags, panel_mode;
    struct dsi_display_mode_priv_info *priv_info;
};

static struct dsi_display_mode_priv_info default_priv_info;
static struct dsi_display_mode cached;
static int validate_error, change_error;
static unsigned conversions;

static void convert_to_dsi_mode(const struct drm_display_mode *mode, struct dsi_display_mode *out)
{
    memset(out, 0, sizeof(*out));
    out->timing.refresh = mode->refresh;
    out->panel_mode = mode->panel_mode;
}

static int dsi_display_find_mode(struct dsi_display *display, struct dsi_display_mode *mode,
                                 struct dsi_display_mode **out)
{
    (void)display; (void)mode;
    *out = &cached;
    return 0;
}

static int dsi_display_validate_mode(struct dsi_display *display, struct dsi_display_mode *mode, int flags)
{
    (void)display; (void)mode; (void)flags;
    return validate_error;
}

static int dsi_display_validate_mode_change(struct dsi_display *display,
                                           struct dsi_display_mode *current, struct dsi_display_mode *next)
{
    (void)display; (void)current; (void)next;
    return change_error;
}

static bool drm_mode_equal(const struct drm_display_mode *a, const struct drm_display_mode *b)
{
    return a->refresh == b->refresh && a->panel_mode == b->panel_mode;
}

static void dsi_convert_to_drm_mode(const struct dsi_display_mode *mode, struct drm_display_mode *out)
{
    conversions++;
    out->refresh = mode->timing.refresh;
    out->panel_mode = mode->panel_mode;
    out->private_flags = mode->dsi_mode_flags;
    out->private = (int *)mode->priv_info;
}

#include "mode-fixup.inc"

static unsigned checks, failures, cases;
#define CHECK(value) do { checks++; if (!(value)) { \
    if (failures < 4) fprintf(stderr, "case %u failed: %s\n", cases, #value); \
    failures++; } } while (0)

int main(void)
{
    const unsigned skips_prepare = DSI_MODE_FLAG_SEAMLESS | DSI_MODE_FLAG_VRR | DSI_MODE_FLAG_DYN_CLK;
    const unsigned transition_flags = DSI_MODE_FLAG_VRR | DSI_MODE_FLAG_POMS | DSI_MODE_FLAG_DYN_CLK;
    for (unsigned splash = 0; splash < 2; splash++)
    for (unsigned video = 0; video < 2; video++)
    for (unsigned active_changed = 0; active_changed < 2; active_changed++)
    for (unsigned different = 0; different < 2; different++)
    for (unsigned connected = 0; connected < 2; connected++)
    for (unsigned flags = 0; flags < 32; flags++)
    for (unsigned error = 0; error < 3; error++) {
        cases++;
        struct drm_crtc_state current = {.mode = {.refresh = 120, .panel_mode = video}, .enable = true};
        struct drm_crtc crtc = {.state = &current};
        struct drm_encoder encoder = {.crtc = &crtc};
        struct dsi_panel panel = {.num_timing_nodes = 1};
        struct dsi_display display = {.panel = &panel, .config = {.panel_mode = video},
            .is_cont_splash_enabled = splash, .name = "test"};
        struct dsi_bridge bridge = {.base = {.encoder = connected ? &encoder : NULL}, .display = &display};
        struct drm_crtc_state requested = {.mode = {.refresh = different ? 90 : 120, .panel_mode = video},
            .crtc = &crtc, .enable = true, .active_changed = active_changed};
        struct drm_display_mode adjusted = requested.mode, before = adjusted;
        cached = (struct dsi_display_mode){.timing = {.refresh = requested.mode.refresh},
            .dsi_mode_flags = flags, .panel_mode = video, .priv_info = &default_priv_info};
        validate_error = error == 1 ? -EINVAL : 0;
        change_error = error == 2 ? -EINVAL : 0;
        conversions = 0;
        unsigned effective = flags;
        if (connected && different && !(flags & transition_flags) && (!active_changed || splash))
            effective |= DSI_MODE_FLAG_DMS;
        bool invalid = validate_error || (connected && change_error) ||
            (active_changed && (effective & transition_flags));
        bool unsupported = splash && video && (effective & DSI_MODE_FLAG_DMS) && !(effective & skips_prepare);
        bool expected = !invalid && !unsupported;
        bool accepted = dsi_bridge_mode_fixup(&bridge.base, &requested.mode, &adjusted);
        CHECK(accepted == expected);
        CHECK(conversions == (unsigned)expected);
        if (!expected) CHECK(before.refresh == adjusted.refresh && before.panel_mode == adjusted.panel_mode &&
                             before.private_flags == adjusted.private_flags && before.private == adjusted.private);
        else CHECK(adjusted.private_flags == effective);
    }
    printf("PICO_FIRST_MODE_%s cases=%u checks=%u failures=%u\n",
           failures ? "FAIL" : "PASS", cases, checks, failures);
    return failures ? 1 : 0;
}
