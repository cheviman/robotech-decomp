/**
 *    Name:        engine/rects.c
 *    Description: the engine's rectangles, written in C: setting, copying, growing and moving them, reading one
 *                 from a file, and placing one against the part of the screen the game lays out in
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A vcRect is left, top, right, bottom, in pixels. vcScreenRect is the part of the screen the game's
 *    screens are laid out in, the title-safe 48, 36, 592, 444 of 640 x 480 unless the game sets another.
 */
#include "decomp.h"
#include "files.h"
#include "rects.h"

#define PLACE_FROM_LEFT     0x01u   /* vcRectPlace's flags */
#define PLACE_FROM_RIGHT    0x02u
#define PLACE_FROM_TOP      0x04u
#define PLACE_FROM_BOTTOM   0x08u
#define PLACE_CENTRE_ACROSS 0x10u
#define PLACE_CENTRE_DOWN   0x20u

int32_t vcRectSet(uint32_t rect, int32_t left, int32_t top, int32_t right, int32_t bottom)
{
    if (!rect)
        return 0;
    vcRect_left(rect) = left;
    vcRect_right(rect) = right;
    vcRect_top(rect) = top;
    vcRect_bottom(rect) = bottom;
    return 1;
}
ENTRY_CDECL5(vcRectSet)

int32_t vcRectCopy(uint32_t to, uint32_t from)
{
    if (!to || !from)
        return 0;
    vcRect_left(to) = vcRect_left(from);
    vcRect_right(to) = vcRect_right(from);
    vcRect_top(to) = vcRect_top(from);
    vcRect_bottom(to) = vcRect_bottom(from);
    return 1;
}
ENTRY_CDECL2(vcRectCopy)

int32_t vcRectInflate(uint32_t rect, int32_t across, int32_t down)
{
    if (!rect)
        return 0;
    vcRect_left(rect) -= across;
    vcRect_right(rect) += across;
    vcRect_top(rect) -= down;
    vcRect_bottom(rect) += down;
    return 1;
}
ENTRY_CDECL3(vcRectInflate)

int32_t vcRectOffset(uint32_t rect, int32_t across, int32_t down)
{
    if (!rect)
        return 0;
    vcRect_left(rect) += across;
    vcRect_right(rect) += across;
    vcRect_top(rect) += down;
    vcRect_bottom(rect) += down;
    return 1;
}
ENTRY_CDECL3(vcRectOffset)

void vcFileReadRect(uint32_t file, uint32_t rect)
{
    vcFileReadU32(file, vcRect_left_VA(rect));
    vcFileReadU32(file, vcRect_right_VA(rect));
    vcFileReadU32(file, vcRect_top_VA(rect));
    vcFileReadU32(file, vcRect_bottom_VA(rect));
}
ENTRY_CDECL2_VOID(vcFileReadRect)

/* The rectangle's left and top are taken as distances from the screen's edges the flags name, then
 * the rectangle is centred on that point if they say so; its width and height stay. */
void vcRectPlace(uint32_t rect, uint32_t flags)
{
    int32_t width = vcRect_right(rect) - vcRect_left(rect), height = vcRect_bottom(rect) - vcRect_top(rect);
    int32_t left = vcRect_left(rect), top = vcRect_top(rect);

    if (flags & PLACE_FROM_LEFT)
        left += vcRect_left(vcScreenRect_VA);
    else if (flags & PLACE_FROM_RIGHT)
        left = vcRect_right(vcScreenRect_VA) - left;
    vcRect_left(rect) = left;
    if (flags & PLACE_FROM_TOP)
        top += vcRect_top(vcScreenRect_VA);
    else if (flags & PLACE_FROM_BOTTOM)
        top = vcRect_bottom(vcScreenRect_VA) - top;
    vcRect_top(rect) = top;
    if (flags & PLACE_CENTRE_ACROSS)
        vcRect_left(rect) = left - width / 2;
    if (flags & PLACE_CENTRE_DOWN)
        vcRect_top(rect) = top - height / 2;
    vcRect_right(rect) = vcRect_left(rect) + width;
    vcRect_bottom(rect) = vcRect_top(rect) + height;
}
ENTRY_CDECL2_VOID(vcRectPlace)

void vcScreenRectReset(void)
{
    vcRect_left(vcScreenRect_VA) = vcRect_left(vcScreenRectDefault_VA);
    vcRect_right(vcScreenRect_VA) = vcRect_right(vcScreenRectDefault_VA);
    vcRect_top(vcScreenRect_VA) = vcRect_top(vcScreenRectDefault_VA);
    vcRect_bottom(vcScreenRect_VA) = vcRect_bottom(vcScreenRectDefault_VA);
}
ENTRY_CDECL0_VOID(vcScreenRectReset)
