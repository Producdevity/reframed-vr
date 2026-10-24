#include "pico-controller-images.h"
#include <opencv2/core.hpp>
#include <array>
#include <atomic>
#include <thread>
#include <cerrno>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <functional>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>
#include <vector>

struct Frame {
    uint8_t camera, pad[3];
    uint32_t width, height, format, type, exposure, gain, pad2;
    int64_t timestamp, center;
    uint64_t number;
    uint32_t size, pad3;
    const uint8_t *data;
};
static_assert(sizeof(Frame) == 72);
struct alignas(16) Head { unsigned char bytes[128]; };
using Ctor = void (*)(void *, int, int);
using Update = void (*)(void *, int, std::vector<Frame>&, Head&, std::function<void()>, const std::vector<int>&);
using Consume = void (*)(void *, std::function<void()>);
static constexpr size_t plane = 640 * 480, set_size = 4 * plane;

template<typename T> static T function(void *handle, const char *name)
{
    dlerror();
    auto pointer = reinterpret_cast<T>(dlsym(handle, name));
    if (!pointer) { fprintf(stderr, "%s: %s\n", name, dlerror()); exit(2); }
    return pointer;
}

int main(int argc, char **argv)
{
    setvbuf(stdout, nullptr, _IONBF, 0);
    assert(argc == 3 && (!strcmp(argv[2], "negative") || !strcmp(argv[2], "owned") || !strcmp(argv[2], "delayed") || !strcmp(argv[2], "retained")));
    bool delayed = !strcmp(argv[2], "delayed");
    bool retained = !strcmp(argv[2], "retained");
    bool owned = strcmp(argv[2], "negative") != 0;
    alarm(90);
    auto library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "tracker: %s\n", dlerror()); return 2; }
    auto ctor = function<Ctor>(library, "_ZN10picosensor15ImageDataBufferC1Eii");
    auto update = function<Update>(owned ? RTLD_DEFAULT : library, "_ZN10picosensor15ImageDataBuffer11updateImageEiRNSt6__ndk16vectorI12frame_item_tNS1_9allocatorIS3_EEEERNS_8HeadDataENS1_8functionIFvvEEERKNS2_IiNS4_IiEEEE");
    const char *symbol = "_ZN10picosensor15ImageDataBuffer15imageThreadFuncENSt6__ndk18functionIFvvEEE";
    auto consume = function<Consume>(owned ? RTLD_DEFAULT : library, symbol);
    auto configure = function<int (*)(void *)>(RTLD_DEFAULT, "pico_controller_images_configure");
    auto prepare = function<int (*)(uint64_t,const void *const *,size_t,const void **)>(RTLD_DEFAULT, "pico_controller_images_prepare");
    auto done = function<int (*)(uint64_t)>(RTLD_DEFAULT, "pico_controller_images_completed");
    auto copies = function<uint64_t (*)()>(RTLD_DEFAULT, "pico_controller_images_adoptions");
    assert(configure(library) == 0);
    alignas(16) unsigned char buffer[1024];
    memset(buffer, 0xa5, sizeof(buffer));
    ctor(buffer, 4, 0);
    for (unsigned i = 0x230; i < sizeof(buffer); ++i) assert(buffer[i] == 0xa5);
    Head head{};
    std::vector<int> order{0,1,2,3};
    std::vector<Frame> frames(4);
    uint8_t *slots[2];
    for (auto &slot : slots) {
        slot = static_cast<uint8_t *>(mmap(nullptr, set_size, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0));
        assert(slot != MAP_FAILED);
    }
    unsigned count = owned ? (retained ? 2 * PICO_CONTROLLER_IMAGES_POOL_SETS : 1000) : 1;
    std::array<std::vector<cv::Mat>,PICO_CONTROLLER_IMAGES_POOL_SETS> held;
    unsigned exhausted = 0;
    for (unsigned iteration = 0; iteration < count; ++iteration) {
        unsigned slot = iteration % 2;
        assert(mprotect(slots[slot], set_size, PROT_READ|PROT_WRITE) == 0);
        uint8_t tag = iteration % 251 + 1;
        memset(slots[slot], tag, set_size);
        std::array<const void *,4> addresses;
        for (unsigned i = 0; i < 4; ++i) {
            addresses[i] = slots[slot] + i * plane;
            frames[i] = {static_cast<uint8_t>(i), {}, 640,480,0x20203859,0,40,16,0,
                         1000000000LL + iteration*10000000LL,1000000000LL + iteration*10000000LL,
                         iteration+1,plane,0,static_cast<const uint8_t *>(addresses[i])};
        }
        if (owned) {
            std::array<const void *,4> destination;
            int prepared = prepare(iteration+1, addresses.data(),plane,destination.data());
            if (retained && iteration >= held.size()) {
                assert(prepared == -EAGAIN);
                held[iteration % held.size()].clear();
                ++exhausted;
                prepared = prepare(iteration+1, addresses.data(),plane,destination.data());
            }
            assert(prepared == 0);
            assert(done(iteration+1) == 0);
            std::array<const void*,4> untouched{};
            assert(prepare(iteration+2,addresses.data(),plane,untouched.data()) == -EAGAIN);
            for (auto value : untouched) assert(value == nullptr);
            for (unsigned i = 0; i < 4; ++i) frames[i].data = static_cast<const uint8_t *>(destination[i]);
            assert(mprotect(slots[slot],set_size,PROT_NONE) == 0);
        }
        update(buffer, 0, frames, head, []{}, order);
        unsigned callbacks = 0;
        std::atomic<bool> entered{false}, release{false};
        auto callback = [&] {
            auto &images = *reinterpret_cast<std::vector<cv::Mat> *>(buffer);
            assert(images.size() == 4);
            for (const auto &image : images) {
                assert(image.rows == 480 && image.cols == 640 && image.data[0] == tag && image.data[plane-1] == tag);
                assert((image.u != nullptr) == owned);
            }
            if (retained) held[iteration % held.size()] = images;
            entered.store(true,std::memory_order_release);
            while (delayed && !release.load(std::memory_order_acquire)) usleep(50);
            ++callbacks;
        };
        if (delayed) {
            std::thread worker([&] { consume(buffer, callback); });
            while (!entered.load(std::memory_order_acquire)) usleep(50);
            assert(done(iteration+1) == 0);
            std::array<const void*,4> unused{};
            assert(prepare(iteration+2,addresses.data(),plane,unused.data()) == -EAGAIN);
            release.store(true,std::memory_order_release);
            worker.join();
        } else consume(buffer,callback);
        assert(callbacks == 1);
        auto &images = *reinterpret_cast<std::vector<cv::Mat> *>(buffer);
        if (owned) {
            assert(done(iteration+1) == 1);
            assert(mprotect(slots[slot], set_size, PROT_NONE) == 0);
            for (const auto &image : images) assert(image.data[0] == tag && image.data[plane-1] == tag && image.u);
        } else {
            memset(slots[slot], 0xee, set_size);
            for (const auto &image : images) assert(image.data[0] == 0xee && image.u == nullptr);
        }
    }
    if (retained) assert(exhausted == held.size());
    struct rusage usage{}; assert(getrusage(RUSAGE_SELF, &usage) == 0);
    printf("PICO_IMAGE_OWNER_%s_PASS sets=%u adoptions=%llu maxrss_kib=%ld hardware_tracking=0\n",
           delayed ? "DELAYED" : retained ? "RETAINED" : owned ? "OWNED" : "NEGATIVE",count,static_cast<unsigned long long>(copies()),usage.ru_maxrss);
    _Exit(0);
}
