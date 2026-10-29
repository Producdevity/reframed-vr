#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#ifndef SYS_gettid
#define SYS_gettid 178
#endif
static const uintptr_t base = 0x10000000;
static const char *module = "/fixture/libpico_controller_tracking.pxr.so";
static int clock_error, tid_error;
static int fixture_dladdr(const void *address, Dl_info *info) {
    (void)address;
    memset(info, 0, sizeof(*info));
    info->dli_fname = module;
    info->dli_fbase = (void *)base;
    return 1;
}
static int fixture_clock_gettime(clockid_t clock_id, struct timespec *now) {
    assert(clock_id == CLOCK_MONOTONIC);
    errno = EBUSY;
    now->tv_sec = 42;
    now->tv_nsec = 123;
    return clock_error ? -1 : 0;
}
static long fixture_syscall(long number, ...) {
    assert(number == SYS_gettid);
    errno = EINVAL;
    return tid_error ? -1 : 4321;
}
#define dladdr fixture_dladdr
#define clock_gettime fixture_clock_gettime
#define syscall fixture_syscall
#define STUB_LOG
#include "../../src/pico-vendor-log.c"
#undef dladdr
#undef clock_gettime
#undef syscall

static int output_fd;
static char output[65536];
static const char *left = "Paul_BruteMatchPoints_L:127.250000,1,2.000000,3.000000,4,5,6,7,8";
static void clear_output(void) {
    fflush(stderr);
    assert(ftruncate(output_fd, 0) == 0);
    assert(lseek(output_fd, 0, SEEK_SET) == 0);
    atomic_store(&worker_marker_emitted, 0);
}
static int marker_count(void) {
    fflush(stderr);
    ssize_t n = pread(output_fd, output, sizeof(output) - 1, 0);
    assert(n >= 0);
    output[n] = 0;
    int count = 0;
    for (char *p = output; (p = strstr(p, "\"event\":\"pico_controller_candidate_worker\"")); ++p) ++count;
    return count;
}
static int run(const char *msg, uintptr_t offset) {
    errno = EDOM;
    int got = log_line(4, "fixture", msg, (void *)(base + offset));
    assert(errno == EDOM);
    char expected[2048];
    int want = snprintf(expected, sizeof(expected), "I/fixture: %s\n", msg);
    assert(got == want);
    marker_count();
    assert(!strncmp(output, expected, strlen(expected)));
    return got;
}
static void *thread_call(void *unused) {
    (void)unused;
    log_line(4, "fixture", left, (void *)(base + 0xb9a08));
    return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    FILE *file = fopen(argv[1], "w+");
    assert(file);
    output_fd = fileno(file);
    assert(dup2(output_fd, STDERR_FILENO) == STDERR_FILENO);
    unsetenv("STUB_LOG_ADDR");
    unsetenv("PICO_CONTROLLER_CANDIDATE_TID");
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 0);
    setenv("PICO_CONTROLLER_CANDIDATE_TID", "yes", 1);
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 0);
    setenv("PICO_CONTROLLER_CANDIDATE_TID", "1", 1);
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 1);
    assert(strstr(output, "\"tid\":4321,\"monotonic_ns\":42000000123"));
    assert(strstr(output, "\"sdk_base\":268435456,\"caller_pc\":269195784,\"caller_offset\":760328"));
    run(left, 0xb9a08); assert(marker_count() == 1);
    clear_output(); run("Paul_BruteMatchPoints_R:1,1,2", 0xb9a08); assert(marker_count() == 0);
    clear_output(); run("Paul_BruteMatchPoints_L:1,0,2", 0xb9a08); assert(marker_count() == 0);
    clear_output(); run("Paul_BruteMatchPoints_L:1,10,2", 0xb9a08); assert(marker_count() == 0);
    clear_output(); run("Paul_BruteMatchPoints_L:,1,2", 0xb9a08); assert(marker_count() == 0);
    clear_output(); run(left, 0xb9994); assert(marker_count() == 0);
    module = "/fixture/other.so";
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 0);
    module = "/fixture/libpico_controller_tracking.pxr.so";
    clock_error = 1;
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 0);
    clock_error = 0; tid_error = 1;
    clear_output(); run(left, 0xb9a08); assert(marker_count() == 0);
    tid_error = 0;
    setenv("STUB_LOG_ADDR", "1", 1);
    clear_output();
    errno = EDOM;
    char expected[2048];
    int want = snprintf(expected, sizeof(expected), "I/fixture [libpico_controller_tracking.pxr.so+0xb9a08]: %s\n", left);
    assert(log_line(4, "fixture", left, (void *)(base + 0xb9a08)) == want);
    assert(errno == EDOM);
    assert(marker_count() == 1 && !strncmp(output, expected, strlen(expected)));
    unsetenv("STUB_LOG_ADDR");
    clear_output();
    pthread_t threads[16];
    for (int i = 0; i < 16; ++i) assert(!pthread_create(&threads[i], NULL, thread_call, NULL));
    for (int i = 0; i < 16; ++i) assert(!pthread_join(threads[i], NULL));
    assert(marker_count() == 1);
    fclose(file);
    puts("logger fixtures passed: opt-in, exact callsite/module/side/flag, one-shot concurrent marker, original line/return/errno, failed clock/tid");
    return 0;
}
