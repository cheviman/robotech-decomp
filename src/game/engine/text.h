/**
 *    Name:        engine/text.h
 *    Description: the engine's text (text.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A string is the guest address of its characters; a coordinate, a height or a scale is a float's
 *    bits, and a width or a height handed back is the x87's double. symbols.txt says what each function
 *    does.
 */
#ifndef ENGINE_TEXT_H
#define ENGINE_TEXT_H

#include <stdint.h>

void vcTextInit(void);
void vcTextShutdown(void);
double vcTextSetSize(uint32_t size);
double vcTextGetSize(void);
uint32_t vcTextSetFont(uint32_t font);
double vcTextWidthN(uint32_t text, uint32_t length);
double vcTextWidth(uint32_t text);
double vcTextSetScale(uint32_t scale);
void vcTextDraw(uint32_t x, uint32_t y, uint32_t color, uint32_t text);
void vcTextSetShadowColor(uint32_t color);
void vcTextSetShadowOffset(uint32_t x, uint32_t y);
void vcTextDrawAligned(uint32_t x, uint32_t y, uint32_t color, uint32_t text, uint32_t flags);
int32_t vcTextDrawInRect(uint32_t rect, uint32_t color, uint32_t text, uint32_t flags, uint32_t indent);

#endif
