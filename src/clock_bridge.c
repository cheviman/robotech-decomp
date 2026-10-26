/**
 *    Name:        clock_bridge.c
 *    Description: a clock tied to the frames presented, for runs compared frame for frame
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game times itself with XAPI's QueryPerformanceCounter, an rdtsc on the console, counting at
 *    733,333,333 Hz (QueryPerformanceFrequency's constant). Read from the host's clock, how much time a
 *    frame took differs from run to run, and so does what the game does with it: two runs of one pad
 *    script drift apart. With ROBOTECH_VIRTUAL_CLOCK=1 the counter is the frames presented so far times a
 *    sixtieth of a second, plus a microsecond for each read within the frame, so a loop that waits for the
 *    counter to move still sees it move. tools/scenario.py runs with it; a game played is never given it.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "clock_bridge.h"
#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax;
extern ptrdiff_t g_xbox_mem_offset;

#define XBOX_COUNTER_HZ 733333333ull
#define FRAME_TICKS     (XBOX_COUNTER_HZ / 60u)
#define READ_TICKS      (XBOX_COUNTER_HZ / 1000000u)

int clock_Virtual(void)
{
    static int on = -1;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_VIRTUAL_CLOCK");
        on = e && *e == '1';
    }
    return on;
}

/* QueryPerformanceCounter(lpPerformanceCount), replacing the game's while the
 * clock is virtual: stdcall, one argument; writes the count, returns TRUE. */
void clock_QueryPerformanceCounter(void)
{
    static unsigned frame = ~0u;
    static uint64_t reads;
    unsigned now = d3d11_FrameCount();
    uint32_t out = *(const uint32_t *)((uintptr_t)g_esp + 4 + g_xbox_mem_offset);
    uint64_t count;

    if (now != frame) {
        frame = now;
        reads = 0;
    }
    count = (uint64_t)now * FRAME_TICKS + ++reads * READ_TICKS;
    if (out)
        memcpy((void *)((uintptr_t)out + g_xbox_mem_offset), &count, 8);
    g_eax = 1;
    g_esp += 4 + 4;                       /* the return address, and one argument */
}
