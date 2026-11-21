"""Checks a naming answer: py -3 tools/naming/check_names.py ANSWER TASK.c

Every function of TASK.c gets exactly one line, `ADDRESS  Name  what it does` or `ADDRESS  skip  why`.
Prints `score: N` (the functions named). Exit 0 when the form is right.
"""
import os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ans, task = sys.argv[1], sys.argv[2]
want = re.findall(r"^/\* ======== sub_([0-9A-F]{8}) ", open(task, encoding="utf-8").read(), re.M)
taken = set()
for t in open(os.path.join(REPO, "symbols", "symbols.txt"), encoding="utf-8"):
    p = t.split()
    if len(p) >= 3 and re.match(r"^[0-9A-F]{8}$", p[0]):
        taken.add(p[2])
    elif len(p) >= 3 and p[0] in ("struct", "comment"):
        taken.add(p[1])
BAD = re.compile(r"(?i)sub_|^func|unknown|helper|^do[A-Z_]|^handle$|stub|wrapper|thunk|placeholder|[0-9]{3}|0x|^fun_|^f[0-9]")
NAME = re.compile(r"^[A-Z][A-Za-z0-9]*(_[A-Z][A-Za-z0-9]*)?$")
errs, seen, names, named = [], {}, set(), 0
text = open(ans, encoding="utf-8").read().strip()
for n, t in enumerate(text.split("\n"), 1):
    t = t.strip().strip("`")
    if not t:
        continue
    m = re.match(r"^(?:0x)?([0-9A-Fa-f]{8})\s+(\S+)\s+(.+)$", t)
    if not m:
        errs.append("line %d is not `ADDRESS  Name  description` nor `ADDRESS  skip  reason`: %s" % (n, t[:100]))
        continue
    a, nm, d = m.group(1).upper(), m.group(2), m.group(3)
    if a not in want:
        errs.append("line %d: %s is not one of the task's functions" % (n, a))
        continue
    if a in seen:
        errs.append("line %d: %s answered twice" % (n, a))
        continue
    seen[a] = nm
    if nm == "skip":
        continue
    if not NAME.match(nm):
        errs.append("line %d: %s is not a CamelCase C name (letters and digits, at most one _ between a prefix and the rest)" % (n, nm))
    elif BAD.search(nm):
        errs.append("line %d: %s is a placeholder or a generic word, not a name that says what it does; skip it instead" % (n, nm))
    elif nm in taken:
        errs.append("line %d: %s is already the name of another symbol of the game; pick another or skip" % (n, nm))
    elif nm in names:
        errs.append("line %d: %s given twice" % (n, nm))
    elif len(d.split()) < 5:
        errs.append("line %d: the description of %s is under 5 words" % (n, nm))
    else:
        names.add(nm)
        named += 1
missing = [a for a in want if a not in seen]
if missing:
    errs.append("no line for: " + ", ".join(missing))
for e in errs:
    print(e)
print("score: %d" % named)
sys.exit(1 if errs else 0)
