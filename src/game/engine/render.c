/**
 *    Name:        engine/render.c
 *    Description: the engine's renderer, written in C: setting a render state or a texture stage's state only
 *                 when it changes
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The engine keeps the states it set last (vcRenderStates, vcRenderTextureStageStates) and leaves one
 *    alone that it would set to the same value. Otherwise it does what the XDK's D3DDevice_SetRenderState
 *    and D3DDevice_SetTextureStageState do, inlined: a simple render state is pushed to the GPU at once; a
 *    deferred one, and a deferred texture stage state, goes into Direct3D's own record with the flags
 *    that tell its next draw what changed; any other has a function of its own. Those functions are
 *    the XDK's, still recompiled.
 *
 *    A state's number is signed, as the original compares it; one past the last is recorded and
 *    nothing more.
 */
#include "decomp.h"
#include "render.h"

/* The XDK's render states: the simple ones, the deferred ones, and the complex ones each with its
 * function */
#define RS_SIMPLE_END           0x5C
#define RS_DEFERRED_END         0x88
#define RS_COMPLEX_END          0xA6

/* The XDK's texture stage states */
#define TSS_PER_STAGE           32
#define TSS_COLOROP             12      /* those before it change the stage's texture */
#define TSS_DEFERRED_END        22      /* those up to TEXTURETRANSFORMFLAGS are recorded */
#define TSS_BUMPENV_LAST        0x1B    /* BUMPENVMAT00 to BUMPENVLOFFSET */
#define TSS_TEXCOORDINDEX       0x1C
#define TSS_BORDERCOLOR         0x1D
#define TSS_COLORKEYCOLOR       0x1E
#define TOP_BUMPENVMAP          0x19    /* the first colour operation that bumps */
/* The dirty flags a colour operation sets: the combiners; from BUMPENVMAP on, the four stages'
 * textures and 0x4000 too */
#define DIRTY_COMBINERS         0x0800u
#define DIRTY_BUMP_COMBINERS    0x480Fu

/* The complex render states' functions, from RS_DEFERRED_END on. */
static void (*const complex_states[RS_COMPLEX_END - RS_DEFERRED_END])(void) = {
    D3DDevice_SetRenderState_PSTextureModes,                /* 0x88 */
    D3DDevice_SetRenderState_VertexBlend,
    D3DDevice_SetRenderState_FogColor,
    D3DDevice_SetRenderState_FillMode,
    D3DDevice_SetRenderState_BackFillMode,
    D3DDevice_SetRenderState_TwoSidedLighting,
    D3DDevice_SetRenderState_NormalizeNormals,
    D3DDevice_SetRenderState_ZEnable,
    D3DDevice_SetRenderState_StencilEnable,                 /* 0x90 */
    D3DDevice_SetRenderState_StencilFail,
    D3DDevice_SetRenderState_FrontFace,
    D3DDevice_SetRenderState_CullMode,
    D3DDevice_SetRenderState_TextureFactor,
    D3DDevice_SetRenderState_ZBias,
    D3DDevice_SetRenderState_LogicOp,
    D3DDevice_SetRenderState_EdgeAntiAlias,
    D3DDevice_SetRenderState_MultiSampleAntiAlias,          /* 0x98 */
    D3DDevice_SetRenderState_MultiSampleMask,
    D3DDevice_SetRenderState_MultiSampleMode,
    D3DDevice_SetRenderState_MultiSampleRenderTargetMode,
    D3DDevice_SetRenderState_ShadowFunc,
    D3DDevice_SetRenderState_LineWidth,
    D3DDevice_SetRenderState_SampleAlpha,
    D3DDevice_SetRenderState_Dxt1NoiseEnable,
    D3DDevice_SetRenderState_YuvEnable,                     /* 0xA0 */
    D3DDevice_SetRenderState_OcclusionCullEnable,
    D3DDevice_SetRenderState_StencilCullEnable,
    D3DDevice_SetRenderState_RopZCmpAlwaysRead,
    D3DDevice_SetRenderState_RopZRead,
    D3DDevice_SetRenderState_DoNotCullUncompressed,         /* 0xA5 */
};

void vcRenderSetState(int32_t state, uint32_t value)
{
    if (value == vcRenderStates(state))
        return;
    vcRenderStates(state) = value;
    if (state < RS_SIMPLE_END) {
        CALL_FASTCALL2(D3DDevice_SetRenderState_Simple, D3DSIMPLERENDERSTATEENCODE(state), value);
    } else if (state < RS_DEFERRED_END) {
        D3D__DirtyFlags |= D3DDIRTYFROMRENDERSTATE(state - RS_SIMPLE_END);
        D3D__RenderState(state) = value;
    } else if (state < RS_COMPLEX_END) {
        CALL(complex_states[state - RS_DEFERRED_END], value);
    }
}
ENTRY_CDECL2_VOID(vcRenderSetState)

void vcRenderSetTextureStageState(uint32_t stage, int32_t state, uint32_t value)
{
    int32_t at = (int32_t)(stage * TSS_PER_STAGE + (uint32_t)state);

    if (value == vcRenderTextureStageStates(at))
        return;
    vcRenderTextureStageStates(at) = value;
    if (state < TSS_COLOROP) {
        D3D__TextureState(at) = value;
        D3D__DirtyFlags |= 1u << (stage & 31u);             /* the stage's texture */
    } else if (state == TSS_COLOROP) {
        D3D__TextureState(at) = value;
        D3D__DirtyFlags |= value < TOP_BUMPENVMAP ? DIRTY_COMBINERS : DIRTY_BUMP_COMBINERS;
    } else if (state < TSS_DEFERRED_END) {
        D3D__DirtyFlags |= D3DDIRTYFROMTEXTURESTATE(state);
        D3D__TextureState(at) = value;
    } else if (state == TSS_TEXCOORDINDEX) {
        CALL(D3DDevice_SetTextureState_TexCoordIndex, stage, value);
    } else if (state == TSS_BORDERCOLOR) {
        CALL(D3DDevice_SetTextureState_BorderColor, stage, value);
    } else if (state == TSS_COLORKEYCOLOR) {
        CALL(D3DDevice_SetTextureState_ColorKeyColor, stage, value);
    } else if (state <= TSS_BUMPENV_LAST) {
        CALL(D3DDevice_SetTextureState_BumpEnv, stage, (uint32_t)state, value);
    }
}
ENTRY_CDECL3_VOID(vcRenderSetTextureStageState)
