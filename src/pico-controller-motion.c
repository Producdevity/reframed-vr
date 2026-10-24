#include "pico-controller-motion.h"

#include <limits.h>
#include <string.h>

bool pico_controller_motion_values(const struct pico_controller_imu_sample *sample,
                                   const struct pico_controller_motion_config *config,
                                   double values[9])
{
    if (!sample || !config || !values || sample->hand < 1 || sample->hand > 2 ||
        config->mcu_type < 1 || config->mcu_type > 2)
        return false;
    float converted[6];
    for (unsigned i = 0; i < 6; ++i) {
        converted[i] = i < 3 ? sample->gyroscope[i] * 0.001065264455974102f
                             : sample->acceleration[i - 3] * 0.004790039267390966f;
        if (config->double_scale == 1) converted[i] += converted[i];
    }
    if (!config->axis_reversal_bypass) {
        for (unsigned i = 0; i < 6; i += 3) {
            float x = converted[i], y = converted[i + 1], z = converted[i + 2];
            if (config->mcu_type == 1 && config->revision == '0') {
                if (sample->hand == 2) {
                    converted[i] = -x;
                    converted[i + 1] = -y;
                }
            } else {
                converted[i] = sample->hand == 1 ? -y : y;
                converted[i + 1] = sample->hand == 1 ? -x : x;
                converted[i + 2] = -z;
            }
        }
    }
    double result[9];
    for (unsigned i = 0; i < 6; ++i) result[i] = converted[i];
    result[6] = (float)((double)sample->temperature / 132.48 + 25.0);
    result[7] = sample->flags & 1;
    result[8] = sample->flags >> 1;
    memcpy(values, result, sizeof(result));
    return true;
}

bool pico_controller_motion_time(const struct ssc_clock *clock, uint64_t timestamp_us,
                                 int64_t now_ns, int64_t max_age_ns,
                                 struct ssc_timestamp *timestamp)
{
    if (!clock || !timestamp || !timestamp_us || !clock->initialized ||
        !clock->counter_hz || clock->host_ns < 0 || clock->uncertainty_ns < 2 ||
        clock->uncertainty_ns > INT64_MAX - 1000 || now_ns < 0 || max_age_ns < 0)
        return false;
    int64_t uncertainty = clock->uncertainty_ns + 1000;
    __int128 counter_ns = (__int128)clock->counter_ticks * 1000000000 / clock->counter_hz;
    __int128 mapped = clock->host_ns + (__int128)timestamp_us * 1000 - counter_ns;
    if (mapped - uncertainty < 0 || mapped + uncertainty > now_ns ||
        (__int128)now_ns - (mapped - uncertainty) > max_age_ns)
        return false;
    *timestamp = (struct ssc_timestamp){(int64_t)mapped, uncertainty};
    return true;
}
