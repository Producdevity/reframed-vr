#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef int Bool;
typedef uint32_t Atom;
enum { FALSE, TRUE, XA_INTEGER = 19, XA_ATOM = 4 };
enum { DRM_MODE_PROP_RANGE = 2, DRM_MODE_PROP_ENUM = 8 };
struct drm_mode_property_enum { uint64_t value; char name[32]; };
struct mode_property {
    unsigned flags, prop_id;
    int count_enums;
    struct drm_mode_property_enum *enums;
};
typedef struct {
    struct mode_property *mode_prop;
    uint64_t value;
    int num_atoms;
    Atom *atoms;
} drmmode_prop_rec, *drmmode_prop_ptr;
typedef struct { int fd; } drmmode_rec, *drmmode_ptr;
typedef struct {
    drmmode_ptr drmmode;
    int num_props;
    drmmode_prop_ptr props;
    unsigned output_id;
    Atom ctm_atom;
    uint64_t ctm[9];
} drmmode_output_private_rec, *drmmode_output_private_ptr;
typedef struct { void *driver_private; void *crtc; } xf86OutputRec, *xf86OutputPtr;
typedef struct { Atom type; int format; size_t size; void *data; } RRPropertyValueRec, *RRPropertyValuePtr;

static unsigned writes, matrix_updates;
static uint64_t last_value;
static int drmModeConnectorSetProperty(int fd, unsigned output, unsigned property,
                                       uint64_t value)
{
    assert(fd == 5 && output == 29 && property == 80);
    writes++;
    last_value = value;
    return 0;
}
static const char *NameForAtom(Atom atom) { return atom == 7 ? "enabled" : NULL; }
static void drmmode_set_ctm(void *crtc, const uint64_t (*ctm)[9])
{
    assert(crtc && (*ctm)[0] == 123);
    matrix_updates++;
}

#include "driver.inc"

int main(void)
{
    drmmode_rec drm = {5};
    struct mode_property range = {.flags = DRM_MODE_PROP_RANGE, .prop_id = 80};
    struct drm_mode_property_enum values[] = {{42, "enabled"}};
    struct mode_property enumeration = {
        .flags = DRM_MODE_PROP_ENUM, .prop_id = 80, .count_enums = 1, .enums = values,
    };
    Atom range_atom[] = {9}, enum_atoms[] = {10, 7};
    drmmode_prop_rec props[] = {
        {.num_atoms = 0, .atoms = NULL},
        {.mode_prop = &range, .num_atoms = 1, .atoms = range_atom},
        {.num_atoms = 1, .atoms = NULL},
        {.mode_prop = &enumeration, .num_atoms = 2, .atoms = enum_atoms},
    };
    drmmode_output_private_rec private = {&drm, 4, props, 29, 20, {0}};
    xf86OutputRec output = {&private, &private};
    uint32_t data = 12;
    RRPropertyValueRec value = {
        XA_INTEGER, 32, 1, &data,
    };
    assert(drmmode_output_set_property((xf86OutputPtr)&output, 9,
                                       (RRPropertyValuePtr)&value));
    assert(writes == 1 && last_value == 12);
    value.type = XA_ATOM;
    assert(!drmmode_output_set_property((xf86OutputPtr)&output, 9,
                                        (RRPropertyValuePtr)&value));
    assert(writes == 1);
    data = 7;
    assert(drmmode_output_set_property((xf86OutputPtr)&output, 10,
                                       (RRPropertyValuePtr)&value));
    assert(writes == 2 && last_value == 42);
    data = 8;
    assert(!drmmode_output_set_property((xf86OutputPtr)&output, 10,
                                        (RRPropertyValuePtr)&value));
    assert(writes == 2);
    assert(drmmode_output_set_property((xf86OutputPtr)&output, 99,
                                       (RRPropertyValuePtr)&value));
    uint64_t matrix[9] = {123};
    value.type = XA_INTEGER; value.size = 18; value.data = matrix;
    assert(drmmode_output_set_property((xf86OutputPtr)&output, 20,
                                       (RRPropertyValuePtr)&value));
    assert(matrix_updates == 1 && private.ctm[0] == 123);
    value.size = 17;
    assert(!drmmode_output_set_property((xf86OutputPtr)&output, 20,
                                        (RRPropertyValuePtr)&value));
    assert(matrix_updates == 1);
    puts("unexposed DRM properties skipped; range, enum and CTM paths preserved");
    return 0;
}
