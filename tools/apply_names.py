"""
Name:        apply_names.py
Description: writes real function names into the disassembly (analysis/disasm/functions.json) before
             recompiling
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    py -3 tools/apply_names.py [--toolkit ../xboxrecomp]

Sources, later ones winning:
  symbols/lib_matches.json  XDK library functions matched byte for byte against
                            the XDK's .lib files (tools/match_libs.py)
  symbols/classes.json      the engine's class callbacks, from the descriptors the
                            game registers (tools/find_classes.py)
  symbols/xdk_symbols.json  XDK library functions found by XbSymbolDatabase
                            (tools/xdk_symbols.py)
  symbols/names.json        names given by hand, {"0x00157AC0": "name", ...}

The recompiler emits whatever `name` an entry carries, as the C function name,
in call sites and in the dispatch table. tools.disasm rewrites functions.json
from scratch, so this runs after it every time (pipeline.py does).

A name the toolkit's runtime also defines (XAPI reimplements Win32 calls such
as CreateThread, which src/platform defines too) would be a second definition
at link time, and the recompiler gives an address suffix to the names it
reserves (C keywords, the C runtime, every Win32 export the host links: its
lifter's _FUNC_RESERVED_IDENT, read from the toolkit here). Both kinds take
their library's prefix instead (xapi_CreateThread, xapi_GetTimeZoneInformation),
so the name stays a name.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCS = os.path.join(REPO, "analysis", "disasm", "functions.json")
LIB = os.path.join(REPO, "symbols", "lib_matches.json")
CLASSES = os.path.join(REPO, "symbols", "classes.json")
XDK = os.path.join(REPO, "symbols", "xdk_symbols.json")
MANUAL = os.path.join(REPO, "symbols", "names.json")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A name the toolkit defines too takes its library's prefix, as match_libs.py
# gives every name of those libraries.
LIB_PREFIX = {"XAPILIB": "xapi_", "D3D8": "d3d_", "DSOUND": "dsound_", "LIBCMT": "crt_"}


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
    if os.path.exists(LIB):
        for s in json.load(open(LIB)):
            if s["kind"] == "function":
                a = int(s["address"], 16)
                wanted[a] = s["name"]
                source[a] = "lib"
    if os.path.exists(CLASSES):
        for s in json.load(open(CLASSES))["names"]:
            a = int(s["address"], 16)
            wanted[a] = s["name"]
            source[a] = "classes"
    library = {}
    for s in json.load(open(XDK)):
        if s["kind"] == "function":
            a = int(s["address"], 16)
            wanted[a] = s["name"]
            source[a] = "xdk"
            library[a] = s["library"]
    if os.path.exists(MANUAL):
        for k, v in json.load(open(MANUAL)).items():
            a = int(k, 16)
            wanted[a] = v
            source[a] = "manual"
    bad = [n for n in wanted.values() if not IDENT.match(n)]
    if bad:
        raise SystemExit("not C identifiers: %s" % ", ".join(sorted(set(bad))))

    sys.path.insert(0, args.toolkit)
    from tools.recomp.lifter import _FUNC_RESERVED_IDENT
    clash = toolkit_defined(args.toolkit, set(wanted.values())) | (set(wanted.values()) & _FUNC_RESERVED_IDENT)
    seen = {}
    for a in sorted(wanted):
        seen.setdefault(wanted[a], []).append(a)

    funcs = json.load(open(FUNCS))
    by_start = {int(f["start"], 16): f for f in funcs}
    # every run starts from the disassembler's names, so a name no source
    # gives any more does not stay behind from the last run
    for f in funcs:
        if f.get("detection_method") != "entry_point":
            f["name"] = "sub_%08X" % int(f["start"], 16)
    applied, missing = {"lib": 0, "classes": 0, "xdk": 0, "manual": 0}, []
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
        if len(seen[name]) > 1:
            missing.append((a, name + " (the same name at another address)"))
            continue
        if name in clash:
            name = LIB_PREFIX.get(library.get(a), "xdk_") + name
        f["name"] = name
        applied[source[a]] += 1

    with open(FUNCS, "w", newline="\n") as fh:
        json.dump(funcs, fh, indent=2)
    print("named %d functions (%d lib, %d classes, %d xdk, %d manual); %d given their library's prefix for"
          " clashing with the toolkit: %s"
          % (sum(applied.values()), applied["lib"], applied["classes"], applied["xdk"],
             applied["manual"], len(clash),
             ", ".join(sorted(clash))))
    for a, name in missing:
        print("  not a disasm entry, skipped: 0x%08X %s" % (a, name))


if __name__ == "__main__":
    main()
