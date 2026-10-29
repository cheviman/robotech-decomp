/**
 *    Name:        vertex_program_hlsl.c
 *    Description: the game's vertex programs (NV2A microcode) as HLSL for shader model 5, for the Direct3D 11
 *                 bridge to run them on the GPU
 *    Version:     0.1.0
 *    Created:     29-10-2026
 *    Modified:    29-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The translation follows XboxXBERecomp's (runtime/gpu/shaders.cpp, MIT, see
 *    licenses/XboxXBERecomp.txt): each instruction's operands read from the fields where the NV2A keeps
 *    them, the MAC and ILU halves as HLSL expressions, the program straight-line code from the slot it
 *    starts at to the one marked final. Its arithmetic is the bridge's own, though: xboxrecomp's
 *    interpreter (src/kernel/nv2a_vsh_interp.c), which draws the vertex programs without ROBOTECH_VP_GPU
 *    and the scenarios were checked with -- a product with a zero is a plain product, RCC clamps to the
 *    interpreter's bounds, an unknown constant index reads c[0], a write to a constant is dropped (the
 *    bridge never enables them) -- and the sums of the dot products go in its order, a product and a
 *    sum at a time, with nothing fused (precise), so a position comes out as the CPU makes it.
 *
 *    The inputs are fetched by the shader itself, from the guest's vertex bytes as the bridge copies them
 *    into one buffer (a ByteAddressBuffer at t0), each attribute at its stream's base, SV_VertexID times
 *    its stride and its offset, and expanded as the bridge's vprog_fetch expands it: any type, offset
 *    and stride the declaration has, with no input layout.
 *
 *    The end of the shader is the rest of the bridge's CPU path: the program's oPos through the viewport
 *    (the epilogue every XDK program ends in left x, y, z divided by w, with c-38 and c-37 at 1 and 0),
 *    the colours clamped and stored as bytes, the fog in the specular's alpha, the coordinate sets of a
 *    linear texture divided by its size; and then what the layer's vertex shader does with such a
 *    pre-transformed vertex (src/d3d/d3d8_shaders.c, its FLAG_PRETRANSFORMED branch, written the same),
 *    into the layer's own VS_OUT, which its pixel shader reads.
 */
#include "vertex_program_hlsl.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PROGRAM_CONSTANTS 192

/* The text being written; on a failed allocation `failed` is set and the rest is dropped. */
typedef struct {
    char *text;
    size_t length, size;
    int failed;
} Hlsl;

static void put(Hlsl *h, const char *format, ...)
{
    va_list ap;
    int n;

    while (!h->failed) {
        va_start(ap, format);
        n = vsnprintf(h->text + h->length, h->size - h->length, format, ap);
        va_end(ap);
        if (n >= 0 && (size_t)n < h->size - h->length) {
            h->length += (size_t)n;
            return;
        }
        {
            size_t size = h->size * 2 + (n > 0 ? (size_t)n : 0);
            char *grown = (char *)realloc(h->text, size);

            if (!grown || n < 0) {
                h->failed = 1;
                return;
            }
            h->text = grown;
            h->size = size;
        }
    }
}

static uint32_t field(const uint32_t *ins, int dw, int lo, int width)
{
    return (ins[dw] >> lo) & ((1u << width) - 1u);
}

/* What every program's shader shares: the constants, the draw's values, the vertex bytes, the layer's
 * VS_OUT, the loads, and the ILU's operations as the interpreter computes them. */
static const char s_head[] =
    "cbuffer Constants : register(b0) { float4 c[192]; };\n"
    "cbuffer Draw : register(b1) {\n"
    "    float4 viewport;\n"
    "    float4 depth;\n"
    "    float4 screen;\n"
    "    float4 texture_size[4];\n"
    "    uint4 texture_set;\n"
    "    uint4 first;\n"
    "    uint4 streams[16];\n"
    "};\n"
    "ByteAddressBuffer vertices : register(t0);\n"
    "\n"
    "struct VS_OUT {\n"
    "    float4 pos      : SV_POSITION;\n"
    "    float4 diffuse  : COLOR0;\n"
    "    float4 specular : COLOR1;\n"
    "    float3 tex0     : TEXCOORD0;\n"
    "    float3 tex1     : TEXCOORD1;\n"
    "    float3 tex2     : TEXCOORD2;\n"
    "    float3 tex3     : TEXCOORD3;\n"
    "    float  fog      : TEXCOORD4;\n"
    "    float4 viewpos  : TEXCOORD5;\n"
    "};\n"
    "\n"
    "/* a DWORD at any byte: Load takes multiples of four */\n"
    "uint load32(uint a)\n"
    "{\n"
    "    uint at = a & ~3u, shift = (a & 3u) * 8u, low = vertices.Load(at);\n"
    "    return shift ? (low >> shift) | (vertices.Load(at + 4u) << (32u - shift)) : low;\n"
    "}\n"
    "float load16s(uint a) { return (float)(asint(load32(a) << 16) >> 16); }\n"
    "float load8(uint a) { return (float)(load32(a) & 0xFFu); }\n"
    "\n"
    "float infinity() { return asfloat(0x7F800000u); }\n"
    "float4 ilu_rcp(float x) { precise float r = x == 0.0 ? infinity() : 1.0 / x; return r.xxxx; }\n"
    "float4 ilu_rcc(float x)\n"
    "{\n"
    "    precise float f = 1.0 / x;\n"
    "    if (abs(f) < 5.42101e-20) f = f < 0.0 ? -5.42101e-20 : 5.42101e-20;\n"
    "    if (abs(f) > 1.884467e19) f = f < 0.0 ? -1.884467e19 : 1.884467e19;\n"
    "    return f.xxxx;\n"
    "}\n"
    "float4 ilu_rsq(float x) { precise float r = 1.0 / sqrt(abs(x)); return r.xxxx; }\n"
    "float4 ilu_exp(float x)\n"
    "{\n"
    "    precise float whole = floor(x);\n"
    "    return float4(exp2(whole), x - whole, exp2(x), 1.0);\n"
    "}\n"
    "float4 ilu_log(float x)\n"
    "{\n"
    "    precise float a = abs(x), e;\n"
    "    if (a == 0.0) return float4(-infinity(), 1.0, -infinity(), 1.0);\n"
    "    e = floor(log2(a));\n"
    "    return float4(e, a / exp2(e), log2(a), 1.0);\n"
    "}\n"
    "/* powf's: 0 to the power 0 is 1, where exp2(0 * log2(0)) is not a number */\n"
    "float4 ilu_lit(float4 s)\n"
    "{\n"
    "    float nl = s.x > 0.0 ? s.x : 0.0, nh = s.y > 0.0 ? s.y : 0.0;\n"
    "    float p = s.w < -127.9961 ? -127.9961 : (s.w > 127.9961 ? 127.9961 : s.w);\n"
    "    return float4(1.0, nl, s.x > 0.0 ? (p == 0.0 ? 1.0 : pow(nh, p)) : 0.0, 1.0);\n"
    "}\n"
    "\n"
    "/* The bridge's CPU path from here (vprog_transform, vprog_color, bridge_vertices), then the layer's\n"
    " * vertex shader for a pre-transformed vertex. */\n"
    "float4 stored_colour(float4 c)\n"
    "{\n"
    "    precise float4 b = floor(saturate(c) * 255.0 + 0.5);\n"
    "    return b / 255.0;\n"
    "}\n"
    "VS_OUT finish(float4 p, float4 d0, float4 d1, float4 fog, float4 t0, float4 t1, float4 t2, float4 t3)\n"
    "{\n"
    "    VS_OUT o;\n"
    "    precise float w = p.w;\n"
    "    precise float x = (viewport.x + (p.x + 1.0) * 0.5 * viewport.z) * depth.z;\n"
    "    precise float y = (viewport.y + (1.0 - p.y) * 0.5 * viewport.w) * depth.w;\n"
    "    precise float z = depth.x + p.z * (depth.y - depth.x);\n"
    "    precise float rhw = w != 0.0 ? 1.0 / w : 1.0;\n"
    "    precise float2 set[4] = { t0.xy, t1.xy, t2.xy, t3.xy };\n"
    "    uint k;\n"
    "\n"
    "    [unroll] for (k = 0; k < 4; k++) {\n"
    "        uint s = texture_set[k];\n"
    "        if (s == 0) set[0] /= texture_size[k].xy;\n"
    "        else if (s == 1) set[1] /= texture_size[k].xy;\n"
    "        else if (s == 2) set[2] /= texture_size[k].xy;\n"
    "        else if (s == 3) set[3] /= texture_size[k].xy;\n"
    "    }\n"
    "    o.pos.x = (x / screen.x) * 2.0 - 1.0;\n"
    "    o.pos.y = 1.0 - (y / screen.y) * 2.0;\n"
    "    o.pos.z = z;\n"
    "    o.pos.w = 1.0;\n"
    "    if (rhw != 0.0) o.pos /= rhw;\n"
    "    o.tex0 = float3(set[0], 0.0);\n"
    "    o.tex1 = float3(set[1], 0.0);\n"
    "    o.tex2 = float3(set[2], 0.0);\n"
    "    o.tex3 = float3(set[3], 0.0);\n"
    "    o.diffuse = stored_colour(saturate(d0));\n"
    "    o.specular = stored_colour(float4(saturate(d1.rgb), fog.x));\n"
    "    o.fog = 1.0;\n"
    "    o.viewpos = float4(0.0, 0.0, 0.0, 1.0);\n"
    "    return o;\n"
    "}\n"
    "\n";

/* An input's four floats, as vprog_fetch expands its type: the components it has, then 0, 0, 0, 1. */
static void put_fetch(Hlsl *h, const VertexProgramInput *in)
{
    static const char *const one[4] = { "0.0", "0.0", "0.0", "1.0" };
    unsigned n = (in->type >> 4) & 0xFu, k;
    char v[4][64];

    for (k = 0; k < 4; k++)
        snprintf(v[k], sizeof v[k], "%s", one[k]);
    switch (in->type & 0xFu) {
    case 0x2:
        if (in->type == 0x72) {                       /* FLOAT2H: x, y, w */
            snprintf(v[0], sizeof v[0], "asfloat(load32(a))");
            snprintf(v[1], sizeof v[1], "asfloat(load32(a + 4u))");
            snprintf(v[3], sizeof v[3], "asfloat(load32(a + 8u))");
        } else if (in->type != 0x02) {                /* FLOATn; NONE has nothing */
            for (k = 0; k < n && k < 4; k++)
                snprintf(v[k], sizeof v[k], "asfloat(load32(a + %uu))", 4 * k);
        }
        break;
    case 0x0:                                         /* D3DCOLOR: ARGB to r, g, b, a */
        snprintf(v[0], sizeof v[0], "(float)((load32(a) >> 16) & 0xFFu) / 255.0");
        snprintf(v[1], sizeof v[1], "(float)((load32(a) >> 8) & 0xFFu) / 255.0");
        snprintf(v[2], sizeof v[2], "(float)(load32(a) & 0xFFu) / 255.0");
        snprintf(v[3], sizeof v[3], "(float)(load32(a) >> 24) / 255.0");
        break;
    case 0x5:                                         /* SHORTn */
        for (k = 0; k < n && k < 4; k++)
            snprintf(v[k], sizeof v[k], "load16s(a + %uu)", 2 * k);
        break;
    case 0x1:                                         /* NORMSHORTn */
        for (k = 0; k < n && k < 4; k++)
            snprintf(v[k], sizeof v[k], "load16s(a + %uu) / 32767.0", 2 * k);
        break;
    case 0x6:                                         /* NORMPACKED3: 11, 11, 10 bits */
        snprintf(v[0], sizeof v[0], "(float)(asint(load32(a) << 21) >> 21) / 1023.0");
        snprintf(v[1], sizeof v[1], "(float)(asint(load32(a) << 10) >> 21) / 1023.0");
        snprintf(v[2], sizeof v[2], "(float)(asint(load32(a)) >> 22) / 511.0");
        break;
    case 0x4:                                         /* PBYTEn */
        for (k = 0; k < n && k < 4; k++)
            snprintf(v[k], sizeof v[k], "load8(a + %uu) / 255.0", k);
        break;
    }
    put(h, "    {\n        uint a = streams[%u].x + vertex * streams[%u].y + %uu;\n", in->stream, in->stream,
        in->offset);
    put(h, "        v%u = float4(%s, %s, %s, %s);\n    }\n", in->reg, v[0], v[1], v[2], v[3]);
}

/* Operand A (0), B (1) or C (2) of an instruction: a temporary (R12 is oPos), an input or a constant,
 * swizzled and negated. */
static void put_operand(Hlsl *h, const uint32_t *ins, int which)
{
    static const char xyzw[] = "xyzw";
    uint32_t neg, swz, mux, reg;

    if (which == 0) {
        neg = field(ins, 1, 8, 1); swz = field(ins, 1, 0, 8);
        mux = field(ins, 2, 26, 2); reg = field(ins, 2, 28, 4);
    } else if (which == 1) {
        neg = field(ins, 2, 25, 1); swz = field(ins, 2, 17, 8);
        mux = field(ins, 2, 11, 2); reg = field(ins, 2, 13, 4);
    } else {
        neg = field(ins, 2, 10, 1); swz = field(ins, 2, 2, 8);
        mux = field(ins, 3, 28, 2);
        reg = (field(ins, 2, 0, 2) << 2) | field(ins, 3, 30, 2);
    }
    put(h, "%s(", neg ? "-" : "");
    if (mux == 1) {
        if (reg == 12)
            put(h, "oPos");
        else
            put(h, "R%u", reg < 12 ? reg : 0u);      /* R13 to R15 read R0, as in the interpreter */
    } else if (mux == 2) {
        put(h, "v%u", field(ins, 1, 9, 4));
    } else {
        uint32_t index = field(ins, 1, 13, 8);

        if (field(ins, 3, 1, 1))
            put(h, "c[constant(%d + a0)]", (int)index);
        else
            put(h, "c[%u]", index < PROGRAM_CONSTANTS ? index : 0u);
    }
    put(h, ").%c%c%c%c", xyzw[(swz >> 6) & 3], xyzw[(swz >> 4) & 3], xyzw[(swz >> 2) & 3], xyzw[swz & 3]);
}

static const char *const s_mask[16] = {
    "", "w", "z", "zw", "y", "yw", "yz", "yzw", "x", "xw", "xz", "xzw", "xy", "xyw", "xyz", "xyzw"
};

/* The register a MAC or ILU result written to temporary `reg` lands in; NULL past R12, as the
 * interpreter drops those. */
static const char *temporary(uint32_t reg, char *name, size_t size)
{
    if (reg == 12)
        return "oPos";
    if (reg > 12)
        return NULL;
    snprintf(name, size, "R%u", reg);
    return name;
}

/* An output register, by its address: what the interpreter hands on, NULL for the rest (oPts, the back
 * colours, the two unused ones). */
static const char *output(uint32_t address)
{
    switch (address) {
    case 0:  return "oPos";
    case 3:  return "oD0";
    case 4:  return "oD1";
    case 5:  return "oFog";
    case 9:  return "oT0";
    case 10: return "oT1";
    case 11: return "oT2";
    case 12: return "oT3";
    }
    return NULL;
}

static void put_instruction(Hlsl *h, const uint32_t *ins, int slot)
{
    static const char *const mac_name[16] = {
        "nop", "mov", "mul", "add", "mad", "dp3", "dph", "dp4",
        "dst", "min", "max", "slt", "sge", "arl", "mac14", "mac15"
    };
    static const char *const ilu_name[8] = { "nop", "mov", "rcp", "rcc", "rsq", "exp", "log", "lit" };
    uint32_t mac = field(ins, 1, 21, 4), ilu = field(ins, 1, 25, 3);
    uint32_t mac_mask = field(ins, 3, 24, 4), ilu_mask = field(ins, 3, 16, 4), tdst = field(ins, 3, 20, 4);
    uint32_t omask = field(ins, 3, 12, 4), oaddr = field(ins, 3, 3, 8);
    char name[8];
    const char *to;

    put(h, "    { /* %d: %s %s */\n        precise float4 A = ", slot, mac_name[mac], ilu_name[ilu]);
    put_operand(h, ins, 0);
    put(h, ", B = ");
    put_operand(h, ins, 1);
    put(h, ", C = ");
    put_operand(h, ins, 2);
    put(h, ";\n        precise float4 m = ");
    /* The MAC: each product and sum rounded on its own, in the interpreter's order */
    switch (mac) {
    case 0:  put(h, "0.0"); break;
    case 2:  put(h, "A * B"); break;
    case 3:  put(h, "A + C"); break;
    case 4:  put(h, "A * B + C"); break;
    case 5:  put(h, "(A.x * B.x + A.y * B.y + A.z * B.z).xxxx"); break;
    case 6:  put(h, "(A.x * B.x + A.y * B.y + A.z * B.z + B.w).xxxx"); break;
    case 7:  put(h, "(A.x * B.x + A.y * B.y + A.z * B.z + A.w * B.w).xxxx"); break;
    case 8:  put(h, "float4(1.0, A.y * B.y, A.z, B.w)"); break;
    case 9:  put(h, "A < B ? A : B"); break;
    case 10: put(h, "A >= B ? A : B"); break;
    case 11: put(h, "(float4)(A < B)"); break;
    case 12: put(h, "(float4)(A >= B)"); break;
    default: put(h, "A"); break;                     /* mov; arl and the unknown ones hand A on */
    }
    put(h, ";\n        precise float4 i = ");
    switch (ilu) {
    case 0:  put(h, "0.0"); break;
    case 2:  put(h, "ilu_rcp(C.x)"); break;
    case 3:  put(h, "ilu_rcc(C.x)"); break;
    case 4:  put(h, "ilu_rsq(C.x)"); break;
    case 5:  put(h, "ilu_exp(C.x)"); break;
    case 6:  put(h, "ilu_log(C.x)"); break;
    case 7:  put(h, "ilu_lit(C)"); break;
    default: put(h, "C"); break;                     /* mov */
    }
    put(h, ";\n");
    if (mac == 13)
        put(h, "        a0 = (int)floor(A.x + 0.001);\n");
    if (mac && mac != 13 && mac_mask && (to = temporary(tdst, name, sizeof name)))
        put(h, "        %s.%s = m.%s;\n", to, s_mask[mac_mask], s_mask[mac_mask]);
    /* Paired with a MAC op, the ILU writes R1 whatever the field says */
    if (ilu && ilu_mask && (to = temporary(mac ? 1u : tdst, name, sizeof name)))
        put(h, "        %s.%s = i.%s;\n", to, s_mask[ilu_mask], s_mask[ilu_mask]);
    /* To an output; to a constant only with the context writes on, which the bridge never turns on */
    if (omask && field(ins, 3, 11, 1) && oaddr < 13 && (to = output(oaddr)))
        put(h, "        %s.%s = %s.%s;\n", to, s_mask[omask], field(ins, 3, 2, 1) ? "i" : "m", s_mask[omask]);
    put(h, "    }\n");
}

char *vertex_program_hlsl(const uint32_t (*program)[4], int slots, const VertexProgramInput *inputs, int count)
{
    Hlsl h;
    int end, s, k;

    for (end = 0; end < slots && !field(program[end], 3, 0, 1); end++)
        ;
    if (end == slots)
        return NULL;
    memset(&h, 0, sizeof h);
    h.size = 16384;
    h.text = (char *)malloc(h.size);
    if (!h.text)
        return NULL;
    h.text[0] = 0;
    put(&h, "%s", s_head);
    put(&h, "int constant(int index) { return (uint)index < %uu ? index : 0; }\n\n", PROGRAM_CONSTANTS);
    put(&h, "VS_OUT main(uint id : SV_VertexID)\n{\n    uint vertex = id - first.x;\n");
    for (k = 0; k < 16; k++)
        put(&h, "    precise float4 v%d = float4(0.0, 0.0, 0.0, 1.0);\n", k);
    for (k = 0; k < count; k++)
        if (inputs[k].reg < 16)
            put_fetch(&h, &inputs[k]);
    put(&h, "    int a0 = 0;\n");
    put(&h, "    precise float4 R0 = 0.0, R1 = 0.0, R2 = 0.0, R3 = 0.0, R4 = 0.0, R5 = 0.0;\n");
    put(&h, "    precise float4 R6 = 0.0, R7 = 0.0, R8 = 0.0, R9 = 0.0, R10 = 0.0, R11 = 0.0, oPos = 0.0;\n");
    put(&h, "    precise float4 oD0 = float4(0.0, 0.0, 0.0, 1.0), oD1 = float4(0.0, 0.0, 0.0, 1.0), oFog = 0.0;\n");
    put(&h, "    precise float4 oT0 = float4(0.0, 0.0, 0.0, 1.0), oT1 = float4(0.0, 0.0, 0.0, 1.0);\n");
    put(&h, "    precise float4 oT2 = float4(0.0, 0.0, 0.0, 1.0), oT3 = float4(0.0, 0.0, 0.0, 1.0);\n");
    for (s = 0; s <= end; s++)
        put_instruction(&h, program[s], s);
    put(&h, "    return finish(oPos, oD0, oD1, oFog, oT0, oT1, oT2, oT3);\n}\n");
    if (h.failed) {
        free(h.text);
        return NULL;
    }
    return h.text;
}
