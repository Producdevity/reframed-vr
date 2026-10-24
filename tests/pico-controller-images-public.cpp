#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <time.h>
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
template<typename T> static T function(void *handle, const char *name)
{
    auto result = reinterpret_cast<T>(dlsym(handle,name));
    if (!result) { fprintf(stderr,"%s: %s\n",name,dlerror()); exit(2); }
    return result;
}
static int64_t now()
{
    uint64_t ticks,frequency;
    asm volatile("mrs %0,cntvct_el0" : "=r"(ticks));
    asm volatile("mrs %0,cntfrq_el0" : "=r"(frequency));
    assert(frequency==19200000);
    return static_cast<int64_t>((static_cast<__int128>(ticks)*1000000000)/frequency);
}
static void head(unsigned char *record,int64_t timestamp)
{
    memset(record,0,368);memcpy(record,&timestamp,8);
    double one=1;memcpy(record+56,&one,8);record[64]=record[65]=1;
}
int main(int argc,char **argv)
{
    setvbuf(stdout,nullptr,_IONBF,0);assert(argc==2);alarm(90);
    void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if(!library){fprintf(stderr,"tracker: %s\n",dlerror());return 2;}
    auto configure=function<int(*)(void*)>(RTLD_DEFAULT,"pico_controller_images_configure");
    auto prepare=function<int(*)(uint64_t,const void*const*,size_t,const void**)>(RTLD_DEFAULT,"pico_controller_images_prepare");
    auto done=function<int(*)(uint64_t)>(RTLD_DEFAULT,"pico_controller_images_completed");
    auto copies=function<uint64_t(*)()>(RTLD_DEFAULT,"pico_controller_images_adoptions");
    auto init=function<int(*)(void*,void*)>(library,"alg_controller_init");
    auto stop=function<int(*)()>(library,"alg_controller_stop");
    auto image=function<int(*)(void*,const void*,const void*)>(library,"alg_controller_update_all_image_with_head");
    assert(configure(library)==0);
    int init_rc=init(nullptr,nullptr);printf("PUBLIC_OWNER_INIT rc=%d\n",init_rc);assert(init_rc==0);
    constexpr size_t plane=640*480,bytes=4*plane;
    auto source=static_cast<unsigned char*>(mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0));assert(source!=MAP_FAILED);
    std::vector<Frame> frames(4);unsigned completed=0;
    for(unsigned iteration=0;iteration<300;++iteration){
        assert(mprotect(source,bytes,PROT_READ|PROT_WRITE)==0);memset(source,iteration%251+1,bytes);
        std::array<const void*,4> input,output;for(unsigned i=0;i<4;++i)input[i]=source+i*plane;
        int prepared=prepare(iteration+1,input.data(),plane,output.data());
        printf("PUBLIC_OWNER_PREPARE set=%u rc=%d\n",iteration+1,prepared);assert(prepared==0);
        for(unsigned i=0;i<4;++i)assert(!memcmp(output[i],input[i],plane));
        assert(mprotect(source,bytes,PROT_NONE)==0);
        int64_t timestamp=now();
        for(unsigned i=0;i<4;++i)frames[i]={static_cast<uint8_t>(i),{},640,480,0x20203859,0,40,16,0,timestamp,timestamp,iteration+1,plane,0,static_cast<const uint8_t*>(output[i])};
        unsigned char before[368],after[368];head(before,timestamp-1000000);head(after,timestamp+1000000);
        int rc=image(&frames,before,after);assert(rc==0);int result=0;
        for(unsigned poll=0;poll<1000;++poll){result=done(iteration+1);if(result)break;usleep(1000);}
        printf("PUBLIC_OWNER_COMPLETION set=%u rc=%d done=%d adoptions=%llu\n",iteration+1,rc,result,static_cast<unsigned long long>(copies()));assert(result==1);
        ++completed;
    }
    int stop_rc=stop();assert(stop_rc==0);struct rusage usage{};assert(getrusage(RUSAGE_SELF,&usage)==0);
    printf("PICO_IMAGE_OWNER_PUBLIC_PASS sets=%u adoptions=%llu stop_rc=%d maxrss_kib=%ld hardware_tracking=0\n",completed,static_cast<unsigned long long>(copies()),stop_rc,usage.ru_maxrss);
    _Exit(0);
}
