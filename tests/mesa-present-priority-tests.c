#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>

typedef int VkResult;
enum { VK_SUCCESS = 0, VK_TIMEOUT = 2, VK_ERROR_DEVICE_LOST = -4 };
enum { thrd_success = 0, thrd_timedout = 2, thrd_error = 4 };
enum Mode { COMPLETE, SEM_TIMEOUT, COND_TIMEOUT, COND_ERROR, PRESENT_ERROR, ZERO_ID, COND_COMPLETE };
struct wsi_swapchain { int unused; };
struct wsi_display_swapchain {
    struct wsi_swapchain base;
    uint64_t present_id;
    VkResult present_id_error;
    int present_id_mutex, present_id_cond;
};
struct Case { const char *option, *nice_option; int policy, query_error, request_error, niceness; enum Mode mode; };
struct State {
    struct Case input;
    struct wsi_display_swapchain chain;
    unsigned lookups, queries, requests, nice_requests;
    bool locked, wait_end;
};
static _Thread_local struct State state;

static char *modeled_getenv(const char *name)
{
    assert(!state.locked && state.wait_end);
    ++state.lookups;
    if (!strcmp(name, "MESA_VK_WSI_PRESENT_THREAD_RT")) return (char *)state.input.option;
    assert(!strcmp(name, "MESA_VK_WSI_PRESENT_THREAD_NICE"));
    return (char *)state.input.nice_option;
}
static int modeled_getscheduler(pid_t pid)
{
    assert(pid == 0 && !state.locked && state.wait_end);
    ++state.queries;
    if (!state.input.query_error) return state.input.policy;
    errno = state.input.query_error;
    return -1;
}
static int modeled_setscheduler(pid_t pid, int policy, const struct sched_param *param)
{
    assert(pid == 0 && !state.locked && state.wait_end);
    assert(policy == (SCHED_RR | SCHED_RESET_ON_FORK) && param && param->sched_priority == 2);
    ++state.requests;
    if (state.input.request_error) { errno = state.input.request_error; return -1; }
    state.input.policy = policy;
    return 0;
}
static int modeled_setpriority(int which, id_t who, int priority)
{
    assert(which == PRIO_PROCESS && who == 0 && priority == -20);
    assert(!state.locked && state.wait_end && state.input.policy == SCHED_OTHER);
    ++state.nice_requests;
    if (state.input.request_error) { errno = state.input.request_error; return -1; }
    state.input.niceness = priority;
    return 0;
}
static uint64_t os_time_get_absolute_timeout(uint64_t timeout) { return timeout + 1000000000; }
static void timespec_from_nsec(struct timespec *time, uint64_t ns)
{ time->tv_sec = (time_t)(ns / 1000000000); time->tv_nsec = (long)(ns % 1000000000); }
static void wsi_present_trace(const char *event, const void *chain, const void *image,
                              uint64_t id, uint64_t detail, int result)
{
    assert(chain == &state.chain && !image);
    (void)id; (void)detail; (void)result;
    if (!strcmp(event, "wait_end")) { assert(!state.locked); state.wait_end = true; }
}
static VkResult wsi_swapchain_wait_for_present_semaphore(struct wsi_swapchain *chain,
                                                         uint64_t id, uint64_t timeout)
{
    assert(chain == &state.chain.base && timeout == 1000);
    (void)id;
    return state.input.mode == SEM_TIMEOUT ? VK_TIMEOUT : VK_SUCCESS;
}
static int mtx_lock(int *mutex)
{ assert(mutex == &state.chain.present_id_mutex && !state.locked); state.locked = true; return 0; }
static int mtx_unlock(int *mutex)
{ assert(mutex == &state.chain.present_id_mutex && state.locked); state.locked = false; return 0; }
static int u_cnd_monotonic_timedwait(int *cond, int *mutex, const struct timespec *absolute)
{
    assert(cond == &state.chain.present_id_cond && mutex == &state.chain.present_id_mutex);
    assert(state.locked && absolute);
    if (state.input.mode == COND_TIMEOUT) return thrd_timedout;
    if (state.input.mode == COND_ERROR) return thrd_error;
    assert(state.input.mode == COND_COMPLETE);
    state.chain.present_id = 1;
    return thrd_success;
}

#define getenv modeled_getenv
#define sched_getscheduler modeled_getscheduler
#define sched_setscheduler modeled_setscheduler
#define setpriority modeled_setpriority
#include "display-present-priority-under-test.h"
#undef getenv
#undef sched_getscheduler
#undef sched_setscheduler
#undef setpriority

static void *exercise(void *opaque)
{
    struct Case initial = *(const struct Case *)opaque;
    state = (struct State){ .input = initial };
    VkResult expected = initial.mode == SEM_TIMEOUT || initial.mode == COND_TIMEOUT ? VK_TIMEOUT :
                        initial.mode == COND_ERROR || initial.mode == PRESENT_ERROR ? VK_ERROR_DEVICE_LOST : VK_SUCCESS;
    bool completed = initial.mode == COMPLETE || initial.mode == COND_COMPLETE;
    bool want_rt = initial.option && !strcmp(initial.option, "1");
    bool want_nice = initial.nice_option && !strcmp(initial.nice_option, "1");
    bool enabled = want_rt != want_nice;
    for (unsigned i = 0; i < 4; ++i) {
        state.chain.present_id = initial.mode == COMPLETE || initial.mode == PRESENT_ERROR || initial.mode == SEM_TIMEOUT ? 1 : 0;
        state.chain.present_id_error = initial.mode == PRESENT_ERROR ? VK_ERROR_DEVICE_LOST : VK_SUCCESS;
        state.wait_end = false;
        errno = E2BIG;
        assert(wsi_display_wait_for_present(&state.chain.base, initial.mode == ZERO_ID ? 0 : 1, 1000) == expected);
        assert(!state.locked && errno == E2BIG);
    }
    if (!completed) {
        assert(!state.lookups && !state.queries && !state.requests && !state.nice_requests);
        state.input.mode = COMPLETE;
        state.chain.present_id = 1;
        state.chain.present_id_error = VK_SUCCESS;
        state.wait_end = false;
        assert(wsi_display_wait_for_present(&state.chain.base, 1, 1000) == VK_SUCCESS);
        assert(errno == E2BIG);
    }
    assert(state.lookups == 2 && state.queries == (unsigned)enabled);
    bool requested = enabled && !initial.query_error && initial.policy == SCHED_OTHER;
    assert(state.requests == (unsigned)(requested && want_rt));
    assert(state.nice_requests == (unsigned)(requested && want_nice));
    assert(state.input.policy == (requested && want_rt && !initial.request_error ? (SCHED_RR | SCHED_RESET_ON_FORK) : initial.policy));
    assert(state.input.niceness == (requested && want_nice && !initial.request_error ? -20 : initial.niceness));
    return NULL;
}
static void check(struct Case value)
{
    pthread_t thread;
    assert(pthread_create(&thread, NULL, exercise, &value) == 0);
    assert(pthread_join(thread, NULL) == 0);
}
int main(void)
{
    check((struct Case){0});
    const char *invalid[] = {"", "0", "2", "true", "01", "1 ", " 1"};
    for (unsigned i = 0; i < sizeof(invalid)/sizeof(*invalid); ++i) check((struct Case){ .option = invalid[i] });
    check((struct Case){ .option = "1" });
    check((struct Case){ .option = "1" });
    check((struct Case){ .option = "1", .query_error = ESRCH });
    check((struct Case){ .option = "1", .request_error = EPERM });
    check((struct Case){ .option = "1", .request_error = EINVAL });
    int policies[] = {SCHED_FIFO, SCHED_RR, SCHED_RR | SCHED_RESET_ON_FORK, SCHED_BATCH, SCHED_IDLE, SCHED_DEADLINE};
    for (unsigned i = 0; i < sizeof(policies)/sizeof(*policies); ++i) check((struct Case){ .option = "1", .policy = policies[i] });
    for (enum Mode mode = SEM_TIMEOUT; mode <= COND_COMPLETE; ++mode) check((struct Case){ .option = "1", .mode = mode });
    check((struct Case){ .nice_option = "1" });
    check((struct Case){ .nice_option = "1", .niceness = -20 });
    check((struct Case){ .nice_option = "1", .query_error = ESRCH });
    check((struct Case){ .nice_option = "1", .request_error = EPERM });
    check((struct Case){ .option = "1", .nice_option = "1" });
    for (unsigned i = 0; i < sizeof(invalid)/sizeof(*invalid); ++i) {
        check((struct Case){ .nice_option = invalid[i] });
        check((struct Case){ .option = "1", .nice_option = invalid[i] });
    }
    for (unsigned i = 0; i < sizeof(policies)/sizeof(*policies); ++i)
        check((struct Case){ .nice_option = "1", .policy = policies[i], .niceness = 5 });
    for (enum Mode mode = SEM_TIMEOUT; mode <= COND_COMPLETE; ++mode)
        check((struct Case){ .nice_option = "1", .mode = mode });
    puts("WSI present priority: completed nonzero frames only, outside mutex, once per thread; failures preserve presentation");
}
