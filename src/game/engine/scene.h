/**
 *    Name:        engine/scene.h
 *    Description: the engine's scene objects (scene.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    An object is its handle; a vcSceneObject, an out buffer or a table is a guest address. symbols.txt
 *    says what each function does.
 */
#ifndef ENGINE_SCENE_H
#define ENGINE_SCENE_H

#include <stdint.h>

void vcSceneInit(void);
void vcSceneShutdown(void);
void vcSceneObjectRegisterType(uint32_t type, uint32_t functions);
uint32_t vcSceneObjectGet(uint32_t handle);
uint32_t vcSceneObjectGetFlags(uint32_t handle);
void vcSceneObjectSetFlags(uint32_t handle, uint32_t flags);
void vcSceneObjectChangeFlags(uint32_t handle, uint32_t set, uint32_t clear);
void vcSceneObjectSetUser(uint32_t handle, uint32_t user);
uint32_t vcSceneObjectGetUser(uint32_t handle);
void vcSceneObjectInheritFlags(uint32_t parent_flags, uint32_t object, uint32_t handle);
void vcSceneObjectPassFlags(uint32_t handle, uint32_t object);
void vcSceneObjectUnlink(uint32_t parent_object, uint32_t object, uint32_t handle);
void vcSceneObjectLink(uint32_t object, uint32_t handle, uint32_t parent, uint32_t parent_object);
void vcSceneObjectReleaseChildren(uint32_t object);
void vcSceneObjectAttach(uint32_t handle, uint32_t parent, int32_t slot);
void vcSceneObjectRemove(uint32_t handle, uint32_t object);
void vcBoxCenter(uint32_t box, uint32_t centre);
void vcSceneObjectReadTransform(uint32_t object, uint32_t rotation, uint32_t position);
void vcSceneObjectInsertBounds(uint32_t object, uint32_t rotation, uint32_t position);
void vcSceneObjectFlagsChanged(uint32_t object, uint32_t handle, uint32_t after, uint32_t before);
void vcSceneObjectGetTransform(uint32_t handle, uint32_t rotation, uint32_t position);
void vcSceneObjectGetBounds(uint32_t handle, uint32_t corners);
void vcSceneObjectInit(uint32_t handle, uint32_t object, uint32_t flags);
void vcSceneObjectCopy(uint32_t handle, uint32_t from);

#endif
