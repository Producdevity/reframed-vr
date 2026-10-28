#include "pico-controller-notify.h"

#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <sys/eventfd.h>
#include <unistd.h>

int pico_controller_notify_open(void)
{
    int fd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    return fd < 0 ? -errno : fd;
}

int pico_controller_notify_signal(int fd)
{
    if (fd < 0) return -EINVAL;
    uint64_t value = 1;
    ssize_t count;
    do { count = write(fd, &value, sizeof(value)); } while (count < 0 && errno == EINTR);
    /* A full counter already guarantees a pending wake for the single reader. */
    if (count < 0) return errno == EAGAIN ? 0 : -errno;
    return count == sizeof(value) ? 0 : -EIO;
}

int pico_controller_notify_wait(int fd, int timeout_ms)
{
    if (fd < 0 || timeout_ms < 0 || timeout_ms > 1000) return -EINVAL;
    struct pollfd descriptor = {.fd = fd, .events = POLLIN};
    int ready = poll(&descriptor, 1, timeout_ms);
    if (ready < 0) return errno == EINTR ? 0 : -errno;
    if (!ready) return 0;
    if (descriptor.revents & POLLNVAL) return -EBADF;
    if (descriptor.revents & (POLLERR | POLLHUP)) return -EIO;
    if (!(descriptor.revents & POLLIN)) return -EIO;
    uint64_t value;
    ssize_t count = read(fd, &value, sizeof(value));
    if (count < 0) return errno == EAGAIN || errno == EINTR ? 0 : -errno;
    return count == sizeof(value) && value ? 1 : -EIO;
}
