#define main controller_fixture_main
#include "pico-steamvr-controller.cpp"
#undef main
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>

static std::string command_line;
static FILE *fixture_cmdline()
{
    FILE *file=tmpfile();assert(file);
    assert(std::fwrite(command_line.data(),1,command_line.size(),file)==command_line.size());
    std::rewind(file);return file;
}

#include "provider-under-test.cpp"

int main(int argc,char **argv)
{
    assert(argc==3);
    std::string head_path=std::string(argv[2])+"/head",input_path=std::string(argv[2])+"/input";
    int fd=open(head_path.c_str(),O_RDWR|O_CREAT|O_EXCL,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(pico_slam_channel)));
    auto *head=static_cast<pico_slam_channel *>(mmap(nullptr,sizeof(pico_slam_channel),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
    assert(head!=MAP_FAILED&&pico_slam_channel_init(head,101));close(fd);
    assert(!munmap(head,sizeof(*head)));
    fd=open(input_path.c_str(),O_RDWR|O_CREAT|O_EXCL,0600);assert(fd>=0);
    assert(!ftruncate(fd,sizeof(pico_controller_channel)));
    auto *input=static_cast<pico_controller_channel *>(mmap(nullptr,sizeof(pico_controller_channel),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
    assert(input!=MAP_FAILED&&pico_controller_channel_init(input,201));close(fd);
    assert(!munmap(input,sizeof(*input)));
    assert(!setenv("PICO_STEAMVR_OPTICS",argv[1],1));
    assert(!setenv("PICO_STEAMVR_POSE_CHANNEL",head_path.c_str(),1));
    assert(!setenv("PICO_STEAMVR_MAX_AGE_NS","100000000",1));
    assert(!setenv("PICO_STEAMVR_BOOT_SERIAL","fixture",1));
    assert(!setenv("PICO_STEAMVR_INSTANCE","0000000000000065",1));
    assert(!setenv("PICO_STEAMVR_GENERATION","0000000000000001",1));
    assert(!setenv("PICO_STEAMVR_CONTROLLER_CHANNEL",input_path.c_str(),1));
    assert(!setenv("PICO_STEAMVR_CONTROLLER_INSTANCE","00000000000000c9",1));
    Context context;context.host.reject_controller=true;
    for (const char *text : {"androidboot.serialno=fixture androidboot.serialno=other\n",
                             "androidboot.serialno=fixture androidboot.serialno=fixture\n"}) {
        command_line=text;PicoProvider provider;
        assert(provider.Init(&context)==VRInitError_Driver_Failed);
        assert(!context.host.registered_hmd);
    }
    command_line="androidboot.serialno=fixture\n";
    PicoProvider provider;
    assert(provider.Init(&context)==VRInitError_None);
    assert(context.host.registered_hmd);
    auto pose=context.host.registered_hmd->GetPose();assert(!pose.poseIsValid);
    provider.RunFrame();provider.Cleanup();
    puts("PICO_STEAMVR_PROVIDER_PASS rejected_controller_retains_hmd=1 duplicate_serials=2");
}
