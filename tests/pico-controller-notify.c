#define _POSIX_C_SOURCE 200809L
#include "pico-controller-notify.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>

static int notification;
static _Atomic unsigned published;

static void *produce(void *unused)
{
    (void)unused;
    for (unsigned i = 1; i <= 10000; ++i) {
        atomic_store_explicit(&published, i, memory_order_release);
        assert(!pico_controller_notify_signal(notification));
    }
    return NULL;
}

int main(void)
{
    alarm(15);
    notification = pico_controller_notify_open();
    assert(notification >= 0);
    assert(fcntl(notification, F_GETFL) & O_NONBLOCK);
    assert(fcntl(notification, F_GETFD) & FD_CLOEXEC);
    assert(pico_controller_notify_wait(notification, 0) == 0);
    assert(pico_controller_notify_wait(notification, 1) == 0);
    assert(!pico_controller_notify_signal(notification));
    assert(!pico_controller_notify_signal(notification));
    assert(pico_controller_notify_wait(notification, 0) == 1);
    assert(pico_controller_notify_wait(notification, 0) == 0);

    uint64_t full = UINT64_MAX - 1;
    assert(write(notification, &full, sizeof(full)) == sizeof(full));
    assert(!pico_controller_notify_signal(notification));
    assert(pico_controller_notify_wait(notification, 0) == 1);
    assert(pico_controller_notify_wait(notification, 0) == 0);

    pthread_t writer;
    assert(!pthread_create(&writer, NULL, produce, NULL));
    unsigned last = 0;
    while (last < 10000) {
        assert(pico_controller_notify_wait(notification, 1000) >= 0);
        unsigned current = atomic_load_explicit(&published, memory_order_acquire);
        assert(current >= last && current <= 10000);
        last = current;
    }
    assert(!pthread_join(writer, NULL));
    assert(pico_controller_notify_wait(notification, 0) >= 0);
    assert(pico_controller_notify_wait(notification, 0) == 0);
    assert(pico_controller_notify_wait(notification, -1) == -EINVAL);
    assert(pico_controller_notify_wait(notification, 1001) == -EINVAL);
    assert(pico_controller_notify_signal(-1) == -EINVAL);
    assert(pico_controller_notify_wait(-1, 1) == -EINVAL);
    assert(!close(notification));
    assert(pico_controller_notify_signal(notification) == -EBADF);
    assert(pico_controller_notify_wait(notification, 0) == -EBADF);
    puts("PICO_CONTROLLER_NOTIFY_PASS");
    return 0;
}
