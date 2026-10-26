#ifndef REFRAMED_PICO_CONTROLLER_HEAD_H
#define REFRAMED_PICO_CONTROLLER_HEAD_H

#include "pico-slam-result.h"
#include "ssc-clock.h"

#ifdef __cplusplus
extern "C" {
#endif

struct pico_controller_head;

/* Serialized owner of 512 raw b1977 head results for the controller tracker.
 * Twenty consecutive tracked results are required after startup or tracking
 * loss. Match copies the last result before and first result after the input's
 * entire uncertainty interval. No identity fallback, interpolation, prediction,
 * image-type mutation or head extrinsic is applied. The vendor status field at
 * 0x44 remains opaque: tracked b1977 results also contain 0x200. All times are
 * monotonic. */
struct pico_controller_head *pico_controller_head_create(uint64_t generation,
    int64_t max_age_ns, int64_t max_gap_ns);

/* 1 = ready, 0 = waiting for tracked history, negative errno = refused.
 * Malformed/regressing current-generation input is terminal. Confidence loss
 * and a gap clear the history and may recover. A tracked duplicate is -EALREADY and
 * stale-generation calls leave the current history unchanged. */
int pico_controller_head_push(struct pico_controller_head *history, uint64_t generation,
    const void *raw, size_t size, int64_t uncertainty_ns, int64_t now_ns);

/* 0 on success; -EAGAIN if a bracketing pair is not yet available. Other
 * negative errno values reject invalid/old input or a stopped history.
 * Outputs are unchanged on refusal and must be two distinct 0x170-byte buffers. */
int pico_controller_head_match(struct pico_controller_head *history, uint64_t generation,
    struct ssc_timestamp input, int64_t now_ns,
    uint8_t before[PICO_SLAM_RESULT_SIZE], uint8_t after[PICO_SLAM_RESULT_SIZE]);

void pico_controller_head_stop(struct pico_controller_head *history);
void pico_controller_head_destroy(struct pico_controller_head *history);

#ifdef __cplusplus
}
#endif
#endif
