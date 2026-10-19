#define XR_USE_TIMESPEC
#include <ctime>
#define XR_USE_GRAPHICS_API_VULKAN
#include "xr-renderer.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <unistd.h>
static void xc(XrResult r) {
  if (XR_FAILED(r))
    throw std::runtime_error("XR=" + std::to_string(r));
}
static void vc(VkResult r) {
  if (r != VK_SUCCESS)
    throw std::runtime_error("VK=" + std::to_string(r));
}
static std::string capture_path;
static uint64_t ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}
class DesktopCapture {
public:
  static constexpr uint32_t width = 1280, height = 720;
  DesktopCapture() {
    display = XOpenDisplay(nullptr);
    if (!display)
      throw std::runtime_error("X11 display unavailable");
    root = DefaultRootWindow(display);
    XWindowAttributes attributes{};
    XGetWindowAttributes(display, root, &attributes);
    if (attributes.width != (int)width || attributes.height != (int)height) {
      XCloseDisplay(display);
      display = nullptr;
      throw std::runtime_error("Expected private 1280x720 desktop");
    }
    try {
      worker = std::thread([this] { run(); });
    } catch (...) {
      XCloseDisplay(display);
      display = nullptr;
      throw;
    }
  }
  ~DesktopCapture() {
    {
      std::lock_guard<std::mutex> guard(lock);
      stopping = true;
    }
    changed.notify_all();
    if (worker.joinable())
      worker.join();
    if (display)
      XCloseDisplay(display);
  }
  bool ready(uint64_t previous) {
    std::lock_guard<std::mutex> guard(lock);
    if (!error.empty())
      throw std::runtime_error(error);
    return sequence > previous;
  }
  bool copy_latest(void *destination, uint64_t &previous, uint64_t &hash,
                   bool &varied) {
    std::lock_guard<std::mutex> guard(lock);
    if (!error.empty())
      throw std::runtime_error(error);
    if (!sequence || sequence == previous)
      return false;
    memcpy(destination, pixels.data(), pixels.size() * sizeof(uint32_t));
    previous = sequence;
    hash = current_hash;
    varied = current_varied;
    return true;
  }

private:
  Display *display = nullptr;
  Window root{};
  std::thread worker;
  std::mutex lock;
  std::condition_variable changed;
  bool stopping = false, current_varied = false;
  uint64_t sequence = 0, current_hash = 0;
  std::vector<uint32_t> pixels;
  std::string error;
  void capture_file(const std::vector<uint32_t> &rgba) {
    uint64_t begin = ns();
    int fd = open(capture_path.c_str(),
                  O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0)
      throw std::runtime_error("Cannot create private capture file");
    FILE *file = fdopen(fd, "wb");
    if (!file) {
      close(fd);
      throw std::runtime_error("Cannot open capture stream");
    }
    bool failed = fprintf(file, "P6\n%u %u\n255\n", width, height) < 0;
    std::vector<unsigned char> row(width * 3);
    const auto *p = reinterpret_cast<const unsigned char *>(rgba.data());
    for (uint32_t y = 0; y < height && !failed; ++y) {
      for (uint32_t x = 0; x < width; ++x)
        memcpy(row.data() + 3 * x, p + 4 * (y * width + x), 3);
      failed = fwrite(row.data(), 1, row.size(), file) != row.size();
    }
    failed = (fclose(file) != 0) || failed;
    if (failed)
      throw std::runtime_error("Capture write failed");
    printf("PICO_DESKTOP_SOURCE_CAPTURED path=%s capture_ms=%.3f\n",
           capture_path.c_str(), (ns() - begin) / 1e6);
  }
  void run() noexcept {
    try {
      std::vector<uint32_t> working((size_t)width * height);
      unsigned captures = 0;
      for (;;) {
        {
          std::lock_guard<std::mutex> guard(lock);
          if (stopping)
            return;
        }
        uint64_t begin = ns();
        XImage *raw =
            XGetImage(display, root, 0, 0, width, height, AllPlanes, ZPixmap);
        if (!raw)
          throw std::runtime_error("X11 capture failed");
        auto destroy_image = [](XImage *value) { XDestroyImage(value); };
        std::unique_ptr<XImage, decltype(destroy_image)> image(raw,
                                                               destroy_image);
        if (raw->bits_per_pixel != 32 || raw->byte_order != LSBFirst ||
            raw->red_mask != 0xff0000 || raw->green_mask != 0xff00 ||
            raw->blue_mask != 0xff)
          throw std::runtime_error("Unsupported X11 pixel layout");
        uint64_t hash = 1469598103934665603ULL;
        uint32_t first = 0;
        bool varied = false;
        for (uint32_t y = 0; y < height; ++y) {
          const auto *p = reinterpret_cast<const uint32_t *>(
              raw->data + y * raw->bytes_per_line);
          for (uint32_t x = 0; x < width; ++x) {
            uint32_t v = p[x] & 0xffffff;
            working[y * width + x] = 0xff000000 | ((v & 0xff) << 16) |
                                     (v & 0xff00) | ((v >> 16) & 0xff);
            if (!x && !y)
              first = v;
            varied |= v != first;
            hash = (hash ^ v) * 1099511628211ULL;
          }
        }
        {
          std::lock_guard<std::mutex> guard(lock);
          pixels.swap(working);
          current_hash = hash;
          current_varied = varied;
          ++sequence;
        }
        working.resize((size_t)width * height);
        ++captures;
        if (captures == 1 || captures % 20 == 0)
          printf("PICO_DESKTOP_CAPTURE sequence=%u hash=%016llx varied=%d "
                 "cpu_ms=%.3f\n",
                 captures, (unsigned long long)hash, varied,
                 (ns() - begin) / 1e6);
        if (captures == 20 && !capture_path.empty())
          capture_file(pixels);
        std::unique_lock<std::mutex> guard(lock);
        if (changed.wait_for(guard, std::chrono::milliseconds(100),
                             [this] { return stopping; }))
          return;
      }
    } catch (const std::exception &failure) {
      std::lock_guard<std::mutex> guard(lock);
      error = failure.what();
    }
  }
};
class DesktopQuad {
public:
  XrSwapchain swap{};
  unsigned updates = 0;
  uint64_t last_hash = 0;
  bool varied = false;
  XrRenderer &r;
  std::unique_ptr<DesktopCapture> source;
  static constexpr uint32_t width = DesktopCapture::width,
                            height = DesktopCapture::height;
  VkFence copy_fence{};
  bool acquired = false, waited = false, pending = false;
  uint32_t index = 0;
  uint64_t source_sequence = 0, submitted_ns = 0;
  std::vector<XrSwapchainImageVulkan2KHR> images;
  VkBuffer buffer{};
  VkDeviceMemory memory{};
  void *mapping = nullptr;
  VkQueue queue{};
  VkCommandPool pool{};
  VkCommandBuffer command{};
  explicit DesktopQuad(XrRenderer &renderer) : r(renderer) {}
  void create(XrSession session) {
    source = std::make_unique<DesktopCapture>();
    uint32_t n = 0;
    xc(xrEnumerateSwapchainFormats(session, 0, &n, nullptr));
    std::vector<int64_t> fs(n);
    xc(xrEnumerateSwapchainFormats(session, n, &n, fs.data()));
    bool ok = false;
    for (auto f : fs)
      ok |= f == VK_FORMAT_R8G8B8A8_UNORM;
    if (!ok)
      throw std::runtime_error("RGBA8 unsupported");
    XrSwapchainCreateInfo ci{XR_TYPE_SWAPCHAIN_CREATE_INFO};
    ci.usageFlags = XR_SWAPCHAIN_USAGE_SAMPLED_BIT |
                    XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT |
                    XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
    ci.format = VK_FORMAT_R8G8B8A8_UNORM;
    ci.sampleCount = ci.faceCount = ci.arraySize = ci.mipCount = 1;
    ci.width = width;
    ci.height = height;
    xc(xrCreateSwapchain(session, &ci, &swap));
    xc(xrEnumerateSwapchainImages(swap, 0, &n, nullptr));
    images.resize(n, {XR_TYPE_SWAPCHAIN_IMAGE_VULKAN2_KHR});
    xc(xrEnumerateSwapchainImages(
        swap, n, &n,
        reinterpret_cast<XrSwapchainImageBaseHeader *>(images.data())));
    vkGetDeviceQueue(r.binding.device, r.binding.queueFamilyIndex, 0, &queue);
    VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bi.size = (uint64_t)width * height * 4;
    bi.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    vc(vkCreateBuffer(r.binding.device, &bi, nullptr, &buffer));
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(r.binding.device, buffer, &mr);
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(r.binding.physicalDevice, &mp);
    uint32_t t = 0;
    for (; t < mp.memoryTypeCount; ++t)
      if ((mr.memoryTypeBits & (1u << t)) &&
          (mp.memoryTypes[t].propertyFlags &
           (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
            VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) ==
              (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
               VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))
        break;
    if (t == mp.memoryTypeCount)
      throw std::runtime_error("No coherent staging memory");
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.allocationSize = mr.size;
    ai.memoryTypeIndex = t;
    vc(vkAllocateMemory(r.binding.device, &ai, nullptr, &memory));
    vc(vkBindBufferMemory(r.binding.device, buffer, memory, 0));
    vc(vkMapMemory(r.binding.device, memory, 0, VK_WHOLE_SIZE, 0, &mapping));
    VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    pi.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pi.queueFamilyIndex = r.binding.queueFamilyIndex;
    vc(vkCreateCommandPool(r.binding.device, &pi, nullptr, &pool));
    VkCommandBufferAllocateInfo ca{
        VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    ca.commandPool = pool;
    ca.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ca.commandBufferCount = 1;
    vc(vkAllocateCommandBuffers(r.binding.device, &ca, &command));
    VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    vc(vkCreateFence(r.binding.device, &fi, nullptr, &copy_fence));
  }
  void update() {
    auto start = ns();
    if (pending) {
      VkResult result = vkGetFenceStatus(r.binding.device, copy_fence);
      if (result == VK_NOT_READY)
        return;
      vc(result);
      XrSwapchainImageReleaseInfo rel{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
      xc(xrReleaseSwapchainImage(swap, &rel));
      pending = acquired = waited = false;
      ++updates;
      if (updates == 1 || updates % 20 == 0)
        printf("PICO_DESKTOP_QUAD_UPLOAD updates=%u source=%llu hash=%016llx "
               "queue_latency_ms=%.3f\n",
               updates, (unsigned long long)source_sequence,
               (unsigned long long)last_hash, (ns() - submitted_ns) / 1e6);
    }
    if (!source->ready(source_sequence))
      return;
    if (!acquired) {
      XrSwapchainImageAcquireInfo ac{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
      xc(xrAcquireSwapchainImage(swap, &ac, &index));
      acquired = true;
    }
    XrSwapchainImageWaitInfo wi{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
    wi.timeout = 0;
    XrResult result = xrWaitSwapchainImage(swap, &wi);
    if (result == XR_TIMEOUT_EXPIRED)
      return;
    xc(result);
    if (result != XR_SUCCESS)
      throw std::runtime_error("Swapchain wait interrupted");
    waited = true;
    bool different = false;
    if (!source->copy_latest(mapping, source_sequence, last_hash, different))
      throw std::runtime_error("Desktop source sequence unavailable");
    varied |= different;
    vc(vkResetCommandBuffer(command, 0));
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    vc(vkBeginCommandBuffer(command, &begin));
    VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    b.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    b.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    b.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = images.at(index).image;
    b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0,
                         nullptr, 1, &b);
    VkBufferImageCopy copy{};
    copy.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    copy.imageExtent = {width, height, 1};
    vkCmdCopyBufferToImage(command, buffer, b.image,
                           VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
    b.oldLayout = b.newLayout;
    b.newLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    b.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_READ_BIT;
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, 0, 0,
                         nullptr, 0, nullptr, 1, &b);
    vc(vkEndCommandBuffer(command));
    VkSubmitInfo sub{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    sub.commandBufferCount = 1;
    sub.pCommandBuffers = &command;
    vc(vkResetFences(r.binding.device, 1, &copy_fence));
    vc(vkQueueSubmit(queue, 1, &sub, copy_fence));
    pending = true;
    submitted_ns = ns();
    if (updates < 2 || updates % 20 == 0)
      printf("PICO_DESKTOP_SUBMIT source=%llu cpu_ms=%.3f\n",
             (unsigned long long)source_sequence, (ns() - start) / 1e6);
  }
  ~DesktopQuad() { destroy(); }
  void destroy() noexcept {
    source.reset();
    if (r.binding.device)
      vkDeviceWaitIdle(r.binding.device);
    if (acquired && swap) {
      if (!waited) {
        XrSwapchainImageWaitInfo wi{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
        wi.timeout = 1000000000;
        waited = xrWaitSwapchainImage(swap, &wi) == XR_SUCCESS;
      }
      if (waited) {
        XrSwapchainImageReleaseInfo rel{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
        xrReleaseSwapchainImage(swap, &rel);
      }
    }
    acquired = waited = pending = false;
    if (swap)
      xrDestroySwapchain(swap);
    swap = XR_NULL_HANDLE;
    if (copy_fence)
      vkDestroyFence(r.binding.device, copy_fence, nullptr);
    copy_fence = VK_NULL_HANDLE;
    if (pool)
      vkDestroyCommandPool(r.binding.device, pool, nullptr);
    pool = VK_NULL_HANDLE;
    if (mapping)
      vkUnmapMemory(r.binding.device, memory);
    mapping = nullptr;
    if (buffer)
      vkDestroyBuffer(r.binding.device, buffer, nullptr);
    buffer = VK_NULL_HANDLE;
    if (memory)
      vkFreeMemory(r.binding.device, memory, nullptr);
    memory = VK_NULL_HANDLE;
  }
};
static XrVector3f rotate(XrQuaternionf q, XrVector3f v) {
  XrVector3f t{2 * (q.y * v.z - q.z * v.y), 2 * (q.z * v.x - q.x * v.z),
               2 * (q.x * v.y - q.y * v.x)};
  return {v.x + q.w * t.x + q.y * t.z - q.z * t.y,
          v.y + q.w * t.y + q.z * t.x - q.x * t.z,
          v.z + q.w * t.z + q.x * t.y - q.y * t.x};
}
int main(int argc, char **argv) {
  setbuf(stdout, nullptr);
  std::string serial;
  unsigned seconds = 60;
  bool have_seconds = false;
  for (int i = 1; i < argc; i += 2) {
    if (i + 1 == argc) {
      fprintf(stderr, "Expected option value\n");
      return 2;
    }
    std::string key = argv[i];
    if (key == "--boot-serial" && serial.empty())
      serial = argv[i + 1];
    else if (key == "--capture-source" && capture_path.empty())
      capture_path = argv[i + 1];
    else if (key == "--seconds" && !have_seconds) {
      have_seconds = true;
      char *end = nullptr;
      errno = 0;
      auto value = strtoul(argv[i + 1], &end, 10);
      if (errno || !*argv[i + 1] || *end || value < 10 || value > 120) {
        fprintf(stderr, "Seconds must be 10 through 120\n");
        return 2;
      }
      seconds = (unsigned)value;
    } else {
      fprintf(stderr, "Unknown or repeated option\n");
      return 2;
    }
  }
  if (serial.empty() || serial.size() > 64 ||
      serial.find_first_not_of(
          "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") !=
          std::string::npos ||
      (!capture_path.empty() &&
       (capture_path.rfind("/run/", 0) != 0 || capture_path.size() <= 5 ||
        capture_path.substr(5) == "." || capture_path.substr(5) == ".." ||
        capture_path.substr(5).find_first_not_of(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._"
            "-") != std::string::npos))) {
    fprintf(stderr, "Require --boot-serial SERIAL; optional --seconds 10..120 "
                    "and --capture-source /run/NEW.ppm\n");
    return 2;
  }
  alarm(seconds + 40);
  std::ifstream f("/proc/cmdline");
  std::string line, word;
  getline(f, line);
  std::istringstream tokens(line);
  bool exact = false;
  while (tokens >> word)
    exact |= word == "androidboot.serialno=" + serial;
  std::ifstream dt("/proc/device-tree/compatible", std::ios::binary);
  std::string compatible((std::istreambuf_iterator<char>(dt)), {});
  const char expected[] = "qcom,kona-iot-mtp\0qcom,kona-iot\0qcom,mtp\0";
  if (!exact || compatible != std::string(expected, sizeof(expected) - 1)) {
    fprintf(stderr, "Pico boot identity or board mismatch\n");
    return 2;
  }
  const char *display_env = getenv("DISPLAY");
  if (!display_env || display_env[0] != ':' || !display_env[1] ||
      strspn(display_env + 1, "0123456789") != strlen(display_env + 1)) {
    fprintf(stderr, "Require an explicit local DISPLAY=:N\n");
    return 2;
  }

  if (!XInitThreads()) {
    fprintf(stderr, "X11 thread initialization failed\n");
    return 2;
  }
  try {
    const char *exts[] = {"XR_KHR_vulkan_enable2",
                          "XR_KHR_convert_timespec_time"};
    XrInstanceCreateInfo ci{XR_TYPE_INSTANCE_CREATE_INFO};
    strcpy(ci.applicationInfo.applicationName, "Pico native desktop quad test");
    ci.applicationInfo.apiVersion = XR_API_VERSION_1_0;
    ci.enabledExtensionCount = 2;
    ci.enabledExtensionNames = exts;
    XrInstance in;
    xc(xrCreateInstance(&ci, &in));
    PFN_xrConvertTimespecTimeToTimeKHR convert_time = nullptr;
    xc(xrGetInstanceProcAddr(
        in, "xrConvertTimespecTimeToTimeKHR",
        reinterpret_cast<PFN_xrVoidFunction *>(&convert_time)));
    XrSystemGetInfo gi{XR_TYPE_SYSTEM_GET_INFO};
    gi.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    XrSystemId sys;
    xc(xrGetSystem(in, &gi, &sys));
    XrSystemProperties prop{XR_TYPE_SYSTEM_PROPERTIES};
    xc(xrGetSystemProperties(in, sys, &prop));
    if (!strstr(prop.systemName, "Pico Neo3 HMD"))
      throw std::runtime_error("Physical HMD required");
    {
      XrRenderer r;
      r.initialize(in, sys);
      XrSessionCreateInfo si{XR_TYPE_SESSION_CREATE_INFO};
      si.next = &r.binding;
      si.systemId = sys;
      XrSession session;
      xc(xrCreateSession(in, &si, &session));
      DesktopQuad quad(r);
      quad.create(session);
      XrReferenceSpaceCreateInfo spi{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
      spi.poseInReferenceSpace.orientation.w = 1;
      spi.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
      XrSpace local, view;
      xc(xrCreateReferenceSpace(session, &spi, &local));
      spi.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
      xc(xrCreateReferenceSpace(session, &spi, &view));
      bool running = false, placed = false;
      unsigned frames = 0, tracked = 0, invalid = 0;
      uint64_t end = ns() + (uint64_t)seconds * 1000000000, last_tracked = 0;
      XrPosef pose{};
      while (ns() < end) {
        XrEventDataBuffer ev{XR_TYPE_EVENT_DATA_BUFFER};
        auto result = xrPollEvent(in, &ev);
        xc(result);
        if (result == XR_SUCCESS &&
            ev.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) {
          auto state = ((XrEventDataSessionStateChanged *)&ev)->state;
          if (state == XR_SESSION_STATE_READY) {
            XrSessionBeginInfo bi{XR_TYPE_SESSION_BEGIN_INFO};
            bi.primaryViewConfigurationType =
                XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
            xc(xrBeginSession(session, &bi));
            running = true;
          }
          if (state == XR_SESSION_STATE_STOPPING) {
            xc(xrEndSession(session));
            running = false;
            break;
          }
        }
        if (!running) {
          std::this_thread::sleep_for(std::chrono::milliseconds(5));
          continue;
        }
        auto frame = r.begin(session);
        XrSpaceLocation head{XR_TYPE_SPACE_LOCATION};
        xc(xrLocateSpace(view, local, frame.predictedDisplayTime, &head));
        bool valid = (head.locationFlags &
                      (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                       XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT)) ==
                     (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                      XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT);
        if (valid) {
          last_tracked = ns();
          ++tracked;
          if (!placed) {
            pose = head.pose;
            auto p = rotate(pose.orientation, {0, 0, -1.8f});
            pose.position.x += p.x;
            pose.position.y += p.y;
            pose.position.z += p.z;
            placed = true;
            printf("PICO_DESKTOP_QUAD_PLACED world_locked=1 distance_m=1.8 "
                   "q=%f,%f,%f,%f\n",
                   pose.orientation.x, pose.orientation.y, pose.orientation.z,
                   pose.orientation.w);
          }
        }
        if (!valid && placed) {
          struct timespec now{};
          if (clock_gettime(CLOCK_MONOTONIC, &now))
            throw std::runtime_error("Clock query failed");
          XrTime current;
          xc(convert_time(in, &now, &current));
          XrSpaceLocation live{XR_TYPE_SPACE_LOCATION};
          xc(xrLocateSpace(view, local, current, &live));
          ++invalid;
          if (invalid <= 5 || ns() - last_tracked > 100000000)
            printf("PICO_DESKTOP_INVALID_POSE ahead_ms=%.3f period_ns=%lld "
                   "predicted_flags=%llu current_flags=%llu\n",
                   (frame.predictedDisplayTime - current) / 1e6,
                   (long long)frame.predictedDisplayPeriod,
                   (unsigned long long)head.locationFlags,
                   (unsigned long long)live.locationFlags);
        }
        if (placed && !valid && ns() - last_tracked > 100000000)
          throw std::runtime_error("Predicted head pose remained invalid");
        if (frame.shouldRender && placed)
          quad.update();
        XrCompositionLayerQuad layer{XR_TYPE_COMPOSITION_LAYER_QUAD};
        layer.space = local;
        layer.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
        layer.subImage.swapchain = quad.swap;
        layer.subImage.imageRect.extent = {(int32_t)quad.width,
                                           (int32_t)quad.height};
        layer.pose = pose;
        layer.size = {1.6f, .9f};
        const auto *header = (const XrCompositionLayerBaseHeader *)&layer;
        XrFrameEndInfo ei{XR_TYPE_FRAME_END_INFO};
        ei.displayTime = frame.predictedDisplayTime;
        ei.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        ei.layerCount =
            frame.shouldRender && valid && placed && quad.updates ? 1 : 0;
        ei.layers = &header;
        xc(xrEndFrame(session, &ei));
        if (ei.layerCount)
          ++frames;
        if (frames && frames % 120 == 0)
          printf("PICO_DESKTOP_QUAD_FRAME frames=%u tracked=%u updates=%u "
                 "period_ns=%lld\n",
                 frames, tracked, quad.updates,
                 (long long)frame.predictedDisplayPeriod);
      }
      if (frames < 120 || tracked < 120 || quad.updates < 10 || !quad.varied)
        throw std::runtime_error("Insufficient tracked desktop quad frames");
      xc(xrRequestExitSession(session));
      for (unsigned i = 0; i < 100 && running; ++i) {
        XrEventDataBuffer ev{XR_TYPE_EVENT_DATA_BUFFER};
        auto result = xrPollEvent(in, &ev);
        xc(result);
        if (result == XR_SUCCESS &&
            ev.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED &&
            ((XrEventDataSessionStateChanged *)&ev)->state ==
                XR_SESSION_STATE_STOPPING) {
          xc(xrEndSession(session));
          running = false;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
      }
      quad.destroy();
      xc(xrDestroySpace(view));
      xc(xrDestroySpace(local));
      xc(xrDestroySession(session));
      printf("PICO_DESKTOP_QUAD_PASS frames=%u tracked=%u uploads=%u "
             "world_locked=1 optical_alignment_verified=0\n",
             frames, tracked, quad.updates);
    }
    xc(xrDestroyInstance(in));
    return 0;
  } catch (const std::exception &e) {
    fprintf(stderr, "PICO_DESKTOP_QUAD_FAIL %s\n", e.what());
    return 1;
  }
}
