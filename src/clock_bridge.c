/**
 *    Name:        clock_bridge.c
 *    Description: a clock tied to the frames presented, for runs compared frame for frame
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game reads two clocks. Its engine times itself with XAPI's QueryPerformanceCounter, an rdtsc on
 *    the console counting at 733,333,333 Hz (QueryPerformanceFrequency's constant), and waits on it in
 *    loops that keep the sound going (the save screen waits seconds so). And XAPI's
 *    GetSystemTimeAsFileTime (the kernel's KeQuerySystemTime) gives the date: what time() hands the
 *    engine's srand at start, what a save is stamped with. Read from the host, both differ from run to
 *    run, and so does what the game does with them: two runs of one pad script drift apart.
 *
 *    XAPI also reads the date straight from the kernel (GetLocalTime, the timestamps it gives a save's
 *    folder, GetTimeZoneInformation), through the kernel thunk of KeQuerySystemTime, and the tick count
 *    through KeTickCount (GetTickCount). xboxrecomp's kernel answers both from the host and has no way
 *    to replace one; but a thunk is a word in the guest's memory, read at every call, so clock_Init points
 *    KeQuerySystemTime's at the wrapped GetSystemTimeAsFileTime, which takes the same argument.
 *
 *    With ROBOTECH_VIRTUAL_CLOCK=1 all of it follows the frames instead. The counter is the frames presented
 *    times a sixtieth of a second, never less, and each read moves it a tenth of a frame on, so a loop
 *    waiting for it gets there in a bounded number of turns; the date is the day the XBE was built,
 *    2002-08-05 22:37:24 UTC, plus the frames. tools/scenario.py runs with it; a game played is never
 *    given it.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "clock_bridge.h"
#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax;
extern ptrdiff_t g_xbox_mem_offset;

#define XBOX_COUNTER_HZ   733333333ull
#define FRAME_TICKS       (XBOX_COUNTER_HZ / 60u)
#define READ_TICKS        (FRAME_TICKS / 10u)
#define BUILD_UNIX_TIME   1028587044ull             /* 2002-08-05 22:37:24 UTC, the XBE's build date */
#define FILETIME_EPOCH    11644473600ull            /* seconds from 1601 to 1970 */
#define FILETIME_HZ       10000000ull               /* 100 ns units */
#define THUNK_TABLE               0x0018EA40u       /* the XBE's kernel thunk table */
#define THUNK_KEQUERYSYSTEMTIME   0x0018EA84u       /* the thunk of KeQuerySystemTime (ordinal 128) */
/* what xboxrecomp's kernel bridge puts in a thunk: 0xFE000000 plus its offset in the table */
#define KERNEL_THUNK_VALUE(va)    (0xFE000000u + ((va) - THUNK_TABLE))
#define GETSYSTEMTIMEASFILETIME   0x0014E562u       /* XAPI's, wrapped in recomp_manual.c */

static uint64_t s_counter;         /* the virtual counter's last value read */

static uint32_t arg0(void)
{
    return *(const uint32_t *)((uintptr_t)g_esp + 4 + g_xbox_mem_offset);
}

int clock_Virtual(void)
{
    static int on = -1;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_VIRTUAL_CLOCK");
        on = e && *e == '1';
    }
    return on;
}

/* After the kernel bridge has filled the thunks: while the clock is virtual,
 * KeQuerySystemTime's thunk calls the wrapped GetSystemTimeAsFileTime. */
void clock_Init(void)
{
    volatile uint32_t *thunk = (volatile uint32_t *)((uintptr_t)THUNK_KEQUERYSYSTEMTIME + g_xbox_mem_offset);

    if (!clock_Virtual())
        return;
    if (*thunk != KERNEL_THUNK_VALUE(THUNK_KEQUERYSYSTEMTIME)) {
        fprintf(stderr, "[CLOCK] KeQuerySystemTime's thunk holds 0x%08X, not the kernel's: the date stays"
                " the host's\n", *thunk);
        return;
    }
    *thunk = GETSYSTEMTIMEASFILETIME;
}

/* GetTickCount(), replacing the game's while the clock is virtual: the
 * milliseconds of the frames presented. */
void clock_GetTickCount(void)
{
    g_eax = (uint32_t)((uint64_t)d3d11_FrameCount() * 1000u / 60u);
    g_esp += 4;
}

/* QueryPerformanceCounter(lpPerformanceCount), replacing the game's while the
 * clock is virtual: stdcall, one argument; writes the count, returns TRUE. */
void clock_QueryPerformanceCounter(void)
{
    uint64_t frames = (uint64_t)d3d11_FrameCount() * FRAME_TICKS;
    uint32_t out = arg0();

    s_counter = s_counter + READ_TICKS > frames ? s_counter + READ_TICKS : frames;
    if (out)
        memcpy((void *)((uintptr_t)out + g_xbox_mem_offset), &s_counter, 8);
    g_eax = 1;
    g_esp += 4 + 4;                       /* the return address, and one argument */
}

/* The time the game has read so far, in 1/rate of a second: the sound's
 * clock while the clock is virtual (sound_mixer.c), so what is heard keeps
 * to the time the game's engine counts. Reading it does not move it. */
uint64_t clock_VirtualTime(unsigned rate)
{
    uint64_t frames = (uint64_t)d3d11_FrameCount() * FRAME_TICKS;
    uint64_t counter = s_counter > frames ? s_counter : frames;

    return counter / XBOX_COUNTER_HZ * rate + counter % XBOX_COUNTER_HZ * rate / XBOX_COUNTER_HZ;
}

/* GetSystemTimeAsFileTime(lpSystemTimeAsFileTime), replacing the game's while
 * the clock is virtual: stdcall, one argument; the date in 100 ns units since
 * 1601. */
void clock_GetSystemTimeAsFileTime(void)
{
    uint64_t date = (BUILD_UNIX_TIME + FILETIME_EPOCH) * FILETIME_HZ
                    + (uint64_t)d3d11_FrameCount() * (FILETIME_HZ / 60u);
    uint32_t out = arg0();

    if (out)
        memcpy((void *)((uintptr_t)out + g_xbox_mem_offset), &date, 8);
    g_esp += 4 + 4;
}
