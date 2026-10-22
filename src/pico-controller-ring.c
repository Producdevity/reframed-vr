#include "pico-controller-ring.h"

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
