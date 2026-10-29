/**
 *    Name:        vertex_program_hlsl.h
 *    Description: the game's vertex programs (NV2A microcode) as HLSL for shader model 5, for the Direct3D 11
 *                 bridge to run them on the GPU
 *    Version:     0.1.0
 *    Created:     29-10-2026
 *    Modified:    29-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The shader computes what the bridge's CPU path hands the layer for a vertex (d3d11_bridge.c,
 *    vprog_transform) and what the layer's vertex shader makes of it, so the layer's pixel shader takes
 *    its output as it takes its own (vertex_program_hlsl.c).
 */
#ifndef VERTEX_PROGRAM_HLSL_H
#define VERTEX_PROGRAM_HLSL_H

#include <stddef.h>
#include <stdint.h>

/* One input of a program, as its declaration has it: the v register, the D3DVSDT type, the stream and
 * the byte offset in that stream's vertex. */
typedef struct {
    uint8_t reg, type, stream, offset;
} VertexProgramInput;

/* The constant buffer each draw fills (b1), as the shader declares it. */
typedef struct {
    float viewport[4];          /* X, Y, Width, Height */
    float depth[4];             /* MinZ, MaxZ; the scale from the back buffer to the target drawn to, x and y */
    float screen[4];            /* the back buffer's width and height */
    float texture_size[4][4];   /* each stage's linear texture: width, height */
    uint32_t texture_set[4];    /* the coordinate set each stage divides by its texture's size; 4: none */
    uint32_t first[4];          /* the SV_VertexID the streams' first vertex has */
    uint32_t streams[16][4];    /* each stream: where its first vertex is in the buffer, its stride */
} VertexProgramDraw;

/* The HLSL of the program that starts at program[0] (four DWORDs an instruction, `slots` of them at
 * most) and ends at the first instruction marked final, reading `count` inputs. A string to free, or
 * NULL when no instruction is final: the interpreter runs nothing then either. */
char *vertex_program_hlsl(const uint32_t (*program)[4], int slots, const VertexProgramInput *inputs, int count);

#endif
