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

#endif
