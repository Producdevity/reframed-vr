#ifndef REFRAMED_PICO_CONTROLLER_MOTION_PRODUCER_H
#define REFRAMED_PICO_CONTROLLER_MOTION_PRODUCER_H

#include "pico-controller-motion-channel.h"
#include "pico-controller-motion.h"
#include "pico-controller-ring.h"

struct pico_controller_motion_producer {
    struct pico_controller_motion_channel *channel;
    struct pico_controller_motion_ring ring;
    struct ssc_clock clock;
    struct pico_controller_motion_config config[2];
    uint64_t generation;
    int64_t started, now, received[2];
    unsigned mcu_type, radio_type, connected_mask;
    int error;
};

/* Serialized producer for one caller-verified connection/configuration. No
 * hardware or clock-origin discovery. All selected hands must provide their
 * verified stock motion settings. The calibrated clock must use MONOTONIC.
 * Missing startup input after 2 s or later silence over 100 ms stops motion
 * permanently; digital input and shared DSP shutdown remain the owner's job. */
int pico_controller_motion_producer_init(struct pico_controller_motion_producer *producer,
    struct pico_controller_motion_channel *channel, uint64_t instance, uint64_t generation,
    const struct ssc_clock *clock, const struct pico_controller_motion_config config[2],
    unsigned mcu_type, unsigned radio_type, unsigned connected_mask, int64_t now_ns);

/* Returns number of published samples or negative errno. Poll even when the
 * DMA ring is unchanged. Caller supplies two CPU-synchronized snapshots and
 * receipt time after the copy. Failure stops publication; stale generations
 * do not affect the current stream. No head matching or controller poses. */
int pico_controller_motion_producer_update(struct pico_controller_motion_producer *producer,
    uint64_t generation, const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now_ns);
void pico_controller_motion_producer_stop(struct pico_controller_motion_producer *producer);

/* After a receive timeout, 1 means every selected hand has a fresh IMU sample
 * captured strictly after that stop; 0 means not yet. This only inspects the
 * synchronized snapshots: no publication, watermark advance or reactivation.
 * Capture outputs are unchanged on refusal. Other stop reasons cannot recover
 * automatically. The owner still resets/rebinds through an explicit restart. */
int pico_controller_motion_producer_resumed(const struct pico_controller_motion_producer *producer,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now_ns,
    struct ssc_timestamp captures[2]);

/* Explicit owner-controlled restart within the same live DSP connection. The
 * new mapping must be distinct, uninitialized and have no readers yet. The
 * old mapping stays stopped forever. Seed the wire watermark from the current
 * synchronized snapshots without replaying them; only later samples publish.
 * The owner resets the estimator before attaching a new consumer, using its
 * unchanged head/world generation. No RPC, DMA or head state is restarted.
 * Only ordinary stop or receive timeout can recover; malformed input cannot.
 * Refusal leaves the producer and both mappings unchanged. */
int pico_controller_motion_producer_restart(struct pico_controller_motion_producer *producer,
    struct pico_controller_motion_channel *channel, uint64_t generation,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], int64_t now_ns);

#endif
