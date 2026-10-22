#include "pico-controller-head.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static const int64_t base = 1000000000, period = 1000000;

static void integer(uint8_t *p, uint64_t n)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(n >> (8 * i));
}

static uint64_t timestamp(const uint8_t *p)
{
    uint64_t n = 0;
    for (unsigned i = 0; i < 8; ++i) n |= (uint64_t)p[i] << (8 * i);
    return n;
}

static void result(uint8_t raw[PICO_SLAM_RESULT_SIZE], unsigned n, bool tracked)
{
    memset(raw, 0, PICO_SLAM_RESULT_SIZE);
    integer(raw, (uint64_t)(base + n * period));
    integer(raw + 0x20, UINT64_C(0x3ff0000000000000));
    raw[0x40] = 1;
    raw[0x41] = tracked;
    raw[0x100] = (uint8_t)n;
}

static void unchanged(struct pico_controller_head *h, struct ssc_timestamp time,
                      int64_t now, int error)
{
    uint8_t a[PICO_SLAM_RESULT_SIZE], b[PICO_SLAM_RESULT_SIZE];
    memset(a, 0x55, sizeof(a)); memset(b, 0x66, sizeof(b));
    assert(pico_controller_head_match(h, 7, time, now, a, b) == error);
    for (unsigned i = 0; i < sizeof(a); ++i) assert(a[i] == 0x55 && b[i] == 0x66);
}

int main(void)
{
    assert(!pico_controller_head_create(0, period, period));
    assert(!pico_controller_head_create(1, 0, period));
    assert(!pico_controller_head_create(1, period, period + 1));
    struct pico_controller_head *h = pico_controller_head_create(7, 100000000, 2000000);
    assert(h);
    uint8_t raw[PICO_SLAM_RESULT_SIZE], a[PICO_SLAM_RESULT_SIZE], b[PICO_SLAM_RESULT_SIZE];
    for (unsigned i = 0; i < 19; ++i) {
        result(raw, i, true);
        assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + i * period + 1000) == 0);
    }
    unchanged(h, (struct ssc_timestamp){base + period / 2, 100}, base + 19 * period, -EAGAIN);
    result(raw, 19, true);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + 19 * period + 1000) == 1);
    int64_t now = base + 20 * period;
    assert(!pico_controller_head_match(h, 7, (struct ssc_timestamp){base + 8500000, 100}, now, a, b));
    assert(timestamp(a) == (uint64_t)(base + 8 * period));
    assert(timestamp(b) == (uint64_t)(base + 9 * period));
    result(raw, 8, true); assert(!memcmp(raw, a, sizeof(raw)));
    result(raw, 9, true); assert(!memcmp(raw, b, sizeof(raw)));
    assert(!pico_controller_head_match(h, 7, (struct ssc_timestamp){base + 9 * period, 0}, now, a, b));
    assert(timestamp(a) == (uint64_t)(base + 8 * period));
    assert(timestamp(b) == (uint64_t)(base + 10 * period));
    unchanged(h, (struct ssc_timestamp){base + 9 * period, period}, now, -ETIMEDOUT);
    unchanged(h, (struct ssc_timestamp){base + 19500000, 0}, now, -EAGAIN);
    unchanged(h, (struct ssc_timestamp){now, 1}, now, -ETIMEDOUT);
    result(raw, 20, true);
    assert(pico_controller_head_push(h, 6, raw, sizeof(raw), 20, now + period) == -ESTALE);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, now + period) == 1);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, now + period) == -EALREADY);
    raw[0x41] = 0;
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, now + period) == 0);
    unchanged(h, (struct ssc_timestamp){base + 18500000, 0}, now + period, -EAGAIN);
    for (unsigned i = 21; i <= 40; ++i) {
        result(raw, i, true);
        assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + i * period + 1000)
               == (i == 40));
    }
    result(raw, 44, true);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + 44 * period + 1000) == 0);
    unchanged(h, (struct ssc_timestamp){base + 39 * period, 0}, base + 45 * period, -EAGAIN);
    result(raw, 43, true);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + 45 * period) == -EPROTO);
    result(raw, 45, true);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + 46 * period) == -EPROTO);
    pico_controller_head_destroy(h);

    h = pico_controller_head_create(7, 1000000000, 2000000); assert(h);
    for (unsigned i = 0; i < 600; ++i) {
        result(raw, i, true);
        assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + i * period + 1000)
               == (i >= 19));
    }
    now = base + 600 * period;
    assert(!pico_controller_head_match(h, 7, (struct ssc_timestamp){base + 590500000, 100}, now, a, b));
    assert(timestamp(a) == (uint64_t)(base + 590 * period));
    unchanged(h, (struct ssc_timestamp){base + 50500000, 100}, now, -EAGAIN);
    assert(pico_controller_head_match(h, 7, (struct ssc_timestamp){base + 590500000, 100}, now, a, a) == -EINVAL);
    result(raw, 600, true);
    raw[0x45] = 2;
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, now + 1000) == 1);
    assert(!pico_controller_head_match(h, 7, (struct ssc_timestamp){base + 599500000, 100}, now + 1000, a, b));
    assert(!memcmp(b, raw, sizeof(raw)));
    for (unsigned i = 601; i <= 620; ++i) {
        result(raw, i, true);
        assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + i * period + 1000)
               == 1);
    }
    now = base + 620 * period + 1000;
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, now) == -EALREADY);
    pico_controller_head_stop(h);
    unchanged(h, (struct ssc_timestamp){base + 590500000, 100}, now, -ESHUTDOWN);
    pico_controller_head_destroy(h);
    h = pico_controller_head_create(7, 100000000, 2000000); assert(h);
    result(raw, 1, true);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + period + 1000) == 0);
    raw[0x100] ^= 1;
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw), 20, base + period + 1000) == -EPROTO);
    pico_controller_head_destroy(h);
    h = pico_controller_head_create(7, 100000000, 2000000); assert(h);
    assert(pico_controller_head_push(h, 7, raw, sizeof(raw) - 1, 20, base + period + 1000) == -EPROTO);
    pico_controller_head_destroy(h);
    pico_controller_head_stop(NULL);
    pico_controller_head_destroy(NULL);
    puts("PICO_CONTROLLER_HEAD_PASS");
}
