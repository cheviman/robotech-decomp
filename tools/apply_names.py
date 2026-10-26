"""
Name:        apply_names.py
Description: writes the names of symbols/symbols.txt into the disassembly (analysis/disasm/functions.json)
             before recompiling
Version:     0.2.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    py -3 tools/apply_names.py

The recompiler emits whatever `name` an entry of functions.json carries, as
the C function name, in call sites and in the dispatch table. tools.disasm
rewrites functions.json from scratch, so this runs after it every time
(pipeline.py does), and every run starts from the disassembler's own names,
so a name symbols.txt no longer gives does not stay behind.

symbols.txt is the one place names live (tools/symbols.py); the names in it
are already the C's, prefixes for clashes included.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCS = os.path.join(REPO, "analysis", "disasm", "functions.json")
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402


def main():
    wanted = symbols.load()["func"]
    funcs = json.load(open(FUNCS))
    by_start = {int(f["start"], 16): f for f in funcs}
    for f in funcs:
        if f.get("detection_method") != "entry_point":
            f["name"] = "sub_%08X" % int(f["start"], 16)
    applied, missing = 0, []
    for a, name in sorted(wanted.items()):
        f = by_start.get(a)
        if not f:
            missing.append((a, name))
            continue
        if f.get("detection_method") == "entry_point":
            # main.c calls the entry by this name (the template's contract)
            f["name"] = "xbe_entry_point"
            continue
        f["name"] = name
        applied += 1
    with open(FUNCS, "w", newline="\n") as fh:
        json.dump(funcs, fh, indent=2)
    print("named %d functions from symbols/symbols.txt" % applied)
    for a, name in missing:
        print("  not a disasm entry, skipped: 0x%08X %s" % (a, name))


if __name__ == "__main__":
    main()
