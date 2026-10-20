#ifndef REFRAMED_PICO_SLAM_CHANNEL_H
#define REFRAMED_PICO_SLAM_CHANNEL_H

#include "pico-slam-pose.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PICO_SLAM_CHANNEL_WORDS 12

struct pico_slam_channel {
    uint64_t magic, version, bytes, instance, sequence;
    uint64_t words[PICO_SLAM_CHANNEL_WORDS];
};

struct pico_slam_channel_sample {
    struct pico_slam_pose pose;
    uint64_t generation;
    int64_t timestamp_ns, uncertainty_ns, published_ns;
};

/* Initialize only a new, exclusively owned mapping before sharing it. The
 * process owner serializes one writer; all payload accesses are atomic so
 * concurrent readers never race ordinary floating-point memory accesses.
 * Readers bind to one instance/generation and make at most four attempts.
 * Starting another generation requires quiescing the previous estimator. */
bool pico_slam_channel_init(struct pico_slam_channel *channel, uint64_t instance);
bool pico_slam_channel_begin(struct pico_slam_channel *channel, uint64_t generation);
bool pico_slam_channel_publish(struct pico_slam_channel *channel,
                               const struct pico_slam_channel_sample *sample);
enum pico_slam_channel_result {
    PICO_SLAM_CHANNEL_REFUSED = -1,
    PICO_SLAM_CHANNEL_WAITING,
    PICO_SLAM_CHANNEL_PUBLISHED,
};
/* Initial nontracking results remain waiting. Once a pose has been published,
 * confidence loss or any failed conversion stops the generation; the owner
 * must establish its world frame again before starting a new generation. */
enum pico_slam_channel_result pico_slam_channel_publish_result(
    struct pico_slam_channel *channel, uint64_t generation,
    const struct pico_slam_pose_config *config, const struct pico_slam_result *result,
    int64_t uncertainty_ns, int64_t now_ns);
/* Confidence loss clears the current pose; a later valid sample may recover.
 * Stop is terminal for this generation. Late old-generation calls do no work.
 * A malformed/regressing current-generation publish stops that generation. */
bool pico_slam_channel_invalidate(struct pico_slam_channel *channel, uint64_t generation);
bool pico_slam_channel_stop(struct pico_slam_channel *channel, uint64_t generation);
bool pico_slam_channel_read(const struct pico_slam_channel *channel,
                            uint64_t instance, uint64_t generation,
                            int64_t now_ns, int64_t max_age_ns,
                            struct pico_slam_channel_sample *sample);

#ifdef __cplusplus
}
#endif
#endif
