"""Splits the unnamed functions of src/decompiled/decompiled.c into naming tasks for the worker.

    py -3 tools/naming/make_name_tasks.py WAVE [MAXLINES]

Writes build/cr/names/WAVE/tNNN.c (the functions, each with the lines that call it) and
build/cr/names/WAVE/tasks.jsonl. Functions already named in symbols.txt are left out.
"""
import json, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src", "decompiled", "decompiled.c")
wave = sys.argv[1]
MAXLINES = int(sys.argv[2]) if len(sys.argv) > 2 else 450
OUT = os.path.join(REPO, "build", "cr", "names", wave)
os.makedirs(OUT, exist_ok=True)

lines = open(SRC, encoding="utf-8").read().split("\n")
sig = re.compile(r"^[A-Za-z_][\w \*]*?\b(\w+)\((.*)\)$")
funcs = []  # (name, start, end) end inclusive
i = 0
while i < len(lines):
    m = sig.match(lines[i])
    if m and i + 1 < len(lines) and lines[i + 1] == "{":
        j = i + 2
        while lines[j] != "}":
            j += 1
        funcs.append((m.group(1), i, j))
        i = j + 1
    else:
        i += 1

unnamed = re.compile(r"^sub_([0-9A-F]{8})$")
owner = {}
for n, s, e in funcs:
    for k in range(s, e + 1):
        owner[k] = n
calls = {}
callre = re.compile(r"\b(sub_[0-9A-F]{8})\(")
for k, t in enumerate(lines):
    if k in owner:
        for c in set(callre.findall(t)):
            if c != owner[k] and not owner[k].endswith("_entry"):
                calls.setdefault(c, []).append(k)

todo = [(n, s, e) for n, s, e in funcs if unnamed.match(n)]
todo.sort(key=lambda f: int(f[0][4:], 16))

def render(n, s, e):
    out = ["/* ======== %s (address 0x%s) ======== */" % (n, n[4:])]
    sites = calls.get(n, [])
    callers = sorted({owner[k] for k in sites})
    out.append("/* called by %d site(s) in: %s */" % (len(sites), ", ".join(callers[:12]) or "nobody in the decompiled C (called through a pointer or from recompiled code)"))
    for k in sites[:3]:
        out.append("/* in %s: */" % owner[k])
        for t in lines[max(k - 3, 0):k + 2]:
            out.append("/*   " + t.replace("*/", "* /").strip() + " */")
    body = lines[s:e + 1]
    if len(body) > 1500:
        body = body[:1500] + ["\t/* ... %d more lines cut ... */" % (len(body) - 1500), "}"]
    return out + body + [""]

tasks, cur, curlen = [], [], 0
for f in todo:
    blk = render(*f)
    if cur and curlen + len(blk) > MAXLINES:
        tasks.append(cur)
        cur, curlen = [], 0
    cur.append((f[0], blk))
    curlen += len(blk)
if cur:
    tasks.append(cur)

with open(os.path.join(OUT, "tasks.jsonl"), "w", newline="\n") as fh:
    for t, group in enumerate(tasks):
        src = os.path.join(OUT, "t%03d.c" % t)
        with open(src, "w", newline="\n", encoding="utf-8") as g:
            for _, blk in group:
                g.write("\n".join(blk) + "\n")
        rel = os.path.relpath(src, REPO).replace("\\", "/")
        out = rel[:-2] + ".txt"
        fh.write(json.dumps({"id": "%s-t%03d" % (wave, t), "files": [rel], "out": out,
                             "check": "py -3 tools/naming/check_names.py {out} " + rel,
                             "max_tokens": 200 * len(group) + 1500}) + "\n")
print("%d unnamed functions, %d tasks in %s" % (len(todo), len(tasks), OUT))
