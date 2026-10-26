#include "pico-steamvr-display.h"
#include <cJSON.h>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

static const cJSON *field(const cJSON *object, const char *name)
{
    if (!cJSON_IsObject(object)) return nullptr;
    const cJSON *found=nullptr;
    for (const cJSON *p=object->child; p; p=p->next) {
        if (!std::strcmp(p->string,name)) { if (found) return nullptr; found=p; }
    }
    return found;
}

static bool number(const cJSON *value, double low, double high, double &out)
{
    if (!cJSON_IsNumber(value) || !std::isfinite(value->valuedouble) ||
        value->valuedouble<low || value->valuedouble>high) return false;
    out=value->valuedouble; return true;
}

static bool integer(const cJSON *value, uint32_t low, uint32_t high, uint32_t &out)
{
    double n;
    if (!number(value,low,high,n) || std::floor(n)!=n) return false;
    out=static_cast<uint32_t>(n); return true;
}

static bool array(const cJSON *value, unsigned count, double *out)
{
    if (!cJSON_IsArray(value) || cJSON_GetArraySize(value)!=static_cast<int>(count)) return false;
    for (unsigned i=0; i<count; ++i)
        if (!number(cJSON_GetArrayItem(value,static_cast<int>(i)),-1000000,1000000,out[i])) return false;
    return true;
}

static bool parse(const cJSON *json, pico_steamvr_display_config &c)
{
    uint32_t version;
    const cJSON *device=field(json,"device"), *serial=field(json,"serial"), *screen=field(json,"screen");
    if (!integer(field(json,"schema_version"),2,3,version) ||
        !cJSON_IsString(device) || std::strcmp(device->valuestring,"PICOA7H10") ||
        !cJSON_IsString(serial) || !serial->valuestring[0] || std::strlen(serial->valuestring)>=sizeof(c.serial)) return false;
    std::strcpy(c.serial,serial->valuestring);
    uint32_t interval;
    if (!integer(field(screen,"width"),1,16384,c.width) ||
        !integer(field(screen,"height"),1,16384,c.height) ||
        !integer(field(screen,"frame_interval_ns"),1000000,100000000,interval)) return false;
    c.frame_interval_ns=interval;
    const cJSON *views=field(json,"views");
    if (!cJSON_IsArray(views) || cJSON_GetArraySize(views)!=2) return false;
    for (unsigned i=0; i<2; ++i) {
        auto &v=c.views[i];
        const cJSON *item=cJSON_GetArrayItem(views,static_cast<int>(i));
        const cJSON *viewport=field(item,"viewport"), *render=field(item,"display");
        if (!cJSON_IsArray(viewport) || cJSON_GetArraySize(viewport)!=4 ||
            !cJSON_IsArray(render) || cJSON_GetArraySize(render)!=2) return false;
        for (unsigned j=0; j<4; ++j)
            if (!integer(cJSON_GetArrayItem(viewport,static_cast<int>(j)),j<2?0:1,16384,v.viewport[j])) return false;
        for (unsigned j=0; j<2; ++j)
            if (!integer(cJSON_GetArrayItem(render,static_cast<int>(j)),1,16384,v.render[j])) return false;
        const cJSON *radial=field(item,"analytic_distortion"), *type=field(radial,"type");
        if (cJSON_GetObjectItemCaseSensitive(item,"distortion") ||
            cJSON_GetObjectItemCaseSensitive(item,"grid_width") ||
            cJSON_GetObjectItemCaseSensitive(item,"grid_height") ||
            !cJSON_IsString(type) || std::strcmp(type->valuestring,"pico-radial-2") ||
            !array(field(item,"rotation"),4,v.rotation) || !array(field(item,"fov"),4,v.fov) ||
            !array(field(item,"eye_pose"),7,v.eye_pose) ||
            !array(field(radial,"tangent_scale"),2,v.tangent_scale) ||
            !array(field(radial,"tangent_offset"),2,v.tangent_offset) ||
            !array(field(radial,"radial_coefficients"),11,v.radial) ||
            !array(field(radial,"chromatic_coefficients"),6,v.chromatic)) return false;
    }
    return pico_steamvr_display_valid(c);
}

bool pico_steamvr_display_load(const char *path, pico_steamvr_display_config &config)
{
    if (!path) return false;
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if (fd<0) return false;
    struct stat st;
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size<=0 || st.st_size>256*1024) {close(fd);return false;}
    std::vector<char> data(static_cast<size_t>(st.st_size)+1,0);
    size_t used=0;
    while (used<static_cast<size_t>(st.st_size)) {
        ssize_t n=read(fd,data.data()+used,static_cast<size_t>(st.st_size)-used);
        if (n<0 && errno==EINTR) continue;
        if (n<=0) {close(fd);return false;}
        used+=static_cast<size_t>(n);
    }
    char extra;
    bool exact=read(fd,&extra,1)==0; close(fd);
    if (!exact || std::memchr(data.data(),0,used)) return false;
    for (size_t i=0;i<used;++i) if (data[i]=='\\') {
        if (i+5<used && !std::memcmp(data.data()+i+1,"u0000",5)) return false;
        ++i;
    }
    cJSON *json=cJSON_ParseWithLengthOpts(data.data(),data.size(),nullptr,true);
    pico_steamvr_display_config candidate{};
    bool ok=json && parse(json,candidate);
    cJSON_Delete(json);
    if (ok) config=candidate;
    return ok;
}
