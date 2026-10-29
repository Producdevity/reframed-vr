#define _GNU_SOURCE
#include "ion-buffer.h"
#include "pico-controller-channel.h"
#include "pico-controller-motion-producer.h"
#include "pico-controller-ring.h"
#include "pico-sensor-rpc.h"
#include "rpcmem.h"
#include "ssc-clock-linux.h"

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static void interrupt(int number) { (void)number; interrupted = 1; }

static int64_t now_ns(void)
{
    struct timespec time;
    if (clock_gettime(CLOCK_MONOTONIC, &time)) return -1;
    return (int64_t)time.tv_sec * 1000000000 + time.tv_nsec;
}

static bool motion_config(const char *text, struct pico_controller_motion_config *config)
{
    if (strlen(text) != 8 || text[2] != ':' || text[5] != ':') return false;
    unsigned value[3] = {0};
    for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 2; ++j) {
        char c = text[i * 3 + j];
        unsigned digit = c >= '0' && c <= '9' ? (unsigned)(c - '0') :
                         c >= 'a' && c <= 'f' ? (unsigned)(c - 'a' + 10) : 16;
        if (digit > 15) return false;
        value[i] = value[i] * 16 + digit;
    }
    *config = (struct pico_controller_motion_config){1, value[0], value[1], value[2]};
    return true;
}

static bool file_equals(const char *path, const char *expected)
{
    char value[128];
    FILE *file = fopen(path, "r");
    if (!file) return false;
    bool ok = fgets(value, sizeof(value), file) && !strcmp(value, expected);
    fclose(file);
    return ok;
}

struct stream {
    struct pico_sensor_rpc rpc;
    struct ion_buffer buffer;
};

static int start(struct stream *stream, int64_t offset, bool acceleration)
{
    void *memory = rpcmem_alloc(-1, 1, PICO_CONTROLLER_RING_BYTES);
    if (!memory) return -ENOMEM;
    stream->buffer = (struct ion_buffer){rpcmem_to_fd(memory), memory, 4096};
    int rc = ion_buffer_sync(&stream->buffer, ION_BUFFER_WRITE, false);
    if (rc) return rc;
    memset(memory, 0, PICO_CONTROLLER_RING_BYTES);
    rc = ion_buffer_sync(&stream->buffer, ION_BUFFER_WRITE, true);
    if (rc) return rc;
    rc = pico_sensor_rpc_open(&stream->rpc);
    if (!rc) rc = pico_sensor_rpc_init(&stream->rpc, stream->buffer.fd, PICO_CONTROLLER_RING_BYTES);
    const struct sns_low_latency_suid controller = {
        UINT64_C(0xf8d9a8908e5f4f1b), UINT64_C(0xf3e0cdbb766d3625)};
    const struct sns_low_latency_suid accel = {
        UINT64_C(0x58442ede47acd316), UINT64_C(0x61ab5376b4a5c9aa)};
    if (!rc) rc = pico_sensor_rpc_config(&stream->rpc, offset,
                                        acceleration ? &accel : &controller,
                                        100000, 0, acceleration ? 2 : 1);
    printf("PICO_CONTROLLER_STREAM acceleration=%u rc=%d state=%d\n",
           acceleration, rc, stream->rpc.state);
    return rc;
}

static int snapshot(const struct ion_buffer *buffer, uint8_t first[1000], uint8_t second[1000])
{
    int rc = ion_buffer_sync(buffer, ION_BUFFER_READ, false);
    if (rc) return rc;
    volatile const uint8_t *data = buffer->data;
    for (unsigned i = 0; i < PICO_CONTROLLER_RING_BYTES; ++i) first[i] = data[i];
    atomic_thread_fence(memory_order_seq_cst);
    for (unsigned i = 0; i < PICO_CONTROLLER_RING_BYTES; ++i) second[i] = data[i];
    return ion_buffer_sync(buffer, ION_BUFFER_READ, true);
}

static struct pico_controller_motion_channel *new_motion_channel(const char *path)
{
    int fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0644);
    if (fd < 0) return MAP_FAILED;
    void *map = MAP_FAILED;
    if (!ftruncate(fd, sizeof(struct pico_controller_motion_channel)) && !fchmod(fd, 0644))
        map = mmap(NULL, sizeof(struct pico_controller_motion_channel),
                   PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    return map;
}

static bool restart_request(const char request[42], uint64_t *previous, uint64_t *next)
{
    if (memcmp(request, "restart ", 8) || request[24] != ' ' || request[41] != '\n') return false;
    char value[17] = {0};
    memcpy(value, request + 8, 16);
    if (strspn(value, "0123456789abcdef") != 16) return false;
    *previous = strtoull(value, NULL, 16);
    memcpy(value, request + 25, 16);
    if (strspn(value, "0123456789abcdef") != 16) return false;
    *next = strtoull(value, NULL, 16);
    return *previous && *next;
}

int main(int argc, char **argv)
{
    const char *boot_id = NULL, *path = NULL;
    const char *motion_path = NULL;
    uint64_t instance = 0, motion_generation = 0;
    struct pico_controller_motion_config config[2] = {{0}};
    unsigned motion_mask = 0;
    unsigned seconds = 0;
    bool companion = false;
    static const struct option options[] = {
        {"boot-id", required_argument, NULL, 'b'},
        {"channel", required_argument, NULL, 'c'},
        {"instance", required_argument, NULL, 'i'},
        {"seconds", required_argument, NULL, 's'},
        {"companion-accel", no_argument, NULL, 'a'},
        {"motion-channel", required_argument, NULL, 'm'},
        {"motion-generation", required_argument, NULL, 'g'},
        {"left-motion-config", required_argument, NULL, 'l'},
        {"right-motion-config", required_argument, NULL, 'r'},
        {NULL, 0, NULL, 0}
    };
    int option;
    while ((option = getopt_long(argc, argv, "", options, NULL)) != -1) {
        char *end = NULL;
        switch (option) {
        case 'b': boot_id = optarg; break;
        case 'c': path = optarg; break;
        case 'i':
            if (strlen(optarg) != 16 || strspn(optarg, "0123456789abcdef") != 16) return 2;
            instance = strtoull(optarg, NULL, 16); break;
        case 's': {
            errno = 0;
            unsigned long value = strtoul(optarg, &end, 10);
            if (errno || !*optarg || *end || value < 1 || value > 3600) return 2;
            seconds = (unsigned)value; break;
        }
        case 'a': companion = true; break;
        case 'm': motion_path = optarg; break;
        case 'g':
            if (strlen(optarg) != 16 || strspn(optarg, "0123456789abcdef") != 16) return 2;
            motion_generation = strtoull(optarg, NULL, 16); break;
        case 'l': case 'r': {
            unsigned hand = option == 'l' ? 0 : 1;
            if ((motion_mask & (1U << hand)) || !motion_config(optarg, &config[hand])) return 2;
            motion_mask |= 1U << hand;
            break;
        }
        default: return 2;
        }
    }
    if (optind != argc || !boot_id || strlen(boot_id) != 36 || !path || path[0] != '/' ||
        !instance || !seconds || geteuid() ||
        (motion_path ? motion_path[0] != '/' || !strcmp(motion_path, path) ||
                       !motion_generation || !motion_mask : motion_generation || motion_mask)) {
        fprintf(stderr, "Usage: %s --boot-id UUID --channel NEW_PATH --instance HEX16 "
                        "--seconds 1..3600 [--companion-accel] "
                        "[--motion-channel NEW_PATH --motion-generation HEX16 "
                        "--left-motion-config REV:SCALE:BYPASS and/or --right-motion-config ...] "
                        "(config bytes are lowercase hex; native Neo3 b1977)\n", argv[0]);
        return 2;
    }
    char boot_line[38]; snprintf(boot_line, sizeof(boot_line), "%s\n", boot_id);
    if (!file_equals("/proc/sys/kernel/random/boot_id", boot_line) ||
        !file_equals("/sys/bus/msm_subsys/devices/subsys7/name", "slpi\n") ||
        !file_equals("/sys/bus/msm_subsys/devices/subsys7/state", "ONLINE\n")) return 2;
    FILE *cmdline = fopen("/proc/cmdline", "r");
    char token[512]; bool serial = false;
    if (!cmdline) return 2;
    while (fscanf(cmdline, "%511s", token) == 1)
        if (!strcmp(token, "androidboot.serialno=c980c8d4")) serial = true;
    fclose(cmdline);
    if (!serial) return 2;
    int lock = open("/run/reframed-pico-controller.lock", O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
    struct stat st;
    if (lock < 0 || fstat(lock, &st) || !S_ISREG(st.st_mode) || st.st_uid ||
        (st.st_mode & 0022) || flock(lock, LOCK_EX | LOCK_NB)) return 2;
    struct ssc_clock clock;
    if (!ssc_clock_calibrate_monotonic(&clock, 16, 100000)) return 2;
    int64_t offset = clock.host_ns - (int64_t)((__int128)clock.counter_ticks * 1000000000 / clock.counter_hz);
    int fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0644);
    if (fd < 0) return 2;
    if (ftruncate(fd, sizeof(struct pico_controller_channel)) || fchmod(fd, 0644)) {
        close(fd); unlink(path); return 2;
    }
    struct pico_controller_channel *channel = mmap(NULL, sizeof(*channel), PROT_READ | PROT_WRITE,
                                                   MAP_SHARED, fd, 0);
    close(fd);
    if (channel == MAP_FAILED || !pico_controller_channel_init(channel, instance)) return 2;
    struct pico_controller_motion_channel *motion_channel = NULL;
    if (motion_path) {
        motion_channel = new_motion_channel(motion_path);
        if (motion_channel == MAP_FAILED) return 2;
    }
    int control_fd = motion_path ? STDIN_FILENO : -1;
    if (control_fd >= 0) {
        int flags = fcntl(control_fd, F_GETFL);
        if (flags < 0 || fcntl(control_fd, F_SETFL, flags | O_NONBLOCK)) return 2;
    }
    char request[42]; size_t request_size = 0;
    unsigned restarts = 0;
    setvbuf(stdout, NULL, _IONBF, 0);
    signal(SIGINT, interrupt); signal(SIGTERM, interrupt); signal(SIGPIPE, SIG_IGN);
    if (setenv("PICO_ION_HEAP_ID", "25", 1)) return 2;
    rpcmem_init();
    struct stream controller = {0}, accel = {0};
    struct pico_controller_ring ring = {0};
    struct pico_controller_motion_producer motion = {0};
    uint64_t motion_samples = 0;
    int motion_error = 0;
    bool resume_failed = false;
    int64_t last_resume_probe = 0, last_resume_report = 0;
    uint64_t published[2] = {0};
    int rc = start(&controller, offset, false);
    int64_t begin = now_ns(), last_report = begin, last_control = begin;
    if (begin <= 0) rc = -EIO;
    if (!rc && motion_channel) {
        rc = pico_controller_motion_producer_init(&motion, motion_channel, instance, motion_generation,
                                                   &clock, config, 1, 2, motion_mask, begin);
        printf("PICO_CONTROLLER_MOTION_READY instance=%016" PRIx64 " generation=%016" PRIx64
               " mask=%u rc=%d\n", instance, motion_generation, motion_mask, rc);
    }
    printf("PICO_CONTROLLER_READY instance=%016" PRIx64 " companion_accel=%u rc=%d\n", instance, companion, rc);
    while (!rc && !interrupted) {
        int64_t now = now_ns();
        if (now <= 0) { rc = -EIO; break; }
        if (now - begin >= (int64_t)seconds * 1000000000) break;
        if (companion && !accel.buffer.data && now - begin >= 1000000000) {
            rc = start(&accel, offset, true);
            if (rc) break;
        }
        uint8_t first[1000], second[1000];
        rc = snapshot(&controller.buffer, first, second);
        if (rc) break;
        struct pico_controller_sample samples[2];
        unsigned changed = pico_controller_ring_read(&ring, first, second, samples);
        int64_t received = now_ns();
        if (control_fd >= 0 && received - last_control >= 20000000) {
            last_control = received;
            ssize_t size = read(control_fd, request + request_size, sizeof(request) - request_size);
            if (size == 0 || (size < 0 && errno != EAGAIN && errno != EINTR)) control_fd = -1;
            if (size > 0) request_size += (size_t)size;
            if (request_size == sizeof(request)) {
                uint64_t previous = 0, next = 0;
                int restart_rc = -EINVAL;
                if (!restart_request(request, &previous, &next)) control_fd = -1;
                else if (previous != motion_generation || next <= previous) restart_rc = -ESTALE;
                else if (restarts >= 64) restart_rc = -EOVERFLOW;
                else if (resume_failed) restart_rc = -EPERM;
                else if (motion_error && motion_error != -ETIMEDOUT && motion_error != -ESHUTDOWN)
                    restart_rc = -EPERM;
                else {
                    char next_path[PATH_MAX];
                    int length = snprintf(next_path, sizeof(next_path), "%s.%016" PRIx64, motion_path, next);
                    struct pico_controller_motion_channel *fresh = MAP_FAILED;
                    if (length > 0 && (size_t)length < sizeof(next_path)) fresh = new_motion_channel(next_path);
                    if (fresh == MAP_FAILED) restart_rc = -EIO;
                    else {
                        if (!motion_error) {
                            pico_controller_motion_producer_stop(&motion);
                            motion_error = -ESHUTDOWN;
                            printf("PICO_CONTROLLER_MOTION_STOP rc=%d samples=%" PRIu64 "\n",
                                   motion_error, motion_samples);
                        }
                        struct pico_controller_motion_channel *old = motion.channel;
                        restart_rc = pico_controller_motion_producer_restart(&motion, fresh, next,
                                                                              first, second, received);
                        if (!restart_rc) {
                            munmap(old, sizeof(*old));
                            motion_generation = next; motion_samples = 0; motion_error = 0;
                            resume_failed = false; last_resume_report = 0;
                            ++restarts;
                        } else munmap(fresh, sizeof(*fresh));
                    }
                }
                printf("PICO_CONTROLLER_MOTION_RESTART previous=%016" PRIx64 " generation=%016" PRIx64
                       " rc=%d\n", previous, next, restart_rc);
                if (!restart_rc)
                    printf("PICO_CONTROLLER_MOTION_READY instance=%016" PRIx64 " generation=%016" PRIx64
                           " mask=%u rc=0\n", instance, motion_generation, motion_mask);
                request_size = 0;
            }
        }
        if (motion.channel && !motion_error) {
            int count = pico_controller_motion_producer_update(&motion, motion_generation,
                                                               first, second, received);
            if (count < 0) {
                motion_error = count;
                printf("PICO_CONTROLLER_MOTION_FAILURE generation=%016" PRIx64
                       " mask=%u rc=%d reason=%u hand=%u now_ns=%" PRId64
                       " started_ns=%" PRId64 " sample_us=%" PRIu64
                       " received_left_ns=%" PRId64 " received_right_ns=%" PRId64
                       " latest_left_us=%" PRIu64 " latest_right_us=%" PRIu64 "\n",
                       motion.generation, motion.connected_mask, motion.error,
                       (unsigned)motion.failure, motion.rejected_hand, motion.failure_now_ns,
                       motion.started, motion.rejected_timestamp_us,
                       motion.received[0], motion.received[1],
                       motion.ring.latest[0].timestamp_us, motion.ring.latest[1].timestamp_us);
                printf("PICO_CONTROLLER_MOTION_STOP rc=%d samples=%" PRIu64 "\n", count, motion_samples);
            } else motion_samples += (unsigned)count;
        }
        if (motion_error == -ETIMEDOUT && !resume_failed &&
            received - last_resume_probe >= 20000000) {
            last_resume_probe = received;
            struct ssc_timestamp captures[2];
            int resumed = pico_controller_motion_producer_resumed(&motion, first, second, received, captures);
            if (resumed < 0) {
                resume_failed = true;
                printf("PICO_CONTROLLER_MOTION_RESUME_FAILED generation=%016" PRIx64 " rc=%d\n",
                       motion_generation, resumed);
            } else if (resumed && received - last_resume_report >= 100000000) {
                int64_t deadline = INT64_MAX;
                for (unsigned hand = 0; hand < 2; ++hand) if (motion_mask & (1U << hand)) {
                    int64_t remaining = PICO_CONTROLLER_MOTION_MAX_AGE_NS - captures[hand].uncertainty_ns;
                    int64_t limit = captures[hand].timestamp_ns > INT64_MAX - remaining ?
                                    INT64_MAX : captures[hand].timestamp_ns + remaining;
                    if (limit < deadline) deadline = limit;
                }
                printf("PICO_CONTROLLER_MOTION_RESUMED instance=%016" PRIx64 " generation=%016" PRIx64
                       " received_ns=%" PRId64 " deadline_ns=%" PRId64 "\n",
                       instance, motion_generation, received, deadline);
                last_resume_report = received;
            }
        }
        for (unsigned hand = 0; hand < 2; ++hand) if (changed & (1U << hand)) {
            if (!pico_controller_channel_publish(channel, &samples[hand], received)) { rc = -EPROTO; break; }
            ++published[hand];
        }
        if (now - last_report >= 1000000000) {
            printf("PICO_CONTROLLER_ACTIVITY left=%" PRIu64 " right=%" PRIu64
                   " station_left=%" PRIu64 " station_right=%" PRIu64 "\n",
                   published[0], published[1], ring.timestamp[0], ring.timestamp[1]);
            last_report = now;
        }
        const struct timespec delay = {0, 1000000}; nanosleep(&delay, NULL);
    }
    pico_controller_channel_disconnect(channel, 1);
    pico_controller_channel_disconnect(channel, 2);
    pico_controller_motion_producer_stop(&motion);
    if (motion.channel && !motion_error)
        printf("PICO_CONTROLLER_MOTION_STOP rc=0 samples=%" PRIu64 "\n", motion_samples);
    int accel_rc = pico_sensor_rpc_close(&accel.rpc);
    int controller_rc = pico_sensor_rpc_close(&controller.rpc);
    printf("PICO_CONTROLLER_STOP rc=%d controller_rc=%d accel_rc=%d left=%" PRIu64
           " right=%" PRIu64 "\n", rc, controller_rc, accel_rc, published[0], published[1]);
    /* The session owns SLPI and other DMA clients. Keep registrations alive
     * until that owner confirms subsystem shutdown, including RPC failures. */
    puts("PICO_CONTROLLER_WAIT_DSP_OFFLINE");
    while (!file_equals("/sys/bus/msm_subsys/devices/subsys7/state", "OFFLINE\n")) {
        const struct timespec delay = {0, 100000000}; nanosleep(&delay, NULL);
    }
    int release_error = 0;
    if (accel.buffer.data) {
        rpcmem_free(accel.buffer.data);
        if (rpcmem_to_fd(accel.buffer.data) >= 0) release_error = 1;
    }
    if (controller.buffer.data) {
        rpcmem_free(controller.buffer.data);
        if (rpcmem_to_fd(controller.buffer.data) >= 0) release_error = 1;
    }
    if (release_error) { puts("PICO_CONTROLLER_RELEASE_FAILED retained=1"); _Exit(1); }
    puts("PICO_CONTROLLER_RELEASED_DSP_OFFLINE");
    _Exit(rc || accel_rc || controller_rc || motion_error ? 1 : 0);
}
