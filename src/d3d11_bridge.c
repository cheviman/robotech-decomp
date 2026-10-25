/**
 *    Name:        d3d11_bridge.c
 *    Description: routes the game's Direct3D (the XDK's, statically linked and recompiled) to Direct3D 11
 *                 through xboxrecomp's D3D8 layer
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    On with ROBOTECH_D3D11=1. The game's own D3D keeps running, as the bookkeeping it is: it creates its
 *    objects in guest memory and keeps their state, and its pushbuffer is never executed (no
 *    RECOMP_PB_EXEC; main.c mirrors its GPU fence). The wrappers in recomp_manual.c call in here around
 *    the generated functions, and this file draws what the game asked for with xboxrecomp's D3D8 layer
 *    (src/d3d, D3D11 underneath). The entries are routed one at a time; docs/d3d.md lists them.
 *
 *    Every function here reads its arguments from the guest stack as the wrapper found it: esp points
 *    at the return address, the first argument is at esp + 4.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp;
extern ptrdiff_t g_xbox_mem_offset;

/* The XDK's D3DCLEAR flags. Xbox splits the target into its four channels;
 * xboxrecomp's layer takes the PC values. */
#define XB_CLEAR_ZBUFFER   0x01u
#define XB_CLEAR_STENCIL   0x02u
#define XB_CLEAR_TARGET    0xF0u

static IDirect3DDevice8 *s_dev;
static HWND s_hwnd;
static unsigned s_presents, s_clears;

static uint32_t guest32(uint32_t va)
{
    return *(const volatile uint32_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static const void *guest_ptr(uint32_t va)
{
    return va ? (const void *)((uintptr_t)va + g_xbox_mem_offset) : NULL;
}

/* The i-th stack argument of the function being wrapped, 0-based. */
static uint32_t arg(int i)
{
    return guest32(g_esp + 4u + 4u * (uint32_t)i);
}

int d3d11_BridgeOn(void)
{
    static int on = -1;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_D3D11");
        on = e && *e && *e != '0';
    }
    return on;
}

static LRESULT CALLBACK bridge_wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_CLOSE || m == WM_DESTROY) {
        /* The layer's message pump (Swap) ends the process on WM_QUIT. */
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

/* The window D3D11 presents into. Made on the game's thread, the one that
 * calls Swap, because Swap is where its messages are pumped. The picture is
 * scaled to the window (ROBOTECH_WINDOW_SCALE, 2 by default). */
static HWND bridge_window(UINT width, UINT height)
{
    WNDCLASSA wc;
    RECT r;
    const char *s = getenv("ROBOTECH_WINDOW_SCALE");
    int scale = s ? atoi(s) : 2;
    DWORD style = WS_OVERLAPPEDWINDOW;

    if (scale < 1)
        scale = 1;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = bridge_wndproc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = "RobotechD3D11";
    RegisterClassA(&wc);

    r.left = r.top = 0;
    r.right = (LONG)(width * (UINT)scale);
    r.bottom = (LONG)(height * (UINT)scale);
    AdjustWindowRect(&r, style, FALSE);
    return CreateWindowA(wc.lpszClassName, "Robotech: Battlecry", style | WS_VISIBLE,
                         CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left, r.bottom - r.top,
                         NULL, NULL, wc.hInstance, NULL);
}

/* Direct3D_CreateDevice(Adapter, DeviceType, hFocusWindow, BehaviorFlags,
 * pPresentationParameters, ppReturnedDeviceInterface).
 *
 * The guest's D3DPRESENT_PARAMETERS is copied a field at a time: its window
 * handle is 32 bits wide, the host's 64. Formats and multisample types keep
 * their XDK values, which the layer takes as they are. The host device is
 * windowed whatever the game asks for. */
void d3d11_CreateDevice(void)
{
    uint32_t pp_va = arg(4);
    D3DPRESENT_PARAMETERS pp;
    IDirect3D8 *d3d;
    HRESULT hr;

    if (!d3d11_BridgeOn() || s_dev || !pp_va)
        return;
    memset(&pp, 0, sizeof pp);
    pp.BackBufferWidth = guest32(pp_va + 0x00);
    pp.BackBufferHeight = guest32(pp_va + 0x04);
    pp.BackBufferFormat = (D3DFORMAT)guest32(pp_va + 0x08);
    pp.BackBufferCount = guest32(pp_va + 0x0C);
    pp.MultiSampleType = (D3DMULTISAMPLE_TYPE)guest32(pp_va + 0x10);
    pp.SwapEffect = (D3DSWAPEFFECT)guest32(pp_va + 0x14);
    pp.EnableAutoDepthStencil = guest32(pp_va + 0x20);
    pp.AutoDepthStencilFormat = (D3DFORMAT)guest32(pp_va + 0x24);
    pp.Flags = guest32(pp_va + 0x28);
    pp.FullScreen_RefreshRateInHz = guest32(pp_va + 0x2C);
    pp.FullScreen_PresentationInterval = guest32(pp_va + 0x30);
    pp.Windowed = TRUE;

    s_hwnd = bridge_window(pp.BackBufferWidth, pp.BackBufferHeight);
    pp.hDeviceWindow = s_hwnd;
    d3d = xbox_Direct3DCreate8(0);
    hr = d3d->lpVtbl->CreateDevice(d3d, 0, 0, s_hwnd, 0, &pp, &s_dev);
    fprintf(stderr, "[D3D11] device %ux%u format 0x%X multisample 0x%X depth 0x%X: %s (0x%08lX)\n",
            pp.BackBufferWidth, pp.BackBufferHeight, (unsigned)pp.BackBufferFormat,
            (unsigned)pp.MultiSampleType, (unsigned)pp.AutoDepthStencilFormat,
            SUCCEEDED(hr) ? "created" : "failed", (unsigned long)hr);
    if (FAILED(hr))
        s_dev = NULL;
}

/* D3DDevice_Clear(Count, pRects, Flags, Color, Z, Stencil). */
void d3d11_Clear(void)
{
    uint32_t count = arg(0), rects_va = arg(1), xflags = arg(2);
    uint32_t color = arg(3), zbits = arg(4), stencil = arg(5);
    DWORD flags = 0;
    float z;

    if (!s_dev)
        return;
    if (xflags & XB_CLEAR_TARGET)
        flags |= D3DCLEAR_TARGET;
    if (xflags & XB_CLEAR_ZBUFFER)
        flags |= D3DCLEAR_ZBUFFER;
    if (xflags & XB_CLEAR_STENCIL)
        flags |= D3DCLEAR_STENCIL;
    memcpy(&z, &zbits, 4);
    /* D3DRECT is four LONGs on both sides. */
    s_dev->lpVtbl->Clear(s_dev, count, (const D3DRECT *)guest_ptr(rects_va), flags,
                         (D3DCOLOR)color, z, stencil);
    s_clears++;
}

/* D3DDevice_Swap(Flags): present, and pump the window's messages. */
void d3d11_Swap(void)
{
    static DWORD last;
    DWORD now;

    if (!s_dev)
        return;
    s_dev->lpVtbl->Swap(s_dev, arg(0));
    s_presents++;
    now = GetTickCount();
    if (!last)
        last = now;
    if (now - last >= 2000) {
        fprintf(stderr, "[D3D11] %.1f fps, %u clears\n", s_presents * 1000.0 / (now - last), s_clears);
        s_presents = s_clears = 0;
        last = now;
    }
}
