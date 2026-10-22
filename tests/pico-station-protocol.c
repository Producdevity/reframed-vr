#include "pico-station-protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t frame[40];
static void golden(const char *hex)
{
    for (unsigned i = 0; i < 40; ++i) {
        unsigned byte;
        assert(sscanf(hex + i * 2, "%2x", &byte) == 1 && frame[i] == byte);
    }
}

int main(void)
{
    assert(pico_station_version(frame));
    golden("aa010100000000000000000000000000000000000000000000000000000000000000000000000044");
    assert(pico_station_controller_imu(1, true, frame));
    golden("aa01070101000000000000000000000000000000000000000000000000000000000000000000006a");
    assert(pico_station_controller_imu(1, false, frame));
    golden("aa01070100000000000000000000000000000000000000000000000000000000000000000000008a");
    assert(pico_station_controller_imu(2, true, frame));
    golden("aa010702010000000000000000000000000000000000000000000000000000000000000000000048");
    assert(pico_station_controller_imu(2, false, frame));
    golden("aa0107020000000000000000000000000000000000000000000000000000000000000000000000a8");
    assert(pico_station_camera_initialize(3, true, frame));
    golden("aa0104010300010000000000000000000000000000000000000000000000000000000000000000b7");
    assert(pico_station_camera_initialize_metadata(0, true, PICO_STATION_CAMERA_METADATA_EXPOSURE, frame));
    golden("aa0104010001010000000000000000000000000000000000000000000000000000000000000000bf");
    assert(pico_station_camera_initialize_metadata(0, true, PICO_STATION_CAMERA_METADATA_EXPOSURE_AND_TYPE, frame));
    golden("aa0104010002010000000000000000000000000000000000000000000000000000000000000000ec");
    assert(pico_station_camera_stream(3, false, frame));
    golden("aa01040203020000000000000000000000000000000000000000000000000000000000000000006c");
    assert(pico_station_camera_pacing(1, frame));
    golden("aa011901000000000000000000000000000000000000000000000000000000000000000000000031");
    assert(pico_station_camera_status(false, frame));
    golden("aa01040f000000000000000000000000000000000000000000000000000000000000000000000056");
    assert(pico_station_camera_read_register(0xe6, 0x300a, frame));
    golden("aa01040ee6300a0000000000000000000000000000000000000000000000000000000000000000e8");

    uint8_t original[40]; memset(frame, 0x5a, sizeof(frame)); memcpy(original, frame, sizeof(frame));
#define BAD(call) do { assert(!(call)); assert(!memcmp(frame, original, sizeof(frame))); } while (0)
    BAD(pico_station_controller_imu(0, true, frame));
    BAD(pico_station_controller_imu(3, false, frame));
    BAD(pico_station_controller_imu((unsigned)-1, true, frame));
    BAD(pico_station_camera_initialize(5, false, frame));
    BAD(pico_station_camera_initialize((unsigned)-1, true, frame));
    BAD(pico_station_camera_initialize_metadata(5, true, PICO_STATION_CAMERA_METADATA_EXPOSURE, frame));
    BAD(pico_station_camera_initialize_metadata(0, true, (enum pico_station_camera_metadata)3, frame));
    BAD(pico_station_camera_initialize_metadata(0, true, (enum pico_station_camera_metadata)-1, frame));
    BAD(pico_station_camera_stream(5, true, frame));
    BAD(pico_station_camera_pacing(0, frame));
    BAD(pico_station_camera_pacing(3, frame));
    BAD(pico_station_camera_read_register(0xdf, 0, frame));
    BAD(pico_station_camera_read_register(0xe1, 0, frame));
    BAD(pico_station_camera_read_register(0xea, 0, frame));
    BAD(pico_station_camera_read_register(0xe6, 0x10000, frame));
    assert(!pico_station_camera_initialize(0, false, NULL));
    assert(!pico_station_camera_initialize_metadata(0, true, PICO_STATION_CAMERA_METADATA_EXPOSURE, NULL));
    assert(!pico_station_camera_stream(0, false, NULL));
    assert(!pico_station_camera_pacing(1, NULL));
    assert(!pico_station_camera_status(false, NULL));
    assert(!pico_station_camera_read_register(0xe6, 0x300a, NULL));
    assert(!pico_station_version(NULL));
    assert(!pico_station_controller_imu(1, true, NULL));
    assert(!pico_station_acknowledge(0, NULL));

    const char *reply = "bb01040f0102030000000000000000000000000000000000000000000000000000000000000000dd";
    uint8_t storage[42] = {0}; uint8_t *unaligned = storage + 1;
    for (unsigned i = 0; i < 40; ++i) {
        unsigned byte; assert(sscanf(reply + i * 2, "%2x", &byte) == 1); unaligned[i] = byte;
    }
    assert(pico_station_response_valid(unaligned, 40));
    for (unsigned size = 0; size < 42; ++size)
        if (size != 40) assert(!pico_station_response_valid(unaligned, size));
    assert(!pico_station_response_valid(NULL, 40));
    for (unsigned bit = 0; bit < 320; ++bit) {
        unaligned[bit / 8] ^= 1U << (bit % 8);
        assert(!pico_station_response_valid(unaligned, 40));
        unaligned[bit / 8] ^= 1U << (bit % 8);
    }
    puts("PICO_STATION_PROTOCOL_PASS golden=12 corrupted_frames=320 hardware_io=0");
    return 0;
}
