#define _GNU_SOURCE
#include "pico-slam-channel.h"
#include <assert.h>
#include <limits.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static struct pico_slam_channel channel;
static _Atomic bool done;
static _Atomic unsigned reads;

static struct pico_slam_channel_sample sample(uint64_t generation, int64_t timestamp)
{
    return (struct pico_slam_channel_sample){.pose.orientation={0,0,0,1},
        .generation=generation,.timestamp_ns=timestamp,.uncertainty_ns=1000,.published_ns=timestamp+1000};
}

static void absent(uint64_t instance, uint64_t generation, int64_t now)
{
    struct pico_slam_channel_sample result,previous;
    memset(&result,0xa5,sizeof(result));memcpy(&previous,&result,sizeof(result));
    assert(!pico_slam_channel_read(&channel,instance,generation,now,100000000,&result));
    assert(!memcmp(&result,&previous,sizeof(result)));
}

static void *reader(void *unused)
{
    (void)unused;
    do {
        struct pico_slam_channel_sample result;
        if (pico_slam_channel_read(&channel,42,9,2000000000,1000000000,&result)) {
            assert(result.pose.position[0]==-result.pose.position[1]);
            assert(result.pose.position[2]==result.pose.position[0]*.5);
            assert(result.timestamp_ns==1000000000+(int64_t)result.pose.position[0]);
            assert(result.published_ns==result.timestamp_ns+1000);
            atomic_fetch_add(&reads,1);
        }
    } while (!atomic_load(&done));
    return NULL;
}

static int process(const char *mode, const char *path)
{
    bool initialize=!strcmp(mode,"--init"),produce=!strcmp(mode,"--produce");
    if (!initialize&&!produce&&strcmp(mode,"--consume")) return 2;
    int fd=open(path,(initialize ? O_RDWR|O_CREAT|O_EXCL : produce ? O_RDWR : O_RDONLY)|O_NOFOLLOW,0600);
    assert(fd>=0);
    if (initialize) assert(!ftruncate(fd,sizeof(channel)));
    struct stat st;assert(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size==sizeof(channel));
    struct pico_slam_channel *shared=mmap(NULL,sizeof(channel),PROT_READ|(initialize||produce ? PROT_WRITE : 0),MAP_SHARED,fd,0);
    assert(shared!=MAP_FAILED);close(fd);
    if (initialize) assert(pico_slam_channel_init(shared,42));
    else if (produce) {
        puts("PRODUCER_READY");fflush(stdout);assert(getchar()=='G');
        assert(pico_slam_channel_begin(shared,9));
        for(unsigned i=1;i<=100000;++i) {
            struct pico_slam_channel_sample s=sample(9,1000000000+i);
            s.pose.position[0]=i;s.pose.position[1]=-(double)i;s.pose.position[2]=i*.5;
            assert(pico_slam_channel_publish(shared,&s));
            if (!(i%1000)) {struct timespec delay={.tv_nsec=1000000};nanosleep(&delay,NULL);}
        }
        puts("PRODUCER_COMPLETE");fflush(stdout);assert(getchar()=='F');
        assert(pico_slam_channel_stop(shared,9));
    } else {
        puts("CONSUMER_READY");fflush(stdout);
        struct timespec start,now;assert(!clock_gettime(CLOCK_MONOTONIC,&start));
        uint64_t previous=0;unsigned unique=0,total=0;
        for (;;) {
            struct pico_slam_channel_sample s;
            if (pico_slam_channel_read(shared,42,9,2000000000,1000000000,&s)) {
                assert(s.pose.position[0]==-s.pose.position[1]&&s.pose.position[2]==s.pose.position[0]*.5);
                assert(s.timestamp_ns==1000000000+(int64_t)s.pose.position[0]);
                assert(s.published_ns==s.timestamp_ns+1000);
                uint64_t current=(uint64_t)s.pose.position[0];assert(current>=previous);
                if(current!=previous){++unique;previous=current;}++total;
                if(current==100000){assert(unique>2);break;}
            }
            assert(!clock_gettime(CLOCK_MONOTONIC,&now));assert(now.tv_sec-start.tv_sec<10);
        }
        printf("PICO_SLAM_PROCESS_PASS unique=%u reads=%u\n",unique,total);
    }
    assert(!munmap(shared,sizeof(channel)));return 0;
}

int main(int argc, char **argv)
{
    if(argc==3)return process(argv[1],argv[2]);
    assert(argc==1);
    struct pico_slam_channel_sample r=sample(1,1000000000),out;
    assert(!pico_slam_channel_init(NULL,1));assert(!pico_slam_channel_init(&channel,0));
    assert(!pico_slam_channel_begin(&channel,1));assert(pico_slam_channel_init(&channel,42));
    absent(42,1,1000002000);
    assert(!pico_slam_channel_publish(&channel,&r));
    assert(pico_slam_channel_begin(&channel,1));assert(!pico_slam_channel_begin(&channel,1));
    assert(!pico_slam_channel_begin(&channel,0));absent(42,1,1000002000);
    assert(pico_slam_channel_publish(&channel,&r));
    assert(pico_slam_channel_read(&channel,42,1,1000002000,100000000,&out));
    assert(out.timestamp_ns==r.timestamp_ns&&out.pose.orientation[3]==1);
    absent(0,1,1000002000);absent(43,1,1000002000);absent(42,2,1000002000);
    absent(42,1,r.timestamp_ns+999);absent(42,1,1100000000);absent(42,1,-1);
    assert(pico_slam_channel_read(&channel,42,1,1099999000,100000000,&out));
    assert(pico_slam_channel_invalidate(&channel,1));absent(42,1,1000002000);
    r.timestamp_ns+=1000;r.published_ns+=1000;
    assert(pico_slam_channel_publish(&channel,&r));
    assert(pico_slam_channel_stop(&channel,1));absent(42,1,1000003000);
    assert(!pico_slam_channel_invalidate(&channel,1));
    r.timestamp_ns+=1000;r.published_ns+=1000;assert(!pico_slam_channel_publish(&channel,&r));
    assert(pico_slam_channel_begin(&channel,2));
    assert(!pico_slam_channel_publish(&channel,&r));assert(!pico_slam_channel_stop(&channel,1));
    r=sample(2,1000000000);assert(pico_slam_channel_publish(&channel,&r));
    struct pico_slam_channel_sample old=sample(1,1000001000);
    assert(!pico_slam_channel_publish(&channel,&old));assert(!pico_slam_channel_stop(&channel,1));
    assert(pico_slam_channel_read(&channel,42,2,1000002000,100000000,&out));
    assert(!pico_slam_channel_publish(&channel,&r));absent(42,2,1000002000);
    r.timestamp_ns+=1000;r.published_ns+=1000;assert(!pico_slam_channel_publish(&channel,&r));

    for (unsigned i=0;i<8;++i) {
        assert(pico_slam_channel_begin(&channel,3+i));
        r=sample(3+i,1000000000);assert(pico_slam_channel_publish(&channel,&r));
        r=sample(3+i,1000001000);
        switch(i) {
        case 0:r.pose.orientation[3]=0;break;
        case 1:r.pose.position[0]=NAN;break;
        case 2:r.timestamp_ns=-1;break;
        case 3:r.uncertainty_ns=-1;break;
        case 4:r.published_ns=r.timestamp_ns-1;break;
        case 5:r.uncertainty_ns=1001;break;
        case 6:r.uncertainty_ns=INT64_MAX;break;
        default:r.pose.orientation[0]=INFINITY;break;
        }
        assert(!pico_slam_channel_publish(&channel,&r));absent(42,3+i,1000002000);
        r=sample(3+i,1000000000);assert(!pico_slam_channel_publish(&channel,&r));
    }
    assert(pico_slam_channel_begin(&channel,11));r=sample(11,1000000000);
    assert(pico_slam_channel_publish(&channel,&r));
    assert(pico_slam_channel_read(&channel,42,11,1000002000,100000000,&out));
    uint64_t *fields[]={&channel.magic,&channel.version,&channel.bytes,&channel.instance};
    for(unsigned i=0;i<4;++i) {
        uint64_t saved=*fields[i];*fields[i]=0;absent(42,11,1000002000);*fields[i]=saved;
        assert(pico_slam_channel_read(&channel,42,11,1000002000,100000000,&out));
    }
    uint64_t sequence=channel.sequence;
    unsigned inactive=((sequence>>1)&1)^1;
    channel.slots[inactive][9]=UINT64_MAX;
    channel.sequence|=1;
    assert(pico_slam_channel_read(&channel,42,11,1000002000,100000000,&out));
    assert(out.timestamp_ns==r.timestamp_ns && out.pose.position[0]==r.pose.position[0]);
    absent(42,11,1200000000);
    channel.sequence=sequence;
    channel.version=1;absent(42,11,1000002000);channel.version=2;
    channel.sequence=UINT64_MAX-1;assert(!pico_slam_channel_begin(&channel,12));absent(42,11,1000002000);
    assert(pico_slam_channel_init(&channel,42));assert(pico_slam_channel_begin(&channel,1));
    struct pico_slam_pose_config config={.world_from_slam.orientation={0,0,0,1},
        .body_from_head.orientation={0,0,0,1},.direction=PICO_SLAM_WORLD_FROM_BODY,.metres_per_unit=1,.max_age_ns=100000000};
    struct pico_slam_result raw={.timestamp_ns=1000000000,.orientation={0,0,0,1},.state=1,.confidence=0};
    assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,1000,1000002000)==PICO_SLAM_CHANNEL_WAITING);
    absent(42,1,1000002000);raw.confidence=1;
    assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,1000,1000002000)==PICO_SLAM_CHANNEL_PUBLISHED);
    assert(pico_slam_channel_read(&channel,42,1,1000002000,100000000,&out));
    raw.confidence=0;raw.timestamp_ns+=1000;
    assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,1000,1000003000)==PICO_SLAM_CHANNEL_REFUSED);
    absent(42,1,1000003000);raw.confidence=1;
    assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,1000,1000003000)==PICO_SLAM_CHANNEL_REFUSED);
    assert(pico_slam_channel_begin(&channel,2));
    assert(pico_slam_channel_publish_result(&channel,1,&config,&raw,1000,1000003000)==PICO_SLAM_CHANNEL_REFUSED);
    assert(pico_slam_channel_publish_result(&channel,2,&config,&raw,1000,1000003000)==PICO_SLAM_CHANNEL_PUBLISHED);
    assert(pico_slam_channel_init(&channel,42));assert(pico_slam_channel_begin(&channel,9));
    r=sample(9,1000000000);assert(pico_slam_channel_publish(&channel,&r));
    pthread_t threads[4];
    for(unsigned i=0;i<4;++i)assert(!pthread_create(&threads[i],NULL,reader,NULL));
    for(unsigned i=1;i<=100000;++i) {
        r=sample(9,1000000000+i);r.pose.position[0]=i;r.pose.position[1]=-(double)i;r.pose.position[2]=i*.5;
        assert(pico_slam_channel_publish(&channel,&r));
    }
    atomic_store(&done,true);
    for(unsigned i=0;i<4;++i)assert(!pthread_join(threads[i],NULL));
    assert(atomic_load(&reads)>0);assert(pico_slam_channel_stop(&channel,9));absent(42,9,2000000000);
    printf("PICO_SLAM_CHANNEL_PASS updates=100000 readers=4 coherent_reads=%u\n",atomic_load(&reads));
    return 0;
}
