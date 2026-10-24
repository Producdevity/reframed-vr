#include "pico-controller-motion-consumer.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct fixture {
    struct pico_controller_motion_channel channel;
    struct pico_controller_head *heads;
    struct pico_controller_motion_consumer *consumer;
    int64_t now, call_ns, before, after;
    int result;
    unsigned calls;
};

static int64_t clock_ns(void *data) { return ((struct fixture *)data)->now; }
static int update(void *data, unsigned hand, const double v[9], int64_t ts,
                  const uint8_t *before, const uint8_t *after)
{
    struct fixture *f = data;
    assert(hand == 1 && v[0] == f->calls && ts > 0);
    memcpy(&f->before, before, 8); memcpy(&f->after, after, 8);
    assert(f->before < ts && f->after >= ts);
    ++f->calls; f->now += f->call_ns;
    return f->result;
}

static void head(struct fixture *f, int64_t timestamp, bool tracked)
{
    uint8_t raw[PICO_SLAM_RESULT_SIZE] = {0}; double one = 1;
    memcpy(raw, &timestamp, 8); memcpy(raw+32, &one, 8);
    raw[64] = 1; raw[65] = tracked; raw[69] = 2;
    assert(pico_controller_head_push(f->heads, 7, raw, sizeof(raw), 10, f->now) >= 0);
}

static struct pico_controller_motion_consumer_config setup(struct fixture *f)
{
    memset(f, 0, sizeof(*f)); f->now = 1020700000; f->call_ns = 50;
    f->heads = pico_controller_head_create(7, 100000000, 4000000); assert(f->heads);
    assert(pico_controller_motion_channel_init(&f->channel, 5, 7));
    for (int i=1; i<=20; ++i) head(f, 1000000000+i*1000000, true);
    return (struct pico_controller_motion_consumer_config){
        .channel=&f->channel, .heads=f->heads, .instance=5, .generation=7, .head_generation=7,
        .connected_mask=1, .max_age_ns=100000000, .max_gap_ns=10000000,
        .data=f, .monotonic_ns=clock_ns, .update=update};
}

static void publish(struct fixture *f, unsigned index, int64_t timestamp, unsigned hand)
{
    struct pico_controller_motion_event e = {.timestamp_us=(uint64_t)timestamp/1000,
        .time={timestamp,10}, .received_ns=timestamp+100, .hand=hand, .sequence=index};
    e.values[0] = index;
    assert(pico_controller_motion_channel_publish(&f->channel, &e));
}

static void cleanup(struct fixture *f)
{
    pico_controller_motion_consumer_destroy(f->consumer);
    pico_controller_head_destroy(f->heads);
}

int main(void)
{
    struct fixture *f = malloc(sizeof(*f)); assert(f);
    struct pico_controller_motion_consumer_config cfg = setup(f);
    assert(pico_controller_motion_consumer_create(NULL, &f->consumer) == -EINVAL);
    cfg.connected_mask = 4;
    assert(pico_controller_motion_consumer_create(&cfg, &f->consumer) == -EINVAL);
    cfg.connected_mask = 1;
    assert(!pico_controller_motion_consumer_create(&cfg, &f->consumer));
    publish(f, 0, 1020500000, 1);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && !f->calls);
    struct pico_controller_motion_consumer_status s;
    pico_controller_motion_consumer_status(f->consumer, &s);
    assert(s.pending && s.read == 1 && s.head_waits == 1);
    f->now = 1021200000; head(f, 1021000000, true);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && f->calls == 1);
    assert(f->before == 1020000000 && f->after == 1021000000);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && f->calls == 1);
    pico_controller_motion_consumer_status(f->consumer, &s);
    assert(!s.pending && s.delivered == 1 && s.max_head_wait_ns == 500000 && s.max_call_ns == 50);
    publish(f, 1, 1020800000, 1); publish(f, 2, 1020900000, 1);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && f->calls == 3);
    pico_controller_motion_consumer_stop(f->consumer);
    assert(pico_controller_motion_consumer_poll(f->consumer) == -ESHUTDOWN);
    assert(f->calls == 3); cleanup(f);

    cfg = setup(f);
    cfg.head_generation = 0;
    assert(pico_controller_motion_consumer_create(&cfg, &f->consumer) == -EINVAL);
    cfg.head_generation = 7;
    assert(!pico_controller_motion_consumer_create(&cfg, &f->consumer));
    publish(f, 0, 1020500000, 1);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && !f->calls);
    pico_controller_motion_channel_stop(&f->channel);
    assert(pico_controller_motion_consumer_poll(f->consumer) == -ESHUTDOWN);
    struct pico_controller_motion_channel *fresh = calloc(1, sizeof(*fresh)); assert(fresh);
    assert(pico_controller_motion_channel_init(fresh, 5, 8));
    struct pico_controller_motion_consumer *old = f->consumer;
    f->consumer = NULL;
    cfg.channel = fresh; cfg.generation = 8;
    assert(!pico_controller_motion_consumer_create(&cfg, &f->consumer));
    struct pico_controller_motion_event resumed = {.timestamp_us=1020800,
        .time={1020800000,10}, .received_ns=1020900000, .hand=1};
    assert(pico_controller_motion_channel_publish(fresh, &resumed));
    f->now = 1021200000; head(f, 1021000000, true);
    assert(!pico_controller_motion_consumer_poll(f->consumer) && f->calls == 1);
    assert(f->before == 1020000000 && f->after == 1021000000);
    assert(pico_controller_motion_consumer_poll(old) == -ESHUTDOWN && f->calls == 1);
    pico_controller_motion_consumer_destroy(old); free(fresh); cleanup(f);

    for (unsigned fault=0; fault<9; ++fault) {
        cfg = setup(f); assert(!pico_controller_motion_consumer_create(&cfg, &f->consumer));
        if (fault != 4 && fault != 5) publish(f, 0, 1020500000, 1);
        if (fault == 4) {
            for (unsigned i=0; i<=PICO_CONTROLLER_MOTION_CAPACITY; ++i)
                publish(f, i, 1020500000+i*1000, 1);
        } else if (fault == 5) publish(f, 0, 1020500000, 2);
        int expected;
        switch (fault) {
        case 0:
            assert(!pico_controller_motion_consumer_poll(f->consumer));
            pico_controller_motion_channel_stop(&f->channel); expected=-ESHUTDOWN; break;
        case 1:
            f->now=1021200000; head(f,1021000000,true); f->result=-ENOMEM;
            expected=-ENOMEM; break;
        case 2:
            f->now=1021200000; head(f,1021000000,true);
            assert(!pico_controller_motion_consumer_poll(f->consumer));
            publish(f,1,1031000001,1); f->now=1031100000; expected=-EPROTO; break;
        case 3:
            assert(!pico_controller_motion_consumer_poll(f->consumer));
            f->now+=100000000; expected=-ETIMEDOUT; break;
        case 4: expected=-EOVERFLOW; break;
        case 5: expected=-EPROTO; break;
        case 6:
            assert(!pico_controller_motion_consumer_poll(f->consumer));
            f->now=1021200000; head(f,1021000000,false);
            assert(!pico_controller_motion_consumer_poll(f->consumer) && !f->calls);
            f->now+=100000000; expected=-ETIMEDOUT; break;
        case 7:
            assert(!pico_controller_motion_consumer_poll(f->consumer));
            --f->now; expected=-ETIME; break;
        default:
            f->now=1021200000; head(f,1021000000,true); f->call_ns=100000000;
            expected=-ETIMEDOUT; break;
        }
        assert(pico_controller_motion_consumer_poll(f->consumer) == expected);
        unsigned calls=f->calls;
        assert(pico_controller_motion_consumer_poll(f->consumer) == expected && f->calls == calls);
        pico_controller_motion_consumer_status(f->consumer,&s);
        assert(s.stopped && s.error == expected);
        cleanup(f);
    }
    free(f); puts("PICO_CONTROLLER_MOTION_CONSUMER_PASS"); return 0;
}
