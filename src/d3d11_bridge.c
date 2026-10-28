/**
 *    Name:        d3d11_bridge.c
 *    Description: routes the game's Direct3D (the XDK's, statically linked and recompiled) to Direct3D 11
 *                 through xboxrecomp's D3D8 layer
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    28-10-2026
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
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>
#include <nv2a_vsh_interp.h>

#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax, g_ecx, g_edx;
extern ptrdiff_t g_xbox_mem_offset;

/* xboxrecomp's D3D8 layer, internal accessors (src/d3d/d3d8_internal.h). */
extern ID3D11Device *d3d8_GetD3D11Device(void);
extern ID3D11DeviceContext *d3d8_GetD3D11Context(void);
extern IDXGISwapChain *d3d8_GetSwapChain(void);
extern UINT d3d8_GetBackbufferWidth(void);
extern UINT d3d8_GetBackbufferHeight(void);

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
#define XB_TSS_TEXTURETRANSFORMFLAGS 21
#define XB_TSS_TEXCOORDINDEX         28
#define XB_TTFF_PROJECTED            0x100u

/* The device the game's D3D keeps (D3D_g_pDevice) holds the surfaces it draws
 * to: D3DDevice_SetRenderTarget stores them there, GetRenderTarget2 and
 * GetDepthStencilSurface2 read them back. A D3DSurface is a
 * D3DPixelContainer and then the texture it is a level of, none for the
 * device's own. */
#define XB_DEVICE_PTR_VA         0x00166B48u
#define XB_DEVICE_RENDER_TARGET  0x21B4u
#define XB_DEVICE_DEPTH_STENCIL  0x21B8u
#define XB_SURFACE_PARENT        0x14u

typedef struct {
    uint32_t va;               /* the guest D3DTexture */
    uint32_t format_word, size_word;
    IDirect3DTexture8 *host;
    UINT width, height, levels, pitch;
    D3DFORMAT format;
    int dirty;                 /* the game locked it since the last upload */
    int target;                /* the game draws to it: a render target on the host, never uploaded */
    IDirect3DCubeTexture8 *cube;  /* a target sampled projectively: copied to this cube's +Z face, sampled there */
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
static uint32_t s_guest_rt = 0xFFFFFFFFu, s_guest_zs;  /* the surfaces the game draws to, as last seen */
static BridgeTexture *s_target;                /* the texture drawn to; NULL: the back buffer */
static IDirect3DSurface8 *s_target_depth;      /* a depth buffer of its size */
static UINT s_target_depth_w, s_target_depth_h;
static float s_world[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };  /* SetTransform's WORLD */
static float s_tex_matrix[BRIDGE_STAGES][16];  /* SetTransform's TEXTURE0-3, as the game set them */
static float s_tex_sent[BRIDGE_STAGES][16];    /* what the layer was given for them */
static int s_tex_matrix_set[BRIDGE_STAGES], s_tex_sent_valid[BRIDGE_STAGES];
static uint32_t s_stream_va, s_stream_stride, s_base_vertex;
static struct {
    uint32_t va, stride;
} s_streams[16];                       /* SetStreamSource's, every stream */
static D3DVIEWPORT8 s_viewport;        /* SetViewport's, for vertex programs */
static struct Vprog *s_vprog;          /* the vertex program selected; NULL: the FVF */
static unsigned s_vp_draws, s_vp_failed;
static struct Vprog *vprog_find(uint32_t handle);
static void vprog_load(struct Vprog *p, uint32_t at);
static int vprog_transform(uint32_t first, uint32_t count, uint32_t base, uint32_t up_data, uint32_t up_stride);
static void vprog_draw(D3DPRIMITIVETYPE pt, UINT count, UINT vertices, const uint16_t *idx);
static unsigned s_skipped_vp;          /* draws left out: vertex program set */
static unsigned s_push_draws;          /* drawn from the game's own pushbuffer writes */
static uint32_t s_pixel_shader;        /* the game's, not routed yet */
static unsigned s_ps_draws;            /* draws made while one was set */
static unsigned s_xforms[10];          /* SetTransform calls, by XDK state */
static unsigned s_frame;               /* Swaps so far */
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

unsigned d3d11_FrameCount(void)
{
    return s_frame;
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

static void bridge_follow_target(void);
static void bridge_bind(uint32_t stage);

/* D3DDevice_Clear(Count, pRects, Flags, Color, Z, Stencil). */
void d3d11_Clear(void)
{
    uint32_t count = arg(0), rects_va = arg(1), xflags = arg(2);
    uint32_t color = arg(3), zbits = arg(4), stencil = arg(5);
    DWORD flags = 0;
    float z;

    if (!s_dev)
        return;
    bridge_follow_target();
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
/* ROBOTECH_D3D11_PICK=<frame>:<x>,<y>: in that frame, every draw that changes
 * the back buffer's pixel (x, y), 640 x 480, with what it was drawn with and
 * from where: which draw makes a pixel that differs from the original's. */
static void bridge_pick(const char *what)
{
    static long frame = -2;
    static UINT px, py;
    static uint32_t last;
    static unsigned draws;
    ID3D11Texture2D *back = NULL, *staging = NULL;
    D3D11_TEXTURE2D_DESC td;
    D3D11_MAPPED_SUBRESOURCE map;
    D3D11_BOX box;
    ID3D11DeviceContext *ctx = d3d8_GetD3D11Context();
    uint32_t now = 0;

    if (frame == -2) {
        const char *e = getenv("ROBOTECH_D3D11_PICK");
        frame = e && sscanf(e, "%ld:%u,%u", &frame, &px, &py) == 3 ? frame : -1;
    }
    if (frame < 0 || s_frame != (unsigned)frame || s_target)
        return;
    draws++;
    if (FAILED(IDXGISwapChain_GetBuffer(d3d8_GetSwapChain(), 0, &IID_ID3D11Texture2D, (void **)&back)))
        return;
    ID3D11Texture2D_GetDesc(back, &td);
    td.Width = td.Height = 1;
    td.MipLevels = td.ArraySize = 1;
    td.SampleDesc.Count = 1;
    td.SampleDesc.Quality = 0;
    td.Usage = D3D11_USAGE_STAGING;
    td.BindFlags = 0;
    td.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    td.MiscFlags = 0;
    box.left = px;
    box.right = px + 1;
    box.top = py;
    box.bottom = py + 1;
    box.front = 0;
    box.back = 1;
    if (SUCCEEDED(ID3D11Device_CreateTexture2D(d3d8_GetD3D11Device(), &td, NULL, &staging))) {
        ID3D11DeviceContext_CopySubresourceRegion(ctx, (ID3D11Resource *)staging, 0, 0, 0, 0,
                                                  (ID3D11Resource *)back, 0, &box);
        if (SUCCEEDED(ID3D11DeviceContext_Map(ctx, (ID3D11Resource *)staging, 0, D3D11_MAP_READ, 0, &map))) {
            memcpy(&now, map.pData, 4);
            ID3D11DeviceContext_Unmap(ctx, (ID3D11Resource *)staging, 0);
        }
        ID3D11Texture2D_Release(staging);
    }
    ID3D11Texture2D_Release(back);
    if (now != last) {
        const uint32_t *rs = s_rs_sent;
        fprintf(stderr, "[PICK] draw %u (%s) from 0x%08X: %08X -> %08X; texture 0x%08X, FVF 0x%X%s, "
                "LIGHTING %u, ALPHABLEND %u SRC %X DEST %X, CULL %X\n", draws, what, guest32(g_esp), last, now,
                s_stage[0] ? s_stage[0]->va : 0, s_fvf, s_vprog ? " (vertex program)" : "",
                rs[102], rs[59], rs[62], rs[63], rs[147]);
        last = now;
    }
}

static void bridge_dump(void)
{
    static const char *prefix = (const char *)-1;
    static unsigned every, n;
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

            snprintf(path, sizeof path, "%s%05u.bmp", prefix, n - 1);   /* the frame's number */
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

/* ROBOTECH_WATCH=<address>[,<address>...]: the 32-bit word of the game's
 * memory at each address (hexadecimal), logged on the frames it changes, for
 * finding what a press or a screen sets. */
static void bridge_watch(void)
{
    static int count = -1;
    static uint32_t addr[16], last[16];
    int i;

    if (count < 0) {
        const char *e = getenv("ROBOTECH_WATCH");
        count = 0;
        while (e && *e && count < 16) {
            char *end;
            uint32_t a = strtoul(e, &end, 16);
            if (end == e)
                break;
            addr[count] = a;
            last[count] = guest32(a);
            fprintf(stderr, "[WATCH] frame %u 0x%08X = 0x%08X\n", s_frame, a, last[count]);
            count++;
            e = *end == ',' ? end + 1 : end;
        }
    }
    for (i = 0; i < count; i++) {
        uint32_t v = guest32(addr[i]);
        if (v != last[i]) {
            fprintf(stderr, "[WATCH] frame %u 0x%08X = 0x%08X\n", s_frame, addr[i], v);
            last[i] = v;
        }
    }
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
    s_frame++;
    {
        /* ROBOTECH_EXIT_FRAME=<n>: leave once frame n is presented, so a run
         * compared with another ends on the same frame (tools/scenario.py) */
        static long exit_at = -2;
        if (exit_at == -2) {
            const char *e = getenv("ROBOTECH_EXIT_FRAME");
            exit_at = e ? atol(e) : -1;
        }
        if (exit_at > 0 && (long)s_frame >= exit_at) {
            fprintf(stderr, "[D3D11] frame %u presented: leaving (ROBOTECH_EXIT_FRAME)\n", s_frame);
            fflush(stderr);
            exit(0);        /* what is kept at exit (the WAV, the sound's counts) is closed */
        }
    }
    bridge_watch();
    now = GetTickCount();
    if (!last)
        last = now;
    if (now - last >= 2000) {
        fprintf(stderr, "[D3D11] %.1f fps, %u clears, %u draws + %u pushed (%u with a pixel shader), "
                "%u by vertex program (%u could not run), %u left out, %d textures\n",
                s_presents * 1000.0 / (now - last), s_clears, s_draws, s_push_draws, s_ps_draws,
                s_vp_draws, s_vp_failed, s_skipped_vp, s_tex_count);
        if (getenv("ROBOTECH_D3D11_TRACE")) {
            fprintf(stderr, "[D3D11] transforms: view %u proj %u world %u world1-3 %u/%u/%u tex0 %u\n",
                    s_xforms[0], s_xforms[1], s_xforms[6], s_xforms[7], s_xforms[8], s_xforms[9], s_xforms[2]);
            memset(s_xforms, 0, sizeof s_xforms);
        }
        s_presents = s_clears = s_draws = s_push_draws = s_ps_draws = s_skipped_vp = 0;
        s_vp_draws = s_vp_failed = 0;
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

/* The texture matrices as D3D applies them. A stage whose
 * TEXTURETRANSFORMFLAGS is DISABLE takes its coordinates as they are, and the
 * layer applies the matrix whatever the flag says. And D3D completes a
 * coordinate set of fewer than four elements with a 1 right after its own (a
 * 2D set is (u, v, 1, 0): a 2D texture scrolls by the matrix's third row),
 * where the layer's shader gets Direct3D 11's (u, v, 0, 1); so the row the 1
 * meets moves to the fourth, as Wine does. The menu's background emblem
 * scrolls a texture so; it stood still. */
static int bridge_make_cube(BridgeTexture *t);

static void bridge_texture_transforms(const uint32_t ts[BRIDGE_STAGES][XB_TSS_MAX])
{
    /* the elements of a coordinate set by the FVF's size field, D3DFVF_TEXTUREFORMATn */
    static const int elements[4] = { 2, 3, 4, 1 };
    int s, k;

    for (s = 0; s < BRIDGE_STAGES; s++) {
        float m[16];
        uint32_t set = s_tci[s] & 0xFFFFu;
        int n = 3;          /* a generated set (TCI_CAMERASPACE*, SPHEREMAP) is (x, y, z, 1) as in the layer */

        for (k = 0; k < 16; k++)
            m[k] = k % 5 == 0 ? 1.0f : 0.0f;
        if (ts[s][XB_TSS_TEXTURETRANSFORMFLAGS] && s_tex_matrix_set[s]) {
            uint32_t flags = ts[s][XB_TSS_TEXTURETRANSFORMFLAGS], count = flags & 0xFFu;

            memcpy(m, s_tex_matrix[s], sizeof m);
            if (!(s_tci[s] & 0xFFFF0000u))
                n = set < 8 ? elements[(s_fvf >> (16 + 2 * set)) & 3u] : 2;
            if (n < 3)
                memcpy(m + 12, m + 4 * n, 4 * sizeof m[0]);
            if ((flags & XB_TTFF_PROJECTED) && count >= 2 && count <= 4 && s_stage[s]
                    && bridge_make_cube(s_stage[s])) {
                /* (s, t, q) to (2s - q, q - 2t, q), q the last of the count: the
                 * direction that finds (s/q, t/q) on the cube's +Z face */
                float p[16];
                uint32_t q = count - 1;

                memcpy(p, m, sizeof p);
                for (k = 0; k < 4; k++) {
                    m[4 * k + 0] = 2.0f * p[4 * k + 0] - p[4 * k + q];
                    m[4 * k + 1] = p[4 * k + q] - 2.0f * p[4 * k + 1];
                    m[4 * k + 2] = p[4 * k + q];
                    m[4 * k + 3] = 0.0f;
                }
            }
        }
        if ((s_tci[s] & 0xFFFF0000u) >= 0x10000u && (s_tci[s] & 0xFFFF0000u) <= 0x30000u)
            for (k = 8; k < 12; k++)
                m[k] = -m[k];   /* the camera space's z, turned for the fog (d3d11_SetTransform), turned back */
        if (s_tex_sent_valid[s] && !memcmp(m, s_tex_sent[s], sizeof m))
            continue;
        s_dev->lpVtbl->SetTransform(s_dev, (D3DTRANSFORMSTATETYPE)(D3DTS_TEXTURE0 + s), (const D3DMATRIX *)m);
        memcpy(s_tex_sent[s], m, sizeof m);
        s_tex_sent_valid[s] = 1;
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
        /* the coordinate set a stage reads (low 16 bits), or how it is made
         * from the vertex (TCI_* in the high ones), the same on both sides */
        if (!s_states_sent || ts[s][XB_TSS_TEXCOORDINDEX] != s_tci[s]) {
            s_tci[s] = ts[s][XB_TSS_TEXCOORDINDEX];
            s_dev->lpVtbl->SetTextureStageState(s_dev, (DWORD)s, D3DTSS_TEXCOORDINDEX, s_tci[s]);
        }
    }
    bridge_texture_transforms(ts);
    memcpy(s_rs_sent, rs, sizeof rs);
    memcpy(s_ts_sent, ts, sizeof ts);
    s_states_sent = 1;
}

/* D3DDevice_SetTextureState_TexCoordIndex(Stage, Value). */
void d3d11_SetTexCoordIndex(void)
{
    /* Nothing more: the XDK keeps the value in the texture-stage array as
     * well (D3D__TextureState[Stage][28]), where the game also writes it
     * itself, without this call (the training's shadow, a camera-space
     * position); bridge_sync_states reads it there before each draw. */
}

/* ── Transforms, viewport, material, lights ────────────────── */

/* ROBOTECH_D3D11_XFORM_FRAME=<n>: every transform and draw of frame n, the
 * matrices whole, for checking what the game's models are drawn with. */
static int xform_frame(void)
{
    static long want = -2;

    if (want == -2) {
        const char *e = getenv("ROBOTECH_D3D11_XFORM_FRAME");
        want = e ? atol(e) : -1;
    }
    return want >= 0 && s_frame == (unsigned)want;
}

/* A render state the game set as a float (the fog's start, end and density). */
static float rs_float(int state)
{
    float f;
    memcpy(&f, &s_rs_sent[state], sizeof f);
    return f;
}

/* D3DDevice_SetTransform(State, pMatrix): the XDK numbers the transforms
 * VIEW 0, PROJECTION 1, TEXTURE0-3 2-5, WORLD 6, WORLD1-3 7-9. */
void d3d11_SetTransform(void)
{
    uint32_t state = arg(0), m = arg(1);
    D3DTRANSFORMSTATETYPE pc;

    if (!s_dev || !m || state > 9)
        return;
    s_xforms[state]++;
    if (xform_frame()) {
        const float *f = (const float *)guest_ptr(m);
        int k;

        fprintf(stderr, "[XFORM] state %u from 0x%08X:", state, guest32(g_esp));
        for (k = 0; k < 16; k++)
            fprintf(stderr, "%s%.3f", k % 4 ? " " : " | ", f[k]);
        fprintf(stderr, "\n");
    }
    if (state >= 2 && state <= 5) {
        /* the layer gets it before each draw, made to D3D's rules (bridge_texture_transforms) */
        memcpy(s_tex_matrix[state - 2], guest_ptr(m), sizeof s_tex_matrix[0]);
        s_tex_matrix_set[state - 2] = 1;
        return;
    }
    if (state == 6)
        memcpy(s_world, guest_ptr(m), sizeof s_world);
    if (state <= 1) {
        /* The layer's table fog takes -z of the camera-space position for the
         * depth, as if the camera looked down -z; D3D's cameras look down +z,
         * so no table fog ever showed (Ambush Hills' far hills, 2000 to 3400).
         * Its camera space gets z turned (the view's third column), the
         * projection takes it back (its third row), the position on screen is
         * the same; what else reads that space, the coordinates generated in
         * it, is turned back by their texture matrix (bridge_texture_transforms).
         * The lighting works in world space, and the eye's position does not
         * change. */
        float f[16];

        memcpy(f, guest_ptr(m), sizeof f);
        if (state == 0) {
            f[2] = -f[2];
            f[6] = -f[6];
            f[10] = -f[10];
            f[14] = -f[14];
        } else {
            f[8] = -f[8];
            f[9] = -f[9];
            f[10] = -f[10];
            f[11] = -f[11];
        }
        s_dev->lpVtbl->SetTransform(s_dev, state == 0 ? D3DTS_VIEW : D3DTS_PROJECTION, (const D3DMATRIX *)f);
        return;
    }
    pc = (D3DTRANSFORMSTATETYPE)(D3DTS_WORLD + (state - 6));
    s_dev->lpVtbl->SetTransform(s_dev, pc, (const D3DMATRIX *)guest_ptr(m));
}

/* D3DDevice_SetViewport(pViewport): the same six fields on both sides. */
void d3d11_SetViewport(void)
{
    uint32_t vp = arg(0);

    if (s_dev && vp) {
        memcpy(&s_viewport, guest_ptr(vp), sizeof s_viewport);
        s_dev->lpVtbl->SetViewport(s_dev, &s_viewport);
    }
}

/* D3DDevice_SetMaterial(pMaterial): 17 floats on both sides. */
void d3d11_SetMaterial(void)
{
    uint32_t m = arg(0);
    int k;

    if (!s_dev || !m)
        return;
    if (xform_frame()) {
        const float *f = (const float *)guest_ptr(m);
        fprintf(stderr, "[XFORM] material from 0x%08X: diffuse ambient specular emissive", guest32(g_esp));
        for (k = 0; k < 17; k++)
            fprintf(stderr, "%s%.3f", k % 4 ? " " : " | ", f[k]);
        fprintf(stderr, "\n");
    }
    s_dev->lpVtbl->SetMaterial(s_dev, (const D3DMATERIAL8 *)guest_ptr(m));
}

/* D3DDevice_SetLight(Index, pLight): the same layout and light types. */
void d3d11_SetLight(void)
{
    uint32_t i = arg(0), l = arg(1);
    int k;

    if (!s_dev || !l)
        return;
    if (xform_frame()) {
        const float *f = (const float *)guest_ptr(l);
        fprintf(stderr, "[XFORM] light %u from 0x%08X: type %u, diffuse specular ambient position direction"
                " range falloff attenuation theta phi", i, guest32(g_esp), guest32(l));
        for (k = 1; k < 26; k++)
            fprintf(stderr, " %.3f", f[k]);
        fprintf(stderr, "\n");
    }
    s_dev->lpVtbl->SetLight(s_dev, i, (const D3DLIGHT8 *)guest_ptr(l));
}

/* D3DDevice_LightEnable(Index, bEnable). */
void d3d11_LightEnable(void)
{
    if (!s_dev)
        return;
    if (xform_frame())
        fprintf(stderr, "[XFORM] light %u enabled %u from 0x%08X\n", arg(0), arg(1), guest32(g_esp));
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
    } else {
        if (t->host)
            t->host->lpVtbl->Release(t->host);
        if (t->cube)
            t->cube->lpVtbl->Release(t->cube);
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

    if (!t->host || !src || t->target)
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

/* Gives the layer what a stage samples: the host texture of the guest one
 * set there, or its cube when it has one. Again after either is remade.
 * The layer's SetTexture changes the stage's COLOROP as D3D does not: no
 * texture turns it to DISABLE, a texture on a DISABLE stage to MODULATE. So
 * the stage gets the game's COLOROP again, the one last sent: the training's
 * shadow is drawn with no texture and SELECTARG2 of TFACTOR, black, and the
 * layer drew it with the stage off, in the vertices' white. And a stage
 * with no texture samples opaque white, as on the console (D3D's no texture),
 * where the layer's would sample nothing: the letterbox of the scenes, black
 * quads with MODULATE of TEXTURE and DIFFUSE and no texture, went
 * transparent. */
static void bridge_bind(uint32_t stage)
{
    static IDirect3DTexture8 *white;
    BridgeTexture *t = s_stage[stage];
    IDirect3DBaseTexture8 *host = NULL;

    if (!white && SUCCEEDED(s_dev->lpVtbl->CreateTexture(s_dev, 1, 1, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED,
                                                         &white))) {
        D3DLOCKED_RECT lr;

        if (SUCCEEDED(white->lpVtbl->LockRect(white, 0, &lr, NULL, 0))) {
            *(uint32_t *)lr.pBits = 0xFFFFFFFFu;
            white->lpVtbl->UnlockRect(white, 0);
        }
    }
    if (t)
        host = t->cube ? (IDirect3DBaseTexture8 *)t->cube : (IDirect3DBaseTexture8 *)t->host;
    s_dev->lpVtbl->SetTexture(s_dev, stage, host ? host : (IDirect3DBaseTexture8 *)white);
    if (s_states_sent)
        s_dev->lpVtbl->SetTextureStageState(s_dev, stage, D3DTSS_COLOROP, xb_top(s_ts_sent[stage][12]));
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
    bridge_bind(stage);
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

/* ── Render targets ────────────────────────────────────────── */

/* The stages that sample t, given its host texture again after it was remade. */
static void bridge_rebind(const BridgeTexture *t)
{
    uint32_t s;

    for (s = 0; s < BRIDGE_STAGES; s++)
        if (s_stage[s] == t)
            bridge_bind(s);
}

/* A texture the game draws to becomes a render target on the host, its
 * first level only; what the game samples from it after is what was drawn
 * there, never the guest's bytes. */
static int bridge_make_target(BridgeTexture *t)
{
    HRESULT hr;

    if (t->target)
        return t->host != NULL;
    if (t->host)
        t->host->lpVtbl->Release(t->host);
    t->host = NULL;
    t->target = 1;
    t->levels = 1;
    t->dirty = 0;
    hr = s_dev->lpVtbl->CreateTexture(s_dev, t->width, t->height, 1, D3DUSAGE_RENDERTARGET, t->format,
                                      D3DPOOL_DEFAULT, &t->host);
    fprintf(stderr, "[D3D11] texture 0x%08X: %ux%u format 0x%02X, a render target: %s\n",
            t->va, t->width, t->height, (unsigned)t->format, SUCCEEDED(hr) ? "created" : "failed");
    if (FAILED(hr))
        t->host = NULL;
    bridge_rebind(t);
    return t->host != NULL;
}

/* A depth buffer the size of a texture drawn to. The game draws to one with
 * none (the training's shadow, the fighter seen from the light), and the layer would take the back
 * buffer's, of another size; so the texture gets its own, cleared each time
 * it is set, which nothing drawn in one pass can tell from none. */
static IDirect3DSurface8 *bridge_target_depth(UINT w, UINT h)
{
    if (s_target_depth && (s_target_depth_w != w || s_target_depth_h != h)) {
        s_target_depth->lpVtbl->Release(s_target_depth);
        s_target_depth = NULL;
    }
    if (!s_target_depth
            && FAILED(s_dev->lpVtbl->CreateDepthStencilSurface(s_dev, w, h, D3DFMT_D24S8,
                                                               D3DMULTISAMPLE_NONE, &s_target_depth)))
        s_target_depth = NULL;
    s_target_depth_w = w;
    s_target_depth_h = h;
    return s_target_depth;
}

/* A texture the game draws to and then samples projectively: its
 * TEXTURETRANSFORMFLAGS have PROJECTED, the coordinates divided by their last
 * before sampling (the training's shadow, cast by its own texture matrix
 * from a camera-space position). The layer's shader samples a 2D texture
 * with the coordinates as they come, divided by nothing; a cube texture,
 * though, is sampled by a direction, the same whatever its length. So the
 * texture goes to the +Z face of a cube of its size, and a stage
 * sampling it gets the coordinates (2s - q, q - 2t, q) (bridge_texture_transforms):
 * on that face, at (s/q, t/q). Where s/q or t/q is outside 0..1 the
 * direction leaves the face for one of the other five, all cleared to
 * nothing as the border the game keeps around what it draws (a viewport a
 * texel inside the texture) would have given.
 *
 * The game still draws to the 2D texture: drawn to the face itself, nothing
 * arrived there (the layer binds a depth buffer of its own, a plain 2D one,
 * with every target). What was drawn goes to the face by a copy, on the
 * GPU, each time the game leaves the texture (bridge_follow_target), and
 * once as the cube is made. The
 * layer's textures keep their ID3D11Texture2D first after the interface and
 * its count (d3d8_internal.h, the same for a cube). */
typedef struct {
    void *iface;
    LONG ref_count;
    ID3D11Texture2D *d3d11_texture;
} LayerTexture;

static void bridge_copy_to_cube(const BridgeTexture *t)
{
    ID3D11Texture2D *flat = ((const LayerTexture *)t->host)->d3d11_texture;
    ID3D11Texture2D *cube = ((const LayerTexture *)t->cube)->d3d11_texture;

    /* the face's subresource is its number, the cube having one level */
    ID3D11DeviceContext_CopySubresourceRegion(d3d8_GetD3D11Context(), (ID3D11Resource *)cube,
                                              D3DCUBEMAP_FACE_POSITIVE_Z, 0, 0, 0,
                                              (ID3D11Resource *)flat, 0, NULL);
}

static int bridge_make_cube(BridgeTexture *t)
{
    static const float nothing[4] = { 0 };
    D3D11_TEXTURE2D_DESC td;
    D3D11_RENDER_TARGET_VIEW_DESC rd;
    ID3D11Texture2D *cube;
    HRESULT hr;
    int f;

    if (t->cube)
        return 1;
    if (!t->target || !t->host || t->width != t->height)
        return 0;
    hr = s_dev->lpVtbl->CreateCubeTexture(s_dev, t->width, 1, D3DUSAGE_RENDERTARGET, t->format,
                                          D3DPOOL_DEFAULT, &t->cube);
    fprintf(stderr, "[D3D11] texture 0x%08X: sampled projectively, copied to a cube of %u: %s\n",
            t->va, t->width, SUCCEEDED(hr) ? "created" : "failed");
    if (FAILED(hr)) {
        t->cube = NULL;
        return 0;
    }
    cube = ((LayerTexture *)t->cube)->d3d11_texture;
    ID3D11Texture2D_GetDesc(cube, &td);
    memset(&rd, 0, sizeof rd);
    rd.Format = td.Format;
    rd.ViewDimension = D3D11_RTV_DIMENSION_TEXTURE2DARRAY;
    rd.Texture2DArray.ArraySize = 1;
    for (f = 0; f < 6; f++) {
        ID3D11RenderTargetView *view = NULL;

        rd.Texture2DArray.FirstArraySlice = (UINT)f;
        if (SUCCEEDED(ID3D11Device_CreateRenderTargetView(d3d8_GetD3D11Device(), (ID3D11Resource *)cube,
                                                          &rd, &view))) {
            ID3D11DeviceContext_ClearRenderTargetView(d3d8_GetD3D11Context(), view, nothing);
            ID3D11RenderTargetView_Release(view);
        }
    }
    bridge_copy_to_cube(t);
    bridge_rebind(t);
    return 1;
}

/* The game sets where it draws with D3DDevice_SetRenderTarget, which runs as
 * the bookkeeping it is and keeps the surface in the device; before each
 * clear and draw the bridge looks there, and draws where the game does: a
 * level of a texture, or the back buffer. With the back buffer only, the
 * training's shadow pass cleared the scene drawn so far to black and drew
 * the fighter white over it. */
static void bridge_follow_target(void)
{
    static int shown;
    uint32_t dev = guest32(XB_DEVICE_PTR_VA);
    uint32_t rt, zs, parent;
    IDirect3DSurface8 *surface = NULL;
    BridgeTexture *t = NULL;

    if (!dev)
        return;
    rt = guest32(dev + XB_DEVICE_RENDER_TARGET);
    zs = guest32(dev + XB_DEVICE_DEPTH_STENCIL);
    if (rt == s_guest_rt && zs == s_guest_zs)
        return;
    s_guest_rt = rt;
    s_guest_zs = zs;
    if (s_target && s_target->cube)
        bridge_copy_to_cube(s_target);    /* what the pass drew, for the projective sampling */
    parent = rt ? guest32(rt + XB_SURFACE_PARENT) : 0;
    if (parent)
        t = bridge_texture(parent);
    if (t && bridge_make_target(t) && SUCCEEDED(t->host->lpVtbl->GetSurfaceLevel(t->host, 0, &surface))) {
        IDirect3DSurface8 *depth = bridge_target_depth(t->width, t->height);

        s_dev->lpVtbl->SetRenderTarget(s_dev, surface, depth);
        surface->lpVtbl->Release(surface);
        if (depth)
            s_dev->lpVtbl->Clear(s_dev, 0, NULL, D3DCLEAR_ZBUFFER, 0, 1.0f, 0);
        s_target = t;
    } else {
        s_dev->lpVtbl->SetRenderTarget(s_dev, NULL, NULL);      /* the back buffer and its depth */
        s_target = NULL;
    }
    if (shown < 4) {
        shown++;
        fprintf(stderr, "[D3D11] drawing to surface 0x%08X (depth 0x%08X): %s 0x%08X\n", rt, zs,
                s_target ? "a level of texture" : parent ? "not routed, back buffer for texture" :
                "the back buffer", parent);
    }
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
        /* a program: loaded at 0 and run from there (vertex programs below) */
        s_vprog = vprog_find(handle);
        vprog_load(s_vprog, 0);
        nv2a_vsh_set_start_slot(0);
        s_fvf = 0;
        return;
    }
    s_vprog = NULL;
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
/* The layer lights with the normals times the inverse of the world matrix,
 * where D3D takes the inverse's transpose (it uploads the transpose of the
 * transpose, for a shader that reads matrices by columns): on a rotated
 * object the normal turns the other way, and the training's fences were lit
 * on the side away from the light. So a lit draw's normals go to it times
 * W^-T W (the world's 3 x 3, vectors in rows), which its W^-1 turns into the
 * normals D3D lights with. Returns 0 when that is the identity. */
static int normal_fix(float a[9])
{
    const float *w = s_world;
    const float m[9] = { w[0], w[1], w[2], w[4], w[5], w[6], w[8], w[9], w[10] };
    float inv[9], det;
    int i, j, k, same = 1;

    det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6])
        + m[2] * (m[3] * m[7] - m[4] * m[6]);
    if (det == 0.0f)
        return 0;
    inv[0] = (m[4] * m[8] - m[5] * m[7]) / det;
    inv[1] = (m[2] * m[7] - m[1] * m[8]) / det;
    inv[2] = (m[1] * m[5] - m[2] * m[4]) / det;
    inv[3] = (m[5] * m[6] - m[3] * m[8]) / det;
    inv[4] = (m[0] * m[8] - m[2] * m[6]) / det;
    inv[5] = (m[2] * m[3] - m[0] * m[5]) / det;
    inv[6] = (m[3] * m[7] - m[4] * m[6]) / det;
    inv[7] = (m[1] * m[6] - m[0] * m[7]) / det;
    inv[8] = (m[0] * m[4] - m[1] * m[3]) / det;
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++) {
            float s = 0.0f;
            for (k = 0; k < 3; k++)
                s += inv[k * 3 + i] * m[k * 3 + j];
            a[i * 3 + j] = s;
            if (fabsf(s - (i == j ? 1.0f : 0.0f)) > 1e-5f)
                same = 0;
        }
    return !same;
}

static const void *bridge_vertices(const uint8_t *src, UINT vertices, UINT stride)
{
    static const UINT pos_bytes[8] = { 0, 12, 16, 16, 20, 24, 28, 0 };
    UINT floats[8], off, k, v;
    size_t bytes = (size_t)vertices * stride;
    float fix[9];
    int any = 0, normals;

    if (!s_fvf)
        return src;
    off = fvf_texcoords(s_fvf, floats);
    for (k = 0; k < BRIDGE_STAGES; k++)
        if (s_tci[k] < 8 && floats[s_tci[k]] && s_stage[k] && s_stage[k]->pitch)
            any = 1;
    normals = s_rs_sent[102] && (s_fvf & D3DFVF_NORMAL) && (s_fvf & D3DFVF_POSITION_MASK) != D3DFVF_XYZRHW
              && normal_fix(fix);
    if (!any && !normals)
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
    if (normals)
        for (v = 0; v < vertices; v++) {
            float *n = (float *)(s_scratch + (size_t)v * stride + pos_bytes[(s_fvf >> 1) & 7u]);
            float x = n[0], y = n[1], z = n[2];

            n[0] = x * fix[0] + y * fix[3] + z * fix[6];
            n[1] = x * fix[1] + y * fix[4] + z * fix[7];
            n[2] = x * fix[2] + y * fix[5] + z * fix[8];
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

    if (!s_fvf && !s_vprog) {
        s_skipped_vp++;
        return 0;
    }
    if (s_pixel_shader)
        s_ps_draws++;
    bridge_follow_target();
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
    if (s_vprog) {
        if (vprog_transform(0, vertices, 0, data, stride))
            vprog_draw(pt, count, vertices, NULL);
        else
            s_vp_failed++;
        return;
    }
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count,
                                   bridge_vertices((const uint8_t *)guest_ptr(data), vertices, stride),
                                   stride);
    bridge_pick("vertices UP");
    s_draws++;
}

/* D3DDevice_SetPixelShader(Handle): not routed yet, only noted, so the
 * bridge's log says how many draws are made with one. */
void d3d11_SetPixelShader(void)
{
    s_pixel_shader = arg(0);
}

/* ── Vertex programs ───────────────────────────────────────── */

/* The game's models are drawn with vertex programs, not the fixed pipeline:
 * measured on the menu's Valkyrie, a program per pass (the cel-shaded body
 * and its outline) reads position, normal and texture coordinates, and takes
 * each part's world-view-projection matrix in c0-c3 (SetVertexShaderConstant4
 * between parts: no SetTransform at all). The layer's own translator lays
 * the inputs out in a fixed order and writes oPos as clip space, while this
 * game's declarations put the normal in v1 and its programs end, as every
 * XDK program does, in the screen-space epilogue (oPos * c-38, times 1/w,
 * plus c-37). So the bridge runs the programs itself, on the CPU, with
 * xboxrecomp's NV2A interpreter -- the one that draws the Valkyrie right
 * through the pushbuffer executor -- and hands the layer the vertices
 * transformed: XYZRHW, the two colours, four texture coordinate sets.
 *
 * c-38 and c-37 (c[58], c[59]) are the viewport scale and offset, which the
 * XDK's own code loads, never the game: they are set here to 1 and 0, so the
 * epilogue leaves x, y, z divided by w, and the viewport maps them. Vertices
 * behind the eye are not clipped (pre-transformed vertices never are); the
 * menu has none. ROBOTECH_D3D11_VSH_DUMP=<prefix> writes each program as
 * created, <prefix><handle>.bin. */

#define VPROG_MAX       32
#define VPROG_ATTRS     16
/* Two floats a texture coordinate set: the layer reads the FVF's size field
 * as the count of floats (0 being 2), not as the XDK and the PC encode it, so
 * two is the one size both read alike. Cube-map and projective coordinates
 * (z, w) are not carried yet. */
#define VPROG_FVF       (D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_SPECULAR | D3DFVF_TEX4)

typedef struct {
    uint8_t reg, type, stream, offset;
} VprogAttr;

typedef struct Vprog {
    uint32_t handle;
    VprogAttr attr[VPROG_ATTRS];
    int nattr;
    uint32_t words[NV2A_VSH_SLOTS * 4];
    int insns;
} Vprog;

typedef struct {
    float x, y, z, rhw;
    DWORD diffuse, specular;
    float t[4][2];
} VprogVertex;

static Vprog s_vprogs[VPROG_MAX];
static int s_nvprogs;
static uint32_t s_vsh_args[3];
static struct {
    uint32_t vb, stride, offset;
} s_vsi[16];                            /* SetVertexShaderInput's streams */
static uint32_t s_vsi_count;
static VprogVertex *s_vout;
static UINT s_vout_cap;

static struct Vprog *vprog_find(uint32_t handle)
{
    int i;

    for (i = 0; i < s_nvprogs; i++)
        if (s_vprogs[i].handle == handle)
            return &s_vprogs[i];
    return NULL;
}

/* The bytes an attribute of a D3DVSDT_* type takes in its stream. */
static UINT vsdt_size(uint32_t type)
{
    UINT n = (type >> 4) & 0xFu;

    switch (type & 0xFu) {
    case 0x2: return type == 0x72 ? 12 : (type == 0x02 ? 0 : 4 * n);   /* FLOATn, FLOAT2H, NONE */
    case 0x0: return 4;                                                 /* D3DCOLOR */
    case 0x5:                                                           /* SHORTn */
    case 0x1: return 2 * n;                                             /* NORMSHORTn */
    case 0x6: return 4;                                                 /* NORMPACKED3 */
    case 0x4: return n;                                                 /* PBYTEn */
    }
    return 0;
}

/* D3DDevice_CreateVertexShader(pDeclaration, pFunction, pHandle, Usage):
 * the declaration becomes a list of (register, type, stream, offset) and
 * the program's instructions are kept for LoadVertexShader. pFunction is the
 * XDK's compiled form: a header, instructions << 16 | 0x2078, then four
 * DWORDs an instruction. */
void d3d11_CreateVertexShaderArgs(void)
{
    s_vsh_args[0] = arg(0);
    s_vsh_args[1] = arg(1);
    s_vsh_args[2] = arg(2);
}

void d3d11_CreateVertexShaderDone(void)
{
    uint32_t handle = s_vsh_args[2] ? guest32(s_vsh_args[2]) : 0, decl = s_vsh_args[0];
    uint32_t func = s_vsh_args[1], header, stream = 0, offset = 0, i;
    const char *dump = getenv("ROBOTECH_D3D11_VSH_DUMP");
    Vprog *p;

    if (!s_dev || !handle || !func)
        return;
    p = vprog_find(handle);
    if (!p) {
        if (s_nvprogs == VPROG_MAX)
            return;
        p = &s_vprogs[s_nvprogs++];
    }
    memset(p, 0, sizeof *p);
    p->handle = handle;
    header = guest32(func);
    p->insns = (int)(header >> 16);
    if (p->insns > NV2A_VSH_SLOTS)
        p->insns = NV2A_VSH_SLOTS;
    for (i = 0; i < (uint32_t)p->insns * 4; i++)
        p->words[i] = guest32(func + 4 + 4 * i);
    for (i = 0; decl && i < 64; i++) {
        uint32_t t = guest32(decl + 4 * i);

        if (t == 0xFFFFFFFFu)
            break;
        switch (t >> 29) {
        case 1:                                         /* STREAM(n) */
            stream = t & 0xFu;
            offset = 0;
            break;
        case 2:                                         /* REG(reg, type), SKIP, SKIPBYTES */
            if (t & 0x10000000u)
                offset += ((t >> 16) & 0xFu) * ((t & 0x08000000u) ? 1u : 4u);
            else if (p->nattr < VPROG_ATTRS) {
                VprogAttr *a = &p->attr[p->nattr++];

                a->reg = (uint8_t)(t & 0x1Fu);
                a->type = (uint8_t)((t >> 16) & 0xFFu);
                a->stream = (uint8_t)stream;
                a->offset = (uint8_t)offset;
                offset += vsdt_size(a->type);
            }
            break;
        case 4:                                         /* CONST(address, count): its data follows */
            i += ((t >> 25) & 0xFu) * 4;
            break;
        case 5:                                         /* extension: its data follows */
            i += (t >> 24) & 0x1Fu;
            break;
        }
    }
    fprintf(stderr, "[D3D11] vertex program 0x%08X: %d instructions, %d inputs\n",
            handle, p->insns, p->nattr);
    if (dump) {
        char path[512];
        FILE *f;

        snprintf(path, sizeof path, "%s%08X.bin", dump, handle);
        f = fopen(path, "wb");
        if (f) {
            fwrite(guest_ptr(func), 4, 1 + (size_t)p->insns * 4, f);
            fclose(f);
        }
    }
}

static void vprog_load(struct Vprog *p, uint32_t at)
{
    int i;

    for (i = 0; p && i < p->insns && at + (uint32_t)i < NV2A_VSH_SLOTS; i++)
        nv2a_vsh_set_instruction(at + (uint32_t)i, &p->words[4 * i]);
}

/* D3DDevice_LoadVertexShader(Handle, Address): the program into program
 * memory at Address. */
void d3d11_LoadVertexShader(void)
{
    vprog_load(vprog_find(arg(0)), arg(1));
}

/* D3DDevice_SelectVertexShader(Handle, Address): run from Address, reading
 * the inputs Handle's declaration names (a null Handle keeps the current). */
void d3d11_SelectVertexShader(void)
{
    if (!s_dev)
        return;
    if (arg(0))
        s_vprog = vprog_find(arg(0));
    nv2a_vsh_set_start_slot(arg(1));
}

/* D3DDevice_SetVertexShaderInput(Handle, StreamCount, pStreamInputs): the
 * streams a program reads, instead of SetStreamSource's, until it is called
 * with none. Each D3DSTREAM_INPUT is VertexBuffer, Stride, Offset. */
void d3d11_SetVertexShaderInput(void)
{
    uint32_t count = arg(1), in = arg(2), i;

    s_vsi_count = in && count <= 16 ? count : 0;
    for (i = 0; i < s_vsi_count; i++) {
        s_vsi[i].vb = guest32(in + 12 * i);
        s_vsi[i].stride = guest32(in + 12 * i + 4);
        s_vsi[i].offset = guest32(in + 12 * i + 8);
    }
    if (arg(0) & 1u)
        s_vprog = vprog_find(arg(0));
}

/* D3DDevice_SetVertexShaderConstant1/4/NotInline, fastcall: ecx the
 * register already biased by 96 (c[0..191]), edx the data. */
void d3d11_SetVertexShaderConstant(int count)
{
    uint32_t reg = g_ecx, data = g_edx, n = count ? (uint32_t)count : arg(0) / 4, i;

    for (i = 0; i < n && reg + i < NV2A_VSH_CONSTANTS; i++)
        nv2a_vsh_set_constant(reg + i, (const float *)guest_ptr(data + 16 * i));
    if (xform_frame()) {
        fprintf(stderr, "[XFORM] constants c%u..c%u:", reg, reg + n - 1);
        for (i = 0; i < n * 4 && i < 16; i++)
            fprintf(stderr, " %.3f", ((const float *)guest_ptr(data))[i]);
        fprintf(stderr, "%s\n", n > 4 ? " ..." : "");
    }
}

/* Where vertex 0 of a program's stream is, and its stride: SetVertexShaderInput's
 * streams when set, else SetStreamSource's; for DrawVerticesUP stream 0 is the
 * game's own pointer. */
static const uint8_t *vprog_stream(uint32_t stream, uint32_t up_data, uint32_t up_stride, uint32_t *stride)
{
    uint32_t vb, extra = 0;

    if (up_data && stream == 0) {
        *stride = up_stride;
        return (const uint8_t *)guest_ptr(up_data);
    }
    if (s_vsi_count) {
        if (stream >= s_vsi_count)
            return NULL;
        vb = s_vsi[stream].vb;
        *stride = s_vsi[stream].stride;
        extra = s_vsi[stream].offset;
    } else {
        vb = s_streams[stream].va;
        *stride = s_streams[stream].stride;
    }
    if (!vb)
        return NULL;
    return (const uint8_t *)guest_ptr(phys_va(guest32(vb + XB_RES_DATA)) + extra);
}

/* One attribute, as the vertex unit expands it into four floats. */
static void vprog_fetch(uint32_t type, const uint8_t *src, float v[4])
{
    UINT n = (type >> 4) & 0xFu, k;

    v[0] = v[1] = v[2] = 0.0f;
    v[3] = 1.0f;
    switch (type & 0xFu) {
    case 0x2:
        if (type == 0x72) {                     /* FLOAT2H: x, y, w */
            memcpy(&v[0], src, 8);
            memcpy(&v[3], src + 8, 4);
        } else if (type != 0x02)
            memcpy(v, src, 4 * (n > 4 ? 4 : n));
        break;
    case 0x0: {                                 /* D3DCOLOR: ARGB to r, g, b, a */
        uint32_t c;

        memcpy(&c, src, 4);
        v[0] = ((c >> 16) & 0xFFu) / 255.0f;
        v[1] = ((c >> 8) & 0xFFu) / 255.0f;
        v[2] = (c & 0xFFu) / 255.0f;
        v[3] = (c >> 24) / 255.0f;
        break;
    }
    case 0x5:                                   /* SHORTn */
    case 0x1:                                   /* NORMSHORTn */
        for (k = 0; k < n && k < 4; k++) {
            int16_t x;

            memcpy(&x, src + 2 * k, 2);
            v[k] = (type & 0xFu) == 0x1 ? x / 32767.0f : (float)x;
        }
        break;
    case 0x6: {                                 /* NORMPACKED3: 11, 11, 10 bits */
        uint32_t c;

        memcpy(&c, src, 4);
        v[0] = (float)((int32_t)(c << 21) >> 21) / 1023.0f;
        v[1] = (float)((int32_t)(c << 10) >> 21) / 1023.0f;
        v[2] = (float)((int32_t)c >> 22) / 511.0f;
        break;
    }
    case 0x4:                                   /* PBYTEn */
        for (k = 0; k < n && k < 4; k++)
            v[k] = src[k] / 255.0f;
        break;
    }
}

static DWORD vprog_color(const float c[4])
{
    DWORD out = 0;
    int k;

    for (k = 0; k < 4; k++) {
        float x = c[k] < 0.0f ? 0.0f : c[k] > 1.0f ? 1.0f : c[k];
        static const int shift[4] = { 16, 8, 0, 24 };

        out |= (DWORD)(x * 255.0f + 0.5f) << shift[k];
    }
    return out;
}

/* Runs the selected program on vertices [first, first + count) of its
 * streams, offset by base, into s_vout[first..]. Returns 0 when it cannot
 * (no program, no stream data, nothing to run), and the draw is left out. */
static int vprog_transform(uint32_t first, uint32_t count, uint32_t base, uint32_t up_data, uint32_t up_stride)
{
    static const float scale[4] = { 1.0f, 1.0f, 1.0f, 1.0f }, zero[4] = { 0 };
    const uint8_t *src[16] = { 0 };
    uint32_t stride[16] = { 0 }, v;
    float in[NV2A_VSH_INPUTS][4];
    float target_x = 1.0f, target_y = 1.0f;
    Nv2aVshOutput out;
    int a;

    if (!s_vprog)
        return 0;
    if (s_target) {
        /* the layer places pre-transformed vertices by the back buffer's size whatever it draws to */
        target_x = (float)d3d8_GetBackbufferWidth() / (float)s_target->width;
        target_y = (float)d3d8_GetBackbufferHeight() / (float)s_target->height;
    }
    if (first + count > s_vout_cap) {
        UINT cap = first + count + 1024;
        VprogVertex *grown = (VprogVertex *)realloc(s_vout, cap * sizeof *grown);

        if (!grown)
            return 0;
        s_vout = grown;
        s_vout_cap = cap;
    }
    for (a = 0; a < s_vprog->nattr; a++) {
        uint32_t st = s_vprog->attr[a].stream;

        if (!src[st] && !(src[st] = vprog_stream(st, up_data, up_stride, &stride[st])))
            return 0;
    }
    nv2a_vsh_set_constant(58, scale);           /* c-38: the viewport scale */
    nv2a_vsh_set_constant(59, zero);            /* c-37: its offset */
    for (v = first; v < first + count; v++) {
        VprogVertex *o = &s_vout[v];
        float w;
        int k;

        for (k = 0; k < NV2A_VSH_INPUTS; k++) {
            in[k][0] = in[k][1] = in[k][2] = 0.0f;
            in[k][3] = 1.0f;
        }
        for (a = 0; a < s_vprog->nattr; a++) {
            const VprogAttr *at = &s_vprog->attr[a];

            if (at->reg < NV2A_VSH_INPUTS)
                vprog_fetch(at->type, src[at->stream] + (size_t)(v + base) * stride[at->stream] + at->offset,
                            in[at->reg]);
        }
        if (!nv2a_vsh_run((const float (*)[4])in, &out))
            return 0;
        w = out.pos[3];
        o->x = (s_viewport.X + (out.pos[0] + 1.0f) * 0.5f * s_viewport.Width) * target_x;
        o->y = (s_viewport.Y + (1.0f - out.pos[1]) * 0.5f * s_viewport.Height) * target_y;
        o->z = s_viewport.MinZ + out.pos[2] * (s_viewport.MaxZ - s_viewport.MinZ);
        o->rhw = w != 0.0f ? 1.0f / w : 1.0f;
        o->diffuse = vprog_color(out.d0);
        out.d1[3] = out.fog[0];                 /* a pre-transformed vertex's fog is specular alpha */
        o->specular = vprog_color(out.d1);
        for (k = 0; k < 4; k++) {
            o->t[k][0] = out.tex[k][0];
            o->t[k][1] = out.tex[k][1];
        }
    }
    return 1;
}

/* Draws s_vout[0..vertices) (indexed when idx is set) with the layer's FVF
 * set to the transformed layout for the draw, and the game's put back. */
static void vprog_draw(D3DPRIMITIVETYPE pt, UINT count, UINT vertices, const uint16_t *idx)
{
    uint32_t game_fvf = s_fvf;
    const void *v;

    s_fvf = VPROG_FVF;
    v = bridge_vertices((const uint8_t *)s_vout, vertices, sizeof(VprogVertex));
    s_dev->lpVtbl->SetVertexShader(s_dev, VPROG_FVF);
    if (idx)
        s_dev->lpVtbl->DrawIndexedPrimitiveUP(s_dev, pt, 0, vertices, count, idx, D3DFMT_INDEX16, v,
                                              sizeof(VprogVertex));
    else
        s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count, v, sizeof(VprogVertex));
    s_fvf = game_fvf;
    if (s_fvf)
        s_dev->lpVtbl->SetVertexShader(s_dev, s_fvf);
    bridge_pick(idx ? "indexed" : "vertices");
    s_vp_draws++;
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

    if (xform_frame())
        fprintf(stderr, "[XFORM] draw %s prim %u, %u vertices, FVF 0x%X, texture 0x%08X, from 0x%08X, to %s;"
                " COLOROP %u %u %u ALPHAOP %u %u %u, TFACTOR %08X, BLEND %u %X %X, COLORWRITE %X, Z %u %X %u,"
                " FOG %u %u %08X %g-%g %g range %u, LIGHTING %u SPECULAR %u\n",
                what, prim, vertices, s_fvf, va, guest32(g_esp), s_target ? "a texture" : "the back buffer",
                ts[12], ts[14], ts[15], ts[16], ts[18], ts[19], s_rs_sent[148], s_rs_sent[59], s_rs_sent[62],
                s_rs_sent[63], s_rs_sent[67], s_rs_sent[143], s_rs_sent[57], s_rs_sent[64],
                s_rs_sent[92], s_rs_sent[93], s_rs_sent[138], rs_float(94), rs_float(95), rs_float(96),
                s_rs_sent[97], s_rs_sent[102], s_rs_sent[103]);
    if (!v)
        return;                         /* a vertex program's draw: no FVF vertices to show */
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
    fprintf(stderr, "; COLOROP %u ARG1 %u ARG2 %u, ALPHAOP %u ARG1 %u ARG2 %u; TCI 0x%X, TEXTURETRANSFORMFLAGS 0x%X\n",
            ts[12], ts[14], ts[15], ts[16], ts[18], ts[19], ts[XB_TSS_TEXCOORDINDEX], ts[XB_TSS_TEXTURETRANSFORMFLAGS]);
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
    bridge_pick("pushed");
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
    if (s_dev && arg(0) < 16) {
        s_streams[arg(0)].va = arg(1);
        s_streams[arg(0)].stride = arg(2);
    }
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

    if (!s_dev || !bridge_primitive(xbtype, vertices, &pt, &count) || !count)
        return;
    if (s_vprog) {
        if (!bridge_before_draw())
            return;
        trace_draw("vertices (program)", xbtype, vertices, 0, NULL);
        if (vprog_transform(0, vertices, start, 0, 0))
            vprog_draw(pt, count, vertices, NULL);
        else
            s_vp_failed++;
        return;
    }
    if (!vb || !s_stream_stride || !bridge_before_draw())
        return;
    vb += (size_t)start * s_stream_stride;
    trace_draw("vertices", xbtype, vertices, s_stream_stride, vb);
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count, bridge_vertices(vb, vertices, s_stream_stride),
                                   s_stream_stride);
    bridge_pick("vertices");
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

    if (!s_dev || !idx || !bridge_primitive(xbtype, indices, &pt, &count) || !count)
        return;
    if (!s_vprog && (!vb || !s_stream_stride))
        return;
    if (!bridge_before_draw())
        return;
    for (i = 0; i < indices; i++) {
        if (idx[i] < lo) lo = idx[i];
        if (idx[i] > hi) hi = idx[i];
    }
    if (s_vprog) {
        trace_draw("indexed (program)", xbtype, hi + 1, 0, NULL);
        if (vprog_transform(lo, hi - lo + 1, s_base_vertex, 0, 0))
            vprog_draw(pt, count, hi + 1, idx);
        else
            s_vp_failed++;
        return;
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
    bridge_pick("indexed");
    s_draws++;
}
