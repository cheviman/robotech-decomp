/**
 *    Name:        engine/screen.c
 *    Description: the engine's screen, written in C: the Direct3D device, 640 x 480, its title-safe part, the
 *                 viewport, and what clears the screen and shows it
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The device is the XDK's (Direct3DCreate8, Direct3D_CreateDevice, D3DDevice_*), still recompiled; the
 *    Direct3D 11 bridge sees each call the way it sees the recompiled code's. The screen is always
 *    640 x 480: what the game asks for is not read.
 *
 *    A D3DRECT is a vcRect (left, top, right, bottom), so a clear hands Direct3D a copy of the game's
 *    rectangle, in the guest's stack as the original's local.
 */
#include "decomp.h"
#include "rects.h"
#include "screen.h"

#define SCREEN_WIDTH            640
#define SCREEN_HEIGHT           480
#define SCREEN_BITS             32
/* the title-safe part of 640 x 480 */
#define SAFE_LEFT               48
#define SAFE_TOP                36
#define SAFE_RIGHT              592
#define SAFE_BOTTOM             444

/* The device asked for, in the XDK's values */
#define ADAPTER_DEFAULT         0u
#define DEVICE_HAL              1u
#define FORMAT_X8R8G8B8         0x07u
#define FORMAT_D24S8            0x2Au       /* 24 bits of depth, 8 of stencil */
#define MULTISAMPLE_2_QUINCUNX  0x1121u
#define BACK_BUFFERS            2u
#define SWAP_DISCARD            1u
#define PRESENT_EVERY_BLANK     1u          /* FullScreen_PresentationInterval: one vertical blank */
/* Direct3D_CreateDevice's behaviour flags and the presentation's flags, as the original passes them */
#define CREATE_FLAGS            0x10u
#define PRESENT_FLAGS           0x100u

/* The console's D3DCLEAR flags */
#define CLEAR_DEPTH             0x01u
#define CLEAR_STENCIL           0x02u
#define CLEAR_COLOR             0xF0u       /* red, green, blue and alpha */
#define BLACK                   0u

/* The original's locals: a D3DVIEWPORT8, a D3DRECT */
#define VIEWPORT_FRAME          0x18u
#define RECT_FRAME              0x10u

void vcScreenSafeAreaInit(uint32_t width, uint32_t height, uint32_t video_flags)
{
    vcRectSet(vcScreenRectDefault_VA, SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, SAFE_BOTTOM);
    vcScreenSafeWidth = SAFE_RIGHT - SAFE_LEFT;
    vcScreenSafeHeight = SAFE_BOTTOM - SAFE_TOP;
    vcRectSet(vcScreenRect_VA, SAFE_LEFT, SAFE_TOP, SAFE_RIGHT, SAFE_BOTTOM);
}
ENTRY_CDECL3_VOID(vcScreenSafeAreaInit)

int32_t vcScreenGetRect(uint32_t rect)
{
    return vcRectSet(rect, 0, 0, vcScreenWidth, vcScreenHeight);
}
ENTRY_CDECL1(vcScreenGetRect)

/* The whole screen to black, its depth to 1 and its stencil to 0. */
static void clear_all(void)
{
    CALL(D3DDevice_Clear, 0, 0, CLEAR_COLOR | CLEAR_DEPTH | CLEAR_STENCIL, BLACK, float_to_bits(1.0f), 0);
}

void vcScreenInit(void)
{
    uint32_t video_flags = CALL0(xapi_XGetVideoFlags), params = vcPresentParameters_VA;

    vcDirect3D = CALL(Direct3DCreate8, 0);
    if (!vcDirect3D)
        return;
    guest_zero(params, D3DPRESENT_PARAMETERS_SIZE);
    D3DPRESENT_PARAMETERS_BackBufferWidth(params) = SCREEN_WIDTH;
    D3DPRESENT_PARAMETERS_BackBufferHeight(params) = SCREEN_HEIGHT;
    D3DPRESENT_PARAMETERS_BackBufferFormat(params) = FORMAT_X8R8G8B8;
    D3DPRESENT_PARAMETERS_BackBufferCount(params) = BACK_BUFFERS;
    D3DPRESENT_PARAMETERS_MultiSampleType(params) = MULTISAMPLE_2_QUINCUNX;
    D3DPRESENT_PARAMETERS_SwapEffect(params) = SWAP_DISCARD;
    D3DPRESENT_PARAMETERS_EnableAutoDepthStencil(params) = 1;
    D3DPRESENT_PARAMETERS_AutoDepthStencilFormat(params) = FORMAT_D24S8;
    D3DPRESENT_PARAMETERS_Flags(params) = PRESENT_FLAGS;
    D3DPRESENT_PARAMETERS_FullScreen_PresentationInterval(params) = PRESENT_EVERY_BLANK;
    CALL(Direct3D_CreateDevice, ADAPTER_DEFAULT, DEVICE_HAL, 0, CREATE_FLAGS, params, vcDevice_VA);
    if (!vcDirect3D)                    /* as the original: Direct3D again, not the device */
        return;
    CALL0(vcScreenSetGamma);
    clear_all();
    CALL(D3DDevice_Swap, 0);
    clear_all();
    CALL(D3DDevice_Swap, 0);
    vcScreenWidth = SCREEN_WIDTH;
    vcScreenHeight = SCREEN_HEIGHT;
    vcScreenBits = SCREEN_BITS;
    vcScreenHasStencil = 1;
    vcScreenSafeAreaInit(SCREEN_WIDTH, SCREEN_HEIGHT, video_flags);
    vcRectSet(vcViewportRect_VA, 0, 0, vcScreenWidth, vcScreenHeight);
}
ENTRY_CDECL0_VOID(vcScreenInit)

void vcScreenShutdown(void)
{
    if (vcDevice) {
        CALL0(D3DDevice_Release);
        vcDevice = 0;
    }
    if (vcDirect3D)
        vcDirect3D = 0;
}
ENTRY_CDECL0_VOID(vcScreenShutdown)

void vcScreenOpen(uint32_t width, uint32_t height, uint32_t bits, uint32_t flag)
{
    CALL0(vcRenderInit);
    CALL0(vcRenderBuffersInit);
    clear_all();
    CALL(D3DDevice_Swap, 0);
}
ENTRY_CDECL4_VOID(vcScreenOpen)

void vcScreenSetViewport(uint32_t rect)
{
    uint32_t viewport = FRAME_TAKE(VIEWPORT_FRAME);

    D3DVIEWPORT8_X(viewport) = vcRect_left(rect);
    D3DVIEWPORT8_Y(viewport) = vcRect_top(rect);
    D3DVIEWPORT8_Width(viewport) = vcRect_right(rect) - vcRect_left(rect);
    D3DVIEWPORT8_Height(viewport) = vcRect_bottom(rect) - vcRect_top(rect);
    D3DVIEWPORT8_MinZ(viewport) = 0.0f;
    D3DVIEWPORT8_MaxZ(viewport) = 1.0f;
    CALL(D3DDevice_SetViewport, viewport);
    vcRectCopy(vcViewportRect_VA, rect);
    FRAME_GIVE(VIEWPORT_FRAME);
}
ENTRY_CDECL1_VOID(vcScreenSetViewport)

void vcScreenClear(uint32_t rect, uint32_t clear_color, uint32_t color, uint32_t clear_depth, uint32_t depth)
{
    uint32_t flags = clear_color ? CLEAR_COLOR : 0, copy;

    if (clear_depth) {
        flags |= CLEAR_DEPTH;
        if (vcScreenHasStencil)
            flags |= CLEAR_STENCIL;
    }
    copy = FRAME_TAKE(RECT_FRAME);
    guest_copy(copy, rect, vcRect_SIZE);
    CALL(D3DDevice_Clear, 1, copy, flags, color, depth, 0);
    FRAME_GIVE(RECT_FRAME);
}
ENTRY_CDECL5_VOID(vcScreenClear)

void vcScreenClearDepth(uint32_t rect, uint32_t depth)
{
    uint32_t flags = vcScreenHasStencil ? CLEAR_DEPTH | CLEAR_STENCIL : CLEAR_DEPTH, copy;

    copy = FRAME_TAKE(RECT_FRAME);
    guest_copy(copy, rect, vcRect_SIZE);
    CALL(D3DDevice_Clear, 1, copy, flags, BLACK, depth, 0);
    FRAME_GIVE(RECT_FRAME);
}
ENTRY_CDECL2_VOID(vcScreenClearDepth)

void vcScreenShow(uint32_t flags)
{
    CALL(D3DDevice_Swap, 0);
}
ENTRY_CDECL1_VOID(vcScreenShow)
