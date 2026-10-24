#include "pico-controller-images.h"
#include <opencv2/core.hpp>
#include <link.h>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <functional>
#include <mutex>
#include <cerrno>
#include <stdexcept>

static_assert(sizeof(cv::Mat) == 96);
static_assert(offsetof(cv::Mat, data) == 0x10 && offsetof(cv::Mat, u) == 0x38);
static_assert(offsetof(cv::UMatData, refcount) == 0x14);
static_assert(sizeof(std::function<void()>) == 48 && sizeof(std::mutex) == 40);
struct alignas(16) Head { unsigned char data[128]; };
struct Packet { std::vector<cv::Mat> images; std::vector<int> exposure; int64_t time; Head head; };
struct Frame {
    uint8_t camera, padding[3];
    uint32_t width, height, format, type, exposure, gain, reserved;
    int64_t timestamp, center;
    uint64_t number;
    uint32_t size, reserved2;
    const unsigned char *pixels;
};
static_assert(sizeof(Frame) == 72 && offsetof(Frame, pixels) == 64);
static_assert(sizeof(Packet) == 192 && offsetof(Packet, head) == 64);
static_assert(sizeof(std::deque<Packet>) == 48);
static constexpr char consume_symbol[] = "_ZN10picosensor15ImageDataBuffer15imageThreadFuncENSt6__ndk18functionIFvvEEE";
static constexpr char update_symbol[] = "_ZN10picosensor15ImageDataBuffer11updateImageEiRNSt6__ndk16vectorI12frame_item_tNS1_9allocatorIS3_EEEERNS_8HeadDataENS1_8functionIFvvEEERKNS2_IiNS4_IiEEEE";
using Consumer = void (*)(void *, std::function<void()>);
using Update = void (*)(void *, int, void *, void *, std::function<void()>, const void *);
static Consumer consumer;
static Update updater;
static std::mutex owner_mutex;
// SDK matrix headers can survive stop(); retain allocator storage until process exit.
static auto &pool = *new std::array<std::array<cv::Mat, 4>, 4>;
static void *image_buffer;
static uint64_t submitted, completed, adoptions;
static unsigned active_slot;
static bool pending, promoted, consumed;
static int fault;

extern "C" __attribute__((visibility("default")))
void owner_image_thread(void *, std::function<void()>) __asm__("_ZN10picosensor15ImageDataBuffer15imageThreadFuncENSt6__ndk18functionIFvvEEE");
extern "C" __attribute__((visibility("default")))
void owner_update(void *, int, void *, void *, std::function<void()>, const void *) __asm__("_ZN10picosensor15ImageDataBuffer11updateImageEiRNSt6__ndk16vectorI12frame_item_tNS1_9allocatorIS3_EEEERNS_8HeadDataENS1_8functionIFvvEEERKNS2_IiNS4_IiEEEE");

static void finish()
{
    if (pending && promoted && consumed) { completed = submitted; pending = false; }
}

static bool sdk_identity(void *symbol)
{
    Dl_info library{};
    if (!dladdr(symbol, &library) || !library.dli_fbase) return false;
    struct Identity { uintptr_t base; bool matched; } identity{reinterpret_cast<uintptr_t>(library.dli_fbase), false};
    dl_iterate_phdr([](dl_phdr_info *info, size_t, void *data) {
        auto &identity = *static_cast<Identity *>(data);
        if (info->dlpi_addr != identity.base) return 0;
        constexpr unsigned char expected[] = {0x3d,0x8d,0xe3,0xcf,0x75,0x20,0x19,0x69,0x07,0xde,
                                             0x3a,0x80,0x76,0xf0,0x76,0x21,0x2b,0xcd,0xa1,0x46};
        for (unsigned i = 0; i < info->dlpi_phnum; ++i) {
            const auto &header = info->dlpi_phdr[i];
            if (header.p_type != PT_NOTE || header.p_memsz > 65536) continue;
            const auto *notes = reinterpret_cast<const unsigned char *>(info->dlpi_addr + header.p_vaddr);
            size_t offset = 0;
            while (header.p_memsz - offset >= sizeof(ElfW(Nhdr))) {
                ElfW(Nhdr) note; memcpy(&note, notes + offset, sizeof(note)); offset += sizeof(note);
                size_t name = (static_cast<size_t>(note.n_namesz) + 3) & ~size_t(3);
                size_t size = (static_cast<size_t>(note.n_descsz) + 3) & ~size_t(3);
                if (name > header.p_memsz - offset || size > header.p_memsz - offset - name) break;
                if (note.n_type == NT_GNU_BUILD_ID && note.n_namesz == 4 && note.n_descsz == sizeof(expected) &&
                    !memcmp(notes + offset, "GNU", 4) && !memcmp(notes + offset + name, expected, sizeof(expected)))
                    identity.matched = true;
                offset += name + size;
            }
        }
        return 1;
    }, &identity);
    return identity.matched;
}

extern "C" __attribute__((visibility("default"))) int pico_controller_images_configure(void *library)
{
    auto c = reinterpret_cast<Consumer>(dlsym(library, consume_symbol));
    auto u = reinterpret_cast<Update>(dlsym(library, update_symbol));
    if (!c || c == owner_image_thread || !u || u == owner_update) return -EINVAL;
    if (!sdk_identity(reinterpret_cast<void *>(c)) || !sdk_identity(reinterpret_cast<void *>(u))) return -ENOTSUP;
    std::lock_guard<std::mutex> lock(owner_mutex);
    if (consumer || pending) return -EBUSY;
    try {
        for (auto &set : pool) for (auto &image : set) image.create(480,640,CV_8UC1);
    } catch (...) { return -ENOMEM; }
    consumer = c; updater = u;
    return 0;
}

extern "C" __attribute__((visibility("default"))) int pico_controller_images_prepare(uint64_t sequence, const void *const *source, size_t plane_bytes, const void **destination)
{
    std::lock_guard<std::mutex> lock(owner_mutex);
    if (!consumer || !source || !destination || plane_bytes != 640*480 || !sequence || sequence <= submitted) return -EINVAL;
    if (fault) return fault;
    if (pending) return -EAGAIN;
    for (unsigned i = 0; i < 4; ++i) if (!source[i]) return -EINVAL;
    try {
        for (unsigned slot = 0; slot < pool.size(); ++slot) {
            bool idle = true;
            for (auto &image : pool[slot]) if (image.u && __atomic_load_n(&image.u->refcount, __ATOMIC_ACQUIRE) != 1) idle = false;
            if (!idle) continue;
            for (unsigned i = 0; i < 4; ++i) {
                cv::Mat input(480,640,CV_8UC1,const_cast<void *>(source[i]));
                input.copyTo(pool[slot][i]);
                destination[i] = pool[slot][i].data;
            }
            active_slot = slot; submitted = sequence; pending = true; promoted = consumed = false;
            return 0;
        }
        return -EAGAIN;
    } catch (...) { return fault = -ENOMEM; }
}

extern "C" __attribute__((visibility("default"))) int pico_controller_images_completed(uint64_t sequence)
{
    std::lock_guard<std::mutex> lock(owner_mutex);
    if (!sequence || sequence > submitted) return -EINVAL;
    return fault ? fault : (!pending && completed == sequence);
}

extern "C" __attribute__((visibility("default"))) uint64_t pico_controller_images_adoptions()
{
    std::lock_guard<std::mutex> lock(owner_mutex);
    return adoptions;
}

static int adopt(cv::Mat &image)
{
    if (!image.data) return -1;
    if (image.rows != 480 || image.cols != 640 || image.type() != CV_8UC1 || image.step[0] != 640)
        throw std::runtime_error("matrix geometry");
    for (unsigned slot = 0; slot < pool.size(); ++slot) for (unsigned camera = 0; camera < 4; ++camera) {
        auto &owner = pool[slot][camera];
        if (owner.data != image.data) continue;
        if (image.u && image.u != owner.u) throw std::runtime_error("matrix owner");
        if (!image.u) { image = owner; ++adoptions; }
        return static_cast<int>(slot);
    }
    throw std::runtime_error("unregistered image");
}

void owner_update(void *buffer, int type, void *frames, void *head, std::function<void()> callback, const void *order)
{
    Update original;
    { std::lock_guard<std::mutex> lock(owner_mutex); original = updater; }
    if (!original) return;
    {
        std::lock_guard<std::mutex> lock(owner_mutex);
        if (fault) return;
        if (!pending || (image_buffer && image_buffer != buffer)) { fault = -EINVAL; return; }
        auto &input = *static_cast<std::vector<Frame> *>(frames);
        if (input.size() != 4) { fault = -EINVAL; return; }
        for (unsigned camera = 0; camera < 4; ++camera) {
            const auto &frame = input[camera];
            if (frame.camera != camera || frame.width != 640 || frame.height != 480 ||
                frame.type != 0 || frame.size != 640*480 || frame.pixels != pool[active_slot][camera].data) {
                fault = -EINVAL;
                return;
            }
        }
        image_buffer = buffer;
    }
    original(buffer,type,frames,head,std::move(callback),order);
    try {
        auto bytes = static_cast<unsigned char *>(buffer);
        // The timer holds this mutex through its local snapshot and queue publication.
        std::lock_guard<std::mutex> timer(*reinterpret_cast<std::mutex *>(bytes+0xc8));
        std::lock_guard<std::mutex> queue_lock(*reinterpret_cast<std::mutex *>(bytes+0x1c0));
        auto *camera_mutexes = *reinterpret_cast<std::mutex **>(bytes+0x178);
        auto *camera_end = *reinterpret_cast<std::mutex **>(bytes+0x180);
        auto *cache = *reinterpret_cast<unsigned char **>(bytes+0x1a8);
        auto *cache_end = *reinterpret_cast<unsigned char **>(bytes+0x1b0);
        if (*reinterpret_cast<int *>(bytes+0xc0) != 4 || camera_end-camera_mutexes != 4 || cache_end-cache != 4*208)
            throw std::runtime_error("buffer ABI");
        std::lock_guard<std::mutex> lock(owner_mutex);
        for (unsigned camera = 0; camera < 4; ++camera) {
            std::lock_guard<std::mutex> camera_lock(camera_mutexes[camera]);
            adopt(*reinterpret_cast<cv::Mat *>(cache+camera*208));
            adopt(*reinterpret_cast<cv::Mat *>(cache+camera*208+96));
        }
        auto &queue = *reinterpret_cast<std::deque<Packet> *>(bytes+0x1e8);
        if (queue.size() > 64) throw std::runtime_error("queue bound");
        for (auto &packet : queue) for (auto &image : packet.images) adopt(image);
        promoted = true; finish();
    } catch (...) {
        std::lock_guard<std::mutex> lock(owner_mutex); fault = -EIO;
    }
}

void owner_image_thread(void *buffer, std::function<void()> callback)
{
    Consumer original;
    { std::lock_guard<std::mutex> lock(owner_mutex); original = consumer; }
    if (!original) return;
    original(buffer, [buffer, callback = std::move(callback)]() {
        uint64_t sequence = 0;
        try {
            {
                std::lock_guard<std::mutex> lock(owner_mutex);
                if (fault) return;
                auto &images = *static_cast<std::vector<cv::Mat> *>(buffer);
                if (images.size() != 4) throw std::runtime_error("image count");
                bool active = pending;
                for (auto &image : images) active = (adopt(image) == static_cast<int>(active_slot)) && active;
                if (active) sequence = submitted;
            }
            if (callback) callback();
            if (sequence) {
                std::lock_guard<std::mutex> lock(owner_mutex);
                if (!pending || sequence != submitted) throw std::runtime_error("completion identity");
                consumed = true; finish();
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(owner_mutex); fault = -EIO;
        }
    });
}
