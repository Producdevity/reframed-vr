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
    assert(pico_controller_motion_producer_update(&p, 8, a, b, 1000000000) == -EPROTO);
    assert(!c->sequence && !c->active);
    assert(pico_controller_motion_producer_resumed(&p,a,b,2001000000,captures)==-EPERM);

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

static const struct ssc_clock test_clock = {.counter_ticks=19200000, .counter_hz=19200000,
    .host_ns=1000000000, .uncertainty_ns=2, .initialized=true};

static void start_test(struct pico_controller_motion_producer *p,
                       struct pico_controller_motion_channel *c, unsigned mask)
{
    assert(!pico_controller_motion_producer_init(p,c,1,2,&test_clock,config,1,2,mask,1000000000));
    assert(!p->error && p->failure==PICO_CONTROLLER_PRODUCER_FAILURE_NONE &&
           !p->rejected_hand && !p->rejected_timestamp_us && !p->failure_now_ns);
}

static int poll_test(struct pico_controller_motion_producer *p, uint8_t a[1000], int64_t now)
{
    return pico_controller_motion_producer_update(p,p->generation,a,a,now);
}

static void check_failure(struct pico_controller_motion_producer *p, int error,
    enum pico_controller_motion_producer_failure reason, unsigned hand,
    uint64_t timestamp, int64_t now)
{
    assert(p->error==error && p->failure==reason && p->rejected_hand==hand &&
           p->rejected_timestamp_us==timestamp && p->failure_now_ns==now && !p->channel->active);
    struct pico_controller_motion_producer saved=*p;
    pico_controller_motion_producer_stop(p);
    assert(pico_controller_motion_producer_update(p,p->generation,NULL,NULL,now+1)==error);
    assert(!memcmp(p,&saved,sizeof(saved)));
    assert(pico_controller_motion_producer_update(p,p->generation+1,NULL,NULL,now+1)==-ESTALE);
    assert(!memcmp(p,&saved,sizeof(saved)));
}

static void startup_and_recovery(void)
{
    for (unsigned missing=1; missing<=2; ++missing) {
        unsigned live=3-missing;
        struct pico_controller_motion_channel *c=calloc(1,sizeof(*c)), *fresh=calloc(1,sizeof(*fresh));
        assert(c && fresh);
        struct pico_controller_motion_producer p={0}; start_test(&p,c,3);
        uint8_t a[1000]={0};
        for (int64_t now=1002000000; now<3000000000; now+=2000000) {
            record(a,(uint64_t)(now-1000000)/1000,live);
            assert(poll_test(&p,a,now)==1);
        }
        uint64_t accepted=c->sequence;
        record(a,2999000,live);
        assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
        assert(c->sequence==accepted && p.received[live-1]==2998000000 && !p.received[missing-1]);
        check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_STARTUP_TIMEOUT,missing,0,3000000000);
        struct ssc_timestamp captures[2]={{17,19},{23,29}}, untouched[2];
        memcpy(untouched,captures,sizeof(captures));
        record(a,3001000,live); record(a+100,2999000,missing);
        assert(!pico_controller_motion_producer_resumed(&p,a,a,3002000000,captures));
        assert(!memcmp(captures,untouched,sizeof(captures)));
        record(a+100,3001000,missing);
        assert(pico_controller_motion_producer_resumed(&p,a,a,3002000000,captures)==1);
        assert(!pico_controller_motion_producer_restart(&p,fresh,3,a,a,3002000000));
        assert(!p.error && !p.failure && !p.failure_now_ns && !p.rejected_hand && !p.rejected_timestamp_us);
        assert(!c->active && fresh->active && !fresh->sequence);
        assert(!poll_test(&p,a,3002000000));
        record(a,3003000,live); record(a+100,3003000,missing);
        assert(poll_test(&p,a,3004000000)==2 && fresh->sequence==2);
        pico_controller_motion_producer_stop(&p); free(c); free(fresh);
    }
    puts("PASS startup_missing_either_hand_first_failure_latched_fresh_both_restart");
}

static void dropouts(void)
{
    for (unsigned missing=1; missing<=2; ++missing) {
        struct pico_controller_motion_channel *c=calloc(1,sizeof(*c));assert(c);
        struct pico_controller_motion_producer p={0};start_test(&p,c,3);
        uint8_t a[1000]={0};record(a,1001000,1);record(a+100,1001000,2);
        assert(poll_test(&p,a,1002000000)==2);
        for (int64_t now=1004000000;now<=1102000000;now+=2000000) {
            record(a+100*(2-missing),(uint64_t)(now-1000000)/1000,3-missing);
            assert(poll_test(&p,a,now)==1);
        }
        record(a+100*(2-missing),1103000,3-missing);
        uint64_t accepted=c->sequence;
        assert(poll_test(&p,a,1104000000)==-ETIMEDOUT && c->sequence==accepted);
        check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_RECEIVE_TIMEOUT,missing,0,1104000000);
        struct ssc_timestamp captures[2]={{0}};
        record(a+100*(2-missing),1105000,3-missing);
        assert(!pico_controller_motion_producer_resumed(&p,a,a,1106000000,captures));
        record(a+100*(missing-1),1105000,missing);
        assert(pico_controller_motion_producer_resumed(&p,a,a,1106000000,captures)==1);
        assert(!c->active);free(c);
    }
    struct pico_controller_motion_channel *c=calloc(1,sizeof(*c));assert(c);
    struct pico_controller_motion_producer p={0};start_test(&p,c,3);
    uint8_t a[1000]={0};record(a,1001000,1);record(a+100,1001000,2);
    assert(poll_test(&p,a,1002000000)==2);
    assert(!poll_test(&p,a,1102000000));
    assert(poll_test(&p,a,1102000001)==-ETIMEDOUT);
    check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_RECEIVE_TIMEOUT,1,0,1102000001);
    start_test(&p,c,3);memset(a,0,sizeof(a));assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
    check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_STARTUP_TIMEOUT,1,0,3000000000);
    for(unsigned hand=1;hand<=2;++hand) {
        start_test(&p,c,1U<<(hand-1));memset(a,0,sizeof(a));
        for(int64_t now=1002000000;now<=3100000000;now+=2000000) {
            record(a,(uint64_t)(now-1000000)/1000,hand);assert(poll_test(&p,a,now)==1);
        }
        assert(c->active && !p.error);
    }
    free(c);puts("PASS receive_dropout_either_hand_both_dropout_unselected_hand_independent");
}

static void errors(void)
{
    struct pico_controller_motion_channel *c=calloc(1,sizeof(*c));assert(c);
    struct pico_controller_motion_producer p={0};uint8_t a[1000]={0};
    start_test(&p,c,3);struct pico_controller_motion_producer saved=p;
    assert(pico_controller_motion_producer_update(&p,999,NULL,NULL,0)==-ESTALE && !memcmp(&p,&saved,sizeof(p)));
    record(a,1001000,1);assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
    check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_SAMPLE_EXPIRED,1,1001000,3000000000);
    start_test(&p,c,3);record(a,4000000,2);assert(poll_test(&p,a,3000000000)==-EPROTO);
    check_failure(&p,-EPROTO,PICO_CONTROLLER_PRODUCER_FAILURE_SAMPLE_TIME,2,4000000,3000000000);
    start_test(&p,c,3);assert(poll_test(&p,NULL,1001000000)==-EINVAL);
    check_failure(&p,-EINVAL,PICO_CONTROLLER_PRODUCER_FAILURE_ARGUMENT,0,0,1001000000);
    start_test(&p,c,3);assert(poll_test(&p,a,999999999)==-ETIME);
    check_failure(&p,-ETIME,PICO_CONTROLLER_PRODUCER_FAILURE_CLOCK,0,0,999999999);
    start_test(&p,c,3);record(a,1001000,2);assert(poll_test(&p,a,1002000000)==1);
    a[33]^=1;checksum(a);assert(poll_test(&p,a,1003000000)==-EPROTO);
    check_failure(&p,-EPROTO,PICO_CONTROLLER_PRODUCER_FAILURE_RING,0,0,1003000000);
    struct ssc_timestamp captures[2]={{0}};
    assert(pico_controller_motion_producer_resumed(&p,a,a,1004000000,captures)==-EPERM);
    start_test(&p,c,3);p.config[1].mcu_type=0;record(a,1001000,2);assert(poll_test(&p,a,1002000000)==-EPROTO);
    check_failure(&p,-EPROTO,PICO_CONTROLLER_PRODUCER_FAILURE_SAMPLE_VALUES,2,1001000,1002000000);
    start_test(&p,c,3);pico_controller_motion_channel_stop(c);assert(poll_test(&p,a,1002000000)==-EPROTO);
    check_failure(&p,-EPROTO,PICO_CONTROLLER_PRODUCER_FAILURE_PUBLISH,2,1001000,1002000000);
    start_test(&p,c,3);pico_controller_motion_producer_stop(&p);
    check_failure(&p,-ESHUTDOWN,PICO_CONTROLLER_PRODUCER_FAILURE_STOP,0,0,1000000000);
    start_test(&p,c,3);a[99]^=1;assert(!poll_test(&p,a,1002000000));
    assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
    check_failure(&p,-ETIMEDOUT,PICO_CONTROLLER_PRODUCER_FAILURE_STARTUP_TIMEOUT,1,0,3000000000);
    free(c);puts("PASS wrong_generation_malformed_clock_stale_age_publish_first_failure_precedence");
}

static void subset_lifecycle(void)
{
    for (unsigned live=1; live<=2; ++live) {
        struct pico_controller_motion_channel *channels[4];
        for (unsigned i=0;i<4;++i) {channels[i]=calloc(1,sizeof(*channels[i]));assert(channels[i]);}
        struct pico_controller_motion_producer p={0};start_test(&p,channels[0],3);
        uint8_t a[1000]={0},b[1000];
        for (int64_t now=1002000000;now<3000000000;now+=2000000) {
            record(a,(uint64_t)(now-1000000)/1000,live);assert(poll_test(&p,a,now)==1);
        }
        assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
        struct pico_controller_motion_offer offer;
        assert(!pico_controller_motion_producer_offer(&p,a,a,3000000000,&offer)&&!offer.mask);
        record(a,3001000,live);
        struct pico_controller_motion_producer saved=p;
        assert(!pico_controller_motion_producer_offer(&p,a,a,3002000000,&offer));
        assert(offer.mask==(1U<<(live-1))&&offer.boundary_ns==3000000000&&
               offer.deadline_ns==3100998998&&!memcmp(&p,&saved,sizeof(p)));
        struct pico_controller_motion_offer bad=offer;bad.mask=3;
        assert(pico_controller_motion_producer_accept(&p,channels[1],3,&bad,a,a,3002000000)==-EAGAIN);
        assert(pico_controller_motion_producer_accept(&p,channels[1],2,&offer,a,a,3002000000)==-ESTALE);
        assert(pico_controller_motion_producer_accept(&p,channels[1],3,&offer,a,a,offer.deadline_ns+1)==-ESTALE);
        assert(!memcmp(&p,&saved,sizeof(p))&&!channels[1]->magic);
        memcpy(b,a,sizeof(b));b[33]^=1;
        struct pico_controller_motion_offer skipped;
        assert(!pico_controller_motion_producer_offer(&p,a,b,3002000000,&skipped)&&!skipped.mask);
        a[99]^=1;assert(!pico_controller_motion_producer_offer(&p,a,a,3002000000,&skipped)&&!skipped.mask);a[99]^=1;
        assert(!pico_controller_motion_producer_accept(&p,channels[1],3,&offer,a,a,3002000000));
        assert(p.connected_mask==offer.mask&&p.configured_mask==3&&!channels[0]->active&&!channels[1]->sequence);
        assert(!poll_test(&p,a,3002000000));
        for (int64_t now=3004000000;now<=5200000000;now+=2000000) {
            record(a,(uint64_t)(now-1000000)/1000,live);assert(poll_test(&p,a,now)==1);
        }
        record(a+100,5201000,3-live);record(a,5201000,live);
        assert(poll_test(&p,a,5202000000)==1);
        assert(!pico_controller_motion_producer_offer(&p,a,a,5202000000,&offer));
        assert(offer.mask==(1U<<(2-live)));
        assert(!pico_controller_motion_producer_retire(&p,3,5202000000));
        assert(!pico_controller_motion_producer_offer(&p,a,a,5202000000,&offer)&&!offer.mask);
        record(a,5203000,live);record(a+100,5203000,3-live);
        assert(!pico_controller_motion_producer_offer(&p,a,a,5204000000,&offer)&&offer.mask==3);
        assert(!pico_controller_motion_producer_accept(&p,channels[2],4,&offer,a,a,5204000000));
        record(a,5205000,live);record(a+100,5205000,3-live);
        assert(poll_test(&p,a,5206000000)==2);
        for (int64_t now=5208000000;now<5306000000;now+=2000000) {
            record(a,(uint64_t)(now-1000000)/1000,live);assert(poll_test(&p,a,now)==1);
        }
        record(a,5307000,live);assert(poll_test(&p,a,5308000000)==-ETIMEDOUT);
        assert(!pico_controller_motion_producer_offer(&p,a,a,5308000000,&offer)&&!offer.mask);
        record(a,5309000,live);
        assert(!pico_controller_motion_producer_offer(&p,a,a,5310000000,&offer)&&offer.mask==(1U<<(live-1)));
        assert(!pico_controller_motion_producer_accept(&p,channels[3],5,&offer,a,a,5310000000));
        assert(poll_test(&p,a,7310000000)==-ETIMEDOUT);
        assert(!pico_controller_motion_producer_offer(&p,a,a,7310000000,&offer)&&!offer.mask);
        record(a,7311000,live);
        assert(!pico_controller_motion_producer_offer(&p,a,a,7312000000,&offer)&&offer.mask==(1U<<(live-1)));
        for (unsigned i=0;i<4;++i) free(channels[i]);
    }
    struct pico_controller_motion_channel *c=calloc(1,sizeof(*c));assert(c);
    struct pico_controller_motion_producer p={0};start_test(&p,c,3);
    uint8_t a[1000]={0};struct pico_controller_motion_offer offer;
    assert(pico_controller_motion_producer_retire(&p,99,1001000000)==-ESTALE&&c->active);
    assert(!pico_controller_motion_producer_retire(&p,2,1000998998));
    record(a,1001000,1);
    assert(!pico_controller_motion_producer_offer(&p,a,a,1002000000,&offer)&&!offer.mask);
    record(a,1001001,1);
    assert(!pico_controller_motion_producer_offer(&p,a,a,1002000000,&offer)&&offer.mask==1);
    record(a,9000000,1);
    assert(pico_controller_motion_producer_offer(&p,a,a,1002000000,&offer)==-EPROTO);
    start_test(&p,c,3);assert(poll_test(&p,a,1002000000)==-EPROTO);
    assert(pico_controller_motion_producer_retire(&p,2,1003000000)==-EPERM);
    assert(pico_controller_motion_producer_offer(&p,a,a,1003000000,&offer)==-EPERM);
    start_test(&p,c,3);memset(a,0,sizeof(a));
    assert(poll_test(&p,a,3000000000)==-ETIMEDOUT);
    int64_t first_failure=p.failure_now_ns;
    record(a,3001000,1);
    assert(!pico_controller_motion_producer_offer(&p,a,a,3002000000,&offer)&&offer.mask==1);
    struct pico_controller_motion_offer old_offer=offer;
    assert(!pico_controller_motion_producer_retire(&p,2,3010000000));
    assert(p.now==3010000000&&p.failure_now_ns==first_failure&&p.failure==PICO_CONTROLLER_PRODUCER_FAILURE_STARTUP_TIMEOUT);
    assert(!pico_controller_motion_producer_offer(&p,a,a,3011000000,&offer)&&!offer.mask);
    struct pico_controller_motion_channel *fresh=calloc(1,sizeof(*fresh));assert(fresh);
    record(a,3012000,1);
    assert(pico_controller_motion_producer_accept(&p,fresh,3,&old_offer,a,a,3013000000)==-ESTALE);
    assert(!pico_controller_motion_producer_offer(&p,a,a,3013000000,&offer)&&offer.mask==1);
    assert(!pico_controller_motion_producer_accept(&p,fresh,3,&offer,a,a,3013000000));
    free(fresh);
    free(c);puts("PASS subset_startup_dropout_join_both_absent_post_boundary_expiry_wrong_generation_malformed");
}

static void replay_subset(const char *input, const char *output)
{
    FILE *file=fopen(input,"rb"),*out=fopen(output,"wx");assert(file&&out);
    uint64_t header[8];assert(fread(header,sizeof(header),1,file)==1);
    assert(header[0]==UINT64_C(0x52564354494d0001)&&header[4]==2024&&header[5]==19200000);
    struct ssc_clock clock={.counter_ticks=3840000000,.counter_hz=19200000,
        .host_ns=INT64_C(200000000000)+(int64_t)header[3],.uncertainty_ns=50002,.initialized=true};
    struct pico_controller_motion_channel *c=calloc(1,sizeof(*c));assert(c);
    struct pico_controller_motion_producer p={0};
    uint64_t cursor=0;unsigned snapshots=0,samples=0,restarts=0;uint8_t raw[2024];size_t bytes;
    while((bytes=fread(raw,1,sizeof(raw),file))) {
        assert(bytes==sizeof(raw));uint64_t receipt;memcpy(&receipt,raw+8,8);fake_now=(int64_t)receipt;
        if(!snapshots)assert(!pico_controller_motion_producer_init(&p,c,19,20,&clock,config,1,2,3,fake_now));
        ++snapshots;
        if(p.error) {
            assert(p.error==-ETIMEDOUT);struct pico_controller_motion_offer offer;
            assert(!pico_controller_motion_producer_offer(&p,raw+24,raw+1024,fake_now,&offer));
            if(offer.mask) {
                assert(offer.mask==1);struct pico_controller_motion_channel *fresh=calloc(1,sizeof(*fresh));assert(fresh);
                assert(!pico_controller_motion_producer_accept(&p,fresh,p.generation+1,&offer,raw+24,raw+1024,fake_now));
                assert(!c->active&&p.connected_mask==1&&p.configured_mask==3&&!fresh->sequence);
                free(c);c=fresh;cursor=0;++restarts;
            }
            continue;
        }
        int count=pico_controller_motion_producer_update(&p,p.generation,raw+24,raw+1024,fake_now);
        if(count<0) {assert(count==-ETIMEDOUT&&p.failure==PICO_CONTROLLER_PRODUCER_FAILURE_STARTUP_TIMEOUT&&p.rejected_hand==2);continue;}
        for(int i=0;i<count;++i) {
            struct pico_controller_motion_event e;
            assert(pico_controller_motion_channel_read(c,19,p.generation,&cursor,clock_ns,NULL,100000000,&e)==1);
            fprintf(out,"%" PRIu64 " %u %" PRIu64 " %" PRId64 "\n",p.generation,e.hand,e.timestamp_us,e.time.timestamp_ns);
            ++samples;
        }
    }
    assert(snapshots&&samples&&restarts==1&&p.connected_mask==1&&p.configured_mask==3&&!p.error);
    assert(feof(file)&&!ferror(file)&&!fclose(file)&&!fclose(out));
    free(c);printf("PICO_CONTROLLER_SUBSET_REPLAY_PASS snapshots=%u samples=%u restarts=%u active_mask=1 configured_mask=3\n",snapshots,samples,restarts);
}

int main(int argc, char **argv)
{
    alarm(20);
    if(argc==4&&!strcmp(argv[1],"--replay-subset")){replay_subset(argv[2],argv[3]);return 0;}
    if (argc == 4 && !strcmp(argv[1], "--replay")) { replay(argv[2], argv[3]); return 0; }
    assert(argc == 1); boundaries(); startup_and_recovery(); dropouts(); errors(); subset_lifecycle();
    puts("PICO_CONTROLLER_MOTION_PRODUCER_PASS");
}
