#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include "util/cnd_monotonic.h"

#define wsi_display_debug(...) ((void)0)
static int injected_result;
static int injected_wait(struct u_cnd_monotonic *cond, mtx_t *mutex,
                         const struct timespec *deadline)
{
   (void)cond;
   (void)mutex;
   (void)deadline;
   return injected_result;
}

#include "display-timeout-under-test.h"

static unsigned checks, failures;
#define CHECK(condition) do { \
   checks++; \
   if (!(condition)) { \
      if (failures < 5) fprintf(stderr, "check failed at line %u: %s\n", (unsigned)__LINE__, #condition); \
      failures++; \
   } \
} while (0)

static uint64_t monotonic_ns(void)
{
   struct timespec now;
   if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
   return (uint64_t)now.tv_sec * UINT64_C(1000000000) + now.tv_nsec;
}

struct signal_context {
   struct u_cnd_monotonic *cond;
   mtx_t *mutex;
   bool ready;
};

static int signal_waiter(void *arg)
{
   struct signal_context *context = arg;
   if (mtx_lock(context->mutex) != thrd_success) return 1;
   context->ready = true;
   int result = u_cnd_monotonic_signal(context->cond);
   if (mtx_unlock(context->mutex) != thrd_success) return 2;
   return result == thrd_success ? 0 : 3;
}

int main(void)
{
   struct u_cnd_monotonic cond;
   mtx_t mutex;
   CHECK(u_cnd_monotonic_init(&cond) == thrd_success);
   CHECK(mtx_init(&mutex, mtx_plain) == thrd_success);
   if (failures) return 1;

   CHECK(mtx_lock(&mutex) == thrd_success);
   struct timespec expired = {0, 0};
   int actual_timeout = u_cnd_monotonic_timedwait(&cond, &mutex, &expired);
   CHECK(actual_timeout == thrd_timedout);
   CHECK(mtx_unlock(&mutex) == thrd_success);

   for (unsigned i = 0; i < 64; i++) {
      CHECK(mtx_lock(&mutex) == thrd_success);
      CHECK(cond_timedwait_ns(&cond, &mutex, i) == ETIMEDOUT);
      CHECK(mtx_unlock(&mutex) == thrd_success);
   }
   for (unsigned i = 0; i < 4; i++) {
      CHECK(mtx_lock(&mutex) == thrd_success);
      int result;
      do {
         result = cond_timedwait_ns(&cond, &mutex, monotonic_ns() + UINT64_C(1000000));
      } while (!result);
      CHECK(result == ETIMEDOUT);
      CHECK(mtx_unlock(&mutex) == thrd_success);
   }
   for (unsigned i = 0; i < 8; i++) {
      struct signal_context context = {&cond, &mutex, false};
      thrd_t thread;
      CHECK(mtx_lock(&mutex) == thrd_success);
      int created = thrd_create(&thread, signal_waiter, &context);
      CHECK(created == thrd_success);
      if (created != thrd_success) {
         CHECK(mtx_unlock(&mutex) == thrd_success);
         continue;
      }
      uint64_t deadline = monotonic_ns() + UINT64_C(1000000000);
      int result = 0;
      while (!context.ready && !result)
         result = cond_timedwait_ns(&cond, &mutex, deadline);
      CHECK(result == 0 && context.ready);
      CHECK(mtx_unlock(&mutex) == thrd_success);
      int thread_result = -1;
      CHECK(thrd_join(thread, &thread_result) == thrd_success && thread_result == 0);
   }

   injected_result = thrd_error;
   int result = injected_cond_timedwait_ns(&cond, &mutex, 0);
   CHECK(result != 0 && result != ETIMEDOUT);

   u_cnd_monotonic_destroy(&cond);
   mtx_destroy(&mutex);
   printf("WSI_DISPLAY_TIMEOUT_%s checks=%u failures=%u c11_timeout=%d errno_timeout=%d\n",
          failures ? "FAIL" : "PASS", checks, failures, actual_timeout, ETIMEDOUT);
   return failures ? 1 : 0;
}
