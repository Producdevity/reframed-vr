#include "pico-controller-pose.h"
#include <string.h>

static struct pico_slam_pose_config slam_config(const struct pico_controller_pose_config *c)
{
    return (struct pico_slam_pose_config){.world_from_slam = c->world_from_slam,
        .body_from_head = c->tracker_from_model, .direction = PICO_SLAM_WORLD_FROM_BODY,
        .metres_per_unit = .001, .max_age_ns = c->max_age_ns};
}

bool pico_controller_pose_begin(struct pico_controller_pose_output *output,
                                struct pico_slam_channel *channel, uint64_t generation,
                                const struct pico_controller_pose_config *config)
{
    if (!output || !channel || !generation || !config) return false;
    struct pico_slam_pose_config check = slam_config(config);
    struct pico_slam_result identity = {.timestamp_ns = 1000000000, .state = 1, .confidence = 1};
    identity.orientation[3] = 1;
    struct pico_slam_pose pose;
    if (!pico_slam_pose_convert(&check, &identity, 0, identity.timestamp_ns, &pose) ||
        !pico_slam_channel_begin(channel, generation)) return false;
    *output = (struct pico_controller_pose_output){.channel = channel,
        .generation = generation, .config = *config};
    return true;
}

static enum pico_controller_pose_result lost(struct pico_controller_pose_output *o)
{
    if (o->tracked && !pico_slam_channel_invalidate(o->channel, o->generation))
        return PICO_CONTROLLER_POSE_REFUSED;
    o->tracked = false;
    return PICO_CONTROLLER_POSE_LOST;
}

enum pico_controller_pose_result pico_controller_pose_publish(
    struct pico_controller_pose_output *o, const void *raw, size_t size,
    int64_t uncertainty_ns, int64_t now_ns)
{
    if (!o || !o->channel || !raw || size != PICO_SLAM_RESULT_SIZE)
        return PICO_CONTROLLER_POSE_REFUSED;
    const uint8_t *bytes = raw;
    struct pico_slam_result result;
    if (bytes[0x40] != 1 || bytes[0x52] != 1 ||
        !pico_slam_result_decode(raw, size, &result)) return lost(o);
    if (result.timestamp_ns <= o->last_timestamp_ns) return PICO_CONTROLLER_POSE_UNCHANGED;
    result.confidence = 1;
    struct pico_slam_pose_config config = slam_config(&o->config);
    struct pico_slam_channel_sample sample = {.generation = o->generation,
        .timestamp_ns = result.timestamp_ns, .uncertainty_ns = uncertainty_ns,
        .published_ns = now_ns};
    if (!pico_slam_pose_convert(&config, &result, uncertainty_ns, now_ns, &sample.pose))
        return lost(o);
    if (!pico_slam_channel_publish(o->channel, &sample)) return PICO_CONTROLLER_POSE_REFUSED;
    o->last_timestamp_ns = result.timestamp_ns;
    o->tracked = true;
    return PICO_CONTROLLER_POSE_PUBLISHED;
}

void pico_controller_pose_stop(struct pico_controller_pose_output *o)
{
    if (o && o->channel) pico_slam_channel_stop(o->channel, o->generation);
}
