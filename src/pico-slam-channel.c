#include "pico-slam-channel.h"
#include <float.h>
#include <limits.h>
#include <math.h>
#include <string.h>

#define MAGIC UINT64_C(0x52565049434f3631)
#define VERSION 1
#define GENERATION 0
#define ACTIVE 1
#define TIMESTAMP 2
#define UNCERTAINTY 3
#define PUBLISHED 4
#define ORIENTATION 5
#define POSITION 9

_Static_assert(__atomic_always_lock_free(8, 0), "Pose IPC requires lock-free 64-bit atomics");
_Static_assert(sizeof(struct pico_slam_channel) == 136, "Pose IPC layout changed");
_Static_assert(sizeof(double)==8 && DBL_MANT_DIG==53 && DBL_MAX_EXP==1024, "Pose IPC requires IEEE binary64");

static bool header(const struct pico_slam_channel *c)
{
    return c && __atomic_load_n(&c->magic,__ATOMIC_RELAXED)==MAGIC &&
        __atomic_load_n(&c->version,__ATOMIC_RELAXED)==VERSION &&
        __atomic_load_n(&c->bytes,__ATOMIC_RELAXED)==sizeof(*c) &&
        __atomic_load_n(&c->instance,__ATOMIC_RELAXED)!=0;
}

static double number(uint64_t value)
{
    double result;memcpy(&result,&value,sizeof(result));return result;
}

static uint64_t bits(double value)
{
    uint64_t result;memcpy(&result,&value,sizeof(result));return result;
}

static bool pose_valid(const struct pico_slam_pose *pose)
{
    double norm=0;
    for (unsigned i=0;i<4;++i) {
        if (!isfinite(pose->orientation[i])) return false;
        norm+=pose->orientation[i]*pose->orientation[i];
    }
    if (!isfinite(norm)||fabs(norm-1)>.0001) return false;
    for (unsigned i=0;i<3;++i)
        if (!isfinite(pose->position[i])||fabs(pose->position[i])>1000000) return false;
    return true;
}

static bool store(struct pico_slam_channel *c, const uint64_t words[PICO_SLAM_CHANNEL_WORDS])
{
    uint64_t sequence=__atomic_load_n(&c->sequence,__ATOMIC_RELAXED);
    if ((sequence&1)||sequence>UINT64_MAX-2) return false;
    if (!__atomic_compare_exchange_n(&c->sequence,&sequence,sequence+1,false,
                                     __ATOMIC_ACQ_REL,__ATOMIC_RELAXED)) return false;
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    for (unsigned i=0;i<PICO_SLAM_CHANNEL_WORDS;++i)
        __atomic_store_n(&c->words[i],words[i],__ATOMIC_RELAXED);
    __atomic_store_n(&c->sequence,sequence+2,__ATOMIC_RELEASE);
    return true;
}

bool pico_slam_channel_init(struct pico_slam_channel *c, uint64_t instance)
{
    if (!c||!instance) return false;
    memset(c,0,sizeof(*c));
    c->magic=MAGIC;c->version=VERSION;c->bytes=sizeof(*c);c->instance=instance;
    return true;
}

bool pico_slam_channel_begin(struct pico_slam_channel *c, uint64_t generation)
{
    if (!header(c)||!generation||generation<=__atomic_load_n(&c->words[GENERATION],__ATOMIC_RELAXED)) return false;
    uint64_t words[PICO_SLAM_CHANNEL_WORDS]={0};
    words[GENERATION]=generation;
    return store(c,words);
}

bool pico_slam_channel_publish(struct pico_slam_channel *c, const struct pico_slam_channel_sample *s)
{
    if (!header(c)||!s||!s->generation||s->generation!=__atomic_load_n(&c->words[GENERATION],__ATOMIC_RELAXED)||
        __atomic_load_n(&c->words[ACTIVE],__ATOMIC_RELAXED)==2) return false;
    if (s->timestamp_ns<=0||s->uncertainty_ns<0||s->uncertainty_ns>1000000000||
        s->published_ns<s->timestamp_ns||s->published_ns-s->timestamp_ns<s->uncertainty_ns||
        (uint64_t)s->timestamp_ns<=__atomic_load_n(&c->words[TIMESTAMP],__ATOMIC_RELAXED)||
        (uint64_t)s->published_ns<__atomic_load_n(&c->words[PUBLISHED],__ATOMIC_RELAXED)||
        !pose_valid(&s->pose)) {
        pico_slam_channel_stop(c,s->generation);
        return false;
    }
    uint64_t words[PICO_SLAM_CHANNEL_WORDS]={s->generation,1,(uint64_t)s->timestamp_ns,
        (uint64_t)s->uncertainty_ns,(uint64_t)s->published_ns};
    for (unsigned i=0;i<4;++i) words[ORIENTATION+i]=bits(s->pose.orientation[i]);
    for (unsigned i=0;i<3;++i) words[POSITION+i]=bits(s->pose.position[i]);
    return store(c,words);
}

static bool deactivate(struct pico_slam_channel *c, uint64_t generation, uint64_t state)
{
    if (!header(c)||!generation||generation!=__atomic_load_n(&c->words[GENERATION],__ATOMIC_RELAXED)) return false;
    uint64_t words[PICO_SLAM_CHANNEL_WORDS];
    for (unsigned i=0;i<PICO_SLAM_CHANNEL_WORDS;++i)
        words[i]=__atomic_load_n(&c->words[i],__ATOMIC_RELAXED);
    if (words[ACTIVE]==2 && state!=2) return false;
    words[ACTIVE]=state;
    return store(c,words);
}

bool pico_slam_channel_invalidate(struct pico_slam_channel *c, uint64_t generation)
{
    return deactivate(c,generation,0);
}

bool pico_slam_channel_stop(struct pico_slam_channel *c, uint64_t generation)
{
    return deactivate(c,generation,2);
}

enum pico_slam_channel_result pico_slam_channel_publish_result(
    struct pico_slam_channel *c, uint64_t generation,
    const struct pico_slam_pose_config *config, const struct pico_slam_result *result,
    int64_t uncertainty, int64_t now)
{
    if (!header(c)||!generation||generation!=__atomic_load_n(&c->words[GENERATION],__ATOMIC_RELAXED)||
        __atomic_load_n(&c->words[ACTIVE],__ATOMIC_RELAXED)==2) return PICO_SLAM_CHANNEL_REFUSED;
    if (!config||!result||result->state!=1||result->confidence>1) {
        pico_slam_channel_stop(c,generation);
        return PICO_SLAM_CHANNEL_REFUSED;
    }
    struct pico_slam_channel_sample sample={.generation=generation,.uncertainty_ns=uncertainty,.published_ns=now};
    if (!pico_slam_pose_convert(config,result,uncertainty,now,&sample.pose)) {
        if (result->confidence == 1 || __atomic_load_n(&c->words[TIMESTAMP],__ATOMIC_RELAXED)) {
            pico_slam_channel_stop(c,generation);
            return PICO_SLAM_CHANNEL_REFUSED;
        }
        return pico_slam_channel_invalidate(c,generation) ? PICO_SLAM_CHANNEL_WAITING : PICO_SLAM_CHANNEL_REFUSED;
    }
    sample.timestamp_ns=result->timestamp_ns;
    return pico_slam_channel_publish(c,&sample) ? PICO_SLAM_CHANNEL_PUBLISHED : PICO_SLAM_CHANNEL_REFUSED;
}

bool pico_slam_channel_read(const struct pico_slam_channel *c, uint64_t instance,
                            uint64_t generation, int64_t now, int64_t max_age,
                            struct pico_slam_channel_sample *sample)
{
    if (!header(c)||!instance||!generation||!sample||now<=0||max_age<=0||max_age>1000000000||
        instance!=__atomic_load_n(&c->instance,__ATOMIC_RELAXED)) return false;
    uint64_t words[PICO_SLAM_CHANNEL_WORDS];bool copied=false;
    for (unsigned attempt=0;attempt<4;++attempt) {
        uint64_t sequence=__atomic_load_n(&c->sequence,__ATOMIC_ACQUIRE);
        if (sequence>UINT64_MAX-2) return false;
        if (sequence&1) continue;
        for (unsigned i=0;i<PICO_SLAM_CHANNEL_WORDS;++i)
            words[i]=__atomic_load_n(&c->words[i],__ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if (sequence==__atomic_load_n(&c->sequence,__ATOMIC_RELAXED)) {copied=true;break;}
    }
    if (!copied||words[GENERATION]!=generation||words[ACTIVE]!=1||!words[TIMESTAMP]||
        words[TIMESTAMP]>(uint64_t)now||words[PUBLISHED]>(uint64_t)now||
        words[PUBLISHED]<words[TIMESTAMP]||words[UNCERTAINTY]>(uint64_t)max_age||
        words[PUBLISHED]-words[TIMESTAMP]<words[UNCERTAINTY]||
        (uint64_t)now-words[TIMESTAMP]>(uint64_t)max_age-words[UNCERTAINTY]) return false;
    struct pico_slam_channel_sample result={.generation=generation,
        .timestamp_ns=(int64_t)words[TIMESTAMP],.uncertainty_ns=(int64_t)words[UNCERTAINTY],
        .published_ns=(int64_t)words[PUBLISHED]};
    for (unsigned i=0;i<4;++i) result.pose.orientation[i]=number(words[ORIENTATION+i]);
    for (unsigned i=0;i<3;++i) result.pose.position[i]=number(words[POSITION+i]);
    if (!pose_valid(&result.pose)) return false;
    *sample=result;
    return true;
}
