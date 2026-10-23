#include "pico-steamvr-pose.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include "pico-vendor-slam-output.h"

struct Replay {
    uint8_t bytes[PICO_SLAM_RESULT_SIZE];
    int64_t now;
};

static int get_result(void *data, void *bytes)
{
    std::memcpy(bytes, static_cast<Replay *>(data)->bytes, PICO_SLAM_RESULT_SIZE);
    return 0;
}
static int64_t clock_ns(void *data) { return static_cast<Replay *>(data)->now; }

static void near(double a, double b) { assert(std::fabs(a-b)<1e-9); }
static void invalid(const vr::DriverPose_t &p, bool connected=true)
{
    assert(p.deviceIsConnected==connected&&!p.poseIsValid&&!p.shouldApplyHeadModel);
    assert(p.result==vr::TrackingResult_Uninitialized);
    assert(p.qWorldFromDriverRotation.w==1&&p.qDriverFromHeadRotation.w==1&&p.qRotation.w==1);
    for(unsigned i=0;i<3;++i)assert(p.vecPosition[i]==0&&p.vecVelocity[i]==0);
}

struct ReadClock {
    pico_slam_channel *channel;
    pico_slam_channel_sample next;
    int64_t now;
    unsigned calls;
};

static int64_t after_snapshot(void *data)
{
    auto &c=*static_cast<ReadClock *>(data);
    ++c.calls;
    if (c.channel) {
        assert(pico_slam_channel_publish(c.channel,&c.next));
        c.channel=nullptr;
    }
    return c.now;
}

static void publication_clock_race()
{
    pico_slam_channel channel{};
    assert(pico_slam_channel_init(&channel,51)&&pico_slam_channel_begin(&channel,1));
    pico_slam_channel_sample sample{};
    sample.generation=1;sample.timestamp_ns=999000000;sample.published_ns=1000000001;
    sample.uncertainty_ns=100;sample.pose.orientation[3]=1;sample.pose.position[0]=3;
    assert(pico_slam_channel_publish(&channel,&sample));
    // The publisher advances between the original clock sample and channel copy.
    invalid(pico_steamvr_pose(&channel,51,1,1000000000,100000000,true));
    ReadClock clock{};clock.now=1000000002;
    pico_slam_read_result status=PICO_SLAM_READ_REFUSED;
    auto pose=pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status);
    assert(status==PICO_SLAM_READ_OK && pose.poseIsValid && clock.calls==1);
    near(pose.poseTimeOffset,-.001000002);

    clock.channel=&channel;clock.next=sample;clock.next.timestamp_ns=1000000001;
    clock.next.published_ns=1000001000;clock.next.pose.position[0]=9;clock.now=1000002000;
    pose=pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status);
    assert(status==PICO_SLAM_READ_OK && pose.poseIsValid && clock.calls==2);
    near(pose.vecPosition[0],3);near(pose.poseTimeOffset,-.001002);
    clock.now=1000000000;
    invalid(pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status));
    assert(status==PICO_SLAM_READ_FUTURE);
    clock.now=1200000000;
    invalid(pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status));
    assert(status==PICO_SLAM_READ_STALE);
    __atomic_store_n(&channel.sequence,7,__ATOMIC_RELEASE);
    clock.now=1000002000;
    channel.slots[0][9]=UINT64_MAX;
    pose=pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status);
    assert(status==PICO_SLAM_READ_OK && pose.poseIsValid);
    near(pose.vecPosition[0],9);
    __atomic_store_n(&channel.sequence,6,__ATOMIC_RELEASE);
    assert(pico_slam_channel_stop(&channel,1));
    unsigned calls=clock.calls;
    invalid(pico_steamvr_pose_now(&channel,51,1,100000000,true,after_snapshot,&clock,&status));
    assert(status==PICO_SLAM_READ_INACTIVE && clock.calls==calls);
    invalid(pico_steamvr_pose_now(&channel,51,2,100000000,true,after_snapshot,&clock,&status));
    assert(status==PICO_SLAM_READ_REFUSED && clock.calls==calls);
}

static void head_motion_convention()
{
    const double basis=std::sqrt(.5), angle=.3;
    pico_slam_pose_config config{};
    config.world_from_slam.orientation[2]=config.world_from_slam.orientation[3]=basis;
    config.body_from_head.orientation[2]=-basis;config.body_from_head.orientation[3]=basis;
    config.direction=PICO_SLAM_WORLD_FROM_BODY;config.metres_per_unit=1;config.max_age_ns=100000000;
    for (int direction : {-1,1}) {
        pico_slam_channel channel{};assert(pico_slam_channel_init(&channel,91));
        assert(pico_slam_channel_begin(&channel,1));
        pico_slam_result raw{};raw.timestamp_ns=1000000000;raw.state=raw.confidence=1;
        raw.orientation[0]=std::sin(direction*angle/2);raw.orientation[3]=std::cos(angle/2);
        assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,100,1001000000)==PICO_SLAM_CHANNEL_PUBLISHED);
        auto pose=pico_steamvr_pose(&channel,91,1,1001000000,100000000,true);
        assert(pose.poseIsValid);
        near(pose.qRotation.x,0);near(pose.qRotation.y,std::sin(direction*angle/2));
        near(pose.qRotation.z,0);near(pose.qRotation.w,std::cos(angle/2));
        // A world-fixed point in front moves right in head space during a left yaw.
        const double view_x=4*pose.qRotation.w*pose.qRotation.y;
        near(view_x,2*std::sin(direction*angle));assert(direction*view_x>0);
        assert(pico_slam_channel_begin(&channel,2));
        raw.orientation[0]=0;raw.orientation[1]=-std::sin(direction*angle/2);
        assert(pico_slam_channel_publish_result(&channel,2,&config,&raw,100,1001000000)==PICO_SLAM_CHANNEL_PUBLISHED);
        pose=pico_steamvr_pose(&channel,91,2,1001000000,100000000,true);
        near(pose.qRotation.x,std::sin(direction*angle/2));near(pose.qRotation.y,0);
        const double view_y=-4*pose.qRotation.w*pose.qRotation.x;
        near(view_y,-2*std::sin(direction*angle));assert(direction*view_y<0);
        assert(pico_slam_channel_begin(&channel,3));
        raw.orientation[1]=0;raw.orientation[3]=1;raw.position[1]=-.2*direction;
        assert(pico_slam_channel_publish_result(&channel,3,&config,&raw,100,1001000000)==PICO_SLAM_CHANNEL_PUBLISHED);
        pose=pico_steamvr_pose(&channel,91,3,1001000000,100000000,true);
        near(pose.vecPosition[0],.2*direction);near(pose.vecPosition[1],0);
        near(pose.qRotation.w,1);
    }
}

int main(int argc, char **argv)
{
    publication_clock_race();
    head_motion_convention();
    pico_slam_channel channel{};
    assert(pico_slam_channel_init(&channel,42)&&pico_slam_channel_begin(&channel,1));
    const int64_t now=1002000000,age=100000000;
    invalid(pico_steamvr_pose(&channel,42,1,now,age,true));
    invalid(pico_steamvr_pose(&channel,42,1,now,age,false),false);
    const double s=std::sqrt(.5);
    pico_slam_pose_config c{};
    c.world_from_slam.orientation[2]=c.world_from_slam.orientation[3]=s;
    c.world_from_slam.position[0]=10;c.world_from_slam.position[1]=20;c.world_from_slam.position[2]=30;
    c.body_from_head.orientation[0]=c.body_from_head.orientation[3]=s;c.body_from_head.position[0]=.1;
    c.direction=PICO_SLAM_WORLD_FROM_BODY;c.metres_per_unit=1;c.max_age_ns=age;
    pico_slam_result r{};
    r.timestamp_ns=1000000000;r.position[0]=1;r.position[1]=2;r.position[2]=3;
    r.orientation[1]=r.orientation[3]=s;r.state=1;r.confidence=0;r.error=512;
    assert(pico_slam_channel_publish_result(&channel,1,&c,&r,1000,now)==PICO_SLAM_CHANNEL_WAITING);
    invalid(pico_steamvr_pose(&channel,42,1,now,age,true));
    r.confidence=1;
    assert(pico_slam_channel_publish_result(&channel,1,&c,&r,1000,now)==PICO_SLAM_CHANNEL_PUBLISHED);
    auto p=pico_steamvr_pose(&channel,42,1,now,age,true);
    assert(p.poseIsValid&&p.deviceIsConnected&&p.result==vr::TrackingResult_Running_OK);
    assert(!p.shouldApplyHeadModel&&!p.willDriftInYaw);
    near(p.vecPosition[0],8);near(p.vecPosition[1],21);near(p.vecPosition[2],32.9);
    near(p.qRotation.w,s);near(p.qRotation.x,0);near(p.qRotation.y,s);near(p.qRotation.z,0);
    near(p.poseTimeOffset,-.002);
    invalid(pico_steamvr_pose(&channel,42,1,r.timestamp_ns+age,age,true));
    invalid(pico_steamvr_pose(&channel,42,1,r.timestamp_ns-1,age,true));
    invalid(pico_steamvr_pose(&channel,43,1,now,age,true));
    invalid(pico_steamvr_pose(&channel,42,2,now,age,true));
    invalid(pico_steamvr_pose(&channel,42,1,now,age,false),false);
    r.confidence=0;r.timestamp_ns+=1000;
    assert(pico_slam_channel_publish_result(&channel,1,&c,&r,1000,now)==PICO_SLAM_CHANNEL_REFUSED);
    invalid(pico_steamvr_pose(&channel,42,1,now,age,true));
    r.confidence=1;
    assert(pico_slam_channel_publish_result(&channel,1,&c,&r,1000,now)==PICO_SLAM_CHANNEL_REFUSED);
    assert(pico_slam_channel_begin(&channel,2));
    assert(pico_slam_channel_publish_result(&channel,2,&c,&r,1000,now)==PICO_SLAM_CHANNEL_PUBLISHED);
    invalid(pico_steamvr_pose(&channel,42,1,now,age,true));
    assert(pico_steamvr_pose(&channel,42,2,now,age,true).poseIsValid);
    assert(pico_slam_channel_stop(&channel,2));invalid(pico_steamvr_pose(&channel,42,2,now,age,true));
    unsigned records=0,published=0;
    if (argc==2) {
        FILE *file=std::fopen(argv[1],"rb");assert(file);
        Replay replay{};
        assert(pico_slam_channel_init(&channel,77));
        pico_vendor_slam_output_config config{};
        config.channel=&channel;config.generation=1;
        config.pose.world_from_slam.orientation[3]=config.pose.body_from_head.orientation[3]=1;
        config.pose.direction=PICO_SLAM_WORLD_FROM_BODY;config.pose.metres_per_unit=1;config.pose.max_age_ns=age;
        config.uncertainty_ns=1000;config.handle=config.clock_data=&replay;
        config.get_result=get_result;config.monotonic_ns=clock_ns;
        pico_vendor_slam_output *output=nullptr;
        assert(!pico_vendor_slam_output_create(&config,&output));
        size_t count;
        while ((count=std::fread(replay.bytes,1,sizeof(replay.bytes),file))) {
            pico_slam_result decoded{};
            assert(count==sizeof(replay.bytes)&&pico_slam_result_decode(replay.bytes,count,&decoded));
            replay.now=decoded.timestamp_ns+2000000;
            auto rc=pico_vendor_slam_output_callback(output);
            auto pose=pico_steamvr_pose(&channel,77,1,replay.now,age,true);
            if (decoded.state==1&&decoded.confidence==1) {
                assert(rc==PICO_SLAM_CHANNEL_PUBLISHED&&pose.poseIsValid);
                for (unsigned i=0;i<3;++i) near(pose.vecPosition[i],decoded.position[i]);
                near(pose.qRotation.w,decoded.orientation[3]);
                near(pose.qRotation.x,decoded.orientation[0]);
                near(pose.qRotation.y,decoded.orientation[1]);
                near(pose.qRotation.z,decoded.orientation[2]);
                near(pose.poseTimeOffset,-.002);++published;
            } else {assert(rc==PICO_SLAM_CHANNEL_WAITING);invalid(pose);}
            ++records;
        }
        assert(!std::ferror(file));std::fclose(file);
        pico_vendor_slam_output_stop(output);
        invalid(pico_steamvr_pose(&channel,77,1,replay.now,age,true));
        assert(!pico_vendor_slam_output_release(&output));
    }
    std::printf("PICO_STEAMVR_POSE_PASS replay_records=%u published=%u\n",records,published);
}
