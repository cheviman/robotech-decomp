/**
 *    Name:        recomp_manual.c
 *    Description: hand-written overrides of recompiled functions, and the indirect-call diagnostics
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
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
extern void sub_00155D10_gen(void);
extern void robotech_D3DDeviceCreated(void);

void sub_00155D10(void)
{
    d3d11_CreateDevice();
    sub_00155D10_gen();
    robotech_D3DDeviceCreated();
}

/* D3DDevice_Clear (0x001576D0) */
extern void sub_001576D0_gen(void);

void sub_001576D0(void)
{
    d3d11_Clear();
    sub_001576D0_gen();
}

/* D3DDevice_Swap (0x00157530) */
extern void sub_00157530_gen(void);

void sub_00157530(void)
{
    d3d11_Swap();
    sub_00157530_gen();
}

/* D3DDevice_SetTexture (0x00156630) */
extern void sub_00156630_gen(void);

void sub_00156630(void)
{
    d3d11_SetTexture();
    sub_00156630_gen();
}

/* D3DTexture_LockRect (0x0015A990) */
extern void sub_0015A990_gen(void);

void sub_0015A990(void)
{
    d3d11_TextureLockRect();
    sub_0015A990_gen();
}

/* D3DDevice_SetVertexShader (0x0015A010) */
extern void sub_0015A010_gen(void);

void sub_0015A010(void)
{
    d3d11_SetVertexShader();
    sub_0015A010_gen();
}

/* D3DDevice_DrawVerticesUP (0x0015A3B0) */
extern void sub_0015A3B0_gen(void);

void sub_0015A3B0(void)
{
    d3d11_DrawVerticesUP();
    sub_0015A3B0_gen();
}

/* D3DDevice_SetRenderState_Simple (0x00157B00), fastcall: Method, Value */
extern void sub_00157B00_gen(void);

void sub_00157B00(void)
{
    d3d11_SetRenderStateSimple();
    sub_00157B00_gen();
}

/* D3DDevice_SetPixelShader (0x0015ADE0) */
extern void sub_0015ADE0_gen(void);

void sub_0015ADE0(void)
{
    d3d11_SetPixelShader();
    sub_0015ADE0_gen();
}

/* D3DDevice_SetTextureState_TexCoordIndex (0x00158360) */
extern void sub_00158360_gen(void);

void sub_00158360(void)
{
    d3d11_SetTexCoordIndex();
    sub_00158360_gen();
}

/* D3DDevice_SetTransform (0x00155EA0) */
extern void sub_00155EA0_gen(void);

void sub_00155EA0(void)
{
    d3d11_SetTransform();
    sub_00155EA0_gen();
}

/* D3DDevice_SetViewport (0x00156200) */
extern void sub_00156200_gen(void);

void sub_00156200(void)
{
    d3d11_SetViewport();
    sub_00156200_gen();
}

/* D3DDevice_SetMaterial (0x00155FB0) */
extern void sub_00155FB0_gen(void);

void sub_00155FB0(void)
{
    d3d11_SetMaterial();
    sub_00155FB0_gen();
}

/* D3DDevice_SetLight (0x00156360) */
extern void sub_00156360_gen(void);

void sub_00156360(void)
{
    d3d11_SetLight();
    sub_00156360_gen();
}

/* D3DDevice_LightEnable (0x00156540) */
extern void sub_00156540_gen(void);

void sub_00156540(void)
{
    d3d11_LightEnable();
    sub_00156540_gen();
}

/* D3DDevice_SetStreamSource (0x00159C20) */
extern void sub_00159C20_gen(void);

void sub_00159C20(void)
{
    d3d11_SetStreamSource();
    sub_00159C20_gen();
}

/* D3DDevice_SetIndices (0x001567B0) */
extern void sub_001567B0_gen(void);

void sub_001567B0(void)
{
    d3d11_SetIndices();
    sub_001567B0_gen();
}

/* D3DDevice_DrawVertices (0x0015A510) */
extern void sub_0015A510_gen(void);

void sub_0015A510(void)
{
    d3d11_DrawVertices();
    sub_0015A510_gen();
}

/* D3DDevice_BeginPush_4 (0x00155CC0): the bridge wants the pointer it
 * returns, so it runs after the generated body. */
extern void sub_00155CC0_gen(void);

void sub_00155CC0(void)
{
    sub_00155CC0_gen();
    d3d11_BeginPushDone();
}

/* D3DDevice_EndPush (0x00155720) */
extern void sub_00155720_gen(void);

void sub_00155720(void)
{
    d3d11_EndPush();
    sub_00155720_gen();
}

/* D3DDevice_DrawIndexedVertices (0x0015A5B0) */
extern void sub_0015A5B0_gen(void);

void sub_0015A5B0(void)
{
    d3d11_DrawIndexedVertices();
    sub_0015A5B0_gen();
}

/* D3DDevice_CreateVertexShader (0x001598B0): the handle exists once the
 * generated body has written it. */
extern void sub_001598B0_gen(void);

void sub_001598B0(void)
{
    d3d11_CreateVertexShaderArgs();
    sub_001598B0_gen();
    d3d11_CreateVertexShaderDone();
}

/* D3DDevice_LoadVertexShader (0x00159CB0) */
extern void sub_00159CB0_gen(void);

void sub_00159CB0(void)
{
    d3d11_LoadVertexShader();
    sub_00159CB0_gen();
}

/* D3DDevice_SelectVertexShader (0x00159D10) */
extern void sub_00159D10_gen(void);

void sub_00159D10(void)
{
    d3d11_SelectVertexShader();
    sub_00159D10_gen();
}

/* D3DDevice_SetVertexShaderInput (0x0015A170) */
extern void sub_0015A170_gen(void);

void sub_0015A170(void)
{
    d3d11_SetVertexShaderInput();
    sub_0015A170_gen();
}

/* D3DDevice_SetVertexShaderConstant1 (0x001599F0), fastcall: one constant */
extern void sub_001599F0_gen(void);

void sub_001599F0(void)
{
    d3d11_SetVertexShaderConstant(1);
    sub_001599F0_gen();
}

/* D3DDevice_SetVertexShaderConstant4 (0x00159A50), fastcall: four constants */
extern void sub_00159A50_gen(void);

void sub_00159A50(void)
{
    d3d11_SetVertexShaderConstant(4);
    sub_00159A50_gen();
}

/* D3DDevice_SetVertexShaderConstantNotInline (0x00159BE0), fastcall: the
 * count, in DWORDs, on the stack */
extern void sub_00159BE0_gen(void);

void sub_00159BE0(void)
{
    d3d11_SetVertexShaderConstant(0);
    sub_00159BE0_gen();
}

/* ── XInput ────────────────────────────────────────────────── */

#include "input_bridge.h"

/* XInputOpen (0x00187F4F): input_bridge.c learns which port a handle is. */
extern void sub_00187F4F_gen(void);

void sub_00187F4F(void)
{
    input_XInputOpenArgs();
    sub_00187F4F_gen();
    input_XInputOpenDone();
}

/* XInputGetState (0x0018818E), replaced: answered from the host's pads and
 * keyboard (input_bridge.c says why). */
void sub_0018818E(void)
{
    input_XInputGetState();
}

/* XInputSetState (0x001881FD), replaced: the rumble to the host's pads. */
void sub_001881FD(void)
{
    input_XInputSetState();
}

/* ── DirectSound ───────────────────────────────────────────── */

#include "dsound_bridge.h"

/* IDirectSoundBuffer_GetStatus (0x00167E1D) */
extern void sub_00167E1D_gen(void);

void sub_00167E1D(void)
{
    dsound_GetStatusArgs();
    sub_00167E1D_gen();
    dsound_GetStatusDone();
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
