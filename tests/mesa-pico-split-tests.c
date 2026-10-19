/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define DRM_MODE_OBJECT_PLANE 0xeeeeeeeeu
#define DRM_PLANE_TYPE_OVERLAY 0
#define DRM_MODE_PROP_IMMUTABLE 4
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);exit(1); } } while (0)
static unsigned checks, allocations, frees, property_queries, fail_query, add_calls, fail_add;
static bool bad_driver, no_version, no_resources, no_plane, no_properties, wrong_crtc, wrong_mask, scaler, no_dma, primary, immutable;
static int missing = -1;
static uint32_t resource_count = 10;
static uint32_t ids[] = {69,91,94,97,100,106,109,112,115,119};
static const char *names[] = {"FB_ID","CRTC_ID","CRTC_X","CRTC_Y","CRTC_W","CRTC_H","SRC_X","SRC_Y","SRC_W","SRC_H","rotation","zpos","alpha","blend_op","excl_rect_v1","sspp_layout","type","csc_dma_v1","scaler_v2"};
static uint32_t formats0[]={1,2,3},formats1[]={2,3,4};
typedef struct { int name_len; char *name; } drmVersion,*drmVersionPtr;
typedef struct { uint32_t count_planes,*planes; } drmModePlaneRes;
typedef struct { uint32_t plane_id,crtc_id,possible_crtcs,count_formats,*formats; } drmModePlane;
typedef struct { uint32_t count_props,*props;uint64_t *prop_values; } drmModeObjectProperties;
typedef struct { uint32_t flags;char name[32]; } drmModePropertyRes,*drmModePropertyPtr;
typedef struct { unsigned count;struct {uint32_t object,property;uint64_t value;} entry[64]; } drmModeAtomicReq;
static void *alloc(size_t n) { void *p=calloc(1,n);CHECK(p);allocations++;return p; }
static void release(void *p) { CHECK(p);frees++;free(p); }
static drmVersionPtr drmGetVersion(int fd) { CHECK(fd==9);if(no_version)return NULL;drmVersionPtr v=alloc(sizeof(*v));v->name=bad_driver?"other":"msm_drm";v->name_len=strlen(v->name);return v; }
static void drmFreeVersion(drmVersionPtr v){release(v);}
static drmModePlaneRes *drmModeGetPlaneResources(int fd){CHECK(fd==9);if(no_resources)return NULL;drmModePlaneRes *r=alloc(sizeof(*r));r->count_planes=resource_count;r->planes=ids;return r;}
static void drmModeFreePlaneResources(drmModePlaneRes *r){release(r);}
static drmModePlane *drmModeGetPlane(int fd,uint32_t id){CHECK(fd==9&&(id==109||id==112));if(no_plane)return NULL;drmModePlane *p=alloc(sizeof(*p));p->plane_id=id;p->crtc_id=wrong_crtc?193:0;p->possible_crtcs=wrong_mask?2:1;p->count_formats=3;p->formats=id==109?formats0:formats1;return p;}
static void drmModeFreePlane(drmModePlane *p){release(p);}
static drmModeObjectProperties *drmModeObjectGetProperties(int fd,uint32_t id,uint32_t type){CHECK(fd==9&&(id==109||id==112)&&type==DRM_MODE_OBJECT_PLANE);if(no_properties)return NULL;drmModeObjectProperties *p=alloc(sizeof(*p)+19*sizeof(uint32_t)+4+19*sizeof(uint64_t));p->props=(uint32_t*)(p+1);p->prop_values=(uint64_t*)((char*)(p+1)+19*sizeof(uint32_t)+4);for(unsigned i=0;i<19;i++){if((int)i==missing||(i==17&&no_dma)||(i==18&&!scaler))continue;unsigned n=p->count_props++;p->props[n]=i+100;p->prop_values[n]=(i==16&&primary)?1:0;}return p;}
static void drmModeFreeObjectProperties(drmModeObjectProperties *p){release(p);}
static drmModePropertyPtr drmModeGetProperty(int fd,uint32_t id){CHECK(fd==9&&id>=100&&id<119);if(++property_queries==fail_query)return NULL;drmModePropertyPtr p=alloc(sizeof(*p));strcpy(p->name,names[id-100]);p->flags=(immutable&&id==110)?DRM_MODE_PROP_IMMUTABLE:0;return p;}
static void drmModeFreeProperty(drmModePropertyPtr p){release(p);}
static int drmModeAtomicAddProperty(drmModeAtomicReq *req,uint32_t object,uint32_t property,uint64_t value){CHECK(req->count<64);if(++add_calls==fail_add)return -ENOMEM;req->entry[req->count].object=object;req->entry[req->count].property=property;req->entry[req->count].value=value;return req->count++;}
#include "wsi_display_pico.h"
static void reset(void){CHECK(allocations==frees);bad_driver=no_version=no_resources=no_plane=no_properties=wrong_crtc=wrong_mask=scaler=no_dma=primary=immutable=false;missing=-1;resource_count=10;property_queries=fail_query=add_calls=fail_add=0;ids[7]=112;}
static void reject(void){struct wsi_pico_split s;CHECK(!wsi_pico_split_init(9,140,0,&s));CHECK(!s.enabled);CHECK(allocations==frees);}
static uint64_t value(drmModeAtomicReq *r,uint32_t object,unsigned index){unsigned found=0;uint64_t v=0;for(unsigned i=0;i<r->count;i++)if(r->entry[i].object==object&&r->entry[i].property==100+index){found++;v=r->entry[i].value;}CHECK(found==1);return v;}
int main(void){
 struct wsi_pico_split s;reset();CHECK(wsi_pico_split_init(9,140,0,&s));CHECK(s.enabled&&s.plane[0].id==109&&s.plane[1].id==112);CHECK(allocations==frees);
 drmModeAtomicReq req={0};CHECK(wsi_pico_split_add(&req,&s,140,88,1920,3664,true)==0);CHECK(req.count==32);
 for(unsigned p=0;p<2;p++){unsigned id=p?112:109,x=p?0:960;CHECK(value(&req,id,PICO_FB)==88&&value(&req,id,PICO_CRTC)==140);CHECK(value(&req,id,PICO_X)==x&&value(&req,id,PICO_Y)==0);CHECK(value(&req,id,PICO_W)==960&&value(&req,id,PICO_H)==3664);CHECK(value(&req,id,PICO_SRC_X)==((uint64_t)x<<16));CHECK(value(&req,id,PICO_SRC_W)==(960u<<16)&&value(&req,id,PICO_SRC_H)==(3664u<<16));CHECK(value(&req,id,PICO_ROTATION)==1&&value(&req,id,PICO_ALPHA)==255&&value(&req,id,PICO_BLEND)==2);CHECK(value(&req,id,PICO_EXCLUSION)==0&&value(&req,id,PICO_LAYOUT)==0);}
 req=(drmModeAtomicReq){0};CHECK(wsi_pico_split_add(&req,&s,140,88,1920,3664,false)==0);CHECK(req.count==4);for(unsigned p=0;p<2;p++){CHECK(value(&req,p?112:109,PICO_FB)==0);CHECK(value(&req,p?112:109,PICO_CRTC)==0);}
 req=(drmModeAtomicReq){0};CHECK(wsi_pico_split_add(&req,&s,140,88,1919,3664,true)==-EINVAL&&req.count==0);CHECK(wsi_pico_split_add(&req,&s,140,88,1920,3663,true)==-EINVAL&&req.count==0);
 req=(drmModeAtomicReq){0};CHECK(wsi_pico_split_add(&req,&s,0,88,1920,3664,true)==-EINVAL&&req.count==0);CHECK(wsi_pico_split_add(&req,&s,140,0,1920,3664,true)==-EINVAL&&req.count==0);
 for(unsigned fail=1;fail<=32;fail++){req=(drmModeAtomicReq){0};add_calls=0;fail_add=fail;CHECK(wsi_pico_split_add(&req,&s,140,88,1920,3664,true)==-ENOMEM);CHECK(req.count==fail-1);}fail_add=0;
 uint32_t f[]={1,2,3,4,5};CHECK(wsi_pico_split_filter_formats(9,&s,5,f)==2&&f[0]==2&&f[1]==3);CHECK(allocations==frees);
 reset();bad_driver=true;reject();reset();no_version=true;reject();reset();no_resources=true;reject();reset();resource_count=7;reject();reset();no_plane=true;reject();reset();no_properties=true;reject();reset();wrong_crtc=true;reject();reset();wrong_mask=true;reject();reset();scaler=true;reject();reset();no_dma=true;reject();reset();primary=true;reject();reset();immutable=true;reject();reset();ids[7]=109;reject();
 for(int m=0;m<16;m++){reset();missing=m;reject();}
 for(unsigned q=1;q<=36;q++){reset();fail_query=q;reject();}
 reset();CHECK(!wsi_pico_split_init(9,140,32,&s));CHECK(allocations==frees);
 printf("PICO_SPLIT_MODEL_PASS checks=%u allocations=%u frees=%u\n",checks,allocations,frees);return 0;
}
