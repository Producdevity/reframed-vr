#include "pico-controller-result.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void number(uint8_t *bytes, double value) { memcpy(bytes, &value, 8); }
static void rejected(const uint8_t *bytes, size_t size)
{
    struct pico_controller_result output, previous;
    memset(&output, 0x5a, sizeof(output)); previous = output;
    assert(!pico_controller_result_decode(bytes, size, &output));
    assert(!memcmp(&output, &previous, sizeof(output)));
}
int main(int argc, char **argv)
{
    uint8_t bytes[PICO_SLAM_RESULT_SIZE] = {1};
    number(bytes + 8, -123); number(bytes + 16, 456); number(bytes + 24, -789);
    number(bytes + 32, sqrt(.5)); number(bytes + 48, sqrt(.5));
    bytes[0x40] = 0; bytes[0x41] = 1; bytes[0x44] = 32;
    bytes[0x52] = 0; bytes[0x54] = 7;
    struct pico_controller_result result;
    assert(pico_controller_result_decode(bytes, sizeof(bytes), &result));
    assert(fabs(result.pose.position[0] + .123) < 1e-12);
    assert(fabs(result.pose.position[1] - .456) < 1e-12);
    assert(fabs(result.pose.position[2] + .789) < 1e-12);
    assert(result.pose.orientation[0] == 0 && result.pose.orientation[2] == 0);
    assert(fabs(result.pose.orientation[1] - sqrt(.5)) < 1e-12);
    assert(result.state == 0 && result.confidence == 1 && result.error == 32);
    assert(result.diagnostic_52 == 0 && result.diagnostic_54 == 7);
    rejected(NULL, sizeof(bytes)); rejected(bytes, sizeof(bytes) - 1);
    rejected(bytes, sizeof(bytes) + 1);
    assert(!pico_controller_result_decode(bytes, sizeof(bytes), NULL));
    number(bytes + 8, NAN); rejected(bytes, sizeof(bytes)); number(bytes + 8, -123);
    number(bytes + 32, 0); rejected(bytes, sizeof(bytes)); number(bytes + 32, sqrt(.5));
    memset(bytes, 0xff, 8); rejected(bytes, sizeof(bytes));
    unsigned records = 0, confident = 0, diagnostic = 0;
    if (argc == 2) {
        FILE *file = fopen(argv[1], "rb"); assert(file);
        size_t count;
        while ((count = fread(bytes, 1, sizeof(bytes), file))) {
            assert(count == sizeof(bytes));
            assert(pico_controller_result_decode(bytes, count, &result));
            assert(result.state == bytes[0x40] && result.confidence == bytes[0x41]);
            assert(result.diagnostic_52 == bytes[0x52] && result.diagnostic_54 == bytes[0x54]);
            confident += result.confidence == 1; diagnostic += result.diagnostic_52 != 0;
            ++records;
        }
        assert(!ferror(file)); fclose(file);
    }
    printf("PICO_CONTROLLER_RESULT_PASS records=%u public_confident=%u diagnostic_52_nonzero=%u\n",
           records, confident, diagnostic);
}
