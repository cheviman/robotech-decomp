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
#define COBJMACROS
#include <windows.h>
#include <d3d11.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax, g_ecx, g_edx;
extern ptrdiff_t g_xbox_mem_offset;

/* xboxrecomp's D3D8 layer, internal accessors (src/d3d/d3d8_internal.h). */
extern ID3D11Device *d3d8_GetD3D11Device(void);
extern ID3D11DeviceContext *d3d8_GetD3D11Context(void);
extern IDXGISwapChain *d3d8_GetSwapChain(void);

/* The XDK's D3DCLEAR flags. Xbox splits the target into its four channels;
 * xboxrecomp's layer takes the PC values. */
#define XB_CLEAR_ZBUFFER   0x01u
#define XB_CLEAR_STENCIL   0x02u
#define XB_CLEAR_TARGET    0xF0u

/* An XDK texture is a D3DPixelContainer in guest memory: Common, Data (the
 * texels' physical address), Lock, Format, Size. Format packs the format
 * code, the mip levels and, for a swizzled texture, log2 of each side; a
 * linear one has its sides and pitch in Size instead. */
#define XB_RES_DATA        0x04u
#define XB_RES_FORMAT      0x0Cu
#define XB_RES_SIZE        0x10u
#define XB_CONTIG_BASE     0x80000000u
#define XB_CONTIG_SIZE     (64u * 1024u * 1024u)

#define BRIDGE_MAX_TEXTURES 256
#define BRIDGE_STAGES       4

/* The game's D3D keeps every render state and texture-stage state in arrays
 * of its own, indexed by the XDK's enums (D3D8Types.h): D3DDevice_SetRenderState
 * is inlined into the game and stores the value there as well as sending it,
 * and the texture-stage states are only stored, for D3D to send at the next
 * draw. The bridge reads them before each draw. */
#define XB_RENDER_STATE_VA  0x00166D58u     /* D3D__RenderState[D3DRS_MAX] */
#define XB_TEXTURE_STATE_VA 0x00166B58u     /* D3D__TextureState[4][D3DTSS_MAX] */
#define XB_RS_MAX           166
#define XB_TSS_MAX          32

typedef struct {
    uint32_t va;               /* the guest D3DTexture */
    uint32_t format_word, size_word;
    IDirect3DTexture8 *host;
    UINT width, height, levels, pitch;
    D3DFORMAT format;
    int dirty;                 /* the game locked it since the last upload */
} BridgeTexture;

static IDirect3DDevice8 *s_dev;
static HWND s_hwnd;
static unsigned s_presents, s_clears, s_draws;
static BridgeTexture s_tex[BRIDGE_MAX_TEXTURES];
static int s_tex_count;
static BridgeTexture *s_stage[BRIDGE_STAGES];
static uint32_t s_fvf;                 /* 0 while a vertex program is set */
static uint8_t *s_scratch;             /* vertices rewritten for the host */
static size_t s_scratch_size;
static uint32_t s_rs_sent[XB_RS_MAX], s_ts_sent[BRIDGE_STAGES][XB_TSS_MAX];
static int s_states_sent;              /* the arrays above hold what was sent */
static uint32_t s_tci[BRIDGE_STAGES] = { 0, 1, 2, 3 };
static uint32_t s_stream_va, s_stream_stride, s_base_vertex;
static unsigned s_skipped_vp;          /* draws left out: vertex program set */
static unsigned s_push_draws;          /* drawn from the game's own pushbuffer writes */
static uint32_t s_pixel_shader;        /* the game's, not routed yet */
static unsigned s_ps_draws;            /* draws made while one was set */
static unsigned s_xforms[10];          /* SetTransform calls, by XDK state */
static uint32_t s_push_caller;         /* EndPush's return address, for the trace */

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

/* xboxrecomp's key table (src/input/keyboard.c). With RECOMP_KEYBOARD=1 the
 * emulated pad reads it: arrows the d-pad, Enter START, Z X C V for A B X Y,
 * W A S D the left stick (the table's comments have the rest). */
extern void xbox_InputKeySet(int vk, int down);
extern void xbox_InputKeysClear(void);
extern int xbox_InputWin32SideVk(int vk, uint32_t lparam);

static void bridge_key(WPARAM w, LPARAM l, int down)
{
    int side = xbox_InputWin32SideVk((int)w, (uint32_t)l);

    xbox_InputKeySet((int)w, down);
    if (side)
        xbox_InputKeySet(side, down);
    /* With both Shifts held Windows sends one key-up, for the last. */
    if (!down && w == VK_SHIFT) {
        xbox_InputKeySet(VK_LSHIFT, 0);
        xbox_InputKeySet(VK_RSHIFT, 0);
    }
}

static LRESULT CALLBACK bridge_wndproc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_CLOSE:
    case WM_DESTROY:
        /* The layer's message pump (Swap) ends the process on WM_QUIT. */
        PostQuitMessage(0);
        return 0;
    case WM_KEYDOWN:
    case WM_SYSKEYDOWN:
        bridge_key(w, l, 1);
        return m == WM_SYSKEYDOWN ? DefWindowProcA(h, m, w, l) : 0;
    case WM_KEYUP:
    case WM_SYSKEYUP:
        bridge_key(w, l, 0);
        return m == WM_SYSKEYUP ? DefWindowProcA(h, m, w, l) : 0;
    case WM_KILLFOCUS:
        xbox_InputKeysClear();
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

/* Write the back buffer about to be presented to <prefix>NNNNN.bmp: what the
 * bridge drew, checkable without looking at the window.
 * ROBOTECH_D3D11_DUMP=<prefix> turns it on, ROBOTECH_D3D11_DUMP_EVERY=<n>
 * keeps one present in n (30 by default). */
static void bridge_dump(void)
{
    static const char *prefix = (const char *)-1;
    static unsigned every, n, seq;
    ID3D11Texture2D *back = NULL, *staging = NULL;
    D3D11_TEXTURE2D_DESC td;
    D3D11_MAPPED_SUBRESOURCE map;
    ID3D11DeviceContext *ctx = d3d8_GetD3D11Context();
    char path[512];
    FILE *f;
    UINT x, y;

    if (prefix == (const char *)-1) {
        const char *e = getenv("ROBOTECH_D3D11_DUMP_EVERY");
        prefix = getenv("ROBOTECH_D3D11_DUMP");
        every = e ? (unsigned)atoi(e) : 30;
        if (!every)
            every = 1;
    }
    if (!prefix || n++ % every)
        return;
    if (FAILED(IDXGISwapChain_GetBuffer(d3d8_GetSwapChain(), 0, &IID_ID3D11Texture2D, (void **)&back)))
        return;
    ID3D11Texture2D_GetDesc(back, &td);
    td.Usage = D3D11_USAGE_STAGING;
    td.BindFlags = 0;
    td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    td.MiscFlags = 0;
    if (SUCCEEDED(ID3D11Device_CreateTexture2D(d3d8_GetD3D11Device(), &td, NULL, &staging))) {
        ID3D11DeviceContext_CopyResource(ctx, (ID3D11Resource *)staging, (ID3D11Resource *)back);
        if (SUCCEEDED(ID3D11DeviceContext_Map(ctx, (ID3D11Resource *)staging, 0, D3D11_MAP_READ, 0, &map))) {
            uint32_t row = (td.Width * 3 + 3) & ~3u, size = 54 + row * td.Height;
            uint8_t hdr[54], *line = (uint8_t *)calloc(1, row);

            snprintf(path, sizeof path, "%s%05u.bmp", prefix, seq++);
            f = fopen(path, "wb");
            if (f && line) {
                memset(hdr, 0, sizeof hdr);
                hdr[0] = 'B'; hdr[1] = 'M';
                memcpy(hdr + 2, &size, 4);
                hdr[10] = 54; hdr[14] = 40;
                memcpy(hdr + 18, &td.Width, 4);
                memcpy(hdr + 22, &td.Height, 4);
                hdr[26] = 1; hdr[28] = 24;
                fwrite(hdr, 1, sizeof hdr, f);
                /* R8G8B8A8 rows, written bottom-up as BGR. */
                for (y = td.Height; y-- > 0; ) {
                    const uint8_t *p = (const uint8_t *)map.pData + (size_t)y * map.RowPitch;
                    for (x = 0; x < td.Width; x++) {
                        line[x * 3 + 0] = p[x * 4 + 2];
                        line[x * 3 + 1] = p[x * 4 + 1];
                        line[x * 3 + 2] = p[x * 4 + 0];
                    }
                    fwrite(line, 1, row, f);
                }
            }
            if (f)
                fclose(f);
            free(line);
            ID3D11DeviceContext_Unmap(ctx, (ID3D11Resource *)staging, 0);
        }
        ID3D11Texture2D_Release(staging);
    }
    ID3D11Texture2D_Release(back);
}

/* The console's Swap waits for the vertical blank; with the game's
 * pushbuffer never executed nothing makes it wait here, and the host's own
 * vsync is the monitor's (144 Hz on the dev machine): the menu ran that fast.
 * Swaps are held to 60 Hz (ROBOTECH_FPS overrides). */
static void bridge_pace(void)
{
    static LARGE_INTEGER freq, next;
    static double period = 0;
    LARGE_INTEGER now;

    if (period == 0) {
        const char *e = getenv("ROBOTECH_FPS");
        double fps = e ? atof(e) : 60.0;
        QueryPerformanceFrequency(&freq);
        period = fps > 0 ? (double)freq.QuadPart / fps : -1;
        timeBeginPeriod(1);
    }
    if (period < 0)
        return;
    QueryPerformanceCounter(&now);
    if (next.QuadPart == 0 || now.QuadPart - next.QuadPart > (LONGLONG)(period * 4)) {
        next.QuadPart = now.QuadPart + (LONGLONG)period;     /* first, or fell far behind */
        return;
    }
    while (now.QuadPart < next.QuadPart) {
        LONGLONG left_ms = (next.QuadPart - now.QuadPart) * 1000 / freq.QuadPart;
        if (left_ms > 1)
            Sleep((DWORD)(left_ms - 1));
        QueryPerformanceCounter(&now);
    }
    next.QuadPart += (LONGLONG)period;
}

/* D3DDevice_Swap(Flags): present, and pump the window's messages. */
void d3d11_Swap(void)
{
    static DWORD last;
    DWORD now;

    if (!s_dev)
        return;
    bridge_dump();
    bridge_pace();
    s_dev->lpVtbl->Swap(s_dev, arg(0));
    s_presents++;
    now = GetTickCount();
    if (!last)
        last = now;
    if (now - last >= 2000) {
        fprintf(stderr, "[D3D11] %.1f fps, %u clears, %u draws + %u pushed (%u with a pixel shader), "
                "%u left out (vertex program), %d textures\n",
                s_presents * 1000.0 / (now - last), s_clears, s_draws, s_push_draws, s_ps_draws,
                s_skipped_vp, s_tex_count);
        if (getenv("ROBOTECH_D3D11_TRACE")) {
            fprintf(stderr, "[D3D11] transforms: view %u proj %u world %u world1-3 %u/%u/%u tex0 %u\n",
                    s_xforms[0], s_xforms[1], s_xforms[6], s_xforms[7], s_xforms[8], s_xforms[9], s_xforms[2]);
            memset(s_xforms, 0, sizeof s_xforms);
        }
        s_presents = s_clears = s_draws = s_push_draws = s_ps_draws = s_skipped_vp = 0;
        last = now;
    }
}

/* ── Render and texture-stage states ───────────────────────── */

/* The XDK's values, as D3D8Types.h has them, to the layer's (PC) ones. */
static DWORD xb_cmp(uint32_t v)
{
    return v >= 0x200 && v <= 0x207 ? D3DCMP_NEVER + (v - 0x200) : D3DCMP_ALWAYS;
}

static DWORD xb_blend(uint32_t v)
{
    switch (v) {
    case 0:     return D3DBLEND_ZERO;
    case 1:     return D3DBLEND_ONE;
    case 0x300: return D3DBLEND_SRCCOLOR;
    case 0x301: return D3DBLEND_INVSRCCOLOR;
    case 0x302: return D3DBLEND_SRCALPHA;
    case 0x303: return D3DBLEND_INVSRCALPHA;
    case 0x304: return D3DBLEND_DESTALPHA;
    case 0x305: return D3DBLEND_INVDESTALPHA;
    case 0x306: return D3DBLEND_DESTCOLOR;
    case 0x307: return D3DBLEND_INVDESTCOLOR;
    case 0x308: return D3DBLEND_SRCALPHASAT;
    }
    return D3DBLEND_ONE;      /* the constant-colour factors have no D3D8 state */
}

static DWORD xb_blendop(uint32_t v)
{
    switch (v) {
    case 0x800A: return 2;    /* SUBTRACT */
    case 0x800B: return 3;    /* REVSUBTRACT */
    case 0x8007: return 4;    /* MIN */
    case 0x8008: return 5;    /* MAX */
    }
    return 1;                 /* ADD, and the signed ones */
}

static DWORD xb_stencilop(uint32_t v)
{
    switch (v) {
    case 0:      return 2;    /* ZERO */
    case 0x1E01: return 3;    /* REPLACE */
    case 0x1E02: return 4;    /* INCRSAT */
    case 0x1E03: return 5;    /* DECRSAT */
    case 0x150A: return 6;    /* INVERT */
    case 0x8507: return 7;    /* INCR */
    case 0x8508: return 8;    /* DECR */
    }
    return 1;                 /* KEEP */
}

static DWORD xb_colorwrite(uint32_t v)
{
    return ((v & 0x00010000u) ? 1u : 0) | ((v & 0x00000100u) ? 2u : 0)
         | ((v & 0x00000001u) ? 4u : 0) | ((v & 0x01000000u) ? 8u : 0);
}

static DWORD xb_wrap(uint32_t v)
{
    return ((v & 0x10u) ? 1u : 0) | ((v & 0x1000u) ? 2u : 0) | ((v & 0x100000u) ? 4u : 0);
}

static DWORD xb_top(uint32_t v)
{
    switch (v) {
    case 13: return D3DTOP_BLENDCURRENTALPHA;
    case 14: return D3DTOP_BLENDTEXTUREALPHA;
    case 15: return D3DTOP_BLENDFACTORALPHA;
    case 16: return D3DTOP_BLENDTEXTUREALPHA;       /* ...PM: no layer op */
    case 17: return D3DTOP_PREMODULATE;
    case 18: case 19: case 20: case 21:
        return D3DTOP_MODULATE;                     /* MODULATE*_ADD*: no layer op */
    case 22: return D3DTOP_DOTPRODUCT3;
    case 23: return D3DTOP_MULTIPLYADD;
    case 24: return D3DTOP_LERP;
    case 25: case 26:
        return D3DTOP_SELECTARG1;                   /* BUMPENVMAP*: not modelled */
    }
    return v >= 1 && v <= 12 ? v : D3DTOP_DISABLE;  /* DISABLE..BLENDDIFFUSEALPHA match */
}

enum { RS_RAW, RS_CMP, RS_BLEND, RS_BLENDOP, RS_STENCILOP, RS_FILL, RS_SHADE, RS_COLORWRITE, RS_WRAP };

static const struct { uint8_t xb; uint16_t pc; uint8_t kind; } s_rs_map[] = {
    { 57, D3DRS_ZFUNC, RS_CMP },             { 58, D3DRS_ALPHAFUNC, RS_CMP },
    { 59, D3DRS_ALPHABLENDENABLE, RS_RAW },  { 60, D3DRS_ALPHATESTENABLE, RS_RAW },
    { 61, D3DRS_ALPHAREF, RS_RAW },          { 62, D3DRS_SRCBLEND, RS_BLEND },
    { 63, D3DRS_DESTBLEND, RS_BLEND },       { 64, D3DRS_ZWRITEENABLE, RS_RAW },
    { 65, D3DRS_DITHERENABLE, RS_RAW },      { 66, D3DRS_SHADEMODE, RS_SHADE },
    { 67, D3DRS_COLORWRITEENABLE, RS_COLORWRITE },
    { 68, D3DRS_STENCILZFAIL, RS_STENCILOP }, { 69, D3DRS_STENCILPASS, RS_STENCILOP },
    { 70, D3DRS_STENCILFUNC, RS_CMP },       { 71, D3DRS_STENCILREF, RS_RAW },
    { 72, D3DRS_STENCILMASK, RS_RAW },       { 73, D3DRS_STENCILWRITEMASK, RS_RAW },
    { 74, D3DRS_BLENDOP, RS_BLENDOP },
    { 92, D3DRS_FOGENABLE, RS_RAW },         { 93, D3DRS_FOGTABLEMODE, RS_RAW },
    { 94, D3DRS_FOGSTART, RS_RAW },          { 95, D3DRS_FOGEND, RS_RAW },
    { 96, D3DRS_FOGDENSITY, RS_RAW },        { 97, D3DRS_RANGEFOGENABLE, RS_RAW },
    { 98, D3DRS_WRAP0, RS_WRAP },            { 99, D3DRS_WRAP1, RS_WRAP },
    { 100, D3DRS_WRAP2, RS_WRAP },           { 101, D3DRS_WRAP3, RS_WRAP },
    { 102, D3DRS_LIGHTING, RS_RAW },         { 103, D3DRS_SPECULARENABLE, RS_RAW },
    { 104, D3DRS_LOCALVIEWER, RS_RAW },      { 105, D3DRS_COLORVERTEX, RS_RAW },
    { 110, D3DRS_SPECULARMATERIALSOURCE, RS_RAW }, { 111, D3DRS_DIFFUSEMATERIALSOURCE, RS_RAW },
    { 112, D3DRS_AMBIENTMATERIALSOURCE, RS_RAW },  { 113, D3DRS_EMISSIVEMATERIALSOURCE, RS_RAW },
    { 115, D3DRS_AMBIENT, RS_RAW },          { 116, D3DRS_POINTSIZE, RS_RAW },
    { 117, D3DRS_POINTSIZE_MIN, RS_RAW },    { 118, D3DRS_POINTSPRITEENABLE, RS_RAW },
    { 119, D3DRS_POINTSCALEENABLE, RS_RAW },
    { 138, D3DRS_FOGCOLOR, RS_RAW },         { 139, D3DRS_FILLMODE, RS_FILL },
    { 142, D3DRS_NORMALIZENORMALS, RS_RAW }, { 143, D3DRS_ZENABLE, RS_RAW },
    { 144, D3DRS_STENCILENABLE, RS_RAW },    { 145, D3DRS_STENCILFAIL, RS_STENCILOP },
    { 148, D3DRS_TEXTUREFACTOR, RS_RAW },    { 151, D3DRS_EDGEANTIALIAS, RS_RAW },
};

#define XB_RS_FRONTFACE 146
#define XB_RS_CULLMODE  147

static DWORD rs_value(int kind, uint32_t v)
{
    switch (kind) {
    case RS_CMP:        return xb_cmp(v);
    case RS_BLEND:      return xb_blend(v);
    case RS_BLENDOP:    return xb_blendop(v);
    case RS_STENCILOP:  return xb_stencilop(v);
    case RS_FILL:       return v == 0x1B00 ? D3DFILL_POINT : v == 0x1B01 ? D3DFILL_WIREFRAME : D3DFILL_SOLID;
    case RS_SHADE:      return v == 0x1D00 ? 1u : 2u;             /* FLAT, GOURAUD */
    case RS_COLORWRITE: return xb_colorwrite(v);
    case RS_WRAP:       return xb_wrap(v);
    }
    return v;
}

/* Xbox culls by winding against D3DRS_FRONTFACE; the layer culls by winding
 * alone, with clockwise as the front. A counter-clockwise front face swaps
 * which winding the cull mode names. */
static DWORD xb_cull(uint32_t cull, uint32_t front)
{
    int cw;

    if (cull == 0)
        return D3DCULL_NONE;
    cw = (cull == 0x900);
    if (front == 0x901)
        cw = !cw;
    return cw ? D3DCULL_CW : D3DCULL_CCW;
}

static const struct { uint8_t xb; uint16_t pc; uint8_t kind; } s_ts_map[] = {
    { 0, D3DTSS_ADDRESSU, 1 },      { 1, D3DTSS_ADDRESSV, 1 },
    { 3, D3DTSS_MAGFILTER, 2 },     { 4, D3DTSS_MINFILTER, 2 },     { 5, D3DTSS_MIPFILTER, 2 },
    { 6, D3DTSS_MIPMAPLODBIAS, 0 }, { 7, D3DTSS_MAXMIPLEVEL, 0 },   { 8, D3DTSS_MAXANISOTROPY, 0 },
    { 12, D3DTSS_COLOROP, 3 },      { 14, D3DTSS_COLORARG1, 0 },    { 15, D3DTSS_COLORARG2, 0 },
    { 16, D3DTSS_ALPHAOP, 3 },      { 18, D3DTSS_ALPHAARG1, 0 },    { 19, D3DTSS_ALPHAARG2, 0 },
    { 20, D3DTSS_RESULTARG, 0 },
};

static DWORD ts_value(int kind, uint32_t v)
{
    switch (kind) {
    case 1: return v == 5 ? D3DTADDRESS_CLAMP : v;                 /* CLAMPTOEDGE */
    case 2: return v > D3DTEXF_ANISOTROPIC ? D3DTEXF_LINEAR : v;    /* QUINCUNX, GAUSSIANCUBIC */
    case 3: return xb_top(v);
    }
    return v;
}

/* The simple states (index < D3DRS_SIMPLE_MAX, 92) are the exception: the
 * game is built as a pure device, so the inlined SetRenderState sends them
 * through D3DDevice_SetRenderState_Simple and does not store them -- its
 * array kept D3D's defaults while the menu's text was drawn with blending.
 * SetRenderState_Simple takes the NV2A method the state is (the XDK's
 * D3DSIMPLERENDERSTATEENCODE, in D3D8.h) and the value as the XDK has it, so
 * the method says which state and the bridge keeps its own copy. */
#define XB_RS_SIMPLE_MAX 92

static const uint16_t s_simple_method[XB_RS_SIMPLE_MAX] = {
    0x0260, 0x0264, 0x0268, 0x026C, 0x0270, 0x0274, 0x0278, 0x027C,    /*  0 PSALPHAINPUTS */
    0x0288, 0x028C, 0x0A60, 0x0A64, 0x0A68, 0x0A6C, 0x0A70, 0x0A74,    /*  8 */
    0x0A78, 0x0A7C, 0x0A80, 0x0A84, 0x0A88, 0x0A8C, 0x0A90, 0x0A94,    /* 16 */
    0x0A98, 0x0A9C, 0x0AA0, 0x0AA4, 0x0AA8, 0x0AAC, 0x0AB0, 0x0AB4,    /* 24 */
    0x0AB8, 0x0ABC, 0x0AC0, 0x0AC4, 0x0AC8, 0x0ACC, 0x0AD0, 0x0AD4,    /* 32 */
    0x0AD8, 0x0ADC, 0x17F8, 0x1E20, 0x1E24, 0x1E40, 0x1E44, 0x1E48,    /* 40 */
    0x1E4C, 0x1E50, 0x1E54, 0x1E58, 0x1E5C, 0x1E60, 0,      0x1E74,    /* 48; 54 reserved */
    0x1E78, 0x0354, 0x033C, 0x0304, 0x0300, 0x0340, 0x0344, 0x0348,    /* 56; 57 ZFUNC */
    0x035C, 0x0310, 0x037C, 0x0358, 0x0374, 0x0378, 0x0364, 0x0368,    /* 64 */
    0x036C, 0x0360, 0x0350, 0x034C, 0x09F8, 0x0384, 0x0388, 0x0330,    /* 72 */
    0x0334, 0x0338, 0x1D78, 0x147C, 0, 0, 0, 0,                        /* 80; 84.. unused */
    0, 0, 0, 0,
};
static uint32_t s_simple[XB_RS_SIMPLE_MAX];
static uint8_t s_simple_set[XB_RS_SIMPLE_MAX];

/* D3DDevice_SetRenderState_Simple(Method, Value), fastcall: ecx, edx. */
void d3d11_SetRenderStateSimple(void)
{
    uint32_t method = g_ecx & 0x1FFCu;
    int i;

    for (i = 0; i < XB_RS_SIMPLE_MAX; i++)
        if (s_simple_method[i] == method) {
            s_simple[i] = g_edx;
            s_simple_set[i] = 1;
            return;
        }
}

/* Send what changed in the game's state arrays since the last draw. */
static void bridge_sync_states(void)
{
    uint32_t rs[XB_RS_MAX], ts[BRIDGE_STAGES][XB_TSS_MAX];
    size_t i;
    int s;

    memcpy(rs, guest_ptr(XB_RENDER_STATE_VA), sizeof rs);
    memcpy(ts, guest_ptr(XB_TEXTURE_STATE_VA), sizeof ts);
    for (s = 0; s < XB_RS_SIMPLE_MAX; s++)
        if (s_simple_set[s])
            rs[s] = s_simple[s];
    for (i = 0; i < sizeof s_rs_map / sizeof s_rs_map[0]; i++) {
        uint8_t x = s_rs_map[i].xb;
        if (s_states_sent && rs[x] == s_rs_sent[x])
            continue;
        s_dev->lpVtbl->SetRenderState(s_dev, (D3DRENDERSTATETYPE)s_rs_map[i].pc,
                                      rs_value(s_rs_map[i].kind, rs[x]));
    }
    if (!s_states_sent || rs[XB_RS_CULLMODE] != s_rs_sent[XB_RS_CULLMODE]
            || rs[XB_RS_FRONTFACE] != s_rs_sent[XB_RS_FRONTFACE])
        s_dev->lpVtbl->SetRenderState(s_dev, D3DRS_CULLMODE,
                                      xb_cull(rs[XB_RS_CULLMODE], rs[XB_RS_FRONTFACE]));
    for (s = 0; s < BRIDGE_STAGES; s++) {
        for (i = 0; i < sizeof s_ts_map / sizeof s_ts_map[0]; i++) {
            uint8_t x = s_ts_map[i].xb;
            if (s_states_sent && ts[s][x] == s_ts_sent[s][x])
                continue;
            s_dev->lpVtbl->SetTextureStageState(s_dev, (DWORD)s, (D3DTEXTURESTAGESTATETYPE)s_ts_map[i].pc,
                                                ts_value(s_ts_map[i].kind, ts[s][x]));
        }
    }
    memcpy(s_rs_sent, rs, sizeof rs);
    memcpy(s_ts_sent, ts, sizeof ts);
    s_states_sent = 1;
}

/* D3DDevice_SetTextureState_TexCoordIndex(Stage, Value): not kept in the
 * game's array, so it is taken here. Also says which coordinate set a stage
 * reads, which the linear-texture fix-up needs. */
void d3d11_SetTexCoordIndex(void)
{
    uint32_t stage = arg(0), value = arg(1);

    if (!s_dev || stage >= BRIDGE_STAGES)
        return;
    s_tci[stage] = value & 0xFFFFu;
    s_dev->lpVtbl->SetTextureStageState(s_dev, stage, D3DTSS_TEXCOORDINDEX, value);
}

/* ── Transforms, viewport, material, lights ────────────────── */

/* D3DDevice_SetTransform(State, pMatrix): the XDK numbers the transforms
 * VIEW 0, PROJECTION 1, TEXTURE0-3 2-5, WORLD 6, WORLD1-3 7-9. */
void d3d11_SetTransform(void)
{
    uint32_t state = arg(0), m = arg(1);
    D3DTRANSFORMSTATETYPE pc;

    if (!s_dev || !m || state > 9)
        return;
    s_xforms[state]++;
    if (state == 0)
        pc = D3DTS_VIEW;
    else if (state == 1)
        pc = D3DTS_PROJECTION;
    else if (state <= 5)
        pc = (D3DTRANSFORMSTATETYPE)(D3DTS_TEXTURE0 + (state - 2));
    else
        pc = (D3DTRANSFORMSTATETYPE)(D3DTS_WORLD + (state - 6));
    s_dev->lpVtbl->SetTransform(s_dev, pc, (const D3DMATRIX *)guest_ptr(m));
}

/* D3DDevice_SetViewport(pViewport): the same six fields on both sides. */
void d3d11_SetViewport(void)
{
    uint32_t vp = arg(0);

    if (s_dev && vp)
        s_dev->lpVtbl->SetViewport(s_dev, (const D3DVIEWPORT8 *)guest_ptr(vp));
}

/* D3DDevice_SetMaterial(pMaterial): 17 floats on both sides. */
void d3d11_SetMaterial(void)
{
    uint32_t m = arg(0);

    if (s_dev && m)
        s_dev->lpVtbl->SetMaterial(s_dev, (const D3DMATERIAL8 *)guest_ptr(m));
}

/* D3DDevice_SetLight(Index, pLight): the same layout and light types. */
void d3d11_SetLight(void)
{
    uint32_t i = arg(0), l = arg(1);

    if (s_dev && l)
        s_dev->lpVtbl->SetLight(s_dev, i, (const D3DLIGHT8 *)guest_ptr(l));
}

/* D3DDevice_LightEnable(Index, bEnable). */
void d3d11_LightEnable(void)
{
    if (s_dev)
        s_dev->lpVtbl->LightEnable(s_dev, arg(0), (BOOL)arg(1));
}

/* ── Textures ──────────────────────────────────────────────── */

/* Where a resource's data is, as the CPU sees it: Data is a physical address,
 * and physical memory shows through the contiguous window. */
static uint32_t phys_va(uint32_t data)
{
    return data < XB_CONTIG_SIZE ? XB_CONTIG_BASE + data : data;
}

/* The bridge's record of a guest texture, made (or remade, when the game
 * reuses the address for another texture) from its Format and Size words. */
static BridgeTexture *bridge_texture(uint32_t va)
{
    uint32_t fw = guest32(va + XB_RES_FORMAT), sw = guest32(va + XB_RES_SIZE);
    BridgeTexture *t = NULL;
    HRESULT hr;
    int i;

    for (i = 0; i < s_tex_count; i++)
        if (s_tex[i].va == va) {
            t = &s_tex[i];
            break;
        }
    if (t && t->format_word == fw && t->size_word == sw)
        return t;
    if (!t) {
        if (s_tex_count == BRIDGE_MAX_TEXTURES)
            return NULL;
        t = &s_tex[s_tex_count++];
    } else if (t->host) {
        t->host->lpVtbl->Release(t->host);
    }
    memset(t, 0, sizeof *t);
    t->va = va;
    t->format_word = fw;
    t->size_word = sw;
    t->format = (D3DFORMAT)((fw >> 8) & 0xFFu);
    t->levels = (fw >> 16) & 0xFu;
    if (!t->levels)
        t->levels = 1;
    if (sw) {
        t->width = (sw & 0xFFFu) + 1;
        t->height = ((sw >> 12) & 0xFFFu) + 1;
        t->pitch = (((sw >> 24) & 0xFFu) + 1) * 64;
        t->levels = 1;
    } else {
        t->width = 1u << ((fw >> 20) & 0xFu);
        t->height = 1u << ((fw >> 24) & 0xFu);
    }
    hr = s_dev->lpVtbl->CreateTexture(s_dev, t->width, t->height, t->levels, 0, t->format,
                                      D3DPOOL_MANAGED, &t->host);
    fprintf(stderr, "[D3D11] texture 0x%08X: %ux%u format 0x%02X, %u level(s)%s: %s\n",
            va, t->width, t->height, (unsigned)t->format, t->levels, sw ? ", linear" : "",
            SUCCEEDED(hr) ? "created" : "failed");
    if (FAILED(hr))
        t->host = NULL;
    t->dirty = 1;
    return t;
}

/* Copy the guest's texels into the host texture, level by level. The layer
 * takes the bytes as the Xbox keeps them (swizzled formats are unswizzled on
 * upload); only a linear texture's rows need repacking, its guest pitch
 * being a multiple of 64. A block-compressed level has a row per four lines
 * of texels: copying a row per line wrote four times past the layer's
 * buffer, and the heap corruption ended the process with no report. */
extern BOOL d3d8_format_is_compressed(D3DFORMAT fmt);

static void bridge_upload(BridgeTexture *t)
{
    const uint8_t *src = (const uint8_t *)guest_ptr(phys_va(guest32(t->va + XB_RES_DATA)));
    BOOL blocks = d3d8_format_is_compressed(t->format);
    UINT level;

    if (!t->host || !src)
        return;
    for (level = 0; level < t->levels; level++) {
        D3DLOCKED_RECT lr;
        UINT h = t->height >> level ? t->height >> level : 1;
        UINT rows = blocks ? (h + 3) / 4 : h;
        UINT row_bytes, y;

        if (FAILED(t->host->lpVtbl->LockRect(t->host, level, &lr, NULL, 0)))
            break;
        if (t->pitch) {
            row_bytes = (UINT)lr.Pitch < t->pitch ? (UINT)lr.Pitch : t->pitch;
            for (y = 0; y < rows; y++)
                memcpy((uint8_t *)lr.pBits + (size_t)y * lr.Pitch, src + (size_t)y * t->pitch, row_bytes);
        } else {
            /* Swizzled levels follow one another with no padding. */
            size_t bytes = (size_t)lr.Pitch * rows;
            memcpy(lr.pBits, src, bytes);
            src += bytes;
        }
        t->host->lpVtbl->UnlockRect(t->host, level);
    }
    t->dirty = 0;
}

/* D3DDevice_SetTexture(Stage, pTexture). */
void d3d11_SetTexture(void)
{
    uint32_t stage = arg(0), va = arg(1);
    BridgeTexture *t;

    if (!s_dev || stage >= BRIDGE_STAGES)
        return;
    t = va ? bridge_texture(va) : NULL;
    s_stage[stage] = t;
    s_dev->lpVtbl->SetTexture(s_dev, stage, t ? (IDirect3DBaseTexture8 *)t->host : NULL);
}

/* D3DTexture_LockRect(pThis, Level, pLockedRect, pRect, Flags): the game is
 * about to write the texels (Bink decodes every movie frame this way), so the
 * texture is uploaded again before its next draw. */
void d3d11_TextureLockRect(void)
{
    uint32_t va = arg(0);
    int i;

    if (!s_dev)
        return;
    for (i = 0; i < s_tex_count; i++)
        if (s_tex[i].va == va)
            s_tex[i].dirty = 1;
}

/* ── Drawing ───────────────────────────────────────────────── */

/* D3DDevice_SetVertexShader(Handle). An FVF code goes through as it is; a
 * vertex program (its handle has bit 0 set) is not routed yet. */
void d3d11_SetVertexShader(void)
{
    uint32_t handle = arg(0);

    if (!s_dev)
        return;
    if (handle & 1u) {
        static int said;
        if (!said++)
            fprintf(stderr, "[D3D11] vertex program 0x%08X not routed\n", handle);
        s_fvf = 0;
        return;
    }
    s_fvf = handle;
    s_dev->lpVtbl->SetVertexShader(s_dev, handle);
}

/* Where an FVF vertex's texture coordinates start, and how many floats each
 * set has. The FVF bits are the same on the Xbox and the PC. */
static UINT fvf_texcoords(uint32_t fvf, UINT floats[8])
{
    static const UINT pos_bytes[8] = { 0, 12, 16, 16, 20, 24, 28, 0 };
    UINT off = pos_bytes[(fvf >> 1) & 7u], sets = (fvf >> 8) & 0xFu, k;

    if (fvf & D3DFVF_NORMAL)   off += 12;
    if (fvf & 0x020u)          off += 4;      /* D3DFVF_PSIZE */
    if (fvf & D3DFVF_DIFFUSE)  off += 4;
    if (fvf & D3DFVF_SPECULAR) off += 4;
    for (k = 0; k < 8; k++) {
        static const UINT size_floats[4] = { 2, 3, 4, 1 };
        floats[k] = k < sets ? size_floats[(fvf >> (16 + 2 * k)) & 3u] : 0;
    }
    return off;
}

/* A linear texture is sampled with coordinates in texels on the Xbox, and in
 * 0..1 on the host: the game's vertices go to the host with those sets
 * divided by the texture's size. Stage k reads the set its TEXCOORDINDEX
 * names (k by default). Returns the vertices to draw, the game's own when
 * nothing needs rewriting. */
static const void *bridge_vertices(const uint8_t *src, UINT vertices, UINT stride)
{
    UINT floats[8], off, k, v;
    size_t bytes = (size_t)vertices * stride;
    int any = 0;

    if (!s_fvf)
        return src;
    off = fvf_texcoords(s_fvf, floats);
    for (k = 0; k < BRIDGE_STAGES; k++)
        if (s_tci[k] < 8 && floats[s_tci[k]] && s_stage[k] && s_stage[k]->pitch)
            any = 1;
    if (!any)
        return src;
    if (bytes > s_scratch_size) {
        free(s_scratch);
        s_scratch = (uint8_t *)malloc(bytes);
        s_scratch_size = s_scratch ? bytes : 0;
        if (!s_scratch)
            return src;
    }
    memcpy(s_scratch, src, bytes);
    for (k = 0; k < BRIDGE_STAGES; k++) {
        BridgeTexture *t = s_stage[k];
        UINT set = s_tci[k], set_off = off, j;

        if (set >= 8 || !floats[set] || !t || !t->pitch)
            continue;
        for (j = 0; j < set; j++)
            set_off += floats[j] * 4;
        for (v = 0; v < vertices; v++) {
            float *uv = (float *)(s_scratch + (size_t)v * stride + set_off);
            uv[0] /= (float)t->width;
            if (floats[set] > 1)
                uv[1] /= (float)t->height;
        }
    }
    return s_scratch;
}

/* The XDK's primitive types, and the layer's (PC) ones they become. A line
 * loop draws as a strip, a quad strip as a triangle strip and a polygon as a
 * fan, which is what they are made of. */
static int bridge_primitive(uint32_t xb, uint32_t vertices, D3DPRIMITIVETYPE *pt, UINT *count)
{
    switch (xb) {
    case 1: *pt = D3DPT_POINTLIST;     *count = vertices;                       return 1;
    case 2: *pt = D3DPT_LINELIST;      *count = vertices / 2;                   return 1;
    case 3:
    case 4: *pt = D3DPT_LINESTRIP;     *count = vertices > 1 ? vertices - 1 : 0; return 1;
    case 5: *pt = D3DPT_TRIANGLELIST;  *count = vertices / 3;                   return 1;
    case 6:
    case 9: *pt = D3DPT_TRIANGLESTRIP; *count = vertices > 2 ? vertices - 2 : 0; return 1;
    case 7:
    case 10: *pt = D3DPT_TRIANGLEFAN;  *count = vertices > 2 ? vertices - 2 : 0; return 1;
    case 8: *pt = D3DPT_QUADLIST;      *count = vertices / 4;                   return 1;
    }
    return 0;
}

/* What every draw needs first: the states the game set since the last one,
 * and the textures it wrote. Returns 0 when the draw cannot be routed yet: a
 * vertex program is set, and the bridge has no translation for those. */
static int bridge_before_draw(void)
{
    int s;

    if (!s_fvf) {
        s_skipped_vp++;
        return 0;
    }
    if (s_pixel_shader)
        s_ps_draws++;
    bridge_sync_states();
    for (s = 0; s < BRIDGE_STAGES; s++)
        if (s_stage[s] && s_stage[s]->dirty)
            bridge_upload(s_stage[s]);
    return 1;
}

/* D3DDevice_DrawVerticesUP(PrimitiveType, VertexCount, pVertexStreamZeroData,
 * VertexStreamZeroStride). */
void d3d11_DrawVerticesUP(void)
{
    uint32_t xbtype = arg(0), vertices = arg(1), data = arg(2), stride = arg(3);
    D3DPRIMITIVETYPE pt;
    UINT count;

    if (!s_dev || !data || !bridge_primitive(xbtype, vertices, &pt, &count) || !count)
        return;
    if (!bridge_before_draw())
        return;
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count,
                                   bridge_vertices((const uint8_t *)guest_ptr(data), vertices, stride),
                                   stride);
    s_draws++;
}

/* D3DDevice_SetPixelShader(Handle): not routed yet, only noted, so the
 * bridge's log says how many draws are made with one. */
void d3d11_SetPixelShader(void)
{
    s_pixel_shader = arg(0);
}

/* ── The game's own pushbuffer writes ──────────────────────── */

/* D3DDevice_BeginPush_4(Count) hands the game a pointer into the pushbuffer
 * (its return value) and D3DDevice_EndPush(pPush) takes back where it
 * stopped: in between the game wrote NV2A commands itself, which no D3D entry
 * shows. Measured on the menu: 19 a frame, every one SET_BEGIN_END(primitive),
 * INLINE_ARRAY(vertices), SET_BEGIN_END(0) -- an immediate-mode draw, which
 * is how the engine draws everything 2D (the backdrop, the boxes, the text).
 * The vertices are laid out as the FVF in force, and NV2A numbers its
 * primitives as the XDK does, so each becomes a DrawPrimitiveUP.
 * ROBOTECH_D3D11_PUSH=1 also counts what was pushed, by method, every two
 * seconds: what a fuller decoder would have to cover. */
#define NV097_SET_BEGIN_END  0x17FCu
#define NV097_INLINE_ARRAY   0x1818u

static uint32_t s_push_start;
static uint32_t *s_inline;              /* one Begin/End's inline vertices */
static size_t s_inline_cap;

void d3d11_BeginPushDone(void)
{
    s_push_start = g_eax;
}

static UINT fvf_size(uint32_t fvf)
{
    UINT floats[8], size = fvf_texcoords(fvf, floats), k;

    for (k = 0; k < 8; k++)
        size += floats[k] * 4;
    return size;
}

/* ROBOTECH_D3D11_TRACE=1: what the first draws with each texture look like,
 * for telling a sampling problem from a state one without guessing. */
static void trace_draw(const char *what, uint32_t prim, UINT vertices, UINT stride, const uint8_t *v)
{
    static int on = -1;
    static uint32_t seen[64];
    static int nseen;
    const uint32_t *ts = (const uint32_t *)guest_ptr(XB_TEXTURE_STATE_VA);
    uint32_t va = s_stage[0] ? s_stage[0]->va : 0;
    int i;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_D3D11_TRACE");
        on = e && *e == '1';
    }
    if (!on)
        return;
    if (!va) {
        /* Untextured: the colour is the point (a fade, a letterbox bar), and
         * for a pushed draw, who pushed it (EndPush's return address). Each
         * (caller, colour) once. */
        static uint32_t pairs[256][2];
        static int npairs;
        static const UINT pos_bytes[8] = { 0, 12, 16, 16, 20, 24, 28, 0 };
        UINT off = pos_bytes[(s_fvf >> 1) & 7u] + ((s_fvf & D3DFVF_NORMAL) ? 12 : 0) + ((s_fvf & 0x20u) ? 4 : 0);
        uint32_t c = 0;
        if (s_fvf & D3DFVF_DIFFUSE)
            memcpy(&c, v + off, 4);
        for (i = 0; i < npairs; i++)
            if (pairs[i][0] == s_push_caller && pairs[i][1] == c)
                return;
        if (npairs == 256)
            return;
        pairs[npairs][0] = s_push_caller;
        pairs[npairs++][1] = c;
        fprintf(stderr, "[TRACE] %s untextured prim %u, %u vertices, FVF 0x%X, diffuse %08X, from 0x%08X\n  stack:",
                what, prim, vertices, s_fvf, c, s_push_caller);
        {
            /* Return addresses into the game's code, innermost first: a
             * scan, not a frame walk (the code is frame-pointer-less). */
            uint32_t sp, shown = 0;
            for (sp = g_esp; sp < g_esp + 0x400 && shown < 12; sp += 4) {
                uint32_t w = guest32(sp);
                if (w >= 0x00011000u && w < 0x00155400u) {
                    fprintf(stderr, " %08X", w);
                    shown++;
                }
            }
            fprintf(stderr, "\n");
        }
        return;
    }
    if (nseen >= 64)
        return;
    for (i = 0; i < nseen; i++)
        if (seen[i] == va)
            return;
    seen[nseen++] = va;
    fprintf(stderr, "[TRACE] %s prim %u, %u vertices of %u bytes, FVF 0x%X; stage 0 texture 0x%08X",
            what, prim, vertices, stride, s_fvf, va);
    if (s_stage[0])
        fprintf(stderr, " %ux%u fmt 0x%02X%s", s_stage[0]->width, s_stage[0]->height,
                (unsigned)s_stage[0]->format, s_stage[0]->pitch ? " linear" : "");
    fprintf(stderr, "; COLOROP %u ARG1 %u ARG2 %u, ALPHAOP %u; TCI %u\n", ts[12], ts[14], ts[15], ts[16], s_tci[0]);
    {
        const uint32_t *rs = s_rs_sent;      /* as last sent, simple states included */
        fprintf(stderr, "  sent: ZFUNC %X ALPHABLEND %u SRC %X DEST %X ALPHATEST %u ALPHAFUNC %X REF %u"
                " ZWRITE %u ZENABLE %u CULL %X LIGHTING %u VERTEXBLEND %u\n", rs[57], rs[59], rs[62], rs[63],
                rs[60], rs[58], rs[61], rs[64], rs[143], rs[147], rs[102],
                ((const uint32_t *)guest_ptr(XB_RENDER_STATE_VA))[137]);
    }
    fprintf(stderr, "  first vertex:");
    for (i = 0; i < (int)(stride / 4) && i < 10; i++) {
        float f;
        memcpy(&f, v + 4 * i, 4);
        fprintf(stderr, " %g", f);
    }
    fprintf(stderr, "\n");
}

static void push_draw(uint32_t prim, const uint32_t *words, size_t n)
{
    static int skip = -1;
    UINT stride, vertices, count;
    D3DPRIMITIVETYPE pt;

    if (skip < 0) {
        const char *e = getenv("ROBOTECH_D3D11_NOPUSH");     /* debugging: leave them out */
        skip = e && *e == '1';
    }
    if (skip || !s_fvf || !n)
        return;
    stride = fvf_size(s_fvf);
    vertices = (UINT)(n * 4 / stride);
    if (!stride || !bridge_primitive(prim, vertices, &pt, &count) || !count)
        return;
    if (!bridge_before_draw())
        return;
    trace_draw("pushed", prim, vertices, stride, (const uint8_t *)words);
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count,
                                   bridge_vertices((const uint8_t *)words, vertices, stride), stride);
    s_push_draws++;
}

static void push_count(uint32_t method)
{
    static int on = -1;
    static unsigned counts[0x800];
    static DWORD last;
    DWORD now;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_D3D11_PUSH");
        on = e && *e == '1';
    }
    if (!on)
        return;
    counts[(method >> 2) & 0x7FF]++;
    now = GetTickCount();
    if (!last)
        last = now;
    if (now - last >= 2000) {
        unsigned i, shown = 0;
        fprintf(stderr, "[PUSH] methods:");
        for (i = 0; i < 0x800 && shown < 24; i++)
            if (counts[i]) {
                fprintf(stderr, " %03X x%u", i << 2, counts[i]);
                shown++;
            }
        fprintf(stderr, "\n");
        memset(counts, 0, sizeof counts);
        last = now;
    }
}

void d3d11_EndPush(void)
{
    uint32_t p, end = arg(0), prim = 0;
    size_t have = 0;

    if (!s_dev || !s_push_start || end <= s_push_start || end - s_push_start > 0x100000) {
        s_push_start = 0;
        return;
    }
    s_push_caller = guest32(g_esp);
    for (p = s_push_start; p < end; ) {
        uint32_t h = guest32(p), n = (h >> 18) & 0x7FFu, m = h & 0x1FFCu, i;

        if (h & 0x20000000u || (h & 3u) == 1 || !n)       /* a jump or a call: not expected here */
            break;
        push_count(m);
        if (m == NV097_SET_BEGIN_END) {
            uint32_t v = guest32(p + 4);
            if (v == 0) {
                push_draw(prim, s_inline, have);
                prim = 0;
            } else {
                prim = v;
            }
            have = 0;
        } else if (m == NV097_INLINE_ARRAY && prim) {
            if (have + n > s_inline_cap) {
                size_t cap = (have + n) * 2;
                uint32_t *grown = (uint32_t *)realloc(s_inline, cap * 4);
                if (!grown)
                    break;
                s_inline = grown;
                s_inline_cap = cap;
            }
            for (i = 0; i < n; i++)
                s_inline[have + i] = guest32(p + 4 + 4 * i);
            have += n;
        }
        p += 4 + 4 * n;
    }
    s_push_start = 0;
}

/* D3DDevice_SetStreamSource(StreamNumber, pStreamData, Stride). Stream 0 is
 * the one an FVF draw reads; the others only serve vertex programs. */
void d3d11_SetStreamSource(void)
{
    if (s_dev && arg(0) == 0) {
        s_stream_va = arg(1);
        s_stream_stride = arg(2);
    }
}

/* D3DDevice_SetIndices(pIndexData, BaseVertexIndex): the XDK's indexed draw
 * takes its indices as a pointer, so only the base vertex matters here. */
void d3d11_SetIndices(void)
{
    if (s_dev)
        s_base_vertex = arg(1);
}

/* The vertices stream 0 points at: a D3DVertexBuffer, whose Data is the
 * physical address of the vertices, like a texture's. */
static const uint8_t *stream_vertices(void)
{
    if (!s_stream_va)
        return NULL;
    return (const uint8_t *)guest_ptr(phys_va(guest32(s_stream_va + XB_RES_DATA)));
}

/* D3DDevice_DrawVertices(PrimitiveType, StartVertex, VertexCount). */
void d3d11_DrawVertices(void)
{
    uint32_t xbtype = arg(0), start = arg(1), vertices = arg(2);
    const uint8_t *vb = stream_vertices();
    D3DPRIMITIVETYPE pt;
    UINT count;

    if (!s_dev || !vb || !s_stream_stride || !bridge_primitive(xbtype, vertices, &pt, &count) || !count)
        return;
    if (!bridge_before_draw())
        return;
    vb += (size_t)start * s_stream_stride;
    trace_draw("vertices", xbtype, vertices, s_stream_stride, vb);
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count, bridge_vertices(vb, vertices, s_stream_stride),
                                   s_stream_stride);
    s_draws++;
}

/* D3DDevice_DrawIndexedVertices(PrimitiveType, VertexCount, pIndexData):
 * VertexCount is the number of 16-bit indices, which index from the base
 * vertex SetIndices gave. */
void d3d11_DrawIndexedVertices(void)
{
    uint32_t xbtype = arg(0), indices = arg(1), ib = arg(2);
    const uint8_t *vb = stream_vertices();
    const uint16_t *idx = (const uint16_t *)guest_ptr(ib);
    D3DPRIMITIVETYPE pt;
    UINT count, i, lo = 0xFFFF, hi = 0;

    if (!s_dev || !vb || !idx || !s_stream_stride || !bridge_primitive(xbtype, indices, &pt, &count) || !count)
        return;
    if (!bridge_before_draw())
        return;
    for (i = 0; i < indices; i++) {
        if (idx[i] < lo) lo = idx[i];
        if (idx[i] > hi) hi = idx[i];
    }
    vb += (size_t)s_base_vertex * s_stream_stride;
    trace_draw("indexed", xbtype, hi + 1, s_stream_stride, vb + (size_t)lo * s_stream_stride);
    /* The range starts at vertex 0, not at the lowest index: the layer's
     * DrawIndexedPrimitiveUP copies NumVertices vertices from the start of
     * the data whatever MinVertexIndex says, so a range from `lo` left the
     * top of the indices pointing past what it copied, and every part of
     * the menu's Valkyrie that did not start at index 0 came out mangled. */
    (void)lo;
    s_dev->lpVtbl->DrawIndexedPrimitiveUP(s_dev, pt, 0, hi + 1, count, idx, D3DFMT_INDEX16,
                                          bridge_vertices(vb, hi + 1, s_stream_stride), s_stream_stride);
    s_draws++;
}
