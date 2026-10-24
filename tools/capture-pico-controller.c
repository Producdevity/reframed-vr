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

struct capture {
    SSCSensor *sensor;
    GObject *client;
    GCancellable *cancel;
    struct pico_controller_stream stream;
    struct pico_controller_stream_config config;
    uint64_t reports, accepted, rejected, configuration_reports, unexpected_reports;
    unsigned objects, hands;
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

static gboolean tick(gpointer data) { (void)data; return G_SOURCE_CONTINUE; }

static void fail(struct capture *s, const char *message)
{
    fprintf(stderr, "PICO_CONTROLLER_ERROR %s\n", message);
    s->failed = true;
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
            printf("PICO_CONTROLLER_CONFIGURATION rate_present=%u rate_hz=%.6f\n",
                   configuration->has_sample_rate, configuration->sample_rate);
            if (fflush(stdout)) fail(s, "configuration output failed");
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
    if (s->reports <= 4 && size <= 4096) {
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
    if (argc != 8 || !board_matches(argv[1]) ||
        !identifier(argv[2], &s.config.suid_high) || !identifier(argv[3], &s.config.suid_low) ||
        (!s.config.suid_high && !s.config.suid_low) ||
        !number(argv[4], 1, 2, &s.config.mcu_type) || !number(argv[5], 1, 2, &s.config.radio_type) ||
        !number(argv[6], 0, 1, &touch) || !number(argv[7], 1, 120, &seconds)) {
        fprintf(stderr, "Usage: %s BOOT_SERIAL SUID_HIGH SUID_LOW MCU RADIO TOUCH SECONDS (b1977)\n", argv[0]);
        return 2;
    }
    s.config.touch_supported = touch;
    signal(SIGPIPE, SIG_IGN);
    signal(SIGINT, interrupt);
    signal(SIGTERM, interrupt);
    guint heartbeat = g_timeout_add(10, tick, NULL);
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
            return 1;
        }
    }
    g_clear_object(&s.sensor);
    g_clear_object(&s.client);
    g_clear_object(&s.cancel);
    end = now_ns() + INT64_C(5000000000);
    while (s.objects && now_ns() < end) g_main_context_iteration(NULL, TRUE);
    g_source_remove(heartbeat);
    bool success = !s.failed && !s.objects && (!s.enable_attempted || s.disabled) &&
                   (s.acknowledged || interrupted);
    fprintf(stderr, "PICO_CONTROLLER_CAPTURE complete=%u acknowledged=%u disabled=%u live_objects=%u"
            " reports=%" PRIu64 " accepted=%" PRIu64 " rejected=%" PRIu64
            " configuration_reports=%" PRIu64 " unexpected_reports=%" PRIu64 " hands=%u physical_acceptance=0\n",
            success, s.acknowledged, s.disabled, s.objects, s.reports, s.accepted, s.rejected,
            s.configuration_reports, s.unexpected_reports, s.hands);
    return success ? 0 : 1;
}
