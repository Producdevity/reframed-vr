#include "pico-slam-result.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void integer(uint8_t *p, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(value >> (8 * i));
}

static void number(uint8_t *p, double value)
{
    uint64_t bits;
    memcpy(&bits, &value, 8);
    integer(p, bits);
}

int main(void)
{
    uint8_t storage[PICO_SLAM_RESULT_SIZE + 2] = {0}, *p = storage + 1;
    struct pico_slam_result result, previous;
    memset(&result, 0xa5, sizeof(result));
    memcpy(&previous, &result, sizeof(result));
    assert(!pico_slam_result_decode(NULL, PICO_SLAM_RESULT_SIZE, &result));
    assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, NULL));
    for (size_t i = 0; i < PICO_SLAM_RESULT_SIZE; ++i)
        assert(!pico_slam_result_decode(p, i, &result));
    assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE + 1, &result));
    assert(!memcmp(&result, &previous, sizeof(result)));

    integer(p, UINT64_C(1234567890123));
    number(p + 8, 1); number(p + 16, -2); number(p + 24, 3);
    number(p + 32, 0.5); number(p + 40, -0.5); number(p + 48, 0.5); number(p + 56, -0.5);
    p[0x40] = 1; p[0x41] = 0; p[0x44] = 4;
    assert(pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
    assert(result.timestamp_ns == INT64_C(1234567890123));
    assert(result.position[0] == 1 && result.position[1] == -2 && result.position[2] == 3);
    assert(result.orientation[0] == -0.5 && result.orientation[1] == 0.5 &&
           result.orientation[2] == -0.5 && result.orientation[3] == 0.5);
    assert(result.state == 1 && result.confidence == 0 && result.error == 4);
    p[0x40] = 255; p[0x41] = 255;
    p[0x44] = 0x12; p[0x45] = 0x34; p[0x46] = 0x56; p[0x47] = 0x78;
    assert(pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
    assert(result.state == 255 && result.confidence == 255 && result.error == UINT32_C(0x78563412));
    memcpy(&previous, &result, sizeof(result));
    for (unsigned i = 0; i < 7; ++i) for (unsigned v = 0; v < 3; ++v) {
        uint8_t saved[8]; memcpy(saved, p + 8 + 8 * i, 8);
        number(p + 8 + 8 * i, (const double[]){NAN, INFINITY, -INFINITY}[v]);
        assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
        assert(!memcmp(&result, &previous, sizeof(result)));
        memcpy(p + 8 + 8 * i, saved, 8);
    }
    for (unsigned i = 0; i < 3; ++i) {
        integer(p, (const uint64_t[]){0, UINT64_C(0x8000000000000000), UINT64_MAX}[i]);
        assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
    }
    integer(p, UINT64_C(1234567890123));
    for (unsigned i = 0; i < 4; ++i) number(p + 32 + 8 * i, 0);
    assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
    number(p + 32, 1.01);
    assert(!pico_slam_result_decode(p, PICO_SLAM_RESULT_SIZE, &result));
    assert(!memcmp(&result, &previous, sizeof(result)));
    puts("PICO_SLAM_RESULT_PASS");
    return 0;
}
