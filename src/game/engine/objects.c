/**
 *    Name:        engine/objects.c
 *    Description: the engine's object system, written in C: classes, handles, references, names, the release
 *                 queue, and reading objects from their files
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Every object of Vicious Cycle's engine is a handle, (type << 16) | index. A class registers a
 *    descriptor (vcClassDesc: its name, the extension of its files, the callbacks below) and gets a table
 *    of instances (vcInstance: the object's own data, its references, what changed of it, its name);
 *    vcClassByType[type] is the class, its instances[index] the object's instance. The object system
 *    creates, shares, clones and releases objects through their classes' callbacks, finds them by name
 *    and reads them from files (vcDataDir\xbox\CLASS\NAME.TAG, or as references inside another's file).
 *
 *    Each function is the original's, line for line in what it does; the ones the recompiled code still
 *    calls have an entry (decomp.h), and the ones that hand nothing back are void because no caller
 *    of the original reads eax after them. A local whose address goes to other code (a name, a vcFile,
 *    a word read from a file) lives in the guest's stack, in a frame of the original's size and at the
 *    original's offset in it; a word the original keeps in its argument's slot is in the frame too.
 */
#include "decomp.h"
#include "objects.h"
#include "files.h"
#include "format.h"

#define TYPES               64      /* vcClassByType's entries */
#define CHANGED_ALL         7u      /* vcInstance flags: data, name and new */
#define CHANGED_DATA        1u
#define CHANGED_NAME        2u
#define CHANGED_NEW         4u
#define QUEUED              0x10u   /* vcInstance flags: in vcReleaseQueue */
#define NAME_BYTES          64u     /* vcInstance name */
#define FIRST_INSTANCES     4       /* a class's table when it first fills */
#define FIRST_QUEUE         0x20    /* vcReleaseQueue's when it first fills */
#define PLATFORM_NAME_BYTES 8u      /* each of vcPlatformNames */
#define COLLECT_HANDLES     8u      /* where a vcCollectList's handles start */
#define FILE_BLOCK          4u      /* an object's header in a file ends on a multiple of 4 */

#define HANDLE(type, index) (((uint32_t)(type) << 16) | (uint32_t)(index))
#define TYPE_OF(handle)     ((uint32_t)(handle) >> 16)
#define INDEX_OF(handle)    ((uint32_t)(handle) & 0xFFFFu)

/* ── The guest's memory ──────────────────────────────────────────────────────────────────────────── */

static uint32_t class_of(uint32_t handle)
{
    return vcClassByType(TYPE_OF(handle));
}

static uint32_t instance_at(uint32_t cls, uint32_t index)
{
    return vcClass_instances(cls) + index * vcInstance_SIZE;
}

static uint32_t instance_of(uint32_t handle)
{
    return instance_at(class_of(handle), INDEX_OF(handle));
}

/* A table of `count` entries of `size` bytes, from calloc. */
static uint32_t calloc_table(uint32_t count, uint32_t size)
{
    return CALL(crt_calloc, count, size);
}

/* ── Classes ─────────────────────────────────────────────────────────────────────────────────────── */

void vcObjectSystemInit(uint32_t data_dir)
{
    uint32_t n = 0;

    guest_zero(vcClassByType_VA, TYPES * 4u);
    guest_zero(vcClassTable_VA, TYPES * vcClass_SIZE);
    do
        vcDataDir(n) = (char)MEM8(data_dir + n);
    while (MEM8(data_dir + n++));
    guest_put_string(vcPlatformNames_VA + 0 * PLATFORM_NAME_BYTES, "pc");
    guest_put_string(vcPlatformNames_VA + 1 * PLATFORM_NAME_BYTES, "xbox");
    guest_put_string(vcPlatformNames_VA + 2 * PLATFORM_NAME_BYTES, "ps2");
    guest_put_string(vcPlatformNames_VA + 3 * PLATFORM_NAME_BYTES, "gc");
}
ENTRY_CDECL1_VOID(vcObjectSystemInit)

uint32_t vcGetDataDir(void)
{
    return vcDataDir_VA;
}
ENTRY_CDECL0(vcGetDataDir)

uint32_t vcGetPlatformName(void)
{
    return vcPlatformNames_VA + 1 * PLATFORM_NAME_BYTES;
}
ENTRY_CDECL0(vcGetPlatformName)

void vcRegisterClass(uint32_t desc, int32_t capacity)
{
    uint32_t cls = vcClassTable_VA + vcClassDesc_type(desc) * vcClass_SIZE;

    guest_copy(cls, desc, vcClassDesc_SIZE);
    vcClass_free_index(cls) = 0;
    vcClass_count(cls) = 0;
    vcClass_peak(cls) = 0;
    vcClass_capacity(cls) = capacity;
    vcClass_instances(cls) = calloc_table((uint32_t)capacity, vcInstance_SIZE);
    vcClassByType(vcClassDesc_type(desc)) = cls;
}
ENTRY_CDECL2_VOID(vcRegisterClass)

/* An instance is free when nothing refers to it. */
void vcClassFindFreeInstance(uint32_t cls)
{
    int32_t start = vcClass_free_index(cls), capacity = vcClass_capacity(cls), i;

    for (i = start; i < vcClass_capacity(cls); i++)
        if (vcInstance_refs(instance_at(cls, (uint32_t)i)) == 0) {
            vcClass_free_index(cls) = i;
            return;
        }
    for (i = start - 1; i >= 0; i--)
        if (vcInstance_refs(instance_at(cls, (uint32_t)i)) == 0) {
            vcClass_free_index(cls) = i;
            return;
        }
    vcClass_free_index(cls) = capacity;
}
ENTRY_THISCALL0_VOID(vcClassFindFreeInstance)

/* Runs a callback over the objects of a class in use: the table of instances is the one there was when
 * it started. */
int32_t vcClassForEach(uint32_t type, uint32_t callback, int32_t max, uint32_t user)
{
    uint32_t cls = vcClassByType(type), instance = vcClass_instances(cls);
    int32_t done = 0;
    uint32_t index = 0;

    if (max < 0)
        max = vcClass_count(cls);
    if (vcClass_count(cls) <= 0)
        return 1;
    do {
        if (done >= max)
            break;
        if (vcInstance_refs(instance) > 0) {
            if (!CALL_AT(callback, HANDLE(type, index), vcInstance_object(instance), user))
                return 0;
            done++;
        }
        instance += vcInstance_SIZE;
        index++;
    } while (done < vcClass_count(cls));
    return 1;
}
ENTRY_CDECL4(vcClassForEach)

void vcClassAddRefAll(uint32_t type)
{
    int32_t i;

    for (i = 0; i < vcClass_capacity(vcClassByType(type)); i++) {
        uint32_t instance = instance_at(vcClassByType(type), (uint32_t)i);

        if (vcInstance_refs(instance) > 0)
            vcInstance_refs(instance)++;
    }
}
ENTRY_CDECL1_VOID(vcClassAddRefAll)

void vcClassDecRefAll(uint32_t type)
{
    int32_t i;

    for (i = 0; i < vcClass_capacity(vcClassByType(type)); i++) {
        uint32_t instance = instance_at(vcClassByType(type), (uint32_t)i);

        if (vcInstance_refs(instance) > 0)
            vcInstance_refs(instance)--;
    }
}
ENTRY_CDECL1_VOID(vcClassDecRefAll)

/* ── Objects ─────────────────────────────────────────────────────────────────────────────────────── */

/* The new instance's address is taken before the class's create callback runs, and the object goes
 * there after it, as in the original (a create that made another object of its class would move the
 * table under it). */
uint32_t vcObjectCreate(uint32_t type)
{
    uint32_t cls = vcClassByType(type), instance, handle;

    vcClassFindFreeInstance(cls);
    if (vcClass_free_index(cls) == vcClass_capacity(cls)) {
        int32_t capacity = vcClass_capacity(cls) ? vcClass_capacity(cls) * 2 : FIRST_INSTANCES;
        uint32_t table = calloc_table((uint32_t)capacity, vcInstance_SIZE);

        guest_copy(table, vcClass_instances(cls), (uint32_t)vcClass_capacity(cls) * vcInstance_SIZE);
        CALL(crt_free, vcClass_instances(cls));
        vcClass_instances(cls) = table;
        vcClass_capacity(cls) = capacity;
        vcObjectCacheHandle = 0;
        vcObjectCacheData = 0;
    }
    instance = instance_at(cls, (uint32_t)vcClass_free_index(cls));
    handle = HANDLE(type, vcClass_free_index(cls));
    vcInstance_name(instance)[0] = 0;
    vcInstance_flags(instance) = CHANGED_ALL;
    vcInstance_refs(instance) = 1;
    vcInstance_object(instance) = CALL_AT(vcClassDesc_create(cls), handle);
    vcClass_count(cls)++;
    if (vcClass_count(cls) > vcClass_peak(cls))
        vcClass_peak(cls) = vcClass_count(cls);
    return handle;
}
ENTRY_CDECL1(vcObjectCreate)

uint32_t vcObjectAddRef(uint32_t handle)
{
    if (handle)
        vcInstance_refs(instance_of(handle))++;
    return handle;
}
ENTRY_CDECL1(vcObjectAddRef)

/* The references left; at none the class's destroy callback frees the object. A handle of 0, or one
 * with its top byte set, releases nothing and hands back eax as the caller left it, as the original
 * (a caller reads it). */
uint32_t vcObjectRelease(uint32_t handle)
{
    uint32_t index = INDEX_OF(handle), cls, instance;
    int32_t refs;

    if (!handle || (handle & 0xFF000000u))
        return EAX_AS_CALLER_LEFT;
    cls = class_of(handle);
    instance = instance_at(cls, index);
    refs = --vcInstance_refs(instance);
    if (refs > 0)
        return (uint32_t)refs;
    CALL_AT(vcClassDesc_destroy(cls), handle, vcInstance_object(instance));
    vcInstance_object(instance) = 0;
    vcInstance_name(instance)[0] = 0;
    vcClass_count(cls)--;
    if ((int32_t)index < vcClass_free_index(cls))
        vcClass_free_index(cls) = (int32_t)index;
    if (handle == vcObjectCacheHandle) {
        vcObjectCacheHandle = 0;
        vcObjectCacheData = 0;
    }
    return 0;
}
ENTRY_CDECL1(vcObjectRelease)

uint32_t vcObjectClone(uint32_t handle)
{
    uint32_t cls, clone;

    if (!handle)
        return 0;
    cls = class_of(handle);
    clone = vcObjectCreate(TYPE_OF(handle));
    CALL_AT(vcClassDesc_copy(cls), clone, vcInstance_object(instance_at(cls, INDEX_OF(handle))));
    return clone;
}
ENTRY_CDECL1(vcObjectClone)

uint32_t vcObjectGetName(uint32_t handle)
{
    return vcInstance_name_VA(instance_of(handle));
}
ENTRY_CDECL1(vcObjectGetName)

void vcObjectMarkChanged(uint32_t handle)
{
    vcInstance_flags(instance_of(handle)) |= CHANGED_DATA;
}
ENTRY_CDECL1_VOID(vcObjectMarkChanged)

void vcObjectClearChanged(uint32_t handle)
{
    vcInstance_flags(instance_of(handle)) &= ~CHANGED_ALL;
}
ENTRY_CDECL1_VOID(vcObjectClearChanged)

uint32_t vcObjectGetSize(uint32_t handle, uint32_t what)
{
    uint32_t cls, instance, get_size;

    if (!handle)
        return 0;
    cls = class_of(handle);
    instance = instance_at(cls, INDEX_OF(handle));
    get_size = vcClassDesc_get_size(cls);
    return get_size ? CALL_AT(get_size, handle, vcInstance_object(instance), what) : 0;
}
ENTRY_CDECL2(vcObjectGetSize)

/* ── Names ───────────────────────────────────────────────────────────────────────────────────────── */

static int names_match(uint32_t name, uint32_t instance)
{
    return !name || CALL(crt_stricmp, name, vcInstance_name_VA(instance)) == 0;
}

/* From a handle's index on, every instance of the class; from none, the instances in use up to the
 * class's count of them. */
uint32_t vcObjectFind(uint32_t type, uint32_t name, uint32_t from)
{
    uint32_t cls = vcClassByType(type);

    if (!from) {
        uint32_t instance = vcClass_instances(cls), index = 0;
        int32_t seen = 0;

        if (vcClass_count(cls) <= 0)
            return 0;
        do {
            if (vcInstance_refs(instance) > 0) {
                if (names_match(name, instance))
                    return HANDLE(type, index);
                seen++;
            }
            instance += vcInstance_SIZE;
            index++;
        } while (seen < vcClass_count(cls));
        return 0;
    }
    {
        uint32_t index = INDEX_OF(from), instance = instance_at(cls, index);

        if ((int32_t)index >= vcClass_capacity(cls))
            return 0;
        do {
            if (vcInstance_refs(instance) > 0 && names_match(name, instance))
                return HANDLE(type, index);
            index++;
            instance += vcInstance_SIZE;
        } while ((int32_t)index < vcClass_capacity(cls));
        return 0;
    }
}
ENTRY_CDECL3(vcObjectFind)

/* At most NAME_BYTES bytes, the terminator among them if it fits. */
int32_t vcObjectSetName(uint32_t handle, uint32_t name)
{
    uint32_t type = TYPE_OF(handle);
    int named = vcObjectFind(type, name, 0) != 0;
    uint32_t cls = vcClassByType(type), instance;

    if ((vcClassDesc_flags(cls) & CLASS_OWN_FILES) && named)
        return 0;
    instance = instance_at(cls, INDEX_OF(handle));
    vcInstance_name(instance)[0] = 0;
    if (name) {
        uint32_t bytes = guest_strlen(name) + 1;

        guest_copy(vcInstance_name_VA(instance), name, bytes < NAME_BYTES ? bytes : NAME_BYTES);
        vcStrLower(vcInstance_name_VA(instance));
    }
    vcInstance_flags(instance) |= CHANGED_NAME;
    return 1;
}
ENTRY_CDECL2(vcObjectSetName)

uint32_t vcObjectGetShared(uint32_t type, uint32_t name)
{
    uint32_t handle = vcObjectFind(type, name, 0);

    if (handle) {
        if (vcClassDesc_flags(vcClassByType(type)) & CLASS_CLONE_SHARED) {
            uint32_t clone = vcObjectClone(handle);

            vcObjectSetName(clone, vcObjectGetName(handle));
            return clone;
        }
        vcInstance_refs(instance_of(handle))++;
        return handle;
    }
    if (vcObjectReportMissing && !(vcClassDesc_flags(vcClassByType(type)) & CLASS_QUIET_MISSING)) {
        uint32_t cls = vcClassByType(type);

        CALL(vcFormat_entry, vcMissingObjectFormat_VA, vcClassDesc_name_VA(cls), name, vcClassDesc_file_tag_VA(cls));
    }
    return 0;
}
ENTRY_CDECL2(vcObjectGetShared)

/* ── Saving: what changed ────────────────────────────────────────────────────────────────────────── */

/* The instance is the one there was before the class's collect callback ran. */
int32_t vcObjectCollectChanged(uint32_t handle, uint32_t list)
{
    uint32_t instance, changed;

    if (!handle)
        return 0;
    instance = instance_of(handle);
    changed = CALL_AT(vcClassDesc_collect(class_of(handle)), handle, vcInstance_object(instance),
                      vcInstance_flags(instance), list);
    if (vcClassDesc_flags(class_of(handle)) & CLASS_OWN_FILES) {
        if (!vcCollectList_whole(list) && !(vcInstance_flags(instance) & (CHANGED_NAME | CHANGED_NEW))) {
            if (!(changed & CHANGED_DATA))
                return 0;
            MEM32(list + COLLECT_HANDLES + 4u * vcCollectList_count(list)) = handle;
            vcCollectList_count(list)++;
            return 0;
        }
        vcInstance_flags(instance) |= CHANGED_DATA;
        MEM32(list + COLLECT_HANDLES + 4u * vcCollectList_count(list)) = handle;
        vcCollectList_count(list)++;
        return 1;
    }
    return (changed & CHANGED_ALL) || vcCollectList_whole(list);
}
ENTRY_CDECL2(vcObjectCollectChanged)

/* ── The release queue ───────────────────────────────────────────────────────────────────────────── */

/* With check 0 the object is queued without asking its class. The queue keeps a reference. */
void vcObjectReleaseLater(uint32_t handle, uint32_t check)
{
    uint32_t instance, in_use;

    if (!handle)
        return;
    instance = instance_of(handle);
    in_use = vcClassDesc_in_use(class_of(handle));
    if (!in_use || (check && !CALL_AT(in_use, handle, vcInstance_object(instance), vcGameTime))) {
        vcInstance_flags(instance) &= ~QUEUED;
        return;
    }
    if (vcInstance_flags(instance) & QUEUED)
        return;
    if (vcReleaseQueueCount == vcReleaseQueueCapacity) {
        int32_t capacity = vcReleaseQueueCapacity ? vcReleaseQueueCapacity * 2 : FIRST_QUEUE;
        uint32_t table = calloc_table((uint32_t)capacity, 4);

        guest_copy(table, vcReleaseQueue, (uint32_t)vcReleaseQueueCapacity * 4u);
        CALL(crt_free, vcReleaseQueue);
        vcReleaseQueue = table;
        vcReleaseQueueCapacity = capacity;
    }
    vcInstance_refs(instance)++;
    MEM32(vcReleaseQueue + 4u * (uint32_t)vcReleaseQueueCount) = handle;
    vcReleaseQueueCount++;
    vcInstance_flags(instance) |= QUEUED;
}
ENTRY_CDECL2_VOID(vcObjectReleaseLater)

/* An object nothing else refers to is destroyed (its instance is not handed out again from free_index,
 * nor the lookup cache cleared, as in the original); one still in use stays; the rest leave the queue
 * with its reference. */
void vcObjectReleaseQueued(void)
{
    uint32_t time = vcGameTime;
    int32_t kept = 0, i;

    for (i = 0; i < vcReleaseQueueCount; i++) {
        uint32_t handle = MEM32(vcReleaseQueue + 4u * (uint32_t)i), cls = class_of(handle);
        uint32_t instance = instance_at(cls, INDEX_OF(handle)), in_use;

        if (vcInstance_refs(instance) - 1 <= 0) {
            uint32_t object = vcInstance_object(instance);

            vcInstance_refs(instance) = 0;
            CALL_AT(vcClassDesc_destroy(cls), handle, object);
            vcInstance_object(instance) = 0;
            vcInstance_name(instance)[0] = 0;
            vcClass_count(cls)--;
            continue;
        }
        in_use = vcClassDesc_in_use(cls);
        if (in_use && CALL_AT(in_use, handle, vcInstance_object(instance), time)) {
            MEM32(vcReleaseQueue + 4u * (uint32_t)kept++) = handle;
            continue;
        }
        vcInstance_flags(instance) &= ~QUEUED;
        vcInstance_refs(instance)--;
    }
    vcReleaseQueueCount = kept;
}
ENTRY_CDECL0_VOID(vcObjectReleaseQueued)

/* Every object of every class is gone over (with a callback that does nothing) before its table is
 * freed; the queue's table is freed and left as it was. */
void vcObjectSystemShutdown(void)
{
    uint32_t type;

    CALL(crt_free, vcReleaseQueue);
    for (type = 0; type < TYPES; type++)
        if (vcClassByType(type)) {
            vcClassForEach(type, vcDefault_ReturnOne_VA, -1, type);
            CALL(crt_free, vcClass_instances(vcClassByType(type)));
            vcClassByType(type) = 0;
        }
    vcObjectReportMissing = 0;
    vcFileClose(vcObjectSystemFile_VA);
}
ENTRY_CDECL0_VOID(vcObjectSystemShutdown)

/* ── Reading objects from files ──────────────────────────────────────────────────────────────────── */

/* A chunk: its tag (vcFileChunkEnd ends them), its version and the file offset it ends at. */
#define CHUNK_FRAME         0xCu    /* the original's 8 bytes of locals, and the word it keeps in its
                                       second argument's slot (decomp.h, FRAME_TAKE) */
#define CHUNK_TAG           0x0u    /* offsets in the frame */
#define CHUNK_VERSION       0x4u
#define CHUNK_END           0x8u

int32_t vcObjectLoadChunk(uint32_t file, uint32_t handle)
{
    uint32_t frame = FRAME_TAKE(CHUNK_FRAME), cls = class_of(handle), instance = instance_at(cls, INDEX_OF(handle));
    uint32_t load_chunk, version;
    int32_t loaded = 0;

    MEM32(frame + CHUNK_END) = 0;
    MEM32(frame + CHUNK_TAG) = 0;
    MEM32(frame + CHUNK_VERSION) = 0;
    vcFileReadU32(file, frame + CHUNK_TAG);
    if (MEM32(frame + CHUNK_TAG) != MEM32(vcFileChunkEnd_VA)) {
        vcFileReadU32(file, frame + CHUNK_VERSION);
        vcFileReadU32(file, frame + CHUNK_END);
        version = MEM32(frame + CHUNK_VERSION);
        load_chunk = vcClassDesc_load_chunk(cls);
        if (version <= vcClassDesc_chunk_version(cls) && load_chunk
            && CALL_AT(load_chunk, handle, file, version, vcInstance_object(instance)))
            loaded = 1;
        vcFileSeek(file, MEM32(frame + CHUNK_END));
    }
    FRAME_GIVE(CHUNK_FRAME);
    return loaded;
}
ENTRY_CDECL2(vcObjectLoadChunk)

/* The locals of vcObjectGet: its frame and where each one sits in it. */
#define GET_FRAME           0x6Cu   /* the original's 0x68 bytes, and the word it keeps in its second
                                       argument's slot, the file's first word */
#define GET_SECOND_WORD     0x00u   /* the file's second word, read and not used */
#define GET_FILE            0x04u   /* a vcFile */
#define GET_NAME            0x28u   /* the name, lower case */
#define GET_MAGIC           0x68u

uint32_t vcObjectGet(uint32_t type, uint32_t name)
{
    uint32_t frame, file, cls, loaded = 0, n = 0;
    int32_t i;

    if (!name || !MEM8(name))
        return 0;
    {
        uint32_t shared = vcObjectGetShared(type, name);

        if (shared)
            return shared;
    }
    frame = FRAME_TAKE(GET_FRAME);
    file = frame + GET_FILE;
    do
        MEM8(frame + GET_NAME + n) = MEM8(name + n);
    while (MEM8(name + n++));
    vcStrLower(frame + GET_NAME);
    cls = vcClassByType(type);
    CALL(vcFormat_entry, vcObjectPathFormat_VA, vcDataDir_VA, vcGetPlatformName(), vcClassDesc_name_VA(cls),
         frame + GET_NAME, vcClassDesc_file_tag_VA(cls));
    if (!vcFileOpen(file, vcFormatLast())) {
        FRAME_GIVE(GET_FRAME);
        return 0;
    }
    vcFileReadU32(file, frame + GET_MAGIC);
    if (MEM32(frame + GET_MAGIC) != MEM32(vcFileMagicVC1_VA) && MEM32(frame + GET_MAGIC) == MEM32(vcFileMagicVC2_VA)) {
        MEM32(frame + GET_SECOND_WORD) = 0xFFFFFFFFu;
        vcFileReadU32(file, frame + GET_SECOND_WORD);
        vcFile_by_name(file) = 1;
        loaded = vcObjectLoad(file);
        if (loaded) {
            MEM32(frame + GET_MAGIC) = 0;
            vcFileReadU32(file, frame + GET_MAGIC);
        }
    }
    for (i = 0; i < vcFile_object_count(file); i++)
        vcObjectRelease(MEM32(vcFile_objects(file) + 4u * (uint32_t)i));
    vcFileFreeObjects(file);
    vcFileClose(file);
    FRAME_GIVE(GET_FRAME);
    return loaded;
}
ENTRY_CDECL2(vcObjectGet)

/* An object's header in a file: whether one is there, the index of one read before in the same file
 * (negative: a new one), its type, its flags (bit 0: an object the game finds by name, not in the
 * file), its name, four words, and then, for one in the file, its version and the offset it ends at.
 * The locals of vcObjectLoad and vcObjectReload: their frames and where each one sits in them. */
#define LOAD_FRAME          0x144u
#define LOAD_NAME_BYTES     0x00u   /* u16 */
#define LOAD_TYPE           0x04u
#define LOAD_VERSION        0x08u
#define LOAD_END            0x0Cu
#define LOAD_INDEX          0x10u
#define LOAD_FLAGS          0x14u
#define LOAD_INSTANCE_OFFSET 0x18u  /* the new instance's offset in its class's table */
#define LOAD_FILE_INDEX     0x1Cu   /* the new object's index among the file's */
#define LOAD_INSTANCE       0x20u   /* the new instance */
#define LOAD_PRESENT        0x24u
#define LOAD_CLASS_SLOT     0x28u   /* the new object's entry in vcClassByType */
#define LOAD_WORD_UNUSED    0x2Cu   /* a word read and not used */
#define LOAD_WORDS          0x30u   /* the four words */
#define LOAD_NAME           0x40u
#define RELOAD_FRAME        0x134u
#define RELOAD_TYPE         0x00u
#define RELOAD_NAME_BYTES   0x04u   /* u16 */
#define RELOAD_INDEX        0x08u   /* then the object's index among the file's */
#define RELOAD_FLAGS        0x0Cu
#define RELOAD_END          0x10u
#define RELOAD_VERSION      0x14u
#define RELOAD_PRESENT      0x18u
#define RELOAD_WORD_UNUSED  0x1Cu
#define RELOAD_WORDS        0x20u
#define RELOAD_NAME         0x30u

/* The header up to the four words, and the file then on a multiple of 4. */
static void read_header(uint32_t file, uint32_t type, uint32_t flags, uint32_t name_bytes, uint32_t name,
                        uint32_t words)
{
    vcFileReadU32(file, type);
    vcFileReadU32(file, flags);
    vcFileReadU16(file, name_bytes);
    vcFileReadBytes(file, name, MEM16(name_bytes));
    vcFileReadU32s(file, words, 4);
    vcFileSeek(file, (vcFileTell(file) + FILE_BLOCK - 1) & ~(FILE_BLOCK - 1));
}

static uint32_t load_object(uint32_t file, uint32_t frame)
{
    uint32_t handle;

    vcFileReadU32(file, frame + LOAD_PRESENT);
    if (!MEM32(frame + LOAD_PRESENT))
        return 0;
    vcFileReadU32(file, frame + LOAD_INDEX);
    if ((int32_t)MEM32(frame + LOAD_INDEX) >= 0) {
        uint32_t read_before = MEM32(vcFile_objects(file) + 4u * MEM32(frame + LOAD_INDEX));

        if (read_before)
            vcInstance_refs(instance_of(read_before))++;
        return MEM32(vcFile_objects(file) + 4u * MEM32(frame + LOAD_INDEX));
    }
    read_header(file, frame + LOAD_TYPE, frame + LOAD_FLAGS, frame + LOAD_NAME_BYTES, frame + LOAD_NAME,
                frame + LOAD_WORDS);
    if (MEM8(frame + LOAD_FLAGS) & 1) {
        handle = vcObjectGet(MEM32(frame + LOAD_TYPE), frame + LOAD_NAME);
        vcFileAddObject(file, handle);
    } else {
        vcFileReadU32(file, frame + LOAD_WORD_UNUSED);
        handle = vcObjectFind(MEM32(frame + LOAD_TYPE), frame + LOAD_NAME, 0);
        if (handle && !(vcClassDesc_flags(class_of(handle)) & CLASS_CLONE_SHARED)) {
            uint32_t reload;

            vcFileAddObject(file, handle);
            vcFileReadU32(file, frame + LOAD_VERSION);
            vcFileReadU32(file, frame + LOAD_END);
            reload = vcClassDesc_reload(vcClassByType(MEM32(frame + LOAD_TYPE)));
            if (reload)
                CALL_AT(reload, handle, file, MEM32(frame + LOAD_VERSION), vcInstance_object(instance_of(handle)));
            vcFileSeek(file, MEM32(frame + LOAD_END));
            vcObjectAddRef(handle);
        } else {
            uint32_t cls, instance, bytes;

            handle = vcObjectCreate(MEM32(frame + LOAD_TYPE));
            MEM32(frame + LOAD_INSTANCE_OFFSET) = INDEX_OF(handle) * vcInstance_SIZE;
            MEM32(frame + LOAD_CLASS_SLOT) = vcClassByType_VA + 4u * TYPE_OF(handle);
            instance = vcClass_instances(MEM32(MEM32(frame + LOAD_CLASS_SLOT))) + MEM32(frame + LOAD_INSTANCE_OFFSET);
            MEM32(frame + LOAD_INSTANCE) = instance;
            MEM32(frame + LOAD_FILE_INDEX) = vcFileAddObject(file, handle);
            bytes = MEM16(frame + LOAD_NAME_BYTES) < NAME_BYTES ? MEM16(frame + LOAD_NAME_BYTES) : NAME_BYTES;
            guest_copy(vcInstance_name_VA(instance), frame + LOAD_NAME, bytes);
            vcFileReadU32(file, frame + LOAD_VERSION);
            vcFileReadU32(file, frame + LOAD_END);
            cls = vcClassByType(MEM32(frame + LOAD_TYPE));
            if (MEM32(frame + LOAD_VERSION) <= vcClassDesc_version(cls)
                && CALL_AT(vcClassDesc_load(cls), handle, file, MEM32(frame + LOAD_VERSION),
                           vcInstance_object(MEM32(frame + LOAD_INSTANCE)))) {
                uint32_t table = vcClass_instances(MEM32(MEM32(frame + LOAD_CLASS_SLOT)));

                vcInstance_flags(table + MEM32(frame + LOAD_INSTANCE_OFFSET)) &= ~CHANGED_ALL;
            } else {
                MEM32(vcFile_objects(file) + 4u * MEM32(frame + LOAD_FILE_INDEX)) = 0;
                vcObjectRelease(handle);
                handle = 0;
            }
            vcFileSeek(file, MEM32(frame + LOAD_END));
        }
    }
    if (handle)
        vcInstance_refs(instance_of(handle))++;
    return handle;
}

uint32_t vcObjectLoad(uint32_t file)
{
    uint32_t frame = FRAME_TAKE(LOAD_FRAME), handle = load_object(file, frame);

    FRAME_GIVE(LOAD_FRAME);
    return handle;
}
ENTRY_CDECL1(vcObjectLoad)

/* An object read again, from the header of one in a file: the given handle, or the object of that
 * name. Without a handle given and none of that name, the class of type 0's first instance is handed
 * to the class's reload callback, as in the original. */
static uint32_t reload_object(uint32_t file, uint32_t given, uint32_t frame)
{
    uint32_t handle;

    vcFileReadU32(file, frame + RELOAD_PRESENT);
    if (!MEM32(frame + RELOAD_PRESENT))
        return 0;
    vcFileReadU32(file, frame + RELOAD_INDEX);
    if ((int32_t)MEM32(frame + RELOAD_INDEX) >= 0)
        return MEM32(vcFile_objects(file) + 4u * MEM32(frame + RELOAD_INDEX));
    read_header(file, frame + RELOAD_TYPE, frame + RELOAD_FLAGS, frame + RELOAD_NAME_BYTES, frame + RELOAD_NAME,
                frame + RELOAD_WORDS);
    if (MEM8(frame + RELOAD_FLAGS) & 1) {
        handle = vcObjectGet(MEM32(frame + RELOAD_TYPE), frame + RELOAD_NAME);
        vcFileAddObject(file, handle);
    } else {
        uint32_t found, reload;

        vcFileReadU32(file, frame + RELOAD_WORD_UNUSED);
        found = vcObjectFind(MEM32(frame + RELOAD_TYPE), frame + RELOAD_NAME, 0);
        handle = given ? given : found;
        MEM32(frame + RELOAD_INDEX) = vcFileAddObject(file, handle);
        vcFileReadU32(file, frame + RELOAD_VERSION);
        vcFileReadU32(file, frame + RELOAD_END);
        reload = vcClassDesc_reload(vcClassByType(MEM32(frame + RELOAD_TYPE)));
        if (reload)
            CALL_AT(reload, handle, file, MEM32(frame + RELOAD_VERSION), vcInstance_object(instance_of(handle)));
        vcFileSeek(file, MEM32(frame + RELOAD_END));
    }
    if (handle)
        vcInstance_refs(instance_of(handle))++;
    return handle;
}

uint32_t vcObjectReload(uint32_t file, uint32_t handle)
{
    uint32_t frame = FRAME_TAKE(RELOAD_FRAME), reloaded = reload_object(file, handle, frame);

    FRAME_GIVE(RELOAD_FRAME);
    return reloaded;
}
ENTRY_CDECL2(vcObjectReload)

/* ── The classes' defaults ───────────────────────────────────────────────────────────────────────── */

/* What a class gives for a callback that has nothing to do: hands back 0. */
uint32_t vcDefault_ReturnZero(void)
{
    return 0;
}
ENTRY_CDECL0(vcDefault_ReturnZero)

/* What a class gives for a callback that only has to succeed: hands back 1. */
uint32_t vcDefault_ReturnOne(void)
{
    return 1;
}
ENTRY_CDECL0(vcDefault_ReturnOne)

/* What a class with no children gives for its collect callback: hands back the changed bits it was
 * given, its third argument. */
uint32_t vcDefault_ReturnArg3(uint32_t handle, uint32_t object, uint32_t changed)
{
    (void)handle;
    (void)object;
    return changed;
}
ENTRY_CDECL3(vcDefault_ReturnArg3)
