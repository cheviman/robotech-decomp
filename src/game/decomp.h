/**
 *    Name:        decomp.h
 *    Description: what the C written by hand needs to sit among the recompiled C
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game's functions are rewritten by hand into src/game/, by subject, one at a time; each takes its
 *    generated version's place (tools/hand_functions.py tells the recompiler not to generate it). Until
 *    every caller is C too, a function written by hand keeps the recompiled code's interface: its
 *    arguments are on the guest stack as the callers pushed them, its result goes in eax, and it pops the
 *    return address (a stdcall function its arguments too). These are that interface, and nothing else;
 *    the guest's memory is read with recomp_types.h's MEM8/16/32, the same in the game and in xboxrecomp's
 *    conformance harness (tools/verify_c.py).
 */
#ifndef DECOMP_H
#define DECOMP_H

#include "recomp_types.h"

/* The n-th 32-bit argument (from 0), as the recompiled callers pushed it. */
#define ARG32(n)                (MEM32(g_esp + 4u + 4u * (uint32_t)(n)))

/* Return v to a recompiled caller from a cdecl function (the caller pops the
 * arguments) or a stdcall one of n arguments (it pops them). */
#define RETURN_CDECL(v)         do { g_eax = (uint32_t)(v); g_esp += 4u; return; } while (0)
#define RETURN_STDCALL(v, n)    do { g_eax = (uint32_t)(v); g_esp += 4u + 4u * (uint32_t)(n); return; } while (0)

#endif
