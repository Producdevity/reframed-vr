/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "libssc-client-private.h"
#include "pico-controller-stream.h"
#include "ssc-clock-linux.h"
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct observed_range {
    uint64_t count, minimum, maximum, last, fingerprint;
};

struct capture {
    SSCSensor *sensor;
    GObject *client;
    GCancellable *cancel;
    struct pico_controller_stream stream;
    struct pico_controller_stream_config config;
    uint64_t reports, accepted, rejected, configuration_reports, unexpected_reports;
    unsigned objects, hands;
    bool configuration_rate_present;
    float configuration_rate_hz;
    bool summary, summary_final, summary_output_failed;
    int64_t summary_last_ns;
    struct observed_range event_ticks, station_ticks, imu_ticks[2];
    uint64_t event_bytes, event_last_bytes, event_hash_bytes, event_hash, event_changes;
    uint64_t imu_decoded, imu_rejected;
    unsigned imu_hands;
    bool pending, failed, stopping, enable_attempted, acknowledged, disabled;
};

static volatile sig_atomic_t interrupted;

static void interrupt(int number) { (void)number; interrupted = 1; }

static int64_t now_ns(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) return -1;
    return (int64_t)value.tv_sec * 1000000000 + value.tv_nsec;
}

static void summary_emit(struct capture *s, int64_t now, bool final);

static gboolean tick(gpointer data)
{
    struct capture *s = data;
    if (s->summary) summary_emit(s, now_ns(), false);
    return G_SOURCE_CONTINUE;
}

static void fail(struct capture *s, const char *message)
{
    fprintf(stderr, "PICO_CONTROLLER_ERROR %s\n", message);
    s->failed = true;
}

static uint64_t fingerprint(const void *data, size_t size)
{
    const unsigned char *bytes = data;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < size; i++) hash = (hash ^ bytes[i]) * UINT64_C(1099511628211);
    return hash;
}

static void observe(struct observed_range *range, uint64_t value, uint64_t hash)
{
    if (!range->count || value < range->minimum) range->minimum = value;
    if (!range->count || value > range->maximum) range->maximum = value;
    range->count++;
    range->last = value;
    range->fingerprint = hash;
}

static uint64_t imu_fingerprint(const struct pico_controller_imu_sample *sample)
{
    unsigned char bytes[25];
    for (unsigned i = 0; i < 8; i++) bytes[i] = sample->timestamp_us >> (8 * i);
    for (unsigned i = 0; i < 7; i++) {
        uint16_t value = i < 3 ? sample->gyroscope[i] :
                         i < 6 ? sample->acceleration[i - 3] : sample->temperature;
        bytes[8 + i * 2] = value;
        bytes[9 + i * 2] = value >> 8;
    }
    bytes[22] = sample->hand;
    bytes[23] = sample->sequence;
    bytes[24] = sample->flags;
    return fingerprint(bytes, sizeof(bytes));
}

static void summary_observe(struct capture *s, uint64_t ticks, const void *bytes, size_t size)
{
    size_t hashed = size < 4096 ? size : 4096;
    uint64_t hash = fingerprint(bytes, hashed);
    if (s->event_ticks.count && (hash != s->event_hash || size != s->event_last_bytes))
        s->event_changes++;
    observe(&s->event_ticks, ticks, hash);
    s->event_bytes += size;
    s->event_last_bytes = size;
    s->event_hash_bytes = hashed;
    s->event_hash = hash;
    struct pico_controller_imu_batch batch;
    unsigned accuracy;
    /* This diagnostic decodes both possible slots; it does not infer connection state. */
    if (!pico_controller_decode_imu_ssc(bytes, size, s->config.mcu_type,
                                       s->config.radio_type, 3, &batch, &accuracy)) {
        s->imu_rejected++;
        return;
    }
    s->imu_decoded++;
    unsigned char station_bytes[8];
    for (unsigned i = 0; i < 8; i++) station_bytes[i] = batch.station_time >> (8 * i);
    observe(&s->station_ticks, batch.station_time, fingerprint(station_bytes, sizeof(station_bytes)));
    for (unsigned i = 0; i < batch.count; i++) {
        const struct pico_controller_imu_sample *sample = &batch.samples[i];
        s->imu_hands |= 1u << (sample->hand - 1);
        observe(&s->imu_ticks[sample->hand - 1], sample->timestamp_us, imu_fingerprint(sample));
    }
}

static void summary_emit(struct capture *s, int64_t now, bool final)
{
    if (!s->summary || s->summary_final || s->summary_output_failed) return;
    if (!final && (now < s->summary_last_ns || now - s->summary_last_ns < INT64_C(1000000000)))
        return;
    s->summary_last_ns = now;
    s->summary_final = final;
    const struct observed_range *e = &s->event_ticks, *station = &s->station_ticks;
    const struct observed_range *left = &s->imu_ticks[0], *right = &s->imu_ticks[1];
    int result = printf("PICO_CONTROLLER_SUMMARY final=%u observed_ns=%" PRId64
        " raw_events=%" PRIu64 " accepted=%" PRIu64 " rejected=%" PRIu64
        " configuration=%" PRIu64 " configuration_rate_present=%u configuration_rate_hz=%.6f"
        " unexpected=%" PRIu64 " accepted_hands=%u"
        " event_ticks_min=%" PRIu64 " event_ticks_max=%" PRIu64 " event_ticks_last=%" PRIu64
        " event_bytes=%" PRIu64 " event_last_bytes=%" PRIu64 " event_hash_bytes=%" PRIu64
        " event_hash_fnv1a64=%016" PRIx64 " event_payload_changes=%" PRIu64
        " imu_assumed_connected_mask=3 imu_decoded=%" PRIu64 " imu_rejected=%" PRIu64 " imu_hands=%u"
        " station_min=%" PRIu64 " station_max=%" PRIu64 " station_last=%" PRIu64
        " station_hash_fnv1a64=%016" PRIx64
        " left_samples=%" PRIu64 " left_us_min=%" PRIu64 " left_us_max=%" PRIu64
        " left_us_last=%" PRIu64 " left_hash_fnv1a64=%016" PRIx64
        " right_samples=%" PRIu64 " right_us_min=%" PRIu64 " right_us_max=%" PRIu64
        " right_us_last=%" PRIu64 " right_hash_fnv1a64=%016" PRIx64 "\n",
        final, now, s->reports, s->accepted, s->rejected, s->configuration_reports,
        s->configuration_rate_present, s->configuration_rate_hz, s->unexpected_reports, s->hands, e->minimum, e->maximum, e->last,
        s->event_bytes, s->event_last_bytes, s->event_hash_bytes, s->event_hash, s->event_changes,
        s->imu_decoded, s->imu_rejected, s->imu_hands, station->minimum, station->maximum, station->last, station->fingerprint,
        left->count, left->minimum, left->maximum, left->last, left->fingerprint,
        right->count, right->minimum, right->maximum, right->last, right->fingerprint);
    if (result < 0 || fflush(stdout)) {
        s->summary_output_failed = true;
        fail(s, "summary output failed");
    }
}

static void finalized(gpointer data, GObject *object)
{
    (void)object;
    struct capture *s = data;
    s->objects--;
}

static void watch(struct capture *s, GObject *object)
{
    if (object) { s->objects++; g_object_weak_ref(object, finalized, s); }
}

static void report(GObject *client, guint id, guint64 high, guint64 low,
                   guint64 ticks, GBytes *payload, gpointer data)
{
    (void)client;
    struct capture *s = data;
    if (s->stopping || high != s->config.suid_high || low != s->config.suid_low)
        return;
    gsize size;
    const void *bytes = g_bytes_get_data(payload, &size);
    if (id == SSC_MSG_RESPONSE_ENABLE_REPORT) {
        if (!bytes || !size || size > 4096) {
            fail(s, "invalid controller configuration response size");
            return;
        }
        SscConfigResponse *configuration = ssc_config_response__unpack(NULL, size, bytes);
        if (!configuration || (configuration->has_sample_rate &&
            (!isfinite(configuration->sample_rate) || configuration->sample_rate < 0))) {
            fail(s, "malformed controller configuration response");
        } else {
            s->configuration_reports++;
            s->configuration_rate_present = configuration->has_sample_rate;
            s->configuration_rate_hz = configuration->sample_rate;
            if (!s->summary) {
                printf("PICO_CONTROLLER_CONFIGURATION rate_present=%u rate_hz=%.6f\n",
                       configuration->has_sample_rate, configuration->sample_rate);
                if (fflush(stdout)) fail(s, "configuration output failed");
            }
        }
        if (configuration) ssc_config_response__free_unpacked(configuration, NULL);
        return;
    }
    if (id == SSC_MSG_RESPONSE_GET_ATTRIBUTES) return;
    if (id != 1024) {
        s->unexpected_reports++;
        fail(s, "unsupported controller event");
        return;
    }
    s->reports++;
    if (s->summary) summary_observe(s, ticks, bytes, size);
    if (!s->summary && s->reports <= 4 && size <= 4096) {
        printf("PICO_CONTROLLER_RAW ticks=%" PRIu64 " bytes=%zu payload=", (uint64_t)ticks, size);
        for (gsize i = 0; i < size; i++) printf("%02x", ((const unsigned char *)bytes)[i]);
        putchar('\n');
        if (fflush(stdout)) fail(s, "raw output failed");
    }
    struct pico_controller_event event;
    if (!pico_controller_stream_report(&s->stream, s->stream.generation, id, high, low,
                                      ticks, bytes, size, now_ns(), &event)) {
        s->rejected++;
        return;
    }
    s->accepted++;
    s->hands |= 1u << (event.sample.hand - 1);
    if (s->summary) return;
    const struct pico_controller_sample *v = &event.sample;
    printf("PICO_CONTROLLER_SAMPLE hand=%u time_ns=%" PRId64 " uncertainty_ns=%" PRId64
           " buttons=%u touches=%u trigger=%u grip=%u stick_x=%u stick_y=%u battery=%u accuracy=%u\n",
           v->hand, event.time.timestamp_ns, event.time.uncertainty_ns, v->buttons, v->touches,
           v->trigger, v->grip, v->stick_x, v->stick_y, v->battery_level, event.accuracy);
    if (fflush(stdout)) fail(s, "sample output failed");
}

static void sent(GObject *object, GAsyncResult *result, gpointer data)
{
    struct capture *s = data;
    GError *error = NULL;
    bool success = ssc_client_send_finish(SSC_CLIENT(object), result, &error);
    s->pending = false;
    if (s->stopping) {
        s->disabled = success;
        if (!success) fail(s, error ? error->message : "disable request failed");
    } else {
        s->acknowledged = success;
        if (!success && !g_error_matches(error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
            fail(s, error ? error->message : "enable request failed");
        if (success) {
            printf("PICO_CONTROLLER_SUBSCRIPTION request_acknowledged=1 requested_rate_hz=480\n");
            if (fflush(stdout)) fail(s, "subscription output failed");
        }
    }
    g_clear_error(&error);
}

static void discovered(GObject *object, GAsyncResult *result, gpointer data)
{
    struct capture *s = data;
    GError *error = NULL;
    watch(s, object);
    s->sensor = ssc_sensor_new_finish(result, &error);
    s->pending = false;
    if (!s->sensor) {
        if (!g_error_matches(error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
            fail(s, error ? error->message : "discovery failed");
        g_clear_error(&error);
        return;
    }
    g_object_get(s->sensor, SSC_SENSOR_CLIENT, &s->client, NULL);
    watch(s, s->client);
    if (g_cancellable_is_cancelled(s->cancel)) return;
    guint64 high = 0, low = 0;
    guint stream_type = G_MAXUINT;
    gboolean available = FALSE;
    g_object_get(s->sensor, SSC_SENSOR_UID_HIGH, &high, SSC_SENSOR_UID_LOW, &low,
                 SSC_SENSOR_AVAILABLE, &available, SSC_SENSOR_STREAM_TYPE, &stream_type, NULL);
    if (!s->client || !available || stream_type != 0 ||
        high != s->config.suid_high || low != s->config.suid_low ||
        !ssc_clock_calibrate_monotonic(&s->config.clock, 16, 100000) ||
        !pico_controller_stream_begin(&s->stream, &s->config)) {
        fail(s, "sensor identity, availability, stream type or clock differs");
        return;
    }
    g_signal_connect(s->client, "report-timestamped", G_CALLBACK(report), s);
    /* b1977 requests 480 Hz although ble_mcu omits the standard rate attribute. */
    const unsigned char configuration[] = {0x0d, 0x00, 0x00, 0xf0, 0x43};
    GArray *message = g_array_sized_new(FALSE, FALSE, 1, sizeof(configuration));
    g_array_append_vals(message, configuration, sizeof(configuration));
    s->pending = s->enable_attempted = true;
    ssc_client_send(SSC_CLIENT(s->client), high, low, SSC_MSG_REQUEST_ENABLE_REPORT_CONTINUOUS,
                    message, s->cancel, sent, s);
    g_array_unref(message);
}

static bool number(const char *text, unsigned low, unsigned high, unsigned *value)
{
    if (!*text || strspn(text, "0123456789") != strlen(text)) return false;
    char *end;
    errno = 0;
    unsigned long parsed = strtoul(text, &end, 10);
    if (errno || *end || parsed < low || parsed > high) return false;
    *value = (unsigned)parsed;
    return true;
}

static bool identifier(const char *text, uint64_t *value)
{
    if (strlen(text) != 16 || strspn(text, "0123456789abcdef") != 16) return false;
    char *end;
    errno = 0;
    *value = strtoull(text, &end, 16);
    return !errno && !*end;
}

static bool board_matches(const char *serial)
{
    if (!*serial || strlen(serial) > 64 ||
        strspn(serial, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != strlen(serial))
        return false;
    char expected[100], line[16384];
    snprintf(expected, sizeof(expected), "androidboot.serialno=%s", serial);
    FILE *file = fopen("/proc/cmdline", "r");
    if (!file) return false;
    bool read = fgets(line, sizeof(line), file) != NULL;
    bool complete = feof(file) || strchr(line, '\n');
    fclose(file);
    if (!read || !complete) return false;
    char *save;
    for (char *part = strtok_r(line, " \r\n", &save); part; part = strtok_r(NULL, " \r\n", &save))
        if (!strcmp(part, expected)) return true;
    return false;
}

int main(int argc, char **argv)
{
    struct capture s = {.config = {.max_age_ns = 100000000}};
    unsigned seconds = 0, touch = 0;
    if ((argc != 8 && argc != 9) || (argc == 9 && strcmp(argv[8], "--summary")) ||
        !board_matches(argv[1]) ||
        !identifier(argv[2], &s.config.suid_high) || !identifier(argv[3], &s.config.suid_low) ||
        (!s.config.suid_high && !s.config.suid_low) ||
        !number(argv[4], 1, 2, &s.config.mcu_type) || !number(argv[5], 1, 2, &s.config.radio_type) ||
        !number(argv[6], 0, 1, &touch) || !number(argv[7], 1, 120, &seconds)) {
        fprintf(stderr, "Usage: %s BOOT_SERIAL SUID_HIGH SUID_LOW MCU RADIO TOUCH SECONDS [--summary] (b1977)\n", argv[0]);
        return 2;
    }
    s.config.touch_supported = touch;
    s.summary = argc == 9;
    s.summary_last_ns = s.summary ? now_ns() : 0;
    signal(SIGPIPE, SIG_IGN);
    signal(SIGINT, interrupt);
    signal(SIGTERM, interrupt);
    guint heartbeat = g_timeout_add(10, tick, &s);
    s.cancel = g_cancellable_new();
    s.pending = true;
    g_async_initable_new_async(SSC_TYPE_SENSOR, G_PRIORITY_DEFAULT, s.cancel, discovered, &s,
                              SSC_SENSOR_DATA_TYPE, "ble_mcu",
                              "requested-uid-high", s.config.suid_high,
                              "requested-uid-low", s.config.suid_low, NULL);
    fprintf(stderr, "PICO_CONTROLLER_LIFECYCLE discovery_started=1\n");
    int64_t end = now_ns() + INT64_C(20000000000);
    while (!s.failed && !interrupted && (!s.acknowledged || s.pending) && now_ns() < end)
        g_main_context_iteration(NULL, TRUE);
    if (!s.acknowledged && !interrupted && !s.failed) fail(&s, "startup deadline expired");
    end = now_ns() + (int64_t)seconds * 1000000000;
    while (s.acknowledged && !s.failed && !interrupted && now_ns() < end)
        g_main_context_iteration(NULL, TRUE);
    g_cancellable_cancel(s.cancel);
    end = now_ns() + INT64_C(5000000000);
    while (s.pending && now_ns() < end) g_main_context_iteration(NULL, TRUE);
    if (s.pending) {
        fprintf(stderr, "PICO_CONTROLLER_CLEANUP pending operation did not drain\n");
        if (s.summary) summary_emit(&s, now_ns(), true);
        return 1;
    }
    s.stopping = true;
    pico_controller_stream_invalidate(&s.stream);
    if (s.client) g_signal_handlers_disconnect_by_data(s.client, &s);
    if (s.enable_attempted) {
        s.pending = true;
        ssc_client_send(SSC_CLIENT(s.client), s.config.suid_high, s.config.suid_low,
                        SSC_MSG_REQUEST_DISABLE_REPORT, NULL, NULL, sent, &s);
        end = now_ns() + INT64_C(5000000000);
        while (s.pending && now_ns() < end) g_main_context_iteration(NULL, TRUE);
        if (s.pending) {
            fprintf(stderr, "PICO_CONTROLLER_CLEANUP disable operation did not drain\n");
            if (s.summary) summary_emit(&s, now_ns(), true);
            return 1;
        }
    }
    g_clear_object(&s.sensor);
    g_clear_object(&s.client);
    g_clear_object(&s.cancel);
    end = now_ns() + INT64_C(5000000000);
    while (s.objects && now_ns() < end) g_main_context_iteration(NULL, TRUE);
    g_source_remove(heartbeat);
    if (s.summary) summary_emit(&s, now_ns(), true);
    bool success = !s.failed && !s.objects && (!s.enable_attempted || s.disabled) &&
                   (s.acknowledged || interrupted);
    fprintf(stderr, "PICO_CONTROLLER_CAPTURE complete=%u acknowledged=%u disabled=%u live_objects=%u"
            " reports=%" PRIu64 " accepted=%" PRIu64 " rejected=%" PRIu64
            " configuration_reports=%" PRIu64 " unexpected_reports=%" PRIu64 " hands=%u physical_acceptance=0\n",
            success, s.acknowledged, s.disabled, s.objects, s.reports, s.accepted, s.rejected,
            s.configuration_reports, s.unexpected_reports, s.hands);
    return success ? 0 : 1;
}
