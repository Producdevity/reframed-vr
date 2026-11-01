#ifndef REFRAMED_PICO_CONTROLLER_HAPTICS_H
#define REFRAMED_PICO_CONTROLLER_HAPTICS_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* One vibration request from the SteamVR driver to the process that owns the
 * station SPI device. Eight bytes, written atomically to a FIFO. */
struct pico_controller_haptic {
    uint8_t magic, version, hand, level;
    uint16_t duration_ms, reserved;
};

#define PICO_CONTROLLER_HAPTIC_MAX_MS 5000
#define PICO_CONTROLLER_HAPTIC_MIN_MS 10
/* Stock StationService uses 75 when no controller motor level is configured. */
#define PICO_CONTROLLER_HAPTIC_STOCK_SCALE 75

/* OpenVR amplitude 0..1 maps to level 0..255; a zero-length pulse gets the
 * minimum duration. Non-finite or negative inputs are refused. */
bool pico_controller_haptic_from_openvr(unsigned hand, float duration_s, float amplitude,
                                        struct pico_controller_haptic *request);
bool pico_controller_haptic_valid(const struct pico_controller_haptic *request);
/* Encodes the stock station motor frame for a valid request. */
bool pico_controller_haptic_frame(const struct pico_controller_haptic *request, unsigned scale_percent,
                                  uint8_t frame[40]);
/* Nonblocking single write; returns 0, -EAGAIN when the reader is behind, or -errno. */
int pico_controller_haptic_send(int fd, const struct pico_controller_haptic *request);
/* Station owner side: drains up to max_requests queued requests without
 * blocking and writes one 40-byte motor frame per valid request to mcu_fd.
 * Malformed requests are counted in rejected. Returns frames written or -errno. */
int pico_controller_haptic_forward(int fifo_fd, int mcu_fd, unsigned scale_percent,
                                   unsigned max_requests, unsigned *rejected);

#ifdef __cplusplus
}
#endif
#endif
