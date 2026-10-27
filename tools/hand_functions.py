"""
Name:        hand_functions.py
Description: lists the functions written by hand, for the recompiler to leave them out
Version:     0.4.0
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
the entries in their place. The functions tools/decompile.py build writes
into src/decompiled/ go in the same list, found by the entries defined
there.

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
DECOMPILED_DIR = os.path.join(REPO, "src", "decompiled")
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


def decompiled_functions():
    """{address: NAME_entry} of the functions src/decompiled/ defines, by the entries it defines
    (tools/decompile.py build): NAME is a name of symbols.txt or sub_ and the address."""
    names = {name: address for address, name in symbols.load()["func"].items()}
    found = {}
    for path in glob.glob(os.path.join(DECOMPILED_DIR, "*.c")):
        for name in re.findall(r"(?m)^void (\w+)_entry\(void\)$", open(path, encoding="utf-8").read()):
            address = names.get(name)
            if address is None and re.match(r"sub_[0-9A-F]{8}$", name):
                address = int(name[4:], 16)
            if address is None:
                sys.exit("src/decompiled/: %s_entry, of no function of symbols.txt" % name)
            found[address] = name + "_entry"
    return found


def main():
    found, unknown = hand_functions()
    listed = {"0x%08X" % a: f_[0] for a, f_ in sorted(found.items())}
    # the ones tools/decompile.py build wrote into src/decompiled/, in their recompiled versions' place too
    decompiled = decompiled_functions()
    for address, entry in decompiled.items():
        listed.setdefault("0x%08X" % address, entry)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(listed.items())), f, indent=1)
        f.write("\n")
    print("%d functions written by hand, %d by the decompiler" % (len(found), len(decompiled)))
    print("%d functions wrapped or replaced by src/recomp_manual.c" % manual_for_toolkit())
    for u in unknown:
        print("  not a function of symbols.txt, not handed to the recompiler: %s" % u)


if __name__ == "__main__":
    main()
