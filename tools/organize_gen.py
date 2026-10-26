"""
Name:        organize_gen.py
Description: lays the recompiled C out in files by subject, each function with its description
Version:     0.3.0
Created:     25-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

    py -3 tools/organize_gen.py

xboxrecomp's recompiler cuts its output by count (--split N: recomp_0000.c,
recomp_0001.c...) and writes no descriptions; neither is in its options. It
does write " * Source: PATH" in a function's header when told the function's
file (tools/apply_files.py, from symbols.txt). This moves every function to
src/recomp/gen/PATH, in address order, under a header that names and
describes the file (the comment of the file's first line in symbols.txt),
and puts each function's description (its comment line in symbols.txt) into
its header. Run again, it starts from whatever is there, cut by count or
already laid out, so it never doubles a function.

Three names on the way, in the generated C, recomp_funcs.h and the dispatch
table: a function src/recomp_manual.c wraps or replaces, sub_X to the
recompiler, becomes NAME, as recomp_manual.c defines it; the body of a
wrapped one, sub_X_gen, becomes NAME_gen; and a call or a tail jump to a
function written by hand, which the recompiler looks up at run time, becomes a
direct call to its entry (explained at WRAPPER, WRAPPED, MANUAL_CALL and
MANUAL_TAIL below).
"""
import glob
import json
import os
import re
import sys
import textwrap
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(REPO, "src", "recomp", "gen")
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402

KEEP = {"recomp_dispatch.c", "recomp_stubs_unresolved.c"}
FUNCS_H = os.path.join(GEN, "recomp_funcs.h")
DISPATCH = os.path.join(GEN, "recomp_dispatch.c")
HAND = os.path.join(REPO, "analysis", "hand_functions.json")
# recomp_manual.c as the recompiler read it (tools/hand_functions.py)
MANUAL_FOR_TOOLKIT = os.path.join(REPO, "analysis", "recomp_manual.c")
# a function src/recomp_manual.c wraps or replaces, as the recompiler calls it
WRAPPER = re.compile(r"\bsub_([0-9A-F]{8})\b")
# the body of a function src/recomp_manual.c wraps, as the recompiler names it
WRAPPED = re.compile(r"\bsub_([0-9A-F]{8})_gen\b")
# A call to a function written by hand. The recompiler looks it up at run
# time, so that a replacement in recomp_lookup_manual wins over it; this
# project replaces functions by writing them, and recomp_lookup_manual
# replaces none (src/recomp_manual.c), so the lookup always finds the entry.
MANUAL_CALL = re.compile(r"\{ uint32_t _icall_esp = g_esp;\n"
                         r"((?:(?![ \t]*\{ uint32_t _icall_esp)(?![ \t]*\}[ \t]*\n)[^\n]*\n)*?)"
                         r"([ \t]*)PUSH32\(esp, (0x[0-9A-Fa-f]+u)\); "
                         r"RECOMP_ICALL_SAFE(?:_CC)?\(0x([0-9A-F]{8})u, _icall_esp\); "
                         r"/\* manual call 0x[0-9A-F]{8} \*/\n")
# A tail jump to a function written by hand, looked up at run time the same way.
MANUAL_TAIL = re.compile(r"RECOMP_ITAIL\(0x([0-9A-F]{8})u\); return; /\* manual tail jmp 0x[0-9A-F]{8} \*/")
# a function's header: its name, any description a run put there, its span
BLOCK = re.compile(r"(?m)^/\*\*\n \* (\w+)\n(?: \*.*\n)*? \* Original: 0x([0-9A-F]{8})")
WIDTH = 100


def function_files():
    out = []
    for path in glob.glob(os.path.join(GEN, "**", "*.c"), recursive=True):
        if os.path.dirname(path) == GEN and os.path.basename(path) in KEEP:
            continue
        out.append(path)
    return out


def blocks_of(text):
    """(address, name, block text) for each function in a generated file."""
    marks = list(BLOCK.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(m.group(2), 16), m.group(1), text[m.start():end].rstrip() + "\n"))
    return out


def describe(block, name, comments):
    """The block with its description under the name line (replacing any
    description an earlier run put there)."""
    head, sep, rest = block.partition("\n * Original: ")
    head = head.split("\n")[:2]                     # "/**" and " * NAME"
    text = comments.get(name) or comments.get(name[:-4] if name.endswith("_gen") else "")
    lines = head
    if text:
        lines += [" * " + l for l in textwrap.wrap(text, WIDTH - 3)] + [" *"]
    return "\n".join(lines) + sep + rest


def real_name(names, match):
    """sub_X_gen as NAME_gen when symbols.txt names the function at X."""
    name = names.get(int(match.group(1), 16))
    return name + "_gen" if name else match.group(0)


def file_header(path, note):
    today = time.strftime("%d-%m-%Y")
    return (
        "/**\n"
        " *    Name:        %s\n"
        " *    Description: %s\n"
        " *    Version:     0.1.0\n"
        " *    Created:     25-10-2026\n"
        " *    Modified:    %s\n"
        " *    Author:      Sebastian Toyos\n"
        " *\n"
        " *    Generated: xboxrecomp's recompiler wrote these functions and tools/organize_gen.py laid them\n"
        " *    out here, with the names, descriptions and files of symbols/symbols.txt. Not edited by hand.\n"
        " */\n\n"
        "#define RECOMP_GENERATED_CODE\n"
        "#include \"recomp_funcs.h\"\n"
        "#include <math.h>\n\n" % (path, note or "functions of the game", today))


def main():
    sym = symbols.load()
    notes = {}
    for _, path, note in sym["files"]:
        if note and path not in notes:
            notes[path] = note
    found = {}
    sources = function_files()
    # a fresh run of the recompiler (its files cut by count) is the truth; the
    # files laid out by an earlier run are read only when there is none
    fresh = [p for p in sources if re.match(r"recomp_\d{4}\.c$", os.path.basename(p))]
    # A function src/recomp_manual.c wraps keeps its generated body under
    # sub_X_gen, the recompiler's name for it whatever the function is
    # called; it gets the real name here, NAME_gen, and recomp_manual.c calls
    # it so. The wrapper (or the replacement) is sub_X to the recompiler, which
    # finds it so (--exclude-manual) and calls it so; recomp_manual.c defines
    # it as NAME, and every call and declaration gets that name here.
    wrappers = {}
    if os.path.exists(MANUAL_FOR_TOOLKIT):
        for a in re.findall(r"(?m)^void sub_([0-9A-F]{8})\(void\)$", open(MANUAL_FOR_TOOLKIT, encoding="utf-8").read()):
            if int(a, 16) in sym["func"]:
                wrappers[a] = sym["func"][int(a, 16)]

    def rename(match):
        return real_name(sym["func"], match)

    def wrapper_name(match):
        return wrappers.get(match.group(1), match.group(0))

    def names(text):
        return WRAPPER.sub(wrapper_name, WRAPPED.sub(rename, text))

    # each call to a function written by hand, straight to its entry
    entries = {int(a, 16): n for a, n in json.load(open(HAND)).items()} if os.path.exists(HAND) else {}

    def direct(match):
        entry = entries.get(int(match.group(4), 16))
        if not entry:
            return match.group(0)
        return ("{\n%s%sPUSH32(esp, %s); RECOMP_ABI_CALL(0x%su, %s); /* call 0x%s, written by hand */\n"
                % (match.group(1), match.group(2), match.group(3), match.group(4), entry, match.group(4)))

    def direct_tail(match):
        entry = entries.get(int(match.group(1), 16))
        if not entry:
            return match.group(0)
        return "RECOMP_ABI_CALL(0x%su, %s); return; /* tail jmp 0x%s, written by hand */" % (
            match.group(1), entry, match.group(1))

    for path in fresh or sources:
        text = MANUAL_TAIL.sub(direct_tail, MANUAL_CALL.sub(direct, names(open(path, encoding="utf-8").read())))
        for addr, name, block in blocks_of(text):
            m = re.search(r"(?m)^ \* Source: (\S+)$", block)
            dest = m.group(1) if m else "game/unsorted.c"
            found[addr] = (dest, describe(block, name, sym["comments"]))
    for path in (FUNCS_H, DISPATCH):
        text = open(path, encoding="utf-8").read()
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(names(text))
    if not found:
        sys.exit("no generated functions under %s" % os.path.relpath(GEN, REPO))
    for path in sources:
        os.remove(path)
    by_file = {}
    for addr, (dest, block) in sorted(found.items()):
        by_file.setdefault(dest, []).append(block)
    for dest, blocks in sorted(by_file.items()):
        out = os.path.join(GEN, dest)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(file_header(dest, notes.get(dest[:-2])))
            f.write("\n".join(blocks))
    for d in sorted(glob.glob(os.path.join(GEN, "**"), recursive=True), reverse=True):
        if os.path.isdir(d) and d != GEN and not os.listdir(d):
            os.rmdir(d)
    described = sum(1 for _, b in found.values() if "\n *\n * Original:" in b)
    print("laid out %d functions in %d files; %d with a description" % (len(found), len(by_file), described))


if __name__ == "__main__":
    main()
