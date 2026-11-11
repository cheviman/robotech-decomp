# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        show.py
Description: prints Ghidra's C of some functions out of analysis/ghidra/out/all.c
Version:     0.1.0
Created:     11-11-2026
Modified:    11-11-2026
Author:      Sebastian Toyos

    py -3 tools/ghidra/show.py 19A30 AC520        the C of the functions at those addresses
    py -3 tools/ghidra/show.py -s 19A30 AC520     only how many lines each has
    py -3 tools/ghidra/show.py -g TEXT 19A30      only its lines with TEXT, and the two around each
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALL = os.path.join(REPO, "analysis", "ghidra", "out", "all.c")


def main():
    args = sys.argv[1:]
    sizes = "-s" in args
    grep = None
    if "-g" in args:
        grep = args[args.index("-g") + 1]
        args = [a for i, a in enumerate(args) if a != "-g" and (i == 0 or args[i - 1] != "-g")]
    wanted = {int(a, 16) for a in args if not a.startswith("-")}
    current, lines = None, []

    def flush():
        if current is None or current[0] not in wanted:
            return
        body = [line for line in lines if line.strip()]
        if sizes:
            print("%08X %-32s %d lines" % (current[0], current[1], len(body)))
            return
        print("// ==== %08X %s" % current)
        if grep is None:
            print("\n".join(body))
            return
        for i, line in enumerate(body):
            if grep in line:
                print("\n".join(body[max(0, i - 2):i + 3]))
                print("   --")

    for line in open(ALL, encoding="utf-8", errors="replace"):
        head = re.match(r"// ==== ([0-9A-F]{8}) (\S+)", line)
        if head:
            flush()
            current, lines = (int(head.group(1), 16), head.group(2)), []
        else:
            lines.append(line.rstrip("\n"))
    flush()


if __name__ == "__main__":
    main()
