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
    {
        PicoProvider provider;
        assert(provider.Init(&context)==VRInitError_None);
        assert(context.host.registered_hmd);
        auto pose=context.host.registered_hmd->GetPose();assert(!pose.poseIsValid);
        provider.RunFrame();provider.Cleanup();
    }
    auto make_poses=[&](const char *name,uint64_t instance) {
        std::string path=std::string(argv[2])+"/"+name;
        int pose_fd=open(path.c_str(),O_RDWR|O_CREAT|O_EXCL,0600);assert(pose_fd>=0);
        assert(!ftruncate(pose_fd,sizeof(pico_slam_channel)));
        auto *poses=static_cast<pico_slam_channel *>(mmap(nullptr,sizeof(pico_slam_channel),
            PROT_READ|PROT_WRITE,MAP_SHARED,pose_fd,0));assert(poses!=MAP_FAILED);close(pose_fd);
        assert(pico_slam_channel_init(poses,instance) && pico_slam_channel_begin(poses,1));return poses;
    };
    auto *left=make_poses("left",301),*right=make_poses("right",401);
    std::string left_path=std::string(argv[2])+"/left",right_path=std::string(argv[2])+"/right";
    auto bind=[&](const char *hand,const char *path,const char *instance) {
        std::string key="PICO_STEAMVR_"+std::string(hand)+"_POSE_";
        assert(!(path?setenv((key+"CHANNEL").c_str(),path,1):unsetenv((key+"CHANNEL").c_str())));
        assert(!(instance?setenv((key+"INSTANCE").c_str(),instance,1):unsetenv((key+"INSTANCE").c_str())));
    };
    auto publish=[&](pico_slam_channel *poses,double x) {
        auto now=now_ns();pico_slam_channel_sample sample{};
        sample.generation=1;sample.timestamp_ns=now-1000000;sample.published_ns=now;
        sample.pose.orientation[3]=1;sample.pose.position[0]=x;
        assert(pico_slam_channel_publish(poses,&sample));
    };
    for (unsigned binding=0;binding<4;++binding) {
        bind("LEFT",binding&1?left_path.c_str():nullptr,binding&1?"000000000000012d":nullptr);
        bind("RIGHT",binding&2?right_path.c_str():nullptr,binding&2?"0000000000000191":nullptr);
        Context dual;dual.host.register_controllers=true;PicoProvider provider;
        assert(provider.Init(&dual)==VRInitError_None && dual.host.controllers.size()==2);
        auto *l=dual.host.controllers.at("-left"),*r=dual.host.controllers.at("-right");
        assert(l!=r && l->Activate(3)==VRInitError_None && r->Activate(4)==VRInitError_None);
        for (unsigned hand=1;hand<=2;++hand) {
            pico_controller_sample sample{};sample.hand=hand;sample.buttons=4;
            assert(pico_controller_channel_publish(input,&sample,now_ns()));
        }
        publish(left,-.3);publish(right,.4);provider.RunFrame();
        assert(dual.input.values.at("/input/x/click") && dual.input.values.at("/input/a/click"));
        assert(l->GetPose().poseIsValid==bool(binding&1) && r->GetPose().poseIsValid==bool(binding&2));
        if (binding&1) assert(l->GetPose().vecPosition[0]==-.3);
        if (binding&2) assert(r->GetPose().vecPosition[0]==.4);
        assert(pico_controller_channel_disconnect(input,1));provider.RunFrame();
        assert(!l->GetPose().deviceIsConnected && !l->GetPose().poseIsValid);
        assert(r->GetPose().deviceIsConnected && r->GetPose().poseIsValid==bool(binding&2));
        assert(!dual.input.values.at("/input/x/click") && dual.input.values.at("/input/a/click"));
        provider.Cleanup();
    }
    bind("LEFT",left_path.c_str(),"000000000000012d");
    for (unsigned bad=0;bad<7;++bad) {
        bind("RIGHT",right_path.c_str(),"0000000000000191");
        std::string alias=std::string(argv[2])+"/alias";
        if (bad==0) bind("RIGHT",right_path.c_str(),nullptr);
        if (bad==1) bind("RIGHT",nullptr,"0000000000000191");
        if (bad==2) bind("RIGHT",head_path.c_str(),"0000000000000191");
        if (bad==3) bind("RIGHT",right_path.c_str(),"000000000000012d");
        if (bad==4) {
            assert(!link(left_path.c_str(),alias.c_str()));bind("RIGHT",alias.c_str(),"0000000000000191");
        }
        if (bad==5) assert(!chmod(right_path.c_str(),0666));
        if (bad==6) bind("RIGHT",right_path.c_str(),"0000000000000065");
        Context invalid;invalid.host.register_controllers=true;PicoProvider provider;
        assert(provider.Init(&invalid)==VRInitError_Driver_Failed && !invalid.host.registered_hmd);
        provider.Cleanup();
        if (bad==4) assert(!unlink(alias.c_str()));
        if (bad==5) assert(!chmod(right_path.c_str(),0600));
    }
    bind("LEFT",nullptr,nullptr);bind("RIGHT",nullptr,nullptr);
    {
        Context partial;partial.host.register_controllers=true;partial.host.reject_hand=2;
        PicoProvider provider;assert(provider.Init(&partial)==VRInitError_None);
        assert(partial.host.registered_hmd && partial.host.controllers.size()==1);
        assert(partial.host.controllers.at("-left")->Activate(3)==VRInitError_None);
        provider.RunFrame();provider.Cleanup();
    }
    assert(!munmap(left,sizeof(*left)) && !munmap(right,sizeof(*right)) && !munmap(input,sizeof(*input)));
    puts("PICO_STEAMVR_PROVIDER_PASS rejected_controller_retains_hmd=1 duplicate_serials=2 dual_hand_bindings=4 invalid_bindings=7");
}
