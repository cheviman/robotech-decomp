/**
 *    Name:        engine/format.c
 *    Description: the engine's formatted strings, written in C: two static buffers of 1 KB, used in turn
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    vcFormat writes into the buffer it did not write last, so the string it handed back before stays
 *    good for one more call: a path built from another. The formatting is the C runtime's vsprintf, still
 *    recompiled, given the guest address of the arguments as its va_list.
 */
#include "decomp.h"
#include "format.h"

#define FORMAT_BUFFER_BYTES 0x400u

static uint32_t last_buffer(void)
{
    return vcFormatBuffers_VA + vcFormatBufferIndex * FORMAT_BUFFER_BYTES;
}

uint32_t vcFormat(uint32_t format, uint32_t args)
{
    uint32_t buffer;

    vcFormatBufferIndex ^= 1;
    buffer = last_buffer();
    MEM8(buffer) = 0;
    if (format)
        CALL(crt_vsprintf, buffer, format, args);
    return last_buffer();
}
ENTRY_VARARGS1(vcFormat)

uint32_t vcFormatAppend(uint32_t format, uint32_t args)
{
    if (format) {
        uint32_t buffer = last_buffer();

        CALL(crt_vsprintf, buffer + guest_strlen(buffer), format, args);
    }
    return last_buffer();
}
ENTRY_VARARGS1(vcFormatAppend)

uint32_t vcFormatLast(void)
{
    return last_buffer();
}
ENTRY_CDECL0(vcFormatLast)

uint32_t vcFormatClear(void)
{
    uint32_t buffer = last_buffer();

    MEM8(buffer) = 0;
    return buffer;
}
ENTRY_CDECL0(vcFormatClear)

/* The C runtime's tolower, a character at a time, its length counted again after each. */
void vcStrLower(uint32_t s)
{
    uint32_t at;

    for (at = s; at < s + guest_strlen(s); at++)
        MEM8(at) = (uint8_t)CALL(crt_tolower, (uint32_t)(int32_t)(int8_t)MEM8(at));
}
ENTRY_CDECL1_VOID(vcStrLower)
