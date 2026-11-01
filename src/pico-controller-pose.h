#ifndef REFRAMED_PICO_CONTROLLER_POSE_H
#define REFRAMED_PICO_CONTROLLER_POSE_H

#include "pico-slam-channel.h"

#ifdef __cplusplus
extern "C" {
#endif

/* b1977 getAlgorithmControllerResult reports the controller in the same vendor
 * world as the head result, in millimetres. tracker_from_model maps the
 * attributed Neo3 render model into the tracker's controller frame. */
struct pico_controller_pose_config {
    struct pico_slam_pose world_from_slam, tracker_from_model;
    int64_t max_age_ns;
};

struct pico_controller_pose_output {
    struct pico_slam_channel *channel;
    uint64_t generation;
    struct pico_controller_pose_config config;
    int64_t last_timestamp_ns;
    bool tracked;
};

enum pico_controller_pose_result {
    PICO_CONTROLLER_POSE_REFUSED = -1,
    PICO_CONTROLLER_POSE_LOST,
    PICO_CONTROLLER_POSE_UNCHANGED,
    PICO_CONTROLLER_POSE_PUBLISHED,
};

/* Begins generation on an initialized channel and validates the transforms. */
bool pico_controller_pose_begin(struct pico_controller_pose_output *output,
                                struct pico_slam_channel *channel, uint64_t generation,
                                const struct pico_controller_pose_config *config);

/* Publishes only state 1 with the getter's unmodified internal confidence
 * (byte 0x52) set; the public confidence byte can be synthesized by the getter.
 * Untracked, undecodable or stale results invalidate the pose so a later
 * acquisition can recover it. A repeated or older timestamp changes nothing. */
enum pico_controller_pose_result pico_controller_pose_publish(
    struct pico_controller_pose_output *output, const void *raw, size_t size,
    int64_t uncertainty_ns, int64_t now_ns);

void pico_controller_pose_stop(struct pico_controller_pose_output *output);

#ifdef __cplusplus
}
#endif
#endif
