#define _POSIX_C_SOURCE 200809L
#include "pico-controller-acquisition.h"
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static uint8_t pixels[4][PICO_CONTROLLER_ACQUISITION_PIXELS];
static uint8_t before[PICO_SLAM_RESULT_SIZE], after[PICO_SLAM_RESULT_SIZE];
static double values[9];

static void head(uint8_t *p, uint64_t timestamp)
{
    memset(p, 0, PICO_SLAM_RESULT_SIZE);
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(timestamp >> (8 * i));
    p[38] = 0xf0; p[39] = 0x3f;
    p[64] = p[65] = 1;
}

static void heads(uint64_t timestamp) { head(before, timestamp - 1); head(after, timestamp + 1); }

static void frames(struct pico_controller_acquisition_frame result[4])
{
    for (unsigned i = 0; i < 4; ++i)
        result[i] = (struct pico_controller_acquisition_frame){
            .sof_ns = 210, .number = 12, .exposure = 1, .gain = 1, .pixels = pixels[i]};
}

static struct pico_controller_acquisition *create(FILE *m, FILE *i, unsigned mc, unsigned ic)
{
    struct pico_controller_acquisition_config cfg = {m, i, 7, mc, ic};
    struct pico_controller_acquisition *r = NULL;
    assert(!pico_controller_acquisition_create(&cfg, &r) && r);
    return r;
}

static void motion(struct pico_controller_acquisition *r, unsigned hand, int64_t timestamp)
{
    heads((uint64_t)timestamp);
    assert(!pico_controller_acquisition_motion(r, 7, hand, timestamp, values, before, after));
}

static void image(struct pico_controller_acquisition *r)
{
    struct pico_controller_acquisition_frame f[4]; frames(f); heads(200);
    assert(!pico_controller_acquisition_images(r, 7, 200, f, before, after));
}

static void capacities(void)
{
    FILE *m = tmpfile(), *i = tmpfile(); assert(m && i);
    struct pico_controller_acquisition *r = create(m, i, 2, 2);
    motion(r, 1, 100); motion(r, 2, 100);
    struct pico_controller_acquisition_status s;
    pico_controller_acquisition_status(r, &s);
    assert(s.stopped && s.reason == PICO_CONTROLLER_ACQUISITION_MOTION_FULL && !s.error);
    assert(s.dispatch_order == 2 && s.motion_records[0] == 1 && s.motion_records[1] == 1);
    assert(pico_controller_acquisition_images(r, 7, 200, NULL, NULL, NULL) == 1);
    assert(!pico_controller_acquisition_finish(r) && ftell(m) == 32 + 2 * 840 && ftell(i) == 32);
    pico_controller_acquisition_destroy(r); assert(!fclose(m) && !fclose(i));

    m = tmpfile(); i = tmpfile(); assert(m && i); r = create(m, i, 8, 1); image(r);
    pico_controller_acquisition_status(r, &s);
    assert(s.reason == PICO_CONTROLLER_ACQUISITION_IMAGES_FULL && s.dispatch_order == 1);
    assert(pico_controller_acquisition_motion(r, 8, 1, 300, values, before, after) == 1);
    assert(!pico_controller_acquisition_finish(r) && ftell(m) == 32 && ftell(i) == 32 + 1229816);
    pico_controller_acquisition_destroy(r); assert(!fclose(m) && !fclose(i));
}

static void invalid_inputs(void)
{
    for (unsigned fault = 0; fault < 14; ++fault) {
        FILE *m = tmpfile(), *i = tmpfile(); assert(m && i);
        struct pico_controller_acquisition *r = create(m, i, 8, 2);
        motion(r, 1, 100); heads(200);
        struct pico_controller_acquisition_frame f[4]; frames(f);
        uint64_t generation = fault == 0 ? 8 : 7;
        int rc;
        if (fault < 7) {
            unsigned hand = fault == 1 ? 0 : fault == 2 ? 3 : 1;
            int64_t timestamp = fault == 3 ? 100 : 200;
            if (fault == 4) values[0] = NAN;
            if (fault == 5) before[65] = 0;
            if (fault == 6) before[39] = 0;
            rc = pico_controller_acquisition_motion(r, generation, hand, timestamp,
                                                     values, before, after);
            values[0] = 0;
        } else {
            if (fault == 7) f[3].pixels = NULL;
            if (fault == 8) f[2].exposure = 0;
            if (fault == 9) f[2].exposure = 4096;
            if (fault == 10) f[1].gain = 256;
            if (fault == 11) f[0].sof_ns = 199;
            if (fault == 12) f[3].number = 13;
            if (fault == 13) after[0] = 0;
            rc = pico_controller_acquisition_images(r, 7, 200, f, before, after);
        }
        assert(rc < 0);
        struct pico_controller_acquisition_status s; pico_controller_acquisition_status(r, &s);
        assert(s.stopped && s.error == rc && s.reason == PICO_CONTROLLER_ACQUISITION_INVALID);
        assert(s.dispatch_order == 1 && ftell(m) == 32 + 840 && ftell(i) == 32);
        assert(pico_controller_acquisition_images(r, 7, 200, f, before, after) == rc);
        assert(pico_controller_acquisition_finish(r) == rc);
        pico_controller_acquisition_destroy(r); assert(!fclose(m) && !fclose(i));
    }
}

static void lifecycle(void)
{
    FILE *m = tmpfile(), *i = tmpfile(); assert(m && i);
    struct pico_controller_acquisition *r = NULL;
    struct pico_controller_acquisition_config cfg = {m, i, 7, 8, 2};
    for (unsigned fault = 0; fault < 6; ++fault) {
        struct pico_controller_acquisition_config bad = cfg;
        if (fault == 0) bad.generation = 0;
        if (fault == 1) bad.motion = NULL;
        if (fault == 2) bad.images = m;
        if (fault == 3) bad.motion_capacity = 0;
        if (fault == 4) bad.motion_capacity = 16385;
        if (fault == 5) bad.image_capacity = 151;
        assert(pico_controller_acquisition_create(&bad, &r) == -EINVAL && !r);
    }
    assert(!pico_controller_acquisition_create(&cfg, &r));
    assert(pico_controller_acquisition_create(&cfg, &r) == -EINVAL);
    motion(r, 1, 100);
    pico_controller_acquisition_stop(r, PICO_CONTROLLER_ACQUISITION_RESET);
    assert(pico_controller_acquisition_motion(r, 8, 2, 200, values, before, after) == 1);
    assert(!pico_controller_acquisition_finish(r) && !pico_controller_acquisition_finish(r));
    struct pico_controller_acquisition_status s; pico_controller_acquisition_status(r, &s);
    assert(s.reason == PICO_CONTROLLER_ACQUISITION_RESET && s.dispatch_order == 1);
    pico_controller_acquisition_destroy(r);
    assert(fputc(0, m) != EOF && fputc(0, i) != EOF);
    assert(!fclose(m) && !fclose(i));

    m = tmpfile(); i = tmpfile(); assert(m && i); r = create(m, i, 8, 2); motion(r, 1, 100);
    FILE *readonly = fopen(__FILE__, "rb"); assert(readonly);
    assert(dup2(fileno(readonly), fileno(m)) >= 0); assert(!fclose(readonly));
    assert(pico_controller_acquisition_finish(r) < 0);
    pico_controller_acquisition_status(r, &s); assert(s.error < 0 && s.reason == PICO_CONTROLLER_ACQUISITION_IO);
    assert(pico_controller_acquisition_motion(r, 7, 1, 200, values, before, after) == s.error);
    pico_controller_acquisition_destroy(r); fclose(m); assert(!fclose(i));

    m = tmpfile(); readonly = fopen(__FILE__, "rb"); assert(m && readonly); r = NULL;
    cfg.motion = m; cfg.images = readonly;
    assert(pico_controller_acquisition_create(&cfg, &r) < 0 && !r);
    fclose(m); fclose(readonly);
}

int main(int argc, char **argv)
{
    assert(argc == 1 || argc == 3);
    for (unsigned i = 0; i < 4; ++i) memset(pixels[i], (int)i + 1, sizeof(pixels[i]));
    capacities(); invalid_inputs(); lifecycle();
    if (argc == 3) {
        FILE *m = fopen(argv[1], "wbx"), *i = fopen(argv[2], "wbx"); assert(m && i);
        struct pico_controller_acquisition *r = create(m, i, 8, 2);
        motion(r, 1, 300); motion(r, 2, 100); image(r); motion(r, 1, 400); motion(r, 2, 200);
        assert(!pico_controller_acquisition_finish(r));
        pico_controller_acquisition_destroy(r); assert(!fclose(m) && !fclose(i));
    }
    puts("PICO_CONTROLLER_ACQUISITION_PASS"); return 0;
}
