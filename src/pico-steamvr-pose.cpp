#include "pico-steamvr-pose.h"

vr::DriverPose_t pico_steamvr_pose(const struct pico_slam_channel *channel,
                                  uint64_t instance, uint64_t generation,
                                  int64_t now, int64_t max_age,
                                  bool device_connected)
{
    vr::DriverPose_t pose{};
    pose.qWorldFromDriverRotation.w=pose.qDriverFromHeadRotation.w=pose.qRotation.w=1;
    pose.deviceIsConnected=device_connected;
    pose.result=vr::TrackingResult_Uninitialized;
    struct pico_slam_channel_sample sample;
    if (!device_connected||!pico_slam_channel_read(channel,instance,generation,now,max_age,&sample)) return pose;
    pose.qRotation={sample.pose.orientation[3],sample.pose.orientation[0],
                    sample.pose.orientation[1],sample.pose.orientation[2]};
    for (unsigned i=0;i<3;++i) pose.vecPosition[i]=sample.pose.position[i];
    pose.poseTimeOffset=(sample.timestamp_ns-now)*1e-9;
    pose.poseIsValid=true;
    pose.result=vr::TrackingResult_Running_OK;
    return pose;
}
