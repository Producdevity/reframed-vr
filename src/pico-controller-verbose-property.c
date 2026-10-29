#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef int (*property_get_fn)(const char *, char *);
static pthread_once_t resolve_once = PTHREAD_ONCE_INIT;
static property_get_fn next_property_get;
static int opted_in;
static _Atomic uint64_t first_exact_query_ns;
static atomic_flag off_reported = ATOMIC_FLAG_INIT;
static _Atomic uint64_t exact_key_reads;
static _Atomic uint64_t delegated_reads;

static void resolve_next(void)
{
    next_property_get = (property_get_fn)dlsym(RTLD_NEXT, "__system_property_get");
    if (!next_property_get)
        abort();
    const char *option = getenv("PICO_CONTROLLER_VERBOSE");
    opted_in = option && strcmp(option, "1") == 0;
}

static uint64_t monotonic_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0 || ts.tv_sec < 0)
        abort();
    uint64_t now = (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
    if (!now)
        abort();
    return now;
}

__attribute__((visibility("default")))
int __system_property_get(const char *name, char *value)
{
    if (pthread_once(&resolve_once, resolve_next) != 0)
        abort();
    if (opted_in && strcmp(name, "persist.pxr.picoController.log") == 0) {
        uint64_t now = monotonic_ns();
        uint64_t start = atomic_load_explicit(&first_exact_query_ns, memory_order_relaxed);
        if (!start) {
            uint64_t expected = 0;
            if (atomic_compare_exchange_strong_explicit(&first_exact_query_ns, &expected,
                    now, memory_order_relaxed, memory_order_relaxed)) {
                start = now;
                fprintf(stderr, "PICO_CONTROLLER_VERBOSE_PROPERTY enabled start_ns=%llu duration_ns=6000000000\n",
                        (unsigned long long)start);
            } else {
                start = expected;
            }
        }
        int enabled = now < start || now - start < UINT64_C(6000000000);
        value[0] = enabled ? '1' : '0';
        value[1] = '\0';
        atomic_fetch_add_explicit(&exact_key_reads, 1, memory_order_relaxed);
        if (!enabled && !atomic_flag_test_and_set_explicit(&off_reported, memory_order_relaxed))
            fprintf(stderr, "PICO_CONTROLLER_VERBOSE_PROPERTY disabled query_ns=%llu start_ns=%llu\n",
                    (unsigned long long)now, (unsigned long long)start);
        return 1;
    }
    atomic_fetch_add_explicit(&delegated_reads, 1, memory_order_relaxed);
    return next_property_get(name, value);
}

__attribute__((visibility("default")))
uint64_t pico_controller_verbose_exact_key_reads(void)
{
    return atomic_load_explicit(&exact_key_reads, memory_order_relaxed);
}

__attribute__((visibility("default")))
uint64_t pico_controller_verbose_delegated_reads(void)
{
    return atomic_load_explicit(&delegated_reads, memory_order_relaxed);
}
