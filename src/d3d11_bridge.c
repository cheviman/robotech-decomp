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

extern RECOMP_TLS uint32_t g_esp;
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

/* D3DDevice_Swap(Flags): present, and pump the window's messages. */
void d3d11_Swap(void)
{
    static DWORD last;
    DWORD now;

    if (!s_dev)
        return;
    bridge_dump();
    s_dev->lpVtbl->Swap(s_dev, arg(0));
    s_presents++;
    now = GetTickCount();
    if (!last)
        last = now;
    if (now - last >= 2000) {
        fprintf(stderr, "[D3D11] %.1f fps, %u clears, %u draws, %d textures\n",
                s_presents * 1000.0 / (now - last), s_clears, s_draws, s_tex_count);
        s_presents = s_clears = s_draws = 0;
        last = now;
    }
}

/* ── Textures ──────────────────────────────────────────────── */

/* Where the texels are, as the CPU sees them: Data is a physical address, and
 * physical memory shows through the contiguous window. */
static uint32_t texel_va(uint32_t data)
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
 * being a multiple of 64. */
static void bridge_upload(BridgeTexture *t)
{
    const uint8_t *src = (const uint8_t *)guest_ptr(texel_va(guest32(t->va + XB_RES_DATA)));
    UINT level;

    if (!t->host || !src)
        return;
    for (level = 0; level < t->levels; level++) {
        D3DLOCKED_RECT lr;
        UINT rows = t->height >> level ? t->height >> level : 1;
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
 * divided by the texture's size. Stage k reads set k (D3DTSS_TEXCOORDINDEX's
 * default). Returns the vertices to draw, the game's own when nothing needs
 * rewriting. */
static const void *bridge_vertices(const uint8_t *src, UINT vertices, UINT stride)
{
    UINT floats[8], off, k, v;
    size_t bytes = (size_t)vertices * stride;
    int any = 0;

    if (!s_fvf)
        return src;
    off = fvf_texcoords(s_fvf, floats);
    for (k = 0; k < BRIDGE_STAGES; k++)
        if (floats[k] && s_stage[k] && s_stage[k]->pitch)
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
        UINT set_off = off, j;

        for (j = 0; j < k; j++)
            set_off += floats[j] * 4;
        if (!floats[k] || !t || !t->pitch)
            continue;
        for (v = 0; v < vertices; v++) {
            float *uv = (float *)(s_scratch + (size_t)v * stride + set_off);
            uv[0] /= (float)t->width;
            if (floats[k] > 1)
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

/* Textures the game wrote since they were last uploaded go up before a draw
 * that samples them. */
static void bridge_flush_textures(void)
{
    int s;

    for (s = 0; s < BRIDGE_STAGES; s++)
        if (s_stage[s] && s_stage[s]->dirty)
            bridge_upload(s_stage[s]);
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
    bridge_flush_textures();
    s_dev->lpVtbl->DrawPrimitiveUP(s_dev, pt, count,
                                   bridge_vertices((const uint8_t *)guest_ptr(data), vertices, stride),
                                   stride);
    s_draws++;
}
