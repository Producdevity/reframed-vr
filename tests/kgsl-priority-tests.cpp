#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>

#define MAX2(a, b) ((a) > (b) ? (a) : (b))
#define MIN2(a, b) ((a) < (b) ? (a) : (b))
#define DIV_ROUND_UP(a, b) (((a) + (b) - 1) / (b))
#define UNREACHABLE(message) __builtin_trap()
#define __user
#include "msm_kgsl.h"

enum VkQueueGlobalPriorityKHR {
    VK_QUEUE_GLOBAL_PRIORITY_LOW_KHR = 128,
    VK_QUEUE_GLOBAL_PRIORITY_MEDIUM_KHR = 256,
    VK_QUEUE_GLOBAL_PRIORITY_HIGH_KHR = 512,
    VK_QUEUE_GLOBAL_PRIORITY_REALTIME_KHR = 1024,
};
enum tu_queue_type { TU_QUEUE_GRAPHICS, TU_QUEUE_SPARSE };
struct VkQueueFamilyGlobalPriorityPropertiesKHR {
    uint32_t priorityCount;
    VkQueueGlobalPriorityKHR priorities[16];
};
struct tu_physical_device { int local_fd; uint32_t submitqueue_priority_count; };
struct tu_device { tu_physical_device *physical_device; };
struct tu_queue { uint32_t priority, msm_queue_id; int kgsl_completion_fd; };

static unsigned calls, seen_flags;
static int ioctl_result;

static int safe_ioctl(int fd, unsigned long request, void *argument)
{
    assert(fd == 19 && request == IOCTL_KGSL_DRAWCTXT_CREATE);
    auto *context = static_cast<kgsl_drawctxt_create *>(argument);
    ++calls;
    seen_flags = context->flags;
    context->drawctxt_id = 71;
    return ioctl_result;
}

#include "kgsl-priority-under-test.h"

int main()
{
    assert(unsetenv("TU_KGSL_CONTEXT_PRIORITIES") == 0);
    assert(kgsl_submitqueue_priority_count() == 1);
    tu_physical_device physical{19, kgsl_submitqueue_priority_count()};
    tu_device device{&physical};
    VkQueueFamilyGlobalPriorityPropertiesKHR properties{};
    tu_physical_device_get_global_priority_properties(&physical, TU_QUEUE_GRAPHICS, &properties);
    assert(properties.priorityCount == 1);
    assert(properties.priorities[0] == VK_QUEUE_GLOBAL_PRIORITY_MEDIUM_KHR);
    tu_queue legacy{0, 0};
    assert(kgsl_submitqueue_new(&device, &legacy) == 0);
    assert((seen_flags & KGSL_CONTEXT_PRIORITY_MASK) == 0);
    for (const char *option : {"", "0", "true", "01", "2"}) {
        assert(setenv("TU_KGSL_CONTEXT_PRIORITIES", option, 1) == 0);
        assert(kgsl_submitqueue_priority_count() == 1);
    }
    assert(setenv("TU_KGSL_CONTEXT_PRIORITIES", "1", 1) == 0);
    physical.submitqueue_priority_count = kgsl_submitqueue_priority_count();
    assert(physical.submitqueue_priority_count == 4);
    tu_physical_device_get_global_priority_properties(&physical, TU_QUEUE_GRAPHICS, &properties);
    assert(properties.priorityCount == 3);
    const VkQueueGlobalPriorityKHR priorities[] = {
        VK_QUEUE_GLOBAL_PRIORITY_LOW_KHR,
        VK_QUEUE_GLOBAL_PRIORITY_MEDIUM_KHR,
        VK_QUEUE_GLOBAL_PRIORITY_HIGH_KHR,
    };
    const unsigned expected[] = {12, 8, 4};
    for (unsigned i = 0; i < 3; ++i) {
        assert(properties.priorities[i] == priorities[i]);
        int index = tu_get_submitqueue_priority(&physical, priorities[i], TU_QUEUE_GRAPHICS, true);
        assert(index >= 0);
        tu_queue queue{static_cast<unsigned>(index), 0};
        assert(kgsl_submitqueue_new(&device, &queue) == 0);
        assert(queue.msm_queue_id == 71);
        assert(((seen_flags & KGSL_CONTEXT_PRIORITY_MASK) >> KGSL_CONTEXT_PRIORITY_SHIFT) == expected[i]);
        assert((seen_flags & ~KGSL_CONTEXT_PRIORITY_MASK) ==
               (KGSL_CONTEXT_SAVE_GMEM | KGSL_CONTEXT_NO_GMEM_ALLOC | KGSL_CONTEXT_PREAMBLE));
    }
    assert(tu_get_submitqueue_priority(&physical, VK_QUEUE_GLOBAL_PRIORITY_REALTIME_KHR,
                                       TU_QUEUE_GRAPHICS, true) == -1);
    int unqueried = tu_get_submitqueue_priority(&physical, VK_QUEUE_GLOBAL_PRIORITY_REALTIME_KHR,
                                               TU_QUEUE_GRAPHICS, false);
    assert(unqueried == 0);
    tu_queue highest{static_cast<unsigned>(unqueried), 0};
    assert(kgsl_submitqueue_new(&device, &highest) == 0);
    assert(((seen_flags & KGSL_CONTEXT_PRIORITY_MASK) >> KGSL_CONTEXT_PRIORITY_SHIFT) == 1);
    unsigned before = calls;
    tu_queue invalid{4, 99};
    assert(kgsl_submitqueue_new(&device, &invalid) == -EINVAL);
    assert(calls == before && invalid.msm_queue_id == 99);
    ioctl_result = -1;
    tu_queue failed{2, 99};
    assert(kgsl_submitqueue_new(&device, &failed) == -1);
    assert(failed.msm_queue_id == 99);
    ioctl_result = 0;
    for (unsigned count : {0u, 1u, 2u, 3u, 5u}) {
        physical.submitqueue_priority_count = count;
        tu_queue invalid_count{count == 1 ? 1u : 0u, 99};
        before = calls;
        assert(kgsl_submitqueue_new(&device, &invalid_count) == -EINVAL);
        assert(calls == before && invalid_count.msm_queue_id == 99);
    }
    puts("KGSL priorities: low=12 medium=8 high=4; invalid and failed creates preserve queue identity");
}
