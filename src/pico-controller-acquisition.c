#include "pico-controller-acquisition.h"

#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(double) == 8, "Acquisition requires binary64");

struct pico_controller_acquisition {
    struct pico_controller_acquisition_config config;
    struct pico_controller_acquisition_status status;
    int64_t last_motion[2], last_image;
};

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8 * i));
}

static void put64(uint8_t *p, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(value >> (8 * i));
}

static uint64_t get64(const uint8_t *p)
{
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= (uint64_t)p[i] << (8 * i);
    return value;
}

static double number(const uint8_t *p)
{
    uint64_t bits = get64(p);
    double value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static bool bracket(int64_t timestamp, const uint8_t *before, const uint8_t *after)
{
    if (!before || !after || timestamp <= 0 || !get64(before) ||
            get64(before) >= (uint64_t)timestamp || get64(after) <= (uint64_t)timestamp ||
            get64(after) > INT64_MAX) return false;
    const uint8_t *poses[2] = {before, after};
    for (unsigned i = 0; i < 2; ++i) {
        const uint8_t *p = poses[i];
        if (p[64] != 1 || p[65] != 1) return false;
        for (unsigned j = 0; j < 3; ++j)
            if (!isfinite(number(p + 8 + 8 * j))) return false;
        double norm = 0;
        for (unsigned j = 0; j < 4; ++j) {
            double value = number(p + 32 + 8 * j);
            if (!isfinite(value)) return false;
            norm += value * value;
        }
        if (!isfinite(norm) || fabs(norm - 1) > .0001) return false;
    }
    return true;
}

static int fail(struct pico_controller_acquisition *r, int error,
                enum pico_controller_acquisition_stop_reason reason)
{
    if (!r->status.error) { r->status.error = error; r->status.reason = reason; }
    r->status.stopped = true;
    return r->status.error;
}

static int write_bytes(struct pico_controller_acquisition *r, FILE *stream,
                       const void *data, size_t size)
{
    errno = 0;
    if (fwrite(data, 1, size, stream) != size)
        return fail(r, errno ? -errno : -EIO, PICO_CONTROLLER_ACQUISITION_IO);
    return 0;
}

static int ready(struct pico_controller_acquisition *r, uint64_t generation)
{
    if (!r) return -EINVAL;
    if (r->status.stopped) return r->status.error ? r->status.error : 1;
    if (generation != r->status.generation)
        return fail(r, -ESTALE, PICO_CONTROLLER_ACQUISITION_INVALID);
    return 0;
}

static void prefix(uint8_t *p, int64_t timestamp, const struct pico_controller_acquisition *r)
{
    put64(p, (uint64_t)timestamp);
    put64(p + 8, r->status.generation);
    put64(p + 16, r->status.dispatch_order + 1);
}

int pico_controller_acquisition_create(const struct pico_controller_acquisition_config *cfg,
                                      struct pico_controller_acquisition **recorder)
{
    if (!cfg || !recorder || *recorder || !cfg->motion || !cfg->images ||
            cfg->motion == cfg->images || !cfg->generation || !cfg->motion_capacity ||
            cfg->motion_capacity > PICO_CONTROLLER_ACQUISITION_MOTION_LIMIT ||
            !cfg->image_capacity || cfg->image_capacity > PICO_CONTROLLER_ACQUISITION_IMAGE_LIMIT)
        return -EINVAL;
    struct pico_controller_acquisition *r = calloc(1, sizeof(*r));
    if (!r) return -ENOMEM;
    r->config = *cfg;
    r->status.generation = cfg->generation;
    uint8_t header[32];
    put64(header, UINT64_C(0x52564354494d0001)); put64(header + 8, 3);
    put64(header + 16, 840); put64(header + 24, cfg->motion_capacity);
    int rc = write_bytes(r, cfg->motion, header, sizeof(header));
    if (!rc) {
        put64(header, UINT64_C(0x5256435443410002));
        put64(header + 16, 1229816); put64(header + 24, cfg->image_capacity);
        rc = write_bytes(r, cfg->images, header, sizeof(header));
    }
    if (rc) { free(r); return rc; }
    *recorder = r;
    return 0;
}

int pico_controller_acquisition_motion(struct pico_controller_acquisition *r,
    uint64_t generation, unsigned hand, int64_t timestamp, const double values[9],
    const uint8_t before[PICO_SLAM_RESULT_SIZE], const uint8_t after[PICO_SLAM_RESULT_SIZE])
{
    int rc = ready(r, generation);
    if (rc) return rc;
    if (hand < 1 || hand > 2 || !values || timestamp <= r->last_motion[hand - 1] ||
            !bracket(timestamp, before, after))
        return fail(r, -EINVAL, PICO_CONTROLLER_ACQUISITION_INVALID);
    uint8_t meta[32] = {0}, encoded[72];
    prefix(meta, timestamp, r); put32(meta + 24, hand);
    for (unsigned i = 0; i < 9; ++i) {
        if (!isfinite(values[i])) return fail(r, -EINVAL, PICO_CONTROLLER_ACQUISITION_INVALID);
        uint64_t bits;
        memcpy(&bits, values + i, sizeof(bits)); put64(encoded + 8 * i, bits);
    }
    if ((rc = write_bytes(r, r->config.motion, meta, sizeof(meta))) ||
            (rc = write_bytes(r, r->config.motion, encoded, sizeof(encoded))) ||
            (rc = write_bytes(r, r->config.motion, before, PICO_SLAM_RESULT_SIZE)) ||
            (rc = write_bytes(r, r->config.motion, after, PICO_SLAM_RESULT_SIZE))) return rc;
    ++r->status.dispatch_order; ++r->status.motion_records[hand - 1];
    r->last_motion[hand - 1] = timestamp;
    if (r->status.motion_records[0] + r->status.motion_records[1] == r->config.motion_capacity) {
        r->status.stopped = true; r->status.reason = PICO_CONTROLLER_ACQUISITION_MOTION_FULL;
    }
    return 0;
}

int pico_controller_acquisition_images(struct pico_controller_acquisition *r,
    uint64_t generation, int64_t timestamp,
    const struct pico_controller_acquisition_frame frames[4],
    const uint8_t before[PICO_SLAM_RESULT_SIZE], const uint8_t after[PICO_SLAM_RESULT_SIZE])
{
    int rc = ready(r, generation);
    if (rc) return rc;
    if (!frames || timestamp <= r->last_image || !bracket(timestamp, before, after))
        return fail(r, -EINVAL, PICO_CONTROLLER_ACQUISITION_INVALID);
    for (unsigned i = 0; i < 4; ++i)
        if (!frames[i].pixels || frames[i].sof_ns < timestamp || !frames[i].exposure ||
                frames[i].exposure > 4095 || !frames[i].gain || frames[i].gain > 255 ||
                frames[i].number != frames[0].number)
            return fail(r, -EINVAL, PICO_CONTROLLER_ACQUISITION_INVALID);
    uint8_t meta[24]; prefix(meta, timestamp, r);
    if ((rc = write_bytes(r, r->config.images, meta, sizeof(meta))) ||
            (rc = write_bytes(r, r->config.images, before, PICO_SLAM_RESULT_SIZE)) ||
            (rc = write_bytes(r, r->config.images, after, PICO_SLAM_RESULT_SIZE))) return rc;
    for (unsigned i = 0; i < 4; ++i) {
        uint8_t header[64] = {0};
        put32(header, i); put32(header + 4, 640); put32(header + 8, 480);
        put32(header + 12, 0x123); put32(header + 20, frames[i].exposure);
        put32(header + 24, frames[i].gain); put64(header + 32, (uint64_t)frames[i].sof_ns);
        put64(header + 40, (uint64_t)timestamp); put64(header + 48, frames[i].number);
        put32(header + 56, PICO_CONTROLLER_ACQUISITION_PIXELS);
        if ((rc = write_bytes(r, r->config.images, header, sizeof(header))) ||
                (rc = write_bytes(r, r->config.images, frames[i].pixels,
                                  PICO_CONTROLLER_ACQUISITION_PIXELS))) return rc;
    }
    ++r->status.dispatch_order; ++r->status.image_sets; r->last_image = timestamp;
    if (r->status.image_sets == r->config.image_capacity) {
        r->status.stopped = true; r->status.reason = PICO_CONTROLLER_ACQUISITION_IMAGES_FULL;
    }
    return 0;
}

void pico_controller_acquisition_stop(struct pico_controller_acquisition *r,
                                     enum pico_controller_acquisition_stop_reason reason)
{
    if (!r || r->status.stopped) return;
    if (reason != PICO_CONTROLLER_ACQUISITION_RESET && reason != PICO_CONTROLLER_ACQUISITION_DURATION &&
            reason != PICO_CONTROLLER_ACQUISITION_SDK_STOP && reason != PICO_CONTROLLER_ACQUISITION_FINISHED) {
        fail(r, -EINVAL, PICO_CONTROLLER_ACQUISITION_INVALID);
        return;
    }
    r->status.stopped = true; r->status.reason = reason;
}

int pico_controller_acquisition_finish(struct pico_controller_acquisition *r)
{
    if (!r) return -EINVAL;
    FILE *streams[2] = {r->config.motion, r->config.images};
    for (unsigned i = 0; i < 2; ++i) {
        errno = 0;
        if (fflush(streams[i])) fail(r, errno ? -errno : -EIO, PICO_CONTROLLER_ACQUISITION_IO);
    }
    pico_controller_acquisition_stop(r, PICO_CONTROLLER_ACQUISITION_FINISHED);
    return r->status.error;
}

void pico_controller_acquisition_status(const struct pico_controller_acquisition *r,
                                       struct pico_controller_acquisition_status *status)
{
    if (r && status) *status = r->status;
}

void pico_controller_acquisition_destroy(struct pico_controller_acquisition *r) { free(r); }
