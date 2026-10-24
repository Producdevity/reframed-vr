#ifndef REFRAMED_PICO_CONTROLLER_RESULT_H
#define REFRAMED_PICO_CONTROLLER_RESULT_H
#include "pico-slam-pose.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_controller_result {
    int64_t timestamp_ns;
    struct pico_slam_pose pose;
    uint32_t error;
    uint8_t state, confidence, diagnostic_52, diagnostic_54;
};

/* b1977 controller positions are millimetres; pose uses metres in the raw
 * tracker frame. Public confidence can be synthesized by the vendor getter.
 * Decoding neither establishes optical validity nor applies grip/aim offsets. */
bool pico_controller_result_decode(const void *bytes, size_t size,
                                   struct pico_controller_result *result);
#ifdef __cplusplus
}
#endif
#endif
