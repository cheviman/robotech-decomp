/**
 *    Name:        dsound_bridge.c
 *    Description: the game's DirectSound answered on the host: its buffers, its 3D and its listener, played by
 *                 sound_mixer.c
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game links the XDK's DirectSound, which drives the console's audio processor (the MCPX APU)
 *    through its registers; xboxrecomp can emulate that processor (RECOMP_AC97_READY=1, main.c), and the
 *    sound then goes through two emulations, the DirectSound's and the hardware's. Here the 29
 *    DirectSound entries the game and its Bink call (recomp_manual.c) are answered instead: a buffer is
 *    a voice of the host's mixer, reading its samples where the game keeps them. xboxrecomp's own
 *    DirectSound (src/audio) is a stub for titles that link none, without ADPCM, so the toolkit is
 *    used for the device (sound_mixer.c), not for this layer.
 *
 *    What a call does is what the XDK's DirectSound in the XBE does, read from it (CDirectSoundBuffer
 *    and CMcpxBuffer, the names in symbols.txt):
 *      - Positions are bytes from the start of the play region; an ADPCM buffer counts them a block at a
 *        time (frames = bytes / block << 6). Stop keeps the position and the next Play goes on from it,
 *        unless DSBPLAY_FROMSTART; a buffer that ends by itself starts again from its beginning.
 *        SetBufferData and SetPlayRegion stop it, or start it again from the region's start.
 *      - The write cursor is the play cursor plus 32 frames or a block, whichever is more.
 *      - The level is the volume less the headroom, both in hundredths of a decibel; a 2D buffer starts
 *        with 600 of headroom, a 3D one with none.
 *      - A buffer goes to the mixbins of its descriptor, or by default the front left and right (a 3D
 *        one, the 3D bins and the I3DL2 reverb's); with more than one channel, the mixbins take the
 *        channels in turn.
 *    Not done, and why (PENDING.md): the effects image (the I3DL2 reverb and the DSP's effects) is
 *    taken and not run; a mixbin is heard when it is a front one (0, 1) or a 3D one (6 to 9), the
 *    others (the centre, the LFE, the rear, the reverb and effect sends) are not mixed to the two
 *    sides; and the 3D is a distance and a pan from the listener, not the console's HRTF.
 *
 *    ROBOTECH_TRACE_DSOUND=1 logs each buffer created, with its format; every run ends with a line of
 *    the buffers and voices it had.
 */
#include <windows.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "dsound_bridge.h"
#include "sound_mixer.h"
#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax;
extern ptrdiff_t g_xbox_mem_offset;

/* HRESULTs */
#define DS_OK                   0x00000000u
#define DSERR_GENERIC           0x80004005u
#define DSERR_OUTOFMEMORY       0x8007000Eu
#define DSERR_INVALIDCALL       0x88780032u

/* The XDK's values the toolkit's dsound_xbox.h does not have */
#define DSBPLAY_FROMSTART       0x00000002u
#define DSBLOCK_FROMWRITECURSOR 0x00000001u
#define DSBLOCK_ENTIREBUFFER    0x00000002u
#define DS3D_IMMEDIATE          0u
/* buffers DirectSound gives no headroom: CTRL3D, and the ones mixed in from
 * other voices or effects (DSBCAPS_MIXIN, DSBCAPS_FXIN, DSBCAPS_FXIN2) */
#define DSBCAPS_NO_HEADROOM     (DSBCAPS_CTRL3D | 0x00182000u)
#define DSB_HEADROOM_2D         600
#define DSBVOLUME_MIN           (-10000)
/* What a voice loses on its way into a mixbin: each mixbin's headroom, 6 dB a
 * step, is 1 for bins 0 to 30 (the XDK's CDirectSoundSettings sets it so, and
 * the game never changes it). A 3D voice goes through the HRTF's headroom too,
 * which DirectSound sets to 0. That a 3D voice also loses its mixbin's is not
 * read from the XDK but measured: the first mission, recorded with it and on
 * the emulated APU, comes out 0.4 dB apart (the menu's 2D music, 0.1 dB). */
#define MIXBIN_HEADROOM_GAIN    0.5f
#define HRTF_HEADROOM_GAIN      1.0f

#define WAVE_PCM                0x0001u
#define WAVE_XBOX_ADPCM         0x0069u
#define WAVE_EXTENSIBLE         0xFFFEu
#define ADPCM_BLOCK_BYTES       36u         /* a block of one channel */

/* DSBUFFERDESC, WAVEFORMATEX and DSMIXBINS as the game lays them out */
#define DESC_FLAGS              4
#define DESC_BYTES              8
#define DESC_FORMAT             12
#define DESC_MIXBINS            16
#define WFX_CHANNELS            2
#define WFX_RATE                4
#define WFX_BLOCK_ALIGN         12
#define WFX_BITS                14

/* the mixbins this mix hears, as sides of the stereo out */
#define MIXBIN_FRONT_LEFT       0
#define MIXBIN_FRONT_RIGHT      1
#define MIXBIN_3D_FRONT_LEFT    6
#define MIXBIN_3D_FRONT_RIGHT   7
#define MIXBIN_3D_BACK_LEFT     8
#define MIXBIN_3D_BACK_RIGHT    9
#define MIXBIN_I3DL2            10
#define MIXBINS_MAX             8

#define BUFFERS_MAX             512
#define HANDLE_BYTES            32          /* the guest memory behind a handle; the game never reads it */

typedef struct Vector {
    float x, y, z;
} Vector;

typedef struct Listener {
    Vector position, front, top;
} Listener;

typedef struct Source3D {
    Vector position;
    float min_distance, max_distance;
} Source3D;

typedef struct DsBuffer {
    uint32_t handle;            /* what the game holds: its IDirectSoundBuffer * */
    uint32_t refs;
    uint32_t flags;             /* DSBCAPS_ */
    uint16_t tag;               /* the format's: WAVE_PCM or WAVE_XBOX_ADPCM */
    unsigned block_align;
    uint32_t data, bytes;       /* the samples, in guest memory */
    uint32_t own;               /* the samples' memory when DirectSound allocated it */
    uint32_t region, region_bytes;  /* the play region, from the data's first byte */
    uint32_t kept;              /* the position Stop kept, from the region's first byte */
    int32_t volume, headroom;   /* hundredths of a decibel */
    uint32_t frequency;         /* 0: as recorded */
    unsigned bins;
    uint8_t bin[MIXBINS_MAX];
    int32_t bin_volume[MIXBINS_MAX];
    Source3D set, heard;        /* the 3D as set (deferred too) and as applied */
    MixerVoice voice;
} DsBuffer;

static DsBuffer *s_buffers[BUFFERS_MAX];
static unsigned s_count;
static uint32_t s_free_handles[BUFFERS_MAX];
static unsigned s_free_count;
static uint32_t s_dsound, s_dsound_refs;    /* the one IDirectSound */
static Listener s_listener_set, s_listener = {
    { 0.0f, 0.0f, 0.0f }, { 0.0f, 0.0f, 1.0f }, { 0.0f, 1.0f, 0.0f },
};
static struct {
    unsigned created, adpcm, pcm, silent, released, alive_max;
} s_tally;

/* the default mixbins (the XDK's tables, 0x1711A4 and 0x171184) */
static const uint8_t BINS_2D[] = { MIXBIN_FRONT_LEFT, MIXBIN_FRONT_RIGHT };
static const uint8_t BINS_3D[] = { MIXBIN_3D_FRONT_LEFT, MIXBIN_3D_BACK_LEFT, MIXBIN_3D_FRONT_RIGHT,
                                   MIXBIN_3D_BACK_RIGHT, MIXBIN_I3DL2 };

/* ── The guest's side ─────────────────────────────────────── */

static uint32_t guest32(uint32_t va)
{
    return *(const volatile uint32_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static uint16_t guest16(uint32_t va)
{
    return *(const volatile uint16_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static void put32(uint32_t va, uint32_t value)
{
    if (va)
        *(volatile uint32_t *)((uintptr_t)va + g_xbox_mem_offset) = value;
}

/* Argument i of the stdcall being answered (the return address is at esp). */
static uint32_t arg(unsigned i)
{
    return guest32(g_esp + 4 + 4 * i);
}

static float arg_float(unsigned i)
{
    uint32_t bits = arg(i);
    float f;

    memcpy(&f, &bits, 4);
    return f;
}

/* ROBOTECH_TRACE_DSOUND: 1, the buffers; 2, every call too */
static int trace_level(void)
{
    static int level = -1;

    if (level < 0) {
        const char *e = getenv("ROBOTECH_TRACE_DSOUND");
        level = e ? atoi(e) : 0;
    }
    return level;
}

static int trace_on(void)
{
    return trace_level() >= 1;
}

/* A call, its arguments, what it returns and where from; for a Get, what it
 * wrote at the pointers it was handed. */
static void trace_call(const char *name, uint32_t value, unsigned args)
{
    unsigned i;

    fprintf(stderr, "[DSOUND] f%u %s(", d3d11_FrameCount(), name + sizeof "dsound_" - 1);
    for (i = 0; i < args; i++)
        fprintf(stderr, "%s%X", i ? ", " : "", arg(i));
    fprintf(stderr, ") = %X, from 0x%08X", value, guest32(g_esp));
    if (strstr(name, "_Get"))
        for (i = 1; i < args; i++)
            if (arg(i))
                fprintf(stderr, " [%X]", guest32(arg(i)));
    fprintf(stderr, "\n");
}

/* The stdcall's return: the value, the return address and the arguments popped. */
#define ret(value, args) stdcall_return(__func__, value, args)

static void stdcall_return(const char *name, uint32_t value, unsigned args)
{
    if (trace_level() >= 2)
        trace_call(name, value, args);
    g_eax = value;
    g_esp += 4 + 4 * args;
}

int dsound_Native(void)
{
    static int native = -1;

    if (native < 0)
        native = !getenv("RECOMP_AC97_READY");
    return native;
}

/* ── Buffers ───────────────────────────────────────────────── */

static DsBuffer *find(uint32_t handle)
{
    unsigned i;

    for (i = 0; i < s_count; i++)
        if (s_buffers[i]->handle == handle)
            return s_buffers[i];
    return NULL;
}

static uint32_t new_handle(void)
{
    return s_free_count ? s_free_handles[--s_free_count] : xbox_HeapAlloc(HANDLE_BYTES, 16);
}

static uint32_t bytes_to_frames(const DsBuffer *b, uint32_t bytes)
{
    uint32_t n = bytes / b->block_align;

    return b->tag == WAVE_XBOX_ADPCM ? n * MIXER_ADPCM_BLOCK : n;
}

static uint32_t frames_to_bytes(const DsBuffer *b, uint32_t frames)
{
    return b->tag == WAVE_XBOX_ADPCM ? frames / MIXER_ADPCM_BLOCK * b->block_align : frames * b->block_align;
}

static float level(int32_t millibels)
{
    if (millibels <= DSBVOLUME_MIN)
        return 0.0f;
    return powf(10.0f, (millibels > 0 ? 0 : millibels) / 2000.0f);
}

/* Where the voice reads: the data and the play region, in frames. */
static void set_source(DsBuffer *b)
{
    b->voice.data = b->data;
    b->voice.start = bytes_to_frames(b, b->region);
    b->voice.end = b->data ? bytes_to_frames(b, b->region + b->region_bytes) : 0;
}

static Vector sub(Vector a, Vector b)
{
    Vector v = { a.x - b.x, a.y - b.y, a.z - b.z };

    return v;
}

static float dot(Vector a, Vector b)
{
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

/* A 3D buffer as the listener hears it: fainter with distance as DirectSound's
 * 3D has it (the minimum distance over the distance, held from the maximum
 * on), and to the side it is on, the power kept across the pan. */
static void gains_3d(const DsBuffer *b, float *left, float *right)
{
    Vector to = sub(b->heard.position, s_listener.position);
    Vector top = s_listener.top, front = s_listener.front;
    Vector side = { top.y * front.z - top.z * front.y, top.z * front.x - top.x * front.z,
                    top.x * front.y - top.y * front.x };
    float distance = sqrtf(dot(to, to)), across = sqrtf(dot(side, side));
    float pan = distance > 1e-4f && across > 1e-6f ? dot(to, side) / (distance * across) : 0.0f;
    float near_ = b->heard.min_distance > 0.0f ? b->heard.min_distance : 1.0f;
    float far_ = b->heard.max_distance > near_ ? b->heard.max_distance : near_;
    float fade = distance <= near_ ? 1.0f : near_ / (distance < far_ ? distance : far_);

    if (pan > 1.0f) pan = 1.0f;
    if (pan < -1.0f) pan = -1.0f;
    *left = fade * sqrtf(0.5f * (1.0f - pan));
    *right = fade * sqrtf(0.5f * (1.0f + pan));
}

/* The voice's gains and frequency from the buffer's volume, headroom,
 * mixbins and 3D. */
static void set_gains(DsBuffer *b)
{
    float master = level(b->volume - b->headroom);
    unsigned channels = b->voice.channels, i;

    memset(b->voice.gain, 0, sizeof b->voice.gain);
    if (b->flags & DSBCAPS_CTRL3D) {
        float left, right;

        gains_3d(b, &left, &right);
        for (i = 0; i < channels; i++) {
            b->voice.gain[i][0] = master * HRTF_HEADROOM_GAIN * MIXBIN_HEADROOM_GAIN * left;
            b->voice.gain[i][1] = master * HRTF_HEADROOM_GAIN * MIXBIN_HEADROOM_GAIN * right;
        }
    } else {
        master *= MIXBIN_HEADROOM_GAIN;
        for (i = 0; i < b->bins; i++) {
            int side = b->bin[i] == MIXBIN_FRONT_LEFT || b->bin[i] == MIXBIN_3D_FRONT_LEFT
                       || b->bin[i] == MIXBIN_3D_BACK_LEFT ? 0
                     : b->bin[i] == MIXBIN_FRONT_RIGHT || b->bin[i] == MIXBIN_3D_FRONT_RIGHT
                       || b->bin[i] == MIXBIN_3D_BACK_RIGHT ? 1 : -1;

            if (side >= 0)
                b->voice.gain[i % channels][side] += master * level(b->bin_volume[i]);
        }
    }
    b->voice.ratio = b->frequency && b->voice.rate ? (double)b->frequency / b->voice.rate : 1.0;
}

/* DSMIXBINS at va, or the defaults when it is 0. */
static void set_mixbins(DsBuffer *b, uint32_t va)
{
    unsigned i;

    if (va) {
        uint32_t count = guest32(va), pairs = guest32(va + 4);

        b->bins = count < MIXBINS_MAX ? count : MIXBINS_MAX;
        for (i = 0; i < b->bins; i++) {
            b->bin[i] = (uint8_t)guest32(pairs + 8 * i);
            b->bin_volume[i] = (int32_t)guest32(pairs + 8 * i + 4);
        }
        return;
    }
    if (b->flags & DSBCAPS_CTRL3D) {
        b->bins = sizeof BINS_3D;
        memcpy(b->bin, BINS_3D, sizeof BINS_3D);
    } else {
        b->bins = sizeof BINS_2D;
        memcpy(b->bin, BINS_2D, sizeof BINS_2D);
    }
    memset(b->bin_volume, 0, sizeof b->bin_volume);
}

/* The play cursor and the write cursor, in bytes from the region's start. */
static void position(DsBuffer *b, uint32_t *play, uint32_t *write)
{
    uint32_t p, w, ahead;

    if (!b->voice.playing) {
        *play = *write = b->kept;
        return;
    }
    p = frames_to_bytes(b, mixer_Frame(&b->voice) - b->voice.start);
    ahead = frames_to_bytes(b, 32);
    w = p + (ahead > b->block_align ? ahead : b->block_align);
    if (b->voice.looping && p < b->region_bytes)
        w %= b->region_bytes;
    else if (b->bytes)
        w %= b->bytes;
    *play = p;
    *write = w;
}

static void stop(DsBuffer *b)
{
    uint32_t play, write;

    if (!b->voice.playing)
        return;
    position(b, &play, &write);
    b->kept = play;
    mixer_Stop(&b->voice);
}

/* A buffer from a DSBUFFERDESC; 0 when the descriptor is not one. */
static uint32_t create_buffer(uint32_t desc, uint32_t out)
{
    uint32_t format, flags, bytes;
    unsigned channels, bits;
    DsBuffer *b;

    put32(out, 0);
    if (!desc || !out || s_count == BUFFERS_MAX)
        return DSERR_INVALIDCALL;
    flags = guest32(desc + DESC_FLAGS);
    bytes = guest32(desc + DESC_BYTES);
    format = guest32(desc + DESC_FORMAT);
    if (!format)
        return DSERR_INVALIDCALL;
    b = calloc(1, sizeof *b);
    if (!b)
        return DSERR_OUTOFMEMORY;
    b->flags = flags;
    b->tag = guest16(format);
    channels = guest16(format + WFX_CHANNELS);
    bits = guest16(format + WFX_BITS);
    b->block_align = guest16(format + WFX_BLOCK_ALIGN);
    b->voice.rate = guest32(format + WFX_RATE);
    b->voice.channels = channels == 2 ? 2 : 1;
    if (b->tag == WAVE_EXTENSIBLE)
        b->tag = WAVE_PCM;                  /* the extensible formats the XDK takes are PCM */
    if (b->tag == WAVE_XBOX_ADPCM) {
        if (!b->block_align)
            b->block_align = ADPCM_BLOCK_BYTES * channels;
        b->voice.encoding = MIXER_XBOX_ADPCM;
        s_tally.adpcm++;
    } else {
        if (!b->block_align)
            b->block_align = channels * bits / 8;
        b->voice.encoding = bits == 8 ? MIXER_PCM8 : MIXER_PCM16;
        s_tally.pcm++;
    }
    if (!b->block_align)
        b->block_align = 1;
    b->voice.block_align = b->block_align;
    /* a format this mix cannot read is a buffer that plays nothing */
    if ((b->tag != WAVE_PCM && b->tag != WAVE_XBOX_ADPCM) || channels < 1 || channels > 2
        || (b->tag == WAVE_PCM && bits != 8 && bits != 16)) {
        b->voice.rate = 0;
        s_tally.silent++;
    }
    if (bytes) {
        b->own = xbox_HeapAlloc(bytes, 16);
        if (!b->own) {
            free(b);
            return DSERR_OUTOFMEMORY;
        }
        b->data = b->own;
        b->bytes = b->region_bytes = bytes;
    }
    b->handle = new_handle();
    if (!b->handle) {
        free(b);
        return DSERR_OUTOFMEMORY;
    }
    b->refs = 1;
    b->headroom = flags & DSBCAPS_NO_HEADROOM ? 0 : DSB_HEADROOM_2D;
    b->set.min_distance = b->heard.min_distance = 1.0f;
    b->set.max_distance = b->heard.max_distance = 1000000000.0f;
    b->voice.cached[0] = b->voice.cached[1] = -1;
    set_mixbins(b, guest32(desc + DESC_MIXBINS));
    set_source(b);
    set_gains(b);
    s_buffers[s_count++] = b;
    s_tally.created++;
    if (s_count > s_tally.alive_max)
        s_tally.alive_max = s_count;
    put32(out, b->handle);
    if (trace_on())
        fprintf(stderr, "[DSOUND] buffer 0x%08X: flags %08X, %u bytes, format %04X, %u ch, %u Hz, block %u%s\n",
                b->handle, flags, bytes, b->tag, channels, b->voice.rate, b->block_align,
                b->voice.rate ? "" : " (not played: a format this mix does not read)");
    return DS_OK;
}

static void release_buffer(DsBuffer *b)
{
    unsigned i;

    mixer_Stop(&b->voice);
    for (i = 0; i < s_count; i++)
        if (s_buffers[i] == b) {
            s_buffers[i] = s_buffers[--s_count];
            break;
        }
    if (b->own)
        xbox_HeapFree(b->own);
    s_free_handles[s_free_count++] = b->handle;
    s_tally.released++;
    free(b);
}

static void report(void)
{
    MixerCounts m = mixer_Counts();

    fprintf(stderr, "[DSOUND] native: %u buffers (%u ADPCM, %u PCM, %u not played), %u released, %u at once;"
            " %u voices started, %u ended by themselves, %u at once; %.1f s mixed\n",
            s_tally.created, s_tally.adpcm, s_tally.pcm, s_tally.silent, s_tally.released, s_tally.alive_max,
            m.starts, m.ended, m.playing_max, (double)m.frames / MIXER_RATE);
}

void dsound_Init(void)
{
    mixer_Init();
    atexit(report);
}

/* ── The entries (stdcall; each pops its arguments) ────────── */

/* DirectSoundCreate(pguidDeviceId, ppDirectSound, pUnkOuter) */
void dsound_DirectSoundCreate(void)
{
    uint32_t out = arg(1);

    mixer_Lock();
    if (!s_dsound)
        s_dsound = xbox_HeapAlloc(HANDLE_BYTES, 16);
    s_dsound_refs++;
    put32(out, s_dsound);
    mixer_Unlock();
    ret(s_dsound ? DS_OK : DSERR_OUTOFMEMORY, 3);
}

/* DirectSoundCreateBuffer(pdsbd, ppBuffer) */
void dsound_DirectSoundCreateBuffer(void)
{
    uint32_t desc = arg(0), out = arg(1), hr;

    mixer_Lock();
    hr = create_buffer(desc, out);
    mixer_Unlock();
    ret(hr, 2);
}

/* IDirectSound_CreateSoundBuffer(pDirectSound, pdsbd, ppBuffer, pUnkOuter) */
void dsound_IDirectSound_CreateSoundBuffer(void)
{
    uint32_t desc = arg(1), out = arg(2), hr;

    mixer_Lock();
    hr = create_buffer(desc, out);
    mixer_Unlock();
    ret(hr, 4);
}

/* IDirectSound_Release(pDirectSound): the count left. The one DirectSound
 * outlives its last release, as its buffers would keep it. */
void dsound_IDirectSound_Release(void)
{
    uint32_t refs;

    mixer_Lock();
    if (s_dsound_refs)
        s_dsound_refs--;
    refs = s_dsound_refs;
    mixer_Unlock();
    ret(refs, 1);
}

/* IDirectSound_DownloadEffectsImage(pDirectSound, pvImageBuffer, dwImageSize,
 * pImageLoc, ppImageDesc): the image is not run (the reverb is not heard);
 * the game reads nothing back. */
void dsound_IDirectSound_DownloadEffectsImage(void)
{
    put32(arg(4), 0);
    ret(DS_OK, 5);
}

/* IDirectSound_SetPosition(pDirectSound, x, y, z, dwApply): the listener */
void dsound_IDirectSound_SetPosition(void)
{
    Vector p = { arg_float(1), arg_float(2), arg_float(3) };
    uint32_t apply = arg(4);
    unsigned i;

    mixer_Lock();
    mixer_Sync(0);
    s_listener_set.position = p;
    if (apply == DS3D_IMMEDIATE) {
        s_listener.position = p;
        for (i = 0; i < s_count; i++)
            set_gains(s_buffers[i]);
    }
    mixer_Unlock();
    ret(DS_OK, 5);
}

/* IDirectSound_SetOrientation(pDirectSound, xFront, yFront, zFront, xTop,
 * yTop, zTop, dwApply) */
void dsound_IDirectSound_SetOrientation(void)
{
    Vector front = { arg_float(1), arg_float(2), arg_float(3) };
    Vector top = { arg_float(4), arg_float(5), arg_float(6) };
    uint32_t apply = arg(7);
    unsigned i;

    mixer_Lock();
    mixer_Sync(0);
    s_listener_set.front = front;
    s_listener_set.top = top;
    if (apply == DS3D_IMMEDIATE) {
        s_listener.front = front;
        s_listener.top = top;
        for (i = 0; i < s_count; i++)
            set_gains(s_buffers[i]);
    }
    mixer_Unlock();
    ret(DS_OK, 8);
}

/* IDirectSound_CommitDeferredSettings(pDirectSound): the 3D set deferred, applied */
void dsound_IDirectSound_CommitDeferredSettings(void)
{
    unsigned i;

    mixer_Lock();
    mixer_Sync(0);
    s_listener = s_listener_set;
    for (i = 0; i < s_count; i++) {
        s_buffers[i]->heard = s_buffers[i]->set;
        set_gains(s_buffers[i]);
    }
    mixer_Unlock();
    ret(DS_OK, 1);
}

/* DirectSoundUseLightHRTF(): the console's light HRTF; this 3D has none */
void dsound_DirectSoundUseLightHRTF(void)
{
    ret(0, 0);
}

/* DirectSoundDoWork(): the mixer works on its own; a virtual clock catches up */
void dsound_DirectSoundDoWork(void)
{
    mixer_Lock();
    mixer_Sync(0);
    mixer_Unlock();
    ret(0, 0);
}

/* IDirectSoundBuffer_Release(pBuffer): the count left */
void dsound_IDirectSoundBuffer_Release(void)
{
    DsBuffer *b;
    uint32_t refs = 0;

    mixer_Lock();
    b = find(arg(0));
    if (b) {
        refs = --b->refs;
        if (!refs)
            release_buffer(b);
    }
    mixer_Unlock();
    ret(refs, 1);
}

/* IDirectSoundBuffer_Play(pBuffer, dwReserved1, dwReserved2, dwFlags) */
void dsound_IDirectSoundBuffer_Play(void)
{
    uint32_t flags = arg(3);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (trace_on())
        fprintf(stderr, "[DSOUND] play 0x%08X, flags %X: %u bytes at 0x%08X, %s, gains %.3f %.3f\n", arg(0),
                flags, b ? b->bytes : 0, b ? b->data : 0,
                !b ? "no such buffer" : b->voice.playing ? "playing" : "stopped",
                b ? b->voice.gain[0][0] : 0.0f, b ? b->voice.gain[0][1] : 0.0f);
    if (b && b->voice.rate && b->voice.end > b->voice.start) {
        b->voice.looping = (flags & DSBPLAY_LOOPING) != 0;
        if (b->voice.playing) {
            if (flags & DSBPLAY_FROMSTART)
                mixer_Play(&b->voice, b->voice.start);
        } else {
            uint32_t from = flags & DSBPLAY_FROMSTART ? 0 : b->kept;

            b->kept = 0;
            mixer_Play(&b->voice, b->voice.start + bytes_to_frames(b, from));
        }
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 4);
}

/* IDirectSoundBuffer_Stop(pBuffer) */
void dsound_IDirectSoundBuffer_Stop(void)
{
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b)
        stop(b);
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 1);
}

/* IDirectSoundBuffer_GetStatus(pBuffer, pdwStatus) */
void dsound_IDirectSoundBuffer_GetStatus(void)
{
    uint32_t out = arg(1), status = 0;
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(1);
    b = find(arg(0));
    if (b && b->voice.playing)
        status = DSBSTATUS_PLAYING | (b->voice.looping ? DSBSTATUS_LOOPING : 0);
    mixer_Unlock();
    put32(out, status);
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_GetCurrentPosition(pBuffer, pdwPlayCursor, pdwWriteCursor) */
void dsound_IDirectSoundBuffer_GetCurrentPosition(void)
{
    uint32_t play_out = arg(1), write_out = arg(2), play = 0, write = 0;
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(1);
    b = find(arg(0));
    if (b)
        position(b, &play, &write);
    mixer_Unlock();
    put32(play_out, play);
    put32(write_out, write);
    ret(b ? DS_OK : DSERR_INVALIDCALL, 3);
}

/* IDirectSoundBuffer_SetCurrentPosition(pBuffer, dwPlayCursor) */
void dsound_IDirectSoundBuffer_SetCurrentPosition(void)
{
    uint32_t at = arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        if (b->voice.playing)
            mixer_Play(&b->voice, b->voice.start + bytes_to_frames(b, at));
        else
            b->kept = at;
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_SetBufferData(pBuffer, pvBufferData, dwBufferBytes): the
 * game's own memory, or with no pointer DirectSound's of that size */
void dsound_IDirectSoundBuffer_SetBufferData(void)
{
    uint32_t data = arg(1), bytes = arg(2), hr = DS_OK;
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (trace_on())
        fprintf(stderr, "[DSOUND] data 0x%08X: %u bytes at 0x%08X\n", arg(0), bytes, data);
    if (!b) {
        hr = DSERR_INVALIDCALL;
    } else if (data != b->data || bytes != b->bytes) {
        mixer_Stop(&b->voice);
        b->kept = 0;
        if (b->own) {
            xbox_HeapFree(b->own);
            b->own = 0;
        }
        if (!data && bytes) {
            b->own = data = xbox_HeapAlloc(bytes, 16);
            if (!data) {
                bytes = 0;
                hr = DSERR_OUTOFMEMORY;
            }
        }
        b->data = data;
        b->bytes = b->region_bytes = bytes;
        b->region = 0;
        b->voice.cached[0] = b->voice.cached[1] = -1;
        set_source(b);
    }
    mixer_Unlock();
    ret(hr, 3);
}

/* IDirectSoundBuffer_SetPlayRegion(pBuffer, dwPlayStart, dwPlayLength): a
 * length of 0 is to the end; a buffer playing starts again at the region */
void dsound_IDirectSoundBuffer_SetPlayRegion(void)
{
    uint32_t start = arg(1), length = arg(2), hr = DS_OK;
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (!b) {
        hr = DSERR_INVALIDCALL;
    } else {
        if (!length)
            length = start < b->bytes ? b->bytes - start : 0;
        if (start + length > b->bytes) {
            hr = DSERR_INVALIDCALL;
        } else {
            b->region = start;
            b->region_bytes = length;
            b->kept = 0;
            set_source(b);
            if (b->voice.playing)
                mixer_Play(&b->voice, b->voice.start);
        }
    }
    mixer_Unlock();
    ret(hr, 3);
}

/* IDirectSoundBuffer_Lock(pBuffer, dwOffset, dwBytes, ppvAudioPtr1,
 * pdwAudioBytes1, ppvAudioPtr2, pdwAudioBytes2, dwFlags): the data in place,
 * in two pieces when it wraps */
void dsound_IDirectSoundBuffer_Lock(void)
{
    uint32_t offset = arg(1), bytes = arg(2), ptr1 = arg(3), bytes1 = arg(4), ptr2 = arg(5), bytes2 = arg(6);
    uint32_t flags = arg(7), first = 0;
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        if (flags & DSBLOCK_FROMWRITECURSOR) {
            uint32_t play;

            position(b, &play, &offset);
        }
        if (flags & DSBLOCK_ENTIREBUFFER)
            bytes = b->bytes;
        if (offset > b->bytes)
            offset = b->bytes;
        first = bytes < b->bytes - offset ? bytes : b->bytes - offset;
        put32(ptr1, b->data + offset);
        put32(bytes1, first);
        if (ptr2 && bytes2) {
            put32(ptr2, first < bytes ? b->data : 0);
            put32(bytes2, first < bytes ? bytes - first : 0);
        }
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 8);
}

/* IDirectSoundBuffer_Unlock(pBuffer, pvLock1, dwLock1, pvLock2, dwLock2): the
 * XDK's does nothing either, the data being the buffer's own */
void dsound_IDirectSoundBuffer_Unlock(void)
{
    ret(DS_OK, 5);
}

/* IDirectSoundBuffer_SetVolume(pBuffer, lVolume) */
void dsound_IDirectSoundBuffer_SetVolume(void)
{
    int32_t volume = (int32_t)arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->volume = volume;
        set_gains(b);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_SetHeadroom(pBuffer, dwHeadroom) */
void dsound_IDirectSoundBuffer_SetHeadroom(void)
{
    int32_t headroom = (int32_t)arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->headroom = headroom;
        set_gains(b);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_SetFrequency(pBuffer, dwFrequency): 0 is as recorded */
void dsound_IDirectSoundBuffer_SetFrequency(void)
{
    uint32_t frequency = arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->frequency = frequency;
        set_gains(b);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_SetMixBins(pBuffer, pMixBins) */
void dsound_IDirectSoundBuffer_SetMixBins(void)
{
    uint32_t bins = arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        set_mixbins(b, bins);
        set_gains(b);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* IDirectSoundBuffer_SetMixBinVolumes_8(pBuffer, pMixBins): the volumes of
 * mixbins the buffer already has */
void dsound_IDirectSoundBuffer_SetMixBinVolumes_8(void)
{
    uint32_t va = arg(1);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b && va) {
        uint32_t count = guest32(va), pairs = guest32(va + 4), i;
        unsigned k;

        for (i = 0; i < count && i < 32; i++) {
            uint8_t bin = (uint8_t)guest32(pairs + 8 * i);

            for (k = 0; k < b->bins; k++)
                if (b->bin[k] == bin)
                    b->bin_volume[k] = (int32_t)guest32(pairs + 8 * i + 4);
        }
        set_gains(b);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 2);
}

/* The 3D setters of a buffer: the value set, and heard now unless deferred. */
static void set_3d(DsBuffer *b, uint32_t apply)
{
    if (apply == DS3D_IMMEDIATE) {
        b->heard = b->set;
        set_gains(b);
    }
}

/* IDirectSoundBuffer_SetMinDistance(pBuffer, flMinDistance, dwApply) */
void dsound_IDirectSoundBuffer_SetMinDistance(void)
{
    float distance = arg_float(1);
    uint32_t apply = arg(2);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->set.min_distance = distance;
        set_3d(b, apply);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 3);
}

/* IDirectSoundBuffer_SetMaxDistance(pBuffer, flMaxDistance, dwApply) */
void dsound_IDirectSoundBuffer_SetMaxDistance(void)
{
    float distance = arg_float(1);
    uint32_t apply = arg(2);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->set.max_distance = distance;
        set_3d(b, apply);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 3);
}

/* IDirectSoundBuffer_SetPosition(pBuffer, x, y, z, dwApply) */
void dsound_IDirectSoundBuffer_SetPosition(void)
{
    Vector p = { arg_float(1), arg_float(2), arg_float(3) };
    uint32_t apply = arg(4);
    DsBuffer *b;

    mixer_Lock();
    mixer_Sync(0);
    b = find(arg(0));
    if (b) {
        b->set.position = p;
        set_3d(b, apply);
    }
    mixer_Unlock();
    ret(b ? DS_OK : DSERR_INVALIDCALL, 5);
}

/* IDirectSoundBuffer_SetI3DL2Source(pBuffer, pds3db, dwApply): the reverb's
 * send of the buffer, which is not heard */
void dsound_IDirectSoundBuffer_SetI3DL2Source(void)
{
    ret(DS_OK, 3);
}
