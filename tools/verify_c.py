"""
Name:        verify_c.py
Description: checks each function written by hand against the game's own machine code, with xboxrecomp's
             conformance harness
Version:     0.4.0
Created:     25-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

    py -3 tools/verify_c.py                 # the functions written by hand (src/game/)
    py -3 tools/verify_c.py --decompiled    # the ones the decompiler writes (src/decompiled/)

xboxrecomp's tools.conformance maps the XBE where it was linked in a 32-bit
process, calls one of its functions with a set of argument vectors, runs a
C function `lifted_<address>` over the same arguments, and compares eax, edx
and the memory it was handed. It fills `lifted_` with its own recompiled C;
here each one calls the entry of the function src/game/ writes by hand
instead (tools/hand_functions.py finds them), so the oracle is the shipped
binary itself. The harness, its argument vectors and its build are the toolkit's
(tools.conformance.xbe_run, unchanged); the 32-bit MSVC is the one
tools/conformance.py finds.

The harness calls the original with four arguments and a plain return, as
it does its own candidates, and compares what it hands back: a function
written by hand is checked here when it is cdecl, hands something back, and
its original calls nothing that is not written by hand too (read from its
machine code). The others are verified by the scenarios (tools/scenario.py).
The C written by hand calls recompiled functions the harness does not have;
it is linked without them (/FORCE:UNRESOLVED), and none of the functions
checked reaches one.

Two changes to the toolkit's harness source, made here: the XBE's sections
are mapped to their virtual size, the uninitialised part zero (most of the
game's variables are there), and the count of vectors compared is printed
for each function, so one compared with nothing is named and not taken for
a pass.
"""
import json
import os
import re
import struct
import subprocess
import sys

import capstone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLKIT = os.path.join(os.path.dirname(REPO), "xboxrecomp")
XBE = os.path.join(REPO, "analysis", "default.xbe")
WORK = os.path.join(REPO, "analysis", "verify_c")
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, TOOLKIT)
import conformance  # noqa: E402  (tools/conformance.py: the 32-bit MSVC)
import hand_functions  # noqa: E402

FUNCTIONS = os.path.join(REPO, "analysis", "disasm", "functions.json")
DECOMPILED = os.path.join(REPO, "analysis", "decompiled_signatures.json")
DECOMPILED_C = os.path.join("src", "decompiled", "decompiled.c")
GLUE = os.path.join(REPO, "src", "game", "decomp.c")     # the calls into the recompiled code


def compare_eax_only(source):
    """The harness compares eax, edx and the memory, as its own recompiled
    code keeps every register. A function written by hand hands back 32 bits
    or nothing, and after such a call no caller compiled for it reads edx
    (the calling convention leaves it undefined): what the original happens
    to leave there, a field it last loaded, is not its result. So edx is
    not compared."""
    compare = "if (nat_eax == g_eax && nat_edx == g_edx && !wrote) return;"
    if compare not in source:
        sys.exit("the toolkit's harness compares otherwise than verify_c expects")
    return source.replace(compare, "if (nat_eax == g_eax && !wrote) return;")


def map_uninitialised(source, sections):
    """The harness maps each section's bytes in the file, its raw size, and
    restores them before every run. The game's variables are mostly past
    that, in .data's uninitialised part (vcRandomCount, vcScreenWidth, the
    class table): a function that reads one faulted on the original with every
    vector and was compared with nothing. So each section is mapped to its
    virtual size, the part past its bytes zero, as the console's loader leaves
    it, and all of it is restored before every run, so neither side sees what
    the other wrote there."""
    table_end = "static unsigned char *g_pristine[64];\n"
    mapped_hi = "uintptr_t hi = (uintptr_t)g_secs[i].va + g_secs[i].raw_size;"
    pristine = ("g_pristine[i] = (unsigned char *)malloc(g_secs[i].raw_size);\n"
                "        if (g_pristine[i])\n"
                "            memcpy(g_pristine[i], (void *)lo, g_secs[i].raw_size);")
    restore = ("memcpy((void *)(uintptr_t)g_secs[i].va, g_pristine[i],\n"
               "                   g_secs[i].raw_size);")
    if any(part not in source for part in (table_end, mapped_hi, pristine, restore)):
        sys.exit("the toolkit's harness maps the XBE otherwise than verify_c expects")
    spans = ", ".join("0x%08Xu" % max(s.vsize, s.raw_size) for s in sections)
    source = source.replace(table_end, table_end + "static const unsigned g_spans[] = { %s };\n" % spans, 1)
    source = source.replace(mapped_hi, "uintptr_t hi = (uintptr_t)g_secs[i].va + g_spans[i];", 1)
    source = source.replace(pristine, (
        "memset((void *)(lo + g_secs[i].raw_size), 0, g_spans[i] - g_secs[i].raw_size);\n"
        "        g_pristine[i] = (unsigned char *)malloc(g_spans[i]);\n"
        "        if (g_pristine[i])\n"
        "            memcpy(g_pristine[i], (void *)lo, g_spans[i]);"), 1)
    return source.replace(restore, "memcpy((void *)(uintptr_t)g_secs[i].va, g_pristine[i],\n"
                                   "                   g_spans[i]);", 1)


def compare_sections(source, memory_only):
    """The harness compares the scratch memory the arguments point into, not
    the XBE's own: a function that writes the game's variables (most of them
    do, and a function with no result does nothing else) passed whatever it
    wrote there. So the sections are kept as the original left them and
    compared with what the C left, and a function that hands back nothing
    (memory_only, their addresses) is compared by the memory alone: its eax
    is whatever it last loaded, which no caller reads."""
    native_done = "    memcpy(g_scratch_native, g_scratch, SCRATCH_SIZE);\n"
    wrote = "    wrote = memcmp(g_scratch_native, g_scratch, SCRATCH_SIZE);\n"
    compare = "    if (nat_eax == g_eax && !wrote) return;\n"
    run_one = "static void run_one(uint32_t va, const uint32_t *raw, int vec, int *shown) {\n"
    if any(part not in source for part in (native_done, wrote, compare, run_one)):
        sys.exit("the toolkit's harness compares otherwise than verify_c expects")
    helpers = (
        "static unsigned char *g_after_native[64];\n"
        "static const uint32_t g_memory_only[] = { %s };\n"
        "static int memory_only(uint32_t va) {\n"
        "    size_t i;\n"
        "    for (i = 0; i < sizeof g_memory_only / sizeof g_memory_only[0]; i++)\n"
        "        if (g_memory_only[i] == va) return 1;\n"
        "    return 0;\n"
        "}\n"
        "/* the sections as the original left them */\n"
        "static void keep_sections(void) {\n"
        "    size_t i;\n"
        "    for (i = 0; i < sizeof g_secs / sizeof g_secs[0]; i++) {\n"
        "        if (!g_pristine[i]) continue;\n"
        "        if (!g_after_native[i]) g_after_native[i] = (unsigned char *)malloc(g_spans[i]);\n"
        "        memcpy(g_after_native[i], (void *)(uintptr_t)g_secs[i].va, g_spans[i]);\n"
        "    }\n"
        "}\n"
        "/* the first address the C left otherwise, 0 if none */\n"
        "static uint32_t sections_differ(void) {\n"
        "    size_t i, k;\n"
        "    for (i = 0; i < sizeof g_secs / sizeof g_secs[0]; i++) {\n"
        "        const unsigned char *now = (const unsigned char *)(uintptr_t)g_secs[i].va;\n"
        "        if (!g_pristine[i] || !memcmp(g_after_native[i], now, g_spans[i])) continue;\n"
        "        for (k = 0; k < g_spans[i]; k++)\n"
        "            if (g_after_native[i][k] != now[k]) return g_secs[i].va + (uint32_t)k;\n"
        "    }\n"
        "    return 0;\n"
        "}\n\n") % (", ".join("0x%08Xu" % va for va in memory_only) or "0")
    source = source.replace(run_one, helpers + run_one, 1)
    source = source.replace(native_done, native_done + "    keep_sections();\n", 1)
    source = source.replace(wrote, wrote + "    { uint32_t at = sections_differ(); if (at) {\n"
                                           "        if (!(*shown)++) printf(\"FAIL sub_%08X\\n\", va);\n"
                                           "        if (*shown <= 3) printf(\"       vec %d  args %08X %08X %08X %08X\\n\"\n"
                                           "                                \"         memory at %08X: the original and the C differ\\n\",\n"
                                           "                                vec, raw[0], raw[1], raw[2], raw[3], at);\n"
                                           "        g_fail++; return; } }\n", 1)
    return source.replace(compare, "    if ((nat_eax == g_eax || memory_only(va)) && !wrote) return;\n", 1)


def count_per_function(source):
    """The harness prints only the vectors compared in all; a function whose
    every vector faulted on the original (it reads memory the harness does not
    map) was compared with nothing. So each function's count is printed too."""
    loop = 'if (shown > 3) printf("       ... and %d more\\n", shown - 3);'
    if loop not in source or "for (i = 0; i < (int)(sizeof g_funcs" not in source:
        sys.exit("the toolkit's harness counts otherwise than verify_c expects")
    source = source.replace("        shown = 0;\n", "        int before = g_total;\n        shown = 0;\n", 1)
    return source.replace(loop, loop + '\n        printf("@VECTORS %08X %d\\n", g_funcs[i], g_total - before);', 1)


def calls_only(funcs):
    """The functions whose original reaches nothing but functions written by
    hand, through its calls and theirs: a direct call elsewhere, or any
    indirect one, on the way leaves one out."""
    data = open(XBE, "rb").read()
    base = struct.unpack_from("<I", data, 0x104)[0]
    count = struct.unpack_from("<I", data, 0x11C)[0]
    headers = struct.unpack_from("<I", data, 0x120)[0] - base
    sections = [struct.unpack_from("<5I", data, headers + i * 56)[1:] for i in range(count)]
    ends = {int(f["start"], 16): int(f["end"], 16) for f in json.load(open(FUNCTIONS))}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    calls = {}
    for va in funcs:
        code = b""
        for start, size, raw, raw_size in sections:
            if start <= va < start + raw_size:
                code = data[raw + va - start: raw + ends.get(va, va) - start]
        targets = [ins.op_str for ins in md.disasm(code, va) if ins.mnemonic == "call"]
        calls[va] = None if any(not t.startswith("0x") or int(t, 16) not in funcs for t in targets)             else {int(t, 16) for t in targets}
    out = {va for va, c in calls.items() if c is not None}
    while True:                         # until no function reaches one left out
        dropped = {va for va in out if not calls[va] <= out}
        if not dropped:
            return out
        out -= dropped


def main():
    from tools.conformance import xbe_run
    import tools.conformance.__main__ as conf

    vcvars = conformance.find_vcvars32()
    if not vcvars:
        sys.exit("no 32-bit MSVC (vcvars32.bat) found")
    decompiled = "--decompiled" in sys.argv[1:]
    if decompiled:
        # the decompiler's (tools/decompile.py build): its arguments on the stack only, as many as the
        # harness passes (four), its results in eax alone; they call none but each other
        funcs = {int(va, 16): (d["entry"], DECOMPILED_C,
                               "CDECL" if not d["registers"] and not d["by_pointer"] and d["arguments"] <= 4
                               else "OTHER", d["arguments"], "int")
                 for va, d in json.load(open(DECOMPILED)).items()}
        what = "written by the decompiler"
    else:
        funcs, _ = hand_functions.hand_functions()
        what = "written by hand"
    if not funcs:
        sys.exit("no functions %s" % what)
    data, sections, base = xbe_run.load(XBE)
    leaves = set(funcs) if decompiled else calls_only(funcs)
    checked = {va: f for va, f in funcs.items() if f[2] == "CDECL" and f[4] in ("int", "void") and va in leaves}
    print("%d functions %s, %d checked here (cdecl, a result in eax or none, no call outside)"
          % (len(funcs), what, len(checked)))

    # Each lifted_ calls an entry; the files that define them, and the calls
    # into the recompiled code, come in ahead of the first.
    files = sorted({f[1] for f in funcs.values()})
    lifted = [(va, f[0], "void lifted_%08X(void) { %s(); }" % (va, f[0]))
              for va, f in sorted(checked.items())]
    includes = "".join('#include "%s"\n' % p.replace("\\", "/")
                       for p in [os.path.join(REPO, p) for p in files] + [GLUE])
    lifted[0] = (lifted[0][0], lifted[0][1], includes + lifted[0][2])
    entries = [(va, name, None) for va, name, _ in lifted]

    os.makedirs(WORK, exist_ok=True)
    for old in ("xbe_harness.exe", "xbe_harness.obj"):
        if os.path.exists(os.path.join(WORK, old)):
            os.remove(os.path.join(WORK, old))      # never run a harness of an earlier build
    with open(os.path.join(WORK, "xbe_harness.c"), "w", encoding="utf-8") as f:
        memory_only = [va for va, f in checked.items() if f[4] == "void"]
        f.write(compare_sections(map_uninitialised(count_per_function(compare_eax_only(
            xbe_run.harness_source(os.path.abspath(XBE), sections, lifted, entries))), sections), memory_only))
    runtime_inc = os.path.join(TOOLKIT, "templates", "runtime")
    game_inc = os.path.join(REPO, "src", "game")
    gen_inc = os.path.join(REPO, "src", "recomp", "gen")        # symbols.h
    decompiled_inc = os.path.join(REPO, "src", "decompiled")    # decompiled.h, x86.h
    # The harness maps the XBE where it was linked, low in the address space,
    # and what Windows randomises there (ASLR) takes some of it now and then:
    # one run in three found the code's sections taken ("mapped nothing", or a
    # section skipped and no vector run). Linking the harness fixed and high
    # made it worse (its stack and heap then always land there), so a run that
    # could not map the code is started again instead.
    r = conf._cl(vcvars, WORK, '/W3 /EHa /I"%s" /I"%s" /I"%s" /I"%s" xbe_harness.c /Fexbe_harness.exe'
                 ' /link /FORCE:UNRESOLVED' % (runtime_inc, game_inc, gen_inc, decompiled_inc))
    if r.returncode != 0:
        sys.exit("harness build failed:\n" + r.stdout + r.stderr)

    # As the toolkit does: a function that brings the harness down is left
    # out and the run starts again.
    exe = os.path.join(WORK, "xbe_harness.exe")
    skips, run, unmapped = [], None, 0
    for _ in range(200):
        cmd = [exe, os.path.abspath(XBE)]
        if skips:
            cmd.append(",".join("%08X" % va for va in skips))
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as hung:
            # a function that never comes back with the harness's vectors (a loop they keep going, on the
            # original or the C): left out as one that brings it down
            out = hung.stdout.decode("utf-8", "replace") if isinstance(hung.stdout, bytes) else (hung.stdout or "")
            started = re.findall(r"@RUN ([0-9A-Fa-f]{8})", out)
            if not started or int(started[-1], 16) in skips:
                sys.exit("the harness stopped answering before it named a function")
            skips.append(int(started[-1], 16))
            continue
        # the code and its data (up to .data's end) have to be mapped; the
        # sections above (DOLBY, BINKDATA, the title images) never are
        skipped = [int(a, 16) for a in re.findall(r"note: ([0-9A-Fa-f]{8})\.\.", run.stdout)]
        # and a run where every call of the original faulted compared nothing,
        # or one that went down before its summary without naming a function:
        # the same collision, further in
        summary = re.search(r"(\d+) function vectors from the title", run.stdout)
        started = re.findall(r"@RUN ([0-9A-Fa-f]{8})", run.stdout)
        lost = (summary and summary.group(1) == "0") or (not summary and run.returncode not in (0, 1)
                                                          and not started)
        if "mapped nothing" in run.stdout or any(a < 0x002C0000 for a in skipped) or lost:
            unmapped += 1
            if unmapped < 12:
                continue
            sys.exit("the harness could not map the XBE's code in 12 runs:\n" + run.stdout)
        started = re.findall(r"@RUN ([0-9A-Fa-f]{8})", run.stdout)
        if run.returncode in (0, 1) or not started:
            break
        casualty = int(started[-1], 16)
        if casualty in skips:
            break
        skips.append(casualty)
    vectors = re.search(r"(\d+) function vectors from the title", run.stdout)
    names = {va: name for va, name, _ in lifted}
    out = run.stdout
    for va, name in names.items():
        out = out.replace("sub_%08X" % va, "%s (0x%08X)" % (name, va))
    print("\n".join(l for l in out.splitlines() if not l.startswith(("@RUN ", "@VECTORS "))).strip())
    if skips:
        print("not checked, they brought the harness down: %s"
              % ", ".join(names.get(va, "0x%08X" % va) for va in skips))
    counts = {int(a, 16): int(n) for a, n in re.findall(r"@VECTORS ([0-9A-Fa-f]{8}) (\d+)", run.stdout)}
    none = [names[va][:-len("_entry")] for va in sorted(names) if va not in skips and counts.get(va, 0) == 0]
    if none:
        print("compared with nothing, every vector faulted on the original: %s" % ", ".join(none))
    print("compared: %d functions" % sum(1 for n in counts.values() if n))
    if not vectors or int(vectors.group(1)) == 0:
        # nothing compared is not a pass
        print("no vector was compared")
        sys.exit(1)
    sys.exit(0 if run.returncode == 0 and not skips else 1)


if __name__ == "__main__":
    main()
