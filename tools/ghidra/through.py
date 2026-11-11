# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        through.py
Description: who reads each word of a record that a word of an entity's record points at, in Ghidra's C
Version:     0.1.0
Created:     11-11-2026
Modified:    11-11-2026
Author:      Sebastian Toyos

An EntitySpec's motions (+0xC0) and death_motions (+0x100) point at records of the type's own. This
lists, from analysis/ghidra/out/all.c, the reads at each offset of the record a variable holds once it
was given the word at OFFSET of what an object's first word points at ("v = *(int *)(*entity + 0xc0);
... *(int *)(v + 0x68)"), and the direct ones ("*(int *)(*(int *)(*entity + 0xc0) + 0x68)").

    py -3 tools/ghidra/through.py C0            the offsets, with the functions that read each
    py -3 tools/ghidra/through.py C0 68 [N]     the lines that read +0x68 of it, with N lines around
"""
import collections
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALL = os.path.join(REPO, "analysis", "ghidra", "out", "all.c")


def functions():
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


def main():
    word = int(sys.argv[1], 16)
    literal = "0x%x" % word if word > 9 else "%d" % word
    # the record's address: the word of what a first word points at, through a variable or not
    source = r"\*\((?:[\w ]+\*)\)\(\*(?:\([\w ]+\*\))?\w+ \+ %s\)" % literal
    held = re.compile(r"^\s*(\w+) = %s;" % source)
    direct = re.compile(r"\(%s \+ (0x[0-9a-f]+|\d+)\)" % source)
    reads = collections.defaultdict(list)
    for address, name, lines in functions():
        names = {m.group(1) for m in map(held.match, lines) if m}
        via = re.compile(r"\((%s) \+ (0x[0-9a-f]+|\d+)\)" % "|".join(sorted(names))) if names else None
        for index, line in enumerate(lines):
            found = [number(m.group(1)) for m in direct.finditer(line)]
            if via is not None:
                found += [number(m.group(2)) for m in via.finditer(line)]
            for offset in found:
                reads[offset].append((name, index, lines))
    if len(sys.argv) > 2:
        offset = int(sys.argv[2], 16)
        around = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        for name, index, lines in reads[offset]:
            print("-- %s" % name)
            print("\n".join(line[:170] for line in lines[max(0, index - around):index + around + 1]))
        return
    for offset in sorted(reads):
        names = collections.Counter(name for name, _, _ in reads[offset])
        print("+0x%03X  %3d  %s" % (offset, len(reads[offset]), ", ".join("%s:%d" % item for item in names.most_common(5))))


if __name__ == "__main__":
    main()
