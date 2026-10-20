#ifndef REFRAMED_PICO_VENDOR_SLAM_FEED_H
#define REFRAMED_PICO_VENDOR_SLAM_FEED_H
#include "ssc-imu.h"
#include <stddef.h>

#define PICO_VENDOR_SLAM_CAMERAS 4
#define PICO_VENDOR_SLAM_WIDTH 640
#define PICO_VENDOR_SLAM_HEIGHT 480

/* b1977 updateImage/update6AxisIMU ABI; not the Pico4 pixel-format contract. */
struct pico_vendor_slam_vector {
    const void *begin, *end, *capacity;
};
struct pico_vendor_slam_image {
    uint8_t camera, padding[3];
    uint32_t width, height, format, type, exposure, gain, reserved;
    int64_t sof_ns, center_ns;
    uint64_t number;
    uint32_t size, reserved2;
    const uint8_t *pixels;
};

struct pico_vendor_slam_camera {
    unsigned calibration_id, classification, exposure, gain;
    uint64_t number;
    int64_t sof_ns, center_ns, uncertainty_ns;
    const uint8_t *pixels;
    size_t size, stride;
};
struct pico_vendor_slam_feed_config {
    uint64_t generation;
    int64_t max_age_ns, max_imu_gap_ns, max_camera_gap_ns;
    int64_t max_camera_skew_ns, startup_timeout_ns;
    unsigned retained_sets, pending_sets;
    void *handle;
    void (*imu)(void *handle, const struct pico_vendor_slam_vector *samples, int64_t timestamp_ns);
    void (*image)(void *handle, int kind, const struct pico_vendor_slam_vector *images);
};
struct pico_vendor_slam_feed_status {
    int error;
    uint64_t imu_pairs, image_sets, unmatched[2];
    unsigned retained_sets, pending_sets;
};
struct pico_vendor_slam_feed;

/* Serialized owner for an already-started, separately isolated vendor backend.
 * No hardware, files, threads, transforms, bias correction or pose publication.
 * Feed raw SSC events from the verified physical IMU in its stock axes/units.
 * Pairs require equal ticks AND times; the seventh value is raw accel.fourth.
 * Accuracy zero is preserved: factory processing belongs to this backend.
 * Every current-generation failure is terminal; stale generations do no work.
 * All timestamps/now use CLOCK_MONOTONIC. Call poll even when inputs are silent. */
int pico_vendor_slam_feed_create(const struct pico_vendor_slam_feed_config *config,
                                int64_t now_ns, struct pico_vendor_slam_feed **feed);
int pico_vendor_slam_feed_imu(struct pico_vendor_slam_feed *feed,
                             const struct ssc_imu_event *sample, int64_t now_ns);
/* Complete synchronized head sets only, four distinct caller-verified camera
 * calibration IDs 0..3. Copies padded RAW8 rows, replacing metadata row 0 with
 * row 1 as stock does. Uses the minimum corrected center for the whole set.
 * Each center's clock uncertainty interval must be bracketed by delivered IMU.
 * A set older than the first IMU's upper bound fails with ENODATA.
 * Caller supplies measured clock/center corrections; no timing defaults. */
int pico_vendor_slam_feed_camera(struct pico_vendor_slam_feed *feed, uint64_t generation,
                                const struct pico_vendor_slam_camera cameras[4], int64_t now_ns);
int pico_vendor_slam_feed_poll(struct pico_vendor_slam_feed *feed, uint64_t generation, int64_t now_ns);
void pico_vendor_slam_feed_status(const struct pico_vendor_slam_feed *feed,
                                 struct pico_vendor_slam_feed_status *status);
/* Invalidates input, but retains all image pixels AND vector metadata. The
 * vendor consumes them asynchronously; no completion/reuse contract is proven.
 * At most 384 retained sets and 8 pending sets; exhaustion stops the feed. */
void pico_vendor_slam_feed_stop(struct pico_vendor_slam_feed *feed);
/* Stop input, then stop/destroy the vendor handle and join its readers first.
 * Refuses a running feed; caller is responsible for backend quiescence. */
int pico_vendor_slam_feed_release(struct pico_vendor_slam_feed **feed);
#endif
