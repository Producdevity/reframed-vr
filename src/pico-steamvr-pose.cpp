#include "pico-steamvr-pose.h"
#include <cmath>

/* World-frame finite difference across two accepted world-from-head poses of
 * the same generation. Velocities are expressed in the tracking frame, matching
 * vecPosition/qRotation (qWorldFromDriver and qDriverFromHead are identity). */
static void estimate_velocity(struct pico_steamvr_velocity_estimator *v,
                              const vr::DriverPose_t &pose,
                              uint64_t generation, int64_t timestamp_ns,
                              double out_velocity[3], double out_angular[3])
{
    out_velocity[0]=out_velocity[1]=out_velocity[2]=0;
    out_angular[0]=out_angular[1]=out_angular[2]=0;
    const double position[3]={pose.vecPosition[0],pose.vecPosition[1],pose.vecPosition[2]};
    const double orientation[4]={pose.qRotation.x,pose.qRotation.y,pose.qRotation.z,pose.qRotation.w};
    /* A repeated read of the still-committed sample carries the last estimate
     * forward unchanged, so motion persists between channel updates. */
    if (v->has_previous && v->generation==generation && timestamp_ns==v->timestamp_ns) {
        for (unsigned i=0;i<3;++i) {out_velocity[i]=v->velocity[i];out_angular[i]=v->angular_velocity[i];}
        return;
    }
    int64_t gap=timestamp_ns-v->timestamp_ns;
    bool differentiable=v->has_previous && v->generation==generation &&
                        gap>0 && gap<=v->max_gap_ns;
    if (differentiable) {
        double dt=gap*1e-9;
        for (unsigned i=0;i<3;++i) out_velocity[i]=(position[i]-v->position[i])/dt;
        /* delta = current * conjugate(previous), the world-frame rotation from
         * the previous orientation to the current one (Hamilton product). */
        const double *a=orientation,*p=v->orientation;
        const double b[4]={-p[0],-p[1],-p[2],p[3]};
        double dx=a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1];
        double dy=a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0];
        double dz=a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3];
        double dw=a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2];
        if (dw<0) {dx=-dx;dy=-dy;dz=-dz;dw=-dw;} /* shortest arc */
        double sine=std::sqrt(dx*dx+dy*dy+dz*dz);
        if (sine>1e-9) {
            double angle=2*std::atan2(sine,dw),scale=angle/(sine*dt);
            out_angular[0]=dx*scale;out_angular[1]=dy*scale;out_angular[2]=dz*scale;
        }
    }
    v->has_previous=true;v->generation=generation;v->timestamp_ns=timestamp_ns;
    for (unsigned i=0;i<3;++i) {
        v->position[i]=position[i];v->velocity[i]=out_velocity[i];v->angular_velocity[i]=out_angular[i];
    }
    for (unsigned i=0;i<4;++i) v->orientation[i]=orientation[i];
}

static vr::DriverPose_t convert(const struct pico_slam_channel_sample *sample,
                               int64_t now, bool device_connected,
                               struct pico_steamvr_velocity_estimator *velocity)
{
    vr::DriverPose_t pose{};
    pose.qWorldFromDriverRotation.w=pose.qDriverFromHeadRotation.w=pose.qRotation.w=1;
    pose.deviceIsConnected=device_connected;
    pose.result=vr::TrackingResult_Uninitialized;
    if (!sample) {if (velocity) velocity->has_previous=false;return pose;}
    pose.qRotation={sample->pose.orientation[3],sample->pose.orientation[0],
                    sample->pose.orientation[1],sample->pose.orientation[2]};
    for (unsigned i=0;i<3;++i) pose.vecPosition[i]=sample->pose.position[i];
    pose.poseTimeOffset=(sample->timestamp_ns-now)*1e-9;
    pose.poseIsValid=true;
    pose.result=vr::TrackingResult_Running_OK;
    if (velocity) estimate_velocity(velocity,pose,sample->generation,sample->timestamp_ns,
                                    pose.vecVelocity,pose.vecAngularVelocity);
    return pose;
}

vr::DriverPose_t pico_steamvr_pose(const struct pico_slam_channel *channel,
                                  uint64_t instance, uint64_t generation,
                                  int64_t now, int64_t max_age, bool connected,
                                  struct pico_steamvr_velocity_estimator *velocity)
{
    struct pico_slam_channel_sample sample;
    bool valid=connected&&pico_slam_channel_read(channel,instance,generation,now,max_age,&sample);
    return convert(valid?&sample:nullptr,now,connected,velocity);
}

vr::DriverPose_t pico_steamvr_pose_now(const struct pico_slam_channel *channel,
    uint64_t instance, uint64_t generation, int64_t max_age, bool connected,
    int64_t (*clock_ns)(void *), void *clock_data, enum pico_slam_read_result *result,
    struct pico_steamvr_velocity_estimator *velocity)
{
    struct pico_slam_channel_sample sample;int64_t now=0;
    auto status=connected?pico_slam_channel_read_clock(channel,instance,generation,
        clock_ns,clock_data,max_age,&sample,&now):PICO_SLAM_READ_REFUSED;
    if (result) *result=status;
    return convert(status==PICO_SLAM_READ_OK?&sample:nullptr,now,connected,velocity);
}
