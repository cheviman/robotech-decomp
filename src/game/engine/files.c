/**
 *    Name:        engine/files.c
 *    Description: the engine's files, written in C: read from the game's disc through a 64 KB buffer, or created
 *                 on a drive of the console; and the table of the objects read from one
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A vcFile keeps 64 KB of the file in a buffer: where in the file the buffer starts, and where in the
 *    buffer the next read is. A read within the buffer copies from it; one past it reads on from the
 *    disc, a whole 64 KB part straight into the reader's memory. The console's files are XAPI's
 *    (CreateFileA, SetFilePointer, ReadFile, CloseHandle), still recompiled.
 *
 *    Each function is the original's in what it does; the ones the recompiled code calls have an entry
 *    (decomp.h). ReadFile's count of bytes read goes to a word of the guest's stack.
 */
#include "decomp.h"
#include "files.h"
#include "format.h"

#define BUFFER_BYTES        0x10000u    /* a file's buffer */
#define FIRST_OBJECTS       0x20        /* a file's table of objects when it first fills */
#define INVALID_HANDLE      0xFFFFFFFFu
/* CreateFileA's and SetFilePointer's arguments */
#define GENERIC_READ_       0x80000000u
#define GENERIC_WRITE_      0x40000000u
#define FILE_SHARE_READ_    1u
#define CREATE_ALWAYS_      2u
#define OPEN_EXISTING_      3u
#define ATTRIBUTE_NORMAL    0x80u
#define SEQUENTIAL_SCAN     0x08000000u
#define FROM_BEGIN          0u
#define FROM_CURRENT        1u
#define FROM_END            2u

/* ReadFile(handle, at, bytes, &read, 0), the count of bytes read in a word of the guest's stack */
static void read_file(uint32_t handle, uint32_t at, uint32_t bytes)
{
    uint32_t read = FRAME_TAKE(4);

    CALL(xapi_ReadFile, handle, at, bytes, read, 0);
    FRAME_GIVE(4);
}

/* ── Opening and closing ─────────────────────────────────────────────────────────────────────────── */

int32_t vcFileFill(uint32_t file)
{
    uint32_t bytes;

    CALL(xapi_SetFilePointer, vcFile_handle(file), 0, 0, FROM_CURRENT);
    vcFile_size(file) = CALL(xapi_SetFilePointer, vcFile_handle(file), 0, 0, FROM_END);
    CALL(xapi_SetFilePointer, vcFile_handle(file), 0, 0, FROM_BEGIN);
    vcFile_buffer(file) = CALL(crt_malloc, BUFFER_BYTES);
    if (!vcFile_buffer(file))
        return 0;
    bytes = vcFile_size(file) < BUFFER_BYTES ? vcFile_size(file) : BUFFER_BYTES;
    read_file(vcFile_handle(file), vcFile_buffer(file), bytes);
    vcFile_buffer_offset(file) = 0;
    vcFile_position(file) = 0;
    return 1;
}
ENTRY_CDECL1(vcFileFill)

int32_t vcFileCreate(uint32_t file, uint32_t name)
{
    uint32_t path, handle;

    vcFile_handle(file) = 0;
    vcFile_by_name(file) = 0;
    vcFile_object_capacity(file) = 0;
    vcFile_object_count(file) = 0;
    vcFile_objects(file) = 0;
    path = CALL(vcFormat_entry, vcFileOnDriveFormat_VA, (uint32_t)(int32_t)(int8_t)vcFileDrive, name);
    handle = CALL(xapi_CreateFileA, path, GENERIC_READ_ | GENERIC_WRITE_, 0, 0, CREATE_ALWAYS_, 0, 0);
    vcFile_handle(file) = handle;
    if (handle == INVALID_HANDLE) {
        vcFile_handle(file) = 0;
        return 0;
    }
    return 1;
}
ENTRY_CDECL2(vcFileCreate)

int32_t vcFileOpen(uint32_t file, uint32_t name)
{
    uint32_t path = CALL(vcFormat_entry, vcFileOnDiscFormat_VA, name);
    uint32_t handle = CALL(xapi_CreateFileA, path, GENERIC_READ_, FILE_SHARE_READ_, 0, OPEN_EXISTING_,
                           SEQUENTIAL_SCAN | ATTRIBUTE_NORMAL, 0);

    vcFile_handle(file) = handle;
    if (handle == INVALID_HANDLE) {
        vcFile_handle(file) = 0;
        return 0;
    }
    vcFile_by_name(file) = 0;
    vcFile_object_capacity(file) = 0;
    vcFile_object_count(file) = 0;
    vcFile_objects(file) = 0;
    vcFile_buffer(file) = 0;
    vcFile_buffer_offset(file) = 0;
    vcFile_position(file) = 0;
    vcFile_size(file) = 0;
    vcFileFill(file);
    return vcFile_handle(file) != INVALID_HANDLE;
}
ENTRY_CDECL2(vcFileOpen)

int32_t vcFileClose(uint32_t file)
{
    if (!vcFile_handle(file))
        return 1;
    if (vcFile_buffer(file)) {
        CALL(crt_free, vcFile_buffer(file));
        vcFile_buffer(file) = 0;
    }
    if (!CALL(xapi_CloseHandle, vcFile_handle(file)))
        return 0;
    vcFile_handle(file) = 0;
    return 1;
}
ENTRY_CDECL1(vcFileClose)

int32_t vcFileExists(uint32_t name)
{
    uint32_t path = CALL(vcFormat_entry, vcFileOnDriveFormat_VA, (uint32_t)(int32_t)(int8_t)vcFileDrive, name);
    uint32_t handle = CALL(xapi_CreateFileA, path, 0, 0, 0, OPEN_EXISTING_, ATTRIBUTE_NORMAL, 0);

    if (handle == INVALID_HANDLE)
        return 0;
    CALL(xapi_CloseHandle, handle);
    return 1;
}
ENTRY_CDECL1(vcFileExists)

/* ── Reading ─────────────────────────────────────────────────────────────────────────────────────── */

/* What is left in the buffer is counted from the file's size or 64 KB, whichever is less, as in the
 * original, wherever the buffer starts. */
uint32_t vcFileRead(uint32_t file, uint32_t to, uint32_t bytes)
{
    uint32_t position = vcFile_position(file), size = vcFile_size(file), in_buffer, rest;

    if (vcFile_buffer_offset(file) + position > size || !size)
        return 0;
    in_buffer = (size < BUFFER_BYTES ? size : BUFFER_BYTES) - position;
    if (bytes <= in_buffer) {
        guest_copy(to, vcFile_buffer(file) + position, bytes);
        vcFile_position(file) += bytes;
        return bytes;
    }
    guest_copy(to, vcFile_buffer(file) + position, in_buffer);
    vcFile_position(file) += in_buffer;
    to += in_buffer;
    for (rest = bytes - in_buffer; rest; ) {
        uint32_t part = rest < BUFFER_BYTES ? rest : BUFFER_BYTES;

        vcFile_buffer_offset(file) += BUFFER_BYTES;
        vcFile_position(file) = 0;
        if (part == BUFFER_BYTES) {
            read_file(vcFile_handle(file), to, part);
        } else {
            read_file(vcFile_handle(file), vcFile_buffer(file), BUFFER_BYTES);
            guest_copy(to, vcFile_buffer(file), part);
        }
        vcFile_position(file) += part;
        to += part;
        rest -= part;
    }
    return bytes;
}
ENTRY_CDECL3(vcFileRead)

int32_t vcFileReadIfOpen(uint32_t file, uint32_t to, uint32_t bytes)
{
    if (!vcFile_handle(file))
        return 0;
    return vcFileRead(file, to, bytes) == bytes;
}
ENTRY_CDECL3(vcFileReadIfOpen)

int32_t vcFileReadBytes(uint32_t file, uint32_t to, uint32_t bytes)
{
    return vcFileRead(file, to, bytes) == bytes;
}
ENTRY_CDECL3(vcFileReadBytes)

int32_t vcFileReadU16(uint32_t file, uint32_t to)
{
    return vcFileRead(file, to, 2) == 2;
}
ENTRY_CDECL2(vcFileReadU16)

int32_t vcFileReadU32(uint32_t file, uint32_t to)
{
    return vcFileRead(file, to, 4) == 4;
}
ENTRY_CDECL2(vcFileReadU32)

int32_t vcFileReadU16s(uint32_t file, uint32_t to, uint32_t count)
{
    return vcFileRead(file, to, count * 2) == count * 2;
}
ENTRY_CDECL3(vcFileReadU16s)

int32_t vcFileReadU32s(uint32_t file, uint32_t to, uint32_t count)
{
    return vcFileRead(file, to, count * 4) == count * 4;
}
ENTRY_CDECL3(vcFileReadU32s)

/* ── Moving ──────────────────────────────────────────────────────────────────────────────────────── */

uint32_t vcFileTell(uint32_t file)
{
    return vcFile_buffer_offset(file) + vcFile_position(file);
}
ENTRY_CDECL1(vcFileTell)

/* Within the buffer the next read only moves; elsewhere the buffer is read from there. */
int32_t vcFileSeek(uint32_t file, uint32_t to)
{
    int32_t in_buffer = (int32_t)(to - vcFile_buffer_offset(file));

    if (in_buffer >= 0 && in_buffer < (int32_t)BUFFER_BYTES) {
        vcFile_position(file) = (uint32_t)in_buffer;
        return 1;
    }
    vcFile_buffer_offset(file) = to;
    vcFile_position(file) = 0;
    CALL(xapi_SetFilePointer, vcFile_handle(file), to, 0, FROM_BEGIN);
    read_file(vcFile_handle(file), vcFile_buffer(file), BUFFER_BYTES);
    return 1;
}
ENTRY_CDECL2(vcFileSeek)

int32_t vcFileSkip(uint32_t file, uint32_t bytes)
{
    return vcFileSeek(file, vcFile_buffer_offset(file) + bytes + vcFile_position(file));
}
ENTRY_CDECL2(vcFileSkip)

/* ── The objects read from a file ────────────────────────────────────────────────────────────────── */

uint32_t vcFileAddObject(uint32_t file, uint32_t handle)
{
    if (vcFile_object_count(file) == vcFile_object_capacity(file)) {
        int32_t capacity = vcFile_object_capacity(file) ? vcFile_object_capacity(file) * 2 : FIRST_OBJECTS;
        uint32_t table = CALL(crt_calloc, (uint32_t)capacity, 4);

        guest_copy(table, vcFile_objects(file), (uint32_t)vcFile_object_capacity(file) * 4u);
        CALL(crt_free, vcFile_objects(file));
        vcFile_objects(file) = table;
        vcFile_object_capacity(file) = capacity;
    }
    MEM32(vcFile_objects(file) + 4u * (uint32_t)vcFile_object_count(file)) = handle;
    return (uint32_t)vcFile_object_count(file)++;
}
ENTRY_CDECL2(vcFileAddObject)

void vcFileFreeObjects(uint32_t file)
{
    if (!vcFile_objects(file))
        return;
    CALL(crt_free, vcFile_objects(file));
    vcFile_objects(file) = 0;
    vcFile_object_capacity(file) = 0;
    vcFile_object_count(file) = 0;
}
ENTRY_CDECL1_VOID(vcFileFreeObjects)
