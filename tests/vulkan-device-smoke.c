#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>

#define CHECK(call) do { VkResult r = (call); if (r != VK_SUCCESS) { \
    fprintf(stderr, "%s: VkResult %d\n", #call, r); exit(1); } } while (0)

int main(void)
{
    const VkDeviceSize bytes = 4 * 1024 * 1024;
    VkInstance instance;
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "Reframed physical GPU smoke", .apiVersion = VK_API_VERSION_1_0};
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app};
    CHECK(vkCreateInstance(&ici, NULL, &instance));
    uint32_t count = 1;
    VkPhysicalDevice physical;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, &physical));
    if (count != 1) return 2;
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(physical, &properties);
    printf("GPU: %s\n", properties.deviceName);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, NULL);
    VkQueueFamilyProperties *families = calloc(count, sizeof(*families));
    if (!families) return 2;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, families);
    uint32_t family = 0;
    while (family < count && !(families[family].queueFlags & VK_QUEUE_TRANSFER_BIT)) ++family;
    free(families);
    if (family == count) return 2;
    float priority = 1;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci};
    VkDevice device;
    CHECK(vkCreateDevice(physical, &dci, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkBufferCreateInfo bci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = bytes, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VkBuffer buffer;
    CHECK(vkCreateBuffer(device, &bci, NULL, &buffer));
    VkMemoryRequirements requirements;
    VkPhysicalDeviceMemoryProperties memory_properties;
    vkGetBufferMemoryRequirements(device, buffer, &requirements);
    vkGetPhysicalDeviceMemoryProperties(physical, &memory_properties);
    uint32_t type = 0;
    while (type < memory_properties.memoryTypeCount &&
           (!(requirements.memoryTypeBits & (1u << type)) ||
            !(memory_properties.memoryTypes[type].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT))) ++type;
    if (type == memory_properties.memoryTypeCount) return 2;
    VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = requirements.size, .memoryTypeIndex = type};
    VkDeviceMemory memory;
    CHECK(vkAllocateMemory(device, &mai, NULL, &memory));
    CHECK(vkBindBufferMemory(device, buffer, memory, 0));
    uint32_t *mapping;
    CHECK(vkMapMemory(device, memory, 0, VK_WHOLE_SIZE, 0, (void **)&mapping));
    VkCommandPoolCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family};
    VkCommandPool pool;
    CHECK(vkCreateCommandPool(device, &pci, NULL, &pool));
    VkCommandBufferAllocateInfo cai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer command;
    CHECK(vkAllocateCommandBuffers(device, &cai, &command));
    VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence;
    CHECK(vkCreateFence(device, &fci, NULL, &fence));
    for (uint32_t iteration = 0; iteration < 16; ++iteration) {
        uint32_t pattern = 0x72667200u + iteration;
        CHECK(vkResetCommandBuffer(command, 0));
        VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
        CHECK(vkBeginCommandBuffer(command, &begin));
        vkCmdFillBuffer(command, buffer, 0, bytes, pattern);
        VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                             0, 1, &barrier, 0, NULL, 0, NULL);
        CHECK(vkEndCommandBuffer(command));
        VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
            .commandBufferCount = 1, .pCommandBuffers = &command};
        CHECK(vkQueueSubmit(queue, 1, &submit, fence));
        CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, 10000000000ull));
        VkMappedMemoryRange range = {.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
            .memory = memory, .size = VK_WHOLE_SIZE};
        CHECK(vkInvalidateMappedMemoryRanges(device, 1, &range));
        for (VkDeviceSize word = 0; word < bytes / sizeof(*mapping); ++word) {
            if (mapping[word] != pattern) {
                fprintf(stderr, "GPU readback mismatch at %llu\n", (unsigned long long)word);
                return 1;
            }
        }
        CHECK(vkResetFences(device, 1, &fence));
    }
    vkDestroyFence(device, fence, NULL);
    vkDestroyCommandPool(device, pool, NULL);
    vkUnmapMemory(device, memory);
    vkDestroyBuffer(device, buffer, NULL);
    vkFreeMemory(device, memory, NULL);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    puts("VULKAN_DEVICE_SMOKE_PASS: 16 GPU fills and complete 4 MiB readbacks");
    return 0;
}
