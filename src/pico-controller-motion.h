#ifndef REFRAMED_PICO_CONTROLLER_MOTION_H
#define REFRAMED_PICO_CONTROLLER_MOTION_H

#include "pico-controller.h"
#include "ssc-clock.h"

struct pico_controller_motion_config {
    unsigned mcu_type;
    uint8_t revision, double_scale, axis_reversal_bypass;
};

/* b1977's nine tracker inputs: gyro rad/s, acceleration m/s², temperature °C,
 * flag bit 0 and remaining flag bits. Reproduces stock float32 intermediates;
 * factory calibration and head/controller extrinsics belong to the tracker.
 * Configuration must come from the selected hand's verified stock status.
 * No clock, connection lifetime or pose is inferred. Failure preserves output. */
bool pico_controller_motion_values(const struct pico_controller_imu_sample *sample,
                                   const struct pico_controller_motion_config *config,
                                   double values[9]);

/* Use only after verifying the controller's microsecond timestamps share the
 * calibrated CPU-counter origin. Recalibrate after resume/reset/reconnect.
 * Adds 1 us of quantization uncertainty; rejects future, old and overflowing
 * intervals. The caller owns per-hand ordering and connection validity. */
bool pico_controller_motion_time(const struct ssc_clock *clock, uint64_t timestamp_us,
                                 int64_t now_ns, int64_t max_age_ns,
                                 struct ssc_timestamp *timestamp);

#endif
