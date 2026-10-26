/**
 *    Name:        engine/vector.c
 *    Description: the engine's vector maths, written in C: a point turned and moved
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A vector is three floats, a rotation nine (three rows), each the guest address of the first. The floats are worked on the x87, as the original:
 *    each operation rounded to the control word's precision (decomp.h), the three of a vector worked
 *    out before any is stored, so an output that is also an input reads the old values.
 */
#include "decomp.h"
#include "vector.h"

static volatile float *floats(uint32_t va)
{
    return (volatile float *)XBOX_PTR(va);
}

/* Each row's products are added from the last: row[0] p[0] + (row[1] p[1] + row[2] p[2]), then the
 * position. */
uint32_t vcTransformPoint(uint32_t out, uint32_t rotation, uint32_t point, uint32_t position)
{
    volatile float *row = floats(rotation), *p = floats(point), *at = floats(position), *o = floats(out);
    double result[3];
    int i;

    for (i = 0; i < 3; i++) {
        double first = RECOMP_FP_PC((double)row[i * 3] * p[0]);
        double second = RECOMP_FP_PC((double)row[i * 3 + 1] * p[1]);
        double third = RECOMP_FP_PC((double)row[i * 3 + 2] * p[2]);

        result[i] = RECOMP_FP_PC(RECOMP_FP_PC(first + RECOMP_FP_PC(second + third)) + at[i]);
    }
    for (i = 0; i < 3; i++)
        o[i] = (float)result[i];
    return out;
}
ENTRY_CDECL4(vcTransformPoint)
