#include "pico-slam-pose.h"
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static unsigned checks;
static void near(double a, double b) { assert(fabs(a-b)<1e-9); ++checks; }

static struct pico_slam_pose_config config(void)
{
    return (struct pico_slam_pose_config){
        .world_from_slam.orientation={0,0,0,1}, .body_from_head.orientation={0,0,0,1},
        .direction=PICO_SLAM_WORLD_FROM_BODY, .metres_per_unit=1, .max_age_ns=50000000};
}

static void refused(const struct pico_slam_pose_config *c, const struct pico_slam_result *r,
                    int64_t uncertainty, int64_t now)
{
    struct pico_slam_pose output, previous;
    memset(&output,0xa5,sizeof(output));memcpy(&previous,&output,sizeof(output));
    assert(!pico_slam_pose_convert(c,r,uncertainty,now,&output));
    assert(!memcmp(&previous,&output,sizeof(output)));++checks;
}

int main(int argc, char **argv)
{
    struct pico_slam_pose_config c=config();
    struct pico_slam_result r={.timestamp_ns=1000000000,.position={100,200,300},
        .orientation={0,0,0,1},.state=1,.confidence=1,.error=512};
    struct pico_slam_pose output;
    const int64_t now=1002000000;
    c.metres_per_unit=.001;
    assert(pico_slam_pose_convert(&c,&r,1000,now,&output));
    near(output.position[0],.1);near(output.position[1],.2);near(output.position[2],.3);
    r.position[0]=r.position[1]=r.position[2]=0;r.error=UINT32_MAX;
    assert(pico_slam_pose_convert(&c,&r,1000,now,&output));
    near(output.position[0],0);near(output.position[1],0);near(output.position[2],0);

    c=config();double s=sqrt(.5);
    c.world_from_slam=(struct pico_slam_pose){.orientation={0,0,s,s},.position={10,20,30}};
    c.body_from_head=(struct pico_slam_pose){.orientation={s,0,0,s},.position={.1,0,0}};
    r=(struct pico_slam_result){.timestamp_ns=1000000000,.position={1,2,3},
        .orientation={0,s,0,s},.state=1,.confidence=1};
    assert(pico_slam_pose_convert(&c,&r,1000,now,&output));
    near(output.position[0],8);near(output.position[1],21);near(output.position[2],32.9);
    near(output.orientation[0],0);near(output.orientation[1],s);
    near(output.orientation[2],0);near(output.orientation[3],s);

    c=config();c.direction=PICO_SLAM_BODY_FROM_WORLD;c.body_from_head.position[0]=.1;
    assert(pico_slam_pose_convert(&c,&r,1000,now,&output));
    near(output.position[0],3);near(output.position[1],-2);near(output.position[2],-.9);
    near(output.orientation[1],-s);near(output.orientation[3],s);

    c=config();refused(NULL,&r,1000,now);refused(&c,NULL,1000,now);
    assert(!pico_slam_pose_convert(&c,&r,1000,now,NULL));
    for (unsigned i=0;i<3;++i) {
        struct pico_slam_result bad=r;bad.confidence=(const uint8_t[]){0,2,255}[i];
        refused(&c,&bad,1000,now);
        bad=r;bad.state=(const uint8_t[]){0,2,255}[i];refused(&c,&bad,1000,now);
    }
    for (unsigned i=0;i<4;++i) {
        c=config();c.metres_per_unit=(const double[]){0,-1,NAN,INFINITY}[i];refused(&c,&r,1000,now);
    }
    c=config();c.direction=0;refused(&c,&r,1000,now);
    c.direction=99;refused(&c,&r,1000,now);
    c=config();c.max_age_ns=INT64_MAX;refused(&c,&r,1000,now);
    c=config();c.max_age_ns=0;refused(&c,&r,1000,now);
    c=config();refused(&c,&r,-1,now);refused(&c,&r,50000001,now);
    refused(&c,&r,1000,r.timestamp_ns+999);refused(&c,&r,0,r.timestamp_ns-1);
    refused(&c,&r,1000,r.timestamp_ns+c.max_age_ns);refused(&c,&r,1000,INT64_MAX);
    assert(pico_slam_pose_convert(&c,&r,1000,r.timestamp_ns+c.max_age_ns-1000,&output));
    for (unsigned i=0;i<4;++i) {
        struct pico_slam_result bad=r;bad.orientation[i]=NAN;refused(&c,&bad,1000,now);
        c=config();c.world_from_slam.orientation[i]=INFINITY;refused(&c,&r,1000,now);
        c=config();c.body_from_head.orientation[i]=NAN;refused(&c,&r,1000,now);
    }
    c=config();memset(c.body_from_head.orientation,0,sizeof(c.body_from_head.orientation));refused(&c,&r,1000,now);
    for (unsigned i=0;i<3;++i) {
        c=config();c.body_from_head.position[i]=NAN;refused(&c,&r,1000,now);
        struct pico_slam_result bad=r;bad.position[i]=INFINITY;c=config();refused(&c,&bad,1000,now);
    }
    c=config();c.metres_per_unit=1000000;refused(&c,&r,1000,now);

    unsigned records=0,accepted=0;
    if (argc==2) {
        FILE *file=fopen(argv[1],"rb");assert(file);
        uint8_t bytes[PICO_SLAM_RESULT_SIZE];size_t n;int64_t previous=0;
        c=config();
        while ((n=fread(bytes,1,sizeof(bytes),file))) {
            assert(n==sizeof(bytes)&&pico_slam_result_decode(bytes,n,&r));
            assert(r.timestamp_ns>previous&&r.timestamp_ns<INT64_MAX-1000000);previous=r.timestamp_ns;
            bool valid=pico_slam_pose_convert(&c,&r,1000,r.timestamp_ns+1000000,&output);
            assert(valid==(r.state==1&&r.confidence==1));
            if (valid) {
                for (unsigned i=0;i<3;++i) near(output.position[i],r.position[i]);
                ++accepted;
            }
            ++records;
        }
        assert(!ferror(file));fclose(file);
    }
    printf("PICO_SLAM_POSE_PASS checks=%u replay_records=%u accepted=%u\n",checks,records,accepted);
    return 0;
}
