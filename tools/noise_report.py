"""
Name:        noise_report.py
Description: counts, in one pass over the generated C, every kind of noise that keeps it from reading
             as code a person wrote, and compares it with the baseline kept in the repo
Version:     0.3.0
Created:     25-10-2026
Modified:    28-10-2026
Author:      Sebastian Toyos

The C under src/recomp/gen/ is a recompilation: xboxrecomp lifts each x86
instruction, with the CPU's registers as variables, its flags as
temporaries, its stack in memory and its jumps as labels. The goal is C that
reads as written by a person, every name real; each kind of noise that keeps
it from that is counted here, so a round of work shows what it took away.

The C under src/decompiled/ is the decompiler's (tools/decompile.py): structured, its stack as local
variables, but with noise of its own, counted apart (the decompiled_ kinds): the registers and flags it
keeps as variables by their names, its parameters and stack slots without names of their own, the
memory it reaches by address, the functions with no name or description yet.

    py -3 tools/noise_report.py           # the table, against tools/noise_baseline.txt
    py -3 tools/noise_report.py --save    # the current counts become the baseline

Exits 1 when a count went up from the baseline.

xboxrecomp has no such count (its tests check that the C builds and runs, not
how it reads), so it is this project's.
"""
import argparse
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import hand_functions  # noqa: E402  (the functions written by hand, by their entries)
GEN = os.path.join(REPO, "src", "recomp", "gen")
DECOMPILED = os.path.join(REPO, "src", "decompiled")
BASELINE = os.path.join(REPO, "tools", "noise_baseline.txt")

DEF = re.compile(r"^void (\w+)\(void\)\s*$", re.M)
# a name that is a number or a position rather than what the thing is
PLACEHOLDER = re.compile(r"(_[0-9A-F]{8}$|_Cb[0-9A-F]{2}$|^[A-Za-z]+\d{2,3}_|_Default[0-9A-F]{2}$|^xdk_|^unk_)")

# (key, what it is, pattern counted over the code, or a function of the files)
KINDS = [
    ("functions", "functions in the generated C", None),
    ("unnamed", "functions without a name: sub_<address>", None),
    ("placeholder", "names that are a number or a position (type numbers, slot offsets, addresses)", None),
    ("uncommented", "functions without a description of what they do", None),
    ("numbered_files", "files cut by count, not by subject (recomp_NNNN.c)", None),
    ("unsorted", "functions in no subject's file yet (game/unsorted.c)", None),
    ("registers", "CPU registers as variables (eax, esp...)", re.compile(r"\b(?:eax|ebx|ecx|edx|esi|edi|ebp|esp)\b")),
    ("flags", "CPU flags as temporaries (_fa, _fb, _flags...)", re.compile(r"\b_(?:fa|fb|fas|fbs|flags)\b")),
    ("fpu_stack", "the x87 register stack (fp_top, fp_st...)", re.compile(r"\bfp_(?:top|st\d?)\b")),
    ("memory_by_address", "memory read or written at a raw address: MEM32(0x...)", re.compile(r"\bMEM(?:8|16|32|64|F|D)?\(0x[0-9A-Fa-f]+\)")),
    ("memory_computed", "memory at a computed address: MEM32(reg + n)", re.compile(r"\bMEM(?:8|16|32|64|F|D)?\((?!0x[0-9A-Fa-f]+\))")),
    ("labels", "labels of the original's jumps (loc_<address>:)", re.compile(r"^\s*loc_[0-9A-F]{8}:", re.M)),
    ("gotos", "goto", re.compile(r"\bgoto\b")),
    ("stack_returns", "returns that pop the emulated stack (esp += n; return;)", re.compile(r"esp \+= \d+; return;")),
    # the sites that look their target up; not the guarded direct arms the
    # recompiler adds for targets the runs have seen (RECOMP_ICALL_GUARD_*)
    ("indirect_calls", "calls through a guest address looked up at run time",
     re.compile(r"\bRECOMP_ICALL_SAFE(?:_AT)?(?:_CC)?\(")),
]

# the decompiler's C (src/decompiled/), counted apart: its entries (NAME_entry, the glue the recompiled code
# calls) are left out
DECOMPILED_KINDS = [
    ("decompiled_functions", "functions the decompiler writes", None),
    ("decompiled_unnamed", "of them without a name: sub_<address>", None),
    ("decompiled_uncommented", "of them without a description of what they do", None),
    ("decompiled_registers", "CPU registers as variables, by their names (eax, ecx_2...)",
     re.compile(r"\b(?:eax|ebx|ecx|edx|esi|edi|ebp)(?:_\d+)?\b")),
    ("decompiled_flags", "CPU flags as variables (zero, negative, overflow, carry)",
     re.compile(r"\b(?:zero|negative|overflow|carry)(?:_\d+)?\b")),
    ("decompiled_arguments", "parameters named by their place (arg0, arg1...)", re.compile(r"\barg\d+(?:_\d+)?\b")),
    ("decompiled_slots", "stack slots named by their offset or the register they save (stack_4, saved_eax)",
     re.compile(r"\b(?:stack(?:_[0-9A-F]+)?|saved_\w+?)(?:_\d+)?\b")),
    ("decompiled_memory_by_address", "memory read or written at a raw address: MEM32(0x...)",
     re.compile(r"\b(?:MEM(?:8|16|32|F|D)|FLOAT_AT)\(0x[0-9A-Fa-f]+u?\)")),
    ("decompiled_memory_computed", "memory at a computed address: MEM32(p + n)",
     re.compile(r"\b(?:MEM(?:8|16|32|F|D)|FLOAT_AT)\((?!0x[0-9A-Fa-f]+u?\))")),
    ("decompiled_float_registers", "x87 values named by their stack depth (f0, f1_2...)",
     re.compile(r"\bf[0-7](?:_\d+)?\b")),
    ("decompiled_float_bits", "floating-point values carried as their bits (x87_float(t), float_to_bits...)",
     re.compile(r"\b(?:x87_float|float_to_bits|float_from_bits|double_from_bits|double_to_bits)\(")),
    ("decompiled_gotos", "goto", re.compile(r"\bgoto\b")),
]
NOT_NOISE = ("functions", "decompiled_functions")    # counts of work done, not of noise


def measure():
    files = sorted(glob.glob(os.path.join(GEN, "**", "*.c"), recursive=True))
    counts = {k: 0 for k, _, _ in KINDS}
    for path in files:
        text = open(path, encoding="utf-8", errors="replace").read()
        names = DEF.findall(text)
        counts["functions"] += len(names)
        counts["unnamed"] += sum(1 for n in names if re.match(r"sub_[0-9A-F]{8}(_gen)?$", n))
        counts["placeholder"] += sum(1 for n in names if not n.startswith("sub_")
                                     and PLACEHOLDER.search(n.replace("_gen", "")))
        # the generator's header names the function and its original span;
        # a description is any line besides those
        for m in re.finditer(r"/\*\*\n((?: \*.*\n)+?) \*/\nvoid \w+\(void\)", text):
            lines = [l[3:].strip() for l in m.group(1).splitlines()]
            told = [l for l in lines if l and not re.match(r"(\w+$|Original:|Category:|Source:|CC:|Frame:)", l)]
            if not told:
                counts["uncommented"] += 1
        if re.match(r"recomp_\d{4}\.c$", os.path.basename(path)):
            counts["numbered_files"] += 1
        if path.replace("\\", "/").endswith("game/unsorted.c"):
            counts["unsorted"] += len(names)
        for key, _, pattern in KINDS:
            if pattern is not None:
                counts[key] += len(pattern.findall(text))
    return counts


def measure_decompiled():
    counts = {k: 0 for k, _, _ in DECOMPILED_KINDS}
    for path in sorted(glob.glob(os.path.join(DECOMPILED, "*.c"))):
        text = open(path, encoding="utf-8", errors="replace").read()
        # the functions, but for the entries at the end
        bodies = re.split(r"(?m)^(?=\w[\w \*]*\b\w+\([^;]*\)\s*$)", text)
        for body in bodies:
            head = re.match(r"(?m)^\w[\w \*]*?\b(\w+)\(", body)
            if head is None or head.group(1).endswith("_entry"):
                continue
            counts["decompiled_functions"] += 1
            counts["decompiled_unnamed"] += bool(re.match(r"sub_[0-9A-F]{8}$", head.group(1)))
            for key, _, pattern in DECOMPILED_KINDS:
                if pattern is not None:
                    counts[key] += len(pattern.findall(body))
        # a description is the comment right above a function
        for m in re.finditer(r"(?m)(\*/\n)?^\w[\w \*]*?\b(\w+)\([^;\n]*\)\n\{", text):
            if not m.group(2).endswith("_entry") and not m.group(1):
                counts["decompiled_uncommented"] += 1
    return counts


def load_baseline():
    base = {}
    if os.path.exists(BASELINE):
        for line in open(BASELINE, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line:
                key, value = line.split()
                base[key] = int(value)
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", action="store_true", help="write the current counts as the baseline")
    args = ap.parse_args()

    counts = measure()
    counts.update(measure_decompiled())
    base = load_baseline()
    worse = []
    print("%-28s %10s %10s  %s" % ("kind", "baseline", "now", "what"))
    for key, what, _ in KINDS + DECOMPILED_KINDS:
        now, was = counts[key], base.get(key)
        mark = ""
        if was is not None and key not in NOT_NOISE:
            mark = "  up" if now > was else ("  down" if now < was else "")
            if now > was:
                worse.append(key)
        print("%-28s %10s %10d  %s%s" % (key, "-" if was is None else was, now, what, mark))
    hand, _ = hand_functions.hand_functions()
    print("written by hand (src/game/): %d functions" % len(hand))
    if args.save:
        with open(BASELINE, "w", encoding="utf-8", newline="\n") as f:
            f.write("# tools/noise_report.py --save; one kind a line: key count\n")
            for key, _, _ in KINDS + DECOMPILED_KINDS:
                f.write("%s %d\n" % (key, counts[key]))
        print("saved %s" % os.path.relpath(BASELINE, REPO))
    if worse and not args.save:
        print("went up: %s" % ", ".join(worse))
        sys.exit(1)


if __name__ == "__main__":
    main()
