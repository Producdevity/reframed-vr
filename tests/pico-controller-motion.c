#include "pico-controller-motion.h"

#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    struct pico_controller_imu_sample s = {
        .hand = 1, .gyroscope = {0, 1, -1}, .acceleration = {0, 1, -1},
        .temperature = 13248, .flags = 255,
    };
    struct pico_controller_motion_config config = {.mcu_type = 1, .revision = '5'};
    double out[9];
    assert(pico_controller_motion_values(&s, &config, out));
    assert(out[0] == -(double)0.001065264455974102f && signbit(out[1]));
    assert(out[2] == (double)0.001065264455974102f);
    assert(out[3] == -(double)0.004790039267390966f && signbit(out[4]));
    assert(out[5] == (double)0.004790039267390966f);
    assert(out[6] == 125 && out[7] == 1 && out[8] == 127);
    config.axis_reversal_bypass = 255;
    config.double_scale = 1;
    s.temperature = -13248;
    assert(pico_controller_motion_values(&s, &config, out));
    assert(!signbit(out[0]) && out[1] == (double)(2 * 0.001065264455974102f));
    assert(out[6] == -75);
    config.double_scale = 255;
    s.temperature = 0;
    assert(pico_controller_motion_values(&s, &config, out));
    assert(out[1] == (double)0.001065264455974102f && out[6] == 25);
    double before[9]; memcpy(before, out, sizeof(out));
    s.hand = 0;
    assert(!pico_controller_motion_values(&s, &config, out));
    assert(!memcmp(before, out, sizeof(out)));
    s.hand = 1; config.mcu_type = 0;
    assert(!pico_controller_motion_values(&s, &config, out));
    assert(!pico_controller_motion_values(NULL, &config, out));
    assert(!pico_controller_motion_values(&s, NULL, out));
    assert(!pico_controller_motion_values(&s, &config, NULL));

    struct ssc_clock clock;
    assert(ssc_clock_init(&clock, 19200000, 19200000, 100, 102, 2));
    struct ssc_timestamp t;
    assert(pico_controller_motion_time(&clock, 1000001, 2104, 2006, &t));
    assert(t.timestamp_ns == 1101 && t.uncertainty_ns == 1003);
    struct ssc_timestamp saved = t;
    assert(!pico_controller_motion_time(&clock, 1000001, 2103, 2006, &t));
    assert(!pico_controller_motion_time(&clock, 1000001, 2104, 2005, &t));
    assert(!pico_controller_motion_time(&clock, 1000000, 2104, 10000, &t));
    assert(!pico_controller_motion_time(&clock, UINT64_MAX, INT64_MAX, INT64_MAX, &t));
    assert(!pico_controller_motion_time(&clock, 0, 2104, 10000, &t));
    assert(!memcmp(&t, &saved, sizeof(t)));
    clock.uncertainty_ns = INT64_MAX;
    assert(!pico_controller_motion_time(&clock, 1, 2104, 10000, &t));
    clock.uncertainty_ns = 3; clock.initialized = false;
    assert(!pico_controller_motion_time(&clock, 1, 2104, 10000, &t));
    assert(!pico_controller_motion_time(NULL, 1, 2104, 10000, &t));
    assert(!pico_controller_motion_time(&clock, 1, 2104, 10000, NULL));
    puts("PICO_CONTROLLER_MOTION_PASS");
    return 0;
}
