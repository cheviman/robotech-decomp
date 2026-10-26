/**
 *    Name:        decomp.c
 *    Description: the calls from the C written by hand into the recompiled C (decomp.h)
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 */
#include "decomp.h"

/* The arguments pushed right to left and the return address, as the
 * original's call did; the callee pops the return address (and, stdcall, its
 * arguments), and the stack is left where it was before the pushes. */
uint32_t decomp_Call(void (*function)(void), unsigned count, const uint32_t *args)
{
    uint32_t esp = g_esp;

    while (count--)
        PUSH32(g_esp, args[count]);
    PUSH32(g_esp, DECOMP_RETURN_ADDRESS);
    function();
    g_esp = esp;
    return g_eax;
}

/* An indirect call finds its function so too: the project's replacements
 * first, then the recompiled functions. One it cannot find is logged, and
 * hands back 0, as RECOMP_ICALL does. */
uint32_t decomp_CallAt(uint32_t va, unsigned count, const uint32_t *args)
{
    recomp_func_t function = recomp_lookup_manual(va);

    if (!function)
        function = recomp_lookup(va);
    if (!function) {
        recomp_icall_fail_log(va);
        return 0;
    }
    return decomp_Call(function, count, args);
}
