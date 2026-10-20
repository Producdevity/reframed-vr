#ifndef REFRAMED_PICO_STEAMVR_POSE_H
#define REFRAMED_PICO_STEAMVR_POSE_H

#include <openvr_driver.h>
#include "pico-slam-channel.h"

/* Channel poses must already use OpenVR's right/up/back world and calibrated
 * head origin. This adapter adds no world transform, head model or prediction. */
vr::DriverPose_t pico_steamvr_pose(const struct pico_slam_channel *channel,
                                  uint64_t instance, uint64_t generation,
                                  int64_t now_ns, int64_t max_age_ns,
                                  bool device_connected);

#endif
