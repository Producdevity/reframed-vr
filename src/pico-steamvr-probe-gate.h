#ifndef REFRAMED_PICO_STEAMVR_PROBE_GATE_H
#define REFRAMED_PICO_STEAMVR_PROBE_GATE_H

// Optional diagnostic barrier before timing/pose sampling; returns an errno.
int pico_steamvr_probe_gate(const char *path, unsigned timeout_ms = 5000);

#endif
