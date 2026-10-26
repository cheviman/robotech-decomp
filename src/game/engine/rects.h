/**
 *    Name:        engine/rects.h
 *    Description: the engine's rectangles (rects.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A rectangle is the guest address of a vcRect. symbols.txt says what each function does.
 */
#ifndef ENGINE_RECTS_H
#define ENGINE_RECTS_H

#include <stdint.h>

int32_t vcRectSet(uint32_t rect, int32_t left, int32_t top, int32_t right, int32_t bottom);
int32_t vcRectCopy(uint32_t to, uint32_t from);
int32_t vcRectInflate(uint32_t rect, int32_t across, int32_t down);
int32_t vcRectOffset(uint32_t rect, int32_t across, int32_t down);
void vcFileReadRect(uint32_t file, uint32_t rect);
void vcRectPlace(uint32_t rect, uint32_t flags);
void vcScreenRectReset(void);

#endif
