#include "pico-vendor-slam-output.h"
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

struct backend {
    uint8_t bytes[PICO_SLAM_RESULT_SIZE];
    int result;
    int64_t now;
    unsigned calls;
    bool advance;
    _Atomic bool block, entered;
};

static int get_result(void *data, void *bytes)
{
    struct backend *b = data;
    ++b->calls;
    atomic_store(&b->entered, true);
    while (atomic_load(&b->block)) {}
    if (b->advance) {
        int64_t ts;
        memcpy(&ts, b->bytes, sizeof(ts));
        ts += 1000000;
        memcpy(b->bytes, &ts, sizeof(ts));
        b->now = ts + 2000000;
    }
    memcpy(bytes, b->bytes, sizeof(b->bytes));
    return b->result;
}

static int64_t clock_ns(void *data) { return ((struct backend *)data)->now; }

static struct pico_vendor_slam_output_config config(struct pico_slam_channel *channel, struct backend *b)
{
    memset(b, 0, sizeof(*b));
    const int64_t ts = 1000000000;
    const double one = 1;
    memcpy(b->bytes, &ts, sizeof(ts));
    memcpy(b->bytes + 32, &one, sizeof(one));
    b->bytes[64] = 1;
    b->now = ts + 2000000;
    assert(pico_slam_channel_init(channel, 42));
    return (struct pico_vendor_slam_output_config){.channel = channel, .generation = 1,
        .pose = {.world_from_slam.orientation = {0, 0, 0, 1},
                 .body_from_head.orientation = {0, 0, 0, 1},
                 .direction = PICO_SLAM_WORLD_FROM_BODY, .metres_per_unit = 1, .max_age_ns = 100000000},
        .uncertainty_ns = 1000, .handle = b, .clock_data = b,
        .get_result = get_result, .monotonic_ns = clock_ns};
}

static void absent(struct pico_slam_channel *c, int64_t now)
{
    struct pico_slam_channel_sample sample;
    assert(!pico_slam_channel_read(c, 42, 1, now, 100000000, &sample));
}

static void *callback(void *data)
{
    assert(pico_vendor_slam_output_callback(data) == PICO_SLAM_CHANNEL_PUBLISHED);
    return NULL;
}

static void *callbacks(void *data)
{
    for (unsigned i = 0; i < 1000; ++i) callback(data);
    return NULL;
}

struct stopper { struct pico_vendor_slam_output *output; _Atomic bool entered, returned; };
static void *stopper(void *data)
{
    struct stopper *s = data;
    atomic_store(&s->entered, true);
    pico_vendor_slam_output_stop(s->output);
    atomic_store(&s->returned, true);
    return NULL;
}

int main(int argc, char **argv)
{
    struct pico_slam_channel channel;
    struct backend b;
    struct pico_vendor_slam_output_config c = config(&channel, &b);
    struct pico_vendor_slam_output *o = NULL;
    assert(pico_vendor_slam_output_create(NULL, &o) == -EINVAL);
    c.pose.metres_per_unit = 0;
    assert(pico_vendor_slam_output_create(&c, &o) == -EINVAL && !o);
    c.pose.metres_per_unit = 1;
    assert(!pico_vendor_slam_output_create(&c, &o));
    assert(pico_vendor_slam_output_release(&o) == -EBUSY);
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_WAITING);
    absent(&channel, b.now);
    b.bytes[65] = 1;
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_PUBLISHED);
    struct pico_slam_channel_sample sample;
    assert(pico_slam_channel_read(&channel, 42, 1, b.now, 100000000, &sample));
    assert(sample.pose.position[0] == 0 && sample.pose.orientation[3] == 1);
    b.bytes[65] = 0;
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_REFUSED);
    absent(&channel, b.now);
    b.bytes[65] = 1;
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_REFUSED && b.calls == 3);
    struct pico_vendor_slam_output_status status = {0};
    pico_vendor_slam_output_status(o, &status);
    assert(status.callbacks == 3 && status.published == 1 && status.waiting == 1 && status.failed && status.stopped);
    assert(!pico_vendor_slam_output_release(&o) && !o);

    for (unsigned fault = 0; fault < 8; ++fault) {
        c = config(&channel, &b); b.bytes[65] = 1;
        assert(!pico_vendor_slam_output_create(&c, &o));
        if (fault < 4) assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_PUBLISHED);
        switch (fault) {
        case 0: b.result = -1; break;
        case 1: memset(b.bytes, 0, sizeof(b.bytes)); break;
        case 2: b.now -= 1000; break;
        case 3: break; /* Repeated tracked timestamp. */
        case 4: b.now += 200000000; break; /* Stale first tracked result. */
        case 5: b.bytes[64] = 2; break;
        case 6: b.bytes[65] = 2; break;
        default: b.now = 0; break;
        }
        assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_REFUSED);
        pico_vendor_slam_output_status(o, &status);
        assert(status.failed && status.stopped);
        absent(&channel, 1002000000);
        assert(!pico_vendor_slam_output_release(&o));
    }

    c = config(&channel, &b); b.bytes[65] = 1; b.advance = true;
    assert(!pico_vendor_slam_output_create(&c, &o));
    pthread_t workers[4];
    for (unsigned i = 0; i < 4; ++i) assert(!pthread_create(workers + i, NULL, callbacks, o));
    for (unsigned i = 0; i < 4; ++i) assert(!pthread_join(workers[i], NULL));
    pico_vendor_slam_output_status(o, &status);
    assert(status.published == 4000 && b.calls == 4000 && !status.failed);
    pico_vendor_slam_output_stop(o);
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_REFUSED && b.calls == 4000);
    assert(!pico_vendor_slam_output_release(&o));

    c = config(&channel, &b); b.bytes[65] = 1; atomic_store(&b.block, true);
    assert(!pico_vendor_slam_output_create(&c, &o));
    assert(!pthread_create(workers, NULL, callback, o));
    while (!atomic_load(&b.entered)) {}
    struct stopper s = {.output = o};
    assert(!pthread_create(workers + 1, NULL, stopper, &s));
    while (!atomic_load(&s.entered)) {}
    assert(!atomic_load(&s.returned));
    atomic_store(&b.block, false);
    assert(!pthread_join(workers[0], NULL) && !pthread_join(workers[1], NULL));
    assert(atomic_load(&s.returned));
    absent(&channel, b.now);
    assert(pico_vendor_slam_output_callback(o) == PICO_SLAM_CHANNEL_REFUSED && b.calls == 1);
    assert(!pico_vendor_slam_output_release(&o));

    unsigned records = 0, accepted = 0;
    if (argc == 2) {
        FILE *file = fopen(argv[1], "rb"); assert(file);
        c = config(&channel, &b);
        assert(!pico_vendor_slam_output_create(&c, &o));
        size_t n;
        while ((n = fread(b.bytes, 1, sizeof(b.bytes), file))) {
            assert(n == sizeof(b.bytes));
            struct pico_slam_result decoded;
            assert(pico_slam_result_decode(b.bytes, n, &decoded));
            b.now = decoded.timestamp_ns + 2000000;
            bool tracked = decoded.state == 1 && decoded.confidence == 1;
            enum pico_slam_channel_result rc = pico_vendor_slam_output_callback(o);
            assert(rc == (tracked ? PICO_SLAM_CHANNEL_PUBLISHED : PICO_SLAM_CHANNEL_WAITING));
            assert(pico_slam_channel_read(&channel, 42, 1, b.now, 100000000, &sample) == tracked);
            if (tracked) {
                for (unsigned i = 0; i < 3; ++i) assert(fabs(sample.pose.position[i] - decoded.position[i]) < 1e-9);
                ++accepted;
            }
            ++records;
        }
        assert(!ferror(file)); fclose(file);
        pico_vendor_slam_output_stop(o);
        assert(!pico_vendor_slam_output_release(&o));
    }
    printf("PICO_VENDOR_SLAM_OUTPUT_PASS concurrent_callbacks=4000 faults=8 replay_records=%u published=%u\n", records, accepted);
}
