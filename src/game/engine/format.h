/**
 *    Name:        engine/format.h
 *    Description: the engine's formatted strings (format.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    vcFormat and vcFormatAppend take their arguments on the guest stack: call their entries,
 *    CALL(vcFormat_entry, format, ...). A string is a guest address.
 */
#ifndef ENGINE_FORMAT_H
#define ENGINE_FORMAT_H

#include <stdint.h>

uint32_t vcFormat(uint32_t format, uint32_t args);
uint32_t vcFormatAppend(uint32_t format, uint32_t args);
uint32_t vcFormatLast(void);
uint32_t vcFormatClear(void);
void vcStrLower(uint32_t s);

#endif
