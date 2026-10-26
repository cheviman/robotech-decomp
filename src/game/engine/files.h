/**
 *    Name:        engine/files.h
 *    Description: the engine's files (files.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A file is the guest address of a vcFile; the places read into are guest addresses. symbols.txt says
 *    what each function does.
 */
#ifndef ENGINE_FILES_H
#define ENGINE_FILES_H

#include <stdint.h>

int32_t vcFileFill(uint32_t file);
int32_t vcFileCreate(uint32_t file, uint32_t name);
int32_t vcFileOpen(uint32_t file, uint32_t name);
int32_t vcFileClose(uint32_t file);
int32_t vcFileExists(uint32_t name);

uint32_t vcFileRead(uint32_t file, uint32_t to, uint32_t bytes);
int32_t vcFileReadIfOpen(uint32_t file, uint32_t to, uint32_t bytes);
int32_t vcFileReadBytes(uint32_t file, uint32_t to, uint32_t bytes);
int32_t vcFileReadU16(uint32_t file, uint32_t to);
int32_t vcFileReadU32(uint32_t file, uint32_t to);
int32_t vcFileReadU16s(uint32_t file, uint32_t to, uint32_t count);
int32_t vcFileReadU32s(uint32_t file, uint32_t to, uint32_t count);

uint32_t vcFileTell(uint32_t file);
int32_t vcFileSeek(uint32_t file, uint32_t to);
int32_t vcFileSkip(uint32_t file, uint32_t bytes);

uint32_t vcFileAddObject(uint32_t file, uint32_t handle);
void vcFileFreeObjects(uint32_t file);

#endif
