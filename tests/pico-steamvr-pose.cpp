#include "pico-steamvr-pose.h"
#include <cassert>
#include <cmath>
#include <cstdio>

static void near(double a, double b) { assert(std::fabs(a-b)<1e-9); }
static void invalid(const vr::DriverPose_t &p, bool connected=true)
{
    assert(p.deviceIsConnected==connected&&!p.poseIsValid&&!p.shouldApplyHeadModel);
    assert(p.result==vr::TrackingResult_Uninitialized);
    assert(p.qWorldFromDriverRotation.w==1&&p.qDriverFromHeadRotation.w==1&&p.qRotation.w==1);
    for(unsigned i=0;i<3;++i)assert(p.vecPosition[i]==0&&p.vecVelocity[i]==0);
}

int main()
{
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
    std::puts("PICO_STEAMVR_POSE_PASS");
}
