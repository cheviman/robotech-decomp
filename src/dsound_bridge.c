/**
 *    Name:        dsound_bridge.c
 *    Description: the game's DirectSound entries seen from the host: for now, a trace of buffer statuses
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game's DirectSound is statically linked and drives xboxrecomp's emulated APU. The first
 *    mission's opening scene stalls with the game polling a buffer's status, so the status each buffer
 *    reports is traced (ROBOTECH_TRACE_DSOUND=1): a buffer that stays playing for longer than it lasts
 *    shows up with how long it has been so.
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

#include <xbox/xboxrecomp.h>

#include "dsound_bridge.h"

extern RECOMP_TLS uint32_t g_esp;
extern ptrdiff_t g_xbox_mem_offset;

static uint32_t guest32(uint32_t va)
{
    return *(const volatile uint32_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static int trace_on(void)
{
    static int on = -1;

    if (on < 0) {
        const char *e = getenv("ROBOTECH_TRACE_DSOUND");
        on = e && *e == '1';
    }
    return on;
}

/* IDirectSoundBuffer_GetStatus(pThis, pdwStatus), stdcall: the arguments are
 * read before the generated body pops them, the status after it wrote it. */
static RECOMP_TLS uint32_t s_buf, s_status_va;

void dsound_GetStatusArgs(void)
{
    if (!trace_on())
        return;
    s_buf = guest32(g_esp + 4);
    s_status_va = guest32(g_esp + 8);
}

void dsound_GetStatusDone(void)
{
    static struct { uint32_t buf, status; DWORD since; } seen[64];
    static int n;
    uint32_t status;
    DWORD now;
    int i;

    if (!trace_on() || !s_status_va)
        return;
    status = guest32(s_status_va);
    now = GetTickCount();
    for (i = 0; i < n; i++)
        if (seen[i].buf == s_buf)
            break;
    if (i == n) {
        if (n == 64)
            return;
        n++;
        seen[i].buf = s_buf;
        seen[i].status = ~0u;
        seen[i].since = now;
    }
    if (seen[i].status != status) {
        fprintf(stderr, "[DSOUND] buffer 0x%08X status %X (was %X for %lu ms)\n", s_buf, status,
                seen[i].status, (unsigned long)(now - seen[i].since));
        seen[i].status = status;
        seen[i].since = now;
    }
}
