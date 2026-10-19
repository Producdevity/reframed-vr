#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/utsname.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#define REQUIRE(value) do { if (!(value)) { \
    fprintf(stderr, "Pico display handoff failed: %s\n", #value); goto done; \
} } while (0)
#define SYSTEM(call) do { if ((call) < 0) { perror(#call); goto done; } } while (0)

static ssize_t read_file(const char *path, char *data, size_t capacity)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t size = 0;
    ssize_t count;
    while (size < capacity - 1) {
        count = read(fd, data + size, capacity - 1 - size);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        size += (size_t)count;
    }
    if (size == capacity - 1) {
        char extra;
        do { count = read(fd, &extra, 1); } while (count < 0 && errno == EINTR);
        if (count > 0) { errno = EOVERFLOW; count = -1; }
    }
    int saved = errno;
    close(fd);
    errno = saved;
    if (count < 0) return -1;
    data[size] = '\0';
    return (ssize_t)size;
}

static bool uuid(const char *text)
{
    if (strlen(text) != 36) return false;
    for (unsigned i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (text[i] != '-') return false;
        } else if (!strchr("0123456789abcdef", text[i])) return false;
    }
    return true;
}

static bool native_identity(const char *serial, const char *expected_boot, char boot[64])
{
    struct utsname system;
    char init[32], compatible[128], command[8192];
    const char board[] = "qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0";
    if (getuid() || uname(&system) || strcmp(system.sysname, "Linux") || strcmp(system.machine, "aarch64") ||
        read_file("/proc/1/comm", init, sizeof(init)) < 0 || strcmp(init, "systemd\n") ||
        read_file("/proc/device-tree/compatible", compatible, sizeof(compatible)) != (ssize_t)sizeof(board) - 1 ||
        memcmp(compatible, board, sizeof(board) - 1) ||
        read_file("/proc/sys/kernel/random/boot_id", boot, 64) < 0 ||
        read_file("/proc/cmdline", command, sizeof(command)) < 0) return false;
    boot[strcspn(boot, "\n")] = '\0';
    if (!uuid(boot) || (expected_boot && strcmp(expected_boot, boot))) return false;
    char token[192];
    if (snprintf(token, sizeof(token), "androidboot.serialno=%s", serial) >= (int)sizeof(token)) return false;
    for (char *word = strtok(command, " \n"); word; word = strtok(NULL, " \n"))
        if (!strcmp(word, token)) return true;
    return false;
}

struct observation { bool received; uint64_t sequence, ns; };

static void sequence_event(int fd, uint64_t sequence, uint64_t ns, uint64_t user)
{
    (void)fd;
    struct observation *event = (struct observation *)(uintptr_t)user;
    event->received = true;
    event->sequence = sequence;
    event->ns = ns;
}

static bool next_vblank(int fd, uint32_t crtc, struct observation *event)
{
    uint64_t queued;
    if (drmCrtcQueueSequence(fd, crtc, DRM_CRTC_SEQUENCE_RELATIVE, 1, &queued,
                             (uint64_t)(uintptr_t)event)) return false;
    struct pollfd descriptor = {.fd = fd, .events = POLLIN};
    int ready;
    do { ready = poll(&descriptor, 1, 1000); } while (ready < 0 && errno == EINTR);
    if (ready != 1 || !(descriptor.revents & POLLIN)) return false;
    drmEventContext context = {.version = 4, .sequence_handler = sequence_event};
    return !drmHandleEvent(fd, &context) && event->received && event->ns && event->sequence >= queued;
}

int main(int argc, char **argv)
{
    const char *serial = NULL, *serial_file = NULL, *expected_boot = NULL;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc) { fprintf(stderr, "Missing handoff argument\n"); return 2; }
        if (!strcmp(argv[i], "--boot-serial") && !serial) serial = argv[i + 1];
        else if (!strcmp(argv[i], "--boot-serial-file") && !serial_file) serial_file = argv[i + 1];
        else if (!strcmp(argv[i], "--boot-id") && !expected_boot) expected_boot = argv[i + 1];
        else { fprintf(stderr, "Invalid handoff arguments\n"); return 2; }
    }
    char configured_serial[130], boot[64];
    if (serial_file) {
        ssize_t size = read_file(serial_file, configured_serial, sizeof(configured_serial));
        if (serial || size < 0 || (size_t)size != strlen(configured_serial)) return 2;
        if (size && configured_serial[size - 1] == '\n') configured_serial[size - 1] = '\0';
        serial = configured_serial;
    }
    if (!serial || !*serial || strlen(serial) > 127 ||
        strspn(serial, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != strlen(serial) ||
        (expected_boot && !uuid(expected_boot))) {
        fprintf(stderr, "Require --boot-serial SERIAL or --boot-serial-file FILE, with optional --boot-id UUID\n");
        return 2;
    }
    if (!native_identity(serial, expected_boot, boot)) {
        fprintf(stderr, "Require the selected native Pico Linux boot\n");
        return 2;
    }

    alarm(20);
    int fd = -1;
    bool active = false, success = false;
    uint32_t framebuffer = 0, crtc = 0;
    void *pixels = MAP_FAILED;
    drmModeRes *resources = NULL;
    drmVersionPtr version = NULL;
    drmModeConnector *connector = NULL;
    drmModeEncoder *encoder = NULL;
    drmModeCrtc *initial = NULL;
    drmModeModeInfo mode = {0};
    struct drm_mode_create_dumb dumb = {0};
    struct observation events[5] = {0};
    uint64_t period = 0;
    fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
    SYSTEM(fd);
    version = drmGetVersion(fd);
    REQUIRE(version && version->name);
    bool expected_driver = !strcmp(version->name, "msm_drm");
    drmFreeVersion(version);
    version = NULL;
    REQUIRE(expected_driver);
    SYSTEM(drmSetMaster(fd));
    resources = drmModeGetResources(fd);
    REQUIRE(resources);
    for (int i = 0; i < resources->count_connectors; i++) {
        drmModeConnector *candidate = drmModeGetConnector(fd, resources->connectors[i]);
        REQUIRE(candidate);
        if (candidate->connection == DRM_MODE_CONNECTED && candidate->connector_type == DRM_MODE_CONNECTOR_DSI) {
            if (connector) { drmModeFreeConnector(candidate); goto done; }
            connector = candidate;
        } else drmModeFreeConnector(candidate);
    }
    REQUIRE(connector && connector->encoder_id);
    encoder = drmModeGetEncoder(fd, connector->encoder_id);
    REQUIRE(encoder && resources->count_crtcs > 0 && resources->count_crtcs <= 32);
    crtc = encoder->crtc_id;
    for (int i = 0; !crtc && i < resources->count_crtcs; i++)
        if (encoder->possible_crtcs & (UINT32_C(1) << i)) crtc = resources->crtcs[i];
    REQUIRE(crtc);
    initial = drmModeGetCrtc(fd, crtc);
    REQUIRE(initial);
    if (initial->mode_valid) {
        mode = initial->mode;
    } else {
        /* Continuous splash can leave the encoder unbound and the CRTC mode unset. */
        for (int i = 0; i < connector->count_modes; i++) {
            const drmModeModeInfo *candidate = &connector->modes[i];
            if (candidate->hdisplay == 1920 && candidate->vdisplay == 3664 &&
                candidate->vrefresh == 120 && (candidate->type & DRM_MODE_TYPE_PREFERRED)) {
                REQUIRE(!mode.hdisplay);
                mode = *candidate;
            }
        }
    }
    REQUIRE(mode.hdisplay == 1920 && mode.vdisplay == 3664 && mode.vrefresh == 120);

    dumb.width = mode.hdisplay;
    dumb.height = mode.vdisplay;
    dumb.bpp = 32;
    SYSTEM(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &dumb));
    REQUIRE(dumb.pitch >= dumb.width * 4 && dumb.size >= (uint64_t)dumb.pitch * dumb.height &&
            dumb.size <= 64 * 1024 * 1024);
    SYSTEM(drmModeAddFB(fd, dumb.width, dumb.height, 24, 32, dumb.pitch, dumb.handle, &framebuffer));
    struct drm_mode_map_dumb map = {.handle = dumb.handle};
    SYSTEM(drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map));
    pixels = mmap(NULL, dumb.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
    REQUIRE(pixels != MAP_FAILED);
    memset(pixels, 0, dumb.size);
    /* Preserve the vendor mode, including its supplied refresh and private flags. */
    SYSTEM(drmModeSetCrtc(fd, crtc, framebuffer, 0, 0, &connector->connector_id, 1, &mode));
    active = true;
    for (unsigned i = 0; i < 5; i++) {
        REQUIRE(next_vblank(fd, crtc, &events[i]));
        if (i) REQUIRE(events[i].sequence > events[i - 1].sequence && events[i].ns > events[i - 1].ns);
    }
    period = (events[4].ns - events[0].ns) / (events[4].sequence - events[0].sequence);
    REQUIRE(period >= UINT64_C(1000000000) / 120 * 95 / 100 &&
            period <= UINT64_C(1000000000) / 120 * 105 / 100);
    success = true;

done:
    if (active && drmModeSetCrtc(fd, crtc, 0, 0, 0, NULL, 0, NULL)) { perror("disable CRTC"); success = false; }
    if (framebuffer && drmModeRmFB(fd, framebuffer)) { perror("remove framebuffer"); success = false; }
    if (pixels != MAP_FAILED && munmap(pixels, dumb.size)) { perror("unmap framebuffer"); success = false; }
    if (dumb.handle) {
        struct drm_mode_destroy_dumb destroy = {.handle = dumb.handle};
        if (drmIoctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy)) { perror("destroy framebuffer"); success = false; }
    }
    bool initial_mode_valid = initial && initial->mode_valid;
    if (initial) drmModeFreeCrtc(initial);
    if (encoder) drmModeFreeEncoder(encoder);
    if (connector) drmModeFreeConnector(connector);
    if (resources) drmModeFreeResources(resources);
    if (version) drmFreeVersion(version);
    if (fd >= 0 && close(fd)) { perror("close DRM"); success = false; }
    if (!success) return 1;
    printf("PICO_DISPLAY_HANDOFF_READY {\"boot_serial\":\"%s\",\"boot_id\":\"%s\","
           "\"mode_hz\":120,\"initial_mode_valid\":%s,\"crtc\":%u,\"vblank_events\":5,\"period_ns\":%" PRIu64 ","
           "\"first_sequence\":%" PRIu64 ",\"last_sequence\":%" PRIu64 ","
           "\"first_ns\":%" PRIu64 ",\"last_ns\":%" PRIu64 ",\"released\":true}\n",
           serial, boot, initial_mode_valid ? "true" : "false", crtc, period,
           events[0].sequence, events[4].sequence, events[0].ns, events[4].ns);
    return 0;
}
