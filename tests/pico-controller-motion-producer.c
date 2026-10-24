#define _GNU_SOURCE
#include "pico-controller-motion-producer.h"

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int64_t fake_now;
static int64_t clock_ns(void *data) { (void)data; return fake_now; }
static const struct pico_controller_motion_config config[2] = {{1, 53, 0, 0}, {1, 53, 0, 0}};

static void checksum(uint8_t *record)
{
    unsigned crc = 0;
    for (unsigned i = 0; i < 99; ++i) {
        crc ^= record[i];
        for (unsigned j = 0; j < 8; ++j) crc = (crc >> 1) ^ ((crc & 1) ? 0x8c : 0);
    }
    record[99] = crc;
}

static void record(uint8_t *out, uint64_t timestamp, unsigned hand)
{
    memset(out, 0, 100); out[0] = 0xa5; out[1] = 1; out[7] = hand == 1 ? 0x40 : 0;
    const int16_t values[7] = {100, -200, 300, 400, -500, 600, -100};
    for (unsigned i = 0; i < 7; ++i) {
        out[33 + 2 * i] = (uint16_t)values[i];
        out[34 + 2 * i] = (uint16_t)values[i] >> 8;
    }
    for (unsigned i = 0; i < 8; ++i) out[47 + i] = timestamp >> (8 * i);
    out[55] = (uint8_t)timestamp; out[87] = 5; checksum(out);
}

static void boundaries(void)
{
    struct pico_controller_motion_channel *c = calloc(1, sizeof(*c)); assert(c);
    struct pico_controller_motion_producer p = {0};
    struct ssc_clock clock = {.counter_ticks = 19200000, .counter_hz = 19200000,
                              .host_ns = 1000000000, .uncertainty_ns = 2, .initialized = true};
    uint8_t a[1000] = {0}, b[1000] = {0};
    assert(!pico_controller_motion_producer_init(&p, c, 3, 4, &clock, config, 1, 2, 1, 1000000000));
    assert(!pico_controller_motion_producer_update(&p, 4, a, b, 1000001000));
    record(a, 1001000, 1); record(a + 900, 1000000, 1); memcpy(b, a, 1000);
    fake_now = 1002000000;
    assert(pico_controller_motion_producer_update(&p, 4, a, b, fake_now) == 2);
    uint64_t cursor = 0;
    for (unsigned i = 0; i < 2; ++i) {
        struct pico_controller_motion_event out;
        assert(pico_controller_motion_channel_read(c, 3, 4, &cursor, clock_ns, NULL, 100000000, &out) == 1);
        assert(out.timestamp_us == 1000000 + i * 1000 && out.hand == 1 && out.flags == 5);
        assert(out.time.timestamp_ns == 1000000000 + i * 1000000 && out.time.uncertainty_ns == 1002);
        assert(out.received_ns == fake_now && out.values[7] == 1 && out.values[8] == 2);
        assert(out.values[0] == (double)(200 * 0.001065264455974102f));
        assert(out.values[1] == (double)(-100 * 0.001065264455974102f));
    }
    struct pico_controller_motion_producer saved; memcpy(&saved, &p, sizeof(p));
    assert(pico_controller_motion_producer_update(&p, 99, a, b, 0) == -ESTALE);
    assert(!memcmp(&saved, &p, sizeof(p)));
    assert(!pico_controller_motion_producer_update(&p, 4, a, b, fake_now));
    record(a, 1001001, 1); memcpy(b, a, 1000); fake_now += 100000001;
    assert(pico_controller_motion_producer_update(&p, 4, a, b, fake_now) == -ETIMEDOUT);

    struct ssc_timestamp captures[2] = {{17, 19}, {23, 29}}, untouched[2];
    memcpy(untouched, captures, sizeof(captures));
    assert(!pico_controller_motion_producer_resumed(&p, a, b, fake_now, captures));
    assert(!memcmp(captures, untouched, sizeof(captures)));
    uint8_t resumed_a[1000] = {0}, resumed_b[1000];
    record(resumed_a, 1103000, 1); memcpy(resumed_b, resumed_a, 1000);
    memcpy(&saved, &p, sizeof(saved));
    assert(pico_controller_motion_producer_resumed(&p, resumed_a, resumed_b, 1104000000, captures) == 1);
    assert(captures[0].timestamp_ns == 1103000000 && !captures[1].timestamp_ns);
    assert(!memcmp(&saved, &p, sizeof(saved)) && !c->active && c->sequence == 2);
    memcpy(captures, untouched, sizeof(captures));
    assert(!pico_controller_motion_producer_resumed(&p, resumed_a, resumed_b, 1304000000, captures));
    assert(!memcmp(captures, untouched, sizeof(captures)));
    assert(!pico_controller_motion_producer_resumed(&p, resumed_a, resumed_b, 1102000001, captures));
    record(resumed_a, 1001000, 1); resumed_a[33] ^= 1; checksum(resumed_a); memcpy(resumed_b, resumed_a, 1000);
    assert(pico_controller_motion_producer_resumed(&p, resumed_a, resumed_b, 1104000000, captures) == -EPROTO);
    assert(!memcmp(&saved, &p, sizeof(saved)) && !memcmp(captures, untouched, sizeof(captures)));
    assert(pico_controller_motion_channel_read(c, 3, 4, &cursor, clock_ns, NULL, 100000000,
                                              &(struct pico_controller_motion_event){0}) == -ESHUTDOWN);
    assert(pico_controller_motion_producer_update(&p, 4, a, b, fake_now) == -ETIMEDOUT);

    struct pico_controller_motion_channel *fresh = calloc(1, sizeof(*fresh)); assert(fresh);
    memcpy(&saved, &p, sizeof(saved));
    assert(pico_controller_motion_producer_restart(&p, c, 5, a, b, fake_now) == -EINVAL);
    assert(pico_controller_motion_producer_restart(&p, fresh, 4, a, b, fake_now) == -ESTALE);
    assert(pico_controller_motion_producer_restart(&p, fresh, 5, a, b, fake_now-1) == -EINVAL);
    assert(!memcmp(&saved, &p, sizeof(saved)) && !fresh->magic);
    assert(!pico_controller_motion_producer_restart(&p, fresh, 5, a, b, fake_now));
    assert(!fresh->sequence && fresh->active && !c->active);
    assert(pico_controller_motion_channel_read(c, 3, 4, &cursor, clock_ns, NULL, 100000000,
                                              &(struct pico_controller_motion_event){0}) == -ESHUTDOWN);
    assert(pico_controller_motion_producer_update(&p, 4, a, b, fake_now) == -ESTALE);
    assert(!pico_controller_motion_producer_update(&p, 5, a, b, fake_now));
    record(a + 100, 1102001, 1); memcpy(b, a, 1000); fake_now = 1103002000;
    assert(pico_controller_motion_producer_update(&p, 5, a, b, fake_now) == 1);
    cursor = 0; struct pico_controller_motion_event event;
    assert(pico_controller_motion_channel_read(fresh, 3, 5, &cursor, clock_ns, NULL,
                                              100000000, &event) == 1);
    assert(event.timestamp_us == 1102001 && cursor == 1);
    struct pico_controller_motion_channel *again = calloc(1, sizeof(*again)); assert(again);
    assert(pico_controller_motion_producer_restart(&p, again, 6, a, b, fake_now) == -EPERM);
    pico_controller_motion_producer_stop(&p);
    a[133] ^= 1; checksum(a + 100); memcpy(b, a, 1000);
    memcpy(&saved, &p, sizeof(saved));
    assert(pico_controller_motion_producer_restart(&p, again, 6, a, b, fake_now) == -EPROTO);
    assert(!memcmp(&saved, &p, sizeof(saved)) && !again->magic);
    a[133] ^= 1; checksum(a + 100); memcpy(b, a, 1000);
    assert(!pico_controller_motion_producer_restart(&p, again, 6, a, b, fake_now));
    assert(!again->sequence && !fresh->active);
    pico_controller_motion_producer_stop(&p); free(fresh); free(again);
    assert(!pico_controller_motion_producer_init(&p, c, 5, 6, &clock, config, 1, 2, 1, 1000000000));
    memset(a, 0, 1000); memset(b, 0, 1000);
    assert(!pico_controller_motion_producer_update(&p, 6, a, b, 2999999999));
    assert(pico_controller_motion_producer_update(&p, 6, a, b, 3000000000) == -ETIMEDOUT);

    assert(!pico_controller_motion_producer_init(&p, c, 7, 8, &clock, config, 1, 2, 1, 1000000000));
    record(a, 2000000, 1); memcpy(b, a, 1000);
    assert(pico_controller_motion_producer_update(&p, 8, a, b, 1000000000) == -ETIMEDOUT);
    assert(!c->sequence && !c->active);

    assert(!pico_controller_motion_producer_init(&p, c, 9, 10, &clock, config, 1, 2, 1, 1000000000));
    memset(a, 0, 1000); record(a, 1001000, 1); memcpy(b, a, 1000);
    assert(pico_controller_motion_producer_update(&p, 10, a, b, 1002000000) == 1);
    a[33] ^= 1; checksum(a); memcpy(b, a, 1000);
    assert(pico_controller_motion_producer_update(&p, 10, a, b, 1002000001) == -EPROTO);
    assert(c->sequence == 1 && !c->active);
    assert(pico_controller_motion_producer_resumed(&p, a, b, 1002000002, captures) == -EPERM);
    fresh = calloc(1, sizeof(*fresh)); assert(fresh);
    assert(pico_controller_motion_producer_restart(&p, fresh, 11, a, b, 1002000002) == -EPERM);
    assert(!fresh->magic); free(fresh);

    assert(!pico_controller_motion_producer_init(&p, c, 11, 12, &clock, config, 1, 2, 3, 1000000000));
    record(a, 1001000, 1); memcpy(b, a, 1000);
    assert(pico_controller_motion_producer_update(&p, 12, a, b, 1002000000) == 1);
    assert(pico_controller_motion_producer_update(&p, 12, a, b, 1001999999) == -ETIME);
    assert(!c->active);
    assert(pico_controller_motion_producer_resumed(&p, a, b, 1002000000, captures) == -EPERM);

    assert(!pico_controller_motion_producer_init(&p, c, 15, 16, &clock, config, 1, 2, 3, 1000000000));
    memset(a, 0, 1000); record(a, 1001000, 1); record(a+100,1001000,2);memcpy(b,a,1000);
    assert(pico_controller_motion_producer_update(&p,16,a,b,1002000000)==2);
    assert(pico_controller_motion_producer_update(&p,16,a,b,1102000001)==-ETIMEDOUT);
    record(a,1103000,1);memcpy(b,a,1000);
    assert(!pico_controller_motion_producer_resumed(&p,a,b,1104000000,captures));
    record(a+100,1103000,2);memcpy(b,a,1000);
    assert(pico_controller_motion_producer_resumed(&p,a,b,1104000000,captures)==1);
    assert(captures[0].timestamp_ns==1103000000 && captures[1].timestamp_ns==1103000000);
    assert(pico_controller_motion_producer_init(&p, c, 1, 2, &clock, config, 1, 2, 0, 1000000000) == -EINVAL);
    struct pico_controller_motion_config bad[2]; memcpy(bad, config, sizeof(bad)); bad[0].mcu_type = 2;
    assert(pico_controller_motion_producer_init(&p, c, 1, 2, &clock, bad, 1, 2, 1, 1000000000) == -EINVAL);
    assert(!pico_controller_motion_producer_init(&p,c,21,22,&clock,config,1,2,1,1000000000));
    memset(a,0,sizeof(a));record(a,1001000,1);memcpy(b,a,sizeof(b));
    assert(pico_controller_motion_producer_update(&p,22,a,b,1002000000)==1);
    record(a,1201000,1);memcpy(b,a,sizeof(b));
    assert(pico_controller_motion_producer_update(&p,22,a,b,1202000000)==1);
    assert(c->active && c->sequence==2);
    assert(!pico_controller_motion_producer_init(&p,c,23,24,&clock,config,1,2,1,1000000000));
    memset(a,0,sizeof(a));record(a,2999000,1);memcpy(b,a,sizeof(b));
    assert(pico_controller_motion_producer_update(&p,24,a,b,3000000000)==1);
    assert(c->active && c->sequence==1);
    free(c);
}

static void replay(const char *input, const char *output)
{
    FILE *file = fopen(input, "rb"), *out = fopen(output, "wx"); assert(file && out);
    uint64_t header[8]; assert(fread(header, sizeof(header), 1, file) == 1);
    assert(header[0] == UINT64_C(0x52564354494d0001) && header[4] == 2024 && header[5] == 19200000);
    struct ssc_clock clock = {.counter_ticks = 3840000000, .counter_hz = 19200000,
        .host_ns = INT64_C(200000000000) + (int64_t)header[3],
        .uncertainty_ns = 50002, .initialized = true};
    struct pico_controller_motion_channel *c = calloc(1, sizeof(*c)); assert(c);
    struct pico_controller_motion_producer producer = {0};
    uint64_t cursor = 0; unsigned snapshots = 0, samples = 0; uint8_t raw[2024];
    size_t bytes;
    while ((bytes=fread(raw, 1, sizeof(raw), file))) {
        assert(bytes==sizeof(raw));
        uint64_t receipt; memcpy(&receipt, raw + 8, sizeof(receipt)); fake_now = (int64_t)receipt;
        if (!snapshots) assert(!pico_controller_motion_producer_init(&producer, c, 19, 20,
            &clock, config, 1, 2, 1, fake_now));
        int count = pico_controller_motion_producer_update(&producer, 20, raw + 24, raw + 1024, fake_now);
        assert(count >= 0);
        for (int i = 0; i < count; ++i) {
            struct pico_controller_motion_event e;
            assert(pico_controller_motion_channel_read(c, 19, 20, &cursor,
                clock_ns, NULL, 100000000, &e) == 1);
            fprintf(out, "%u %" PRIu64 " %u %u %" PRId64 " %" PRId64 " %" PRId64,
                    e.hand, e.timestamp_us, e.sequence, e.flags, e.time.timestamp_ns,
                    e.time.uncertainty_ns, e.received_ns);
            for (unsigned j = 0; j < 9; ++j) fprintf(out, " %.17g", e.values[j]);
            fputc('\n', out); ++samples;
        }
        ++snapshots;
    }
    assert(snapshots && samples && feof(file) && !ferror(file)); assert(!fclose(file) && !fclose(out));
    pico_controller_motion_producer_stop(&producer); free(c);
    printf("PICO_CONTROLLER_MOTION_REPLAY_PASS snapshots=%u samples=%u\n", snapshots, samples);
}

int main(int argc, char **argv)
{
    alarm(20);
    if (argc == 4 && !strcmp(argv[1], "--replay")) { replay(argv[2], argv[3]); return 0; }
    assert(argc == 1); boundaries(); puts("PICO_CONTROLLER_MOTION_PRODUCER_PASS");
}
