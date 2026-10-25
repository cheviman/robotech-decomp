/**
 *    Name:        dsound_bridge.h
 *    Description: the DirectSound entries recomp_manual.c's wrappers call (dsound_bridge.c)
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 */
#ifndef DSOUND_BRIDGE_H
#define DSOUND_BRIDGE_H

void dsound_GetStatusArgs(void);    /* before the generated IDirectSoundBuffer_GetStatus */
void dsound_GetStatusDone(void);    /* after it */

#endif
