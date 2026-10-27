/**
 *    Name:        x86.h
 *    Description: what the decompiled C (tools/decompile.py) calls for the x86's own arithmetic: shifts
 *                 by a count the processor masks, the flags of an addition or a subtraction, the string
 *                 instructions, the 64-bit divisions
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Each does what the Pentium III does: a shift's count is taken modulo 32 (64 for a 64-bit value), a
 *    string instruction walks upwards (the game never sets the direction flag) a unit at a time, as the
 *    processor does, so a copy over itself goes as the original's; DIV and IDIV divide EDX:EAX. The
 *    guest's memory is the recompiled code's (MEM8, XBOX_PTR: recomp_types.h).
 */
#ifndef DECOMPILED_X86_H
#define DECOMPILED_X86_H

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

/* A jump through a table to an entry it does not have: the game's guard before each table keeps it from
 * happening. */
static inline void invalid_jump(uint32_t value)
{
    fprintf(stderr, "a jump through a table to an entry it does not have: %u\n", value);
    abort();
}

#endif
