#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#define CHECK(call) do { if ((call) < 0) { perror(#call); exit(1); } } while (0)

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "/dev/dri/card0")) return 2;
    alarm(25);
    int fd = open(argv[1], O_RDWR | O_CLOEXEC);
    CHECK(fd);
    drmVersionPtr version = drmGetVersion(fd);
    if (!version || strcmp(version->name, "msm_drm")) return 2;
    printf("DRM driver: %s\n", version->name);
    drmFreeVersion(version);
    CHECK(drmSetMaster(fd));
    drmModeRes *resources = drmModeGetResources(fd);
    if (!resources) return 1;
    drmModeConnector *connector = NULL;
    drmModeModeInfo mode = {0};
    for (int i = 0; i < resources->count_connectors; ++i) {
        drmModeConnector *candidate = drmModeGetConnector(fd, resources->connectors[i]);
        if (!candidate) return 1;
        if (candidate->connector_type == DRM_MODE_CONNECTOR_DSI &&
            candidate->connection == DRM_MODE_CONNECTED) {
            for (int j = 0; j < candidate->count_modes; ++j) {
                drmModeModeInfo *m = &candidate->modes[j];
                printf("DSI mode: %s %ux%u refresh=%u clock=%u totals=%ux%u\n",
                       m->name, m->hdisplay, m->vdisplay, m->vrefresh, m->clock,
                       m->htotal, m->vtotal);
                if (m->hdisplay == 1920 && m->vdisplay == 3664) mode = *m;
            }
            if (mode.hdisplay) { connector = candidate; break; }
        }
        drmModeFreeConnector(candidate);
    }
    if (!connector) { fputs("No expected Pico DSI mode\n", stderr); return 2; }
    uint32_t crtc = 0;
    unsigned crtc_index = 0;
    for (int i = 0; i < connector->count_encoders && !crtc; ++i) {
        drmModeEncoder *encoder = drmModeGetEncoder(fd, connector->encoders[i]);
        if (!encoder) return 1;
        for (int j = 0; j < resources->count_crtcs; ++j) {
            if (encoder->possible_crtcs & (1u << j)) {
                crtc = resources->crtcs[j]; crtc_index = j; break;
            }
        }
        drmModeFreeEncoder(encoder);
    }
    if (!crtc || crtc_index > 1) return 2;
    drmModeCrtc *initial = drmModeGetCrtc(fd, crtc);
    if (!initial) return 1;
    printf("Initial CRTC: valid=%d framebuffer=%u mode=%s refresh=%u\n",
           initial->mode_valid, initial->buffer_id, initial->mode.name, initial->mode.vrefresh);
    bool found = false;
    /* The vendor driver refuses a refresh change during splash handoff. */
    for (int i = 0; i < connector->count_modes; ++i) {
        drmModeModeInfo *m = &connector->modes[i];
        if (m->hdisplay != 1920 || m->vdisplay != 3664) continue;
        if ((initial->mode_valid && m->vrefresh == initial->mode.vrefresh) ||
            (!initial->mode_valid && (m->type & DRM_MODE_TYPE_PREFERRED))) {
            mode = *m; found = true; break;
        }
    }
    drmModeFreeCrtc(initial);
    if (!found) { fputs("No matching initial/preferred Pico mode\n", stderr); return 2; }
    struct drm_mode_create_dumb dumb = {.width = mode.hdisplay,
        .height = mode.vdisplay, .bpp = 32};
    CHECK(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &dumb));
    uint32_t framebuffer;
    CHECK(drmModeAddFB(fd, dumb.width, dumb.height, 24, 32, dumb.pitch,
                       dumb.handle, &framebuffer));
    struct drm_mode_map_dumb map = {.handle = dumb.handle};
    CHECK(drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map));
    uint8_t *pixels = mmap(NULL, dumb.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
    if (pixels == MAP_FAILED) { perror("mmap"); return 1; }
    const uint32_t colors[] = {0xff102030, 0xff30a0e0, 0xff30b060, 0xffd06030};
    for (uint32_t y = 0; y < dumb.height; ++y) {
        uint32_t *row = (uint32_t *)(pixels + y * dumb.pitch);
        for (uint32_t x = 0; x < dumb.width; ++x)
            row[x] = colors[((x / 240) + ((y % 1832) / 240)) % 4];
    }
    printf("Setting connector=%u crtc=%u mode=%s framebuffer=%u\n",
           connector->connector_id, crtc, mode.name, framebuffer);
    fflush(stdout);
    CHECK(drmModeSetCrtc(fd, crtc, framebuffer, 0, 0, &connector->connector_id, 1, &mode));
    for (unsigned i = 0; i < 5; ++i) {
        drmVBlank blank = {.request = {.type = DRM_VBLANK_RELATIVE |
            (crtc_index ? DRM_VBLANK_SECONDARY : 0), .sequence = 1}};
        CHECK(drmWaitVBlank(fd, &blank));
        printf("VBLANK sequence=%u\n", blank.reply.sequence);
    }
    sleep(2);
    CHECK(drmModeSetCrtc(fd, crtc, 0, 0, 0, NULL, 0, NULL));
    CHECK(drmModeRmFB(fd, framebuffer));
    CHECK(munmap(pixels, dumb.size));
    struct drm_mode_destroy_dumb destroy = {.handle = dumb.handle};
    CHECK(drmIoctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy));
    drmModeFreeConnector(connector);
    drmModeFreeResources(resources);
    CHECK(drmDropMaster(fd));
    close(fd);
    puts("PICO_KMS_SMOKE_PASS: pattern modeset, five vblanks, and disable");
    return 0;
}
