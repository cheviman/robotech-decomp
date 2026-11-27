"""Several proposals of symbol lines against each other, before they are merged one after another.

    py -3.14 tools/cross_proposals.py build/sessions5/*/proposal.txt

Each proposal passes tools/weapons_check_proposal.py against symbols.txt alone; lanes that work side by
side can still meet. This reads them all and tells, with the files and lines:

- a function two proposals rename, or name, differently (the same address, or the same old name);
- a new name two proposals give to different things (functions, variables, structures);
- a new name of one that is the old name of another's rename (a chain: the order of the merge matters);
- a variable's address with two names or two types;
- a structure declared twice with sizes that differ, and a field's offset with two names or types.

Lines that say the same thing twice are counted, not told: the second is dropped by the merge.
Writes nothing.
"""
import collections
import os
import re
import sys

ADDR = re.compile(r"^[0-9A-Fa-f]{8}$")


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    old, new, at = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    variables, structs, fields = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for path in paths:
        lane = os.path.basename(os.path.dirname(path))
        for n, l in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
            f = l.partition("#")[0].split()
            where = "%s:%d" % (lane, n)
            if len(f) >= 3 and f[0] == "rename":
                old[f[1]].append((f[2], where))
                new[f[2]].append(("rename of " + f[1], where))
                m = re.search(r"0x([0-9A-Fa-f]+)|\b([0-9A-Fa-f]{8})\b", l.partition("#")[2])
                if m:
                    at[int(m.group(1) or m.group(2), 16)].append((f[2], where))
            elif len(f) >= 3 and ADDR.match(f[0]) and f[1] == "func":
                at[int(f[0], 16)].append((f[2], where))
                new[f[2]].append(("func " + f[0], where))
            elif len(f) >= 4 and ADDR.match(f[0]) and f[1] == "var":
                variables[int(f[0], 16)].append((" ".join(f[2:]), where))
                new[f[2]].append(("var " + f[0], where))
            elif len(f) == 3 and f[0] == "struct":
                structs[f[1]].append((f[2].upper().lstrip("0") or "0", where))
            elif len(f) >= 5 and f[0] == "field":
                fields[(f[1], int(f[2], 16))].append((" ".join(f[3:]), where))
    told = same = 0

    def tell(what, entries):
        nonlocal told, same
        values = {v for v, _ in entries}
        if len(entries) > 1 and len(values) == 1:
            same += 1
        elif len(values) > 1:
            told += 1
            print("%s:" % what)
            for v, where in entries:
                print("    %-24s %s" % (where, v))

    for name, e in sorted(old.items()):
        tell("%s renamed two ways" % name, e)
    for a, e in sorted(at.items()):
        tell("0x%X named two ways" % a, e)
    for name, e in sorted(new.items()):
        tell("the name %s for two things" % name, e)
    for name in sorted(set(old) & set(new)):
        told += 1
        print("a chain: %s is renamed (%s) and is also the new name of %s" % (
            name, ", ".join(w for _, w in old[name]), ", ".join("%s %s" % (v, w) for v, w in new[name])))
    for a, e in sorted(variables.items()):
        tell("the variable at 0x%X two ways" % a, e)
    for name, e in sorted(structs.items()):
        tell("struct %s with two sizes" % name, e)
    for (name, off), e in sorted(fields.items()):
        tell("field %s +0x%X two ways" % (name, off), e)
    told += overlaps(paths)
    print("%d proposals: %d clashes, %d lines said twice the same" % (len(paths), told, same))


def overlaps(paths):
    """The proposals' variables that cover an address another variable has: one of symbols.txt or of
    another proposal (a variable is as long as its type: a structure's size times its count)."""
    import bisect
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import symbols as S
    sym = S.load()
    sizes = {name: st.get("size", 0) for name, st in sym["structs"].items()}
    unit = {"u8": 1, "s8": 1, "char": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "f32": 4, "f64": 8}
    mine = []
    for path in paths:
        lane = os.path.basename(os.path.dirname(path))
        for n, l in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
            f = l.partition("#")[0].split()
            if len(f) == 3 and f[0] == "struct":
                sizes[f[1]] = max(sizes.get(f[1], 0), int(f[2], 16))
            elif len(f) >= 4 and ADDR.match(f[0]) and f[1] == "var":
                mine.append((int(f[0], 16), f[2], f[3], "%s:%d" % (lane, n)))

    def length(type_name):
        m = re.match(r"^(\w+?)(?:\[(\d*)\])?$", type_name)
        count = int(m.group(2)) if m and m.group(2) else 1
        return max(1, (unit.get(m.group(1)) or sizes.get(m.group(1)) or 4) * count) if m else 4

    # a text of the generated section inside a proposal's variable is no clash: `symbols.py texts`, run
    # after the merge, drops the texts a variable holds
    there = sorted((a, a + length(v["type"]), v["name"], "symbols.txt") for a, v in sym["vars"].items()
                   if not (v["name"].endswith("Text") and v["type"].startswith("char")))
    every = sorted(there + [(a, a + length(t), name, where) for a, name, t, where in mine])
    told, seen = 0, set()
    starts = [e[0] for e in every]
    for a, end, name, where in every:
        if where == "symbols.txt":
            continue
        i = bisect.bisect_left(starts, a)
        for b, b_end, other, other_where in every[max(0, i - 1):]:
            if b >= end:
                break
            if (b, other) == (a, name) or b_end <= a or (a == b and other_where == "symbols.txt"):
                continue                         # itself, clear of it, or the line it takes the place of
            key = tuple(sorted(((a, name), (b, other))))
            if key in seen:
                continue
            seen.add(key)
            told += 1
            print("overlap: %s %s 0x%X..0x%X and %s %s 0x%X..0x%X" % (where, name, a, end, other_where, other, b, b_end))
    return told


if __name__ == "__main__":
    main()
