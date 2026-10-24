#include "pico-controller-channel.h"
#include <string.h>

#define MAGIC UINT64_C(0x5256504943430001)

_Static_assert(__atomic_always_lock_free(8, 0), "Controller IPC requires lock-free 64-bit atomics");
_Static_assert(sizeof(struct pico_controller_channel) == 128, "Controller IPC layout changed");
_Static_assert(sizeof(struct pico_controller_sample) == 8, "Controller input layout changed");

static bool header(const struct pico_controller_channel *c)
{
    return c && __atomic_load_n(&c->magic, __ATOMIC_RELAXED) == MAGIC &&
        __atomic_load_n(&c->instance, __ATOMIC_RELAXED) != 0;
}

static bool store(struct pico_controller_channel *c, unsigned hand, const uint64_t words[3])
{
    unsigned h = hand - 1;
    uint64_t sequence = __atomic_load_n(&c->sequence[h], __ATOMIC_RELAXED);
    if (sequence > UINT64_MAX - 2 || (sequence & 1)) return false;
    if (!__atomic_compare_exchange_n(&c->sequence[h], &sequence, sequence + 1, false,
                                    __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) return false;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    unsigned next = ((sequence >> 1) & 1) ^ 1;
    for (unsigned i = 0; i < 3; i++)
        __atomic_store_n(&c->slots[h][next][i], words[i], __ATOMIC_RELAXED);
    __atomic_store_n(&c->sequence[h], sequence + 2, __ATOMIC_RELEASE);
    return true;
}

bool pico_controller_channel_init(struct pico_controller_channel *c, uint64_t instance)
{
    if (!c || !instance) return false;
    memset(c, 0, sizeof(*c));
    c->magic = MAGIC;
    c->instance = instance;
    return true;
}

bool pico_controller_channel_publish(struct pico_controller_channel *c,
                                     const struct pico_controller_sample *s, int64_t received)
{
    if (!header(c) || !s || s->hand < 1 || s->hand > 2 || received <= 0 ||
        (s->buttons & 64) || (s->touches & ~31) || s->battery_level > 7) return false;
    unsigned h = s->hand - 1;
    uint64_t sequence = __atomic_load_n(&c->sequence[h], __ATOMIC_RELAXED);
    uint64_t previous = __atomic_load_n(&c->slots[h][(sequence >> 1) & 1][0], __ATOMIC_RELAXED);
    if ((uint64_t)received <= previous) return false;
    uint64_t words[3] = {(uint64_t)received, 1, 0};
    memcpy(&words[2], s, sizeof(*s));
    return store(c, s->hand, words);
}

bool pico_controller_channel_disconnect(struct pico_controller_channel *c, unsigned hand)
{
    if (!header(c) || hand < 1 || hand > 2) return false;
    unsigned h = hand - 1;
    uint64_t sequence = __atomic_load_n(&c->sequence[h], __ATOMIC_RELAXED);
    uint64_t words[3] = {
        __atomic_load_n(&c->slots[h][(sequence >> 1) & 1][0], __ATOMIC_RELAXED), 0, 0};
    return store(c, hand, words);
}

bool pico_controller_channel_read(const struct pico_controller_channel *c,
                                  uint64_t instance, unsigned hand,
                                  int64_t (*clock_ns)(void *), void *clock_data,
                                  int64_t max_age, struct pico_controller_sample *sample)
{
    if (!header(c) || !instance || hand < 1 || hand > 2 || !clock_ns || !sample ||
        max_age <= 0 || max_age > 1000000000 ||
        instance != __atomic_load_n(&c->instance, __ATOMIC_RELAXED)) return false;
    unsigned h = hand - 1;
    for (unsigned attempt = 0; attempt < 16; attempt++) {
        uint64_t sequence = __atomic_load_n(&c->sequence[h], __ATOMIC_ACQUIRE), words[3];
        if (sequence > UINT64_MAX - 2) return false;
        for (unsigned i = 0; i < 3; i++)
            words[i] = __atomic_load_n(&c->slots[h][(sequence >> 1) & 1][i], __ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if ((sequence & ~UINT64_C(1)) !=
            (__atomic_load_n(&c->sequence[h], __ATOMIC_RELAXED) & ~UINT64_C(1))) continue;
        int64_t now = clock_ns(clock_data);
        if (words[1] != 1 || !words[0] || now <= 0 || words[0] > (uint64_t)now ||
            (uint64_t)now - words[0] > (uint64_t)max_age) return false;
        struct pico_controller_sample next;
        memcpy(&next, &words[2], sizeof(next));
        if (next.hand != hand || (next.buttons & 64) || (next.touches & ~31) || next.battery_level > 7)
            return false;
        *sample = next;
        return true;
    }
    return false;
}
