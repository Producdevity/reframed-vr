#ifndef REFRAMED_PICO_SLAM_POSE_H
#define REFRAMED_PICO_SLAM_POSE_H

#include "pico-slam-result.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_slam_pose {
    double orientation[4]; /* x, y, z, w */
    double position[3]; /* metres */
};

enum pico_slam_pose_direction {
    PICO_SLAM_WORLD_FROM_BODY = 1,
    PICO_SLAM_BODY_FROM_WORLD,
};

struct pico_slam_pose_config {
    struct pico_slam_pose world_from_slam, body_from_head;
    enum pico_slam_pose_direction direction;
    double metres_per_unit;
    int64_t max_age_ns;
};

/* T_world_head = T_world_slam * T_slam_body * T_body_head.
 * Caller supplies verified frame direction, metric scale and head extrinsics;
 * there are no inferred defaults, recentering or prediction. All times use
 * CLOCK_MONOTONIC. Only the observed b1977 state=1/confidence=1 is accepted;
 * the vendor error field remains opaque. Failure preserves the output. */
bool pico_slam_pose_convert(const struct pico_slam_pose_config *config,
                            const struct pico_slam_result *result,
                            int64_t uncertainty_ns, int64_t now_ns,
                            struct pico_slam_pose *world_from_head);

#ifdef __cplusplus
}
#endif
#endif
