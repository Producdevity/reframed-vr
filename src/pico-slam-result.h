#ifndef REFRAMED_PICO_SLAM_RESULT_H
#define REFRAMED_PICO_SLAM_RESULT_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PICO_SLAM_RESULT_SIZE 0x170

struct pico_slam_result {
    int64_t timestamp_ns;
    double position[3];
    double orientation[4]; /* x, y, z, w */
    uint8_t state, confidence;
    uint32_t error;
};

/* b1977 getAlgorithmResult wire layout, in the vendor SLAM coordinate frame.
 * No prediction, head offset, world conversion or tracking validity is inferred.
 * Status bytes and the error field remain opaque. Failure preserves output. */
bool pico_slam_result_decode(const void *bytes, size_t size, struct pico_slam_result *result);
#ifdef __cplusplus
}
#endif
#endif
