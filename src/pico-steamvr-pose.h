#ifndef REFRAMED_PICO_STEAMVR_POSE_H
#define REFRAMED_PICO_STEAMVR_POSE_H

#include <openvr_driver.h>
#include "pico-slam-channel.h"

/* Opt-in finite-difference motion estimator. SteamVR extrapolates the reported
 * pose to photon time using vecVelocity/vecAngularVelocity; the live SLAM
 * channel carries neither, so a stationary read establishes no motion quality
 * and the compositor cannot predict during head motion. When an estimator is
 * supplied, consecutive accepted world-from-head poses of one generation are
 * differenced to fill those two fields in the same tracking frame as
 * vecPosition/qRotation. It adds no smoothing, head model or prediction of its
 * own; a generation change, a stale/invalid read or a gap wider than
 * max_gap_ns resets it to zero velocity. Supplying no estimator preserves the
 * previous zero-velocity behaviour exactly. Physical motion and jitter
 * acceptance remain open; see docs/pico-vr-acceptance.md. */
struct pico_steamvr_velocity_estimator {
    bool has_previous;
    uint64_t generation;
    int64_t timestamp_ns;
    double position[3];
    double orientation[4]; /* x, y, z, w; world-from-head */
    double velocity[3];
    double angular_velocity[3];
    int64_t max_gap_ns; /* consecutive-sample bound; a wider gap resets to zero */
};

/* Channel poses must already use OpenVR's right/up/back world and calibrated
 * tracked-device origin. This adapter adds no world transform, head model or prediction. */
vr::DriverPose_t pico_steamvr_pose(const struct pico_slam_channel *channel,
                                  uint64_t instance, uint64_t generation,
                                  int64_t now_ns, int64_t max_age_ns,
                                  bool device_connected,
                                  struct pico_steamvr_velocity_estimator *velocity = nullptr);

vr::DriverPose_t pico_steamvr_pose_now(const struct pico_slam_channel *channel,
    uint64_t instance, uint64_t generation, int64_t max_age_ns, bool device_connected,
    int64_t (*monotonic_ns)(void *), void *clock_data, enum pico_slam_read_result *result,
    struct pico_steamvr_velocity_estimator *velocity = nullptr);

#endif
