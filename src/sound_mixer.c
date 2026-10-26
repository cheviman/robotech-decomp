/**
 *    Name:        sound_mixer.c
 *    Description: the host's mixer of the game's sounds: voices read from guest memory, mixed to 48 kHz stereo
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    What the console's audio processor did for the game's DirectSound, done on the host: each voice reads
 *    its samples where the game keeps them, in guest memory (PCM, or the Xbox's ADPCM decoded block by
 *    block as the voice gets to it, so a buffer the game refills while it plays is heard as refilled),
 *    is resampled to 48 kHz by linear interpolation, and is added to the two sides with the gains its
 *    owner (dsound_bridge.c) worked out. The mix goes to the device through xboxrecomp's audio output
 *    (apu_xaudio2.h: XAudio2 on Windows, SDL2 elsewhere), a period of 256 frames at a time, kept as far
 *    ahead of the device as the toolkit's own APU keeps it (xa2_pacing_marks); RECOMP_AUDIO_WAV=<path>
 *    also writes it to a WAV file, with the toolkit's tap (apu_wav.h).
 *
 *    The Xbox ADPCM block is IMA ADPCM: per channel a header (the predictor, a 16-bit sample, and the
 *    step index), then the nibbles, low one first, in runs of four bytes per channel. A block is 64
 *    frames, as the XDK's DirectSound counts them (it converts bytes to frames as bytes / block << 6):
 *    the header's sample first, then 63 of the 64 nibbles. The last nibble is not heard, as in xemu's
 *    APU and vgmstream.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>
#include "apu_xaudio2.h"
#include "apu_wav.h"

#include "sound_mixer.h"
#include "clock_bridge.h"
#include "d3d11_bridge.h"

extern ptrdiff_t g_xbox_mem_offset;

#define PERIOD          256u                    /* frames mixed at a time */
#define FRAME_SAMPLES   (MIXER_RATE / 60u)      /* the sound of one frame presented */
#define POLL_SAMPLES    (FRAME_SAMPLES / 100u)  /* how far a status read moves a virtual clock */
#define ADPCM_MAX_STEP  88

static CRITICAL_SECTION s_lock;
static int s_ready;
static MixerVoice *s_playing;
static unsigned s_playing_now;
static MixerCounts s_counts;
static uint64_t s_target;       /* with a virtual clock: the frame the mix is brought to */
static int s_high = 2048;       /* frames queued on the device the mix keeps ahead */

/* IMA ADPCM's step sizes and how a nibble moves the index (the IMA's
 * recommended practice, 1992). */
static const int16_t ADPCM_STEP[ADPCM_MAX_STEP + 1] = {
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80,
    88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598,
    658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
    16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
};
static const int8_t ADPCM_INDEX[16] = { -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8 };

static const uint8_t *guest(uint32_t va)
{
    return (const uint8_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static int adpcm_nibble(int *predictor, int *index, unsigned nibble)
{
    int step = ADPCM_STEP[*index];
    int diff = step >> 3;

    if (nibble & 4) diff += step;
    if (nibble & 2) diff += step >> 1;
    if (nibble & 1) diff += step >> 2;
    *predictor += (nibble & 8) ? -diff : diff;
    if (*predictor > 32767) *predictor = 32767;
    if (*predictor < -32768) *predictor = -32768;
    *index += ADPCM_INDEX[nibble];
    if (*index < 0) *index = 0;
    if (*index > ADPCM_MAX_STEP) *index = ADPCM_MAX_STEP;
    return *predictor;
}

/* Block `number` of the voice's data, decoded into out[channel][frame]. */
static void adpcm_block(const MixerVoice *v, uint32_t number, int16_t out[2][MIXER_ADPCM_BLOCK])
{
    const uint8_t *p = guest(v->data + number * v->block_align);
    const uint8_t *runs = p + 4 * v->channels;
    int predictor[2], index[2];
    unsigned ch, run, k;

    for (ch = 0; ch < v->channels; ch++) {
        predictor[ch] = (int16_t)(p[4 * ch] | p[4 * ch + 1] << 8);
        index[ch] = p[4 * ch + 2] > ADPCM_MAX_STEP ? ADPCM_MAX_STEP : p[4 * ch + 2];
        out[ch][0] = (int16_t)predictor[ch];
    }
    for (run = 0; run < MIXER_ADPCM_BLOCK / 8; run++)
        for (ch = 0; ch < v->channels; ch++) {
            const uint8_t *bytes = runs + (run * v->channels + ch) * 4;

            for (k = 0; k < 8; k++) {
                int s = adpcm_nibble(&predictor[ch], &index[ch], (bytes[k >> 1] >> ((k & 1) * 4)) & 15);
                unsigned frame = run * 8 + k + 1;

                if (frame < MIXER_ADPCM_BLOCK)
                    out[ch][frame] = (int16_t)s;
            }
        }
}

/* The voice's frame f, each channel in [-1, 1). The two ADPCM blocks kept are
 * the one being played and the next, in the slots of their parity, so the
 * interpolation across a block's end decodes each block once. */
static void frame_at(MixerVoice *v, uint32_t f, float out[2])
{
    unsigned ch;

    switch (v->encoding) {
    case MIXER_PCM16:
        for (ch = 0; ch < v->channels; ch++) {
            int16_t s;

            memcpy(&s, guest(v->data + f * v->block_align + 2 * ch), 2);
            out[ch] = s * (1.0f / 32768.0f);
        }
        break;
    case MIXER_PCM8:
        for (ch = 0; ch < v->channels; ch++)
            out[ch] = ((int)*guest(v->data + f * v->block_align + ch) - 128) * (1.0f / 128.0f);
        break;
    case MIXER_XBOX_ADPCM: {
        uint32_t number = f / MIXER_ADPCM_BLOCK;
        unsigned slot = number & 1;

        if (v->cached[slot] != (int32_t)number) {
            adpcm_block(v, number, v->block[slot]);
            v->cached[slot] = (int32_t)number;
        }
        for (ch = 0; ch < v->channels; ch++)
            out[ch] = v->block[slot][ch][f % MIXER_ADPCM_BLOCK] * (1.0f / 32768.0f);
        break;
    }
    }
}

/* n frames of the voice added to acc; 0 once a voice that does not loop has
 * reached its end. The gains move from where the last period left them to
 * the ones set now, over the period, as the console's do (in steps there):
 * a volume changed every frame is heard as a level, not as a buzz. */
static int mix_voice(MixerVoice *v, float (*acc)[2], unsigned n)
{
    uint64_t step = (uint64_t)(v->ratio * v->rate / MIXER_RATE * 4294967296.0 + 0.5);
    uint64_t end = (uint64_t)v->end << 32, length = (uint64_t)(v->end - v->start) << 32;
    float g[2][2], d[2][2];
    unsigned i, ch, side;

    if (v->end <= v->start || !step) {
        v->playing = 0;
        return 0;
    }
    for (ch = 0; ch < 2; ch++)
        for (side = 0; side < 2; side++) {
            g[ch][side] = v->gain_now[ch][side];
            d[ch][side] = (v->gain[ch][side] - g[ch][side]) / n;
        }
    for (i = 0; i < n; i++) {
        uint32_t f = (uint32_t)(v->cursor >> 32);
        uint32_t f1 = f + 1 < v->end ? f + 1 : (v->looping ? v->start : f);
        float t = (uint32_t)v->cursor * (1.0f / 4294967296.0f);
        float a[2], b[2];

        frame_at(v, f, a);
        frame_at(v, f1, b);
        for (ch = 0; ch < v->channels; ch++) {
            float x = a[ch] + (b[ch] - a[ch]) * t;

            for (side = 0; side < 2; side++) {
                g[ch][side] += d[ch][side];
                acc[i][side] += g[ch][side] * x;
            }
        }
        v->cursor += step;
        if (v->cursor >= end) {
            if (!v->looping) {
                v->playing = 0;
                break;
            }
            while (v->cursor >= end)
                v->cursor -= length;
        }
    }
    memcpy(v->gain_now, v->gain, sizeof v->gain_now);
    return v->playing;
}

/* n frames (up to a period) of every voice playing, to the device and the WAV
 * tap. Called holding the lock. */
static void mix(unsigned n)
{
    float acc[PERIOD][2];
    int16_t out[PERIOD][2];
    MixerVoice **link = &s_playing;
    unsigned i, side;

    memset(acc, 0, n * sizeof acc[0]);
    while (*link) {
        MixerVoice *v = *link;

        if (mix_voice(v, acc, n)) {
            link = &v->next;
            continue;
        }
        *link = v->next;
        v->next = NULL;
        s_playing_now--;
        s_counts.ended++;
    }
    for (i = 0; i < n; i++)
        for (side = 0; side < 2; side++) {
            float x = acc[i][side] * 32767.0f;

            out[i][side] = (int16_t)(x > 32767.0f ? 32767 : x < -32768.0f ? -32768 : x);
        }
    if (xa2_is_active())
        xa2_submit_samples(&out[0][0], (int)n);
    apu_wav_write(&out[0][0], (int)n);
    s_counts.frames += n;
}

static void mix_to(uint64_t target)
{
    while (s_counts.frames < target) {
        uint64_t n = target - s_counts.frames;

        mix(n < PERIOD ? (unsigned)n : PERIOD);
    }
}

/* The mix kept ahead of the device; with a virtual clock, brought up to the
 * frames presented; with no device, paced by the host's clock. */
static DWORD WINAPI mixer_thread(LPVOID unused)
{
    LARGE_INTEGER hz, start, now;

    (void)unused;
    QueryPerformanceFrequency(&hz);
    QueryPerformanceCounter(&start);
    for (;;) {
        mixer_Lock();
        if (clock_Virtual()) {
            mix_to((uint64_t)d3d11_FrameCount() * FRAME_SAMPLES);
        } else if (xa2_is_active()) {
            while (xa2_queued_samples() < s_high)
                mix(PERIOD);
        } else {
            uint64_t due;

            QueryPerformanceCounter(&now);
            due = (uint64_t)(now.QuadPart - start.QuadPart) * MIXER_RATE / (uint64_t)hz.QuadPart;
            if (due > s_counts.frames + MIXER_RATE / 10)
                s_counts.frames = due - MIXER_RATE / 10;    /* a stall is not mixed in a burst */
            mix_to(due);
        }
        mixer_Unlock();
        Sleep(1);
    }
}

void mixer_Init(void)
{
    const char *wav = getenv("RECOMP_AUDIO_WAV");
    const char *secs = getenv("RECOMP_AUDIO_WAV_SECS");
    HANDLE thread;

    if (s_ready)
        return;
    InitializeCriticalSection(&s_lock);
    s_ready = 1;
    if (wav && *wav)
        apu_wav_open(wav, secs ? atof(secs) : 0.0);
    if (xa2_init()) {
        int low;

        xa2_pacing_marks(xa2_get_buffer_size(), xa2_get_buffer_count(), PERIOD, &low, &s_high);
        fprintf(stderr, "[SOUND] mixing to %s, %d frames ahead\n", XA2_BACKEND_NAME, s_high);
    } else {
        fprintf(stderr, "[SOUND] no audio device: the mix is paced by the host's clock\n");
    }
    if (clock_Virtual())
        s_counts.frames = s_target = (uint64_t)d3d11_FrameCount() * FRAME_SAMPLES;
    thread = CreateThread(NULL, 0, mixer_thread, NULL, 0, NULL);
    if (thread) {
        SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST);
        CloseHandle(thread);
    }
}

void mixer_Lock(void)
{
    EnterCriticalSection(&s_lock);
}

void mixer_Unlock(void)
{
    LeaveCriticalSection(&s_lock);
}

void mixer_Sync(int poll)
{
    uint64_t now;

    if (!clock_Virtual())
        return;
    now = clock_VirtualTime(MIXER_RATE);
    if (poll)
        s_target += POLL_SAMPLES;
    if (s_target < now)
        s_target = now;
    mix_to(s_target);
}

void mixer_Play(MixerVoice *v, uint32_t frame)
{
    if (frame < v->start || frame >= v->end)
        frame = v->start;
    v->cursor = (uint64_t)frame << 32;
    v->cached[0] = v->cached[1] = -1;
    if (v->playing)
        return;
    memcpy(v->gain_now, v->gain, sizeof v->gain_now);
    v->playing = 1;
    v->next = s_playing;
    s_playing = v;
    s_counts.starts++;
    if (++s_playing_now > s_counts.playing_max)
        s_counts.playing_max = s_playing_now;
}

void mixer_Stop(MixerVoice *v)
{
    MixerVoice **link;

    if (!v->playing)
        return;
    for (link = &s_playing; *link; link = &(*link)->next)
        if (*link == v) {
            *link = v->next;
            break;
        }
    v->next = NULL;
    v->playing = 0;
    s_playing_now--;
}

uint32_t mixer_Frame(const MixerVoice *v)
{
    return (uint32_t)(v->cursor >> 32);
}

MixerCounts mixer_Counts(void)
{
    return s_counts;
}
