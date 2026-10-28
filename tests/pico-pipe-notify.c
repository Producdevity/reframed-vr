#define _GNU_SOURCE
#include "pico-pipe-notify.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

enum { CAPACITY = 128, RECORDS = 20000 };
struct queue {
    _Atomic unsigned written, read;
    unsigned values[CAPACITY];
};

int main(void)
{
    alarm(15);
    int ends[2];
    assert(!pipe2(ends, O_NONBLOCK | O_CLOEXEC));
    assert(pico_pipe_notify_wait(ends[0], 0) == 0);
    assert(!pico_pipe_notify_signal(ends[1]));
    assert(pico_pipe_notify_wait(ends[0], 0) == 1);
    assert(pico_pipe_notify_wait(ends[0], 1) == 0);
    assert(pico_pipe_notify_wait(-1, 0) == -EINVAL);
    assert(pico_pipe_notify_wait(ends[0], -1) == -EINVAL);
    assert(pico_pipe_notify_wait(ends[0], 1001) == -EINVAL);
    assert(pico_pipe_notify_signal(-1) == -EINVAL);
    assert(pico_pipe_notify_signal(ends[0]) == -EBADF);
    unsigned char bytes[4096] = {0};
    while (write(ends[1], bytes, sizeof(bytes)) > 0) {}
    assert(errno == EAGAIN);
    assert(!pico_pipe_notify_signal(ends[1]));
    while (pico_pipe_notify_wait(ends[0], 0) == 1) {}
    close(ends[1]);
    assert(pico_pipe_notify_wait(ends[0], 0) == -EPIPE);
    int closed = ends[0];
    close(ends[0]);
    assert(pico_pipe_notify_wait(closed, 0) == -EBADF);
    assert(pico_pipe_notify_signal(closed) == -EBADF);

    char path[] = "/tmp/pico-pipe-notify-XXXXXX";
    int temporary = mkstemp(path);
    assert(temporary >= 0);
    close(temporary);
    assert(!unlink(path) && !mkfifo(path, 0600));
    int owner = open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);
    assert(owner >= 0);
    struct queue *q = mmap(NULL, sizeof(*q), PROT_READ | PROT_WRITE,
                           MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    assert(q != MAP_FAILED);
    atomic_init(&q->written, 0);
    atomic_init(&q->read, 0);
    assert(atomic_is_lock_free(&q->written) && atomic_is_lock_free(&q->read));
    /* Publication between an empty queue check and wait must remain readable. */
    assert(atomic_load_explicit(&q->written, memory_order_acquire) == 0);
    pid_t publisher = fork();
    assert(publisher >= 0);
    if (!publisher) {
        int fd = open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
        assert(fd >= 0);
        q->values[0] = 73;
        atomic_store_explicit(&q->written, 1, memory_order_release);
        assert(!pico_pipe_notify_signal(fd));
        close(fd);
        _exit(0);
    }
    int status;
    assert(waitpid(publisher, &status, 0) == publisher && WIFEXITED(status) && !WEXITSTATUS(status));
    int reader = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    assert(reader >= 0 && pico_pipe_notify_wait(reader, 0) == 1);
    assert(atomic_load_explicit(&q->written, memory_order_acquire) == 1 && q->values[0] == 73);
    atomic_store(&q->written, 0);
    close(reader);
    pid_t child = fork();
    assert(child >= 0);
    if (!child) {
        int fd = open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
        assert(fd >= 0);
        for (unsigned i = 0; i < RECORDS; ++i) {
            while (i - atomic_load_explicit(&q->read, memory_order_acquire) >= CAPACITY)
                sched_yield();
            q->values[i % CAPACITY] = i;
            atomic_store_explicit(&q->written, i + 1, memory_order_release);
            assert(!pico_pipe_notify_signal(fd));
        }
        close(fd);
        _exit(0);
    }
    reader = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    assert(reader >= 0);
    unsigned read = 0;
    while (read < RECORDS) {
        unsigned written = atomic_load_explicit(&q->written, memory_order_acquire);
        while (read < written) {
            assert(q->values[read % CAPACITY] == read);
            ++read;
            atomic_store_explicit(&q->read, read, memory_order_release);
        }
        if (read < RECORDS) assert(pico_pipe_notify_wait(reader, 1000) >= 0);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(atomic_load(&q->written) == RECORDS && atomic_load(&q->read) == RECORDS);
    close(reader);
    close(owner);
    assert(!unlink(path) && !munmap(q, sizeof(*q)));
    puts("Pico cross-process pipe notification checks passed");
    return 0;
}
