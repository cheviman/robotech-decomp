/**
 *    Name:        engine/scene.c
 *    Description: the engine's scene objects, written in C: the scene's quadtrees, finding an object's
 *                 vcSceneObject, its flags, user, transform and bounds, the tree of parents and children
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Every object placed in the world has a vcSceneObject: where it is (its rotation and position in the
 *    world, and in its parent's frame), its bounding boxes, the flags of what it takes part in, and its
 *    place in a tree of parents and children, by handles. The object's type registers, besides its
 *    class, a table of functions for it (vcSceneObjectTypes); its get function finds the vcSceneObject
 *    of a handle, wherever the type keeps it. Two quadtrees hold the objects by their boxes: one by their
 *    bounds, the other by their hit bounds, which the scene's queries (a ray, a line) go through.
 *
 *    The tree is by handles: a parent holds a reference to each child. Three functions of it take
 *    their arguments in registers (ENTRY_REGISTERS_VOID), as the compiler passed them. A change of flags
 *    puts an object in a quadtree or takes it out, as a sphere around its box. Still recompiled: the
 *    types' functions, the quadtrees themselves, placing an object in its parent's frame, putting it in
 *    the hit tree (with a radius under a ten-thousandth the original moves its entry to a centre it
 *    never worked out, whatever its stack held, which C cannot hold the same) and what entering and
 *    leaving the bounds tree does besides.
 */
#include <float.h>
#include <math.h>

#include "decomp.h"
#include "objects.h"
#include "scene.h"
#include "vector.h"

#define TYPE_OF(handle)         ((uint32_t)(handle) >> 16)
#define NO_SLOT                 -1

/* The scene's quadtrees */
#define BOUNDS_TREE_LEVELS      6
#define HIT_TREE_LEVELS         7
#define TREE_ENTRIES            0x800
#define WORLD_SIZE              16000.0f
#define WORLD_FRAME             0x10u       /* vcSceneInit's local: the world's centre and size */

/* vcSceneObjectInsertBounds's locals, in the guest's stack at the original's offsets: the box's centre
 * moved into the world, and the box's centre */
#define INSERT_FRAME            0x24u
#define INSERT_WORLD_CENTRE     0x0Cu
#define INSERT_CENTRE           0x18u
#define LEAST_RADIUS            0.0001f     /* a smaller sphere stays out of a quadtree */
/* vcSceneObjectFlagsChanged's: the object's position and rotation, copied */
#define CHANGE_FRAME            0x30u
#define CHANGE_POSITION         0x00u
#define CHANGE_ROTATION         0x0Cu

/* vcSceneObject flags */
#define OUT_OF_BOUNDS_TREE      0x00004u
#define OUT_OF_HIT_TREE         0x00010u
#define KEEPS_OWN               0x1F000u    /* the ones a child keeps against its parent's */
#define KEEPS_OWN_HIT_TREE      0x01000u    /* and these say it keeps its own 0x10, 4 */
#define KEEPS_OWN_BOUNDS_TREE   0x02000u

/* ── The scene ───────────────────────────────────────────────────────────────────────────────────── */

void vcSceneInit(void)
{
    uint32_t world = FRAME_TAKE(WORLD_FRAME);
    volatile float *centre_and_size = (volatile float *)XBOX_PTR(world);

    guest_zero(vcSceneObjectTypes_VA, 64 * vcSceneObjectType_SIZE);
    centre_and_size[0] = centre_and_size[1] = centre_and_size[2] = 0.0f;
    centre_and_size[3] = WORLD_SIZE;
    vcSceneBoundsTree = CALL(vcQuadtreeCreate, BOUNDS_TREE_LEVELS, world, TREE_ENTRIES);
    centre_and_size[3] = WORLD_SIZE;
    vcSceneHitTree = CALL(vcQuadtreeCreate, HIT_TREE_LEVELS, world, TREE_ENTRIES);
    FRAME_GIVE(WORLD_FRAME);
}
ENTRY_CDECL0_VOID(vcSceneInit)

void vcSceneShutdown(void)
{
    CALL(vcQuadtreeDestroy, vcSceneBoundsTree);
    CALL(vcQuadtreeDestroy, vcSceneHitTree);
    vcSceneBoundsTree = 0;
    vcSceneHitTree = 0;
}
ENTRY_CDECL0_VOID(vcSceneShutdown)

/* ── The types ───────────────────────────────────────────────────────────────────────────────────── */

void vcSceneObjectRegisterType(uint32_t type, uint32_t functions)
{
    guest_copy(vcSceneObjectTypes_VA + type * vcSceneObjectType_SIZE, functions, vcSceneObjectType_SIZE);
}
ENTRY_CDECL2_VOID(vcSceneObjectRegisterType)

uint32_t vcSceneObjectGet(uint32_t handle)
{
    uint32_t type = vcSceneObjectTypes_VA + TYPE_OF(handle) * vcSceneObjectType_SIZE;

    return CALL_AT(vcSceneObjectType_get(type), handle);
}
ENTRY_CDECL1(vcSceneObjectGet)

/* ── Flags and user ──────────────────────────────────────────────────────────────────────────────── */

uint32_t vcSceneObjectGetFlags(uint32_t handle)
{
    return vcSceneObject_flags(vcSceneObjectGet(handle));
}
ENTRY_CDECL1(vcSceneObjectGetFlags)

void vcSceneObjectSetFlags(uint32_t handle, uint32_t flags)
{
    uint32_t object = vcSceneObjectGet(handle), before = vcSceneObject_flags(object);

    if (before == flags)
        return;
    vcSceneObject_flags(object) = flags;
    vcSceneObjectFlagsChanged(object, handle, flags, before);
}
ENTRY_CDECL2_VOID(vcSceneObjectSetFlags)

void vcSceneObjectChangeFlags(uint32_t handle, uint32_t set, uint32_t clear)
{
    uint32_t object = vcSceneObjectGet(handle), before = vcSceneObject_flags(object);
    uint32_t after = (before | set) & ~clear;

    if (before == after)
        return;
    vcSceneObject_flags(object) = after;
    vcSceneObjectFlagsChanged(object, handle, after, before);
}
ENTRY_CDECL3_VOID(vcSceneObjectChangeFlags)

void vcSceneObjectSetUser(uint32_t handle, uint32_t user)
{
    vcSceneObject_user(vcSceneObjectGet(handle)) = user;
}
ENTRY_CDECL2_VOID(vcSceneObjectSetUser)

uint32_t vcSceneObjectGetUser(uint32_t handle)
{
    return vcSceneObject_user(vcSceneObjectGet(handle));
}
ENTRY_CDECL1(vcSceneObjectGetUser)

/* The centre of a box (its least corner, then its greatest): each sum is stored as a float before it
 * is halved, and the three are worked out before any is stored. */
void vcBoxCenter(uint32_t box, uint32_t centre)
{
    volatile float *least = (volatile float *)XBOX_PTR(box), *greatest = least + 3;
    volatile float *out = (volatile float *)XBOX_PTR(centre);
    double sum[3], half[3];
    int i;

    for (i = 0; i < 3; i++)
        sum[i] = RECOMP_FP_PC((double)greatest[i] + least[i]);
    for (i = 0; i < 3; i++)
        out[i] = (float)sum[i];
    for (i = 0; i < 3; i++)
        half[i] = RECOMP_FP_PC((double)out[i] * 0.5f);
    for (i = 0; i < 3; i++)
        out[i] = (float)half[i];
}
ENTRY_CDECL2_VOID(vcBoxCenter)

/* ── The quadtrees ───────────────────────────────────────────────────────────────────────────────── */

void vcSceneObjectReadTransform(uint32_t object, uint32_t rotation, uint32_t position)
{
    guest_copy(rotation, vcSceneObject_rotation_VA(object), 9 * 4);
    guest_copy(position, vcSceneObject_position_VA(object), 3 * 4);
}
ENTRY_REGISTERS_VOID(vcSceneObjectReadTransform, g_eax, g_ecx, g_edx)

/* The sphere around the bounds: half the box's diagonal for its radius, the diagonal's squares added
 * from the last, its root stored as a float before it is halved; -1 for a box empty on every axis
 * (its least corner past its greatest). Its centre is the box's, turned and moved into the world. */
void vcSceneObjectInsertBounds(uint32_t object, uint32_t rotation, uint32_t position)
{
    uint32_t frame = FRAME_TAKE(INSERT_FRAME), world_centre = frame + INSERT_WORLD_CENTRE;
    uint32_t centre = frame + INSERT_CENTRE;
    volatile float *least = vcSceneObject_bounds_min(object), *greatest = vcSceneObject_bounds_max(object);
    float radius = -1.0f;

    if (!(least[0] > greatest[0]) || !(least[1] > greatest[1]) || !(least[2] > greatest[2])) {
        double x = RECOMP_FP_PC((double)greatest[0] - least[0]);
        double y = RECOMP_FP_PC((double)greatest[1] - least[1]);
        double z = RECOMP_FP_PC((double)greatest[2] - least[2]);
        double squares = RECOMP_FP_PC(RECOMP_FP_PC(x * x)
                                      + RECOMP_FP_PC(RECOMP_FP_PC(y * y) + RECOMP_FP_PC(z * z)));
        float diagonal = (float)RECOMP_FP_PC(sqrt(squares));

        radius = (float)RECOMP_FP_PC((double)diagonal * 0.5f);
    }
    vcBoxCenter(vcSceneObject_bounds_min_VA(object), centre);
    vcTransformPoint(world_centre, rotation, centre, position);
    if (!vcSceneObject_bounds_entry(object)) {
        if (radius >= LEAST_RADIUS)
            vcSceneObject_bounds_entry(object) = CALL(vcQuadtreeInsert, vcSceneBoundsTree, world_centre,
                                                      float_to_bits(radius), object);
    } else {
        CALL(vcQuadtreeMove, vcSceneBoundsTree, vcSceneObject_bounds_entry(object), world_centre,
             float_to_bits(radius));
        if (radius < LEAST_RADIUS)
            vcSceneObject_bounds_entry(object) = 0;
    }
    FRAME_GIVE(INSERT_FRAME);
}
ENTRY_REGISTERS_VOID(vcSceneObjectInsertBounds, g_esi, ARG32(0), ARG32(1))

/* Calls a function that takes its scene object in esi, keeping esi the caller's. */
static void call_with_esi(void (*function)(void), uint32_t object, uint32_t rotation, uint32_t position)
{
    uint32_t saved = g_esi;

    g_esi = object;
    CALL(function, rotation, position);
    g_esi = saved;
}

/* Flag 4 going off puts the object in vcSceneBoundsTree, on takes it out; 0x10 the same for
 * vcSceneHitTree. Its transform is copied once, for both. */
void vcSceneObjectFlagsChanged(uint32_t object, uint32_t handle, uint32_t after, uint32_t before)
{
    uint32_t frame = FRAME_TAKE(CHANGE_FRAME), position = frame + CHANGE_POSITION, rotation = frame + CHANGE_ROTATION;
    int copied = 0;

    if ((before & OUT_OF_BOUNDS_TREE) && !(after & OUT_OF_BOUNDS_TREE)) {
        vcSceneObjectReadTransform(object, rotation, position);
        vcSceneObjectInsertBounds(object, rotation, position);
        CALL(vcSceneObjectEnterBoundsTree, handle);
        copied = 1;
    } else if (!(before & OUT_OF_BOUNDS_TREE) && (after & OUT_OF_BOUNDS_TREE)) {
        uint32_t saved = g_ebx;

        CALL(vcQuadtreeRemove, vcSceneBoundsTree, vcSceneObject_bounds_entry(object));
        vcSceneObject_bounds_entry(object) = 0;
        g_ebx = handle;                                 /* its argument */
        CALL0(vcSceneObjectLeaveBoundsTree);
        g_ebx = saved;
    }
    if ((before & OUT_OF_HIT_TREE) && !(after & OUT_OF_HIT_TREE)) {
        if (!copied)
            vcSceneObjectReadTransform(object, rotation, position);
        call_with_esi(vcSceneObjectInsertHitBounds, object, rotation, position);
    } else if (!(before & OUT_OF_HIT_TREE) && (after & OUT_OF_HIT_TREE)) {
        CALL(vcQuadtreeRemove, vcSceneHitTree, vcSceneObject_hit_bounds_entry(object));
        vcSceneObject_hit_bounds_entry(object) = 0;
    }
    g_eax = handle;     /* what the original leaves in eax when the object has no children */
    vcSceneObjectPassFlags(handle, object);
    FRAME_GIVE(CHANGE_FRAME);
}
ENTRY_CDECL4_VOID(vcSceneObjectFlagsChanged)

/* The flags with the ones of mask taken from own. */
static uint32_t keep(uint32_t flags, uint32_t own, uint32_t mask)
{
    return (flags & ~mask) | (own & mask);
}

/* The child takes its parent's flags but for the ones it keeps; 0x10000 makes it keep its own 2, a
 * flag whose use is not known yet. */
void vcSceneObjectInheritFlags(uint32_t parent_flags, uint32_t object, uint32_t handle)
{
    uint32_t before = vcSceneObject_flags(object);

    vcSceneObject_flags(object) = keep(parent_flags, before, KEEPS_OWN);
    if (vcSceneObject_flags(object) & KEEPS_OWN_HIT_TREE)
        vcSceneObject_flags(object) = keep(vcSceneObject_flags(object), before, OUT_OF_HIT_TREE);
    if (vcSceneObject_flags(object) & KEEPS_OWN_BOUNDS_TREE)
        vcSceneObject_flags(object) = keep(vcSceneObject_flags(object), before, OUT_OF_BOUNDS_TREE);
    if (vcSceneObject_flags(object) & 0x10000u)
        vcSceneObject_flags(object) = keep(vcSceneObject_flags(object), before, 0x2u);
    vcSceneObjectFlagsChanged(object, handle, vcSceneObject_flags(object), before);
}
ENTRY_REGISTERS_VOID(vcSceneObjectInheritFlags, g_eax, g_ecx, ARG32(0))

void vcSceneObjectPassFlags(uint32_t handle, uint32_t object)
{
    uint32_t child = vcSceneObject_first_child(object);

    while (child) {
        uint32_t child_object = vcSceneObjectGet(child);

        vcSceneObjectInheritFlags(vcSceneObject_flags(object), child_object, child);
        child = vcSceneObject_next_sibling(child_object);
    }
}
ENTRY_CDECL2_VOID(vcSceneObjectPassFlags)

/* ── The tree ────────────────────────────────────────────────────────────────────────────────────── */

void vcSceneObjectUnlink(uint32_t parent_object, uint32_t object, uint32_t handle)
{
    uint32_t next = vcSceneObject_next_sibling(object), previous;

    if (vcSceneObject_first_child(parent_object) == handle)
        vcSceneObject_first_child(parent_object) = next;
    if (next)
        vcSceneObject_previous_sibling(vcSceneObjectGet(next)) = vcSceneObject_previous_sibling(object);
    previous = vcSceneObject_previous_sibling(object);
    if (previous)
        vcSceneObject_next_sibling(vcSceneObjectGet(previous)) = vcSceneObject_next_sibling(object);
    vcSceneObject_next_sibling(object) = 0;
    vcSceneObject_previous_sibling(object) = 0;
    vcSceneObject_parent(object) = 0;
    vcSceneObject_parent_slot(object) = NO_SLOT;
    vcObjectRelease(handle);
}
ENTRY_REGISTERS_VOID(vcSceneObjectUnlink, g_eax, g_esi, g_ebx)

void vcSceneObjectLink(uint32_t object, uint32_t handle, uint32_t parent, uint32_t parent_object)
{
    uint32_t first;

    vcSceneObjectInheritFlags(vcSceneObject_flags(parent_object), object, handle);
    CALL(vcSceneObjectPlaceInParent, object, parent_object, parent);
    first = vcSceneObject_first_child(parent_object);
    if (first) {
        vcSceneObject_previous_sibling(vcSceneObjectGet(first)) = handle;
        vcSceneObject_next_sibling(object) = first;
    }
    vcSceneObject_first_child(parent_object) = handle;
    vcSceneObject_parent(object) = parent;
    vcObjectAddRef(handle);
}
ENTRY_REGISTERS_VOID(vcSceneObjectLink, g_edi, g_ebx, ARG32(0), ARG32(1))

void vcSceneObjectReleaseChildren(uint32_t object)
{
    uint32_t child = vcSceneObject_first_child(object);

    while (child) {
        uint32_t child_object = vcSceneObjectGet(child), next = vcSceneObject_next_sibling(child_object);

        vcSceneObject_parent(child_object) = 0;
        vcSceneObject_next_sibling(child_object) = 0;
        vcSceneObject_previous_sibling(child_object) = 0;
        vcSceneObject_parent_slot(child_object) = NO_SLOT;
        vcObjectRelease(child);
        child = next;
    }
    vcSceneObject_first_child(object) = 0;
}
ENTRY_CDECL1_VOID(vcSceneObjectReleaseChildren)

void vcSceneObjectAttach(uint32_t handle, uint32_t parent, int32_t slot)
{
    uint32_t object = vcSceneObjectGet(handle);

    if (vcSceneObject_parent(object)) {
        vcSceneObjectUnlink(vcSceneObjectGet(vcSceneObject_parent(object)), object, handle);
        vcSceneObject_parent_slot(object) = NO_SLOT;
    }
    if (parent) {
        uint32_t parent_object = vcSceneObjectGet(parent);

        vcSceneObject_parent_slot(object) = slot;
        vcSceneObjectLink(object, handle, parent, parent_object);
    }
}
ENTRY_CDECL3_VOID(vcSceneObjectAttach)

/* Both entries are read before either is taken out, as the original. */
void vcSceneObjectRemove(uint32_t handle, uint32_t object)
{
    uint32_t bounds_entry = vcSceneObject_bounds_entry(object), hit_entry = vcSceneObject_hit_bounds_entry(object);

    if (bounds_entry)
        CALL(vcQuadtreeRemove, vcSceneBoundsTree, bounds_entry);
    if (hit_entry)
        CALL(vcQuadtreeRemove, vcSceneHitTree, hit_entry);
    if (vcSceneObject_parent(object))
        vcSceneObjectUnlink(vcSceneObjectGet(vcSceneObject_parent(object)), object, handle);
    if (vcSceneObject_first_child(object))
        vcSceneObjectReleaseChildren(object);
}
ENTRY_CDECL2_VOID(vcSceneObjectRemove)

/* ── Transform and bounds ────────────────────────────────────────────────────────────────────────── */

void vcSceneObjectGetTransform(uint32_t handle, uint32_t rotation, uint32_t position)
{
    uint32_t object = vcSceneObjectGet(handle);

    guest_copy(rotation, vcSceneObject_rotation_VA(object), 9 * 4);
    guest_copy(position, vcSceneObject_position_VA(object), 3 * 4);
}
ENTRY_CDECL3_VOID(vcSceneObjectGetTransform)

/* The least corner, then the greatest. */
void vcSceneObjectGetBounds(uint32_t handle, uint32_t corners)
{
    guest_copy(corners, vcSceneObject_bounds_min_VA(vcSceneObjectGet(handle)), 6 * 4);
}
ENTRY_CDECL2_VOID(vcSceneObjectGetBounds)

/* ── Starting and copying ────────────────────────────────────────────────────────────────────────── */

void vcSceneObjectInit(uint32_t handle, uint32_t object, uint32_t flags)
{
    int i;

    guest_zero(object, vcSceneObject_SIZE);
    for (i = 0; i < 3; i++) {
        vcSceneObject_rotation(object)[i * 4] = 1.0f;               /* the diagonal */
        vcSceneObject_rotation_in_parent(object)[i * 4] = 1.0f;
        vcSceneObject_bounds_min(object)[i] = FLT_MAX;
        vcSceneObject_bounds_max(object)[i] = -FLT_MAX;
        vcSceneObject_hit_bounds_min(object)[i] = FLT_MAX;
        vcSceneObject_hit_bounds_max(object)[i] = -FLT_MAX;
    }
    vcSceneObject_handle(object) = handle;
    vcSceneObject_flags(object) = flags;
    vcSceneObject_parent_slot(object) = NO_SLOT;
}
ENTRY_CDECL3_VOID(vcSceneObjectInit)

/* The flags are cleared before the other's are read, as the original: copied onto itself, an object's
 * flags come out 0. */
void vcSceneObjectCopy(uint32_t handle, uint32_t from)
{
    uint32_t object = vcSceneObjectGet(handle);

    guest_copy(object, from, vcSceneObject_SIZE);
    vcSceneObject_flags(object) = 0;
    vcSceneObject_user(object) = 0;
    vcSceneObject_bounds_entry(object) = 0;
    vcSceneObject_hit_bounds_entry(object) = 0;
    vcSceneObject_handle(object) = handle;
    vcSceneObject_flags(object) = vcSceneObject_flags(from);
    vcSceneObject_first_child(object) = 0;
    vcSceneObject_next_sibling(object) = 0;
    vcSceneObject_parent(object) = 0;
    vcSceneObject_parent_slot(object) = NO_SLOT;
}
ENTRY_CDECL2_VOID(vcSceneObjectCopy)
