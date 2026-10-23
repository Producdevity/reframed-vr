#include "pico-controller-ring.h"

#include <errno.h>
#include <string.h>

unsigned pico_controller_ring_read(struct pico_controller_ring *ring,
                                   const uint8_t first[PICO_CONTROLLER_RING_BYTES],
                                   const uint8_t second[PICO_CONTROLLER_RING_BYTES],
                                   struct pico_controller_sample samples[2])
{
    if (!ring || !first || !second || !samples) return 0;
    unsigned changed = 0;
    for (unsigned slot = 0; slot < 10; ++slot) {
        const uint8_t *record = first + 100 * slot;
        struct pico_controller_sample sample;
        if (memcmp(record, second + 100 * slot, 100) ||
            !pico_controller_decode(record, 100, 1, 2, true, &sample)) continue;
        uint64_t timestamp = 0;
        for (unsigned i = 0; i < 8; ++i) timestamp |= (uint64_t)record[56 + i] << (8 * i);
        unsigned hand = sample.hand - 1;
        if (timestamp <= ring->timestamp[hand]) continue;
        ring->timestamp[hand] = timestamp;
        samples[hand] = sample;
        changed |= 1U << hand;
    }
    return changed;
}

static bool same_motion(const struct pico_controller_imu_sample *a,
                        const struct pico_controller_imu_sample *b)
{
    return a->hand == b->hand && a->timestamp_us == b->timestamp_us &&
        a->sequence == b->sequence && a->flags == b->flags &&
        a->temperature == b->temperature &&
        !memcmp(a->gyroscope, b->gyroscope, sizeof(a->gyroscope)) &&
        !memcmp(a->acceleration, b->acceleration, sizeof(a->acceleration));
}

int pico_controller_ring_read_motion(struct pico_controller_motion_ring *ring,
    const uint8_t first[PICO_CONTROLLER_RING_BYTES],
    const uint8_t second[PICO_CONTROLLER_RING_BYTES], unsigned mcu_type,
    unsigned radio_type, unsigned connected_mask,
    struct pico_controller_imu_sample samples[PICO_CONTROLLER_RING_MAX_IMU])
{
    if (!ring || !first || !second || !samples || mcu_type < 1 || mcu_type > 2 ||
        radio_type < 1 || radio_type > 2 || !connected_mask || connected_mask > 3)
        return -EINVAL;
    struct pico_controller_imu_sample pending[PICO_CONTROLLER_RING_MAX_IMU];
    unsigned count = 0;
    for (unsigned slot = 0; slot < 10; ++slot) {
        const uint8_t *record = first + 100 * slot;
        struct pico_controller_imu_batch batch;
        if (memcmp(record, second + 100 * slot, 100) ||
            !pico_controller_decode_imu(record, 100, mcu_type, radio_type,
                                        connected_mask, &batch)) continue;
        for (unsigned i = 0; i < batch.count; ++i) {
            const struct pico_controller_imu_sample *sample = &batch.samples[i];
            unsigned hand = sample->hand - 1;
            if (!(connected_mask & (1U << hand))) continue;
            const struct pico_controller_imu_sample *previous = &ring->latest[hand];
            if (sample->timestamp_us < previous->timestamp_us) continue;
            if (sample->timestamp_us == previous->timestamp_us) {
                if (!same_motion(sample, previous)) return -EPROTO;
                continue;
            }
            pending[count++] = *sample;
        }
    }
    for (unsigned i = 1; i < count; ++i) {
        struct pico_controller_imu_sample sample = pending[i];
        unsigned j = i;
        while (j && (pending[j - 1].timestamp_us > sample.timestamp_us ||
               (pending[j - 1].timestamp_us == sample.timestamp_us &&
                pending[j - 1].hand > sample.hand))) {
            pending[j] = pending[j - 1];
            --j;
        }
        pending[j] = sample;
    }
    struct pico_controller_motion_ring next = *ring;
    unsigned used = 0;
    for (unsigned i = 0; i < count; ++i) {
        const struct pico_controller_imu_sample *sample = &pending[i];
        struct pico_controller_imu_sample *previous = &next.latest[sample->hand - 1];
        if (sample->timestamp_us == previous->timestamp_us) {
            if (!same_motion(sample, previous)) return -EPROTO;
            continue;
        }
        *previous = *sample;
        pending[used++] = *sample;
    }
    memcpy(samples, pending, used * sizeof(*samples));
    *ring = next;
    return (int)used;
}
