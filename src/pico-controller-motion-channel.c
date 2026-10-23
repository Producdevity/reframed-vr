#include "pico-controller-motion-channel.h"

#include <errno.h>
#include <math.h>
#include <string.h>

#define MAGIC UINT64_C(0x525650434d430001)

_Static_assert(__atomic_always_lock_free(8, 0), "Motion IPC requires lock-free 64-bit atomics");
_Static_assert(sizeof(double) == 8, "Motion IPC requires binary64");
_Static_assert(sizeof(struct pico_controller_motion_channel) == 32832, "Motion IPC layout changed");

static bool header(const struct pico_controller_motion_channel *c)
{
    return c && __atomic_load_n(&c->magic, __ATOMIC_ACQUIRE) == MAGIC &&
        __atomic_load_n(&c->instance, __ATOMIC_RELAXED) &&
        __atomic_load_n(&c->generation, __ATOMIC_RELAXED);
}

static bool valid(const struct pico_controller_motion_event *e, int64_t now, int64_t max_age)
{
    if (!e || !e->timestamp_us || e->hand < 1 || e->hand > 2 ||
        e->time.timestamp_ns <= 0 || e->time.uncertainty_ns < 0 ||
        e->time.uncertainty_ns > e->time.timestamp_ns ||
        e->time.uncertainty_ns > max_age || e->received_ns <= 0 ||
        e->received_ns > now || e->time.timestamp_ns > e->received_ns ||
        e->received_ns - e->time.timestamp_ns < e->time.uncertainty_ns ||
        now - e->time.timestamp_ns > max_age - e->time.uncertainty_ns)
        return false;
    for (unsigned i = 0; i < 9; ++i) if (!isfinite(e->values[i])) return false;
    return e->values[7] == (e->flags & 1) && e->values[8] == (e->flags >> 1);
}

bool pico_controller_motion_channel_init(struct pico_controller_motion_channel *c,
                                         uint64_t instance, uint64_t generation)
{
    if (!c || !instance || !generation) return false;
    memset(c, 0, sizeof(*c));
    c->instance = instance;
    c->generation = generation;
    c->active = 1;
    __atomic_store_n(&c->magic, MAGIC, __ATOMIC_RELEASE);
    return true;
}

bool pico_controller_motion_channel_publish(struct pico_controller_motion_channel *c,
    const struct pico_controller_motion_event *e)
{
    if (!header(c) || __atomic_load_n(&c->active, __ATOMIC_ACQUIRE) != 1 ||
        !e || !valid(e, e->received_ns, PICO_CONTROLLER_MOTION_MAX_AGE_NS)) return false;
    uint64_t sequence = __atomic_load_n(&c->sequence, __ATOMIC_RELAXED);
    if (sequence >= UINT64_MAX - 1 ||
        (uint64_t)e->time.timestamp_ns <= __atomic_load_n(&c->last_time[e->hand - 1], __ATOMIC_RELAXED) ||
        (uint64_t)e->received_ns < __atomic_load_n(&c->last_received, __ATOMIC_RELAXED)) return false;
    uint64_t words[14] = {e->timestamp_us, (uint64_t)e->time.timestamp_ns,
        (uint64_t)e->time.uncertainty_ns, (uint64_t)e->received_ns,
        e->hand | (uint64_t)e->sequence << 8 | (uint64_t)e->flags << 16};
    memcpy(words + 5, e->values, sizeof(e->values));
    uint64_t *slot = c->slots[sequence % PICO_CONTROLLER_MOTION_CAPACITY];
    __atomic_store_n(slot, 0, __ATOMIC_RELEASE);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    for (unsigned i = 0; i < 14; ++i) __atomic_store_n(slot + 1 + i, words[i], __ATOMIC_RELAXED);
    __atomic_store_n(slot, sequence + 1, __ATOMIC_RELEASE);
    __atomic_store_n(&c->last_time[e->hand - 1], (uint64_t)e->time.timestamp_ns, __ATOMIC_RELAXED);
    __atomic_store_n(&c->last_received, (uint64_t)e->received_ns, __ATOMIC_RELAXED);
    __atomic_store_n(&c->sequence, sequence + 1, __ATOMIC_RELEASE);
    return true;
}

void pico_controller_motion_channel_stop(struct pico_controller_motion_channel *c)
{
    if (header(c)) __atomic_store_n(&c->active, 0, __ATOMIC_RELEASE);
}

int pico_controller_motion_channel_read(const struct pico_controller_motion_channel *c,
    uint64_t instance, uint64_t generation, uint64_t *cursor,
    int64_t (*clock_ns)(void *), void *clock_data, int64_t max_age,
    struct pico_controller_motion_event *event)
{
    if (!cursor || !clock_ns || !event || max_age <= 0 ||
        max_age > PICO_CONTROLLER_MOTION_MAX_AGE_NS) return -EINVAL;
    if (!header(c) || !instance || !generation ||
        __atomic_load_n(&c->instance, __ATOMIC_RELAXED) != instance ||
        __atomic_load_n(&c->generation, __ATOMIC_RELAXED) != generation) return -ESTALE;
    for (unsigned attempt = 0; attempt < 16; ++attempt) {
        if (__atomic_load_n(&c->active, __ATOMIC_ACQUIRE) != 1) return -ESHUTDOWN;
        uint64_t latest = __atomic_load_n(&c->sequence, __ATOMIC_ACQUIRE);
        if (*cursor > latest || latest == UINT64_MAX) return -EPROTO;
        if (latest - *cursor > PICO_CONTROLLER_MOTION_CAPACITY) return -EOVERFLOW;
        if (*cursor == latest) return 0;
        uint64_t sequence = *cursor + 1, words[14];
        const uint64_t *slot = c->slots[*cursor % PICO_CONTROLLER_MOTION_CAPACITY];
        uint64_t stamp = __atomic_load_n(slot, __ATOMIC_ACQUIRE);
        if (stamp > sequence) return -EOVERFLOW;
        if (stamp != sequence) continue;
        for (unsigned i = 0; i < 14; ++i) words[i] = __atomic_load_n(slot + 1 + i, __ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if (__atomic_load_n(slot, __ATOMIC_RELAXED) != stamp) continue;
        struct pico_controller_motion_event next = {
            .timestamp_us = words[0], .time = {(int64_t)words[1], (int64_t)words[2]},
            .received_ns = (int64_t)words[3],
            .hand = (uint8_t)words[4], .sequence = (uint8_t)(words[4] >> 8),
            .flags = (uint8_t)(words[4] >> 16)};
        memcpy(next.values, words + 5, sizeof(next.values));
        int64_t now = clock_ns(clock_data);
        if (__atomic_load_n(&c->active, __ATOMIC_ACQUIRE) != 1) return -ESHUTDOWN;
        if (words[4] >> 24 || !valid(&next, next.received_ns, PICO_CONTROLLER_MOTION_MAX_AGE_NS))
            return -EPROTO;
        if (!valid(&next, now, max_age)) return -ETIMEDOUT;
        *event = next;
        *cursor = sequence;
        return 1;
    }
    return -EAGAIN;
}
