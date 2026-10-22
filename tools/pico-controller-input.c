#define _GNU_SOURCE
#include "ion-buffer.h"
#include "pico-controller-channel.h"
#include "pico-controller-ring.h"
#include "pico-sensor-rpc.h"
#include "rpcmem.h"
#include "ssc-clock-linux.h"

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
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

int main(int argc, char **argv)
{
    const char *boot_id = NULL, *path = NULL;
    uint64_t instance = 0;
    unsigned seconds = 0;
    bool companion = false;
    static const struct option options[] = {
        {"boot-id", required_argument, NULL, 'b'},
        {"channel", required_argument, NULL, 'c'},
        {"instance", required_argument, NULL, 'i'},
        {"seconds", required_argument, NULL, 's'},
        {"companion-accel", no_argument, NULL, 'a'},
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
        default: return 2;
        }
    }
    if (optind != argc || !boot_id || strlen(boot_id) != 36 || !path || path[0] != '/' ||
        !instance || !seconds || geteuid()) {
        fprintf(stderr, "Usage: %s --boot-id UUID --channel NEW_PATH --instance HEX16 "
                        "--seconds 1..3600 [--companion-accel] (native Neo3 b1977)\n", argv[0]);
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
    if (fd < 0 || ftruncate(fd, sizeof(struct pico_controller_channel)) || fchmod(fd, 0644)) return 2;
    struct pico_controller_channel *channel = mmap(NULL, sizeof(*channel), PROT_READ | PROT_WRITE,
                                                   MAP_SHARED, fd, 0);
    close(fd);
    if (channel == MAP_FAILED || !pico_controller_channel_init(channel, instance)) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    signal(SIGINT, interrupt); signal(SIGTERM, interrupt); signal(SIGPIPE, SIG_IGN);
    if (setenv("PICO_ION_HEAP_ID", "25", 1)) return 2;
    rpcmem_init();
    struct stream controller = {0}, accel = {0};
    struct pico_controller_ring ring = {0};
    uint64_t published[2] = {0};
    int rc = start(&controller, offset, false);
    int64_t begin = now_ns(), last_report = begin;
    if (begin <= 0) rc = -EIO;
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
    if (accel.buffer.data) rpcmem_free(accel.buffer.data);
    if (controller.buffer.data) rpcmem_free(controller.buffer.data);
    puts("PICO_CONTROLLER_RELEASED_DSP_OFFLINE");
    _Exit(rc || accel_rc || controller_rc ? 1 : 0);
}
