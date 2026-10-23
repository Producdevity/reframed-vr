#include "pico-controller-motion-producer.h"

#include <errno.h>
#include <string.h>

static int fail(struct pico_controller_motion_producer *p, int error)
{
    if (!p->error) p->error = error;
    pico_controller_motion_channel_stop(p->channel);
    return p->error;
}

int pico_controller_motion_producer_init(struct pico_controller_motion_producer *p,
    struct pico_controller_motion_channel *channel, uint64_t instance, uint64_t generation,
    const struct ssc_clock *clock, const struct pico_controller_motion_config config[2],
    unsigned mcu_type, unsigned radio_type, unsigned mask, int64_t now)
{
    if (!p || !channel || !instance || !generation || !clock || !config || now <= 0 ||
        !clock->initialized || !clock->counter_hz || clock->host_ns < 0 || clock->host_ns > now ||
        clock->uncertainty_ns < 2 || clock->uncertainty_ns > PICO_CONTROLLER_MOTION_MAX_AGE_NS - 1000 ||
        mcu_type < 1 || mcu_type > 2 || radio_type < 1 || radio_type > 2 || !mask || mask > 3)
        return -EINVAL;
    for (unsigned hand = 0; hand < 2; ++hand)
        if ((mask & (1U << hand)) && config[hand].mcu_type != mcu_type) return -EINVAL;
    struct pico_controller_motion_producer next = {
        .channel = channel, .clock = *clock, .generation = generation,
        .started = now, .now = now, .mcu_type = mcu_type, .radio_type = radio_type,
        .connected_mask = mask};
    memcpy(next.config, config, sizeof(next.config));
    if (!pico_controller_motion_channel_init(channel, instance, generation)) return -EINVAL;
    *p = next;
    return 0;
}

int pico_controller_motion_producer_update(struct pico_controller_motion_producer *p,
    uint64_t generation, const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now)
{
    if (!p || !p->channel) return -EINVAL;
    if (generation != p->generation) return -ESTALE;
    if (p->error) return p->error;
    if (!first || !second) return fail(p, -EINVAL);
    if (now <= 0 || now < p->now) return fail(p, -ETIME);
    p->now = now;
    struct pico_controller_motion_ring ring = p->ring;
    struct pico_controller_imu_sample samples[PICO_CONTROLLER_RING_MAX_IMU];
    int count = pico_controller_ring_read_motion(&ring, first, second,
        p->mcu_type, p->radio_type, p->connected_mask, samples);
    if (count < 0) return fail(p, count);
    struct pico_controller_motion_event pending[PICO_CONTROLLER_RING_MAX_IMU];
    unsigned delivered = 0;
    for (int i = 0; i < count; ++i) {
        const struct pico_controller_imu_sample *s = &samples[i];
        struct pico_controller_motion_event *e = &pending[i];
        *e = (struct pico_controller_motion_event){.timestamp_us = s->timestamp_us,
            .received_ns = now, .hand = s->hand, .sequence = s->sequence, .flags = s->flags};
        if (!pico_controller_motion_time(&p->clock, s->timestamp_us, now,
                PICO_CONTROLLER_MOTION_MAX_AGE_NS, &e->time)) return fail(p, -ETIMEDOUT);
        if (!pico_controller_motion_values(s, &p->config[s->hand - 1], e->values)) return fail(p, -EPROTO);
        delivered |= 1U << (s->hand - 1);
    }
    for (unsigned hand = 0; hand < 2; ++hand)
        if ((p->connected_mask & ~delivered) & (1U << hand))
            if ((p->received[hand] && now - p->received[hand] > PICO_CONTROLLER_MOTION_MAX_AGE_NS) ||
                (!p->received[hand] && now - p->started >= INT64_C(2000000000)))
                return fail(p, -ETIMEDOUT);
    for (int i = 0; i < count; ++i) {
        if (!pico_controller_motion_channel_publish(p->channel, &pending[i])) return fail(p, -EPROTO);
        p->received[pending[i].hand - 1] = now;
    }
    p->ring = ring;
    return count;
}

void pico_controller_motion_producer_stop(struct pico_controller_motion_producer *p)
{
    if (p && p->channel) fail(p, -ESHUTDOWN);
}

int pico_controller_motion_producer_resumed(const struct pico_controller_motion_producer *p,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now,
    struct ssc_timestamp captures[2])
{
    if (!p || !p->channel || !first || !second || !captures || now <= 0 || now < p->now)
        return -EINVAL;
    if (p->error != -ETIMEDOUT) return -EPERM;
    struct pico_controller_motion_ring ring = p->ring;
    struct pico_controller_imu_sample samples[PICO_CONTROLLER_RING_MAX_IMU];
    int rc = pico_controller_ring_read_motion(&ring, first, second,
        p->mcu_type, p->radio_type, p->connected_mask, samples);
    if (rc < 0) return rc;
    struct ssc_timestamp pending[2] = {{0}};
    for (unsigned hand = 0; hand < 2; ++hand) if (p->connected_mask & (1U << hand)) {
        const struct pico_controller_imu_sample *sample = &ring.latest[hand];
        if (sample->timestamp_us <= p->ring.latest[hand].timestamp_us ||
            !pico_controller_motion_time(&p->clock, sample->timestamp_us, now,
                PICO_CONTROLLER_MOTION_MAX_AGE_NS, &pending[hand]) ||
            pending[hand].timestamp_ns - pending[hand].uncertainty_ns <= p->now) return 0;
        double values[9];
        if (!pico_controller_motion_values(sample, &p->config[hand], values)) return -EPROTO;
    }
    memcpy(captures, pending, sizeof(pending));
    return 1;
}

int pico_controller_motion_producer_restart(struct pico_controller_motion_producer *p,
    struct pico_controller_motion_channel *channel, uint64_t generation,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now)
{
    if (!p || !p->channel || !channel || channel == p->channel ||
        !first || !second || now <= 0 || now < p->now ||
        __atomic_load_n(&channel->magic, __ATOMIC_ACQUIRE)) return -EINVAL;
    if (!p->error || (p->error != -ETIMEDOUT && p->error != -ESHUTDOWN)) return -EPERM;
    if (generation <= p->generation) return -ESTALE;
    struct pico_controller_motion_ring ring = p->ring;
    struct pico_controller_imu_sample discarded[PICO_CONTROLLER_RING_MAX_IMU];
    int rc = pico_controller_ring_read_motion(&ring, first, second,
        p->mcu_type, p->radio_type, p->connected_mask, discarded);
    if (rc < 0) return rc;
    struct pico_controller_motion_producer next;
    rc = pico_controller_motion_producer_init(&next, channel, p->channel->instance,
        generation, &p->clock, p->config, p->mcu_type, p->radio_type, p->connected_mask, now);
    if (rc) return rc;
    next.ring = ring;
    *p = next;
    return 0;
}
