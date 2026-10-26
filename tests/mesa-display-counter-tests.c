#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *VkDevice;
typedef void *VkSwapchainKHR;
typedef uint32_t VkSurfaceCounterFlagBitsEXT;
typedef int VkResult;
#define VKAPI_ATTR
#define VKAPI_CALL
#define VK_SUCCESS 0
#define VK_ERROR_INITIALIZATION_FAILED -3
#define VK_ERROR_UNKNOWN -13
#define VK_SURFACE_COUNTER_VBLANK_BIT_EXT 1
#define VK_ICD_WSI_PLATFORM_DISPLAY 0
#define VK_FROM_HANDLE(type, name, handle) struct type *name = (handle)
struct wsi_display { int fd; };
struct wsi_device { void *wsi[1]; };
struct vk_physical_device { struct wsi_device *wsi_device; };
struct vk_device { struct vk_physical_device *physical; };
struct wsi_display_connector { bool active; uint32_t crtc_id; };
struct wsi_display_mode { struct wsi_display_connector *connector; };
struct surface { struct wsi_display_mode *displayMode; };
struct wsi_display_swapchain { struct surface *surface; };
static void *wsi_swapchain_from_handle(void *p) { return p; }
static struct wsi_display_mode *wsi_display_mode_from_handle(struct wsi_display_mode *p) { return p; }
static unsigned queries;
static unsigned traces;
static const void *expected_trace_chain;
static int query_result;
static uint64_t query_timestamp=1000000000;
static int drmCrtcGetSequence(int fd, uint32_t crtc, uint64_t *value, uint64_t *timestamp)
{
    assert(fd==7 && crtc==140);
    ++queries;
    if (!query_result) {
        *value=123;
        if (timestamp) *timestamp=query_timestamp;
    }
    return query_result;
}
static void wsi_present_trace(const char *event, const void *chain, const void *image,
                             uint64_t sequence, uint64_t timestamp, int result)
{
    if (!strcmp(event,"counter_query")) {
        const char *enabled=getenv("MESA_VK_WSI_FRAME_COUNTER_TIMING");
        bool timing=sequence==0x7ffffffd && enabled && !strcmp(enabled,"1");
        assert(chain==expected_trace_chain && !image && !result && timestamp==(uint64_t)timing);
        return;
    }
    assert(!strcmp(event,"counter") && chain==expected_trace_chain && !image && !result);
    assert(sequence==123 && timestamp==query_timestamp);
    ++traces;
}
#include "display-counter-under-test.h"

int main(void)
{
    struct wsi_display display={7};
    struct wsi_device wsi={{&display}};
    struct vk_physical_device physical={&wsi};
    struct vk_device device={&physical};
    struct wsi_display_connector connector={true,140};
    struct wsi_display_mode mode={&connector};
    struct surface surface={&mode};
    struct wsi_display_swapchain chain={&surface};
    expected_trace_chain=&chain;
    assert(!unsetenv("MESA_VK_WSI_FRAME_COUNTER_TIMING"));
    uint64_t values[3]={456,789,987};
    uint32_t unsupported[]={0,2,3,0x7ffffffd,0xffffffff};
    for (unsigned i=0;i<sizeof(unsupported)/sizeof(unsupported[0]);++i) {
        assert(wsi_GetSwapchainCounterEXT(&device,&chain,unsupported[i],values)==VK_ERROR_UNKNOWN);
        assert(values[0]==456 && values[1]==789 && !queries);
    }
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,1,values)==VK_SUCCESS);
    assert(values[0]==123 && values[1]==789 && queries==1);
    connector.active=false;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,1,values)==VK_SUCCESS);
    assert(!values[0] && values[1]==789 && queries==1);
    connector.active=true;query_result=-1;values[0]=456;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,1,values)==VK_SUCCESS && !values[0]);
    display.fd=-1;values[0]=456;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,1,values)==VK_ERROR_INITIALIZATION_FAILED);
    assert(values[0]==456 && values[1]==789 && queries==2);
    display.fd=7;query_result=0;
    assert(!setenv("MESA_VK_WSI_FRAME_COUNTER_TIMING","1",1));
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,0x7ffffffd,values)==VK_SUCCESS);
    assert(values[0]==123 && values[1]==1000000000 && values[2]==987 && queries==3);
    assert(traces==1);
    values[1]=789;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,1,values)==VK_SUCCESS);
    assert(values[0]==123 && values[1]==789 && values[2]==987 && queries==4);
    values[0]=456;values[1]=789;query_result=-1;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,0x7ffffffd,values)==VK_ERROR_UNKNOWN);
    assert(values[0]==456 && values[1]==789 && values[2]==987 && queries==5);
    query_result=0;query_timestamp=0;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,0x7ffffffd,values)==VK_ERROR_UNKNOWN);
    assert(values[0]==456 && values[1]==789 && values[2]==987 && queries==6);
    connector.active=false;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,0x7ffffffd,values)==VK_ERROR_UNKNOWN);
    assert(values[0]==456 && values[1]==789 && queries==6);
    connector.active=true;
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,2,values)==VK_ERROR_UNKNOWN && queries==6);
    assert(!setenv("MESA_VK_WSI_FRAME_COUNTER_TIMING","0",1));
    assert(wsi_GetSwapchainCounterEXT(&device,&chain,0x7ffffffd,values)==VK_ERROR_UNKNOWN && queries==6);
    assert(traces==1);
    struct wsi_display_swapchain second_chain={&surface};
    expected_trace_chain=&second_chain;
    assert(!setenv("MESA_VK_WSI_FRAME_COUNTER_TIMING","1",1));
    query_timestamp=1000000000;
    assert(wsi_GetSwapchainCounterEXT(&device,&second_chain,0x7ffffffd,values)==VK_SUCCESS);
    assert(values[0]==123 && values[1]==1000000000 && queries==7 && traces==2);
    query_result=-1;values[0]=456;values[1]=789;
    assert(wsi_GetSwapchainCounterEXT(&device,&second_chain,0x7ffffffd,values)==VK_ERROR_UNKNOWN);
    assert(values[0]==456 && values[1]==789 && values[2]==987 && queries==8 && traces==2);
    puts("MESA_DISPLAY_COUNTER_PASS opt-in paired DRM time; failure bounds; standard queries preserved");
}
