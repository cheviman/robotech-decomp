/**
 *    Name:        input_bridge.h
 *    Description: the XInput entries recomp_manual.c routes to the host (input_bridge.c)
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 */
#ifndef INPUT_BRIDGE_H
#define INPUT_BRIDGE_H

void input_XInputOpenArgs(void);    /* before the generated XInputOpen */
void input_XInputOpenDone(void);    /* after it: its return value */
void input_XInputGetState(void);    /* replaces the game's */

#endif
