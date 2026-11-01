#include "pico-controller-pose.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define INSTANCE UINT64_C(0x4c1d6e7f2a3b4c5d)
#define GENERATION 104
#define HALF 0.70710678118654757

static void number(uint8_t *bytes, double value) { memcpy(bytes, &value, 8); }

/* Values returned by the unchanged b1977 getter for the synthetic five-LED
 * control in output/pico-controller-result-frame-20261101-v1/. */
static void tracked(uint8_t raw[PICO_SLAM_RESULT_SIZE], int64_t timestamp)
{
    memset(raw, 0, PICO_SLAM_RESULT_SIZE);
    memcpy(raw, &timestamp, 8);
    number(raw + 8, -219.470084); number(raw + 16, -58.872435); number(raw + 24, -265.285403);
    double norm = sqrt(0.471654 * 0.471654 + 0.039954 * 0.039954 +
                       0.880232 * 0.880232 + 0.033739 * 0.033739);
    number(raw + 32, 0.471654 / norm); number(raw + 40, 0.039954 / norm);
    number(raw + 48, 0.880232 / norm); number(raw + 56, -0.033739 / norm);
    raw[0x40] = 1; raw[0x41] = 1; raw[0x52] = 1;
}

static bool read(const struct pico_slam_channel *channel, int64_t now,
                 struct pico_slam_channel_sample *sample)
{
    return pico_slam_channel_read(channel, INSTANCE, GENERATION, now, 100000000, sample);
}

int main(void)
{
    struct pico_controller_pose_config config = {
        .world_from_slam = {.orientation = {0, 0, HALF, HALF}},
        .tracker_from_model = {.orientation = {0, 0, -HALF, HALF}},
        .max_age_ns = 100000000};
    struct pico_slam_channel channel;
    struct pico_controller_pose_output output;
    assert(pico_slam_channel_init(&channel, INSTANCE));
    assert(!pico_controller_pose_begin(&output, &channel, 0, &config));
    struct pico_controller_pose_config bad = config;
    bad.tracker_from_model.orientation[3] = 0;
    assert(!pico_controller_pose_begin(&output, &channel, GENERATION, &bad));
    assert(pico_controller_pose_begin(&output, &channel, GENERATION, &config));

    uint8_t raw[PICO_SLAM_RESULT_SIZE];
    struct pico_slam_channel_sample sample;
    int64_t t = 5000000000;

    tracked(raw, t);
    raw[0x40] = 0;
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 2000000) ==
           PICO_CONTROLLER_POSE_LOST);
    assert(!read(&channel, t + 2000000, &sample));

    tracked(raw, t);
    raw[0x52] = 0; /* public confidence alone is synthesized by the getter */
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 2000000) ==
           PICO_CONTROLLER_POSE_LOST);
    assert(!read(&channel, t + 2000000, &sample));

    tracked(raw, t);
    memset(raw, 0xff, 8);
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 2000000) ==
           PICO_CONTROLLER_POSE_LOST);

    tracked(raw, t);
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 2000000) ==
           PICO_CONTROLLER_POSE_PUBLISHED);
    assert(read(&channel, t + 2000000, &sample));
    assert(sample.timestamp_ns == t && sample.generation == GENERATION);
    /* World and controller axes take the head's +90 degree Z basis change. */
    assert(fabs(sample.pose.position[0] - 0.058872435) < 1e-9);
    assert(fabs(sample.pose.position[1] + 0.219470084) < 1e-9);
    assert(fabs(sample.pose.position[2] + 0.265285403) < 1e-9);
    double w = sample.pose.orientation[3] < 0 ? -1 : 1;
    double norm = sqrt(0.471654 * 0.471654 + 0.039954 * 0.039954 +
                       0.880232 * 0.880232 + 0.033739 * 0.033739);
    assert(fabs(w * sample.pose.orientation[0] + 0.880232 / norm) < 1e-9);
    assert(fabs(w * sample.pose.orientation[1] - 0.039954 / norm) < 1e-9);
    assert(fabs(w * sample.pose.orientation[2] + 0.033739 / norm) < 1e-9);
    assert(fabs(w * sample.pose.orientation[3] - 0.471654 / norm) < 1e-9);

    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 3000000) ==
           PICO_CONTROLLER_POSE_UNCHANGED);
    assert(read(&channel, t + 3000000, &sample) && sample.timestamp_ns == t);

    tracked(raw, t + 2000000);
    raw[0x40] = 0;
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 4000000) ==
           PICO_CONTROLLER_POSE_LOST);
    assert(!read(&channel, t + 4000000, &sample));

    tracked(raw, t + 4000000);
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 205000000) ==
           PICO_CONTROLLER_POSE_LOST);
    assert(!read(&channel, t + 205000000, &sample));

    tracked(raw, t + 210000000);
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 211000000) ==
           PICO_CONTROLLER_POSE_PUBLISHED);
    assert(read(&channel, t + 211000000, &sample) && sample.timestamp_ns == t + 210000000);
    assert(!read(&channel, t + 320000000, &sample));

    assert(pico_controller_pose_publish(&output, raw, sizeof(raw) - 1, 1000, t + 212000000) ==
           PICO_CONTROLLER_POSE_REFUSED);
    assert(pico_controller_pose_publish(NULL, raw, sizeof(raw), 1000, t + 212000000) ==
           PICO_CONTROLLER_POSE_REFUSED);

    pico_controller_pose_stop(&output);
    tracked(raw, t + 220000000);
    assert(pico_controller_pose_publish(&output, raw, sizeof(raw), 1000, t + 221000000) ==
           PICO_CONTROLLER_POSE_REFUSED);
    assert(!read(&channel, t + 221000000, &sample));
    puts("PICO_CONTROLLER_POSE_PASS");
}
