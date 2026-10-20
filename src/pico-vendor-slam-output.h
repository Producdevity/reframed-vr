#ifndef REFRAMED_PICO_VENDOR_SLAM_OUTPUT_H
#define REFRAMED_PICO_VENDOR_SLAM_OUTPUT_H

#include "pico-slam-channel.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_vendor_slam_output_config {
    struct pico_slam_channel *channel;
    uint64_t generation;
    struct pico_slam_pose_config pose;
    int64_t uncertainty_ns;
    void *handle, *clock_data;
    int (*get_result)(void *handle, void *result);
    int64_t (*monotonic_ns)(void *clock_data);
};

struct pico_vendor_slam_output_status {
    uint64_t callbacks, waiting, published;
    bool stopped, failed;
};

struct pico_vendor_slam_output;

/* Borrows an initialized channel and the vendor handle. Serializes callbacks,
 * including getAlgorithmResult, before publishing. The caller supplies verified
 * head/world transforms and current output-clock uncertainty. No defaults or
 * hardware access. One output owner per channel generation. */
int pico_vendor_slam_output_create(const struct pico_vendor_slam_output_config *config,
                                   struct pico_vendor_slam_output **output);
enum pico_slam_channel_result pico_vendor_slam_output_callback(struct pico_vendor_slam_output *output);
void pico_vendor_slam_output_status(struct pico_vendor_slam_output *output,
                                    struct pico_vendor_slam_output_status *status);
/* Stop waits for an in-flight result call and invalidates the channel. After it
 * returns, late callbacks cannot call the vendor handle. Stop before destroying
 * that handle; join/unregister its callbacks before releasing the output owner. */
void pico_vendor_slam_output_stop(struct pico_vendor_slam_output *output);
int pico_vendor_slam_output_release(struct pico_vendor_slam_output **output);

#ifdef __cplusplus
}
#endif
#endif
