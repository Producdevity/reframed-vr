#include "pico-controller-result.h"
#include <string.h>

bool pico_controller_result_decode(const void *bytes, size_t size,
                                   struct pico_controller_result *result)
{
    if (!result) return false;
    struct pico_slam_result raw;
    if (!pico_slam_result_decode(bytes, size, &raw)) return false;
    const uint8_t *data = bytes;
    struct pico_controller_result value = {.timestamp_ns = raw.timestamp_ns,
        .error = raw.error, .state = raw.state, .confidence = raw.confidence,
        .diagnostic_52 = data[0x52], .diagnostic_54 = data[0x54]};
    memcpy(value.pose.orientation, raw.orientation, sizeof(value.pose.orientation));
    for (unsigned i = 0; i < 3; ++i) value.pose.position[i] = raw.position[i] * .001;
    *result = value;
    return true;
}
