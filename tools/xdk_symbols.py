"""
Name:        xdk_symbols.py
Description: turns XbSymbolDatabase's scan of the XBE into symbols/xdk_symbols.json, and reports how its
             functions line up with the disassembly
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    XbSymbolDatabaseCLI analysis/default.xbe -e > analysis/xbsymbols.txt
    py -3 tools/xdk_symbols.py analysis/xbsymbols.txt

XbSymbolDatabase (github.com/Cxbx-Reloaded/XbSymbolDatabase, MIT) recognises
the XDK libraries the title links statically -- D3D8, DSOUND, XAPILIB -- by
signature. The JSON keeps every symbol with its library, kind (function or
variable), calling convention and parameters, and reports how the functions
line up with what tools.disasm found, per XBE section.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINE = re.compile(r"^(?P<lib>[A-Z0-9]+)__(?P<kind>FUN|VAR|UNK)__(?:(?P<cc>[a-z]+)__)?"
                  r"(?P<name>[A-Za-z0-9_]+)(?:\((?P<params>[^)]*)\))? = 0x(?P<addr>[0-9a-fA-F]+)$")


def parse(path):
    syms = []
    for line in open(path, encoding="latin1"):
        m = LINE.match(line.strip())
        if not m:
            continue
        params = [p.strip() for p in (m.group("params") or "").split(",") if p.strip()]
        syms.append({
            "address": "0x%08X" % int(m.group("addr"), 16),
            "library": m.group("lib"),
            "kind": {"FUN": "function", "VAR": "variable", "UNK": "unknown"}[m.group("kind")],
            "calling_convention": m.group("cc"),
            "name": m.group("name"),
            "params": params,
        })
    return syms


def section_of(addr, sections):
    for s in sections:
        if s["va"] <= addr < s["va"] + s["size"]:
            return s["name"]
    return "?"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "analysis", "xbsymbols.txt")
    syms = parse(src)
    funcs = json.load(open(os.path.join(REPO, "analysis", "disasm", "functions.json")))
    if isinstance(funcs, dict):
        funcs = funcs.get("functions", list(funcs.values()))
    starts = {int(f["start"] if "start" in f else f["address"], 16) for f in funcs}
    summary = json.load(open(os.path.join(REPO, "analysis", "disasm", "summary.json")))
    sections = [{"name": s["name"], "va": int(s["va"], 16), "size": s["size"]}
                for s in summary["sections_analyzed"]]

    per = {}
    for s in syms:
        a = int(s["address"], 16)
        s["section"] = section_of(a, sections)
        if s["kind"] == "function":
            s["disasm_entry"] = a in starts
            k = per.setdefault(s["section"], [0, 0])
            k[0] += 1
            k[1] += s["disasm_entry"]

    out = os.path.join(REPO, "symbols", "xdk_symbols.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="\n") as f:
        json.dump(sorted(syms, key=lambda s: s["address"]), f, indent=1)
        f.write("\n")

    by_sec = {}
    for fn in funcs:
        a = int(fn["start"] if "start" in fn else fn["address"], 16)
        by_sec[section_of(a, sections)] = by_sec.get(section_of(a, sections), 0) + 1
    print("%d symbols -> %s" % (len(syms), os.path.relpath(out, REPO)))
    print("%-10s %9s %9s %9s" % ("section", "disasm", "named", "matched"))
    for sec in sorted(set(by_sec) | set(per)):
        named, matched = per.get(sec, [0, 0])
        print("%-10s %9d %9d %9d" % (sec, by_sec.get(sec, 0), named, matched))
    missing = [s for s in syms if s["kind"] == "function" and not s["disasm_entry"]]
    if missing:
        print("named functions that are not a disasm entry:")
        for s in missing:
            print("  %s %-8s %s" % (s["address"], s["section"], s["name"]))


if __name__ == "__main__":
    main()
