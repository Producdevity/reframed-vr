#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <set>
#include <unistd.h>
#include <sys/resource.h>
#include <vector>

#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); std::abort(); } } while (0)
#define ASSERTED [[maybe_unused]]
#define UNREACHABLE(x) std::abort()
#define MAX2(a,b) std::max(a,b)
#define container_of(p,t,m) reinterpret_cast<t *>(reinterpret_cast<char *>(p) - offsetof(t,m))
#define p_atomic_set(p,v) (*(p) = (v))
enum VkResult { VK_SUCCESS = 0, VK_ERROR_OUT_OF_HOST_MEMORY = -1, VK_ERROR_DEVICE_LOST = -4, VK_ERROR_UNKNOWN = -13 };
enum vk_sync_flags { VK_SYNC_NONE = 0 };
struct vk_object_base { uint64_t unused; };
struct vk_queue {};
struct vk_sync { bool drm; };
struct vk_drm_syncobj { vk_sync vk; uint32_t syncobj; };
struct vk_sync_wait { vk_sync *sync; uint64_t stage_mask, wait_value; };
struct vk_sync_signal { vk_sync *sync; uint64_t signal_value; };
struct vk_device { bool lost; int alloc; };
struct tu_physical_device { unsigned submitqueue_priority_count = 1; int local_fd = 40, kgsl_sync_fd = 42; bool has_kgsl_drm_sync = true; };
struct tu_device { vk_device vk{}; tu_physical_device *physical_device; int fd = 40, kgsl_profiling_mutex = 0, kgsl_profiling_suballoc = 0; };
#include "kgsl-queue-under-test.h"
struct tu_bo { uint64_t iova; unsigned gem_handle; };
struct tu_suballoc_bo { uint64_t iova; tu_bo *bo; };
struct tu_u_trace_submission_data { tu_suballoc_bo kgsl_timestamp_bo; uint64_t gpu_ts_offset; };
struct kgsl_cmdbatch_profiling_buffer { uint64_t wall_clock_ns, gpu_ticks_queued; };
struct util_dynarray { unsigned size; void *data; };
struct tu_kgsl_queue_submit { util_dynarray commands{}, bind_cmds{}; };
#define util_dynarray_num_elements(a,t) ((a)->size / sizeof(t))
#define util_dynarray_foreach(a,t,v) for (t *v = static_cast<t *>((a)->data); reinterpret_cast<char *>(v) < static_cast<char *>((a)->data) + (a)->size; ++v)
struct kgsl_command_object { uint64_t offset, gpuaddr, size; unsigned flags, id; };
struct kgsl_drawctxt_create { unsigned flags, drawctxt_id; };
struct kgsl_drawctxt_destroy { unsigned drawctxt_id; };
struct kgsl_timestamp_event { unsigned type, timestamp, context_id; void *priv; unsigned len; };
struct kgsl_cmd_syncpoint_timestamp { unsigned context_id, timestamp; };
struct kgsl_cmd_syncpoint_fence { int fd; };
struct kgsl_command_syncpoint { unsigned type; uintptr_t priv; size_t size; };
struct kgsl_gpu_command { unsigned flags; uintptr_t cmdlist; size_t cmdsize, numcmds; uintptr_t synclist; size_t syncsize, numsyncs; unsigned context_id; uintptr_t objlist; size_t objsize, numobjs; unsigned timestamp; };
struct kgsl_gpu_aux_command_bind { unsigned unused; };
struct kgsl_gpu_aux_command_generic { uintptr_t priv; size_t size; unsigned type; };
struct kgsl_gpu_aux_command { unsigned flags; uintptr_t cmdlist; size_t cmdsize, numcmds; uintptr_t synclist; size_t syncsize, numsyncs; unsigned context_id, timestamp; };
enum { KGSL_CONTEXT_SAVE_GMEM = 1, KGSL_CONTEXT_NO_GMEM_ALLOC = 2, KGSL_CONTEXT_PREAMBLE = 4, KGSL_CONTEXT_PRIORITY_SHIFT = 8,
       KGSL_TIMESTAMP_EVENT_FENCE = 1, KGSL_OBJLIST_MEMOBJ = 1, KGSL_OBJLIST_PROFILE = 2,
       KGSL_CMD_SYNCPOINT_TYPE_TIMESTAMP = 1, KGSL_CMD_SYNCPOINT_TYPE_FENCE = 2,
       KGSL_CMDBATCH_SUBMIT_IB_LIST = 1, KGSL_CMDBATCH_PROFILING = 2,
       KGSL_GPU_AUX_COMMAND_BIND = 1, KGSL_GPU_AUX_COMMAND_SYNC = 2, VK_SYSTEM_ALLOCATION_SCOPE_COMMAND = 0,
       IOCTL_KGSL_DRAWCTXT_CREATE = 1, IOCTL_KGSL_DRAWCTXT_DESTROY, IOCTL_KGSL_TIMESTAMP_EVENT,
       IOCTL_KGSL_GPU_COMMAND, IOCTL_KGSL_GPU_AUX_COMMAND };
using Deps = std::set<uint64_t>;
static std::map<int, Deps> fds;
static std::map<uint32_t, Deps> drm;
static std::map<std::pair<unsigned,unsigned>, Deps> timestamps;
static Deps completed;
static std::set<void *> allocations, initialized;
static unsigned next_context = 1, timestamp_value = 7, exports, gpu_calls, closes, failure_seen;
static uint64_t epoch;
static unsigned assertions;
enum Fail { NONE, ALLOC, INIT, WAIT_EXPORT, TS_EXPORT, DUP, MERGE, PUBLISH, GPU, CREATE, FAIL_COUNT };
static Fail failure;
static unsigned fail_at, calls[FAIL_COUNT];
static bool fails(Fail op) { bool yes = (++calls[op] == fail_at || fail_at == 0) && failure == op; failure_seen += yes; if (yes) errno = EMFILE; return yes; }
static void inject(Fail op = NONE, unsigned at = 1) { failure = op; fail_at = at; failure_seen = 0; std::memset(calls, 0, sizeof(calls)); }
static int make_fd(const Deps &deps, bool cloexec)
{
    int fd = open("/dev/null", O_RDONLY | (cloexec ? O_CLOEXEC : 0));
    if (fd < 0) return -1;
    CHECK(fds.emplace(fd, deps).second); return fd;
}
static int model_close(int fd) { CHECK(fds.erase(fd) == 1); ++closes; return close(fd); }
static int model_dup(int fd)
{
    CHECK(fds.count(fd)); if (fails(DUP)) return -1;
    int copy = fcntl(fd, F_DUPFD_CLOEXEC, 0); if (copy < 0) return -1;
    CHECK(fds.emplace(copy, fds.at(fd)).second); return copy;
}
static int model_merge(const char *, int a, int b)
{
    CHECK(fds.count(a) && fds.count(b)); if (fails(MERGE)) return -1;
    Deps deps = fds.at(a); deps.insert(fds.at(b).begin(), fds.at(b).end()); return make_fd(deps, true);
}
static void *model_calloc(size_t n, size_t size)
{
    if (fails(ALLOC)) return nullptr;
    void *p = calloc(n, size); if (p) CHECK(allocations.insert(p).second); return p;
}
static void model_free(void *p) { if (p) CHECK(allocations.erase(p) == 1); free(p); }
static void *vk_alloc(int *, size_t n, size_t, int) { void *p = malloc(n); if (p) CHECK(allocations.insert(p).second); return p; }
static void vk_free(int *, void *p) { model_free(p); }
static VkResult vk_device_set_lost(vk_device *device, const char *, ...) { device->lost = true; return VK_ERROR_DEVICE_LOST; }
static int vk_kgsl_sync_type;
static VkResult vk_sync_init(vk_device *, vk_sync *, int *, vk_sync_flags, uint64_t);
static void vk_sync_finish(vk_device *, vk_sync *);
static vk_drm_syncobj *vk_sync_as_drm_syncobj(vk_sync *s) { return s->drm ? reinterpret_cast<vk_drm_syncobj *>(s) : nullptr; }
static int tu_kgsl_drm_export_wait(int fd, uint32_t id, uint64_t, int *out)
{
    CHECK(fd == 42 && drm.count(id)); *out = -1; if (fails(WAIT_EXPORT)) return -1;
    *out = make_fd(drm.at(id), true); return *out < 0 ? -1 : 0;
}
static int tu_kgsl_drm_import_signal(int fd, uint32_t id, uint64_t, int in)
{
    CHECK(fd == 42 && (in == -1 || fds.count(in))); if (fails(PUBLISH)) return -1;
    drm[id] = in < 0 ? Deps{} : fds.at(in); return 0;
}
static Deps gpu_dependencies(uintptr_t sync_ptr, size_t count)
{
    Deps deps;
    if (count) {
        auto *sync = reinterpret_cast<kgsl_command_syncpoint *>(sync_ptr);
        if (sync->type == KGSL_CMD_SYNCPOINT_TYPE_FENCE)
            deps = fds.at(reinterpret_cast<kgsl_cmd_syncpoint_fence *>(sync->priv)->fd);
        else {
            auto *ts = reinterpret_cast<kgsl_cmd_syncpoint_timestamp *>(sync->priv);
            deps = timestamps.at({ts->context_id, ts->timestamp});
        }
    }
    deps.insert(++epoch); return deps;
}
static int safe_ioctl(int, unsigned request, void *data)
{
    switch (request) {
    case IOCTL_KGSL_DRAWCTXT_CREATE:
        if (fails(CREATE)) return -1;
        static_cast<kgsl_drawctxt_create *>(data)->drawctxt_id = next_context++; return 0;
    case IOCTL_KGSL_DRAWCTXT_DESTROY: return 0;
    case IOCTL_KGSL_TIMESTAMP_EVENT: {
        ++exports; if (fails(TS_EXPORT)) return -1;
        auto *req = static_cast<kgsl_timestamp_event *>(data);
        CHECK(req->type == KGSL_TIMESTAMP_EVENT_FENCE && req->len == sizeof(int));
        *static_cast<int *>(req->priv) = make_fd(timestamps.at({req->context_id, req->timestamp}), false); return *static_cast<int *>(req->priv) < 0 ? -1 : 0;
    }
    case IOCTL_KGSL_GPU_COMMAND: {
        ++gpu_calls; if (fails(GPU)) return -1;
        auto *req = static_cast<kgsl_gpu_command *>(data);
        CHECK(req->numcmds > 0); req->timestamp = timestamp_value;
        timestamps[{req->context_id, req->timestamp}] = gpu_dependencies(req->synclist, req->numsyncs); return 0;
    }
    case IOCTL_KGSL_GPU_AUX_COMMAND: {
        ++gpu_calls; if (fails(GPU)) return -1;
        auto *req = static_cast<kgsl_gpu_aux_command *>(data); req->timestamp = timestamp_value;
        timestamps[{req->context_id, req->timestamp}] = gpu_dependencies(req->synclist, req->numsyncs); return 0;
    }
    default: std::abort();
    }
}
static void kgsl_bind_finalize(tu_kgsl_queue_submit *) {}
static void mtx_lock(int *) {}
static void mtx_unlock(int *) {}
static void tu_suballoc_bo_alloc(tu_suballoc_bo *, int *, size_t, unsigned) { std::abort(); }
static void *tu_suballoc_bo_map(tu_suballoc_bo *) { std::abort(); }
static void tu_suballoc_bo_free(int *, tu_suballoc_bo *) { std::abort(); }
#define close model_close
#define os_dupfd_cloexec model_dup
#define sync_merge model_merge
#define calloc model_calloc
#define free model_free
#include "kgsl-completion-under-test.h"
#undef close
#undef os_dupfd_cloexec
#undef sync_merge
#undef calloc
#undef free

static VkResult vk_sync_init(vk_device *, vk_sync *s, int *type, vk_sync_flags, uint64_t value)
{
    CHECK(type == &vk_kgsl_sync_type && value == 0);
    if (fails(INIT)) return VK_ERROR_OUT_OF_HOST_MEMORY;
    CHECK(initialized.insert(s).second); s->drm = false;
    kgsl_syncobj_init(&reinterpret_cast<vk_kgsl_syncobj *>(s)->syncobj, false); return VK_SUCCESS;
}
static void vk_sync_finish(vk_device *, vk_sync *s)
{
    CHECK(initialized.erase(s) == 1); kgsl_syncobj_destroy(&reinterpret_cast<vk_kgsl_syncobj *>(s)->syncobj);
}
struct Fixture {
    tu_physical_device physical;
    tu_device device{{}, &physical};
    tu_queue queue{};
    Fixture() { inject(); queue.device = &device; queue.fence = -1; CHECK(kgsl_submitqueue_new(&device, &queue) == 0); }
    ~Fixture() { kgsl_submitqueue_close(&device, &queue); CHECK(allocations.empty() && initialized.empty()); }
};
static VkResult submit(Fixture &f, bool gpu, std::vector<uint32_t> waits = {}, std::vector<uint32_t> signals = {200}, bool bind = false)
{
    kgsl_command_object cmd{}; kgsl_gpu_aux_command_bind binding{};
    tu_kgsl_queue_submit job;
    if (gpu) job.commands = {sizeof(cmd), &cmd};
    if (bind) job.bind_cmds = {sizeof(binding), &binding};
    std::vector<vk_drm_syncobj> objects(waits.size() + signals.size());
    std::vector<vk_sync_wait> w(waits.size()); std::vector<vk_sync_signal> s(signals.size());
    for (unsigned i = 0; i < waits.size(); ++i) { objects[i] = {{true}, waits[i]}; w[i] = {&objects[i].vk, 1, 0}; }
    for (unsigned i = 0; i < signals.size(); ++i) { objects[waits.size()+i] = {{true}, signals[i]}; s[i] = {&objects[waits.size()+i].vk, 0}; }
    VkResult result = kgsl_queue_submit(&f.queue, &job, w.data(), w.size(), s.data(), s.size(), nullptr);
    CHECK(allocations.empty() && initialized.empty()); return result;
}
static bool ready(uint32_t id) { const auto &deps = drm.at(id); return std::includes(completed.begin(), completed.end(), deps.begin(), deps.end()); }
static void clean() { CHECK(fds.empty() && allocations.empty() && initialized.empty()); drm.clear(); completed.clear(); timestamps.clear(); inject(); ++assertions; }

static void repeated_empty()
{
    unsigned initial = exports;
    {
        Fixture f;
        CHECK(submit(f, false) == VK_SUCCESS && drm.at(200).empty());
        CHECK(exports == initial);
        CHECK(submit(f, true, {}, {200, 201, 202}) == VK_SUCCESS);
        Deps gpu = drm.at(200); CHECK(gpu.size() == 1 && drm.at(201) == gpu && drm.at(202) == gpu);
        CHECK(exports == initial + 1);
        for (unsigned i = 0; i < 4; ++i) {
            CHECK(submit(f, false, {}, {203}) == VK_SUCCESS && drm.at(203) == gpu);
            CHECK(!ready(203));
        }
        CHECK(exports == initial + (HAS_CACHE ? 1 : 5));
#if HAS_CACHE
        CHECK(fds.size() == 1 && f.queue.kgsl_completion_fd >= 0);
        CHECK(fcntl(f.queue.kgsl_completion_fd, F_GETFD) & FD_CLOEXEC);
#endif
        drm[100] = {1000000};
        CHECK(submit(f, false, {100}, {204}) == VK_SUCCESS);
        Deps both = gpu; both.insert(1000000); CHECK(drm.at(204) == both);
        completed = gpu; CHECK(!ready(204)); completed.insert(1000000); CHECK(ready(204));
        completed.clear();
        CHECK(submit(f, false, {}, {205}) == VK_SUCCESS && drm.at(205) == gpu);
        CHECK(submit(f, false, {204}, {206}) == VK_SUCCESS && drm.at(206) == both);
        CHECK(exports == initial + (HAS_CACHE ? 1 : 8));
    }
    CHECK(fds.empty() && !ready(206)); completed = drm.at(206); CHECK(ready(206));
    clean();
}
static void replacement_and_sparse()
{
    {
        Fixture f;
        CHECK(submit(f, true) == VK_SUCCESS); Deps old = drm.at(200);
        CHECK(submit(f, true) == VK_SUCCESS); CHECK(drm.at(200) != old);
#if HAS_CACHE
        CHECK(fds.size() == 1 && fds.at(f.queue.kgsl_completion_fd) == drm.at(200));
#endif
        unsigned before = exports;
        CHECK(submit(f, true, {}, {}) == VK_SUCCESS && exports == before);
        CHECK(fds.empty());
        Deps next = timestamps.at({f.queue.msm_queue_id, timestamp_value});
        CHECK(submit(f, false) == VK_SUCCESS && drm.at(200) == next && exports == before + 1);
        timestamp_value = UINT32_MAX;
        CHECK(submit(f, true) == VK_SUCCESS);
        timestamp_value = 1;
        CHECK(submit(f, false, {}, {}, true) == VK_SUCCESS);
        CHECK(fds.empty());
        next = timestamps.at({f.queue.msm_queue_id, timestamp_value});
        CHECK(submit(f, false) == VK_SUCCESS && drm.at(200) == next);
        CHECK(submit(f, false, {}, {201}, true) == VK_SUCCESS);
#if HAS_CACHE
        CHECK(fds.size() == 1 && fds.at(f.queue.kgsl_completion_fd) == drm.at(201));
#endif
    }
    timestamp_value = 7; clean();
}
static void missing_cache_merged_completion()
{
    {
        Fixture f;
        CHECK(submit(f, true, {}, {}) == VK_SUCCESS); CHECK(fds.empty());
        drm[100] = {2000000};
        CHECK(submit(f, false, {100}) == VK_SUCCESS);
        CHECK(fds.empty()); // A merged completion must never become a pure-TS cache.
        Deps pure = timestamps.at({f.queue.msm_queue_id, timestamp_value});
        CHECK(submit(f, false, {}, {201}) == VK_SUCCESS && drm.at(201) == pure);
    }
    clean();
}
static void independent_queues()
{
    {
        Fixture a, b;
        CHECK(submit(a, true, {}, {200}) == VK_SUCCESS);
        CHECK(submit(b, true, {}, {201}) == VK_SUCCESS);
        Deps both = drm.at(200); both.insert(drm.at(201).begin(), drm.at(201).end());
        unsigned before = exports;
        CHECK(submit(a, false, {201}, {202}) == VK_SUCCESS && drm.at(202) == both);
        CHECK(exports == before + (HAS_CACHE ? 0 : 1));
        completed = drm.at(200); CHECK(!ready(202)); completed = both; CHECK(ready(202));
    }
    clean();
}
static void optional_cache_failure()
{
    {
        Fixture f;
        inject(DUP);
        CHECK(submit(f, true) == VK_SUCCESS && !f.device.vk.lost);
#if HAS_CACHE
        CHECK(failure_seen == 1 && f.queue.kgsl_completion_fd == -1 && fds.empty());
#else
        CHECK(failure_seen == 0);
#endif
        inject(); Deps gpu = drm.at(200); unsigned before = exports;
        CHECK(submit(f, false, {}, {201}) == VK_SUCCESS && drm.at(201) == gpu);
        CHECK(exports == before + 1);
    }
    clean();
}
static void native_mode()
{
    {
        Fixture f; f.physical.has_kgsl_drm_sync = false;
        kgsl_command_object cmd{}; tu_kgsl_queue_submit job{{sizeof(cmd), &cmd}, {}};
        vk_kgsl_syncobj signal{}; kgsl_syncobj_init(&signal.syncobj, false);
        vk_sync_signal s{&signal.vk, 0};
        unsigned before = exports;
        CHECK(kgsl_queue_submit(&f.queue, &job, nullptr, 0, &s, 1, nullptr) == VK_SUCCESS);
        CHECK(signal.syncobj.state == KGSL_SYNCOBJ_STATE_TS);
        int fd; CHECK(kgsl_syncobj_export(&signal.syncobj, &fd) == VK_SUCCESS); model_close(fd);
        job.commands = {};
        CHECK(kgsl_queue_submit(&f.queue, &job, nullptr, 0, &s, 1, nullptr) == VK_SUCCESS);
        CHECK(signal.syncobj.state == KGSL_SYNCOBJ_STATE_TS);
        CHECK(kgsl_syncobj_export(&signal.syncobj, &fd) == VK_SUCCESS); model_close(fd);
        CHECK(exports == before + 2 && fds.empty()); kgsl_syncobj_destroy(&signal.syncobj);
    }
    clean();
}
static void faults()
{
    unsigned exercised = 0;
    for (unsigned mode : {0u, 1u, 2u}) {
        for (Fail op : {ALLOC, INIT, WAIT_EXPORT, TS_EXPORT, DUP, MERGE, PUBLISH, GPU}) {
            for (unsigned at = 1; at <= 14; ++at) {
                {
                    Fixture f;
                    CHECK(submit(f, true) == VK_SUCCESS);
                    drm[100] = {3000000}; drm[101] = {4000000};
                    unsigned before_gpu = gpu_calls;
                    inject(op, at);
                    VkResult result = submit(f, mode == 1, {100, 101}, {201, 202, 203}, mode == 2);
                    if (failure_seen) {
                        ++exercised;
                        if (op == PUBLISH || (op == TS_EXPORT && gpu_calls > before_gpu))
                            CHECK(result == VK_ERROR_DEVICE_LOST && f.device.vk.lost);
                        if (result != VK_SUCCESS)
                            CHECK(!drm.count(203));
                    } else CHECK(result == VK_SUCCESS);
#if HAS_CACHE
                    CHECK(fds.size() == (f.queue.kgsl_completion_fd >= 0 ? 1u : 0u));
#else
                    CHECK(fds.empty());
#endif
                }
                clean();
            }
        }
    }
    CHECK(exercised >= 30);
    std::printf("Injected %u reached allocation/initialization/wait-export/native-export/dup/merge/publication/GPU failures.\n", exercised);
}
static void context_lifecycle()
{
    tu_physical_device physical; tu_device device{{}, &physical}; tu_queue q{}; q.device = &device;
    inject(CREATE); CHECK(kgsl_submitqueue_new(&device, &q) < 0);
#if HAS_CACHE
    CHECK(q.kgsl_completion_fd == -1);
#endif
    clean();
    {
        Fixture f; CHECK(submit(f, true) == VK_SUCCESS);
        Deps old = drm.at(200); unsigned old_timestamp = f.queue.fence;
        inject(GPU); CHECK(submit(f, true) == VK_ERROR_DEVICE_LOST);
        CHECK(static_cast<unsigned>(f.queue.fence) == old_timestamp);
#if HAS_CACHE
        CHECK(fds.at(f.queue.kgsl_completion_fd) == old);
#endif
    }
    clean();
}
static void cache_resource_failures()
{
    {
        Fixture f; CHECK(submit(f, true) == VK_SUCCESS);
        inject(DUP, 1);
        CHECK(submit(f, false, {}, {}) == VK_SUCCESS && calls[DUP] == 0);
        inject(DUP, 2);
        CHECK(submit(f, false, {}, {201}) == VK_SUCCESS && !f.device.vk.lost);
        CHECK(calls[DUP] == (HAS_CACHE ? 1u : 0u));
        inject(DUP, 1); unsigned before = exports;
        CHECK(submit(f, false, {}, {202}) == VK_SUCCESS && drm.at(202) == drm.at(200));
        CHECK(exports == before + 1 && calls[DUP] == (HAS_CACHE ? 2u : 0u));
        drm[100] = {9000000}; inject(MERGE, 0);
        CHECK(submit(f, false, {100}, {203}) != VK_SUCCESS);
        CHECK(calls[MERGE] == (HAS_CACHE ? 2u : 1u) && !drm.count(203));
        CHECK(!f.device.vk.lost);
    }
    clean();
}

static void real_fd_headroom()
{
    unsigned cases = 0, successful = 0;
    for (unsigned nw = 0; nw < 3; ++nw) for (unsigned ns = 0; ns < 2; ++ns)
    for (unsigned holes = 0; holes < 9; ++holes) {
        {
            Fixture f; CHECK(submit(f, true) == VK_SUCCESS); Deps expected = drm.at(200);
            std::vector<uint32_t> waits, signals; std::vector<int> fillers;
            for (unsigned i = 0; i < nw; ++i) {
                drm[100+i] = {8000000+i}; waits.push_back(100+i); expected.insert(8000000+i);
            }
            if (ns) signals.push_back(201);
            struct rlimit old_limit; CHECK(getrlimit(RLIMIT_NOFILE, &old_limit) == 0);
            struct rlimit limit = old_limit; limit.rlim_cur = std::min<rlim_t>(old_limit.rlim_cur, 64);
            CHECK(setrlimit(RLIMIT_NOFILE, &limit) == 0);
            while (true) {
                int fd = open("/dev/null", O_RDONLY | O_CLOEXEC);
                if (fd < 0) break;
                fillers.push_back(fd);
            }
            CHECK(errno == EMFILE && fillers.size() >= holes);
            for (unsigned i = 0; i < holes; ++i) { CHECK(close(fillers.back()) == 0); fillers.pop_back(); }
            inject(); VkResult result = submit(f, false, waits, signals);
            CHECK(setrlimit(RLIMIT_NOFILE, &old_limit) == 0);
            for (int fd : fillers) CHECK(close(fd) == 0);
            // Baseline peaks measured by the same actual-function fixture.
            unsigned baseline_minimum = nw ? nw + 4 : (ns ? 1 : 0);
            if (holes >= baseline_minimum) CHECK(result == VK_SUCCESS);
            if (result == VK_SUCCESS) {
                ++successful;
                if (ns) CHECK(drm.at(201) == expected);
            }
            ++cases;
        }
        clean();
    }
    std::printf("PASS: %u real RLIMIT_NOFILE headroom cases (%u successful), explicit dependencies retained.\n", cases, successful);
}

int main()
{
    unsetenv("TU_KGSL_CONTEXT_PRIORITIES");
    CHECK(kgsl_submitqueue_priority_count() == 1);
    cache_resource_failures(); real_fd_headroom();
    repeated_empty(); replacement_and_sparse(); missing_cache_merged_completion(); independent_queues();
    optional_cache_failure(); native_mode(); context_lifecycle(); faults();
    std::printf("PASS: %s, %u clean ownership cases; actual queue lifecycle/native submits/DRM bridge/merge/export. Modeled ioctls, no GPU hardware.\n",
                HAS_CACHE ? "cached completion eliminates repeated empty-submit timestamp exports" : "baseline reproduces repeated empty-submit timestamp exports", assertions);
}
