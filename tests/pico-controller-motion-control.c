#define main worker_main
#include "../tools/pico-controller-input.c"
#undef main
#include <assert.h>

int main(void)
{
    uint64_t values[3]; unsigned mask;
    const char *retire="retire2 0000000000000068 0000000000000100\n";
    const char *accept="accept2 0000000000000068 0000000000000069 0000000000000001 1\n";
    assert(subset_request(retire,strlen(retire),values,&mask)==1&&values[0]==104&&values[1]==256);
    assert(subset_request(accept,strlen(accept),values,&mask)==2&&values[0]==104&&values[1]==105&&values[2]==1&&mask==1);
    for(size_t i=0;i<strlen(accept);++i)assert(!subset_request(accept,i,values,&mask));
    char bad[128];strcpy(bad,accept);bad[59]='0';assert(!subset_request(bad,strlen(bad),values,&mask));
    strcpy(bad,accept);bad[8]='A';assert(!subset_request(bad,strlen(bad),values,&mask));
    strcpy(bad,accept);strcat(bad,"x");assert(!subset_request(bad,strlen(bad),values,&mask));
    strcpy(bad,accept);bad[6]='3';assert(!subset_request(bad,strlen(bad),values,&mask));
    assert(!subset_request("restart 0000000000000068 0000000000000069\n",42,values,&mask));
    assert(restart_request("restart 0000000000000068 0000000000000069\n",values,values+1));
    struct pico_controller_motion_producer p={0};
    struct pico_controller_motion_channel *channel=calloc(1,sizeof(*channel));assert(channel);
    struct ssc_clock clock={.counter_ticks=19200000,.counter_hz=19200000,.host_ns=1000000000,
        .uncertainty_ns=2,.initialized=true};
    struct pico_controller_motion_config config[2]={{1,53,0,0},{1,53,0,0}};
    assert(!pico_controller_motion_producer_init(&p,channel,1,104,&clock,config,1,2,3,1000000000));
    uint8_t raw[1000]={0};struct subset_state state={0};
    assert(pico_controller_motion_producer_update(&p,104,raw,raw,3000000000)==-ETIMEDOUT);
    subset_poll(&p,&state,raw,raw,3001000000,0);
    assert(state.retired&&!state.error&&!state.id&&!state.offer.mask);
    raw[0]=0xa5;raw[1]=1;raw[7]=0x40;uint64_t timestamp=3002000;
    for(unsigned i=0;i<8;++i)raw[47+i]=timestamp>>(8*i);
    unsigned crc=0;
    for(unsigned i=0;i<99;++i){crc^=raw[i];for(unsigned j=0;j<8;++j)crc=(crc>>1)^((crc&1)?0x8c:0);}
    raw[99]=crc;
    subset_poll(&p,&state,raw,raw,3003000000,0);
    assert(state.offer.mask==1&&state.id==1&&state.offer.boundary_ns==3000000000);
    subset_poll(&p,&state,raw,raw,3004000000,0);assert(state.id==1);
    subset_poll(&p,&state,raw,raw,3204000000,0);assert(!state.offer.mask);
    free(channel);puts("PICO_CONTROLLER_MOTION_CONTROL_PASS");return 0;
}
