#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/sync_file.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "drm.h"

#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "DRM_SYNCOBJ_FAIL line %d: %s errno=%d\n", __LINE__, #x, errno); \
    exit(1); } } while (0)

struct sw_fence { uint32_t value; char name[32]; int32_t fence; };
#define SW_CREATE _IOWR('W', 0, struct sw_fence)
#define SW_INCREMENT _IOW('W', 1, uint32_t)
struct fence_refs { int32_t fd; uint32_t handle; uint32_t refs; };
#define TEST_REFS _IOWR('T', 0, struct fence_refs)

static void timed_out(int signal_number)
{
    (void)signal_number;
    static const char message[] = "DRM_SYNCOBJ_FAIL watchdog timeout\n";
    (void)write(STDERR_FILENO, message, sizeof(message)-1);
    (void)reboot(RB_POWER_OFF);
    _exit(1);
}

static uint64_t pointer(const void *p) { return (uintptr_t)p; }

static int64_t deadline(void)
{
    struct timespec ts;
    CHECK(clock_gettime(CLOCK_MONOTONIC, &ts) == 0);
    return (int64_t)ts.tv_sec * 1000000000 + ts.tv_nsec + 2000000000;
}

static unsigned fd_count(void)
{
    DIR *dir = opendir("/proc/self/fd");
    CHECK(dir);
    unsigned count = 0;
    while (readdir(dir)) ++count;
    closedir(dir);
    return count;
}

static void dump_virtual_nodes(void)
{
    const char *directories[] = {"/sys/bus/virtio/devices", "/sys/class/drm",
        "/sys/bus/platform/drivers/virtio-mmio"};
    for (unsigned i = 0; i < sizeof(directories) / sizeof(directories[0]); ++i) {
        DIR *dir = opendir(directories[i]);
        if (!dir) continue;
        struct dirent *entry;
        while ((entry = readdir(dir))) {
            if (entry->d_name[0] == '.') continue;
            printf("DRM_SYNCOBJ_VIRTUAL_NODE %s/%s\n", directories[i], entry->d_name);
            char path[512], value[256];
            snprintf(path, sizeof(path), "%s/%s/modalias", directories[i], entry->d_name);
            FILE *stream = fopen(path, "r");
            if (stream) {
                if (fgets(value, sizeof(value), stream)) printf("DRM_SYNCOBJ_ALIAS %s", value);
                fclose(stream);
            }
        }
        closedir(dir);
    }
}

static uint32_t create(int drm, uint32_t flags)
{
    struct drm_syncobj_create arg = {.flags = flags};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_CREATE, &arg) == 0);
    return arg.handle;
}

static void destroy(int drm, uint32_t handle)
{
    struct drm_syncobj_destroy arg = {.handle = handle};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_DESTROY, &arg) == 0);
}

static void signal_point(int drm, uint32_t handle, uint64_t point)
{
    struct drm_syncobj_timeline_array arg = {
        .handles = pointer(&handle), .points = pointer(&point), .count_handles = 1};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_TIMELINE_SIGNAL, &arg) == 0);
}

static int wait_point(int drm, uint32_t handle, uint64_t point, uint32_t flags, int64_t timeout)
{
    struct drm_syncobj_timeline_wait arg = {.handles = pointer(&handle),
        .points = pointer(&point), .count_handles = 1, .flags = flags, .timeout_nsec = timeout};
    return ioctl(drm, DRM_IOCTL_SYNCOBJ_TIMELINE_WAIT, &arg);
}

static uint64_t query(int drm, uint32_t handle)
{
    uint64_t point = UINT64_MAX;
    struct drm_syncobj_timeline_array arg = {
        .handles = pointer(&handle), .points = pointer(&point), .count_handles = 1};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_QUERY, &arg) == 0);
    return point;
}

static void transfer(int drm, uint32_t dst, uint64_t dst_point, uint32_t src, uint64_t src_point)
{
    struct drm_syncobj_transfer arg = {.dst_handle = dst, .dst_point = dst_point,
        .src_handle = src, .src_point = src_point};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_TRANSFER, &arg) == 0);
}

static int export_fd(int drm, uint32_t handle, uint32_t flags)
{
    struct drm_syncobj_handle arg = {.handle = handle, .flags = flags, .fd = -1};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_HANDLE_TO_FD, &arg) == 0 && arg.fd >= 0);
    return arg.fd;
}

static uint32_t import_fd(int drm, int fd)
{
    struct drm_syncobj_handle arg = {.fd = fd};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_FD_TO_HANDLE, &arg) == 0);
    return arg.handle;
}

static void import_fence(int drm, uint32_t handle, int fd)
{
    struct drm_syncobj_handle arg = {.handle = handle, .fd = fd,
        .flags = DRM_SYNCOBJ_FD_TO_HANDLE_FLAGS_IMPORT_SYNC_FILE};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_FD_TO_HANDLE, &arg) == 0);
}

static void poll_fence(int fd, int ready)
{
    struct pollfd p = {.fd = fd, .events = POLLIN};
    int ret = poll(&p, 1, ready ? 2000 : 0);
    CHECK(ready ? ret == 1 && p.revents == POLLIN : ret == 0);
}

static int new_software_fence(int *software)
{
    *software = open("/sys/kernel/debug/sync/sw_sync", O_RDWR | O_CLOEXEC);
    CHECK(*software >= 0);
    struct sw_fence arg = {.value = 1, .name = "drm-syncobj-test", .fence = -1};
    CHECK(ioctl(*software, SW_CREATE, &arg) == 0 && arg.fence >= 0);
    return arg.fence;
}

static void complete(int software)
{
    uint32_t increment = 1;
    CHECK(ioctl(software, SW_INCREMENT, &increment) == 0);
}

static void future_point(int drm)
{
    int software, fence = new_software_fence(&software), socket[2];
    uint32_t timeline = create(drm, 0), binary = create(drm, 0);
    int object = export_fd(drm, timeline, 0);
    CHECK(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, socket) == 0);
    pid_t child = fork();
    CHECK(child >= 0);
    if (!child) {
        close(socket[0]); close(drm); close(software); close(fence);
        int peer = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
        CHECK(peer >= 0);
        uint32_t imported = import_fd(peer, object);
        close(object);
        CHECK(write(socket[1], "r", 1) == 1);
        CHECK(wait_point(peer, imported, 42, DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL |
            DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT | DRM_SYNCOBJ_WAIT_FLAGS_WAIT_AVAILABLE,
            deadline()) == 0);
        CHECK(wait_point(peer, imported, 42, DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL, 0) == -1 && errno == ETIME);
        CHECK(write(socket[1], "p", 1) == 1);
        CHECK(wait_point(peer, imported, 42, DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL, deadline()) == 0);
        destroy(peer, imported); close(peer); close(socket[1]);
        _exit(0);
    }
    close(socket[1]); close(object);
    char ready;
    CHECK(read(socket[0], &ready, 1) == 1 && ready == 'r');
    struct pollfd p = {.fd = socket[0], .events = POLLIN};
    CHECK(poll(&p, 1, 100) == 0);
    import_fence(drm, binary, fence);
    transfer(drm, timeline, 42, binary, 0);
    CHECK(read(socket[0], &ready, 1) == 1 && ready == 'p');
    CHECK(query(drm, timeline) < 42);
    poll_fence(fence, 0);
    complete(software);
    int status;
    CHECK(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    CHECK(query(drm, timeline) == 42);
    destroy(drm, binary); destroy(drm, timeline);
    close(socket[0]); close(software); close(fence);
    puts("DRM_SYNCOBJ_FUTURE_AND_OPAQUE_FD_PASS");
}

static void transfers(int drm)
{
    int first, second, a = new_software_fence(&first), b = new_software_fence(&second);
    uint32_t binary = create(drm, 0), timeline = create(drm, 0), copy = create(drm, 0);
    import_fence(drm, binary, a); transfer(drm, timeline, 7, binary, 0);
    import_fence(drm, binary, b); transfer(drm, timeline, 8, binary, 0);
    transfer(drm, copy, 1ULL << 40, timeline, 8);
    transfer(drm, binary, 0, copy, 1ULL << 40);
    int exported = export_fd(drm, binary, DRM_SYNCOBJ_HANDLE_TO_FD_FLAGS_EXPORT_SYNC_FILE);
    destroy(drm, copy); destroy(drm, timeline); destroy(drm, binary);
    close(a); close(b);
    poll_fence(exported, 0);
    complete(second); poll_fence(exported, 0);
    complete(first); poll_fence(exported, 1);
    close(exported); close(first); close(second);
    puts("DRM_SYNCOBJ_TRANSFER_COMPLETION_PASS");
}

static void counters_and_cleanup(int drm)
{
    uint32_t timeline = create(drm, 0), binary = create(drm, 0);
    const uint64_t points[] = {1, UINT32_MAX, 1ULL << 32, 1ULL << 63, (1ULL << 63) + 9};
    for (unsigned i = 0; i < sizeof(points) / sizeof(points[0]); ++i) {
        signal_point(drm, timeline, points[i]);
        CHECK(query(drm, timeline) == points[i]);
        CHECK(wait_point(drm, timeline, points[i], DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL, 0) == 0);
    }
    transfer(drm, binary, 0, timeline, 1);
    int fd = export_fd(drm, binary, DRM_SYNCOBJ_HANDLE_TO_FD_FLAGS_EXPORT_SYNC_FILE);
    poll_fence(fd, 1); close(fd);
    struct drm_syncobj_transfer invalid = {.src_handle = timeline, .src_point = 1,
        .dst_handle = binary, .flags = UINT32_MAX};
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_TRANSFER, &invalid) == -1 && errno == EINVAL);
    invalid.flags = 0; invalid.src_handle = UINT32_MAX;
    CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_TRANSFER, &invalid) == -1 && errno == ENOENT);
    destroy(drm, timeline); destroy(drm, binary);
    unsigned count = fd_count();
    for (unsigned i = 0; i < 1024; ++i) {
        timeline = create(drm, 0); signal_point(drm, timeline, (1ULL << 40) + i);
        fd = export_fd(drm, timeline, 0);
        uint32_t imported = import_fd(drm, fd);
        destroy(drm, timeline); close(fd);
        CHECK(wait_point(drm, imported, (1ULL << 40) + i, DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL, 0) == 0);
        destroy(drm, imported);
    }
    CHECK(fd_count() == count);
    puts("DRM_SYNCOBJ_COUNTERS_AND_CLEANUP_PASS");
}

static unsigned refs(int probe, int drm, uint32_t handle)
{
    struct fence_refs arg = {.fd = drm, .handle = handle};
    CHECK(ioctl(probe, TEST_REFS, &arg) == 0);
    return arg.refs;
}

static void query_references(int drm, int expect_leak)
{
    int software, fence = new_software_fence(&software);
    uint32_t binary = create(drm, 0), timeline = create(drm, 0);
    import_fence(drm, binary, fence);
    transfer(drm, timeline, 7, binary, 0);
    int probe = open("/dev/drm-syncobj-test", O_RDWR | O_CLOEXEC);
    CHECK(probe >= 0);
    unsigned before = refs(probe, drm, timeline);
    for (unsigned i = 0; i < 512; ++i)
        CHECK(query(drm, timeline) == 0);
    struct drm_syncobj_timeline_array bad_copy = {
        .handles = pointer(&timeline), .points = 1, .count_handles = 1};
    for (unsigned i = 0; i < 8; ++i)
        CHECK(ioctl(drm, DRM_IOCTL_SYNCOBJ_QUERY, &bad_copy) == -1 && errno == EFAULT);
    unsigned after = refs(probe, drm, timeline);
    printf("DRM_SYNCOBJ_QUERY_REFS before=%u after=%u\n", before, after);
    CHECK(expect_leak ? after == before + 520 : after == before);
    complete(software);
    close(probe); close(fence); close(software);
    destroy(drm, timeline); destroy(drm, binary);
    puts(expect_leak ? "DRM_SYNCOBJ_QUERY_LEAK_REPRODUCED_PASS" : "DRM_SYNCOBJ_QUERY_REFS_PASS");
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    CHECK(getpid() == 1);
    CHECK(mount("proc", "/proc", "proc", 0, NULL) == 0);
    CHECK(mount("sysfs", "/sys", "sysfs", 0, NULL) == 0);
    FILE *stream = fopen("/proc/device-tree/compatible", "r");
    char compatible[128] = {0};
    CHECK(stream && fgets(compatible, sizeof(compatible), stream)); fclose(stream);
    CHECK(strcmp(compatible, "linux,dummy-virt") == 0);
    char command[4096] = {0};
    stream = fopen("/proc/cmdline", "r");
    CHECK(stream && fgets(command, sizeof(command), stream)); fclose(stream);
    int expect_leak = strstr(command, "reframed.query_leak=expected") != NULL;
    CHECK(mount("devtmpfs", "/dev", "devtmpfs", 0, NULL) == 0);
    CHECK(mount("debugfs", "/sys/kernel/debug", "debugfs", 0, NULL) == 0);
    CHECK(signal(SIGALRM, timed_out) != SIG_ERR);
    alarm(30);
    int module = open("/drm_syncobj_test.ko", O_RDONLY | O_CLOEXEC);
    CHECK(module >= 0 && syscall(SYS_finit_module, module, "", 0) == 0);
    close(module);
    int drm = -1;
    for (unsigned i = 0; i < 100 && drm < 0; ++i) {
        drm = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
        if (drm < 0) usleep(10000);
    }
    if (drm < 0) dump_virtual_nodes();
    CHECK(drm >= 0);
    struct drm_get_cap cap = {.capability = DRM_CAP_SYNCOBJ_TIMELINE};
    CHECK(ioctl(drm, DRM_IOCTL_GET_CAP, &cap) == 0 && cap.value == 1);
    unsigned count = fd_count();
    query_references(drm, expect_leak);
    future_point(drm); transfers(drm); counters_and_cleanup(drm);
    CHECK(fd_count() == count);
    close(drm);
    CHECK(syscall(SYS_delete_module, "drm_syncobj_test", O_NONBLOCK) == 0);
    CHECK(access("/sys/class/drm/renderD128", F_OK) == -1 && errno == ENOENT);
    puts("DRM_SYNCOBJ_FIXTURE_UNLOAD_PASS");
    puts("DRM_SYNCOBJ_ALL_PASS");
    sync(); CHECK(reboot(RB_POWER_OFF) == 0);
    return 0;
}
