#ifndef REFRAMED_PICO_CONTROLLER_NOTIFY_H
#define REFRAMED_PICO_CONTROLLER_NOTIFY_H

#ifdef __cplusplus
extern "C" {
#endif

/* Linux notification for one queue consumer. Publish queue data before signal;
 * drain the queue after waking. Notifications may coalesce. Keep the descriptor
 * nonblocking and close it only after producer callbacks and the consumer stop. */
int pico_controller_notify_open(void);
int pico_controller_notify_signal(int fd);
/* 1 = notified, 0 = timeout/interruption, negative errno = failure. */
int pico_controller_notify_wait(int fd, int timeout_ms);

#ifdef __cplusplus
}
#endif

#endif
