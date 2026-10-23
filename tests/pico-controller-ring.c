#include "pico-controller-ring.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void record(uint8_t *out, unsigned hand, uint64_t timestamp, uint8_t buttons)
{
    memset(out, 0, 100);
    out[0] = 0xa5; out[1] = 1;
    out[7] = (hand == 1 ? 0x40 : 0) | buttons;
    for (unsigned i = 0; i < 8; ++i) out[56 + i] = timestamp >> (8 * i);
    uint8_t crc = 0;
    for (unsigned i = 0; i < 99; ++i) {
        crc ^= out[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0x8c : 0);
    }
    out[99] = crc;
}

int main(void)
{
    struct pico_controller_ring ring = {0};
    struct pico_controller_sample samples[2] = {{0}};
    uint8_t first[1000] = {0}, second[1000] = {0};
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    record(first, 1, 0, 16); memcpy(second, first, sizeof(first));
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    for (unsigned slot = 0; slot < 10; ++slot) record(first + 100 * slot, 1, 10 - slot, slot);
    memcpy(second, first, sizeof(first));
    assert(pico_controller_ring_read(&ring, first, second, samples) == 1);
    assert(ring.timestamp[0] == 10 && samples[0].buttons == 0 && !samples[1].hand);
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    record(first + 900, 1, 11, 4);
    record(first + 800, 2, 1, 8);
    memcpy(second, first, sizeof(first));
    assert(pico_controller_ring_read(&ring, first, second, samples) == 3);
    assert(samples[0].buttons == 4 && samples[1].buttons == 8);
    record(first + 900, 1, 11, 16); memcpy(second, first, sizeof(first));
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    assert(samples[0].buttons == 4);
    struct pico_controller_sample saved[2]; memcpy(saved, samples, sizeof(saved));
    record(first + 900, 1, 12, 16);
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    first[999] ^= 1; memcpy(second, first, sizeof(first));
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    record(first + 900, 1, 0, 16); memcpy(second, first, sizeof(first));
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    record(first + 900, 1, 1, 16); memcpy(second, first, sizeof(first));
    assert(!pico_controller_ring_read(&ring, first, second, samples));
    assert(!memcmp(saved, samples, sizeof(saved)));
    record(first + 900, 1, 12, 16); memcpy(second, first, sizeof(first));
    assert(pico_controller_ring_read(&ring, first, second, samples) == 1);
    assert(samples[0].buttons == 16 && samples[1].buttons == 8);
    assert(!pico_controller_ring_read(NULL, first, second, samples));
    puts("PICO_CONTROLLER_RING_PASS");
}
