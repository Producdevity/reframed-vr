#include <assert.h>
#include <errno.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>

static unsigned calls;
static int request_error;
static int modeled_sched_setscheduler(pid_t pid, int policy, const struct sched_param *param)
{
    assert(pid == 0 && policy == (SCHED_RR | SCHED_RESET_ON_FORK));
    assert(param && param->sched_priority == 2);
    ++calls;
    if (!request_error) return 0;
    errno = request_error;
    return -1;
}

#define sched_setscheduler modeled_sched_setscheduler
#include "display-event-under-test.h"
#undef sched_setscheduler

int main(void)
{
    assert(unsetenv("MESA_VK_WSI_DISPLAY_EVENT_RT") == 0);
    errno = E2BIG;
    assert(wsi_display_event_priority() == 0 && calls == 0 && errno == E2BIG);
    const char *invalid[] = {"", "0", "2", "true", "1 ", " 1", "01", "-1"};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(*invalid); ++i) {
        assert(setenv("MESA_VK_WSI_DISPLAY_EVENT_RT", invalid[i], 1) == 0);
        assert(wsi_display_event_priority() == 0 && calls == 0 && errno == E2BIG);
    }
    assert(setenv("MESA_VK_WSI_DISPLAY_EVENT_RT", "1", 1) == 0);
    assert(wsi_display_event_priority() == 0 && calls == 1 && errno == E2BIG);
    request_error = EPERM;
    assert(wsi_display_event_priority() == EPERM && calls == 2 && errno == E2BIG);
    request_error = EINVAL;
    assert(wsi_display_event_priority() == EINVAL && calls == 3 && errno == E2BIG);
    return 0;
}
