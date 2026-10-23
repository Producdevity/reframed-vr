#include "pico-vendor-slam-output.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>

struct pico_vendor_slam_output {
    pthread_mutex_t mutex;
    struct pico_vendor_slam_output_config config;
    struct pico_vendor_slam_output_status status;
    int64_t last_now, last_result;
};

static bool config_valid(const struct pico_vendor_slam_output_config *c)
{
    if (!c || !c->channel || !c->generation || !c->handle || !c->get_result || !c->monotonic_ns ||
        c->uncertainty_ns < 0 || c->uncertainty_ns > 500000000) return false;
    struct pico_slam_result result = {.timestamp_ns = 1000000000, .state = 1, .confidence = 1};
    result.orientation[3] = 1;
    struct pico_slam_pose pose;
    return pico_slam_pose_convert(&c->pose, &result, c->uncertainty_ns,
                                  result.timestamp_ns + c->uncertainty_ns, &pose);
}

int pico_vendor_slam_output_create(const struct pico_vendor_slam_output_config *config,
                                   struct pico_vendor_slam_output **output)
{
    if (!output || *output || !config_valid(config)) return -EINVAL;
    struct pico_vendor_slam_output *o = calloc(1, sizeof(*o));
    if (!o) return -ENOMEM;
    int rc = pthread_mutex_init(&o->mutex, NULL);
    if (rc) { free(o); return -rc; }
    if (!pico_slam_channel_begin(config->channel, config->generation)) {
        pthread_mutex_destroy(&o->mutex);
        free(o);
        return -EINVAL;
    }
    o->config = *config;
    *output = o;
    return 0;
}

enum pico_slam_channel_result pico_vendor_slam_output_callback(struct pico_vendor_slam_output *o)
{
    if (!o) return PICO_SLAM_CHANNEL_REFUSED;
    pthread_mutex_lock(&o->mutex);
    enum pico_slam_channel_result rc = PICO_SLAM_CHANNEL_REFUSED;
    if (o->status.stopped) goto done;
    ++o->status.callbacks;
    uint8_t bytes[PICO_SLAM_RESULT_SIZE] = {0};
    struct pico_slam_result result;
    if (o->config.get_result(o->config.handle, bytes) ||
        !pico_slam_result_decode(bytes, sizeof(bytes), &result)) goto fail;
    int64_t now = o->config.monotonic_ns(o->config.clock_data);
    if (now <= 0 || now < o->last_now || result.timestamp_ns < o->last_result) goto fail;
    o->last_now = now;
    o->last_result = result.timestamp_ns;
    rc = pico_slam_channel_publish_result(o->config.channel, o->config.generation,
                                         &o->config.pose, &result, o->config.uncertainty_ns, now);
    if (rc == PICO_SLAM_CHANNEL_REFUSED) goto fail;
    if (rc == PICO_SLAM_CHANNEL_PUBLISHED) ++o->status.published;
    else ++o->status.waiting;
    goto done;
fail:
    o->status.failed = o->status.stopped = true;
    pico_slam_channel_stop(o->config.channel, o->config.generation);
done:
    pthread_mutex_unlock(&o->mutex);
    return rc;
}

void pico_vendor_slam_output_status(struct pico_vendor_slam_output *o,
                                    struct pico_vendor_slam_output_status *status)
{
    if (!o || !status) return;
    pthread_mutex_lock(&o->mutex);
    *status = o->status;
    pthread_mutex_unlock(&o->mutex);
}

void pico_vendor_slam_output_stop(struct pico_vendor_slam_output *o)
{
    if (!o) return;
    pthread_mutex_lock(&o->mutex);
    o->status.stopped = true;
    pico_slam_channel_stop(o->config.channel, o->config.generation);
    pthread_mutex_unlock(&o->mutex);
}

int pico_vendor_slam_output_release(struct pico_vendor_slam_output **output)
{
    if (!output || !*output) return -EINVAL;
    struct pico_vendor_slam_output *o = *output;
    if (!o->status.stopped) return -EBUSY;
    int rc = pthread_mutex_destroy(&o->mutex);
    if (rc) return -rc;
    free(o);
    *output = NULL;
    return 0;
}
