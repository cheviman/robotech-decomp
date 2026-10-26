/**
 *    Name:        dsound_bridge.h
 *    Description: the game's DirectSound answered on the host (dsound_bridge.c), entry by entry for recomp_manual.c
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 */
#ifndef DSOUND_BRIDGE_H
#define DSOUND_BRIDGE_H

/* 1 unless RECOMP_AC97_READY=1 takes the emulated APU (main.c) */
int dsound_Native(void);
void dsound_Init(void);

/* Each replaces the XDK's entry of its name: stdcall, it pops its arguments. */
void dsound_DirectSoundCreate(void);
void dsound_DirectSoundCreateBuffer(void);
void dsound_DirectSoundUseLightHRTF(void);
void dsound_DirectSoundDoWork(void);
void dsound_IDirectSound_CreateSoundBuffer(void);
void dsound_IDirectSound_Release(void);
void dsound_IDirectSound_DownloadEffectsImage(void);
void dsound_IDirectSound_SetPosition(void);
void dsound_IDirectSound_SetOrientation(void);
void dsound_IDirectSound_CommitDeferredSettings(void);
void dsound_IDirectSoundBuffer_Release(void);
void dsound_IDirectSoundBuffer_Play(void);
void dsound_IDirectSoundBuffer_Stop(void);
void dsound_IDirectSoundBuffer_GetStatus(void);
void dsound_IDirectSoundBuffer_GetCurrentPosition(void);
void dsound_IDirectSoundBuffer_SetCurrentPosition(void);
void dsound_IDirectSoundBuffer_SetBufferData(void);
void dsound_IDirectSoundBuffer_SetPlayRegion(void);
void dsound_IDirectSoundBuffer_Lock(void);
void dsound_IDirectSoundBuffer_Unlock(void);
void dsound_IDirectSoundBuffer_SetVolume(void);
void dsound_IDirectSoundBuffer_SetHeadroom(void);
void dsound_IDirectSoundBuffer_SetFrequency(void);
void dsound_IDirectSoundBuffer_SetMixBins(void);
void dsound_IDirectSoundBuffer_SetMixBinVolumes_8(void);
void dsound_IDirectSoundBuffer_SetMinDistance(void);
void dsound_IDirectSoundBuffer_SetMaxDistance(void);
void dsound_IDirectSoundBuffer_SetPosition(void);
void dsound_IDirectSoundBuffer_SetI3DL2Source(void);

#endif
