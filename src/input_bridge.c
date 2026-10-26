/**
 *    Name:        input_bridge.c
 *    Description: answers the game's XInputGetState from the host's controllers and keyboard, and
 *                 sends its rumble to them
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game's XAPI is statically linked and reads its pad through the emulated USB host controller
 *    (RECOMP_USB). That gets as far as enumerating it: in the menu the driver stopped queueing the pad's
 *    interrupt transfer after a few dozen reports, and the game stopped seeing presses. Its USB driver
 *    guards itself with cli/sti, which are no-ops here, while the controller's interrupt runs on another
 *    host thread. So the state the game asks for is answered from the host instead: XInputOpen is
 *    wrapped to learn which port a handle is, and XInputGetState is replaced (recomp_manual.c), filled
 *    from xboxrecomp's input layer -- the host's XInput pads, and the keyboard on port 0. XInputSetState,
 *    the rumble, went the same USB way and is replaced the same way.
 *
 *    ROBOTECH_PAD_SCRIPT="<ms>:<button>[+<button>...][:<hold ms>],..." presses buttons on port 0 at times
 *    counted from the game's first read, for runs nobody plays: a b x y black white lt rt up down left
 *    right start back, 150 ms held by default. A time written f<n> is the n-th frame the game presents
 *    instead, its hold in frames too (9 by default): a press then lands on the same frame however long
 *    the loading took, which runs compared frame for frame need (tools/scenario.py).
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <xbox/xboxrecomp.h>

#include "input_bridge.h"
#include "d3d11_bridge.h"

extern RECOMP_TLS uint32_t g_esp, g_eax;
extern ptrdiff_t g_xbox_mem_offset;

#define INPUT_HANDLES 16
#define SCRIPT_MAX    512

static struct { uint32_t handle, port; } s_handles[INPUT_HANDLES];
static int s_handle_count;
static uint32_t s_open_port;

static struct { DWORD at, hold; int frames; WORD buttons; BYTE analog[8]; } s_script[SCRIPT_MAX];
static int s_script_len = -1;
static DWORD s_script_t0;

static uint32_t guest32(uint32_t va)
{
    return *(const volatile uint32_t *)((uintptr_t)va + g_xbox_mem_offset);
}

static uint32_t arg(int i)
{
    return guest32(g_esp + 4u + 4u * (uint32_t)i);
}

/* XInputOpen(DeviceType, dwPort, dwSlot, pPollingParameters): the port is an
 * argument, the handle the return value. */
void input_XInputOpenArgs(void)
{
    s_open_port = arg(1);
}

void input_XInputOpenDone(void)
{
    int i;

    if (!g_eax)
        return;
    for (i = 0; i < s_handle_count; i++)
        if (s_handles[i].handle == g_eax)
            break;
    if (i == s_handle_count) {
        if (s_handle_count == INPUT_HANDLES)
            return;
        s_handle_count++;
    }
    s_handles[i].handle = g_eax;
    s_handles[i].port = s_open_port;
    fprintf(stderr, "[INPUT] XInputOpen: port %u -> handle 0x%08X\n", s_open_port, g_eax);
}

static void script_load(void)
{
    static const struct { const char *name; WORD bit; int analog; } names[] = {
        { "up", 0x0001, -1 }, { "down", 0x0002, -1 }, { "left", 0x0004, -1 }, { "right", 0x0008, -1 },
        { "start", 0x0010, -1 }, { "back", 0x0020, -1 },
        { "a", 0, 0 }, { "b", 0, 1 }, { "x", 0, 2 }, { "y", 0, 3 },
        { "black", 0, 4 }, { "white", 0, 5 }, { "lt", 0, 6 }, { "rt", 0, 7 },
    };
    const char *spec = getenv("ROBOTECH_PAD_SCRIPT");
    char *buf, *entry, *ctx = NULL;

    s_script_len = 0;
    if (!spec || !*spec)
        return;
    buf = _strdup(spec);
    for (entry = strtok_s(buf, ",", &ctx); entry && s_script_len < SCRIPT_MAX;
         entry = strtok_s(NULL, ",", &ctx)) {
        char *colon = strchr(entry, ':'), *btn, *hold, *plus;
        size_t k;

        if (!colon)
            continue;
        memset(&s_script[s_script_len], 0, sizeof s_script[0]);
        s_script[s_script_len].frames = entry[0] == 'f';
        s_script[s_script_len].at = (DWORD)strtoul(entry + s_script[s_script_len].frames, NULL, 10);
        btn = colon + 1;
        hold = strchr(btn, ':');
        s_script[s_script_len].hold = hold ? (DWORD)strtoul(hold + 1, NULL, 10)
                                           : (s_script[s_script_len].frames ? 9 : 150);
        if (hold)
            *hold = 0;
        for (; btn && *btn; btn = plus ? plus + 1 : NULL) {
            plus = strchr(btn, '+');
            if (plus)
                *plus = 0;
            for (k = 0; k < sizeof names / sizeof names[0]; k++)
                if (!strcmp(btn, names[k].name)) {
                    if (names[k].analog < 0)
                        s_script[s_script_len].buttons |= names[k].bit;
                    else
                        s_script[s_script_len].analog[names[k].analog] = 0xFF;
                }
        }
        s_script_len++;
    }
    free(buf);
    fprintf(stderr, "[INPUT] pad script: %d step(s)\n", s_script_len);
}

static void script_apply(XBOX_GAMEPAD *pad)
{
    DWORD t, frame, now;
    int i, k;

    if (s_script_len < 0)
        script_load();
    if (!s_script_len)
        return;
    if (!s_script_t0)
        s_script_t0 = GetTickCount();
    t = GetTickCount() - s_script_t0;
    frame = d3d11_FrameCount();
    for (i = 0; i < s_script_len; i++) {
        now = s_script[i].frames ? frame : t;
        if (now >= s_script[i].at && now < s_script[i].at + s_script[i].hold) {
            pad->wButtons |= s_script[i].buttons;
            for (k = 0; k < 8; k++)
                if (s_script[i].analog[k])
                    pad->bAnalogButtons[k] = s_script[i].analog[k];
        }
    }
}

/* XInputGetState(hDevice, pState), replacing the game's: stdcall, two
 * arguments. The packet number moves only when the state does, as the
 * console's does; games compare it to tell a new report. */
void input_XInputGetState(void)
{
    static XBOX_GAMEPAD last[4];
    static DWORD packet[4];
    uint32_t handle = arg(0), state_va = arg(1), port = 0;
    XBOX_INPUT_STATE st;
    uint8_t *dst;
    int i;

    for (i = 0; i < s_handle_count; i++)
        if (s_handles[i].handle == handle)
            port = s_handles[i].port;
    if (port > 3)
        port = 0;
    memset(&st, 0, sizeof st);
    xbox_InputGetState(port, &st);
    if (port == 0)
        script_apply(&st.Gamepad);
    if (memcmp(&st.Gamepad, &last[port], sizeof st.Gamepad)) {
        last[port] = st.Gamepad;
        packet[port]++;
    }
    if (state_va) {
        dst = (uint8_t *)((uintptr_t)state_va + g_xbox_mem_offset);
        memcpy(dst, &packet[port], 4);
        memcpy(dst + 4, &st.Gamepad.wButtons, 2);
        memcpy(dst + 6, st.Gamepad.bAnalogButtons, 8);
        memcpy(dst + 14, &st.Gamepad.sThumbLX, 2);
        memcpy(dst + 16, &st.Gamepad.sThumbLY, 2);
        memcpy(dst + 18, &st.Gamepad.sThumbRX, 2);
        memcpy(dst + 20, &st.Gamepad.sThumbRY, 2);
    }
    g_eax = ERROR_SUCCESS;
    g_esp += 4 + 8;                       /* the return address, and two arguments */
}

/* XInputSetState(hDevice, pFeedback), replacing the game's: stdcall, two
 * arguments. XINPUT_FEEDBACK is packed to 1: dwStatus at 0, hEvent at 4, 58
 * reserved bytes, then the two motor speeds at 66 and 68. On the console
 * the request completes later (dwStatus ERROR_IO_PENDING until then, and the
 * game sends no other while it is); here it completes at once. The game
 * passes no event. ROBOTECH_TRACE_RUMBLE=1 logs each change of speeds. */
void input_XInputSetState(void)
{
    static XBOX_VIBRATION last[4];
    uint32_t handle = arg(0), fb = arg(1), port = 0;
    XBOX_VIBRATION vib;
    uint8_t *p;
    int i;

    for (i = 0; i < s_handle_count; i++)
        if (s_handles[i].handle == handle)
            port = s_handles[i].port;
    if (port > 3)
        port = 0;
    if (fb) {
        p = (uint8_t *)((uintptr_t)fb + g_xbox_mem_offset);
        memcpy(&vib.wLeftMotorSpeed, p + 66, 2);
        memcpy(&vib.wRightMotorSpeed, p + 68, 2);
        xbox_InputSetState(port, &vib);
        if (memcmp(&vib, &last[port], sizeof vib) && getenv("ROBOTECH_TRACE_RUMBLE"))
            fprintf(stderr, "[RUMBLE] port %u: left %u, right %u\n", port, vib.wLeftMotorSpeed,
                    vib.wRightMotorSpeed);
        last[port] = vib;
        memset(p, 0, 4);                  /* dwStatus: ERROR_SUCCESS, done */
    }
    g_eax = ERROR_SUCCESS;
    g_esp += 4 + 8;
}
