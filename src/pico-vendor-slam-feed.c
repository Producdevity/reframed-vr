#include "pico-vendor-slam-feed.h"
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(void *) == 8, "Vendor ABI requires 64-bit pointers");
_Static_assert(sizeof(struct pico_vendor_slam_vector) == 24, "Vendor vector ABI");
_Static_assert(sizeof(struct pico_vendor_slam_image) == 0x48, "Vendor frame ABI");
_Static_assert(offsetof(struct pico_vendor_slam_image, sof_ns) == 0x20, "Vendor frame time ABI");
_Static_assert(offsetof(struct pico_vendor_slam_image, pixels) == 0x40, "Vendor frame pixels ABI");

/* SSC can deliver matched accelerometer and gyroscope samples in separate bursts. */
#define IMU_CAPACITY 256
#define MAX_RETAINED 384
#define PIXELS (PICO_VENDOR_SLAM_WIDTH * PICO_VENDOR_SLAM_HEIGHT)

struct retained_set {
    struct pico_vendor_slam_image images[4];
    struct pico_vendor_slam_vector vector;
    int64_t coverage_ns, coverage_low_ns;
    struct ssc_timestamp time;
    uint8_t pixels[4][PIXELS];
};
struct pico_vendor_slam_feed {
    struct pico_vendor_slam_feed_config config;
    struct pico_vendor_slam_feed_status status;
    struct ssc_imu_event pending[2][IMU_CAPACITY];
    unsigned counts[2];
    uint64_t last_ticks[2], last_number;
    int64_t last_time[2], began_ns, now_ns, first_imu_upper_ns;
    struct ssc_timestamp paired, camera;
    struct retained_set *sets[MAX_RETAINED];
    struct retained_set *queued[8];
};

static int fail(struct pico_vendor_slam_feed *f, int error)
{
    if (!f->status.error) f->status.error = error;
    return f->status.error;
}

static bool fresh(struct ssc_timestamp t, int64_t now, int64_t age)
{
    return t.timestamp_ns > 0 && t.uncertainty_ns >= 0 &&
        t.uncertainty_ns <= t.timestamp_ns && t.uncertainty_ns <= age &&
        now >= t.timestamp_ns && now - t.timestamp_ns >= t.uncertainty_ns &&
        now - t.timestamp_ns <= age - t.uncertainty_ns;
}

static int check(struct pico_vendor_slam_feed *f, uint64_t generation, int64_t now)
{
    if (!f) return -EINVAL;
    if (generation != f->config.generation) return -ESTALE;
    if (f->status.error) return f->status.error;
    if (now <= 0 || now < f->now_ns) return fail(f, -ETIME);
    f->now_ns = now;
    struct ssc_timestamp times[] = {f->paired, f->camera};
    for (unsigned i = 0; i < 2; ++i) {
        if (times[i].timestamp_ns) {
            if (!fresh(times[i], now, f->config.max_age_ns)) return fail(f, -ETIMEDOUT);
        } else if (now - f->began_ns > f->config.startup_timeout_ns) {
            return fail(f, -ETIMEDOUT);
        }
    }
    return 0;
}

int pico_vendor_slam_feed_create(const struct pico_vendor_slam_feed_config *c,
                                int64_t now, struct pico_vendor_slam_feed **feed)
{
    if (!feed || *feed || !c || !c->generation || now <= 0 || !c->handle || !c->imu || !c->image ||
        c->max_age_ns <= 0 || c->max_age_ns > INT64_C(1000000000) ||
        c->max_imu_gap_ns <= 0 || c->max_imu_gap_ns > c->max_age_ns ||
        c->max_camera_gap_ns <= 0 || c->max_camera_gap_ns > c->max_age_ns ||
        c->max_camera_skew_ns < 0 || c->max_camera_skew_ns > c->max_camera_gap_ns ||
        c->startup_timeout_ns <= 0 || c->startup_timeout_ns > INT64_C(10000000000) ||
        !c->retained_sets || c->retained_sets > MAX_RETAINED ||
        (c->image_lifetime != PICO_VENDOR_SLAM_RETAIN_UNTIL_STOP &&
         c->image_lifetime != PICO_VENDOR_SLAM_COPY_ON_RETURN) ||
        !c->pending_sets || c->pending_sets > 8 || c->pending_sets > c->retained_sets) return -EINVAL;
    struct pico_vendor_slam_feed *f = calloc(1, sizeof(*f));
    if (!f) return -ENOMEM;
    f->config = *c;
    f->began_ns = f->now_ns = now;
    *feed = f;
    return 0;
}

static int deliver(struct pico_vendor_slam_feed *f, int64_t now)
{
    while (f->status.pending_sets) {
        struct retained_set *s = f->queued[0];
        if (!fresh(s->time, now, f->config.max_age_ns))
            return fail(f, -ETIMEDOUT);
        if (f->first_imu_upper_ns && s->coverage_low_ns < f->first_imu_upper_ns)
            return fail(f, -ENODATA);
        if (!f->paired.timestamp_ns ||
            s->coverage_ns > f->paired.timestamp_ns - f->paired.uncertainty_ns) break;
        f->config.image(f->config.handle, 0, &s->vector);
        if (f->config.image_lifetime == PICO_VENDOR_SLAM_COPY_ON_RETURN) {
            free(s);
            --f->status.retained_sets;
        }
        ++f->status.image_sets;
        --f->status.pending_sets;
        memmove(f->queued, f->queued + 1, f->status.pending_sets * sizeof(f->queued[0]));
    }
    return 0;
}

static void discard(struct pico_vendor_slam_feed *f, unsigned sensor)
{
    --f->counts[sensor];
    memmove(f->pending[sensor], f->pending[sensor] + 1,
            f->counts[sensor] * sizeof(f->pending[sensor][0]));
}

static int pair(struct pico_vendor_slam_feed *f, int64_t now)
{
    while (f->counts[0] && f->counts[1]) {
        const struct ssc_imu_event *a = &f->pending[0][0], *g = &f->pending[1][0];
        int64_t ta = a->time.timestamp_ns, tg = g->time.timestamp_ns;
        if (!fresh(a->time, now, f->config.max_age_ns) || !fresh(g->time, now, f->config.max_age_ns))
            return fail(f, -ETIMEDOUT);
        if (ta != tg) {
            if (a->ticks == g->ticks || (ta < tg) != (a->ticks < g->ticks)) return fail(f, -EPROTO);
            unsigned old = ta < tg ? 0 : 1;
            ++f->status.unmatched[old];
            discard(f, old);
            continue;
        }
        if (a->ticks != g->ticks || (f->paired.timestamp_ns &&
            ta - f->paired.timestamp_ns > f->config.max_imu_gap_ns)) return fail(f, -EPROTO);
        double values[7];
        for (unsigned i = 0; i < 3; ++i) {
            values[i] = g->vector.values[i];
            values[i + 3] = a->vector.values[i];
        }
        values[6] = a->vector.fourth;
        struct pico_vendor_slam_vector vector = {values, values + 7, values + 7};
        f->config.imu(f->config.handle, &vector, ta);
        f->paired = (struct ssc_timestamp){ta, a->time.uncertainty_ns > g->time.uncertainty_ns ?
            a->time.uncertainty_ns : g->time.uncertainty_ns};
        if (!f->status.imu_pairs) f->first_imu_upper_ns = ta + f->paired.uncertainty_ns;
        ++f->status.imu_pairs;
        discard(f, 0); discard(f, 1);
        int rc = deliver(f, now);
        if (rc) return rc;
    }
    return 0;
}

int pico_vendor_slam_feed_imu(struct pico_vendor_slam_feed *f,
                             const struct ssc_imu_event *s, int64_t now)
{
    if (!s) return f ? fail(f, -EINVAL) : -EINVAL;
    int rc = check(f, s->generation, now);
    if (rc) return rc;
    if ((s->sensor != SSC_IMU_ACCELERATION && s->sensor != SSC_IMU_GYROSCOPE) ||
        !s->ticks || s->vector.accuracy > 3 || !s->vector.has_fourth || !isfinite(s->vector.fourth) ||
        !fresh(s->time, now, f->config.max_age_ns)) return fail(f, -EINVAL);
    for (unsigned i = 0; i < 3; ++i) if (!isfinite(s->vector.values[i])) return fail(f, -EINVAL);
    unsigned i = s->sensor;
    if (s->ticks <= f->last_ticks[i] || s->time.timestamp_ns <= f->last_time[i] ||
        (f->last_time[i] && s->time.timestamp_ns - f->last_time[i] > f->config.max_imu_gap_ns))
        return fail(f, -EPROTO);
    if (f->counts[i] == IMU_CAPACITY) return fail(f, -ENOBUFS);
    f->pending[i][f->counts[i]++] = *s;
    f->last_ticks[i] = s->ticks;
    f->last_time[i] = s->time.timestamp_ns;
    return pair(f, now);
}

int pico_vendor_slam_feed_camera(struct pico_vendor_slam_feed *f, uint64_t generation,
                                const struct pico_vendor_slam_camera cameras[4], int64_t now)
{
    int rc = check(f, generation, now);
    if (rc) return rc;
    if (!cameras) return fail(f, -EINVAL);
    unsigned mask = 0;
    int64_t low = INT64_MAX, high = 0, coverage = 0, coverage_low = INT64_MAX, uncertainty = 0;
    for (unsigned i = 0; i < 4; ++i) {
        const struct pico_vendor_slam_camera *c = &cameras[i];
        if (c->calibration_id >= 4 || (mask & (1u << c->calibration_id)) || c->classification != 1 ||
            !c->number || c->number != cameras[0].number || !c->exposure || c->exposure > 4095 ||
            !c->gain || c->gain > 255 || c->sof_ns < c->center_ns || c->sof_ns > now ||
            !fresh((struct ssc_timestamp){c->center_ns, c->uncertainty_ns}, now, f->config.max_age_ns) ||
            !c->pixels || c->stride < PICO_VENDOR_SLAM_WIDTH ||
            c->stride > (SIZE_MAX - PICO_VENDOR_SLAM_WIDTH) / (PICO_VENDOR_SLAM_HEIGHT - 1) ||
            c->size < (PICO_VENDOR_SLAM_HEIGHT - 1) * c->stride + PICO_VENDOR_SLAM_WIDTH)
            return fail(f, -EINVAL);
        mask |= 1u << c->calibration_id;
        if (c->center_ns < low) low = c->center_ns;
        if (c->center_ns > high) high = c->center_ns;
        if (c->center_ns + c->uncertainty_ns > coverage) coverage = c->center_ns + c->uncertainty_ns;
        if (c->center_ns - c->uncertainty_ns < coverage_low) coverage_low = c->center_ns - c->uncertainty_ns;
        if (c->uncertainty_ns > uncertainty) uncertainty = c->uncertainty_ns;
    }
    if (high - low > f->config.max_camera_skew_ns ||
        (f->camera.timestamp_ns && (low <= f->camera.timestamp_ns || cameras[0].number <= f->last_number ||
         low - f->camera.timestamp_ns > f->config.max_camera_gap_ns))) return fail(f, -EPROTO);
    if (f->status.retained_sets == f->config.retained_sets ||
        f->status.pending_sets == f->config.pending_sets) return fail(f, -ENOBUFS);
    struct retained_set *s = calloc(1, sizeof(*s));
    if (!s) return fail(f, -ENOMEM);
    for (unsigned i = 0; i < 4; ++i) {
        const struct pico_vendor_slam_camera *c = &cameras[i];
        unsigned id = c->calibration_id;
        s->images[id] = (struct pico_vendor_slam_image){.camera = (uint8_t)id,
            .width = PICO_VENDOR_SLAM_WIDTH, .height = PICO_VENDOR_SLAM_HEIGHT,
            .format = 0x123, .type = 1, .exposure = c->exposure, .gain = c->gain,
            .sof_ns = c->sof_ns, .center_ns = low, .number = c->number,
            .size = PIXELS, .pixels = s->pixels[id]};
        for (unsigned y = 0; y < PICO_VENDOR_SLAM_HEIGHT; ++y)
            memcpy(s->pixels[id] + y * PICO_VENDOR_SLAM_WIDTH,
                    c->pixels + (y ? y : 1) * c->stride, PICO_VENDOR_SLAM_WIDTH);
    }
    s->vector = (struct pico_vendor_slam_vector){s->images, s->images + 4, s->images + 4};
    s->coverage_ns = coverage;
    s->coverage_low_ns = coverage_low;
    s->time = (struct ssc_timestamp){low, uncertainty};
    if (f->config.image_lifetime == PICO_VENDOR_SLAM_RETAIN_UNTIL_STOP)
        f->sets[f->status.retained_sets] = s;
    ++f->status.retained_sets;
    f->queued[f->status.pending_sets] = s;
    ++f->status.pending_sets;
    f->camera = (struct ssc_timestamp){low, uncertainty};
    f->last_number = cameras[0].number;
    return deliver(f, now);
}

int pico_vendor_slam_feed_poll(struct pico_vendor_slam_feed *f, uint64_t generation, int64_t now)
{
    int rc = check(f, generation, now);
    return rc ? rc : deliver(f, now);
}

void pico_vendor_slam_feed_status(const struct pico_vendor_slam_feed *f,
                                 struct pico_vendor_slam_feed_status *status)
{
    if (f && status) *status = f->status;
}

void pico_vendor_slam_feed_stop(struct pico_vendor_slam_feed *f)
{
    if (f) fail(f, -ECANCELED);
}

int pico_vendor_slam_feed_release(struct pico_vendor_slam_feed **feed)
{
    if (!feed || !*feed) return 0;
    struct pico_vendor_slam_feed *f = *feed;
    if (!f->status.error) return -EBUSY;
    if (f->config.image_lifetime == PICO_VENDOR_SLAM_COPY_ON_RETURN) {
        for (unsigned i = 0; i < f->status.pending_sets; ++i) free(f->queued[i]);
    } else {
        for (unsigned i = 0; i < f->status.retained_sets; ++i) free(f->sets[i]);
    }
    free(f);
    *feed = NULL;
    return 0;
}
