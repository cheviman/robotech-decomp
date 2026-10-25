"""Write real names into analysis/disasm/functions.json before recompiling.

    py -3 tools/apply_names.py [--toolkit ../xboxrecomp]

Sources, later ones winning:
  symbols/xdk_symbols.json  XDK library functions found by XbSymbolDatabase
                            (tools/xdk_symbols.py)
  symbols/names.json        names given by hand, {"0x00157AC0": "name", ...}

The recompiler emits whatever `name` an entry carries, as the C function name,
in call sites and in the dispatch table. tools.disasm rewrites functions.json
from scratch, so this runs after it every time (pipeline.py does).

A name the toolkit's runtime also defines (XAPI reimplements Win32 calls such
as CreateThread, which src/platform defines too) would be a second definition
at link time, so those get the address appended, as the lifter does for its
own reserved names.
"""
import argparse
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCS = os.path.join(REPO, "analysis", "disasm", "functions.json")
XDK = os.path.join(REPO, "symbols", "xdk_symbols.json")
MANUAL = os.path.join(REPO, "symbols", "names.json")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def toolkit_defined(toolkit, names):
    """Names among `names` that the toolkit's C sources declare as functions."""
    found = set()
    pats = {n: re.compile(r"^[A-Za-z_][\w \*]*\b" + re.escape(n) + r"\s*\(", re.M) for n in names}
    for path in glob.glob(os.path.join(toolkit, "src", "**", "*.[ch]"), recursive=True):
        text = open(path, encoding="latin1").read()
        for n, p in pats.items():
            if n not in found and n in text and p.search(text):
                found.add(n)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--toolkit", default=os.path.join(os.path.dirname(REPO), "xboxrecomp"))
    args = ap.parse_args()

    wanted = {}
    source = {}
    for s in json.load(open(XDK)):
        if s["kind"] == "function":
            a = int(s["address"], 16)
            wanted[a] = s["name"]
            source[a] = "xdk"
    if os.path.exists(MANUAL):
        for k, v in json.load(open(MANUAL)).items():
            a = int(k, 16)
            wanted[a] = v
            source[a] = "manual"
    bad = [n for n in wanted.values() if not IDENT.match(n)]
    if bad:
        raise SystemExit("not C identifiers: %s" % ", ".join(sorted(set(bad))))

    clash = toolkit_defined(args.toolkit, set(wanted.values()))
    seen = {}
    for a in sorted(wanted):
        seen.setdefault(wanted[a], []).append(a)

    funcs = json.load(open(FUNCS))
    by_start = {int(f["start"], 16): f for f in funcs}
    applied, missing = {"xdk": 0, "manual": 0}, []
    for a, name in sorted(wanted.items()):
        f = by_start.get(a)
        if not f:
            missing.append((a, name))
            continue
        if f.get("detection_method") == "entry_point":
            # main.c calls the entry by this name (the template's contract);
            # XbSymbolDatabase knows it as mainCRTStartup. Set rather than
            # skipped: a cached disasm keeps the names of the last run.
            f["name"] = "xbe_entry_point"
            continue
        if name in clash or len(seen[name]) > 1:
            name = "%s_%08X" % (name, a)
        f["name"] = name
        applied[source[a]] += 1

    with open(FUNCS, "w", newline="\n") as fh:
        json.dump(funcs, fh, indent=2)
    print("named %d functions (%d xdk, %d manual); %d renamed for clashing with the toolkit: %s"
          % (sum(applied.values()), applied["xdk"], applied["manual"], len(clash), ", ".join(sorted(clash))))
    for a, name in missing:
        print("  not a disasm entry, skipped: 0x%08X %s" % (a, name))


if __name__ == "__main__":
    main()
