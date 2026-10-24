#ifndef REFRAMED_PICO_CONTROLLER_IMAGES_H
#define REFRAMED_PICO_CONTROLLER_IMAGES_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* b1977 ARM64 Bionic SDK only; preload before dlopen, configure before init.
 * The launcher must verify the full SDK SHA in profiles/pico-controller-images.json.
 * configure also checks the loaded ELF build ID before inspecting private ABI.
 * Use one SDK instance for the process lifetime; do not unload either library. */
int pico_controller_images_configure(void *sdk_handle);

/* Copies four tightly packed 640x480 RAW8 planes into a bounded four-set pool.
 * Replace each submitted frame's pixels with destination, then call the SDK's
 * public all-image entry. Input pixels may be recycled on successful return.
 * Sequence must increase. EAGAIN leaves the current lease and outputs unchanged;
 * drop/defer controller frames without blocking the head/compositor feed. */
int pico_controller_images_prepare(uint64_t sequence, const void *const source[4],
                                   size_t plane_bytes, const void *destination[4]);

/* 1 once SDK aliases own references AND its consumer callback has returned;
 * 0 while pending, negative on invalid input or terminal ownership failure.
 * Completion permits another submission; pool slots additionally wait for all
 * SDK matrix references to disappear. Stop input before stopping/joining SDK. */
int pico_controller_images_completed(uint64_t sequence);
uint64_t pico_controller_images_adoptions(void);

#ifdef __cplusplus
}
#endif
#endif
