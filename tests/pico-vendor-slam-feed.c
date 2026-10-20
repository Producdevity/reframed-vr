#include "pico-vendor-slam-feed.h"
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BASE INT64_C(1000000000)
#define STRIDE 648
static uint8_t pixels[4][STRIDE * 480];
struct backend {
    unsigned pairs, sets;
    double last_imu[7];
    int64_t last_ns;
    const struct pico_vendor_slam_vector *images[8];
};
static struct backend backend;
static struct pico_vendor_slam_feed *feed;
static uint64_t generation;
static unsigned faults;

static void imu(void *handle, const struct pico_vendor_slam_vector *v, int64_t timestamp)
{
    struct backend *b = handle;
    const double *begin = v->begin, *end = v->end;
    assert(end - begin == 7 && v->capacity == v->end && timestamp > b->last_ns);
    memcpy(b->last_imu, begin, sizeof(b->last_imu));
    b->last_ns = timestamp;
    ++b->pairs;
}
static void image(void *handle, int kind, const struct pico_vendor_slam_vector *v)
{
    struct backend *b = handle;
    const struct pico_vendor_slam_image *begin = v->begin, *end = v->end;
    assert(!kind && end - begin == 4 && v->capacity == v->end && b->sets < 8);
    assert(b->pairs && begin[0].center_ns <= b->last_ns);
    b->images[b->sets++] = v;
}
static struct pico_vendor_slam_feed_config config(void)
{
    return (struct pico_vendor_slam_feed_config){.generation = generation,
        .max_age_ns = 100000000, .max_imu_gap_ns = 10000000, .max_camera_gap_ns = 50000000,
        .max_camera_skew_ns = 100, .startup_timeout_ns = 200000000,
        .retained_sets = 8, .pending_sets = 2, .handle = &backend, .imu = imu, .image = image};
}
static uint8_t copied_pixels[4][640 * 480];
static void copy_image(void *handle, int kind, const struct pico_vendor_slam_vector *v)
{
    struct backend *b = handle;
    const struct pico_vendor_slam_image *images = v->begin;
    assert(!kind && v->end == images + 4 && v->capacity == v->end);
    for (unsigned i = 0; i < 4; ++i) {
        assert(images[i].camera == i && images[i].number == b->sets + 1);
        assert(images[i].center_ns <= b->last_ns);
        memcpy(copied_pixels[i], images[i].pixels, sizeof(copied_pixels[i]));
    }
    ++b->sets;
}
static void release(void)
{
    pico_vendor_slam_feed_stop(feed);
    assert(!pico_vendor_slam_feed_release(&feed) && !feed);
}
static void begin(void)
{
    release();
    memset(&backend, 0, sizeof(backend));
    ++generation;
    struct pico_vendor_slam_feed_config c = config();
    assert(!pico_vendor_slam_feed_create(&c, BASE, &feed));
}
static struct ssc_imu_event sample(unsigned sensor, int64_t time)
{
    return (struct ssc_imu_event){.sensor = sensor, .generation = generation,
        .ticks = (uint64_t)time * 2, .time = {time, 5},
        .vector = {.values = {1 + sensor, 3 + sensor, 5 + sensor},
            .fourth = sensor ? 29.9f : 25.0f, .has_fourth = true, .accuracy = 0}};
}
static int push(unsigned sensor, int64_t time, int64_t now)
{
    struct ssc_imu_event s = sample(sensor, time);
    return pico_vendor_slam_feed_imu(feed, &s, now);
}
static void pair(int64_t time, int64_t now)
{
    assert(!push(1, time, now));
    assert(!push(0, time, now));
}
static void cameras(struct pico_vendor_slam_camera c[4], uint64_t number, int64_t time)
{
    for (unsigned i = 0; i < 4; ++i) {
        unsigned id = 3 - i;
        for (unsigned y = 0; y < 480; ++y) {
            memset(pixels[id] + y * STRIDE, (int)(20 * id + y % 17), 640);
            memset(pixels[id] + y * STRIDE + 640, 0xef, STRIDE - 640);
        }
        c[i] = (struct pico_vendor_slam_camera){.calibration_id = id, .classification = 1,
            .exposure = 600, .gain = 128, .number = number,
            .sof_ns = time + 20, .center_ns = time + id, .uncertainty_ns = 3,
            .pixels = pixels[id], .stride = STRIDE, .size = sizeof(pixels[id])};
    }
}
static void verify_retained(void)
{
    for (unsigned n = 0; n < backend.sets; ++n) {
        const struct pico_vendor_slam_image *images = backend.images[n]->begin;
        for (unsigned i = 0; i < 4; ++i) {
            const struct pico_vendor_slam_image *im = &images[i];
            assert(im->camera == i && im->width == 640 && im->height == 480);
            assert(im->format == 0x123 && im->type == 1 && im->size == 640 * 480);
            assert(im->number == n + 1 && im->exposure == 600 && im->gain == 128);
            for (unsigned y = 0; y < 480; ++y) for (unsigned x = 0; x < 640; ++x)
                assert(im->pixels[y * 640 + x] == 20 * i + (y ? y : 1) % 17);
        }
    }
}
static void terminal(int rc)
{
    assert(rc < 0);
    unsigned p = backend.pairs, s = backend.sets;
    assert(pico_vendor_slam_feed_poll(feed, generation, BASE + 1000) == rc);
    assert(push(0, BASE + 200, BASE + 1000) == rc);
    assert(backend.pairs == p && backend.sets == s);
    struct pico_vendor_slam_feed_status status = {0};
    pico_vendor_slam_feed_status(feed, &status);
    assert(status.error == rc);
    ++faults;
}

int main(void)
{
    generation = 1;
    struct pico_vendor_slam_feed_config c = config();
    for (unsigned i = 0; i < 18; ++i) {
        struct pico_vendor_slam_feed_config bad = c;
        switch (i) {
        case 0: bad.generation = 0; break;
        case 1: bad.max_age_ns = 0; break;
        case 2: bad.max_age_ns = INT64_MAX; break;
        case 3: bad.max_imu_gap_ns = 0; break;
        case 4: bad.max_camera_gap_ns = bad.max_age_ns + 1; break;
        case 5: bad.max_camera_skew_ns = -1; break;
        case 6: bad.max_camera_skew_ns = bad.max_camera_gap_ns + 1; break;
        case 7: bad.startup_timeout_ns = INT64_MAX; break;
        case 8: bad.retained_sets = 0; break;
        case 9: bad.retained_sets = 385; break;
        case 10: bad.pending_sets = 0; break;
        case 11: bad.pending_sets = 9; break;
        case 12: bad.retained_sets = 1; bad.pending_sets = 2; break;
        case 13: bad.handle = NULL; break;
        case 14: bad.imu = NULL; break;
        case 15: bad.image = NULL; break;
        case 16: bad.image_lifetime = 2; break;
        case 17: bad.image_lifetime = (enum pico_vendor_slam_image_lifetime)-1; break;
        }
        assert(pico_vendor_slam_feed_create(&bad, BASE, &feed) == -EINVAL && !feed);
    }
    assert(pico_vendor_slam_feed_create(&c, 0, &feed) == -EINVAL);
    assert(pico_vendor_slam_feed_create(NULL, BASE, &feed) == -EINVAL);
    assert(pico_vendor_slam_feed_poll(NULL, generation, BASE) == -EINVAL);
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        begin();
        struct pico_vendor_slam_camera cams[4];
        cameras(cams, 1, BASE + 100);
        assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
        memset(pixels, 0xaa, sizeof(pixels));
        assert(!backend.sets);
        pair(BASE + 90, BASE + 130);
        pair(BASE + 110, BASE + 130);
        assert(!backend.sets); /* newest IMU's lower bound is 105; cameras need 106 */
        pair(BASE + 111, BASE + 130);
        assert(backend.sets == 1 && backend.pairs == 3);
        const double expected[] = {2, 4, 6, 1, 3, 5, 25};
        assert(!memcmp(expected, backend.last_imu, sizeof(expected)));
        cameras(cams, 2, BASE + 200);
        pair(BASE + 220, BASE + 250);
        assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 250));
        memset(pixels, 0xbb, sizeof(pixels));
        assert(backend.sets == 2);
        assert(pico_vendor_slam_feed_release(&feed) == -EBUSY && feed);
        struct ssc_imu_event stale = sample(0, BASE + 900);
        --stale.generation;
        assert(pico_vendor_slam_feed_imu(feed, &stale, INT64_MAX) == -ESTALE);
        assert(pico_vendor_slam_feed_camera(feed, generation - 1, NULL, INT64_MAX) == -ESTALE);
        assert(!pico_vendor_slam_feed_poll(feed, generation, BASE + 250));
        pico_vendor_slam_feed_stop(feed);
        verify_retained(); /* delayed vendor reads, including vector metadata, after stop */
        release();
    }

    for (unsigned i = 0; i < 16; ++i) {
        begin();
        struct ssc_imu_event s = sample(0, BASE + 100);
        switch (i) {
        case 0: s.sensor = 2; break;
        case 1: s.ticks = 0; break;
        case 2: s.vector.accuracy = 4; break;
        case 3: s.vector.has_fourth = false; break;
        case 4: s.vector.fourth = NAN; break;
        case 5: s.vector.values[2] = INFINITY; break;
        case 6: s.time.timestamp_ns = 0; break;
        case 7: s.time.timestamp_ns = INT64_MAX; break;
        case 8: s.time.uncertainty_ns = -1; break;
        case 9: s.time.uncertainty_ns = INT64_MAX; break;
        case 10: s.time.timestamp_ns = BASE + 126; break;
        case 11: pair(BASE + 100, BASE + 120); break;
        case 12: pair(BASE + 100, BASE + 120); s.ticks += 1; break;
        case 13: pair(BASE + 100, BASE + 120); s.time.timestamp_ns += 1; break;
        case 14: s.time.timestamp_ns = BASE - 100000000; break;
        case 15: pair(BASE + 100, BASE + 120); s.time.timestamp_ns += 10000001; s.ticks += 30000000; break;
        }
        int64_t now = i == 15 ? s.time.timestamp_ns + 20 : BASE + 130;
        terminal(pico_vendor_slam_feed_imu(feed, &s, now));
    }
    begin();
    assert(!push(0, BASE + 100, BASE + 130));
    struct ssc_imu_event g = sample(1, BASE + 100); ++g.ticks;
    terminal(pico_vendor_slam_feed_imu(feed, &g, BASE + 130));
    begin();
    assert(!push(0, BASE + 100, BASE + 130));
    g = sample(1, BASE + 101); g.ticks = (uint64_t)(BASE + 100) * 2;
    terminal(pico_vendor_slam_feed_imu(feed, &g, BASE + 130));
    begin();
    assert(!push(0, BASE + 100, BASE + 130));
    assert(!push(0, BASE + 101, BASE + 130));
    assert(!push(1, BASE + 101, BASE + 130));
    struct pico_vendor_slam_feed_status status = {0};
    pico_vendor_slam_feed_status(feed, &status);
    assert(status.imu_pairs == 1 && status.unmatched[0] == 1 && !status.unmatched[1]);
    begin();
    for (unsigned i = 0; i < 32; ++i) assert(!push(0, BASE + i + 1, BASE + 100));
    assert(push(0, BASE + 33, BASE + 100) == -ENOBUFS);
    terminal(-ENOBUFS);

    for (unsigned i = 0; i < 24; ++i) {
        begin();
        struct pico_vendor_slam_camera cams[4];
        cameras(cams, 1, BASE + 100);
        switch (i) {
        case 0: cams[0].calibration_id = 4; break;
        case 1: cams[0].calibration_id = cams[1].calibration_id; break;
        case 2: cams[0].classification = 3; break;
        case 3: cams[0].number = 0; break;
        case 4: cams[0].number = 2; break;
        case 5: cams[0].exposure = 0; break;
        case 6: cams[0].exposure = 4096; break;
        case 7: cams[0].gain = 0; break;
        case 8: cams[0].gain = 256; break;
        case 9: cams[0].sof_ns = cams[0].center_ns - 1; break;
        case 10: cams[0].sof_ns = BASE + 131; break;
        case 11: cams[0].center_ns = 0; break;
        case 12: cams[0].center_ns = INT64_MAX; break;
        case 13: cams[0].uncertainty_ns = -1; break;
        case 14: cams[0].uncertainty_ns = INT64_MAX; break;
        case 15: cams[0].pixels = NULL; break;
        case 16: cams[0].stride = 639; break;
        case 17: cams[0].stride = SIZE_MAX; break;
        case 18: cams[0].size = 479 * STRIDE + 639; break;
        case 19: cams[0].center_ns = BASE - 1000; break;
        case 20: cams[0].center_ns = BASE - 100000000; break;
        case 21: pair(BASE + 80, BASE + 130); pair(BASE + 120, BASE + 130);
            assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130)); break;
        case 22: pair(BASE + 80, BASE + 130); pair(BASE + 120, BASE + 130);
            assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
            cameras(cams, 1, BASE + 101); break;
        case 23: pair(BASE + 80, BASE + 130); pair(BASE + 120, BASE + 130);
            assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
            cameras(cams, 2, BASE + 50000101); break;
        }
        int64_t now = i == 23 ? BASE + 50000131 : BASE + 130;
        unsigned before = backend.sets;
        terminal(pico_vendor_slam_feed_camera(feed, generation, cams, now));
        assert(backend.sets == before);
    }
    begin();
    struct pico_vendor_slam_camera cams[4];
    for (unsigned i = 0; i < 2; ++i) {
        cameras(cams, i + 1, BASE + 100 + i);
        assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
    }
    cameras(cams, 3, BASE + 102);
    assert(pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130) == -ENOBUFS);
    terminal(-ENOBUFS);
    begin();
    pair(BASE + 80, BASE + 2000);
    pair(BASE + 1000, BASE + 2000);
    for (unsigned i = 0; i < 8; ++i) {
        cameras(cams, i + 1, BASE + 100 + i);
        assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 2000));
    }
    memset(pixels, 0xdd, sizeof(pixels));
    cameras(cams, 9, BASE + 108);
    assert(pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 2000) == -ENOBUFS);
    terminal(-ENOBUFS);
    verify_retained();
    begin();
    terminal(pico_vendor_slam_feed_poll(feed, generation, BASE + 200000001));
    begin();
    pair(BASE + 100, BASE + 130);
    terminal(pico_vendor_slam_feed_poll(feed, generation, BASE + 100000096));
    begin();
    assert(!pico_vendor_slam_feed_poll(feed, generation, BASE + 100));
    terminal(pico_vendor_slam_feed_poll(feed, generation, BASE + 99));
    begin();
    cameras(cams, 1, BASE + 100);
    assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
    cameras(cams, 2, BASE + 50000000);
    assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 50000030));
    terminal(pico_vendor_slam_feed_poll(feed, generation, BASE + 100000098));
    begin();
    cameras(cams, 1, BASE + 100);
    assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 130));
    assert(!push(0, BASE + 110, BASE + 130));
    terminal(push(1, BASE + 110, BASE + 130));
    release();

    memset(&backend, 0, sizeof(backend));
    ++generation;
    c = config();
    c.image = copy_image;
    c.image_lifetime = PICO_VENDOR_SLAM_COPY_ON_RETURN;
    c.retained_sets = c.pending_sets = 2;
    assert(!pico_vendor_slam_feed_create(&c, BASE, &feed));
    for (unsigned cycle = 0; cycle < 500; ++cycle) {
        int64_t t = BASE + 10000 * cycle;
        pair(t + 80, t + 300);
        for (unsigned j = 0; j < 2; ++j) {
            cameras(cams, 2 * cycle + j + 1, t + 100 + 100 * j);
            assert(!pico_vendor_slam_feed_camera(feed, generation, cams, t + 300));
            memset(pixels, 0xaa, sizeof(pixels));
        }
        pico_vendor_slam_feed_status(feed, &status);
        assert(status.pending_sets == 2 && status.retained_sets == 2);
        assert(status.image_sets == 2 * cycle);
        pair(t + 220, t + 300);
        pico_vendor_slam_feed_status(feed, &status);
        assert(!status.pending_sets && !status.retained_sets && !status.error);
        assert(status.image_sets == 2 * cycle + 2 && backend.sets == 2 * cycle + 2);
        for (unsigned i = 0; i < 4; ++i) for (unsigned y = 0; y < 480; ++y)
            for (unsigned x = 0; x < 640; ++x)
                assert(copied_pixels[i][y * 640 + x] == 20 * i + (y ? y : 1) % 17);
    }
    cameras(cams, 1001, BASE + 5000100);
    assert(!pico_vendor_slam_feed_camera(feed, generation, cams, BASE + 5000300));
    pico_vendor_slam_feed_status(feed, &status);
    assert(status.pending_sets == 1 && status.retained_sets == 1);
    release();

    memset(&backend, 0, sizeof(backend));
    ++generation;
    c = config();
    assert(!pico_vendor_slam_feed_create(&c, INT64_MAX - 1000, &feed));
    cameras(cams, 1, INT64_MAX - 100);
    assert(!pico_vendor_slam_feed_camera(feed, generation, cams, INT64_MAX));
    pair(INT64_MAX - 150, INT64_MAX);
    pair(INT64_MAX - 50, INT64_MAX);
    assert(backend.sets == 1);
    release();
    printf("PICO_VENDOR_SLAM_FEED_PASS cycles=100 faults=%u\n", faults);
    puts("PICO_VENDOR_SLAM_COPY_PASS delivered=1000 retained_limit=2 pending_on_stop=1");
    return 0;
}
