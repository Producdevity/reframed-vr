#ifndef REFRAMED_PICO_CONTROLLER_MOTION_CONSUMER_H
#define REFRAMED_PICO_CONTROLLER_MOTION_CONSUMER_H

#include "pico-controller-head.h"
#include "pico-controller-motion-channel.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_controller_motion_consumer_config {
    const struct pico_controller_motion_channel *channel;
    struct pico_controller_head *heads;
    uint64_t instance, generation, head_generation;
    unsigned connected_mask;
    int64_t max_age_ns, max_gap_ns;
    void *data;
    int64_t (*monotonic_ns)(void *data);
    int (*update)(void *data, unsigned hand, const double values[9], int64_t timestamp_ns,
                  const uint8_t before[PICO_SLAM_RESULT_SIZE],
                  const uint8_t after[PICO_SLAM_RESULT_SIZE]);
};

struct pico_controller_motion_consumer_status {
    uint64_t read, delivered, head_waits;
    int64_t max_age_ns, max_head_wait_ns, max_call_ns;
    int error;
    bool pending, stopped;
};

struct pico_controller_motion_consumer;

/* Serialized consumer, including access to the borrowed head history. Prepare
 * the estimator first; create only after the producer initializes its mapping.
 * Head/world generation is independent of the motion generation. Recovery
 * requires a reset estimator and a new consumer/mapping; never revive this one.
 * A missing future head bracket retains one event without extrapolation. No
 * allocations or wakeup syscalls occur in poll. Stop/error is permanent and
 * affects neither the producer nor head tracking. No pose is published here. */
int pico_controller_motion_consumer_create(const struct pico_controller_motion_consumer_config *config,
                                          struct pico_controller_motion_consumer **consumer);
int pico_controller_motion_consumer_poll(struct pico_controller_motion_consumer *consumer);
void pico_controller_motion_consumer_status(const struct pico_controller_motion_consumer *consumer,
                                           struct pico_controller_motion_consumer_status *status);
void pico_controller_motion_consumer_stop(struct pico_controller_motion_consumer *consumer);
void pico_controller_motion_consumer_destroy(struct pico_controller_motion_consumer *consumer);

#ifdef __cplusplus
}
#endif
#endif
