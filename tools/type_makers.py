"""What the code says of each object type that has no `type` line yet, in one table.

    py -3 tools/type_makers.py [all]

For every type of symbols/registries.json without a name (every type with `all`): the functions that make
one by its number (GameObjectCreate with its family, or a family's own maker: WeaponCreate,
EffectCreateInstance...), the types whose functions take a use of it (GameObjectTypeUse), the types its
own functions use, and the strings only its own functions hand on (a function several types share says
nothing of one of them). The numbers are followed through the decompiled C's arguments and its pushes in
a straight line, so a number that comes from a table or a variable is not seen: a type nobody is seen to
make is made from the levels' data or from a table.
"""
import collections, json, os, re, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src", "decompiled", "decompiled.c")
SYM = os.path.join(REPO, "symbols", "symbols.txt")
XBE = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "default.xbe")


def xbe_strings():
    d = open(XBE, "rb").read()
    base = struct.unpack_from("<I", d, 0x104)[0]
    count, headers = struct.unpack_from("<II", d, 0x11C)
    secs = [struct.unpack_from("<IIIII", d, headers - base + i * 56)[1:] for i in range(count)]

    def at(va):
        for v, _, raw, size in secs:
            if v <= va < v + size:
                o = raw + va - v
                t = d[o:d.find(b"\0", o)]
                if 2 < len(t) < 70 and all(32 <= c < 127 for c in t):
                    return t.decode("latin1")
        return None
    return at


def functions():
    """[(name, parameters, body lines)] of the decompiled C."""
    lines = open(SRC, encoding="utf-8").read().split("\n")
    sig = re.compile(r"^[A-Za-z_][\w \*]*?\b(\w+)\((.*)\)$")
    out, i = [], 0
    while i < len(lines):
        m = sig.match(lines[i])
        if m and i + 1 < len(lines) and lines[i + 1] == "{":
            j = i + 2
            while lines[j] != "}":
                j += 1
            params = [p.split()[-1].lstrip("*") for p in m.group(2).split(",") if p.strip() != "void"]
            out.append((m.group(1), params, lines[i + 2:j]))
            i = j + 1
        else:
            i += 1
    return out


CONST = re.compile(r"^(0x[0-9A-Fa-f]+|\d+)u$")
ASSIGN = re.compile(r"^\t+(\w+) = (.+);$")
PUSH = re.compile(r"^\t+MEM32\(g_esp(?: \+ (0x[0-9A-Fa-f]+|\d+)u)?\) = (.+);$")
MOVE = re.compile(r"^\t+g_esp = g_esp ([-+]) (0x[0-9A-Fa-f]+|\d+)u;$")
READ = re.compile(r"^MEM32\(g_esp(?: \+ (0x[0-9A-Fa-f]+|\d+)u)?\)$")
CALL = re.compile(r"\b(\w+)\(([^()]*)\)")


def calls_with_numbers(body):
    """(callee, [argument value or None]) for each call of a body, the constants followed in a line."""
    val, stack = {}, []

    def value(text):
        text = text.strip().lstrip("&")
        if CONST.match(text):
            return int(text[:-1], 0)
        m = READ.match(text)
        if m:
            k = int(m.group(1) or "0", 0) // 4
            return stack[-1 - k] if k < len(stack) else None
        return val.get(text)

    for t in body:
        m = MOVE.match(t)
        if m:
            n = int(m.group(2), 0) // 4
            if m.group(1) == "-":
                stack.extend([None] * n)
            else:
                del stack[max(len(stack) - n, 0):]
            continue
        m = PUSH.match(t)
        if m:
            k = int(m.group(1) or "0", 0) // 4
            if k < len(stack):
                stack[-1 - k] = value(m.group(2))
            continue
        for c in CALL.finditer(t):
            texts = [a.strip() for a in c.group(2).split(",")] if c.group(2).strip() else []
            if c.group(1) == "x86_call" and len(texts) >= 3:
                # a call the decompiler left on the guest's stack: its arguments are the last pushed
                callee = texts[0][:-6] if texts[0].endswith("_entry") else texts[0]
                given = [value(a) for a in texts[3:]]
                yield callee, given or [stack[-1 - k] for k in range(min(len(stack), 8))]
            elif c.group(1) not in ("MEM32", "MEM16", "MEM8", "MEMF", "FLOAT_AT", "if", "while", "x87_round"):
                yield c.group(1), [value(a) for a in texts]
        m = ASSIGN.match(t)
        if m:
            val[m.group(1)] = value(m.group(2)) if "(" not in m.group(2) or READ.match(m.group(2)) else None
        elif t.startswith("\t") and t.rstrip().endswith(":"):
            val.clear()


def main():
    everything = len(sys.argv) > 1 and sys.argv[1] == "all"
    string_at = xbe_strings()
    name_of, typed = {}, {}
    for t in open(SYM, encoding="utf-8"):
        p = t.split()
        if len(p) >= 3 and p[1] == "func" and re.match(r"^[0-9A-F]{8}$", p[0]):
            name_of[int(p[0], 16)] = p[2]
        if len(p) >= 4 and p[0] == "type" and p[2].isdigit():
            typed[(p[1], int(p[2]))] = p[3]
    families = json.load(open(os.path.join(REPO, "symbols", "registries.json")))["families"]
    family_name = {f["number"]: f["name"] for f in families}
    funcs = functions()
    by_name = {n: (params, body) for n, params, body in funcs}

    # whose function each one is: {function name: [(family, type)]}
    owners = collections.defaultdict(list)
    for f in families:
        for t in f["types"]:
            for a in [t["register"]] + list(t["slots"].values()):
                a = int(a, 16)
                owners[name_of.get(a, "sub_%08X" % a)].append((f["name"], t["type"]))

    def label(key):
        return typed.get(key) or "%s %d" % key

    # who calls whom, to follow a type's own functions into what only they call
    calls_of, callers = {}, collections.defaultdict(set)
    word = re.compile(r"\b([A-Za-z_]\w*)\b")
    for n, params, body in funcs:
        calls_of[n] = {w for w in word.findall("\n".join(body)) if w in by_name and w != n}
        for c in calls_of[n]:
            if n != c + "_entry":       # a function's own entry, as the recompiled code calls it
                callers[c].add(n)

    # the named data each function reads: a variable of symbols.txt, or a structure's field
    variables = set()
    for t in open(SYM, encoding="utf-8"):
        p = t.split()
        if len(p) >= 4 and p[1] == "var" and re.match(r"^[0-9A-F]{8}$", p[0]):
            variables.add(p[2])
    field = re.compile(r"\b([A-Z]\w*?_[a-z]\w*)\(")
    data_of, readers = {}, collections.Counter()
    for n, params, body in funcs:
        text = "\n".join(body)
        found = {w[:-3] if w.endswith("_VA") else w for w in word.findall(text)}
        data_of[n] = (found & variables) | set(field.findall(text))
        for w in data_of[n]:
            readers[w] += 1

    # the game's texts by their number (tools/string_table.py writes them; not in git)
    texts, table = {}, os.path.join(REPO, "analysis", "string_table.txt")
    if os.path.exists(table):
        for t in open(table, encoding="utf-8", errors="replace"):
            m = re.match(r"^(0x[0-9A-Fa-f]+)\s+(\S+)\s*(.*)$", t)
            if m:
                texts[int(m.group(1), 16)] = "%s \"%s\"" % (m.group(2), m.group(3).strip()[:40])

    # a family's own makers: a function that hands GameObjectCreate its family as a number and a type
    # that is no number, which is then its own first argument (WeaponCreate, EffectCreateInstance)
    makers = {"GameObjectCreate": (None, 1)}
    for n, params, body in funcs:
        for callee, args in calls_with_numbers(body):
            if callee == "GameObjectCreate" and len(args) > 1 and args[0] in family_name and args[1] is None                     and params and params[0] == "arg0":
                makers[n] = (args[0], 0)
    print("makers: " + ", ".join("%s (%s, argument %d)" % (n, family_name.get(f, "any family"), k)
                                 for n, (f, k) in sorted(makers.items())))

    made, used_by, uses = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    for n, params, body in funcs:
        for callee, args in calls_with_numbers(body):
            if callee in makers:
                fam, k = makers[callee]
                fam = args[0] if fam is None and args else fam
                if fam in family_name and k < len(args) and args[k] is not None:
                    made[(family_name[fam], args[k])].add(n)
            elif callee == "GameObjectTypeUse" and len(args) > 1 and args[0] in family_name and args[1] is not None:
                key = (family_name[args[0]], args[1])
                for owner in owners.get(n, []):
                    used_by[key].add(owner)
                    uses[owner].add(key)

    for f in families:
        for t in f["types"]:
            key = (f["name"], t["type"])
            if key in typed and not everything:
                continue
            own = [name_of.get(int(a, 16), "sub_%08X" % int(a, 16)) for a in [t["register"]] + list(t["slots"].values())]
            own = {n for n in own if len(owners[n]) == 1}
            for _ in range(3):      # and what only they call, three calls down
                own |= {c for n in own for c in calls_of.get(n, ()) if callers[c] <= own and c not in owners}
            strings, shown = [], []
            for n in sorted(own):
                body = by_name.get(n, ([], []))[1]
                for x in re.findall(r"\b(0x1[0-9A-F]{5})u\b", "\n".join(body)):
                    s = string_at(int(x, 16))
                    if s and s not in strings:
                        strings.append(s)
                for callee, args in calls_with_numbers(body):
                    if callee == "vcStringManagerGetText" and len(args) > 1 and args[1] in texts                             and texts[args[1]] not in shown:
                        shown.append(texts[args[1]])
            print("%s %d%s" % (f["name"], t["type"], " " + typed[key] if key in typed else ""))
            print("    register: %s" % name_of.get(int(t["register"], 16), t["register"]))
            if made.get(key):
                print("    made by: %s" % ", ".join(sorted(made[key])[:10]))
            if used_by.get(key):
                print("    used by: %s" % ", ".join(sorted(label(k) for k in used_by[key])[:10]))
            if uses.get(key):
                print("    uses: %s" % ", ".join(sorted(label(k) for k in uses[key])))
            # its fingerprint: the named functions it calls and the named data it reads, the rarest first
            called = {c for n in own for c in calls_of.get(n, ()) if c not in own and not c.startswith("sub_")}
            called = sorted((c for c in called if len(callers[c]) <= 12), key=lambda c: (len(callers[c]), c))
            read = collections.Counter(w for n in own for w in data_of.get(n, ()))
            read = sorted((w for w in read if readers[w] <= 12), key=lambda w: (readers[w], w))
            if called:
                print("    calls: %s" % ", ".join(called[:12]))
            if read:
                print("    reads: %s" % ", ".join(read[:10]))
            if strings:
                print("    its strings: %s" % ", ".join(strings[:8]))
            if shown:
                print("    its texts: %s" % "; ".join(shown[:10]))


if __name__ == "__main__":
    main()
