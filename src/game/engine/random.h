/**
 *    Name:        engine/random.h
 *    Description: the engine's random numbers (random.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The floats are the x87's (a double the precision of the control word rounded, decomp.h).
 */
#ifndef ENGINE_RANDOM_H
#define ENGINE_RANDOM_H

#include <stdint.h>

uint32_t vcRandom(void);
double vcRandomUnit(void);
double vcRandomSpread(void);
uint32_t vcRandomCosmetic(void);
double vcRandomCosmeticUnit(void);
double vcRandomCosmeticSpread(void);
void vcRandomReset(void);

#endif
