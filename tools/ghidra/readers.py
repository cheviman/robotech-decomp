# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        readers.py
Description: who reads each word of the record an object's first word points at, in Ghidra's C
Version:     0.1.0
Created:     11-11-2026
Modified:    11-11-2026
Author:      Sebastian Toyos

An entity's first word points at its type's record of 65 pointers (PENDING.md), so the shared code
reaches a constant of the type as "*(float *)*(int *)(*entity + 0x68)", or through a variable that holds
"*entity". This lists, from the C of every function that tools/ghidra/RobotechDecompileAll.java wrote
(analysis/ghidra/out/all.c), the functions that read at each offset of what a first word points at, and
which of them tools/decompile.py does not have in its build. A read through any other record whose first
word is a pointer shows here too: the functions say which it is.

    py -3 tools/ghidra/readers.py             the offsets, with how many functions read each
    py -3 tools/ghidra/readers.py 68 [N]      the lines that read offset 0x68, of up to N functions
"""
import collections
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALL = os.path.join(REPO, "analysis", "ghidra", "out", "all.c")
BUILT = os.path.join(REPO, "analysis", "decompiled_functions.json")
LIMIT = 0x104       # the record's size

HELD = re.compile(r"^\s*(\w+) = \*(?:\([\w ]+\*\))?(\w+);")
DIRECT = re.compile(r"\(\*(?:\([\w ]+\*\))?(\w+) \+ (0x[0-9a-f]+|\d+)\)")
FIRST = re.compile(r"\*\*(?:\([\w ]+\*\*\))?(\w+)\b(?! \+)")


def functions():
    """(address, name, lines) of each function of all.c."""
    address, name, lines = None, None, []
    for line in open(ALL, encoding="utf-8", errors="replace"):
        head = re.match(r"// ==== ([0-9A-F]{8}) (\S+)", line)
        if head:
            if address is not None:
                yield address, name, lines
            address, name, lines = int(head.group(1), 16), head.group(2), []
        else:
            lines.append(line.rstrip("\n"))
    if address is not None:
        yield address, name, lines


def number(text):
    return int(text, 16) if text.startswith("0x") else int(text)


def game_code():
    """Whether an address is in the game's or the engine's code, by symbols.txt's file lines (the XDK's
    and Bink's functions read records of their own whose first word is a pointer)."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import bisect
    import symbols
    files = symbols.load()["files"]
    starts = [address for address, _, _ in files]

    def own(address):
        position = bisect.bisect_right(starts, address) - 1
        return position >= 0 and not files[position][1].startswith(("xdk/", "bink/"))
    return own


def main():
    built = {int(key, 16) for key in json.load(open(BUILT))} if os.path.exists(BUILT) else set()
    own = game_code()
    reads = collections.defaultdict(list)       # offset -> [(address, name, line)]
    for address, name, lines in functions():
        if not own(address):
            continue
        held = {m.group(1) for m in map(HELD.match, lines) if m}
        via = re.compile(r"\((%s) \+ (0x[0-9a-f]+|\d+)\)" % "|".join(sorted(held))) if held else None
        for line in lines:
            if HELD.match(line):
                continue
            found = [number(m.group(2)) for m in DIRECT.finditer(line)]
            if via is not None:
                found += [number(m.group(2)) for m in via.finditer(line)]
            found += [0] * len(FIRST.findall(line))     # the record's first word: **entity
            for offset in found:
                if offset < LIMIT and offset % 4 == 0:
                    reads[offset].append((address, name, line.strip()))
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        # every offset with up to N different lines that read it, for reading them in one go
        most = int(sys.argv[2]) if len(sys.argv) > 2 else 4
        for offset in sorted(reads):
            names = {address for address, _, _ in reads[offset]}
            print("+0x%02X  %d functions, %d not in the build" % (offset, len(names), len(names - built)))
            shown = set()
            for address, name, line in reads[offset]:
                key = re.sub(r"\b[a-z]+Var\d+\b|\bparam_\d+\b|\bunaff_\w+\b", "v", line)
                if key in shown:
                    continue
                shown.add(key)
                print("   %-28s %s" % (name[:28], line[:150]))
                if len(shown) == most:
                    break
        return
    if len(sys.argv) > 1:
        offset = int(sys.argv[1], 16)
        most = int(sys.argv[2]) if len(sys.argv) > 2 else 8
        seen = []
        for address, name, line in reads[offset]:
            if name not in seen:
                if len(seen) == most:
                    break
                seen.append(name)
                print("-- %08X %s%s" % (address, name, "" if address in built else "   (not in the build)"))
            print("   " + line[:200])
        return
    print("offset  reads  functions  of them not in the build")
    for offset in sorted(reads):
        names = {address for address, _, _ in reads[offset]}
        print("  +0x%02X  %5d  %9d  %d" % (offset, len(reads[offset]), len(names), len(names - built)))
    print("%d offsets of %d have a reader" % (len(reads), LIMIT // 4))


if __name__ == "__main__":
    main()
