"""
Name:        organize_gen.py
Description: lays the recompiled C out in files by subject, each function with its description
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
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
"""
import glob
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
    for path in fresh or sources:
        for addr, name, block in blocks_of(open(path, encoding="utf-8").read()):
            m = re.search(r"(?m)^ \* Source: (\S+)$", block)
            dest = m.group(1) if m else "game/unsorted.c"
            found[addr] = (dest, describe(block, name, sym["comments"]))
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
