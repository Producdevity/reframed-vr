/* SPDX-License-Identifier: GPL-3.0-or-later */
#define main controller_capture_main
#include "../tools/capture-pico-controller.c"
#undef main
#include <assert.h>

static void emit(struct capture *s, unsigned id, uint64_t high,
                 const void *data, size_t size)
{
    GBytes *bytes = g_bytes_new(data, size);
    report(NULL, id, high, s->config.suid_low, 0, bytes, s);
    g_bytes_unref(bytes);
}

int main(void)
{
    struct capture s = {.config = {.suid_high = 1, .suid_low = 2,
        .mcu_type = 1, .radio_type = 2, .touch_supported = true,
        .max_age_ns = 100000000,
        .clock = {.initialized = true, .counter_hz = 19200000,
                  .host_ns = now_ns() - 1000000, .uncertainty_ns = 2}}};
    assert(pico_controller_stream_begin(&s.stream, &s.config));
    s.enable_attempted = true;
    emit(&s, SSC_MSG_RESPONSE_GET_ATTRIBUTES, 1, NULL, 0);
    assert(!s.failed && !s.unexpected_reports);
    emit(&s, 999, 3, NULL, 0);
    assert(!s.failed && !s.unexpected_reports);
    s.stopping = true;
    emit(&s, 999, 1, NULL, 0);
    assert(!s.failed && !s.unexpected_reports);
    s.stopping = false;
    emit(&s, 999, 1, NULL, 0);
    assert(s.failed && s.unexpected_reports == 1);
    s.failed = false;
    const unsigned char configuration[] = {0x0d, 0x00, 0x00, 0xf0, 0x43};
    emit(&s, SSC_MSG_RESPONSE_ENABLE_REPORT, 1, configuration, sizeof(configuration));
    assert(!s.failed && s.configuration_reports == 1);
    emit(&s, SSC_MSG_RESPONSE_ENABLE_REPORT, 1, configuration, 1);
    assert(s.failed && s.configuration_reports == 1);
    s.failed = false;
    unsigned char record[100] = {0xa5, 1}, payload[127];
    record[7] = 0x40;
    unsigned char crc = 0;
    for (unsigned i = 0; i < 99; i++) {
        crc ^= record[i];
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((crc & 1) ? 0x8c : 0);
    }
    record[99] = crc;
    for (unsigned i = 0; i < 25; i++) {
        payload[5 * i] = 0x0d;
        memcpy(payload + 5 * i + 1, record + 4 * i, 4);
    }
    payload[125] = 0x10;
    payload[126] = 3;
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(!s.failed && s.reports == 1 && s.accepted == 1 && s.hands == 1);
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 2 && s.accepted == 1 && s.rejected == 1);
    payload[1] ^= 1;
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 3 && s.accepted == 1 && s.rejected == 2);
    puts("PICO_CONTROLLER_REPORT_TESTS_PASS cases=9 hardware_access=0");
    return 0;
}
