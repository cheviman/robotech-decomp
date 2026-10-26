/**
 *    Name:        engine/vector.h
 *    Description: the engine's vector maths (vector.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A vector or a rotation is the guest address of its floats. symbols.txt says what each
 *    function does.
 */
#ifndef ENGINE_VECTOR_H
#define ENGINE_VECTOR_H

#include <stdint.h>

uint32_t vcTransformPoint(uint32_t out, uint32_t rotation, uint32_t point, uint32_t position);

#endif
