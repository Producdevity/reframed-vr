#include "pico-station-protocol.h"
#include <string.h>

static uint8_t checksum(const uint8_t *bytes, size_t size)
{
    unsigned result = 0;
    for (size_t i = 0; i < size; ++i) {
        result ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            result = (result >> 1) ^ ((result & 1) ? 0x8c : 0);
    }
    return (uint8_t)result;
}

static bool encode(uint8_t command, const uint8_t *payload, size_t count, uint8_t *output)
{
    if (!output || count > 36 || (count && !payload)) return false;
    uint8_t frame[PICO_STATION_FRAME_SIZE] = {0xaa, 1, command};
    if (count) memcpy(frame + 3, payload, count);
    frame[39] = checksum(frame, 39);
    memcpy(output, frame, sizeof(frame));
    return true;
}

bool pico_station_camera_initialize(unsigned camera, bool raw8, uint8_t *output)
{
    return pico_station_camera_initialize_metadata(camera, raw8, PICO_STATION_CAMERA_METADATA_NONE, output);
}

bool pico_station_camera_initialize_metadata(unsigned camera, bool raw8,
                                              enum pico_station_camera_metadata metadata,
                                              uint8_t *output)
{
    if (camera > 4 || (unsigned)metadata > PICO_STATION_CAMERA_METADATA_EXPOSURE_AND_TYPE) return false;
    const uint8_t data[] = {1, (uint8_t)camera, (uint8_t)metadata, raw8 ? 1 : 0};
    return encode(4, data, sizeof(data), output);
}

bool pico_station_camera_stream(unsigned camera, bool enabled, uint8_t *output)
{
    if (camera > 4) return false;
    const uint8_t data[] = {2, (uint8_t)camera, enabled ? 1 : 2};
    return encode(4, data, sizeof(data), output);
}

bool pico_station_camera_pacing(unsigned mode, uint8_t *output)
{
    if (mode < 1 || mode > 2) return false;
    const uint8_t value = (uint8_t)mode;
    return encode(0x19, &value, 1, output);
}

bool pico_station_camera_status(bool failure_counters, uint8_t *output)
{
    const uint8_t value = failure_counters ? 6 : 15;
    return encode(4, &value, 1, output);
}

bool pico_station_camera_read_register(unsigned slave, unsigned address, uint8_t *output)
{
    if (slave < 0xe0 || slave > 0xe8 || slave % 2 || address > UINT16_MAX) return false;
    const uint8_t data[] = {14, (uint8_t)slave, (uint8_t)(address >> 8), (uint8_t)address};
    return encode(4, data, sizeof(data), output);
}

bool pico_station_version(uint8_t *output)
{
    return encode(1, NULL, 0, output);
}

bool pico_station_acknowledge(uint16_t sequence, uint8_t *output)
{
    const uint8_t data[] = {(uint8_t)sequence, (uint8_t)(sequence >> 8)};
    return encode(0xfa, data, sizeof(data), output);
}

bool pico_station_response_valid(const void *data, size_t size)
{
    if (!data || size != PICO_STATION_FRAME_SIZE) return false;
    const uint8_t *frame = data;
    if (frame[0] != 0xa5 && frame[0] != 0xbb) return false;
    return checksum(frame, 39) == frame[39];
}
