/**
 *    Name:        x86.h
 *    Description: what the decompiled C (tools/decompile.py) calls for the x86's own arithmetic: shifts
 *                 by a count the processor masks, the flags of an addition or a subtraction, the string
 *                 instructions, the 64-bit divisions, the calls of functions that stay recompiled
 *    Version:     0.3.0
 *    Created:     26-10-2026
 *    Modified:    28-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Each does what the Pentium III does: a shift's count is taken modulo 32 (64 for a 64-bit value), a
 *    string instruction walks upwards (the game never sets the direction flag) a unit at a time, as the
 *    processor does, so a copy over itself goes as the original's; DIV and IDIV divide EDX:EAX. The
 *    guest's memory is the recompiled code's (MEM8, XBOX_PTR: recomp_types.h).
 */
#ifndef DECOMPILED_X86_H
#define DECOMPILED_X86_H

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "recomp_types.h"

/* ── Shifts by a count the processor masks ────────────────────────────────────────────────────────── */

static inline uint32_t shl32(uint32_t value, int count)
{
    return value << (count & 31);
}

static inline uint32_t shr32(uint32_t value, int count)
{
    return value >> (count & 31);
}

static inline int32_t sar32(int32_t value, int count)
{
    return value >> (count & 31);
}

static inline uint64_t shl64(uint64_t value, int count)
{
    return value << (count & 63);
}

static inline uint64_t shr64(uint64_t value, int count)
{
    return value >> (count & 63);
}

/* ── The flags of an addition or a subtraction (with a carry or borrow in) ───────────────────────── */

#define X86_FLAGS(bits, type)                                                                              \
    static inline uint32_t x86_carry_add##bits(uint32_t a, uint32_t b, uint32_t carry)                     \
    {                                                                                                      \
        return (uint32_t)(((uint64_t)(type)a + (type)b + carry) >> (bits));                                \
    }                                                                                                      \
    static inline uint32_t x86_overflow_add##bits(uint32_t a, uint32_t b, uint32_t carry)                  \
    {                                                                                                      \
        type result = (type)((type)a + (type)b + (type)carry);                                             \
        return (uint32_t)(((~((type)a ^ (type)b) & ((type)a ^ result)) >> ((bits) - 1)) & 1u);             \
    }                                                                                                      \
    static inline uint32_t x86_carry_sub##bits(uint32_t a, uint32_t b, uint32_t borrow)                   \
    {                                                                                                      \
        return (uint64_t)(type)a < (uint64_t)(type)b + borrow;                                             \
    }                                                                                                      \
    static inline uint32_t x86_overflow_sub##bits(uint32_t a, uint32_t b, uint32_t borrow)                 \
    {                                                                                                      \
        type result = (type)((type)a - (type)b - (type)borrow);                                            \
        return (uint32_t)(((((type)a ^ (type)b) & ((type)a ^ result)) >> ((bits) - 1)) & 1u);             \
    }

X86_FLAGS(8, uint8_t)
X86_FLAGS(16, uint16_t)
X86_FLAGS(32, uint32_t)

/* ── The string instructions, REP: count units from the guest's address up ───────────────────────── */

static inline void x86_rep_stos8(uint32_t to, uint32_t value, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM8(to + n) = (uint8_t)value;
}

static inline void x86_rep_stos16(uint32_t to, uint32_t value, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM16(to + 2u * n) = (uint16_t)value;
}

static inline void x86_rep_stos32(uint32_t to, uint32_t value, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM32(to + 4u * n) = value;
}

static inline void x86_rep_movs8(uint32_t to, uint32_t from, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM8(to + n) = MEM8(from + n);
}

static inline void x86_rep_movs16(uint32_t to, uint32_t from, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM16(to + 2u * n) = MEM16(from + 2u * n);
}

static inline void x86_rep_movs32(uint32_t to, uint32_t from, uint32_t count)
{
    for (uint32_t n = 0; n < count; n++)
        MEM32(to + 4u * n) = MEM32(from + 4u * n);
}

/* ── DIV and IDIV: EDX:EAX by a 32-bit value ─────────────────────────────────────────────────────── */

static inline uint32_t x86_udiv64(uint32_t high, uint32_t low, uint32_t divisor)
{
    return (uint32_t)((((uint64_t)high << 32) | low) / divisor);
}

static inline uint32_t x86_urem64(uint32_t high, uint32_t low, uint32_t divisor)
{
    return (uint32_t)((((uint64_t)high << 32) | low) % divisor);
}

static inline uint32_t x86_sdiv64(uint32_t high, uint32_t low, uint32_t divisor)
{
    return (uint32_t)(int32_t)((int64_t)(((uint64_t)high << 32) | low) / (int32_t)divisor);
}

static inline uint32_t x86_srem64(uint32_t high, uint32_t low, uint32_t divisor)
{
    return (uint32_t)(int32_t)((int64_t)(((uint64_t)high << 32) | low) % (int32_t)divisor);
}

/* ── A call of a function that stays recompiled ──────────────────────────────────────────────────── */

/* As the recompiled code calls it: its 'count' arguments on the guest's stack as the original pushes
 * them, the return address the original's call pushes over them, SP back where it was afterwards (the
 * function drops what it drops, the caller the rest). The registers it reads are in the globals already;
 * what it hands back in EAX is the value. */
static inline uint32_t x86_call(void (*function)(void), uint32_t return_address, int count, ...)
{
    uint32_t sp = g_esp;
    va_list arguments;
    va_start(arguments, count);
    g_esp -= 4u * (uint32_t)count;
    for (int n = 0; n < count; n++)
        MEM32(g_esp + 4u * (uint32_t)n) = va_arg(arguments, uint32_t);
    va_end(arguments);
    g_esp -= 4u;
    MEM32(g_esp) = return_address;
    function();
    g_esp = sp;
    return g_eax;
}

/* A jump to a function that stays recompiled from one whose stack stays in memory: it runs on the
 * caller's frame as the original's jump has it, its arguments and return address where the caller's are,
 * and SP is put back after. */
static inline uint32_t x86_jump(void (*function)(void))
{
    uint32_t sp = g_esp;
    function();
    g_esp = sp;
    return g_eax;
}

/* A jump through a table to an entry it does not have: the game's guard before each table keeps it from
 * happening. */
static inline void invalid_jump(uint32_t value)
{
    fprintf(stderr, "a jump through a table to an entry it does not have: %u\n", value);
    abort();
}

/* ── The x87's floating point (tools/x86/x87.py, tools/core/decompiler/floats.py) ─────────────────── */

/* The x87's registers are doubles in the C, as in the recompiled code (recomp_types.h). A float is made one
 * as FLD makes it (FLOAT_AT); each operation is rounded as the control word's precision says (x87_round:
 * at 24 bits, a float's precision with the exponent kept, which a float's range does not have; the game
 * also runs at 53, a double's); a value becomes a float where memory holds one. What C has no operator
 * for is the x87's own, as the recompiled code works it out: its trigonometry, its conversions to
 * integers, its status word. */

/* An arithmetic result as the x87 rounds it, under the control word's precision. */
static inline double x87_round(double value)
{
    return RECOMP_FP_PC(value);
}

/* A float's bits as FLD loads them: a double, a signaling NaN made quiet (so a float loaded and stored
 * again is not always a copy of its bits). */
static inline double x87_float(uint32_t bits)
{
    if ((bits & 0x7F800000u) == 0x7F800000u && (bits & 0x007FFFFFu) != 0u)
        bits |= 0x00400000u;
    return (double)float_from_bits(bits);
}

/* The float at a guest address, as FLD loads it. */
#define FLOAT_AT(address) x87_float(MEM32(address))

/* A 64-bit integer at a guest address, as FILD and FISTP load and store it whole. */
#define MEM64(address) (*(volatile uint64_t *)XBOX_PTR(address))

/* The float a function that stays recompiled hands back in st(0), taken off the recompiled code's stack:
 * read or not, as the original's caller pops it. */
static inline double x87_pop(void)
{
    double value = g_fp_stack[g_fp_top & 7];

    g_fp_top = (g_fp_top + 1) & 7;
    return value;
}

/* The float a decompiled function hands back to the recompiled code that calls it, onto its stack: st(0),
 * where the original leaves it. */
static inline void x87_push(double value)
{
    g_fp_top = (g_fp_top + 7) & 7;
    g_fp_stack[g_fp_top] = value;
}

static inline double double_from_bits(uint64_t bits)
{
    double d;

    memcpy(&d, &bits, 8);
    return d;
}

static inline uint64_t double_to_bits(double d)
{
    uint64_t bits;

    memcpy(&bits, &d, 8);
    return bits;
}

/* True when a or b is a NaN: a compare's unordered outcome. */
static inline int x87_unordered(double a, double b)
{
    return a != a || b != b;
}

/* FSIN and FCOS: past 2^63 the x87 leaves the value as it was. */
static inline double x87_sin(double value)
{
    return recomp_fp_trig_in_range(value) ? recomp_x87_sin(value) : value;
}

static inline double x87_cos(double value)
{
    return recomp_fp_trig_in_range(value) ? recomp_x87_cos(value) : value;
}

/* FIST(P): rounded as the control word says (to nearest, the game's), the integer indefinite past range. */
static inline uint64_t x87_fist(double value, uint32_t bits)
{
    return (uint64_t)recomp_fist(value, g_fp_control_word, bits);
}

/* The C runtime's _ftol2, which C's (int) of a float calls: the value rounded to nearest by FISTP, then
 * one back toward 0 when the rounding went past it, as the float of the difference's sign says; 0 and the
 * integer indefinite as FISTP gives them. EDX:EAX. */
static inline uint64_t x87_ftol(double value)
{
    int64_t n = recomp_fist(value, g_fp_control_word, 64);
    uint32_t sign = float_to_bits((float)value), difference;

    if ((uint32_t)n == 0u && ((uint64_t)n >> 32 & 0x7FFFFFFFu) == 0u)
        return (uint64_t)n;
    difference = float_to_bits((float)RECOMP_FP_PC(value - (double)n));
    if (!(sign & 0x80000000u)) {
        if (difference > 0x80000000u)
            n -= 1;
    } else if ((difference ^ 0x80000000u) > 0x80000000u) {
        n += 1;
    }
    return (uint64_t)n;
}

/* FNSTSW AX after a compare of a with b, with 'depth' values on the stack: TOP in bits 11-13 (the stack the
 * recompiled code keeps does not move while the decompiled C works), C3 C2 C0 as the outcome sets them. */
static inline uint64_t x87_status(double a, double b, uint32_t depth)
{
    return (((uint32_t)(g_fp_top - (int)depth) & 7u) << 11) | RECOMP_FCMP_CC(RECOMP_FCMP(a, b));
}

#endif
