#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

struct wsi_display { int fd, device_fd; unsigned master_refcount; };
static int is_master, set_result, set_calls, drop_result, drop_calls;
static int drmIsMaster(int fd) { assert(fd==7); return is_master; }
static int drmSetMaster(int fd) { assert(fd==7); ++set_calls; return set_result; }
static int drmDropMaster(int fd) { assert(fd==7); ++drop_calls; return drop_result; }
#define wsi_display_debug(...) ((void)0)
#include "display-master-under-test.h"

int main(void)
{
    struct wsi_display w={.fd=7,.device_fd=7};
    is_master=1; set_result=-EACCES; drop_result=-EACCES;
    assert(drmIsMaster(7)==1);
    assert(wsi_display_get_master(&w)==0 && w.master_refcount==1 && set_calls==0);
    assert(wsi_display_get_master(&w)==0 && w.master_refcount==2 && set_calls==0);
    assert(wsi_display_drop_master(&w)==0 && w.master_refcount==1 && drop_calls==0);
    assert(wsi_display_drop_master(&w)==0 && w.master_refcount==0 && drop_calls==1);
    assert(wsi_display_get_master(&w)==0 && w.master_refcount==1 && set_calls==0);
    w.master_refcount=0; is_master=0;
    assert(wsi_display_get_master(&w)==-EACCES && w.master_refcount==0 && set_calls==1);
    set_result=0;
    assert(wsi_display_get_master(&w)==0 && w.master_refcount==1 && set_calls==2);
    drop_result=0;
    assert(wsi_display_drop_master(&w)==0 && w.master_refcount==0 && drop_calls==2);
    w.fd=8;
    assert(wsi_display_get_master(&w)==0 && w.master_refcount==0 && set_calls==2);
    assert(wsi_display_drop_master(&w)==0 && drop_calls==2);
    puts("MESA_DISPLAY_MASTER_PASS held, denied, reacquired, nested and external files");
    return 0;
}
