#ifndef REFRAMED_PICO_PIPE_NOTIFY_H
#define REFRAMED_PICO_PIPE_NOTIFY_H

#ifdef __cplusplus
extern "C" {
#endif

/* Cross-process wake hint for a bounded queue. Keep both pipe ends nonblocking
 * and owned until publishers and the single reader stop. Publish queue data
 * before signalling; drain the queue after every wake. Hints may coalesce. */
int pico_pipe_notify_signal(int fd);
/* 1 = notified, 0 = timeout/interruption, negative errno = failure. */
int pico_pipe_notify_wait(int fd, int timeout_ms);

#ifdef __cplusplus
}
#endif

#endif
