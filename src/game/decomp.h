/**
 *    Name:        decomp.h
 *    Description: what the C written by hand needs to sit among the recompiled C
 *    Version:     0.2.0
 *    Created:     25-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    The game's functions are rewritten by hand into src/game/, by subject, one at a time. A function
 *    written by hand is C: its arguments and its result are its own, and the guest's memory is read by
 *    name with symbols.h's accessors (vcClass_count(p), vcClassByType(type)), built on recomp_types.h's
 *    XBOX_PTR, the same in the game and in xboxrecomp's conformance harness (tools/verify_c.py). Guest
 *    pointers stay guest addresses, uint32_t.
 *
 *    Two bridges join it to the code still recompiled, until every caller and callee is C too:
 *      - its entry, NAME_entry, defined beside it with ENTRY_*: what the recompiled code calls in the
 *        original's place, with the original's convention (the arguments on the guest stack, the result
 *        in eax, the return address popped). tools/hand_functions.py finds the entries and hands their
 *        names to the recompiler, which generates no body for the function.
 *      - CALL and CALL_AT: how it calls a function still recompiled, by its name or by a guest address
 *        (a class's callback), pushing the arguments and a return address as the original's call did.
 */
#ifndef DECOMP_H
#define DECOMP_H

#include "recomp_types.h"
#include "symbols.h"      /* the game's structures and variables, by name (tools/symbols.py header) */

/* The n-th 32-bit argument (from 0), as the recompiled callers pushed it. */
#define ARG32(n)                (MEM32(g_esp + 4u + 4u * (uint32_t)(n)))

/* What a function that hands back nothing on some path leaves in eax there: what the caller had in it,
 * as the original, when a caller is known to read eax after it. */
#define EAX_AS_CALLER_LEFT      ((uint32_t)g_eax)

/* ── Entries ─────────────────────────────────────────────────────────────────────────────────────── */

/* cdecl, n arguments, the result in eax */
#define ENTRY_CDECL0(name)  void name##_entry(void) { g_eax = (uint32_t)name(); g_esp += 4u; }
#define ENTRY_CDECL1(name)  void name##_entry(void) { g_eax = (uint32_t)name(ARG32(0)); g_esp += 4u; }
#define ENTRY_CDECL2(name)  void name##_entry(void) \
    { g_eax = (uint32_t)name(ARG32(0), ARG32(1)); g_esp += 4u; }
#define ENTRY_CDECL3(name)  void name##_entry(void) \
    { g_eax = (uint32_t)name(ARG32(0), ARG32(1), ARG32(2)); g_esp += 4u; }
#define ENTRY_CDECL4(name)  void name##_entry(void) \
    { g_eax = (uint32_t)name(ARG32(0), ARG32(1), ARG32(2), ARG32(3)); g_esp += 4u; }

/* cdecl, n arguments, no result: no caller of the original reads eax after it (measured, objects.c) */
#define ENTRY_CDECL0_VOID(name)  void name##_entry(void) { name(); g_esp += 4u; }
#define ENTRY_CDECL1_VOID(name)  void name##_entry(void) { name(ARG32(0)); g_esp += 4u; }
#define ENTRY_CDECL2_VOID(name)  void name##_entry(void) { name(ARG32(0), ARG32(1)); g_esp += 4u; }

/* thiscall, the object in ecx and no other argument, no result */
#define ENTRY_THISCALL0_VOID(name)  void name##_entry(void) { name(g_ecx); g_esp += 4u; }

/* ── Calls into the recompiled code ──────────────────────────────────────────────────────────────── */

/* The return address a call from the C written by hand pushes: no function of the game reads its own. */
#define DECOMP_RETURN_ADDRESS   0u

/* Runs a recompiled function, cdecl or stdcall, with count 32-bit arguments; hands back eax. */
uint32_t decomp_Call(void (*function)(void), unsigned count, const uint32_t *args);
/* The same for a function known by its guest address, as an indirect call finds it; 0 if there is
 * none there. */
uint32_t decomp_CallAt(uint32_t va, unsigned count, const uint32_t *args);

#define DECOMP_ARGS(...)        (const uint32_t[]){ __VA_ARGS__ }
#define DECOMP_COUNT(...)       ((unsigned)(sizeof(DECOMP_ARGS(__VA_ARGS__)) / sizeof(uint32_t)))
#define CALL(function, ...)     decomp_Call(function, DECOMP_COUNT(__VA_ARGS__), DECOMP_ARGS(__VA_ARGS__))
#define CALL0(function)         decomp_Call(function, 0, 0)
#define CALL_AT(va, ...)        decomp_CallAt(va, DECOMP_COUNT(__VA_ARGS__), DECOMP_ARGS(__VA_ARGS__))

#include "recomp_funcs.h"   /* the recompiled functions, by name, and the entries of the ones written by hand */

#endif
