#ifndef REFRAMED_PICO_STATION_PROTOCOL_H
#define REFRAMED_PICO_STATION_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PICO_STATION_FRAME_SIZE 40

/* Neo3 b1977 station protocol only. These encoders perform no device I/O.
 * Camera zero addresses all four; 1..4 selects one. Output covers 40 bytes;
 * invalid arguments preserve it. Streaming requires a separate owner with
 * bounded shutdown handling. */
bool pico_station_camera_initialize(unsigned camera, bool raw8, uint8_t *output);
bool pico_station_camera_stream(unsigned camera, bool enabled, uint8_t *output);
/* The two stock pacing modes are wire values, not measured frame rates. */
bool pico_station_camera_pacing(unsigned mode, uint8_t *output);
bool pico_station_camera_status(bool failure_counters, uint8_t *output);
bool pico_station_camera_read_register(unsigned slave, unsigned address, uint8_t *output);
bool pico_station_version(uint8_t *output);
bool pico_station_acknowledge(uint16_t sequence, uint8_t *output);

/* Validate one complete fixed-size station response before interpreting it.
 * Longer announced messages require a separate bounded parser. */
bool pico_station_response_valid(const void *frame, size_t size);

#endif
