/**
 *    Name:        sound_mixer.h
 *    Description: the host's mixer of the game's sounds: voices read from guest memory, mixed to 48 kHz stereo
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 */
#ifndef SOUND_MIXER_H
#define SOUND_MIXER_H

#include <stdint.h>

#define MIXER_RATE              48000u
#define MIXER_ADPCM_BLOCK       64u     /* frames in an Xbox ADPCM block, per channel */

typedef enum {
    MIXER_PCM8,
    MIXER_PCM16,
    MIXER_XBOX_ADPCM,
} MixerEncoding;

/* One sound read from the guest's memory. The owner fills the source and the
 * gains, always holding mixer_Lock; the mixer moves the cursor and says when
 * a voice that does not loop has ended (playing back to 0). */
typedef struct MixerVoice {
    /* the source */
    MixerEncoding encoding;
    unsigned channels;          /* 1 or 2 */
    unsigned rate;              /* frames per second the data was recorded at */
    unsigned block_align;       /* bytes of a frame (PCM) or of a block (ADPCM) */
    uint32_t data;              /* guest address of the samples */
    uint32_t start, end;        /* the frames played, [start, end) from the data's first */
    int looping;                /* from end back to start, until stopped */
    double ratio;               /* the frequency asked for over rate: 1 plays as recorded */
    float gain[2][2];           /* gain[channel][side]: side 0 the left, 1 the right */

    /* the mixer's */
    int playing;
    uint64_t cursor;            /* frames from the data's first, 32.32 fixed point */
    float gain_now[2][2];       /* where the last period's gains ended */
    int32_t cached[2];          /* the ADPCM blocks decoded (-1: none) */
    int16_t block[2][2][MIXER_ADPCM_BLOCK];     /* [cache][channel][frame] */
    struct MixerVoice *next;    /* the voices playing */
} MixerVoice;

typedef struct MixerCounts {
    uint64_t frames;            /* frames mixed */
    unsigned starts;            /* voices started */
    unsigned ended;             /* voices that reached their end */
    unsigned playing_max;       /* most voices playing at once */
} MixerCounts;

void mixer_Init(void);
void mixer_Lock(void);
void mixer_Unlock(void);

/* With the clock tied to the frames (ROBOTECH_VIRTUAL_CLOCK=1), the sound
 * follows that clock too, so what the game reads of it is the same run after
 * run: mixer_Sync brings the mix up to the time the game has read
 * (clock_VirtualTime), and a poll (a status or a position read) moves the
 * sound a hundredth of a frame on, so a game waiting on a sound and reading
 * nothing else gets there in a bounded number of reads. Without it, the mix
 * follows the device and mixer_Sync does nothing. Called holding the lock. */
void mixer_Sync(int poll);

void mixer_Play(MixerVoice *v, uint32_t frame);     /* from frame, of the data */
void mixer_Stop(MixerVoice *v);
uint32_t mixer_Frame(const MixerVoice *v);           /* the frame the voice is at */

MixerCounts mixer_Counts(void);

#endif
