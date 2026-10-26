"""
Name:        apply_files.py
Description: tells the recompiler which file of the C each function belongs to, from symbols/symbols.txt
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    py -3 tools/apply_files.py

xboxrecomp's recompiler writes " * Source: PATH" in a function's header when
its classification (analysis/func_id/identified_functions.json) has a
source_file -- the field tools.func_id and tools.debug_symbols fill. This
fills it from the file lines of symbols.txt (each function goes to the file
of the last file line at or before its address), after func_id and before
the recompiler; tools/organize_gen.py then moves each function to its file.
"""
import bisect
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTIFIED = os.path.join(REPO, "analysis", "func_id", "identified_functions.json")
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402


def main():
    files = symbols.load()["files"]
    starts = [a for a, _, _ in files]
    ident = json.load(open(IDENTIFIED))
    placed = 0
    for e in ident:
        a = int(e["start"], 16)
        i = bisect.bisect_right(starts, a) - 1
        if i >= 0:
            e["source_file"] = files[i][1] + ".c"
            placed += 1
    with open(IDENTIFIED, "w", newline="\n") as fh:
        json.dump(ident, fh, indent=2)
    print("placed %d of %d functions in %d files" % (placed, len(ident), len({p for _, p, _ in files})))


if __name__ == "__main__":
    main()
