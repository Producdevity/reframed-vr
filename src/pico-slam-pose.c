#include "pico-slam-pose.h"
#include <math.h>
#include <string.h>

static bool normalized(struct pico_slam_pose *pose)
{
    double norm = 0;
    for (unsigned i = 0; i < 4; ++i) {
        if (!isfinite(pose->orientation[i])) return false;
        norm += pose->orientation[i] * pose->orientation[i];
    }
    if (!isfinite(norm) || fabs(norm - 1) > 0.0001) return false;
    for (unsigned i = 0; i < 3; ++i)
        if (!isfinite(pose->position[i]) || fabs(pose->position[i]) > 1000000) return false;
    norm = sqrt(norm);
    for (unsigned i = 0; i < 4; ++i) pose->orientation[i] /= norm;
    return true;
}

static void rotate(const double q[4], const double p[3], double result[3])
{
    const double cross[3] = {q[1]*p[2] - q[2]*p[1], q[2]*p[0] - q[0]*p[2], q[0]*p[1] - q[1]*p[0]};
    const double twice_cross[3] = {q[1]*cross[2] - q[2]*cross[1],
                                  q[2]*cross[0] - q[0]*cross[2], q[0]*cross[1] - q[1]*cross[0]};
    for (unsigned i = 0; i < 3; ++i) result[i] = p[i] + 2 * (q[3]*cross[i] + twice_cross[i]);
}

static struct pico_slam_pose compose(const struct pico_slam_pose *a, const struct pico_slam_pose *b)
{
    const double *q = a->orientation, *r = b->orientation;
    struct pico_slam_pose result = {.orientation = {
        q[3]*r[0] + q[0]*r[3] + q[1]*r[2] - q[2]*r[1],
        q[3]*r[1] - q[0]*r[2] + q[1]*r[3] + q[2]*r[0],
        q[3]*r[2] + q[0]*r[1] - q[1]*r[0] + q[2]*r[3],
        q[3]*r[3] - q[0]*r[0] - q[1]*r[1] - q[2]*r[2]}};
    rotate(q, b->position, result.position);
    for (unsigned i = 0; i < 3; ++i) result.position[i] += a->position[i];
    return result;
}

bool pico_slam_pose_convert(const struct pico_slam_pose_config *config,
                            const struct pico_slam_result *result,
                            int64_t uncertainty, int64_t now,
                            struct pico_slam_pose *world_from_head)
{
    if (!config || !result || !world_from_head ||
        (config->direction != PICO_SLAM_WORLD_FROM_BODY && config->direction != PICO_SLAM_BODY_FROM_WORLD) ||
        !isfinite(config->metres_per_unit) || config->metres_per_unit <= 0 || config->metres_per_unit > 1000000 ||
        config->max_age_ns <= 0 || config->max_age_ns > 1000000000 ||
        result->state != 1 || result->confidence != 1 || result->timestamp_ns <= 0 ||
        now < result->timestamp_ns || uncertainty < 0 || uncertainty > config->max_age_ns) return false;
    int64_t age = now - result->timestamp_ns;
    if (age < uncertainty || age > config->max_age_ns - uncertainty) return false;
    struct pico_slam_pose world = config->world_from_slam, head = config->body_from_head;
    struct pico_slam_pose body;
    memcpy(body.orientation, result->orientation, sizeof(body.orientation));
    for (unsigned i = 0; i < 3; ++i) body.position[i] = result->position[i] * config->metres_per_unit;
    if (!normalized(&world) || !normalized(&head) || !normalized(&body)) return false;
    if (config->direction == PICO_SLAM_BODY_FROM_WORLD) {
        double inverse_position[3];
        for (unsigned i = 0; i < 3; ++i) {
            body.orientation[i] = -body.orientation[i];
            inverse_position[i] = -body.position[i];
        }
        rotate(body.orientation, inverse_position, body.position);
    }
    struct pico_slam_pose world_body = compose(&world, &body);
    struct pico_slam_pose output = compose(&world_body, &head);
    if (!normalized(&output)) return false;
    *world_from_head = output;
    return true;
}
