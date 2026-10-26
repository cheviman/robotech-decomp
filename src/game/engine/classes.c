/**
 *    Name:        engine/classes.c
 *    Description: the engine's classes, written in C: their registrations, each a descriptor built and handed to
 *                 vcRegisterClass
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    A class's registration builds its vcClassDesc on its stack, zeroed, and hands it to vcRegisterClass
 *    with the capacity of its table of instances: its type, its name, the tag of its files, the
 *    versions of the object and of its chunks its callbacks read, its flags and its callbacks (the
 *    guest addresses of the class's functions, still recompiled, or of the defaults). Here each one is
 *    a table, class_registration, and register_class builds the descriptor from it. These are the
 *    registrations that do only that; the others (vcLight, vcMesh, vcSound, vcMusic, gcLevel and the
 *    classes that register a scene object's functions as well) stay recompiled.
 *
 *    The registrations of vcTexture, vcSnd and vcSFXBank take their chunk version from a call to
 *    vcDefault_ReturnOne, which hands back 1; here it is the 1.
 */
#include "decomp.h"
#include "objects.h"
#include "classes.h"

struct class_registration {
    uint32_t type;
    const char *name;
    const char *file_tag;           /* three letters at most */
    uint32_t version, chunk_version, flags;
    int32_t capacity;
    uint32_t create, destroy, collect, load, reload, load_chunk, copy, in_use, get_size;
};

static const struct class_registration vcTexture_registration = {
    .type = 0x01, .name = "vcTexture", .file_tag = "txr", .version = 7, .chunk_version = 1,   /* vcDefault_ReturnOne() */
    .flags = CLASS_OWN_FILES, .capacity = 256,
    .create = vcTexture_Create_VA,
    .destroy = vcTexture_Destroy_VA,
    .collect = vcTexture_Collect_VA,
    .load = vcTexture_Load_VA,
    .reload = vcTexture_Reload_VA,
    .load_chunk = vcTexture_LoadChunk_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcTexture_GetSize_VA,
};

static const struct class_registration vcMaterial_registration = {
    .type = 0x02, .name = "vcMaterial", .file_tag = "mtl", .version = 10, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 256,
    .create = vcMaterial_Create_VA,
    .destroy = vcMaterial_Destroy_VA,
    .collect = vcMaterial_Collect_VA,
    .load = vcMaterial_Load_VA,
    .reload = vcMaterial_Reload_VA,
    .copy = vcMaterial_Copy_VA,
    .get_size = vcMaterial_GetSize_VA,
};

static const struct class_registration vcSpline_registration = {
    .type = 0x04, .name = "vcSpline", .file_tag = "spl", .version = 1, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 32,
    .create = vcSpline_Create_VA,
    .destroy = vcSpline_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcSpline_Load_VA,
    .copy = vcSpline_Copy_VA,
    .get_size = vcSpline_GetSize_VA,
};

static const struct class_registration vcSceneExport_registration = {
    .type = 0x08, .name = "vcSceneExport", .file_tag = "vxo", .version = 2, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 256,
    .create = vcSceneExport_Create_VA,
    .destroy = vcSceneExport_Destroy_VA,
    .collect = vcSceneExport_Collect_VA,
    .load = vcSceneExport_Load_VA,
    .reload = vcSceneExport_Reload_VA,
    .copy = vcSceneExport_Copy_VA,
    .get_size = vcSceneExport_GetSize_VA,
};

static const struct class_registration vcMotionFiles_registration = {
    .type = 0x09, .name = "vcMotionFiles", .file_tag = "vmf", .version = 7, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 256,
    .create = vcMotionFiles_Create_VA,
    .destroy = vcMotionFiles_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcMotionFiles_Load_VA,
    .copy = vcMotionFiles_Copy_VA,
    .get_size = vcMotionFiles_GetSize_VA,
};

static const struct class_registration vcMultiSub_registration = {
    .type = 0x0A, .name = "vcMultiSub", .file_tag = "vmo", .version = 1, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 64,
    .create = vcMultiSub_Create_VA,
    .destroy = vcMultiSub_Destroy_VA,
    .collect = vcMultiSub_Collect_VA,
    .load = vcMultiSub_Load_VA,
    .reload = vcMultiSub_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcMultiSub_GetSize_VA,
};

static const struct class_registration vcSnd_registration = {
    .type = 0x0F, .name = "vcSnd", .file_tag = "snd", .version = 1, .chunk_version = 1,   /* vcDefault_ReturnOne() */
    .flags = CLASS_OWN_FILES, .capacity = 64,
    .create = vcSnd_Create_VA,
    .destroy = vcSnd_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcSnd_Load_VA,
    .load_chunk = vcSnd_LoadChunk_VA,
    .copy = vcDefault_ReturnZero_VA,
    .in_use = vcSnd_InUse_VA,
    .get_size = vcSnd_GetSize_VA,
};

static const struct class_registration vcRefObject_registration = {
    .type = 0x10, .name = "vcRefObject", .file_tag = "", .version = 1, .chunk_version = 0,
    .flags = CLASS_CLONE_SHARED, .capacity = 64,
    .create = vcRefObject_Create_VA,
    .destroy = vcRefObject_Destroy_VA,
    .collect = vcRefObject_Collect_VA,
    .load = vcRefObject_Load_VA,
    .reload = vcRefObject_Reload_VA,
    .copy = vcRefObject_Copy_VA,
    .in_use = vcRefObject_InUse_VA,
    .get_size = vcRefObject_GetSize_VA,
};

static const struct class_registration vcSkybox_registration = {
    .type = 0x11, .name = "vcSkybox", .file_tag = "sky", .version = 1, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 8,
    .create = vcSkybox_Create_VA,
    .destroy = vcSkybox_Destroy_VA,
    .collect = vcSkybox_Collect_VA,
    .load = vcSkybox_Load_VA,
    .reload = vcSkybox_Reload_VA,
    .copy = vcSkybox_Copy_VA,
    .get_size = vcSkybox_GetSize_VA,
};

static const struct class_registration vcStringManager_registration = {
    .type = 0x12, .name = "vcStringManager", .file_tag = "st", .version = 1, .chunk_version = 0,
    .flags = CLASS_CLONE_SHARED, .capacity = 4,
    .create = vcStringManager_Create_VA,
    .destroy = vcStringManager_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcStringManager_Load_VA,
    .copy = vcStringManager_Copy_VA,
    .get_size = vcStringManager_GetSize_VA,
};

static const struct class_registration vcSpaceScene_registration = {
    .type = 0x15, .name = "vcSpaceScene", .file_tag = "spc", .version = 2, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 2,
    .create = vcSpaceScene_Create_VA,
    .destroy = vcSpaceScene_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcSpaceScene_Load_VA,
    .reload = vcSpaceScene_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcSpaceScene_GetSize_VA,
};

static const struct class_registration vcLineEffect_registration = {
    .type = 0x16, .name = "vcLineEffect", .file_tag = "lne", .version = 0, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 4,
    .create = vcLineEffect_Create_VA,
    .destroy = vcLineEffect_Destroy_VA,
    .collect = vcLineEffect_Collect_VA,
    .load = vcLineEffect_Load_VA,
    .reload = vcLineEffect_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcLineEffect_GetSize_VA,
};

static const struct class_registration vcSkyScene_registration = {
    .type = 0x17, .name = "vcSkyScene", .file_tag = "skc", .version = 2, .chunk_version = 0,
    .flags = CLASS_CLONE_SHARED, .capacity = 8,
    .create = vcSkyScene_Create_VA,
    .destroy = vcSkyScene_Destroy_VA,
    .collect = vcDefault_CollectFirstChild_VA,
    .load = vcSkyScene_Load_VA,
    .reload = vcSkyScene_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcSkyScene_GetSize_VA,
};

static const struct class_registration vcLensFlare_registration = {
    .type = 0x18, .name = "vcLensFlare", .file_tag = "lnf", .version = 1, .chunk_version = 0,
    .flags = CLASS_CLONE_SHARED, .capacity = 8,
    .create = vcLensFlare_Create_VA,
    .destroy = vcLensFlare_Destroy_VA,
    .collect = vcLensFlare_Collect_VA,
    .load = vcLensFlare_Load_VA,
    .reload = vcLensFlare_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .in_use = vcDefault_ReturnZero_VA,
    .get_size = vcLensFlare_GetSize_VA,
};

static const struct class_registration vcPak_registration = {
    .type = 0x1C, .name = "vcPak", .file_tag = "pak", .version = 1, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 16,
    .create = vcPak_Create_VA,
    .destroy = vcPak_Destroy_VA,
    .collect = vcPak_Collect_VA,
    .load = vcPak_Load_VA,
    .reload = vcPak_Reload_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcPak_GetSize_VA,
};

static const struct class_registration vcDecalMgr_registration = {
    .type = 0x1F, .name = "vcDecalMgr", .file_tag = "dcm", .version = 0, .chunk_version = 0,
    .flags = CLASS_CLONE_SHARED, .capacity = 4,
    .create = vcDecalMgr_Create_VA,
    .destroy = vcDecalMgr_Destroy_VA,
    .collect = vcDecalMgr_Collect_VA,
    .load = vcDefault_ReturnOne_VA,
    .copy = vcDefault_ReturnZero_VA,
    .in_use = vcDefault_ReturnOne_VA,
    .get_size = vcDecalMgr_GetSize_VA,
};

static const struct class_registration vcSFXBank_registration = {
    .type = 0x31, .name = "vcSFXBank", .file_tag = "sfb", .version = 1, .chunk_version = 1,   /* vcDefault_ReturnOne() */
    .flags = 0, .capacity = 16,
    .create = vcSFXBank_Create_VA,
    .destroy = vcSFXBank_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = vcSFXBank_Load_VA,
    .load_chunk = vcDefault_ReturnOne_VA,
    .copy = vcDefault_ReturnZero_VA,
    .get_size = vcSFXBank_GetSize_VA,
};

static const struct class_registration gcComponent_registration = {
    .type = 0x21, .name = "gcComponent", .file_tag = "cmp", .version = 0, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 64,
    .create = gcComponent_Create_VA,
    .destroy = gcComponent_Destroy_VA,
    .collect = gcComponent_Collect_VA,
    .load = gcComponent_Load_VA,
    .copy = vcDefault_ReturnZero_VA,
    .in_use = vcDefault_ReturnZero_VA,
    .get_size = gcComponent_GetSize_VA,
};

static const struct class_registration gcAIData_registration = {
    .type = 0x22, .name = "gcAIData", .file_tag = "spt", .version = 0, .chunk_version = 0,
    .flags = CLASS_OWN_FILES, .capacity = 4,
    .create = gcComponent_Create_VA,
    .destroy = gcComponent_Destroy_VA,
    .collect = vcDefault_ReturnArg3_VA,
    .load = gcAIData_Load_VA,
    .copy = vcDefault_ReturnZero_VA,
    .in_use = vcDefault_ReturnZero_VA,
    .get_size = gcComponent_GetSize_VA,
};

/* The descriptor, in the guest's stack where the original builds it. */
static void register_class(const struct class_registration *r)
{
    uint32_t desc = FRAME_TAKE(vcClassDesc_SIZE);

    guest_zero(desc, vcClassDesc_SIZE);
    vcClassDesc_type(desc) = r->type;
    guest_put_string(vcClassDesc_name_VA(desc), r->name);
    guest_put_string(vcClassDesc_file_tag_VA(desc), r->file_tag);
    vcClassDesc_version(desc) = r->version;
    vcClassDesc_chunk_version(desc) = r->chunk_version;
    vcClassDesc_flags(desc) = r->flags;
    vcClassDesc_create(desc) = r->create;
    vcClassDesc_destroy(desc) = r->destroy;
    vcClassDesc_collect(desc) = r->collect;
    vcClassDesc_load(desc) = r->load;
    vcClassDesc_reload(desc) = r->reload;
    vcClassDesc_load_chunk(desc) = r->load_chunk;
    vcClassDesc_copy(desc) = r->copy;
    vcClassDesc_in_use(desc) = r->in_use;
    vcClassDesc_get_size(desc) = r->get_size;
    vcRegisterClass(desc, r->capacity);
    FRAME_GIVE(vcClassDesc_SIZE);
}

void vcTexture_Register(void)
{
    register_class(&vcTexture_registration);
}
ENTRY_CDECL0_VOID(vcTexture_Register)

void vcMaterial_Register(void)
{
    register_class(&vcMaterial_registration);
}
ENTRY_CDECL0_VOID(vcMaterial_Register)

void vcSpline_Register(void)
{
    register_class(&vcSpline_registration);
}
ENTRY_CDECL0_VOID(vcSpline_Register)

void vcSceneExport_Register(void)
{
    register_class(&vcSceneExport_registration);
}
ENTRY_CDECL0_VOID(vcSceneExport_Register)

void vcMotionFiles_Register(void)
{
    register_class(&vcMotionFiles_registration);
}
ENTRY_CDECL0_VOID(vcMotionFiles_Register)

void vcMultiSub_Register(void)
{
    register_class(&vcMultiSub_registration);
}
ENTRY_CDECL0_VOID(vcMultiSub_Register)

void vcSnd_Register(void)
{
    register_class(&vcSnd_registration);
}
ENTRY_CDECL0_VOID(vcSnd_Register)

void vcRefObject_Register(void)
{
    register_class(&vcRefObject_registration);
}
ENTRY_CDECL0_VOID(vcRefObject_Register)

void vcSkybox_Register(void)
{
    register_class(&vcSkybox_registration);
}
ENTRY_CDECL0_VOID(vcSkybox_Register)

void vcStringManager_Register(void)
{
    register_class(&vcStringManager_registration);
}
ENTRY_CDECL0_VOID(vcStringManager_Register)

void vcSpaceScene_Register(void)
{
    register_class(&vcSpaceScene_registration);
}
ENTRY_CDECL0_VOID(vcSpaceScene_Register)

void vcLineEffect_Register(void)
{
    register_class(&vcLineEffect_registration);
}
ENTRY_CDECL0_VOID(vcLineEffect_Register)

void vcSkyScene_Register(void)
{
    register_class(&vcSkyScene_registration);
}
ENTRY_CDECL0_VOID(vcSkyScene_Register)

void vcLensFlare_Register(void)
{
    register_class(&vcLensFlare_registration);
}
ENTRY_CDECL0_VOID(vcLensFlare_Register)

void vcPak_Register(void)
{
    register_class(&vcPak_registration);
}
ENTRY_CDECL0_VOID(vcPak_Register)

void vcDecalMgr_Register(void)
{
    register_class(&vcDecalMgr_registration);
}
ENTRY_CDECL0_VOID(vcDecalMgr_Register)

void vcSFXBank_Register(void)
{
    register_class(&vcSFXBank_registration);
}
ENTRY_CDECL0_VOID(vcSFXBank_Register)

void gcComponent_Register(void)
{
    register_class(&gcComponent_registration);
}
ENTRY_CDECL0_VOID(gcComponent_Register)

void gcAIData_Register(void)
{
    register_class(&gcAIData_registration);
}
ENTRY_CDECL0_VOID(gcAIData_Register)
