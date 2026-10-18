#include "tu_kgsl_drm_sync.h"

#include <assert.h>
#include <stdbool.h>
#include <stdio.h>

enum operation { CREATE, TRANSFER, EXPORT, IMPORT, SIGNAL, DESTROY, OPERATIONS };
static unsigned calls[OPERATIONS];
static int fail = -1;
static bool timelines;

static int result(enum operation op)
{
    calls[op]++;
    if (fail == (int)op) { errno = EIO; return -1; }
    return 0;
}

int drmSyncobjCreate(int fd, uint32_t flags, uint32_t *handle)
{
    assert(timelines && fd == 7 && flags <= 1);
    int ret = result(CREATE);
    if (!ret) *handle = 99;
    return ret;
}

int drmSyncobjDestroy(int fd, uint32_t handle)
{
    assert(timelines && fd == 7 && handle == 99);
    calls[DESTROY]++;
    errno = EBADF;
    return 0;
}

int drmSyncobjTransfer(int fd, uint32_t dst, uint64_t dst_point,
                       uint32_t src, uint64_t src_point, uint32_t flags)
{
    assert(timelines && fd == 7 && !flags);
    assert((dst == 99 && !dst_point && src == 67 && src_point == 17) ||
           (src == 99 && !src_point && dst == 67 && dst_point == 17));
    return result(TRANSFER);
}

int drmSyncobjExportSyncFile(int fd, uint32_t handle, int *out)
{
    assert(fd == 7 && handle == (timelines ? 99u : 67u));
    int ret = result(EXPORT);
    if (!ret) *out = 42;
    return ret;
}

int drmSyncobjImportSyncFile(int fd, uint32_t handle, int input)
{
    assert(fd == 7 && handle == (timelines ? 99u : 67u) && input == 42);
    return result(IMPORT);
}

int drmSyncobjSignal(int fd, const uint32_t *handles, uint32_t count)
{
    assert(!timelines && fd == 7 && count == 1 && handles[0] == 67);
    return result(SIGNAL);
}

int main(void)
{
    for (unsigned cycle = 0; cycle < 128; cycle++) {
        int fd = 123;
        assert(!tu_kgsl_drm_export_wait(7, 67, 0, &fd) && fd == 42);
        assert(!tu_kgsl_drm_import_signal(7, 67, 0, fd));
        assert(!tu_kgsl_drm_import_signal(7, 67, 0, -1));
    }
    assert(calls[CREATE] == 0 && calls[TRANSFER] == 0 && calls[DESTROY] == 0);
    assert(calls[EXPORT] == 128 && calls[IMPORT] == 128 && calls[SIGNAL] == 128);
    int fd;
    fail = EXPORT;
    assert(tu_kgsl_drm_export_wait(7, 67, 0, &fd) == -1 && fd == -1 && errno == EIO);
    fail = IMPORT;
    assert(tu_kgsl_drm_import_signal(7, 67, 0, 42) == -1 && errno == EIO);
    fail = SIGNAL;
    assert(tu_kgsl_drm_import_signal(7, 67, 0, -1) == -1 && errno == EIO);
    timelines = true;
    fail = -1;
    assert(!tu_kgsl_drm_export_wait(7, 67, 17, &fd) && fd == 42);
    assert(!tu_kgsl_drm_import_signal(7, 67, 17, fd));
    assert(!tu_kgsl_drm_import_signal(7, 67, 17, -1));
    for (unsigned op = CREATE; op <= IMPORT; op++) {
        fail = (int)op;
        if (op != IMPORT)
            assert(tu_kgsl_drm_export_wait(7, 67, 17, &fd) == -1 && fd == -1 && errno == EIO);
        if (op != EXPORT)
            assert(tu_kgsl_drm_import_signal(7, 67, 17, 42) == -1 && errno == EIO);
    }
    puts("KGSL_DRM_BINARY_PASS");
    return 0;
}
