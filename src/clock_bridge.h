/**
 *    Name:        clock_bridge.h
 *    Description: the clock tied to the frames that recomp_manual.c routes the game's counter to
 *                 (clock_bridge.c)
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 */
#ifndef CLOCK_BRIDGE_H
#define CLOCK_BRIDGE_H

int clock_Virtual(void);                  /* ROBOTECH_VIRTUAL_CLOCK=1 */
void clock_QueryPerformanceCounter(void); /* replaces the game's while the clock is virtual */

#endif
