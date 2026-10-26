/**
 *    Name:        recomp_manual.c
 *    Description: hand-written overrides of recompiled functions, and the indirect-call diagnostics
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Started from xboxrecomp's templates/new-game/src/recomp_manual.c (MIT, see licenses/xboxrecomp.txt).
 *
 * This file provides:
 *   - recomp_lookup_manual()  : intercept specific Xbox VAs with hand-written code
 *   - recomp_icall_fail_log() : log when an indirect call target can't be resolved
 *   - ICALL trace ring buffer  : globals used by the RECOMP_ICALL macro
 *
 * The recomp pipeline generates an auto-dispatch table (recomp_lookup) that
 * resolves most function addresses. recomp_lookup_manual() is called FIRST,
 * giving you a chance to override any function with a custom implementation.
 *
 * Common reasons to add manual overrides:
 *   - Trace a function to understand call flow (wrap the generated version)
 *   - Fix a function the lifter translated incorrectly
 *   - Stub out a function that crashes (return early, set eax to a safe value)
 *   - Redirect a function to a native implementation (e.g., skip CRT init)
 *   - Intercept D3D/audio calls for custom rendering or sound
 */

#include <stdio.h>
#include <stdint.h>
#include <stddef.h>   /* ptrdiff_t */

/* ── ICALL trace ring buffer ───────────────────────────────── */

/*
 * These globals are written by the RECOMP_ICALL macro (defined in
 * recomp_types.h) every time an indirect call is dispatched. When a
 * crash occurs, the VEH handler or recomp_icall_fail_log() can dump
 * the last 16 call targets to help you trace what happened.
 *
 * The runtime owns them: xbox_kernel defines all three in
 * src/kernel/xbox_memory_layout.c, and recomp_types.h declares them extern.
 * Declare, do not define -- a definition here as well is a duplicate symbol,
 * and a project copied from this template failed to link on all three:
 *
 *   xbox_memory_layout.obj : error LNK2005: g_icall_count already defined
 *                            in recomp_manual.obj
 */
extern volatile uint32_t g_icall_trace[16];
extern volatile uint32_t g_icall_trace_idx;
extern volatile uint64_t g_icall_count;

typedef void (*recomp_func_t)(void);

/* ── Register state (defined in xbox_memory_layout.c) ──────── */

extern uint32_t g_eax;
extern ptrdiff_t g_xbox_mem_offset;

/* ── Manual function overrides ─────────────────────────────── */

/*
 * Return a function pointer to override the given Xbox VA, or NULL
 * to fall through to the auto-generated dispatch table.
 *
 * This is called on every indirect call (RECOMP_ICALL) and every
 * direct call through the dispatch table, so keep it fast. A chain
 * of if-statements on uint32_t compiles to a simple comparison
 * sequence; for large override tables, consider a sorted array
 * with binary search.
 *
 * Examples of common override patterns:
 *
 *   // Trace wrapper: log entry/exit around the generated function
 *   extern void sub_00012345(void);
 *   static void traced_sub_00012345(void) {
 *       fprintf(stderr, "[TRACE] sub_00012345 entered, eax=0x%08X\n", g_eax);
 *       sub_00012345();
 *       fprintf(stderr, "[TRACE] sub_00012345 returned, eax=0x%08X\n", g_eax);
 *   }
 *
 *   // Stub: skip a function entirely (return 0 in eax)
 *   static void stub_00067890(void) {
 *       g_eax = 0;
 *   }
 *
 *   // Fix: replace a broken lifted function with correct C
 *   static void fixed_sub_000ABCDE(void) {
 *       // Read arguments from stack/registers per calling convention
 *       uint32_t arg1 = g_ecx;
 *       uint32_t arg2 = MEM32(g_esp + 4);
 *       // ... correct implementation ...
 *       g_eax = result;
 *   }
 */
recomp_func_t recomp_lookup_manual(uint32_t xbox_va)
{
    /*
     * TODO: Add your overrides here. Examples:
     *
     * if (xbox_va == 0x00012345) return traced_sub_00012345;
     * if (xbox_va == 0x00067890) return stub_00067890;
     * if (xbox_va == 0x000ABCDE) return fixed_sub_000ABCDE;
     */

    (void)xbox_va;
    return (recomp_func_t)0;
}

/* ── Direct3D ──────────────────────────────────────────────── */

/* The game's D3D entries, wrapped: the Direct3D 11 bridge (d3d11_bridge.c)
 * sees each call first, while the guest stack still holds its arguments, and
 * the generated body then runs as before. The names are XbSymbolDatabase's. */
#include "d3d11_bridge.h"

/* Direct3D_CreateDevice (0x00155D10): after the generated body has created
 * the device, main.c checks where its GPU-time word ended up. */
extern void Direct3D_CreateDevice_gen(void);
extern void robotech_D3DDeviceCreated(void);

void Direct3D_CreateDevice(void)
{
    d3d11_CreateDevice();
    Direct3D_CreateDevice_gen();
    robotech_D3DDeviceCreated();
}

/* D3DDevice_Clear (0x001576D0) */
extern void D3DDevice_Clear_gen(void);

void D3DDevice_Clear(void)
{
    d3d11_Clear();
    D3DDevice_Clear_gen();
}

/* D3DDevice_Swap (0x00157530) */
extern void D3DDevice_Swap_gen(void);

void D3DDevice_Swap(void)
{
    d3d11_Swap();
    D3DDevice_Swap_gen();
}

/* D3DDevice_SetTexture (0x00156630) */
extern void D3DDevice_SetTexture_gen(void);

void D3DDevice_SetTexture(void)
{
    d3d11_SetTexture();
    D3DDevice_SetTexture_gen();
}

/* D3DTexture_LockRect (0x0015A990) */
extern void D3DTexture_LockRect_gen(void);

void D3DTexture_LockRect(void)
{
    d3d11_TextureLockRect();
    D3DTexture_LockRect_gen();
}

/* D3DDevice_SetVertexShader (0x0015A010) */
extern void D3DDevice_SetVertexShader_gen(void);

void D3DDevice_SetVertexShader(void)
{
    d3d11_SetVertexShader();
    D3DDevice_SetVertexShader_gen();
}

/* D3DDevice_DrawVerticesUP (0x0015A3B0) */
extern void D3DDevice_DrawVerticesUP_gen(void);

void D3DDevice_DrawVerticesUP(void)
{
    d3d11_DrawVerticesUP();
    D3DDevice_DrawVerticesUP_gen();
}

/* D3DDevice_SetRenderState_Simple (0x00157B00), fastcall: Method, Value */
extern void D3DDevice_SetRenderState_Simple_gen(void);

void D3DDevice_SetRenderState_Simple(void)
{
    d3d11_SetRenderStateSimple();
    D3DDevice_SetRenderState_Simple_gen();
}

/* D3DDevice_SetPixelShader (0x0015ADE0) */
extern void D3DDevice_SetPixelShader_gen(void);

void D3DDevice_SetPixelShader(void)
{
    d3d11_SetPixelShader();
    D3DDevice_SetPixelShader_gen();
}

/* D3DDevice_SetTextureState_TexCoordIndex (0x00158360) */
extern void D3DDevice_SetTextureState_TexCoordIndex_gen(void);

void D3DDevice_SetTextureState_TexCoordIndex(void)
{
    d3d11_SetTexCoordIndex();
    D3DDevice_SetTextureState_TexCoordIndex_gen();
}

/* D3DDevice_SetTransform (0x00155EA0) */
extern void D3DDevice_SetTransform_gen(void);

void D3DDevice_SetTransform(void)
{
    d3d11_SetTransform();
    D3DDevice_SetTransform_gen();
}

/* D3DDevice_SetViewport (0x00156200) */
extern void D3DDevice_SetViewport_gen(void);

void D3DDevice_SetViewport(void)
{
    d3d11_SetViewport();
    D3DDevice_SetViewport_gen();
}

/* D3DDevice_SetMaterial (0x00155FB0) */
extern void D3DDevice_SetMaterial_gen(void);

void D3DDevice_SetMaterial(void)
{
    d3d11_SetMaterial();
    D3DDevice_SetMaterial_gen();
}

/* D3DDevice_SetLight (0x00156360) */
extern void D3DDevice_SetLight_gen(void);

void D3DDevice_SetLight(void)
{
    d3d11_SetLight();
    D3DDevice_SetLight_gen();
}

/* D3DDevice_LightEnable (0x00156540) */
extern void D3DDevice_LightEnable_gen(void);

void D3DDevice_LightEnable(void)
{
    d3d11_LightEnable();
    D3DDevice_LightEnable_gen();
}

/* D3DDevice_SetStreamSource (0x00159C20) */
extern void D3DDevice_SetStreamSource_gen(void);

void D3DDevice_SetStreamSource(void)
{
    d3d11_SetStreamSource();
    D3DDevice_SetStreamSource_gen();
}

/* D3DDevice_SetIndices (0x001567B0) */
extern void D3DDevice_SetIndices_gen(void);

void D3DDevice_SetIndices(void)
{
    d3d11_SetIndices();
    D3DDevice_SetIndices_gen();
}

/* D3DDevice_DrawVertices (0x0015A510) */
extern void D3DDevice_DrawVertices_gen(void);

void D3DDevice_DrawVertices(void)
{
    d3d11_DrawVertices();
    D3DDevice_DrawVertices_gen();
}

/* D3DDevice_BeginPush_4 (0x00155CC0): the bridge wants the pointer it
 * returns, so it runs after the generated body. */
extern void D3DDevice_BeginPush_4_gen(void);

void D3DDevice_BeginPush_4(void)
{
    D3DDevice_BeginPush_4_gen();
    d3d11_BeginPushDone();
}

/* D3DDevice_EndPush (0x00155720) */
extern void D3DDevice_EndPush_gen(void);

void D3DDevice_EndPush(void)
{
    d3d11_EndPush();
    D3DDevice_EndPush_gen();
}

/* D3DDevice_DrawIndexedVertices (0x0015A5B0) */
extern void D3DDevice_DrawIndexedVertices_gen(void);

void D3DDevice_DrawIndexedVertices(void)
{
    d3d11_DrawIndexedVertices();
    D3DDevice_DrawIndexedVertices_gen();
}

/* D3DDevice_CreateVertexShader (0x001598B0): the handle exists once the
 * generated body has written it. */
extern void D3DDevice_CreateVertexShader_gen(void);

void D3DDevice_CreateVertexShader(void)
{
    d3d11_CreateVertexShaderArgs();
    D3DDevice_CreateVertexShader_gen();
    d3d11_CreateVertexShaderDone();
}

/* D3DDevice_LoadVertexShader (0x00159CB0) */
extern void D3DDevice_LoadVertexShader_gen(void);

void D3DDevice_LoadVertexShader(void)
{
    d3d11_LoadVertexShader();
    D3DDevice_LoadVertexShader_gen();
}

/* D3DDevice_SelectVertexShader (0x00159D10) */
extern void D3DDevice_SelectVertexShader_gen(void);

void D3DDevice_SelectVertexShader(void)
{
    d3d11_SelectVertexShader();
    D3DDevice_SelectVertexShader_gen();
}

/* D3DDevice_SetVertexShaderInput (0x0015A170) */
extern void D3DDevice_SetVertexShaderInput_gen(void);

void D3DDevice_SetVertexShaderInput(void)
{
    d3d11_SetVertexShaderInput();
    D3DDevice_SetVertexShaderInput_gen();
}

/* D3DDevice_SetVertexShaderConstant1 (0x001599F0), fastcall: one constant */
extern void D3DDevice_SetVertexShaderConstant1_gen(void);

void D3DDevice_SetVertexShaderConstant1(void)
{
    d3d11_SetVertexShaderConstant(1);
    D3DDevice_SetVertexShaderConstant1_gen();
}

/* D3DDevice_SetVertexShaderConstant4 (0x00159A50), fastcall: four constants */
extern void D3DDevice_SetVertexShaderConstant4_gen(void);

void D3DDevice_SetVertexShaderConstant4(void)
{
    d3d11_SetVertexShaderConstant(4);
    D3DDevice_SetVertexShaderConstant4_gen();
}

/* D3DDevice_SetVertexShaderConstantNotInline (0x00159BE0), fastcall: the
 * count, in DWORDs, on the stack */
extern void D3DDevice_SetVertexShaderConstantNotInline_gen(void);

void D3DDevice_SetVertexShaderConstantNotInline(void)
{
    d3d11_SetVertexShaderConstant(0);
    D3DDevice_SetVertexShaderConstantNotInline_gen();
}

/* ── XInput ────────────────────────────────────────────────── */

#include "input_bridge.h"

/* XInputOpen (0x00187F4F): input_bridge.c learns which port a handle is. */
extern void XInputOpen_gen(void);

void XInputOpen(void)
{
    input_XInputOpenArgs();
    XInputOpen_gen();
    input_XInputOpenDone();
}

/* XInputGetState (0x0018818E), replaced: answered from the host's pads and
 * keyboard (input_bridge.c says why). */
void xapi_XInputGetState(void)
{
    input_XInputGetState();
}

/* XInputSetState (0x001881FD), replaced: the rumble to the host's pads. */
void XInputSetState(void)
{
    input_XInputSetState();
}

/* ── The clock ─────────────────────────────────────────────── */

#include "clock_bridge.h"

/* QueryPerformanceCounter (0x0014E5BE): tied to the frames while
 * ROBOTECH_VIRTUAL_CLOCK=1 (clock_bridge.c), the game's own otherwise. */
extern void xapi_QueryPerformanceCounter_gen(void);

void xapi_QueryPerformanceCounter(void)
{
    if (clock_Virtual())
        clock_QueryPerformanceCounter();
    else
        xapi_QueryPerformanceCounter_gen();
}

/* GetSystemTimeAsFileTime (0x0014E562): the date, which time() and the save
 * stamps read, tied to the frames too while the clock is virtual. */
extern void xapi_GetSystemTimeAsFileTime_gen(void);

void xapi_GetSystemTimeAsFileTime(void)
{
    if (clock_Virtual())
        clock_GetSystemTimeAsFileTime();
    else
        xapi_GetSystemTimeAsFileTime_gen();
}

/* GetTickCount (0x0014E6E6): the milliseconds of the frames while the clock
 * is virtual. */
extern void xapi_GetTickCount_gen(void);

void xapi_GetTickCount(void)
{
    if (clock_Virtual())
        clock_GetTickCount();
    else
        xapi_GetTickCount_gen();
}

/* ── DirectSound ───────────────────────────────────────────── */

#include "dsound_bridge.h"

/* The 29 DirectSound entries the game and its Bink call, answered on the host
 * (dsound_bridge.c says how); with RECOMP_AC97_READY=1, the XDK's own, on the
 * emulated APU. */

/* IDirectSound_Release (0x00167453) */
extern void IDirectSound_Release_gen(void);

void IDirectSound_Release(void)
{
    if (dsound_Native())
        dsound_IDirectSound_Release();
    else
        IDirectSound_Release_gen();
}

/* IDirectSoundBuffer_Unlock (0x00167469) */
extern void IDirectSoundBuffer_Unlock_gen(void);

void IDirectSoundBuffer_Unlock(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_Unlock();
    else
        IDirectSoundBuffer_Unlock_gen();
}

/* IDirectSoundBuffer_Release (0x0016746E) */
extern void IDirectSoundBuffer_Release_gen(void);

void IDirectSoundBuffer_Release(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_Release();
    else
        IDirectSoundBuffer_Release_gen();
}

/* DirectSoundUseLightHRTF (0x00167484) */
extern void DirectSoundUseLightHRTF_gen(void);

void DirectSoundUseLightHRTF(void)
{
    if (dsound_Native())
        dsound_DirectSoundUseLightHRTF();
    else
        DirectSoundUseLightHRTF_gen();
}

/* IDirectSound_DownloadEffectsImage (0x00167D4A) */
extern void IDirectSound_DownloadEffectsImage_gen(void);

void IDirectSound_DownloadEffectsImage(void)
{
    if (dsound_Native())
        dsound_IDirectSound_DownloadEffectsImage();
    else
        IDirectSound_DownloadEffectsImage_gen();
}

/* IDirectSoundBuffer_SetVolume (0x00167D71) */
extern void IDirectSoundBuffer_SetVolume_gen(void);

void IDirectSoundBuffer_SetVolume(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetVolume();
    else
        IDirectSoundBuffer_SetVolume_gen();
}

/* IDirectSoundBuffer_SetHeadroom (0x00167D8D) */
extern void IDirectSoundBuffer_SetHeadroom_gen(void);

void IDirectSoundBuffer_SetHeadroom(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetHeadroom();
    else
        IDirectSoundBuffer_SetHeadroom_gen();
}

/* IDirectSoundBuffer_SetMixBins (0x00167DA9) */
extern void IDirectSoundBuffer_SetMixBins_gen(void);

void IDirectSoundBuffer_SetMixBins(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetMixBins();
    else
        IDirectSoundBuffer_SetMixBins_gen();
}

/* IDirectSoundBuffer_SetMixBinVolumes_8 (0x00167DC5) */
extern void IDirectSoundBuffer_SetMixBinVolumes_8_gen(void);

void IDirectSoundBuffer_SetMixBinVolumes_8(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetMixBinVolumes_8();
    else
        IDirectSoundBuffer_SetMixBinVolumes_8_gen();
}

/* IDirectSoundBuffer_Play (0x00167DE1) */
extern void IDirectSoundBuffer_Play_gen(void);

void IDirectSoundBuffer_Play(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_Play();
    else
        IDirectSoundBuffer_Play_gen();
}

/* IDirectSoundBuffer_Stop (0x00167E05) */
extern void IDirectSoundBuffer_Stop_gen(void);

void IDirectSoundBuffer_Stop(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_Stop();
    else
        IDirectSoundBuffer_Stop_gen();
}

/* IDirectSoundBuffer_GetStatus (0x00167E1D) */
extern void IDirectSoundBuffer_GetStatus_gen(void);

void IDirectSoundBuffer_GetStatus(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_GetStatus();
    else
        IDirectSoundBuffer_GetStatus_gen();
}

/* IDirectSoundBuffer_GetCurrentPosition (0x00167E39) */
extern void IDirectSoundBuffer_GetCurrentPosition_gen(void);

void IDirectSoundBuffer_GetCurrentPosition(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_GetCurrentPosition();
    else
        IDirectSoundBuffer_GetCurrentPosition_gen();
}

/* IDirectSoundBuffer_SetCurrentPosition (0x00167E59) */
extern void IDirectSoundBuffer_SetCurrentPosition_gen(void);

void IDirectSoundBuffer_SetCurrentPosition(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetCurrentPosition();
    else
        IDirectSoundBuffer_SetCurrentPosition_gen();
}

/* IDirectSoundBuffer_Lock (0x00167E75) */
extern void IDirectSoundBuffer_Lock_gen(void);

void IDirectSoundBuffer_Lock(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_Lock();
    else
        IDirectSoundBuffer_Lock_gen();
}

/* DirectSoundDoWork (0x00167EA5) */
extern void DirectSoundDoWork_gen(void);

void DirectSoundDoWork(void)
{
    if (dsound_Native())
        dsound_DirectSoundDoWork();
    else
        DirectSoundDoWork_gen();
}

/* IDirectSound_CommitDeferredSettings (0x001684CA) */
extern void IDirectSound_CommitDeferredSettings_gen(void);

void IDirectSound_CommitDeferredSettings(void)
{
    if (dsound_Native())
        dsound_IDirectSound_CommitDeferredSettings();
    else
        IDirectSound_CommitDeferredSettings_gen();
}

/* IDirectSoundBuffer_SetFrequency (0x001684E2) */
extern void IDirectSoundBuffer_SetFrequency_gen(void);

void IDirectSoundBuffer_SetFrequency(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetFrequency();
    else
        IDirectSoundBuffer_SetFrequency_gen();
}

/* IDirectSoundBuffer_SetMaxDistance (0x001684FE) */
extern void IDirectSoundBuffer_SetMaxDistance_gen(void);

void IDirectSoundBuffer_SetMaxDistance(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetMaxDistance();
    else
        IDirectSoundBuffer_SetMaxDistance_gen();
}

/* IDirectSoundBuffer_SetMinDistance (0x00168522) */
extern void IDirectSoundBuffer_SetMinDistance_gen(void);

void IDirectSoundBuffer_SetMinDistance(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetMinDistance();
    else
        IDirectSoundBuffer_SetMinDistance_gen();
}

/* IDirectSoundBuffer_SetPosition (0x00168546) */
extern void IDirectSoundBuffer_SetPosition_gen(void);

void IDirectSoundBuffer_SetPosition(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetPosition();
    else
        IDirectSoundBuffer_SetPosition_gen();
}

/* IDirectSoundBuffer_SetI3DL2Source (0x0016857B) */
extern void IDirectSoundBuffer_SetI3DL2Source_gen(void);

void IDirectSoundBuffer_SetI3DL2Source(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetI3DL2Source();
    else
        IDirectSoundBuffer_SetI3DL2Source_gen();
}

/* IDirectSoundBuffer_SetPlayRegion (0x0016859B) */
extern void IDirectSoundBuffer_SetPlayRegion_gen(void);

void IDirectSoundBuffer_SetPlayRegion(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetPlayRegion();
    else
        IDirectSoundBuffer_SetPlayRegion_gen();
}

/* IDirectSound_SetOrientation (0x00168A34) */
extern void IDirectSound_SetOrientation_gen(void);

void IDirectSound_SetOrientation(void)
{
    if (dsound_Native())
        dsound_IDirectSound_SetOrientation();
    else
        IDirectSound_SetOrientation_gen();
}

/* IDirectSound_SetPosition (0x00168A7E) */
extern void IDirectSound_SetPosition_gen(void);

void IDirectSound_SetPosition(void)
{
    if (dsound_Native())
        dsound_IDirectSound_SetPosition();
    else
        IDirectSound_SetPosition_gen();
}

/* IDirectSoundBuffer_SetBufferData (0x00168AB3) */
extern void IDirectSoundBuffer_SetBufferData_gen(void);

void IDirectSoundBuffer_SetBufferData(void)
{
    if (dsound_Native())
        dsound_IDirectSoundBuffer_SetBufferData();
    else
        IDirectSoundBuffer_SetBufferData_gen();
}

/* IDirectSound_CreateSoundBuffer (0x00168D17) */
extern void IDirectSound_CreateSoundBuffer_gen(void);

void IDirectSound_CreateSoundBuffer(void)
{
    if (dsound_Native())
        dsound_IDirectSound_CreateSoundBuffer();
    else
        IDirectSound_CreateSoundBuffer_gen();
}

/* DirectSoundCreate (0x00168ED1) */
extern void DirectSoundCreate_gen(void);

void DirectSoundCreate(void)
{
    if (dsound_Native())
        dsound_DirectSoundCreate();
    else
        DirectSoundCreate_gen();
}

/* DirectSoundCreateBuffer (0x00168F18) */
extern void DirectSoundCreateBuffer_gen(void);

void DirectSoundCreateBuffer(void)
{
    if (dsound_Native())
        dsound_DirectSoundCreateBuffer();
    else
        DirectSoundCreateBuffer_gen();
}

/* ── ICALL failure logging ─────────────────────────────────── */

/*
 * Called when RECOMP_ICALL cannot resolve a target address.
 * This usually means one of:
 *   - A vtable dispatch to an address not in the dispatch table
 *   - A function pointer loaded from uninitialized or corrupt memory
 *   - A kernel thunk address that the bridge doesn't handle
 *
 * During early bring-up you will see many of these. Most are harmless
 * (the ICALL macro pops the dummy return address and continues).
 * Focus on the ones that cause crashes or incorrect behavior.
 */
void recomp_icall_fail_log(uint32_t va)
{
    fprintf(stderr, "[ICALL] Failed to resolve VA 0x%08X (total calls: %llu)\n",
            va, (unsigned long long)g_icall_count);

    /* Dump last 16 call targets from the ring buffer */
    fprintf(stderr, "  Recent ICALL targets:\n");
    for (int i = 0; i < 16; i++) {
        int idx = (g_icall_trace_idx - 16 + i) & 15;
        if (g_icall_trace[idx])
            fprintf(stderr, "    [%2d] 0x%08X\n", i, g_icall_trace[idx]);
    }
    fflush(stderr);
}

/* An indirect call whose target is not code: a null or wild function pointer.
 *
 * Skipping these is right -- calling a data address is worse -- but skipping
 * them *silently* is not. They almost always arrive inside a loop, so the
 * symptom is a hang with no output rather than a diagnosable null vtable call.
 *
 * Rate-limited per address: a spin can produce millions of these, and the
 * useful information is which addresses occur, not how often.
 */
void recomp_icall_not_code_log(uint32_t va)
{
    enum { SLOTS = 16 };
    static uint32_t seen[SLOTS];
    static uint64_t hits[SLOTS];
    static int count;
    int i;

    for (i = 0; i < count; i++)
        if (seen[i] == va)
            break;
    if (i == count) {
        if (count == SLOTS)
            return;
        seen[count] = va;
        hits[count] = 0;
        count++;
    }
    hits[i]++;
    /* Report at 1, 10, 100, 1000 ... rather than once. A single line says a
     * wild pointer was skipped; the progression says it is being skipped in a
     * loop, which is the difference between a curiosity and the reason the
     * title is hung. */
    {
        uint64_t n = hits[i];
        while (n >= 10 && n % 10 == 0)
            n /= 10;
        if (n != 1)
            return;
    }
    fprintf(stderr, "[ICALL] target 0x%08X is not code -- skipped %llu time(s) "
                    "(null or wild function pointer, at call #%llu)\n",
            va, (unsigned long long)hits[i],
            (unsigned long long)g_icall_count);
    fflush(stderr);
}

/* ── Untranslated instructions ───────────────────────────────────────────
 *
 * The lifter emits RECOMP_UNIMPL(text, va) at every instruction it has no
 * translation for, in place of the bare comment it used to leave. The
 * instruction is still a no-op; this only stops the omission being silent.
 * RECOMP_UNIMPL_TRAP=1 aborts at the first hit, at the guest address of the
 * cause rather than wherever the damage surfaces. */
#include <stdlib.h>

void recomp_unimpl(const char *text, uint32_t va)
{
    static int printed;
    const char *trap = getenv("RECOMP_UNIMPL_TRAP");
    int stop = trap && *trap && *trap != '0';

    if (printed < 50 || stop) {
        printed++;
        fprintf(stderr,
                "[UNIMPL] untranslated instruction REACHED: `%s` at 0x%08X"
                " (a no-op; set RECOMP_UNIMPL_TRAP=1 to stop here)\n",
                text, va);
        fflush(stderr);
    }
    if (stop) abort();
}
