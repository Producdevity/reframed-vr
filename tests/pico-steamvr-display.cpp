#include "pico-steamvr-display.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>

static void near(double a,double b) {assert(std::fabs(a-b)<.00001);}
static pico_steamvr_display_config config()
{
    pico_steamvr_display_config c{};
    std::strcpy(c.serial,"synthetic-neo3");c.width=1920;c.height=3664;c.frame_interval_ns=11111111;
    for (unsigned i=0;i<2;++i) {
        auto &v=c.views[i];v.viewport[0]=0;v.viewport[1]=i*1832;v.viewport[2]=1920;v.viewport[3]=1832;
        v.render[0]=1832;v.render[1]=1920;v.rotation[0]=v.rotation[3]=1;
        v.fov[0]=-.7;v.fov[1]=.8;v.fov[2]=.6;v.fov[3]=-.9;
        v.eye_pose[3]=1;v.eye_pose[4]=i?.032:-.032;
        v.tangent_offset[0]=std::tan(v.fov[0]);v.tangent_scale[0]=std::tan(v.fov[1])-v.tangent_offset[0];
        v.tangent_offset[1]=std::tan(v.fov[2]);v.tangent_scale[1]=std::tan(v.fov[3])-v.tangent_offset[1];
        v.radial[0]=1;
    }
    assert(pico_steamvr_display_valid(c));return c;
}

int main(int argc,char **argv)
{
    if (argc==3) {
        auto c=config();auto previous=c;
        bool ok=pico_steamvr_display_load(argv[2],c);
        assert(ok==!std::strcmp(argv[1],"--load"));
        if (!ok) assert(!std::memcmp(&c,&previous,sizeof(c)));
        std::puts("PICO_STEAMVR_CONFIG_PASS");return 0;
    }
    auto c=config();PicoSteamvrDisplay d(c);
    int32_t x,y;uint32_t w,h,px,py;
    d.GetWindowBounds(&x,&y,&w,&h);assert(x==0&&y==0&&w==1920&&h==3664);
    assert(!d.IsDisplayOnDesktop()&&d.IsDisplayRealDisplay());
    d.GetRecommendedRenderTargetSize(&w,&h);assert(w==1832&&h==1920);
    d.GetEyeOutputViewport(vr::Eye_Right,&px,&py,&w,&h);assert(px==0&&py==1832&&w==1920&&h==1832);
    float left,right,top,bottom;d.GetProjectionRaw(vr::Eye_Left,&left,&right,&top,&bottom);
    near(left,std::tan(-.7));near(right,std::tan(.8));near(top,-std::tan(.6));near(bottom,-std::tan(-.9));
    auto eye=pico_steamvr_eye_to_head(c.views[0]);near(eye.m[0][3],-.032);near(eye.m[1][1],1);
    auto v=c.views[1];v.eye_pose[0]=v.eye_pose[3]=std::sqrt(.5);
    eye=pico_steamvr_eye_to_head(v);near(eye.m[0][3],.032);near(eye.m[1][2],-1);near(eye.m[2][1],1);
    unsigned checks=0;
    for (unsigned turn=0;turn<4;++turn) for(unsigned chroma=0;chroma<2;++chroma) {
        c=config();
        const double rotations[4][4]={{1,0,0,1},{0,1,-1,0},{-1,0,0,-1},{0,-1,1,0}};
        for (auto &view:c.views) {
            std::memcpy(view.rotation,rotations[turn],sizeof(view.rotation));
            if (chroma) {view.radial[1]=.15;view.radial[2]=-.02;view.chromatic[0]=.02;view.chromatic[3]=.03;view.chromatic[4]=-.01;}
        }
        assert(pico_steamvr_display_valid(c));PicoSteamvrDisplay display(c);
        for (unsigned iy=0;iy<=32;++iy) for (unsigned ix=0;ix<=32;++ix) {
            const double u=ix/32.,v=iy/32.;double su=u,sv=v;
            if(turn==1){su=v;sv=1-u;}else if(turn==2){su=1-u;sv=1-v;}else if(turn==3){su=1-v;sv=u;}
            const auto &view=c.views[0];
            double tx=view.tangent_scale[0]*su+view.tangent_offset[0],ty=view.tangent_scale[1]*sv+view.tangent_offset[1];
            double rsq=tx*tx+ty*ty,scale=0,power=1;
            for(unsigned i=0;i<11;++i){scale+=view.radial[i]*power;power*=rsq;}
            const double *k=view.chromatic;
            double factors[3]={1+k[0]+rsq*k[1]+std::sqrt(rsq)*k[4],1,1+k[2]+rsq*k[3]+std::sqrt(rsq)*k[5]};
            auto result=display.ComputeDistortion(vr::Eye_Left,static_cast<float>(u),static_cast<float>(v));
            const float *rgb[3]={result.rfRed,result.rfGreen,result.rfBlue};
            for(unsigned i=0;i<3;++i) {
                near(rgb[i][0],(tx*scale*factors[i]-std::tan(view.fov[0]))/(std::tan(view.fov[1])-std::tan(view.fov[0])));
                near(rgb[i][1],(std::tan(view.fov[2])-ty*scale*factors[i])/(std::tan(view.fov[2])-std::tan(view.fov[3])));
                checks+=2;
            }
        }
    }
    auto bad=d.ComputeDistortion(vr::Eye_Left,-.1f,.5f);assert(bad.rfRed[0]==-1);
    bad=d.ComputeDistortion(vr::Eye_Left,std::numeric_limits<float>::quiet_NaN(),.5f);assert(bad.rfGreen[1]==-1);
    vr::HmdVector2_t inverse{{42,42}};assert(!d.ComputeInverseDistortion(&inverse,vr::Eye_Left,0,.5f,.5f));assert(inverse.v[0]==42);
    for(unsigned i=0;i<8;++i) {
        c=config();
        switch(i) {
        case 0:c.views[1].viewport[1]=0;break;
        case 1:c.views[0].rotation[0]=-1;break;
        case 2:c.views[0].eye_pose[3]=0;break;
        case 3:c.views[0].fov[2]=0;break;
        case 4:c.views[0].tangent_scale[0]=0;break;
        case 5:c.views[0].radial[10]=std::numeric_limits<double>::infinity();break;
        case 6:c.views[0].viewport[0]=UINT32_MAX;break;
        default:c.frame_interval_ns=0;break;
        }
        assert(!pico_steamvr_display_valid(c));
    }
    std::printf("PICO_STEAMVR_DISPLAY_PASS uv_checks=%u rotations=4 chromatic_models=2\n",checks);
}
