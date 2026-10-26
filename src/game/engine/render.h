/**
 *    Name:        engine/render.h
 *    Description: the engine's renderer (render.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A state is the XDK's D3DRS or D3DTSS number. symbols.txt says what each function does.
 */
#ifndef ENGINE_RENDER_H
#define ENGINE_RENDER_H

#include <stdint.h>

void vcRenderSetState(int32_t state, uint32_t value);
void vcRenderSetTextureStageState(uint32_t stage, int32_t state, uint32_t value);

#endif
