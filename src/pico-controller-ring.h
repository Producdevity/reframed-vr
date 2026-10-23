#ifndef REFRAMED_PICO_CONTROLLER_RING_H
#define REFRAMED_PICO_CONTROLLER_RING_H

#include "pico-controller.h"

#define PICO_CONTROLLER_RING_BYTES 1000

struct pico_controller_ring {
    uint64_t timestamp[2];
};

/* b1977 FastRPC ring: two CPU-synchronized snapshots of ten 100-byte records.
 * Zero-initialize for each new DSP stream. Timestamps order records only; they
 * are not host receipt times. Returns a bit per changed hand, newest first in
 * time per hand, leaving absent outputs unchanged. */
unsigned pico_controller_ring_read(struct pico_controller_ring *ring,
                                   const uint8_t first[PICO_CONTROLLER_RING_BYTES],
                                   const uint8_t second[PICO_CONTROLLER_RING_BYTES],
                                   struct pico_controller_sample samples[2]);

#define PICO_CONTROLLER_RING_MAX_IMU 20

struct pico_controller_motion_ring {
    struct pico_controller_imu_sample latest[2];
};

/* Separate from the newest-only digital reader: retains every new, stable,
 * CRC-valid IMU slot in wire-timestamp order, deduplicated per hand. Initialize
 * once per DSP stream/connection and supply verified MCU/radio/connected state.
 * Returns 0..20 samples, -EINVAL for invalid arguments, or -EPROTO for conflicting
 * measurements with the same hand/timestamp. Refusal preserves state/output;
 * the caller must stop on conflicts. Sequence-byte wrap does not order samples.
 * No clock mapping, missing-sample detection, freshness, conversion or pose.
 * Downstream must enforce age/gaps and reset after reconnect/resume. */
int pico_controller_ring_read_motion(struct pico_controller_motion_ring *ring,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], unsigned mcu_type,
    unsigned radio_type, unsigned connected_mask,
    struct pico_controller_imu_sample samples[PICO_CONTROLLER_RING_MAX_IMU]);

#endif
