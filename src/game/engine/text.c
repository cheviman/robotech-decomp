/**
 *    Name:        engine/text.c
 *    Description: the engine's text, written in C: its fonts, the characters' height and width, measuring a
 *                 string, and drawing one at a point, aligned and shadowed, or laid out in lines in a rectangle
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A font is a texture of 16 x 16 characters; vcFontDrawString, still recompiled, draws a string with
 *    one. The default font, read from defaultfont.tga, is the only one whose characters have widths of
 *    their own (vcDefaultFontWidths, in 16ths of the height); in any other a character is as wide as the
 *    height times the scale.
 *
 *    The floats are worked on the x87, as the original: each operation rounded to the control word's
 *    precision (decomp.h), a float stored to memory rounded to a float. A width or a height handed back
 *    goes back in st(0).
 */
#include "decomp.h"
#include "objects.h"
#include "text.h"

#define FONTS                   16
#define CLASS_TEXTURE           1u          /* vcTexture's type: a font is one */
#define SIZE_DEFAULT_MARK       -1.0f       /* vcTextSetSize's "the default" */
#define SIZE_DEFAULT            16.0f
#define WIDTH_UNIT              0.0625f     /* vcDefaultFontWidths are in 16ths of the height */
#define HALF                    0.5f
#define TWO_TO_32               4294967296.0f

/* vcTextDrawAligned's and vcTextDrawInRect's flags */
#define ALIGN_CENTRE_ACROSS     0x01u
#define ALIGN_CENTRE_DOWN       0x02u
#define ALIGN_SHADOW            0x04u

/* vcTextDrawInRect's locals, in the guest's stack: the string laid out in lines (1 KB), then the line
 * being drawn; below them the three registers the original saves, its frame aligned to 8 bytes */
#define WRAP_LOCALS             0x814u
#define WRAP_SAVED              12u
#define WRAP_LINES_AT           0x20u
#define WRAP_LINES_BYTES        0x400u
#define WRAP_LINE_AT            0x420u

/* ── The fonts ───────────────────────────────────────────────────────────────────────────────────── */

void vcTextInit(void)
{
    uint32_t i;

    if (++vcTextUsers > 1)
        return;
    for (i = 0; i < FONTS; i++)
        if (!vcFonts(i)) {
            vcFonts(i) = vcObjectGet(CLASS_TEXTURE, vcDefaultFontName_VA);
            vcTextDefaultFont = i;
            vcTextFont = i;
            return;
        }
    vcTextDefaultFont = 0;
    vcTextFont = 0;
}
ENTRY_CDECL0_VOID(vcTextInit)

void vcTextShutdown(void)
{
    uint32_t i;

    if (--vcTextUsers)
        return;
    for (i = 0; i < FONTS; i++)
        if (vcFonts(i)) {
            vcObjectRelease(vcFonts(i));
            vcFonts(i) = 0;
        }
}
ENTRY_CDECL0_VOID(vcTextShutdown)

uint32_t vcTextSetFont(uint32_t font)
{
    uint32_t before = vcTextFont;

    vcTextFont = font;
    return before;
}
ENTRY_CDECL1(vcTextSetFont)

/* ── Height and width ────────────────────────────────────────────────────────────────────────────── */

double vcTextSetSize(uint32_t size)
{
    double before = vcTextSize;

    vcTextSize = float_from_bits(size) == SIZE_DEFAULT_MARK ? SIZE_DEFAULT : float_from_bits(size);
    return before;
}
ENTRY_CDECL1_FLOAT(vcTextSetSize)

double vcTextGetSize(void)
{
    return vcTextSize;
}
ENTRY_CDECL0_FLOAT(vcTextGetSize)

double vcTextSetScale(uint32_t scale)
{
    double before = vcTextScale;

    vcTextScale = float_from_bits(scale);
    return before;
}
ENTRY_CDECL1_FLOAT(vcTextSetScale)

/* The original sums the default font's widths four characters at a turn, then the rest; each one is
 * still multiplied and added in its order, so one at a turn gives the same number. */
double vcTextWidthN(uint32_t text, uint32_t length)
{
    uint32_t all = guest_strlen(text), i;
    double width, count;

    if (length > all)
        length = all;
    if (vcTextFont != vcTextDefaultFont) {
        width = RECOMP_FP_PC((double)vcTextScale * vcTextSize);
        count = (double)(int32_t)length;            /* loaded signed, then made unsigned */
        if ((int32_t)length < 0)
            count = RECOMP_FP_PC(count + TWO_TO_32);
        return RECOMP_FP_PC(width * count);
    }
    width = 0.0;
    for (i = 0; i < length; i++) {
        double character = (double)vcDefaultFontWidths(MEM8(text + i));

        character = RECOMP_FP_PC(character * vcTextScale);
        character = RECOMP_FP_PC(character * vcTextSize);
        character = RECOMP_FP_PC(character * WIDTH_UNIT);
        width = RECOMP_FP_PC(width + character);
    }
    return width;
}
ENTRY_CDECL2_FLOAT(vcTextWidthN)

double vcTextWidth(uint32_t text)
{
    return vcTextWidthN(text, guest_strlen(text));
}
ENTRY_CDECL1_FLOAT(vcTextWidth)

/* ── Drawing ─────────────────────────────────────────────────────────────────────────────────────── */

/* vcFontDrawString with the font, height and scale set. */
static void draw_string(uint32_t x, uint32_t y, uint32_t color, uint32_t text)
{
    CALL(vcFontDrawString, x, y, color, text, vcFonts(vcTextFont), float_to_bits(vcTextSize),
         float_to_bits(vcTextScale), vcTextFont == vcTextDefaultFont);
}

void vcTextDraw(uint32_t x, uint32_t y, uint32_t color, uint32_t text)
{
    draw_string(x, y, color, text);
}
ENTRY_CDECL4_VOID(vcTextDraw)

void vcTextSetShadowColor(uint32_t color)
{
    vcTextShadowColor = color;
}
ENTRY_CDECL1_VOID(vcTextSetShadowColor)

void vcTextSetShadowOffset(uint32_t x, uint32_t y)
{
    vcTextShadowX = float_from_bits(x);
    vcTextShadowY = float_from_bits(y);
}
ENTRY_CDECL2_VOID(vcTextSetShadowOffset)

void vcTextDrawAligned(uint32_t x_bits, uint32_t y_bits, uint32_t color, uint32_t text, uint32_t flags)
{
    float x = float_from_bits(x_bits), y = float_from_bits(y_bits);

    if (flags & ALIGN_CENTRE_ACROSS)
        x = (float)RECOMP_FP_PC(x - RECOMP_FP_PC(vcTextWidth(text) * HALF));
    if (flags & ALIGN_CENTRE_DOWN)
        y = (float)RECOMP_FP_PC(y - RECOMP_FP_PC((double)vcTextSize * HALF));
    if (flags & ALIGN_SHADOW)
        draw_string(float_to_bits((float)RECOMP_FP_PC((double)vcTextShadowX + x)),
                    float_to_bits((float)RECOMP_FP_PC((double)vcTextShadowY + y)), vcTextShadowColor, text);
    draw_string(float_to_bits(x), float_to_bits(y), color, text);
}
ENTRY_CDECL5_VOID(vcTextDrawAligned)

/* The middle of two edges, as the original works it out: low + (high - low) / 2, the half rounded
 * down. */
static int32_t middle(int32_t low, int32_t high)
{
    return (int32_t)((uint32_t)low + (uint32_t)((int32_t)((uint32_t)high - (uint32_t)low) >> 1));
}

/* The string is copied into the lines buffer a character at a time, carriage returns left out; as soon
 * as the line so far is wider than the rectangle (less the indent, for the first line) or a line feed
 * comes, the line ends: at its last space, which becomes the line feed and the next line's start, or
 * else after that character. Then each line is drawn, a height below the one before. */
int32_t vcTextDrawInRect(uint32_t rect, uint32_t color, uint32_t text, uint32_t flags, uint32_t indent_bits)
{
    uint32_t frame = ((g_esp - 4u) & ~7u) - WRAP_LOCALS - WRAP_SAVED, taken = g_esp - frame;
    uint32_t lines_buffer = frame + WRAP_LINES_AT, line = frame + WRAP_LINE_AT;
    uint32_t write, start, space = 0, from;
    float indent = float_from_bits(indent_bits), available, x, y;
    int32_t lines = 1, i;
    uint8_t c;

    FRAME_TAKE(taken);
    guest_zero(lines_buffer, WRAP_LINES_BYTES);
    if (!text) {
        FRAME_GIVE(taken);
        return 0;
    }
    write = start = lines_buffer;
    from = text;
    c = MEM8(from);
    if (c) {
        available = (float)(int32_t)((uint32_t)vcRect_right(rect) - (uint32_t)vcRect_left(rect));
        do {
            if (c == ' ')
                space = write;
            if (c != '\r') {
                MEM8(write) = c;
                write++;
                MEM8(write) = 0;
            }
            if (RECOMP_FP_PC((double)available - indent) < vcTextWidth(start) || c == '\n') {
                if (space && c != '\n') {
                    MEM8(space) = '\n';
                    start = space;
                } else {
                    if (!space && c != '\n') {
                        MEM8(write) = '\n';
                        write++;
                    }
                    start = write;
                }
                lines++;
                indent = 0.0f;
                space = 0;
            }
            from++;
            c = MEM8(from);
        } while (c);
    }
    MEM8(write) = 0;

    if (flags & ALIGN_CENTRE_ACROSS)
        x = (float)middle(vcRect_left(rect), vcRect_right(rect));
    else
        x = (float)vcRect_left(rect);
    if (flags & ALIGN_CENTRE_DOWN) {
        double half_block = RECOMP_FP_PC(RECOMP_FP_PC((double)lines * vcTextSize) * HALF);
        double half_line = RECOMP_FP_PC((double)vcTextSize * HALF);

        y = (float)RECOMP_FP_PC((double)middle(vcRect_top(rect), vcRect_bottom(rect))
                                - RECOMP_FP_PC(half_block - half_line));
    } else {
        y = (float)vcRect_top(rect);
    }

    for (i = 0, from = lines_buffer; i < lines; i++) {
        uint32_t to = line;
        float line_x = i ? x : (float)RECOMP_FP_PC((double)x + float_from_bits(indent_bits));

        c = MEM8(from);
        while (c != '\n' && c) {
            MEM8(to) = c;
            to++;
            c = MEM8(++from);
        }
        MEM8(to) = 0;
        vcTextDrawAligned(float_to_bits(line_x), float_to_bits(y), color, line, flags);
        y = (float)RECOMP_FP_PC((double)vcTextSize + y);
        from++;
    }
    FRAME_GIVE(taken);
    return lines;
}
ENTRY_CDECL5(vcTextDrawInRect)
