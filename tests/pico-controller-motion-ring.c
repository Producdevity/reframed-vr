#include "pico-controller-ring.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static void checksum(uint8_t *record)
{
    uint8_t crc = 0;
    for (unsigned i = 0; i < 99; ++i) {
        crc ^= record[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0x8c : 0);
    }
    record[99] = crc;
}

static void record(uint8_t *out, unsigned hand, uint64_t first, uint64_t second)
{
    memset(out, 0, 100);
    out[0] = 0xa5; out[1] = 1; out[7] = hand == 1 ? 0x40 : 0;
    for (unsigned slot = 0; slot < 2; ++slot) {
        uint64_t timestamp = slot ? second : first;
        uint8_t *sample = out + 10 + 23 * slot;
        for (unsigned i = 0; i < 8; ++i) sample[14 + i] = timestamp >> (8 * i);
        sample[22] = (uint8_t)timestamp;
        sample[0] = 0x80; sample[1] = 0xff;
        sample[6] = 0xff; sample[7] = 0x7f;
    }
    checksum(out);
}

int main(void)
{
    struct pico_controller_motion_ring ring = {0};
    struct pico_controller_imu_sample out[20];
    uint8_t a[1000] = {0}, b[1000] = {0};
    memset(out, 0x5a, sizeof(out));
    struct pico_controller_imu_sample saved[20]; memcpy(saved, out, sizeof(out));
    assert(!pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out));
    assert(!memcmp(saved, out, sizeof(out)));

    for (unsigned slot = 0; slot < 10; ++slot)
        record(a + 100 * slot, 1, 20 - 2 * slot, 19 - 2 * slot);
    memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == 20);
    for (unsigned i = 0; i < 20; ++i) {
        assert(out[i].hand == 1 && out[i].timestamp_us == i + 1);
        assert(out[i].gyroscope[0] == -128 && out[i].acceleration[0] == 32767);
    }
    memcpy(saved, out, sizeof(out));
    assert(!pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out));
    assert(!memcmp(saved, out, sizeof(out)));

    record(a + 900, 2, 22, 21); record(a, 1, 22, 21);
    memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == 4);
    assert(out[0].hand == 1 && out[0].timestamp_us == 21);
    assert(out[1].hand == 2 && out[1].timestamp_us == 21);
    assert(out[2].hand == 1 && out[2].timestamp_us == 22);
    assert(out[3].hand == 2 && out[3].timestamp_us == 22);

    record(a + 100, 1, 23, 24); memcpy(a + 200, a + 100, 100);
    memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == 2);
    assert(out[0].timestamp_us == 23 && out[1].timestamp_us == 24);
    record(a + 100, 1, 25, 26); memcpy(b, a, sizeof(a));
    b[100] ^= 1;
    assert(!pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out));
    memcpy(b, a, sizeof(a)); a[199] ^= 1; b[199] ^= 1;
    assert(!pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out));
    checksum(a + 100); memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == 2);

    memset(a, 0, sizeof(a));
    record(a, 1, 255, 256); memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == 2);
    assert(out[0].sequence == 255 && out[1].sequence == 0);
    record(a, 1, 1000, 2000); memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 2, out) == 0);
    assert(ring.latest[0].timestamp_us == 256);

    record(a, 1, 300, 301); record(a + 100, 1, 300, 302);
    a[110] ^= 1; checksum(a + 100); memcpy(b, a, sizeof(a));
    struct pico_controller_motion_ring before = ring;
    memcpy(saved, out, sizeof(out));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == -EPROTO);
    assert(!memcmp(&before, &ring, sizeof(ring)) && !memcmp(saved, out, sizeof(out)));
    memset(a + 100, 0, 100); record(a, 1, 256, 257);
    a[10] ^= 1; checksum(a); memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 1, 3, out) == -EPROTO);
    assert(!memcmp(&before, &ring, sizeof(ring)) && !memcmp(saved, out, sizeof(out)));

    memset(&ring, 0, sizeof(ring)); record(a, 1, 10, 11); memcpy(b, a, sizeof(a));
    assert(pico_controller_ring_read_motion(&ring, a, b, 2, 2, 3, out) == 2);
    assert(out[0].hand == 2 && out[0].timestamp_us == 10);
    assert(out[1].hand == 1 && out[1].timestamp_us == 11);
    memset(&ring, 0, sizeof(ring));
    assert(pico_controller_ring_read_motion(&ring, a, b, 2, 2, 1, out) == 1);
    assert(out[0].hand == 1 && out[0].timestamp_us == 11);
    before = ring; memcpy(saved, out, sizeof(out));
    assert(pico_controller_ring_read_motion(NULL, a, b, 1, 2, 1, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, NULL, b, 1, 2, 1, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, NULL, 1, 2, 1, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 2, 1, NULL) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, b, 0, 2, 1, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 3, 1, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 2, 0, out) == -EINVAL);
    assert(pico_controller_ring_read_motion(&ring, a, b, 1, 2, 4, out) == -EINVAL);
    assert(!memcmp(&before, &ring, sizeof(ring)) && !memcmp(saved, out, sizeof(out)));
    puts("PICO_CONTROLLER_MOTION_RING_PASS");
}
