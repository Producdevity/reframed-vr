#define _GNU_SOURCE
#include "pico-controller-motion-channel.h"

#include <assert.h>
#include <errno.h>
#include <math.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

static int64_t fake_now = 1000000020;
static int64_t clock_ns(void *data) { (void)data; return fake_now; }

static struct pico_controller_motion_event event(unsigned index)
{
    struct pico_controller_motion_event e = {
        .timestamp_us = index + 1, .time = {1000000000 + index, 1},
        .received_ns = 1000000010 + index, .hand = 1 + index % 2,
        .sequence = (uint8_t)index, .flags = (uint8_t)(index >> 1)};
    for (unsigned i = 0; i < 7; ++i) e.values[i] = (double)(index * 10 + i);
    e.values[7] = e.flags & 1; e.values[8] = e.flags >> 1;
    return e;
}

static void same(const struct pico_controller_motion_event *a,
                 const struct pico_controller_motion_event *b)
{
    assert(a->timestamp_us == b->timestamp_us && a->time.timestamp_ns == b->time.timestamp_ns &&
           a->time.uncertainty_ns == b->time.uncertainty_ns && a->received_ns == b->received_ns &&
           a->hand == b->hand && a->sequence == b->sequence && a->flags == b->flags &&
           !memcmp(a->values, b->values, sizeof(a->values)));
}

static int64_t stop_during_read(void *data)
{
    pico_controller_motion_channel_stop(data);
    return fake_now;
}

static void boundaries(void)
{
    struct pico_controller_motion_channel *c = calloc(1, sizeof(*c)); assert(c);
    struct pico_controller_motion_event out, saved, e = event(0);
    memset(&out, 0xa5, sizeof(out)); memcpy(&saved, &out, sizeof(out));
    uint64_t cursor = 0;
    assert(!pico_controller_motion_channel_init(NULL, 1, 2));
    assert(!pico_controller_motion_channel_init(c, 0, 2));
    assert(!pico_controller_motion_channel_init(c, 1, 0));
    assert(pico_controller_motion_channel_init(c, 1, 2));
    assert(!pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out));
    assert(!memcmp(&out, &saved, sizeof(out)) && !cursor);
    assert(pico_controller_motion_channel_publish(c, &e));
    assert(!pico_controller_motion_channel_publish(c, &e));
    struct pico_controller_motion_event right = event(1);
    right.received_ns = e.received_ns;
    assert(pico_controller_motion_channel_publish(c, &right));
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out) == 1);
    same(&e, &out); assert(cursor == 1);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out) == 1);
    same(&right, &out); assert(cursor == 2);

    e = event(2); assert(pico_controller_motion_channel_publish(c, &e));
    memcpy(&saved, &out, sizeof(out));
    fake_now = e.time.timestamp_ns + 100;
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out) == -ETIMEDOUT);
    assert(cursor == 2 && !memcmp(&out, &saved, sizeof(out)));
    fake_now = e.time.timestamp_ns + 99;
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out) == 1);
    same(&e, &out);
    assert(pico_controller_motion_channel_read(c, 2, 2, &cursor, clock_ns, NULL, 100, &out) == -ESTALE);
    assert(pico_controller_motion_channel_read(c, 1, 3, &cursor, clock_ns, NULL, 100, &out) == -ESTALE);
    assert(pico_controller_motion_channel_read(c, 1, 2, NULL, clock_ns, NULL, 100, &out) == -EINVAL);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, NULL, NULL, 100, &out) == -EINVAL);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 0, &out) == -EINVAL);

    e = event(3); assert(pico_controller_motion_channel_publish(c, &e));
    memcpy(&saved, &out, sizeof(out));
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, stop_during_read, c, 100, &out) == -ESHUTDOWN);
    assert(cursor == 3 && !memcmp(&out, &saved, sizeof(out)));
    assert(!pico_controller_motion_channel_publish(c, &e));
    pico_controller_motion_channel_stop(c);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 100, &out) == -ESHUTDOWN);

    assert(pico_controller_motion_channel_init(c, 1, 2)); cursor = 0; e = event(0);
    e.values[2] = NAN; assert(!pico_controller_motion_channel_publish(c, &e));
    e = event(0); e.values[7] = 99; assert(!pico_controller_motion_channel_publish(c, &e));
    e = event(0); e.time.uncertainty_ns = 11; assert(!pico_controller_motion_channel_publish(c, &e));
    e = event(0); e.hand = 3; assert(!pico_controller_motion_channel_publish(c, &e));
    e = event(0); assert(pico_controller_motion_channel_publish(c, &e));
    __atomic_store_n(&c->slots[0][0], 0, __ATOMIC_RELEASE);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 1000, &out) == -EAGAIN);
    assert(!cursor);
    __atomic_store_n(&c->slots[0][0], 1, __ATOMIC_RELEASE);
    __atomic_store_n(&c->slots[0][5], UINT64_MAX, __ATOMIC_RELAXED);
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 1000, &out) == -EPROTO);
    assert(!cursor);

    assert(pico_controller_motion_channel_init(c, 1, 2)); cursor = 0;
    for (unsigned i = 0; i <= PICO_CONTROLLER_MOTION_CAPACITY; ++i) {
        e = event(i); assert(pico_controller_motion_channel_publish(c, &e));
    }
    memcpy(&saved, &out, sizeof(out));
    assert(pico_controller_motion_channel_read(c, 1, 2, &cursor, clock_ns, NULL, 1000, &out) == -EOVERFLOW);
    assert(!cursor && !memcmp(&out, &saved, sizeof(out)));
    c->sequence = UINT64_MAX - 1; e = event(999);
    assert(!pico_controller_motion_channel_publish(c, &e));
    free(c);
}

struct shared {
    struct pico_controller_motion_channel channel;
    uint64_t acknowledged;
};

static void processes(void)
{
    struct shared *s = mmap(NULL, sizeof(*s), PROT_READ | PROT_WRITE,
                           MAP_ANONYMOUS | MAP_SHARED, -1, 0);
    assert(s != MAP_FAILED);
    assert(pico_controller_motion_channel_init(&s->channel, 55, 66));
    const unsigned count = 100000;
    fake_now = 1000200000;
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        uint64_t cursor = 0;
        for (unsigned i = 0; i < count;) {
            struct pico_controller_motion_event out;
            int rc = pico_controller_motion_channel_read(&s->channel, 55, 66, &cursor,
                                                         clock_ns, NULL, 100000000, &out);
            assert(rc == 0 || rc == 1 || rc == -EAGAIN);
            if (rc == 1) {
                struct pico_controller_motion_event expected = event(i);
                same(&expected, &out); ++i;
                __atomic_store_n(&s->acknowledged, i, __ATOMIC_RELEASE);
            } else sched_yield();
        }
        _Exit(0);
    }
    for (unsigned i = 0; i < count; ++i) {
        while (i - __atomic_load_n(&s->acknowledged, __ATOMIC_ACQUIRE) >= 128) sched_yield();
        struct pico_controller_motion_event e = event(i);
        assert(pico_controller_motion_channel_publish(&s->channel, &e));
    }
    int status; assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(s->acknowledged == count);
    pico_controller_motion_channel_stop(&s->channel);
    assert(!munmap(s, sizeof(*s)));
}

int main(void)
{
    alarm(20);
    boundaries(); processes();
    puts("PICO_CONTROLLER_MOTION_CHANNEL_PASS cross_process_samples=100000");
}
