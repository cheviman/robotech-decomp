/**
 *    Name:        engine/screen.h
 *    Description: the engine's screen (screen.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A rectangle is the guest address of a vcRect; a depth is a float's bits. symbols.txt says what each
 *    function does.
 */
#ifndef ENGINE_SCREEN_H
#define ENGINE_SCREEN_H

#include <stdint.h>

void vcScreenSafeAreaInit(uint32_t width, uint32_t height, uint32_t video_flags);
int32_t vcScreenGetRect(uint32_t rect);
void vcScreenInit(void);
void vcScreenShutdown(void);
void vcScreenOpen(uint32_t width, uint32_t height, uint32_t bits, uint32_t flag);
void vcScreenSetViewport(uint32_t rect);
void vcScreenClear(uint32_t rect, uint32_t clear_color, uint32_t color, uint32_t clear_depth, uint32_t depth);
void vcScreenClearDepth(uint32_t rect, uint32_t depth);
void vcScreenShow(uint32_t flags);

#endif
