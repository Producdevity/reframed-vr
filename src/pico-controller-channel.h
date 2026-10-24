#ifndef REFRAMED_PICO_CONTROLLER_CHANNEL_H
#define REFRAMED_PICO_CONTROLLER_CHANNEL_H

#include "pico-controller.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_controller_channel {
    uint64_t magic, instance, sequence[2];
    uint64_t slots[2][2][3];
};

/* One producer owns a fresh mapping for its lifetime. A new producer needs a
 * new instance and file; receipt time is host CLOCK_MONOTONIC, not MCU time. */
bool pico_controller_channel_init(struct pico_controller_channel *channel, uint64_t instance);
bool pico_controller_channel_publish(struct pico_controller_channel *channel,
                                     const struct pico_controller_sample *sample, int64_t received_ns);
bool pico_controller_channel_read(const struct pico_controller_channel *channel,
                                  uint64_t instance, unsigned hand,
                                  int64_t (*clock_ns)(void *), void *clock_data,
                                  int64_t max_age_ns, struct pico_controller_sample *sample);
bool pico_controller_channel_disconnect(struct pico_controller_channel *channel, unsigned hand);

#ifdef __cplusplus
}
#endif
#endif
