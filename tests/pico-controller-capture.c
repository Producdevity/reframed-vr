/* SPDX-License-Identifier: GPL-3.0-or-later */
#define main controller_capture_main
#include "../tools/capture-pico-controller.c"
#undef main
#include <assert.h>
#include <fcntl.h>
#include <unistd.h>

static void emit(struct capture *s, unsigned id, uint64_t high,
                 const void *data, size_t size)
{
    GBytes *bytes = g_bytes_new(data, size);
    report(NULL, id, high, s->config.suid_low, 0, bytes, s);
    g_bytes_unref(bytes);
}

static struct capture summary_capture(void)
{
    struct capture s = {.summary = true, .config = {.suid_high = 1, .suid_low = 2,
        .mcu_type = 1, .radio_type = 2, .touch_supported = true, .max_age_ns = 100000000,
        .clock = {.initialized = true, .counter_hz = 19200000,
                  .host_ns = now_ns() - 1000000, .uncertainty_ns = 2}}};
    assert(pico_controller_stream_begin(&s.stream, &s.config));
    return s;
}

static void summary_packet(unsigned char payload[127])
{
    unsigned char record[100] = {0xa5, 1};
    record[7] = 0x40;
    uint64_t controller = UINT64_C(0x123456789a), station = UINT64_C(0x23456789ab);
    for (unsigned i = 0; i < 8; i++) {
        record[47 + i] = controller >> (8 * i);
        record[56 + i] = station >> (8 * i);
    }
    unsigned char crc = 0;
    for (unsigned i = 0; i < 99; i++) {
        crc ^= record[i];
        for (unsigned bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) ? 0x8c : 0);
    }
    record[99] = crc;
    for (unsigned i = 0; i < 25; i++) {
        payload[5 * i] = 0x0d;
        memcpy(payload + 5 * i + 1, record + 4 * i, 4);
    }
    payload[125] = 0x10; payload[126] = 3;
}

static long output_size(FILE *file)
{
    assert(fflush(stdout) == 0 && fseek(file, 0, SEEK_END) == 0);
    return ftell(file);
}

static void summary_tests(void)
{
    assert(fflush(stdout) == 0);
    int saved = dup(STDOUT_FILENO); assert(saved >= 0);
    FILE *output = tmpfile(); assert(output && dup2(fileno(output), STDOUT_FILENO) >= 0);
    struct capture s = summary_capture();
    summary_emit(&s, 500000000, false); assert(output_size(output) == 0);
    summary_emit(&s, 1000000000, false); long first = output_size(output); assert(first > 0 && first < 2048);
    summary_emit(&s, 1500000000, false); assert(output_size(output) == first);
    summary_emit(&s, 1600000000, true); long final = output_size(output); assert(final > first);
    summary_emit(&s, 2000000000, true); summary_emit(&s, 3000000000, false);
    assert(output_size(output) == final);

    unsigned char payload[127]; summary_packet(payload); s = summary_capture();
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 1 && s.accepted == 1 && s.imu_decoded == 1 && !s.imu_rejected);
    assert(s.imu_ticks[0].last == UINT64_C(0x123456789a) && s.imu_ticks[0].count == 1);
    assert(s.station_ticks.last == UINT64_C(0x23456789ab) && s.imu_hands == 1);
    assert(s.event_last_bytes == sizeof(payload) && s.event_hash_bytes == sizeof(payload));
    assert(output_size(output) == final);

    uint64_t hash = s.event_hash, imu_hash = s.imu_ticks[0].fingerprint;
    struct pico_controller_stream previous = s.stream;
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 2 && s.accepted == 1 && s.rejected == 1 && s.imu_decoded == 2);
    assert(!s.event_changes && s.event_hash == hash && s.imu_ticks[0].fingerprint == imu_hash);
    assert(!memcmp(&previous, &s.stream, sizeof(previous)));

    payload[1] ^= 1;
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 3 && s.rejected == 2 && s.imu_rejected == 1 && s.event_changes == 1);
    assert(s.imu_ticks[0].count == 2 && s.event_hash != hash);

    struct capture before = s;
    emit(&s, 1024, 3, payload, sizeof(payload));
    GBytes *bytes = g_bytes_new(payload, sizeof(payload));
    report(NULL, 1024, 1, 99, 0, bytes, &s); g_bytes_unref(bytes);
    assert(!memcmp(&s, &before, sizeof(s)));

    s.stopping = true; before = s;
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(!memcmp(&s, &before, sizeof(s)));
    summary_emit(&s, 4000000000, true); assert(s.summary_final);

    s = summary_capture(); const unsigned char configuration[] = {0x0d, 0, 0, 0xf0, 0x43};
    long length = output_size(output);
    emit(&s, SSC_MSG_RESPONSE_ENABLE_REPORT, 1, configuration, sizeof(configuration));
    assert(!s.failed && s.configuration_reports == 1 && !s.reports && output_size(output) == length);
    assert(s.configuration_rate_present && s.configuration_rate_hz == 480.0f);
    emit(&s, SSC_MSG_RESPONSE_ENABLE_REPORT, 1, configuration, 1);
    assert(s.failed && s.configuration_reports == 1);
    assert(s.configuration_rate_present && s.configuration_rate_hz == 480.0f);
    summary_emit(&s, 1000000000, true);
    assert(fflush(stdout) == 0 && fseek(output, length, SEEK_SET) == 0);
    char configuration_line[2048];
    assert(fgets(configuration_line, sizeof(configuration_line), output));
    assert(strstr(configuration_line, "configuration_rate_present=1 configuration_rate_hz=480.000000"));

    s = summary_capture(); emit(&s, 999, 1, NULL, 0);
    assert(s.failed && s.unexpected_reports == 1 && !s.reports);

    s = summary_capture(); s.config.clock.host_ns = now_ns() - 200000000;
    assert(pico_controller_stream_begin(&s.stream, &s.config)); summary_packet(payload);
    emit(&s, 1024, 1, payload, sizeof(payload));
    assert(s.reports == 1 && !s.accepted && s.rejected == 1 && s.imu_decoded == 1);
    assert(!s.stream.seen[0]);

    s = summary_capture(); assert(fflush(stdout) == 0);
    int read_only = open("/dev/null", O_RDONLY); assert(read_only >= 0);
    assert(dup2(read_only, STDOUT_FILENO) >= 0); close(read_only);
    summary_emit(&s, 1000000000, false);
    assert(s.failed && s.summary_output_failed);
    summary_emit(&s, 2000000000, true); assert(!s.summary_final);
    assert(dup2(saved, STDOUT_FILENO) >= 0); close(saved); clearerr(stdout);
    fclose(output);
}

int main(void)
{
    assert(setvbuf(stdout, NULL, _IONBF, 0) == 0);
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
    summary_tests();
    puts("PICO_CONTROLLER_REPORT_TESTS_PASS cases=19 hardware_access=0");
    return 0;
}
