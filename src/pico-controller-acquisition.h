#ifndef REFRAMED_PICO_CONTROLLER_ACQUISITION_H
#define REFRAMED_PICO_CONTROLLER_ACQUISITION_H

#include "pico-slam-result.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PICO_CONTROLLER_ACQUISITION_PIXELS (640u * 480u)
#define PICO_CONTROLLER_ACQUISITION_MOTION_LIMIT 16384u
#define PICO_CONTROLLER_ACQUISITION_IMAGE_LIMIT 150u

enum pico_controller_acquisition_stop_reason {
    PICO_CONTROLLER_ACQUISITION_RUNNING,
    PICO_CONTROLLER_ACQUISITION_MOTION_FULL,
    PICO_CONTROLLER_ACQUISITION_IMAGES_FULL,
    PICO_CONTROLLER_ACQUISITION_RESET,
    PICO_CONTROLLER_ACQUISITION_DURATION,
    PICO_CONTROLLER_ACQUISITION_SDK_STOP,
    PICO_CONTROLLER_ACQUISITION_FINISHED,
    PICO_CONTROLLER_ACQUISITION_INVALID,
    PICO_CONTROLLER_ACQUISITION_IO
};

struct pico_controller_acquisition_config {
    FILE *motion, *images;
    uint64_t generation;
    unsigned motion_capacity, image_capacity;
};

struct pico_controller_acquisition_frame {
    int64_t sof_ns;
    uint64_t number;
    unsigned exposure, gain;
    const uint8_t *pixels;
};

struct pico_controller_acquisition_status {
    uint64_t generation, dispatch_order, motion_records[2], image_sets;
    enum pico_controller_acquisition_stop_reason reason;
    int error;
    bool stopped;
};

struct pico_controller_acquisition;

/* Serialized SDK-call prefix, version 3, little-endian. Streams are distinct,
 * newly opened, borrowed files; finish before inspecting status and closing.
 * Capacity, reset and failure stop both streams. No SDK or sensor is invoked. */
int pico_controller_acquisition_create(const struct pico_controller_acquisition_config *config,
                                      struct pico_controller_acquisition **recorder);
int pico_controller_acquisition_motion(struct pico_controller_acquisition *recorder,
    uint64_t generation, unsigned hand, int64_t timestamp_ns, const double values[9],
    const uint8_t before[PICO_SLAM_RESULT_SIZE], const uint8_t after[PICO_SLAM_RESULT_SIZE]);
int pico_controller_acquisition_images(struct pico_controller_acquisition *recorder,
    uint64_t generation, int64_t timestamp_ns,
    const struct pico_controller_acquisition_frame frames[4],
    const uint8_t before[PICO_SLAM_RESULT_SIZE], const uint8_t after[PICO_SLAM_RESULT_SIZE]);
void pico_controller_acquisition_stop(struct pico_controller_acquisition *recorder,
                                     enum pico_controller_acquisition_stop_reason reason);
int pico_controller_acquisition_finish(struct pico_controller_acquisition *recorder);
void pico_controller_acquisition_status(const struct pico_controller_acquisition *recorder,
                                       struct pico_controller_acquisition_status *status);
void pico_controller_acquisition_destroy(struct pico_controller_acquisition *recorder);

#ifdef __cplusplus
}
#endif

#endif
