/**
 *    Name:        engine/random.c
 *    Description: the engine's random numbers, written in C: two sequences, each a hash of a seed and a count
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A draw hashes the sequence's seed and its count, which goes one on: the same seed and count give the
 *    same number, so restarting the count replays the draws. vcRandomReset sets both seeds and restarts
 *    the game's sequence; the cosmetic one, which what the game shows draws from and its play does not
 *    (the pad's rumble, the string manager, line effects, nodes, screens), keeps counting.
 *
 *    The floats are worked on the x87, as the original: each operation rounded to the control word's
 *    precision (decomp.h), and handed back in st(0).
 */
#include "decomp.h"
#include "random.h"

#define SEED_GAME           0x71FBu     /* vcRandomReset's seeds */
#define SEED_COSMETIC       0x23DBu
#define TWO_TO_32           4294967296.0f
/* the float just below 2^-32 and 2^-31, so that a draw times it stays below 1 and 2 */
#define UNIT_SCALE          0x2F7FFFFDu
#define SPREAD_SCALE        0x2FFFFFFDu

/* The hash of the seed and the count, which counts on. */
static uint32_t draw(uint32_t seed, uint32_t count_va)
{
    uint32_t count = MEM32(count_va), hash = (seed + count) * 0x3Bu + seed;

    MEM32(count_va) = count + 1;
    hash ^= hash << 13;
    return vcRandomDividend / (((count + 1) & 0xFFFFEu) | 1u)
         + (vcRandomCubeFactor * hash * hash + vcRandomLinearFactor) * hash;
}

/* A draw as the x87 loads it, unsigned, times a scale. */
static double scaled(uint32_t drawn, uint32_t scale_bits)
{
    double x = (double)(int32_t)drawn;

    if ((int32_t)drawn < 0)
        x = RECOMP_FP_PC(x + TWO_TO_32);
    return RECOMP_FP_PC(x * float_from_bits(scale_bits));
}

uint32_t vcRandom(void)
{
    return draw(vcRandomSeed, vcRandomCount_VA);
}
ENTRY_CDECL0(vcRandom)

/* In [0, 1). */
double vcRandomUnit(void)
{
    return scaled(draw(vcRandomSeed, vcRandomCount_VA), UNIT_SCALE);
}
ENTRY_CDECL0_FLOAT(vcRandomUnit)

/* In (-1, 1]. */
double vcRandomSpread(void)
{
    return RECOMP_FP_PC(1.0f - scaled(draw(vcRandomSeed, vcRandomCount_VA), SPREAD_SCALE));
}
ENTRY_CDECL0_FLOAT(vcRandomSpread)

uint32_t vcRandomCosmetic(void)
{
    return draw(vcRandomCosmeticSeed, vcRandomCosmeticCount_VA);
}
ENTRY_CDECL0(vcRandomCosmetic)

double vcRandomCosmeticUnit(void)
{
    return scaled(draw(vcRandomCosmeticSeed, vcRandomCosmeticCount_VA), UNIT_SCALE);
}
ENTRY_CDECL0_FLOAT(vcRandomCosmeticUnit)

double vcRandomCosmeticSpread(void)
{
    return RECOMP_FP_PC(1.0f - scaled(draw(vcRandomCosmeticSeed, vcRandomCosmeticCount_VA), SPREAD_SCALE));
}
ENTRY_CDECL0_FLOAT(vcRandomCosmeticSpread)

void vcRandomReset(void)
{
    vcRandomSeed = SEED_GAME;
    vcRandomCosmeticSeed = SEED_COSMETIC;
    vcRandomCount = 0;
}
ENTRY_CDECL0_VOID(vcRandomReset)
