/**
 *    Name:        engine/objects.h
 *    Description: the engine's object system (objects.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A handle is (type << 16) | index; a guest pointer is a guest address (uint32_t). symbols.txt says
 *    what each function does.
 */
#ifndef ENGINE_OBJECTS_H
#define ENGINE_OBJECTS_H

#include <stdint.h>

/* classes */
void vcObjectSystemInit(uint32_t data_dir);
void vcObjectSystemShutdown(void);
uint32_t vcGetDataDir(void);
uint32_t vcGetPlatformName(void);
void vcRegisterClass(uint32_t desc, int32_t capacity);
void vcClassFindFreeInstance(uint32_t cls);
int32_t vcClassForEach(uint32_t type, uint32_t callback, int32_t max, uint32_t user);
void vcClassAddRefAll(uint32_t type);
void vcClassDecRefAll(uint32_t type);

/* objects */
uint32_t vcObjectCreate(uint32_t type);
uint32_t vcObjectAddRef(uint32_t handle);
uint32_t vcObjectRelease(uint32_t handle);
uint32_t vcObjectClone(uint32_t handle);
uint32_t vcObjectGetSize(uint32_t handle, uint32_t what);
void vcObjectMarkChanged(uint32_t handle);
void vcObjectClearChanged(uint32_t handle);
int32_t vcObjectCollectChanged(uint32_t handle, uint32_t list);

/* names */
uint32_t vcObjectGetName(uint32_t handle);
int32_t vcObjectSetName(uint32_t handle, uint32_t name);
uint32_t vcObjectFind(uint32_t type, uint32_t name, uint32_t from);
uint32_t vcObjectGetShared(uint32_t type, uint32_t name);

/* the release queue */
void vcObjectReleaseLater(uint32_t handle, uint32_t check);
void vcObjectReleaseQueued(void);

/* files */
uint32_t vcObjectGet(uint32_t type, uint32_t name);
uint32_t vcObjectLoad(uint32_t file);
uint32_t vcObjectReload(uint32_t file, uint32_t handle);
int32_t vcObjectLoadChunk(uint32_t file, uint32_t handle);

/* the classes' defaults */
uint32_t vcDefault_ReturnZero(void);
uint32_t vcDefault_ReturnOne(void);
uint32_t vcDefault_ReturnArg3(uint32_t handle, uint32_t object, uint32_t changed);

#endif
