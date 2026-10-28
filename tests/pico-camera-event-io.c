#include "pico-camera-control.h"
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>

static unsigned calls, failure;
static uint32_t event_id;
static bool enabled;
static int poll_result, poll_error;
static short poll_events[2];
#ifdef __linux__
#define poll __wrap_poll
#endif
int poll(struct pollfd *sources, nfds_t count, int timeout_ms)
{
    assert(count == 2 && sources[0].fd == 31 && sources[1].fd == 32 && timeout_ms == 2);
    assert(sources[0].events == POLLPRI && sources[1].events == POLLPRI);
    assert(!sources[0].revents && !sources[1].revents);
    sources[0].revents = poll_events[0];sources[1].revents = poll_events[1];
    errno = poll_error;return poll_result;
}
int ioctl(int fd, unsigned long request, ...)
{
    va_list args; va_start(args, request); uint8_t *data = va_arg(args, void *); va_end(args);
    assert(fd == 31); ++calls;
    if (request == 0x80885659UL) {
        for (unsigned i = 0; i < 136; ++i) assert(!data[i]);
        memset(data, 0xa5, 136);
        uint32_t type = 0x08000000, pending = 17, sequence = UINT32_MAX;
        memcpy(data, &type, 4); memcpy(data + 72, &pending, 4);
        memcpy(data + 76, &sequence, 4); memcpy(data + 96, &event_id, 4);
        for (unsigned i = 0; i < 64; ++i) data[8 + i] = (uint8_t)i;
    } else {
        assert(request == (enabled ? 0x4020565aUL : 0x4020565bUL));
        uint32_t words[8]; memcpy(words, data, sizeof(words));
        assert(words[0] == 0x08000000 && words[1] == event_id);
        for (unsigned i = 2; i < 8; ++i) assert(!words[i]);
    }
    if (failure) { errno = failure; return -1; }
    return 0;
}
int main(void)
{
    for (event_id = 0; event_id < 2; ++event_id) {
        enabled = true; assert(!pico_camera_event_subscribe(31, event_id, true));
        struct pico_camera_event event = {0};
        assert(!pico_camera_event_dequeue(31, &event));
        assert(event.type == 0x08000000 && event.id == event_id && event.sequence == UINT32_MAX && event.pending == 17);
        for (unsigned i = 0; i < 64; ++i) assert(event.data[i] == i);
        enabled = false; assert(!pico_camera_event_subscribe(31, event_id, false));
    }
    event_id = 0; struct pico_camera_event event, original;
    memset(&event, 0x5a, sizeof(event)); original = event;
    const unsigned failures[] = {EAGAIN, ENOENT, EINTR, EIO};
    for (unsigned i = 0; i < sizeof(failures) / sizeof(failures[0]); ++i) {
        failure = failures[i];
        unsigned before = calls;
        int expected = failure == ENOENT ? -EAGAIN : -(int)failure;
        assert(pico_camera_event_dequeue(31, &event) == expected);
        assert(calls == before + 1 && !memcmp(&event, &original, sizeof(event)));
    }
    failure = ENOENT;
    enabled = true;
    assert(pico_camera_event_subscribe(31, event_id, true) == -ENOENT);
    failure = 0;
    unsigned before = calls;
    assert(pico_camera_event_subscribe(31, 2, true) == -EINVAL);
    assert(pico_camera_event_subscribe(-1, 0, true) == -EINVAL);
    assert(pico_camera_event_dequeue(-1, &event) == -EINVAL);
    assert(pico_camera_event_dequeue(31, NULL) == -EINVAL);
    assert(calls == before);
    assert(pico_camera_event_wait(31, 32, 2) == 0);
    poll_result = -1;poll_error = EINTR;assert(pico_camera_event_wait(31, 32, 2) == 0);
    poll_error = ENOMEM;assert(pico_camera_event_wait(31, 32, 2) == -ENOMEM);
    poll_result = 1;poll_events[0] = POLLPRI;assert(pico_camera_event_wait(31, 32, 2) == 1);
    poll_events[0] = 0;poll_events[1] = POLLPRI;assert(pico_camera_event_wait(31, 32, 2) == 1);
    poll_result = 2;poll_events[0] = POLLPRI;assert(pico_camera_event_wait(31, 32, 2) == 1);
    poll_events[1] = POLLNVAL;assert(pico_camera_event_wait(31, 32, 2) == -EBADF);
    poll_events[1] = POLLERR;assert(pico_camera_event_wait(31, 32, 2) == -EIO);
    poll_events[1] = POLLHUP;assert(pico_camera_event_wait(31, 32, 2) == -EIO);
    poll_events[0] = 0;poll_events[1] = POLLIN;assert(pico_camera_event_wait(31, 32, 2) == -EIO);
    assert(pico_camera_event_wait(-1, 32, 2) == -EINVAL);
    assert(pico_camera_event_wait(31, -1, 2) == -EINVAL);
    assert(pico_camera_event_wait(31, 31, 2) == -EINVAL);
    assert(pico_camera_event_wait(31, 32, -1) == -EINVAL);
    assert(pico_camera_event_wait(31, 32, 1001) == -EINVAL);
    printf("PICO_CAMERA_EVENT_IO_PASS calls=%u hardware=0\n", calls); return 0;
}
