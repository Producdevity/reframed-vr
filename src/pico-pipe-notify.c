#include "pico-pipe-notify.h"

#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <unistd.h>

int pico_pipe_notify_signal(int fd)
{
    if (fd < 0) return -EINVAL;
    uint8_t value = 1;
    ssize_t count;
    do { count = write(fd, &value, sizeof(value)); } while (count < 0 && errno == EINTR);
    /* A full pipe already contains a wake hint for the reader. */
    if (count < 0) return errno == EAGAIN ? 0 : -errno;
    return count == sizeof(value) ? 0 : -EIO;
}

int pico_pipe_notify_wait(int fd, int timeout_ms)
{
    if (fd < 0 || timeout_ms < 0 || timeout_ms > 1000) return -EINVAL;
    struct pollfd descriptor = {.fd = fd, .events = POLLIN};
    int ready = poll(&descriptor, 1, timeout_ms);
    if (ready < 0) return errno == EINTR ? 0 : -errno;
    if (!ready) return 0;
    if (descriptor.revents & POLLNVAL) return -EBADF;
    if (descriptor.revents & POLLIN) {
        uint8_t hints[4096];
        ssize_t count = read(fd, hints, sizeof(hints));
        if (count > 0) return 1;
        if (!count) return -EPIPE;
        return errno == EAGAIN || errno == EINTR ? 0 : -errno;
    }
    return descriptor.revents & POLLHUP ? -EPIPE : -EIO;
}
