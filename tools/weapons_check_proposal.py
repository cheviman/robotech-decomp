"""Checks a proposal of symbol lines against symbols/symbols.txt before it is merged by hand.

    py -3 tools/weapons_check_proposal.py [build/sessions/weapons/proposal.txt]

A proposal is lines in symbols.txt's own syntax (type, func, var, struct, field, comment) plus
`rename OLD NEW  # 0xADDRESS: why`, which asks for the name of a func line already there to change.
Reads both files and writes nothing. It tells:

- a line that is in none of those forms;
- a rename whose OLD is no function of symbols.txt, or whose address is not the one written after it;
- a new name (func, var, struct, rename's NEW) that symbols.txt already has for something else;
- a func or var line at an address symbols.txt already names (the line there, to change by hand);
- a type line for a type that has a name already (the swap or the change it asks for);
- a field of a struct neither file declares, or past its size; a var of a struct neither declares;
- a comment for a function neither file names.

and counts what the proposal holds. symbols.txt changes while sessions work on it: run it again before
pasting.
"""
import os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYM = os.path.join(REPO, "symbols", "symbols.txt")
PLAIN = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "f32": 4, "f64": 8, "char": 1}

FUNC = re.compile(r"^([0-9A-Fa-f]{8})\s+func\s+(\w+)")
VAR = re.compile(r"^([0-9A-Fa-f]{8})\s+var\s+(\w+)\s+(\w+)(\[\d*\])?(?:\s+(\w+))?")
TYPE = re.compile(r"^type\s+(\w+)\s+(\d+)\s+(\w+)")
STRUCT = re.compile(r"^struct\s+(\w+)\s+([0-9A-Fa-f]+)")
FIELD = re.compile(r"^field\s+(\w+)\s+([0-9A-Fa-f]+)\s+(\w+)\s+(\w+)(\[(\d+)\])?(?:\s+(\w+))?")
COMMENT = re.compile(r"^comment\s+(\w+)\s+\S")
RENAME = re.compile(r"^rename\s+(\w+)\s+(\w+)\s*(?:#\s*0x([0-9A-Fa-f]+))?")


def read(path):
    """What a file of symbol lines declares: functions and variables both ways, types, structs."""
    funcs, by_addr, variables, types, structs = {}, {}, {}, {}, {}
    for text in open(path, encoding="utf-8", errors="replace"):
        text = text.split("#")[0].rstrip()
        m = FUNC.match(text)
        if m:
            funcs[m.group(2)] = int(m.group(1), 16)
            by_addr[int(m.group(1), 16)] = m.group(2)
            continue
        m = VAR.match(text)
        if m:
            variables[m.group(2)] = int(m.group(1), 16)
            by_addr.setdefault(int(m.group(1), 16), m.group(2))
            continue
        m = TYPE.match(text)
        if m:
            types[(m.group(1), int(m.group(2)))] = m.group(3)
            continue
        m = STRUCT.match(text)
        if m:
            structs[m.group(1)] = int(m.group(2), 16)
    return funcs, by_addr, variables, types, structs


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "build", "sessions", "weapons", "proposal.txt")
    funcs, by_addr, variables, types, structs = read(SYM)
    new_funcs, _, new_vars, _, new_structs = read(path)
    renamed = {}
    for text in open(path, encoding="utf-8"):
        m = RENAME.match(text)
        if m:
            renamed[m.group(1)] = m.group(2)
    known_structs = dict(structs, **new_structs)
    known_funcs = set(funcs) | set(new_funcs) | set(renamed.values())
    # a type line names its four callbacks, which a comment may be for
    count = {k: 0 for k in ("type", "func", "rename", "var", "struct", "field", "comment")}
    trouble = []

    def say(n, what):
        trouble.append("line %d: %s" % (n, what))

    for n, raw in enumerate(open(path, encoding="utf-8"), 1):
        text = raw.split("#")[0].rstrip()
        if not text:
            continue
        m = RENAME.match(raw)
        if m:
            count["rename"] += 1
            old, new, addr = m.group(1), m.group(2), m.group(3)
            if old not in funcs:
                say(n, "rename of %s, which is no function of symbols.txt" % old)
            elif addr and funcs[old] != int(addr, 16):
                say(n, "%s is at %08X in symbols.txt, the line says %s" % (old, funcs[old], addr))
            if new in funcs or new in variables:
                say(n, "%s is a name symbols.txt already has" % new)
            continue
        m = FUNC.match(text)
        if m:
            count["func"] += 1
            addr, name = int(m.group(1), 16), m.group(2)
            if name in funcs and funcs[name] != addr or name in variables:
                say(n, "%s is a name symbols.txt already has" % name)
            if addr in by_addr and by_addr[addr] != name:
                say(n, "%08X is %s in symbols.txt: change that line, or write a rename" % (addr, by_addr[addr]))
            continue
        m = VAR.match(text)
        if m:
            count["var"] += 1
            addr, name, kind, struct = int(m.group(1), 16), m.group(2), m.group(3), m.group(5)
            if name in funcs or name in variables and variables[name] != addr:
                say(n, "%s is a name symbols.txt already has" % name)
            if addr in by_addr and by_addr[addr] != name:
                say(n, "%08X is %s in symbols.txt already" % (addr, by_addr[addr]))
            for s in (kind, struct):
                if s and s not in PLAIN and s not in known_structs:
                    say(n, "%s is a struct neither file declares" % s)
            continue
        m = TYPE.match(text)
        if m:
            count["type"] += 1
            key, name = (m.group(1), int(m.group(2))), m.group(3)
            if key in types and types[key] != name:
                say(n, "%s %d is %s in symbols.txt: this line changes its name" % (key[0], key[1], types[key]))
            other = [k for k, v in types.items() if v == name and k != key]
            if other:
                say(n, "%s is %s %d's name in symbols.txt: a swap, to do in one go" % (name, other[0][0], other[0][1]))
            continue
        m = STRUCT.match(text)
        if m:
            count["struct"] += 1
            if m.group(1) in structs:
                say(n, "struct %s is in symbols.txt already" % m.group(1))
            continue
        m = FIELD.match(text)
        if m:
            count["field"] += 1
            struct, at, kind, many, points = m.group(1), int(m.group(2), 16), m.group(4), m.group(6), m.group(7)
            if struct not in known_structs:
                say(n, "field of %s, a struct neither file declares" % struct)
            elif kind not in PLAIN:
                say(n, "%s is no type of a field" % kind)
            elif at + PLAIN[kind] * int(many or 1) > known_structs[struct]:
                say(n, "%s.%s ends past the struct's %X bytes" % (struct, m.group(3), known_structs[struct]))
            if points and points not in known_structs:
                say(n, "%s is a struct neither file declares" % points)
            continue
        m = COMMENT.match(text)
        if m:
            count["comment"] += 1
            if m.group(1) not in known_funcs:
                say(n, "comment for %s, which neither file names" % m.group(1))
            continue
        say(n, "not a line of symbols.txt nor a rename: %s" % text[:60])

    print("%s: %s" % (os.path.relpath(path, REPO), ", ".join("%d %s" % (v, k) for k, v in count.items())))
    print("\n".join(trouble) if trouble else "nothing to tell")


if __name__ == "__main__":
    main()
