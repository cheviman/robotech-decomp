"""Checks a review answer: py -3 tools/naming/check_review.py REVIEW DRAFT

One line per named line of DRAFT: `ADDRESS OK`, `ADDRESS BETTER Name why` or `ADDRESS WRONG why`."""
import re, sys

rev, draft = sys.argv[1], sys.argv[2]
want = []
for t in open(draft, encoding="utf-8").read().split("\n"):
    m = re.match(r"^\s*`?(?:0x)?([0-9A-Fa-f]{8})\s+(\S+)", t)
    if m and m.group(2) != "skip":
        want.append(m.group(1).upper())
NAME = re.compile(r"^[A-Z][A-Za-z0-9]*(_[A-Z][A-Za-z0-9]*)?$")
errs, seen = [], set()
for n, t in enumerate(open(rev, encoding="utf-8").read().strip().split("\n"), 1):
    t = t.strip().strip("`")
    if not t:
        continue
    m = re.match(r"^(?:0x)?([0-9A-Fa-f]{8})\s+(OK|BETTER|WRONG)\b\s*(\S*)\s*(.*)$", t)
    if not m:
        errs.append("line %d is not `ADDRESS OK`, `ADDRESS BETTER Name why` or `ADDRESS WRONG why`: %s" % (n, t[:100]))
        continue
    a = m.group(1).upper()
    if a not in want:
        errs.append("line %d: %s is not a named line of the draft" % (n, a))
    elif a in seen:
        errs.append("line %d: %s reviewed twice" % (n, a))
    seen.add(a)
    if m.group(2) == "BETTER" and not NAME.match(m.group(3)):
        errs.append("line %d: BETTER needs a CamelCase name, got %s" % (n, m.group(3)))
miss = [a for a in want if a not in seen]
if miss:
    errs.append("no line for: " + ", ".join(miss))
for e in errs:
    print(e)
sys.exit(1 if errs else 0)
