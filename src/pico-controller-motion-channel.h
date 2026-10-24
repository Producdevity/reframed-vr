#ifndef REFRAMED_PICO_CONTROLLER_MOTION_CHANNEL_H
#define REFRAMED_PICO_CONTROLLER_MOTION_CHANNEL_H

#include "ssc-clock.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PICO_CONTROLLER_MOTION_CAPACITY 256
#define PICO_CONTROLLER_MOTION_MAX_AGE_NS INT64_C(100000000)

struct pico_controller_motion_event {
    uint64_t timestamp_us;
    struct ssc_timestamp time;
    int64_t received_ns;
    double values[9];
    uint8_t hand, sequence, flags;
};

struct pico_controller_motion_channel {
    uint64_t magic, instance, generation, sequence, active, last_time[2], last_received;
    uint64_t slots[PICO_CONTROLLER_MOTION_CAPACITY][16];
};

/* One serialized producer, fresh mapping/instance/generation per connection.
 * Publish converted stock units and calibrated CLOCK_MONOTONIC capture times.
 * Receipt times may coincide within one snapshot; capture times increase per
 * hand. Stop is permanent. No reader can backpressure a DSP owner. */
bool pico_controller_motion_channel_init(struct pico_controller_motion_channel *channel,
                                         uint64_t instance, uint64_t generation);
bool pico_controller_motion_channel_publish(struct pico_controller_motion_channel *channel,
    const struct pico_controller_motion_event *event);
void pico_controller_motion_channel_stop(struct pico_controller_motion_channel *channel);

/* One serialized cursor per reader, initially zero. 1 = next event, 0 = none;
 * -EAGAIN = writer in progress, -EOVERFLOW = unread history overwritten,
 * -ETIMEDOUT = stale, -ESTALE = wrong binding, -ESHUTDOWN = stopped.
 * All refusals preserve cursor/output. Do not skip an overrun or stale event:
 * restart the estimator/stream explicitly. Clock is sampled after copying.
 * The caller still enforces per-hand capture gaps and head-history brackets.
 * No controller pose, calibration default or optical validity is inferred. */
int pico_controller_motion_channel_read(const struct pico_controller_motion_channel *channel,
    uint64_t instance, uint64_t generation, uint64_t *cursor,
    int64_t (*clock_ns)(void *), void *clock_data, int64_t max_age_ns,
    struct pico_controller_motion_event *event);

#ifdef __cplusplus
}
#endif
#endif
