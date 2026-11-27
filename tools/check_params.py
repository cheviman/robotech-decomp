"""Checks a proposal of `param` lines against symbols/symbols.txt and the decompiled C.

    py -3.14 tools/check_params.py PROPOSAL [TODO.json]

A proposal of parameter names is lines `param  FUNCTION  REG  name  [# why]` (symbols.txt's own syntax:
REG a register, eax to edi, or an argument on the stack, arg0 up) and comment lines. This reads it against
the functions' signatures in src/decompiled/decompiled.c (written with the names the last build had:
build/symbols.before_types.txt, when it is there, takes them to today's by their address) and tells:

- a line that is no `param` line, or whose REG is none;
- a FUNCTION symbols.txt does not name, or one the decompiled C does not write;
- a REG the function's signature does not have (its outputs, p_eax..., are not parameters to name);
- a (FUNCTION, REG) named twice in the proposal, or that symbols.txt names already;
- a name that is not snake_case (a lower-case letter, then lower-case letters, digits and _), a C keyword
  or a type, a register's or an argument's own name (eax, arg1, eax_2), the same name for two parameters
  of a function, or a name the function's C already uses for something else (a local, a call, a variable):
  the C would not compile, or would read as another thing.

With TODO.json ({function: [registers]}, what a lane was given) it also says how many of those are named.
Hands back 1 if it tells anything. Writes nothing.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols as S

DECOMPILED = os.path.join(REPO, "src", "decompiled", "decompiled.c")
BEFORE = os.path.join(REPO, "build", "symbols.before_types.txt")
HEADER = re.compile(r"^(?!static\b)[A-Za-z_][\w \*]*?\b(\w+)\(([^)]*)\)\s*$", re.M)
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
OWN = re.compile(r"^(e[abcd]x|e[sd]i|ebp|esp|arg\d+|p_\w+|f\d+|t\d+|stack_\w+|saved_\w+)(_\d+)?$")
RESERVED = set("""auto break case char const continue default do double else enum extern float for goto if
inline int long register restrict return short signed sizeof static struct switch typedef union unsigned
void volatile while bool true false uint8_t int8_t uint16_t int16_t uint32_t int32_t uint64_t int64_t
size_t null ignored zero negative overflow carry g_esp g_eax g_ecx g_edx g_ebx g_ebp g_esi g_edi""".split())


def signatures():
    """{today's name: (set of the registers its signature takes, set of the identifiers its C uses)}."""
    sym = S.load()
    today = sym["func"]
    was = S.load(BEFORE)["func"] if os.path.exists(BEFORE) else today
    address = {name: a for a, name in was.items()}
    src = open(DECOMPILED, encoding="utf-8", errors="replace").read()
    found = list(HEADER.finditer(src))
    out = {}
    for i, m in enumerate(found):
        a = address.get(m.group(1))
        if a is None or a not in today:
            continue
        body = src[m.end(): found[i + 1].start() if i + 1 < len(found) else len(src)]
        # without the comments: the next function's description comes right before its header, and a word
        # of a comment is no name of the C
        body = re.sub(r"/\*.*?\*/|//[^\n]*", " ", body, flags=re.S)
        params = {p.strip().split()[-1].lstrip("*") for p in m.group(2).split(",") if p.strip() and p.strip() != "void"}
        out[today[a]] = ({p for p in params if not p.startswith("p_")}, set(re.findall(r"[A-Za-z_]\w*", body)) | params)
    return sym, out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sym, known = signatures()
    functions = set(sym["func"].values())
    told, seen, by_function = 0, {}, {}

    def tell(n, text):
        nonlocal told
        told += 1
        if told <= 80:
            print("line %d: %s" % (n, text))

    for n, l in enumerate(open(sys.argv[1], encoding="utf-8").read().split("\n"), 1):
        f = l.partition("#")[0].split()
        if not f:
            continue
        if f[0] != "param" or len(f) != 4:
            tell(n, "not a `param FUNCTION REG name` line: %s" % l[:70])
            continue
        _, function, reg, name = f
        if not S.REGISTER_RE.match(reg):
            tell(n, "%s is no register and no argument" % reg)
            continue
        if function not in functions:
            tell(n, "%s is no function of symbols.txt" % function)
            continue
        if function not in known:
            tell(n, "the decompiled C does not write %s" % function)
            continue
        regs, used = known[function]
        if reg not in regs:
            tell(n, "%s does not take %s (it takes %s)" % (function, reg, ", ".join(sorted(regs)) or "nothing"))
            continue
        if (function, reg) in seen:
            tell(n, "%s %s is named on line %d already" % (function, reg, seen[(function, reg)]))
            continue
        if (function, reg) in sym["params"]:
            tell(n, "%s %s is %s in symbols.txt already" % (function, reg, sym["params"][(function, reg)]))
            continue
        seen[(function, reg)] = n
        if not NAME.match(name):
            tell(n, "%s is not snake_case" % name)
        elif name in RESERVED or OWN.match(name):
            tell(n, "%s is a keyword, a type or a register's own name" % name)
        elif name in by_function.setdefault(function, {}):
            tell(n, "%s names two parameters of %s (line %d)" % (name, function, by_function[function][name]))
        elif name in used:
            tell(n, "%s's C already has a %s" % (function, name))
        else:
            by_function[function][name] = n
    print("%s: %d param lines for %d functions; %d told" % (
        os.path.relpath(sys.argv[1], REPO), len(seen), len({f for f, _ in seen}), told))
    if len(sys.argv) > 2:
        todo = json.load(open(sys.argv[2]))
        wanted = {(f, r) for f, regs in todo.items() for r in regs}
        print("of the %d parameters of the todo's %d functions, %d named" % (len(wanted), len(todo), len(wanted & set(seen))))
    sys.exit(1 if told else 0)


if __name__ == "__main__":
    main()
