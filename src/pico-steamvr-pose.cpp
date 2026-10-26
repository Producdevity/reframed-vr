#include "pico-steamvr-pose.h"

static vr::DriverPose_t convert(const struct pico_slam_channel_sample *sample,
                               int64_t now, bool device_connected)
{
    vr::DriverPose_t pose{};
    pose.qWorldFromDriverRotation.w=pose.qDriverFromHeadRotation.w=pose.qRotation.w=1;
    pose.deviceIsConnected=device_connected;
    pose.result=vr::TrackingResult_Uninitialized;
    if (!sample) return pose;
    pose.qRotation={sample->pose.orientation[3],sample->pose.orientation[0],
                    sample->pose.orientation[1],sample->pose.orientation[2]};
    for (unsigned i=0;i<3;++i) pose.vecPosition[i]=sample->pose.position[i];
    pose.poseTimeOffset=(sample->timestamp_ns-now)*1e-9;
    pose.poseIsValid=true;
    pose.result=vr::TrackingResult_Running_OK;
    return pose;
}

vr::DriverPose_t pico_steamvr_pose(const struct pico_slam_channel *channel,
                                  uint64_t instance, uint64_t generation,
                                  int64_t now, int64_t max_age, bool connected)
{
    struct pico_slam_channel_sample sample;
    bool valid=connected&&pico_slam_channel_read(channel,instance,generation,now,max_age,&sample);
    return convert(valid?&sample:nullptr,now,connected);
}

vr::DriverPose_t pico_steamvr_pose_now(const struct pico_slam_channel *channel,
    uint64_t instance, uint64_t generation, int64_t max_age, bool connected,
    int64_t (*clock_ns)(void *), void *clock_data, enum pico_slam_read_result *result)
{
    struct pico_slam_channel_sample sample;int64_t now=0;
    auto status=connected?pico_slam_channel_read_clock(channel,instance,generation,
        clock_ns,clock_data,max_age,&sample,&now):PICO_SLAM_READ_REFUSED;
    if (result) *result=status;
    return convert(status==PICO_SLAM_READ_OK?&sample:nullptr,now,connected);
}
