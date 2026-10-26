#include "pico-controller-head.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#define CAPACITY 512
#define MIN_TRACKED 20

struct head_result {
    struct ssc_timestamp time;
    uint8_t raw[PICO_SLAM_RESULT_SIZE];
};

struct pico_controller_head {
    uint64_t generation;
    int64_t max_age, max_gap, last_time, now;
    unsigned count, next;
    int error;
    struct head_result results[CAPACITY];
};

static bool fresh(struct ssc_timestamp time, int64_t now, int64_t max_age)
{
    return time.timestamp_ns > 0 && time.uncertainty_ns >= 0 &&
        time.uncertainty_ns <= time.timestamp_ns && time.uncertainty_ns <= max_age &&
        now >= time.timestamp_ns && now - time.timestamp_ns >= time.uncertainty_ns &&
        now - time.timestamp_ns <= max_age - time.uncertainty_ns;
}

struct pico_controller_head *pico_controller_head_create(uint64_t generation,
    int64_t max_age, int64_t max_gap)
{
    if (!generation || max_age <= 0 || max_age > 1000000000 ||
        max_gap <= 0 || max_gap > max_age) return NULL;
    struct pico_controller_head *h = calloc(1, sizeof(*h));
    if (h) {
        h->generation = generation;
        h->max_age = max_age;
        h->max_gap = max_gap;
    }
    return h;
}

static int fail(struct pico_controller_head *h, int error)
{
    h->count = 0;
    if (!h->error) h->error = error;
    return h->error;
}

static int check(struct pico_controller_head *h, uint64_t generation, int64_t now)
{
    if (!h) return -EINVAL;
    if (generation != h->generation) return -ESTALE;
    if (h->error) return h->error;
    if (now <= 0 || now < h->now) return fail(h, -ETIME);
    h->now = now;
    return 0;
}

int pico_controller_head_push(struct pico_controller_head *h, uint64_t generation,
    const void *raw, size_t size, int64_t uncertainty, int64_t now)
{
    int rc = check(h, generation, now);
    if (rc) return rc;
    struct pico_slam_result result;
    if (!pico_slam_result_decode(raw, size, &result) ||
        !fresh((struct ssc_timestamp){result.timestamp_ns, uncertainty}, now, h->max_age))
        return fail(h, -EPROTO);
    if (result.timestamp_ns < h->last_time) return fail(h, -EPROTO);
    if (result.timestamp_ns == h->last_time) {
        if (result.state != 1 || result.confidence != 1) {
            h->count = 0;
            return 0;
        }
        if (h->count && memcmp(h->results[(h->next + CAPACITY - 1) % CAPACITY].raw, raw, size))
            return fail(h, -EPROTO);
        return -EALREADY;
    }
    if (h->last_time && result.timestamp_ns - h->last_time > h->max_gap) h->count = 0;
    h->last_time = result.timestamp_ns;
    if (result.state != 1 || result.confidence != 1) {
        h->count = 0;
        return 0;
    }
    struct head_result *slot = &h->results[h->next];
    slot->time = (struct ssc_timestamp){result.timestamp_ns, uncertainty};
    memcpy(slot->raw, raw, sizeof(slot->raw));
    h->next = (h->next + 1) % CAPACITY;
    if (h->count < CAPACITY) ++h->count;
    return h->count >= MIN_TRACKED;
}

int pico_controller_head_match(struct pico_controller_head *h, uint64_t generation,
    struct ssc_timestamp input, int64_t now,
    uint8_t before[PICO_SLAM_RESULT_SIZE], uint8_t after[PICO_SLAM_RESULT_SIZE])
{
    int rc = check(h, generation, now);
    if (rc) return rc;
    if (!before || !after || before == after) return -EINVAL;
    if (!fresh(input, now, h->max_age)) return -ETIMEDOUT;
    if (h->count < MIN_TRACKED) return -EAGAIN;
    const struct head_result *a = NULL, *b = NULL;
    for (unsigned i = 0; i < h->count; ++i) {
        const struct head_result *s = &h->results[(h->next + CAPACITY - h->count + i) % CAPACITY];
        if (s->time.timestamp_ns + s->time.uncertainty_ns < input.timestamp_ns - input.uncertainty_ns)
            a = s;
        if (s->time.timestamp_ns - s->time.uncertainty_ns >= input.timestamp_ns + input.uncertainty_ns) {
            b = s;
            break;
        }
    }
    if (!a || !b) return -EAGAIN;
    if (b->time.timestamp_ns - a->time.timestamp_ns > h->max_gap ||
        !fresh(a->time, now, h->max_age) || !fresh(b->time, now, h->max_age))
        return -ETIMEDOUT;
    memcpy(before, a->raw, PICO_SLAM_RESULT_SIZE);
    memcpy(after, b->raw, PICO_SLAM_RESULT_SIZE);
    return 0;
}

void pico_controller_head_stop(struct pico_controller_head *h)
{
    if (h) fail(h, -ESHUTDOWN);
}

void pico_controller_head_destroy(struct pico_controller_head *h)
{
    free(h);
}
