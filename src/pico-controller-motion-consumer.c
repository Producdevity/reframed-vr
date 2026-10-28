#include "pico-controller-motion-consumer.h"

#include <errno.h>
#include <stdlib.h>

struct pico_controller_motion_consumer {
    struct pico_controller_motion_consumer_config config;
    struct pico_controller_motion_consumer_status status;
    struct pico_controller_motion_event pending;
    uint64_t cursor;
    int64_t now, waiting_since, last_time[2];
};

static int fail(struct pico_controller_motion_consumer *c, int error,
                enum pico_controller_motion_failure failure,
                const struct pico_controller_motion_event *event, int64_t now)
{
    c->status.stopped = true;
    if (!c->status.error) {
        c->status.error = error;
        c->status.failure = failure;
        c->status.failure_now_ns = now;
        if (event) {
            c->status.rejected_hand = event->hand;
            c->status.rejected_sequence = event->sequence;
            c->status.rejected_timestamp_ns = event->time.timestamp_ns;
            if (event->hand >= 1 && event->hand <= 2)
                c->status.previous_timestamp_ns = c->last_time[event->hand - 1];
        }
    }
    return c->status.error;
}

int pico_controller_motion_consumer_create(const struct pico_controller_motion_consumer_config *cfg,
                                          struct pico_controller_motion_consumer **consumer)
{
    if (!cfg || !consumer || *consumer || !cfg->channel || !cfg->heads ||
        !cfg->instance || !cfg->generation || !cfg->head_generation ||
        !cfg->connected_mask || cfg->connected_mask > 3 ||
        !cfg->monotonic_ns || !cfg->update || cfg->max_age_ns <= 0 ||
        cfg->max_age_ns > PICO_CONTROLLER_MOTION_MAX_AGE_NS ||
        cfg->max_gap_ns <= 0 || cfg->max_gap_ns > cfg->max_age_ns) return -EINVAL;
    struct pico_controller_motion_consumer *c = calloc(1, sizeof(*c));
    if (!c) return -ENOMEM;
    c->config = *cfg;
    *consumer = c;
    return 0;
}

int pico_controller_motion_consumer_poll(struct pico_controller_motion_consumer *c)
{
    if (!c) return -EINVAL;
    if (c->status.stopped) return c->status.error ? c->status.error : -ESHUTDOWN;
    for (unsigned batch = 0; batch < PICO_CONTROLLER_MOTION_CAPACITY; ++batch) {
        struct pico_controller_motion_event next;
        uint64_t cursor = c->cursor;
        int rc = pico_controller_motion_channel_read(c->config.channel, c->config.instance,
            c->config.generation, &cursor, c->config.monotonic_ns, c->config.data,
            c->config.max_age_ns, &next);
        if (rc < 0 && rc != -EAGAIN)
            return fail(c, rc, PICO_CONTROLLER_MOTION_FAILURE_CHANNEL, NULL, c->now);
        int64_t now = c->config.monotonic_ns(c->config.data);
        if (now <= 0 || now < c->now)
            return fail(c, -ETIME, PICO_CONTROLLER_MOTION_FAILURE_CLOCK, NULL, now);
        c->now = now;
        for (unsigned i = 0; i < 2; ++i)
            if (c->last_time[i] && now - c->last_time[i] > c->config.max_age_ns)
                return fail(c, -ETIMEDOUT, PICO_CONTROLLER_MOTION_FAILURE_EXPIRED, NULL, now);
        if (!c->status.pending) {
            if (rc != 1) return 0;
            if (!(c->config.connected_mask & (1u << (next.hand - 1))))
                return fail(c, -EPROTO, PICO_CONTROLLER_MOTION_FAILURE_HAND, &next, now);
            int64_t previous = c->last_time[next.hand - 1];
            if (previous && next.time.timestamp_ns <= previous)
                return fail(c, -EPROTO, PICO_CONTROLLER_MOTION_FAILURE_TIMESTAMP, &next, now);
            if (previous && next.time.timestamp_ns - previous > c->config.max_gap_ns)
                return fail(c, -EPROTO, PICO_CONTROLLER_MOTION_FAILURE_GAP, &next, now);
            c->pending = next;
            c->cursor = cursor;
            c->waiting_since = now;
            c->status.pending = true;
            ++c->status.read;
        }
        const struct pico_controller_motion_event *e = &c->pending;
        if (now < e->time.timestamp_ns || now - e->time.timestamp_ns >
            c->config.max_age_ns - e->time.uncertainty_ns)
            return fail(c, -ETIMEDOUT, PICO_CONTROLLER_MOTION_FAILURE_EXPIRED, e, now);
        uint8_t before[PICO_SLAM_RESULT_SIZE], after[PICO_SLAM_RESULT_SIZE];
        rc = pico_controller_head_match(c->config.heads, c->config.head_generation, e->time, now, before, after);
        if (rc == -EAGAIN) { ++c->status.head_waits; return 0; }
        if (rc) return fail(c, rc, PICO_CONTROLLER_MOTION_FAILURE_HEAD, e, now);
        int64_t begin = c->config.monotonic_ns(c->config.data);
        if (begin < now) return fail(c, -ETIME, PICO_CONTROLLER_MOTION_FAILURE_CLOCK, e, begin);
        if (begin - e->time.timestamp_ns > c->config.max_age_ns - e->time.uncertainty_ns)
            return fail(c, -ETIMEDOUT, PICO_CONTROLLER_MOTION_FAILURE_EXPIRED, e, begin);
        int64_t age = begin - e->time.timestamp_ns + e->time.uncertainty_ns;
        if (age > c->status.max_age_ns) c->status.max_age_ns = age;
        int64_t wait = begin - c->waiting_since;
        if (wait > c->status.max_head_wait_ns) c->status.max_head_wait_ns = wait;
        rc = c->config.update(c->config.data, e->hand, e->values, e->time.timestamp_ns, before, after);
        int64_t end = c->config.monotonic_ns(c->config.data);
        if (end < begin) return fail(c, -ETIME, PICO_CONTROLLER_MOTION_FAILURE_CLOCK, e, end);
        if (end - begin > c->status.max_call_ns) c->status.max_call_ns = end - begin;
        c->now = end;
        if (rc) return fail(c, rc < 0 ? rc : -EIO, PICO_CONTROLLER_MOTION_FAILURE_UPDATE, e, end);
        c->last_time[e->hand - 1] = e->time.timestamp_ns;
        ++c->status.delivered;
        c->status.pending = false;
        if (end - e->time.timestamp_ns > c->config.max_age_ns - e->time.uncertainty_ns)
            return fail(c, -ETIMEDOUT, PICO_CONTROLLER_MOTION_FAILURE_EXPIRED, e, end);
    }
    return 0;
}

void pico_controller_motion_consumer_status(const struct pico_controller_motion_consumer *c,
                                           struct pico_controller_motion_consumer_status *status)
{
    if (c && status) *status = c->status;
}

void pico_controller_motion_consumer_stop(struct pico_controller_motion_consumer *c)
{
    if (c) c->status.stopped = true;
}

void pico_controller_motion_consumer_destroy(struct pico_controller_motion_consumer *c)
{
    free(c);
}
