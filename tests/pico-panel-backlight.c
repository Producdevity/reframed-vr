#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define EPROBE_DEFER 517
#define DSI_DEBUG(...) ((void)0)
#define DSI_ERR(...) ((void)0)
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
#define MAX_BL_SCALE_LEVEL 1024
#define MAX_SV_BL_SCALE_LEVEL 65535
#define MAX_BL_LEVEL 4095
typedef uint32_t u32;
enum { DSI_BACKLIGHT_UNKNOWN, DSI_BACKLIGHT_PWM, DSI_BACKLIGHT_WLED,
       DSI_BACKLIGHT_DCS, DSI_BACKLIGHT_GPIO, DSI_BACKLIGHT_EXTERNAL };
enum { BL_UPDATE_NONE, BL_UPDATE_DELAY_UNTIL_FIRST_FRAME };
struct dsi_parser_utils {
    void *data;
    const void *(*get_property)(void *, const char *, void *);
    int (*get_named_gpio)(void *, const char *, int);
    int (*read_u32)(void *, const char *, u32 *);
};
struct dsi_panel {
    const char *type, *name;
    struct dsi_parser_utils utils;
    struct {
        int type, bklt_brightness_gpio[3], bl_update, en_gpio;
        u32 bl_scale, bl_scale_sv, bl_min_level, bl_max_level;
        u32 brightness_max_level, bl_dcs_subtype;
    } bl_config;
};
static const char *control, *missing;
static int enable_gpio, pwm_result;
static bool gpio_is_valid(int gpio) { return gpio >= 0; }
static int gpio_request(int gpio, const char *label)
{
    assert(gpio >= 0 && label);
    return 0;
}
static int dsi_panel_parse_bl_pwm_config(struct dsi_panel *panel)
{
    assert(panel->bl_config.type == DSI_BACKLIGHT_PWM);
    return pwm_result;
}
static const void *property(void *data, const char *name, void *length)
{
    assert(!data && !length);
    return strstr(name, "pmic-control-type") ? control : NULL;
}
static int named_gpio(void *data, const char *name, int index)
{
    assert(!data && !index);
    return !strcmp(name, "qcom,platform-bklight-en-gpio") ? enable_gpio : 1;
}
static int read_u32(void *data, const char *name, u32 *value)
{
    assert(!data);
    if (!strcmp(name, missing))
        return -EINVAL;
    *value = 7;
    return 0;
}

#include "driver.inc"

int main(void)
{
    const char *optional[] = {
        "qcom,mdss-dsi-bl-min-level", "qcom,mdss-dsi-bl-max-level",
        "qcom,mdss-brightness-max-level", "qcom,mdss-dsi-bl-ctrl-dcs-subtype",
        "none",
    };
    const char *types[] = {"bl_ctrl_gpio", "bl_ctrl_pwm", "bl_ctrl_dcs",
        "bl_ctrl_wled", "bl_ctrl_external", "unknown"};
    unsigned defects = 0, checks = 0;
    for (unsigned t = 0; t < sizeof(types) / sizeof(types[0]); ++t) {
        for (unsigned i = 0; i < sizeof(optional) / sizeof(optional[0]); ++i) {
            struct dsi_panel panel = {.type = "primary", .name = "stock-panel",
                .utils = {.get_property = property, .get_named_gpio = named_gpio,
                          .read_u32 = read_u32}};
            control = types[t]; missing = optional[i];
            enable_gpio = 29; pwm_result = 0;
            if (dsi_panel_parse_bl_config(&panel)) ++defects;
            if (i == 3) assert(panel.bl_config.bl_dcs_subtype == 0);
            ++checks;
            enable_gpio = -EPROBE_DEFER;
            assert(dsi_panel_parse_bl_config(&panel) == -EPROBE_DEFER);
            ++checks;
            enable_gpio = -ENOENT;
            assert(!dsi_panel_parse_bl_config(&panel));
            ++checks;
            if (t == 1) {
                enable_gpio = 29; pwm_result = -EIO;
                assert(dsi_panel_parse_bl_config(&panel) == -EIO);
                ++checks;
            }
        }
    }
#ifdef EXPECT_OLD
    assert(defects > 0);
#else
    assert(defects == 0);
#endif
    printf("%u backlight checks; %u default defects\n", checks, defects);
    return 0;
}
