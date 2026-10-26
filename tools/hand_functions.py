"""
Name:        hand_functions.py
Description: lists the functions written by hand, for the recompiler to leave them out
Version:     0.3.0
Created:     25-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

    py -3 tools/hand_functions.py

A function of symbols/symbols.txt that src/game/**/*.c writes by hand is C
with its own signature, and beside it an entry, ENTRY_<convention>(NAME)
(src/game/decomp.h), which defines NAME_entry: the function as the recompiled
code calls it. This writes them as {address: NAME_entry} to
analysis/hand_functions.json, which xboxrecomp's recompiler takes as
--manual-functions: it generates no body for them, and declares and calls
the entries in their place.

src/recomp_manual.c wraps others, or replaces them: it defines NAME and calls
the generated body, NAME_gen. The recompiler knows a function by its address
only: it takes the definitions of sub_X there for functions it must not
generate, and `extern void sub_X_gen(void);` for wrapped ones, whose body it
generates as sub_X_gen (--exclude-manual); tools/organize_gen.py gives both
their names back after. So the file the recompiler reads is a copy of
recomp_manual.c with each NAME and NAME_gen of a function of symbols.txt as
sub_X and sub_X_gen: analysis/recomp_manual.c.
"""
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(REPO, "src", "game")
OUT = os.path.join(REPO, "analysis", "hand_functions.json")
MANUAL = os.path.join(REPO, "src", "recomp_manual.c")
MANUAL_FOR_TOOLKIT = os.path.join(REPO, "analysis", "recomp_manual.c")
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402

# ENTRY_CDECL2(vcObjectFind), ENTRY_CDECL1_VOID(...), ENTRY_CDECL0_FLOAT(...), ENTRY_THISCALL0_VOID(...),
# ENTRY_REGISTERS_VOID(vcSceneObjectUnlink, g_eax, g_esi, g_ebx)
ENTRY = re.compile(r"(?m)^ENTRY_([A-Z]+)(\d*)(_VOID|_FLOAT)?\((\w+)(?:,.*)?\)\s*$")


def hand_functions():
    """{address: (entry, file, convention, arguments, result)} of the
    functions src/game/ writes by hand: convention "CDECL", "VARARGS",
    "THISCALL" or "REGISTERS" (its arguments listed in the entry); result
    "int" (in eax), "float" (in st(0)) or "void"."""
    by_name = {n: a for a, n in symbols.load()["func"].items()}
    out, unknown = {}, []
    for path in sorted(glob.glob(os.path.join(GAME, "**", "*.c"), recursive=True)):
        for convention, count, kind, name in ENTRY.findall(open(path, encoding="utf-8").read()):
            if name in by_name:
                result = {"": "int", "_VOID": "void", "_FLOAT": "float"}[kind]
                out[by_name[name]] = (name + "_entry", os.path.relpath(path, REPO).replace("\\", "/"),
                                      convention, int(count or 0), result)
            else:
                unknown.append("%s (%s)" % (name, os.path.relpath(path, REPO)))
    return out, unknown


def manual_for_toolkit():
    """recomp_manual.c in the recompiler's names: each wrapper NAME it defines
    as sub_X, each NAME_gen as sub_X_gen."""
    by_name = {n: a for a, n in symbols.load()["func"].items()}

    def toolkit_name(match):
        addr = by_name.get(match.group(2))
        return "%ssub_%08X%s" % (match.group(1), addr, match.group(3)) if addr is not None else match.group(0)

    text = open(MANUAL, encoding="utf-8").read()
    text = re.sub(r"()\b(\w+)(_gen)\b", toolkit_name, text)
    text = re.sub(r"(?m)^(void )(\w+)(\(void\))$", toolkit_name, text)
    with open(MANUAL_FOR_TOOLKIT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return len(re.findall(r"(?m)^void sub_[0-9A-F]{8}\(void\)$", text))


def main():
    found, unknown = hand_functions()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"0x%08X" % a: f_[0] for a, f_ in sorted(found.items())}, f, indent=1)
        f.write("\n")
    print("%d functions written by hand" % len(found))
    print("%d functions wrapped or replaced by src/recomp_manual.c" % manual_for_toolkit())
    for u in unknown:
        print("  not a function of symbols.txt, not handed to the recompiler: %s" % u)


if __name__ == "__main__":
    main()
