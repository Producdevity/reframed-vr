#include "pico-slam-result.h"
#include <float.h>
#include <limits.h>
#include <math.h>
#include <string.h>

_Static_assert(sizeof(double) == 8 && DBL_MANT_DIG == 53 && DBL_MAX_EXP == 1024,
               "Vendor result requires IEEE binary64");

static uint64_t le64(const uint8_t *p)
{
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= (uint64_t)p[i] << (8 * i);
    return value;
}

static double number(const uint8_t *p)
{
    uint64_t bits = le64(p);
    double value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

bool pico_slam_result_decode(const void *bytes, size_t size, struct pico_slam_result *result)
{
    if (!bytes || !result || size != PICO_SLAM_RESULT_SIZE) return false;
    const uint8_t *p = bytes;
    uint64_t timestamp = le64(p);
    if (!timestamp || timestamp > INT64_MAX) return false;
    struct pico_slam_result value = {.timestamp_ns = (int64_t)timestamp,
        .state = p[0x40], .confidence = p[0x41]};
    for (unsigned i = 0; i < 4; ++i) value.error |= (uint32_t)p[0x44 + i] << (8 * i);
    for (unsigned i = 0; i < 3; ++i) {
        value.position[i] = number(p + 8 + 8 * i);
        if (!isfinite(value.position[i])) return false;
        value.orientation[i] = number(p + 0x28 + 8 * i);
    }
    value.orientation[3] = number(p + 0x20);
    double norm = 0;
    for (unsigned i = 0; i < 4; ++i) {
        double q = value.orientation[i];
        if (!isfinite(q) || fabs(q) > 1.0001) return false;
        norm += q * q;
    }
    if (fabs(norm - 1) > 0.0001) return false;
    *result = value;
    return true;
}
