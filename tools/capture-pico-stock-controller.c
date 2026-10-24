#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int boot_matches(const char *expected)
{
    char actual[38] = {0};
    FILE *file = fopen("/proc/sys/kernel/random/boot_id", "r");
    if (!file) return 0;
    int ok = fgets(actual, sizeof(actual), file) && strlen(actual) == 37 &&
        actual[36] == '\n' && !strncmp(actual, expected, 36);
    fclose(file);
    return ok;
}

static int64_t now(clockid_t clock)
{
    struct timespec time;
    if (clock_gettime(clock, &time)) return -1;
    return (int64_t)time.tv_sec * 1000000000 + time.tv_nsec;
}

static int64_t qtimer_now(void)
{
#if defined(__aarch64__)
    uint64_t frequency, ticks;
    __asm__ volatile("mrs %0, cntfrq_el0\n\tisb\n\tmrs %1, cntvct_el0\n\tisb"
                     : "=r"(frequency), "=r"(ticks) : : "memory");
    if (frequency != 19200000) return -1;
    __uint128_t ns = (__uint128_t)ticks * 1000000000 / frequency;
    return ns > INT64_MAX ? -1 : (int64_t)ns;
#else
    return -1;
#endif
}

int main(int argc, char **argv)
{
    if (argc != 3 || strlen(argv[1]) != 36 || !boot_matches(argv[1])) return 2;
    umask(0077);
    alarm(20);
    setvbuf(stdout, NULL, _IONBF, 0);
    void *library = dlopen("/system/lib64/libtrackingclient.pxr.so", RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 3; }
    void *(*create)(void) = dlsym(library, "CreateClient");
    int (*get)(void *, void *, void *) = dlsym(library, "GetControllerTrackingRawData");
    int (*prime)(void *, int64_t, void *, void *, void *, void *) =
        dlsym(library, "GetControllerData");
    if (!create || !get || !prime) return 4;
    void *client = create();
    if (!client) return 5;
    uint32_t fake;
    memcpy(&fake, (const uint8_t *)client + 0x7b8, sizeof(fake));
    if (fake) return 6;
    /* b1977's raw getter does not lazily map the controller buffer; the normal
     * data getter does. Neither starts an algorithm. Host verifies this ABI. */
    int primed = prime(client, 0, NULL, NULL, NULL, NULL);
    printf("PICO_STOCK_CONTROLLER_READ prime=%d fake=%u\n", primed, fake);
    if (primed) return 7;
    FILE *file = fopen(argv[2], "wxe");
    if (!file) return 8;
    const uint64_t header[8] = {UINT64_C(0x5256504353500001), 2, 368, 808, 300, 19200000, 0, 0};
    if (fwrite(header, sizeof(header), 1, file) != 1) return 9;
    unsigned success = 0;
    for (unsigned i = 0; i < 300; ++i) {
        _Alignas(8) uint8_t left[368] = {0}, right[368] = {0};
        int64_t timing[9];
        timing[0] = now(CLOCK_BOOTTIME);
        timing[1] = now(CLOCK_MONOTONIC);
        timing[2] = now(CLOCK_MONOTONIC_RAW);
        timing[3] = qtimer_now();
        int rc = get(client, left, right);
        timing[4] = qtimer_now();
        timing[5] = now(CLOCK_MONOTONIC_RAW);
        timing[6] = now(CLOCK_MONOTONIC);
        timing[7] = now(CLOCK_BOOTTIME);
        timing[8] = rc;
        if (timing[0] < 0 || timing[1] < 0 || timing[2] < 0 || timing[3] < 0 ||
            timing[4] < timing[3] || timing[5] < timing[2] ||
            timing[6] < timing[1] || timing[7] < timing[0] ||
            fwrite(timing, sizeof(timing), 1, file) != 1 ||
            fwrite(left, sizeof(left), 1, file) != 1 ||
            fwrite(right, sizeof(right), 1, file) != 1) return 9;
        success += rc == 0;
        const struct timespec delay = {0, 10000000};
        if (nanosleep(&delay, NULL)) return 10;
    }
    if (fclose(file) || !boot_matches(argv[1])) return 11;
    printf("PICO_STOCK_CONTROLLER_CAPTURED calls=300 successful_reads=%u\n", success);
    _Exit(success ? 0 : 12);
}
