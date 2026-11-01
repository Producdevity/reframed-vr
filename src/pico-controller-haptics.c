#define _POSIX_C_SOURCE 200809L
#include "pico-controller-haptics.h"
#include "pico-station-protocol.h"
#include <errno.h>
#include <math.h>
#include <signal.h>
#include <unistd.h>

#define MAGIC 0x48
#define VERSION 1

_Static_assert(sizeof(struct pico_controller_haptic) == 8, "Haptic request layout changed");

bool pico_controller_haptic_from_openvr(unsigned hand, float duration_s, float amplitude,
                                        struct pico_controller_haptic *request)
{
    if (!request || hand < 1 || hand > 2 || !isfinite(duration_s) || !isfinite(amplitude) ||
        duration_s < 0 || amplitude < 0) return false;
    float level = amplitude > 1 ? 255.f : roundf(amplitude * 255.f);
    float ms = roundf(duration_s * 1000.f);
    if (ms < PICO_CONTROLLER_HAPTIC_MIN_MS) ms = PICO_CONTROLLER_HAPTIC_MIN_MS;
    if (ms > PICO_CONTROLLER_HAPTIC_MAX_MS) ms = PICO_CONTROLLER_HAPTIC_MAX_MS;
    *request = (struct pico_controller_haptic){.magic = MAGIC, .version = VERSION,
        .hand = (uint8_t)hand, .level = (uint8_t)level, .duration_ms = (uint16_t)ms};
    return true;
}

bool pico_controller_haptic_valid(const struct pico_controller_haptic *r)
{
    return r && r->magic == MAGIC && r->version == VERSION && r->hand >= 1 && r->hand <= 2 &&
        r->duration_ms >= PICO_CONTROLLER_HAPTIC_MIN_MS &&
        r->duration_ms <= PICO_CONTROLLER_HAPTIC_MAX_MS && !r->reserved;
}

bool pico_controller_haptic_frame(const struct pico_controller_haptic *r, unsigned scale_percent,
                                  uint8_t frame[40])
{
    return pico_controller_haptic_valid(r) &&
        pico_station_controller_motor(r->hand, r->level, scale_percent, r->duration_ms, frame);
}

int pico_controller_haptic_send(int fd, const struct pico_controller_haptic *r)
{
    if (fd < 0 || !pico_controller_haptic_valid(r)) return -EINVAL;
    /* A departed reader must not deliver SIGPIPE to the hosting runtime. */
    sigset_t pipe_set, previous, pending;
    sigemptyset(&pipe_set);
    sigaddset(&pipe_set, SIGPIPE);
    if (pthread_sigmask(SIG_BLOCK, &pipe_set, &previous)) return -EINVAL;
    sigpending(&pending);
    bool already = sigismember(&pending, SIGPIPE);
    ssize_t written = write(fd, r, sizeof(*r));
    int error = written < 0 ? errno : 0;
    if (error == EPIPE && !already && !sigpending(&pending) && sigismember(&pending, SIGPIPE)) {
        int signal;
        sigwait(&pipe_set, &signal);
    }
    pthread_sigmask(SIG_SETMASK, &previous, NULL);
    if (written == (ssize_t)sizeof(*r)) return 0;
    return written < 0 ? -error : -EIO;
}

int pico_controller_haptic_forward(int fifo_fd, int mcu_fd, unsigned scale_percent,
                                   unsigned max_requests, unsigned *rejected)
{
    if (fifo_fd < 0 || mcu_fd < 0 || scale_percent > 100) return -EINVAL;
    int written = 0;
    for (unsigned i = 0; i < max_requests; ++i) {
        struct pico_controller_haptic request;
        ssize_t count = read(fifo_fd, &request, sizeof(request));
        if (count < 0) return errno == EAGAIN ? written : -errno;
        if (!count) break;
        uint8_t frame[40];
        if (count != (ssize_t)sizeof(request) ||
            !pico_controller_haptic_frame(&request, scale_percent, frame)) {
            if (rejected) ++*rejected;
            continue;
        }
        ssize_t sent = write(mcu_fd, frame, sizeof(frame));
        if (sent != (ssize_t)sizeof(frame)) return sent < 0 ? -errno : -EIO;
        ++written;
    }
    return written;
}
