"""
Name:        hand_functions.py
Description: lists the functions src/game/ defines by hand, for the recompiler to leave them out
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    py -3 tools/hand_functions.py

Every `void NAME(void)` defined in src/game/**/*.c whose NAME is a function
of symbols/symbols.txt is the game's function at that address, written by
hand. This writes them as {address: name} to analysis/hand_functions.json,
which xboxrecomp's recompiler takes as --manual-functions: it generates no
body for them, and declares and calls them by that name.
"""
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(REPO, "src", "game")
OUT = os.path.join(REPO, "analysis", "hand_functions.json")
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402

DEF = re.compile(r"(?m)^void (\w+)\(void\)\s*$")


def hand_functions():
    """{address: (name, file)} of the functions src/game/ defines."""
    by_name = {n: a for a, n in symbols.load()["func"].items()}
    out, unknown = {}, []
    for path in sorted(glob.glob(os.path.join(GAME, "**", "*.c"), recursive=True)):
        for name in DEF.findall(open(path, encoding="utf-8").read()):
            if name in by_name:
                out[by_name[name]] = (name, os.path.relpath(path, REPO).replace("\\", "/"))
            else:
                unknown.append("%s (%s)" % (name, os.path.relpath(path, REPO)))
    return out, unknown


def main():
    found, unknown = hand_functions()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"0x%08X" % a: n for a, (n, _) in sorted(found.items())}, f, indent=1)
        f.write("\n")
    print("%d functions written by hand" % len(found))
    for u in unknown:
        print("  not a function of symbols.txt, not handed to the recompiler: %s" % u)


if __name__ == "__main__":
    main()
