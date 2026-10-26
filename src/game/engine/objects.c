/**
 *    Name:        engine/objects.c
 *    Description: the engine's object system, written in C: so far its default callbacks
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The rest of the object system (vcRegisterClass, vcObjectCreate, vcObjectRelease, vcObjectClone,
 *    vcObjectLoad) is still recompiled, in src/recomp/gen/engine/objects.c. The callbacks below are what a
 *    class gives for a slot it has nothing to do with; the object system calls them through the class
 *    tables, never by name.
 */
#include "decomp.h"

/* What a class gives for a callback that has nothing to do: hands back 0. */
void vcDefault_ReturnZero(void)
{
    RETURN_CDECL(0);
}

/* What a class gives for a callback that only has to succeed: hands back 1. */
void vcDefault_ReturnOne(void)
{
    RETURN_CDECL(1);
}

/* The default of the callback the object system runs over an object's
 * children: hands back the flags it was given, its third argument. */
void vcDefault_ReturnArg3(void)
{
    RETURN_CDECL(ARG32(2));
}
