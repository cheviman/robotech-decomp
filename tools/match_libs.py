"""
Name:        match_libs.py
Description: names the XDK library code in the XBE by matching it against the XDK's own .lib files
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

The game links the XDK's static libraries (D3D8, DSOUND, XAPILIB, LIBCMT); their
code sits in the XBE byte for byte, except where the linker wrote an address.
Each function of each .lib becomes a pattern: its bytes, with the bytes its
relocations cover left as wildcards. A pattern found at exactly one place in
the XBE names that place. Then each match's relocations name what they point
at: the variables the function reads and the functions it calls, matched by
bytes or not.

The XDK here is 5849 and the game was built with 4721: what changed between
the two does not match, and is left for the other sources (XbSymbolDatabase,
names given by hand).

xboxrecomp's way to these names is tools/ghidra_naming (Ghidra's Function ID
databases), which needs Ghidra and recognises the C runtime and XDK helpers
by signature; this reads the XDK's own .lib files, byte for byte, and also
names the libraries' variables and the functions they call.

    py -3 tools/match_libs.py                     # writes symbols/lib_matches.json
    py -3 tools/match_libs.py --libs D:/xdk/extracted/lib

Output, one entry per address: {"address", "name" (a C identifier, safe to
emit as a function name), "symbol" (the decorated name in the .lib), "library",
"kind" (function | variable), "how" (bytes | reloc), "size" (bytes only)}.
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

import capstone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XBE = os.path.join(REPO, "analysis", "default.xbe")
ANALYSIS_JSON = os.path.join(REPO, "analysis", "default_analysis.json")
OUT = os.path.join(REPO, "symbols", "lib_matches.json")

# The libraries the XBE header lists, by their .lib file. D3DX8 and XGraphics,
# which a game can link without a version in the header, were tried on
# 25-10-2026: not one function of either matches by bytes, nor reads 85 % alike
# anywhere in .text; the engine has its own maths.
LIBS = {
    "d3d8.lib": "D3D8",
    "dsound.lib": "DSOUND",
    "xapilib.lib": "XAPILIB",
    "libcmt.lib": "LIBCMT",
    "libcpmt.lib": "LIBCPMT",
    "xboxkrnl.lib": "XBOXKRNL",     # import stubs only: names, no code
}

# The generated C defines a function by each name, and the host links its own
# C runtime and Win32: vsnprintf, RemoveEntryList or CreateFileA from the Xbox
# would be second definitions. So every name carries its library: the C
# runtime's and XAPI's always get a prefix, D3D8's and DSOUND's when they do
# not already start with their library's own mark (D3DDevice_*, DirectSound_*).
# A kernel export gets krnl_, and a name no parsed library defines xdk_.
PREFIX = {
    "D3D8": ("d3d_", ("D3D", "Direct3D")),
    "DSOUND": ("dsound_", ("DirectSound", "IDirectSound", "DSound", "XAudio", "AC3")),
    "XAPILIB": ("xapi_", ()),
    "LIBCMT": ("crt_", ()),
    "LIBCPMT": ("crt_", ()),
    "XBOXKRNL": ("krnl_", ()),
}

ANCHOR = 8              # bytes of the window a pattern is looked up by
MIN_FIXED = 12          # a pattern needs at least this many non-wildcard bytes
MIN_SIZE = 16           # and this many bytes in all

REL_I386_DIR32 = 0x06
REL_I386_DIR32NB = 0x07
REL_I386_SECTION = 0x0A
REL_I386_SECREL = 0x0B
REL_I386_REL32 = 0x14
REL_WIDTH = {REL_I386_DIR32: 4, REL_I386_DIR32NB: 4, REL_I386_SECTION: 2,
             REL_I386_SECREL: 4, REL_I386_REL32: 4}
SCN_CNT_CODE = 0x00000020


# ── .lib (ar archive) and COFF objects ──────────────────────

def ar_members(data):
    """(name, bytes) for each object member of an ar archive."""
    if data[:8] != b"!<arch>\n":
        raise ValueError("not an ar archive")
    pos, longnames = 8, b""
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[:16].decode("latin-1").strip()
        size = int(hdr[48:58].decode("latin-1").strip())
        body = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
        if name == "/" :
            continue
        if name == "//":
            longnames = body
            continue
        if name.startswith("/") and name[1:].isdigit():
            off = int(name[1:])
            name = longnames[off:longnames.index(b"\0", off) if b"\0" in longnames[off:] else None]
            name = name.decode("latin-1").rstrip("/\n")
        yield name.rstrip("/"), body


def coff_object(blob):
    """Sections, symbols and relocations of an i386 COFF object, or None for
    anything else (import stubs, other machines)."""
    if len(blob) < 20:
        return None
    machine, nsec, _, symptr, nsym, optsize, _ = struct.unpack_from("<HHIIIHH", blob, 0)
    if machine != 0x14C or symptr == 0 or symptr + 18 * nsym > len(blob):
        return None
    strtab = symptr + 18 * nsym

    def sname(raw):
        if raw[:4] == b"\0\0\0\0":
            off = struct.unpack_from("<I", raw, 4)[0]
            end = blob.index(b"\0", strtab + off)
            return blob[strtab + off:end].decode("latin-1")
        return raw.rstrip(b"\0").decode("latin-1")

    sections = []
    base = 20 + optsize
    for i in range(nsec):
        raw = blob[base + 40 * i:base + 40 * i + 40]
        name = sname(raw[:8]) if raw[0:1] != b"/" else raw[:8].rstrip(b"\0").decode("latin-1")
        (_, _, size, dataptr, relptr, _, nrel, _, chars) = struct.unpack_from("<IIIIIIHHI", raw, 8)
        data = blob[dataptr:dataptr + size] if dataptr else b"\0" * size
        relocs = [struct.unpack_from("<IIH", blob, relptr + 10 * k) for k in range(nrel)]
        sections.append({"name": name, "data": data, "relocs": relocs, "chars": chars})

    symbols = {}
    i = 0
    while i < nsym:
        raw = blob[symptr + 18 * i:symptr + 18 * i + 18]
        value, secnum, typ, cls, naux = struct.unpack_from("<IhHBB", raw, 8)
        symbols[i] = {"name": sname(raw[:8]), "value": value, "section": secnum,
                      "type": typ, "class": cls}
        i += 1 + naux
    return {"sections": sections, "symbols": symbols}


# ── Names ───────────────────────────────────────────────────

SPECIAL = {"0": "ctor", "1": "dtor", "2": "operator_new", "3": "operator_delete",
           "4": "op_assign", "_G": "scalar_deleting_dtor", "_E": "vector_deleting_dtor",
           "_U": "operator_new_array", "_V": "operator_delete_array", "_7": "vftable"}


def c_name(sym):
    """A C identifier for a decorated symbol: _foo, _Foo@12 and @Foo@8 lose
    their decoration; ?Name@Scope@@... becomes Scope_Name."""
    if sym.startswith("?"):
        body = sym[1:]
        special = None
        if body.startswith("?"):
            key = body[1:3] if body[1] == "_" else body[1]
            special = SPECIAL.get(key, "op" + re.sub(r"\W", "_", key))
            body = body[1 + len(key):]
        parts, seen = [], []
        while body and not body.startswith("@"):
            if body[0].isdigit():
                idx = int(body[0])
                parts.append(seen[idx] if idx < len(seen) else "x")
                body = body[1:]
                continue
            if body.startswith("?$"):
                end = body.find("@", 2)
                piece = body[2:end] if end > 0 else body[2:]
                parts.append(piece)
                depth_end = body.find("@@", end) if end > 0 else -1
                body = body[depth_end + 1:] if depth_end > 0 else ""
                continue
            end = body.find("@")
            if end < 0:
                break
            piece = body[:end]
            parts.append(piece)
            seen.append(piece)
            body = body[end + 1:]
        if special:
            # ??0CDevice@D3D@@ is D3D_CDevice_ctor
            parts.insert(0, special)
        name = "_".join(reversed([p for p in parts if p]))
    elif sym.startswith("@"):
        name = sym[1:].split("@")[0]
    elif sym.startswith("_"):
        name = sym[1:].split("@")[0]
    else:
        name = sym.split("@")[0]
    name = re.sub(r"\W", "_", name).strip("_")
    if not name or name[0].isdigit():
        name = "x_" + name
    return name[:96]


def emit_name(sym, defs):
    """The C name of a symbol, with its library's prefix (PREFIX)."""
    name = c_name(sym)
    library = defs.get(sym)
    if library is None:
        return "xdk_" + name
    prefix, marks = PREFIX[library]
    if marks and name.startswith(marks):
        return name
    if name.startswith("x_") and name[2:3].isdigit():
        name = name[2:]                 # the prefix makes it an identifier already
    return prefix + name


# ── Patterns ────────────────────────────────────────────────

def lib_functions(path, library, defs):
    """Each code symbol of each object as {name, symbol, bytes, mask, relocs};
    every symbol an object defines goes into defs, {symbol: library}."""
    data = open(path, "rb").read()
    for member, blob in ar_members(data):
        if blob[:4] == b"\0\0\xff\xff":
            # a short import object: the symbol name follows its 20-byte header
            defs.setdefault(blob[20:blob.index(b"\0", 20)].decode("latin-1"), library)
            continue
        obj = coff_object(blob)
        if not obj:
            continue
        secs, syms = obj["sections"], obj["symbols"]
        for s in syms.values():
            # externals and statics alike, not section or literal symbols; and
            # the uninitialised globals, external with no section but a size
            defined = s["section"] > 0 and s["class"] in (2, 3)
            common = s["section"] == 0 and s["class"] == 2 and s["value"] > 0
            if (defined or common) and not s["name"].startswith((".", "$")):
                defs.setdefault(s["name"], library)
        bysec = collections.defaultdict(list)
        for s in syms.values():
            if s["section"] > 0 and s["class"] in (2, 3) and s["type"] == 0x20:
                bysec[s["section"]].append(s)
        for secnum, funcs in bysec.items():
            sec = secs[secnum - 1]
            if not sec["chars"] & SCN_CNT_CODE:
                continue
            funcs.sort(key=lambda s: s["value"])
            for k, fn in enumerate(funcs):
                start = fn["value"]
                end = funcs[k + 1]["value"] if k + 1 < len(funcs) else len(sec["data"])
                code = sec["data"][start:end]
                mask = bytearray(b"\1" * len(code))
                relocs = []
                for va, symidx, rtype in sec["relocs"]:
                    if not start <= va < end:
                        continue
                    w = REL_WIDTH.get(rtype, 4)
                    for b in range(va - start, min(va - start + w, len(code))):
                        mask[b] = 0
                    target = syms.get(symidx)
                    if target is not None:
                        addend = struct.unpack_from("<i", code, va - start)[0] if va - start + 4 <= len(code) else 0
                        relocs.append((va - start, rtype, target, addend))
                yield {"member": member, "library": library, "symbol": fn["name"],
                       "bytes": code, "mask": bytes(mask), "relocs": relocs, "obj": obj,
                       "secnum": secnum, "start": start}


def fixed_runs(code, mask):
    """The (offset, bytes) runs a pattern has to equal."""
    runs, i = [], 0
    while i < len(code):
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < len(code) and mask[j]:
            j += 1
        runs.append((i, code[i:j]))
        i = j
    return runs


def load_known():
    """XbSymbolDatabase's names ({va: name}), which know the 4721 build."""
    path = os.path.join(REPO, "symbols", "xdk_symbols.json")
    if not os.path.exists(path):
        return {}
    return {int(s["address"], 16): s["name"] for s in json.load(open(path))
            if s["kind"] == "function"}


def same_name(a, b):
    """Whether two names of one function agree: XbSymbolDatabase writes
    CDirectSoundVoice_SetPosition or DSound_CRefCount_Release where the .lib
    has ?SetPosition@CDirectSoundVoice@DirectSound@@..., so the shorter,
    undecorated, must end the longer."""
    def norm(n):
        n = c_name(n) if n[:1] in "?@_" else n
        n = re.sub(r"[^a-z0-9]", "", n.lower())
        for p in ("directsound", "dsound", "d3d"):
            if n.startswith(p):
                n = n[len(p):]
        return n
    x, y = norm(a), norm(b)
    return bool(x) and bool(y) and (x.endswith(y) or y.endswith(x))


# ── Calls in order ──────────────────────────────────────────

def starts_of():
    """{start: end} of the disassembly's functions."""
    funcs = json.load(open(os.path.join(REPO, "analysis", "disasm", "functions.json")))
    return {int(f["start"], 16): int(f["end"], 16) for f in funcs}


def lib_calls(fn, md):
    """The symbols a .lib function calls or tail-jumps to, in order (None
    where it cannot be told): a relocated rel32 names its target; one with no
    relocation lands in the same section, on a static of the same object."""
    rel = {off: (target, addend) for off, rtype, target, addend in fn["relocs"] if rtype == REL_I386_REL32}
    syms = fn["obj"]["symbols"]
    out = []
    for ins in md.disasm(fn["bytes"], 0):
        if ins.size != 5 or ins.bytes[0] not in (0xE8, 0xE9):
            continue
        if ins.address + 1 in rel:
            target, addend = rel[ins.address + 1]
            if target["class"] == 3 and target["name"].startswith("."):
                inner = [s for s in syms.values() if s["section"] == target["section"]
                         and s["value"] == addend + 4 and s["type"] == 0x20]
                out.append(inner[0]["name"] if inner else None)
            else:
                out.append(target["name"])
            continue
        dest = ins.address + 5 + struct.unpack_from("<i", fn["bytes"], ins.address + 1)[0]
        if 0 <= dest < len(fn["bytes"]):
            if ins.bytes[0] == 0xE8:
                out.append(None)        # a call inside itself: keeps the count
            continue
        inner = [s for s in syms.values() if s["section"] == fn["secnum"]
                 and s["value"] == fn["start"] + dest and s["type"] == 0x20]
        out.append(inner[0]["name"] if inner else None)
    return out


def xbe_calls(va, end, raw_img, sections, md):
    """The targets a function of the XBE calls or tail-jumps to, in order."""
    sec = section_of(sections, va)
    if sec is None:
        return []
    base, data = raw_img[sec]
    out = []
    for ins in md.disasm(data[va - base:end - base], va):
        if ins.size != 5 or ins.bytes[0] not in (0xE8, 0xE9):
            continue
        dest = (ins.address + 5 + struct.unpack_from("<i", bytes(ins.bytes), 1)[0]) & 0xFFFFFFFF
        if va <= dest < end:
            if ins.bytes[0] == 0xE8:
                out.append(dest)
            continue
        out.append(dest)
    return out


def name_by_calls(by_addr, known, by_symbol, raw_img, sections, starts, defs):
    """Step 7 of main: names callees by their place in a named caller's calls.
    Adds to by_addr; returns (named, rounds, callers that lent, disagreed)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    lib_norm = [(sym, c_name(sym)) for sym in by_symbol]

    def symbols_at(va):
        out = {n[1] for n in by_addr.get(va, ()) if n[5] == "function"}
        if va in known:
            out.add(known[va])
        return out

    def counterpart(va):
        """The .lib functions a named address is, when one name fits."""
        names = symbols_at(va)
        for sym in names:
            if sym in by_symbol:
                return by_symbol[sym]
        for n in names:
            cands = {sym for sym, cn in lib_norm if same_name(n, cn)}
            if len({c_name(c) for c in cands}) == 1:
                return [fn for c in cands for fn in by_symbol[c]]
        return None

    calls_of = {}
    lent, disagreed, named, rounds = set(), set(), 0, 0
    done = set()
    while True:
        rounds += 1
        votes = collections.defaultdict(set)
        for va in [a for a in set(by_addr) | set(known) if a in starts and a not in done]:
            fns = counterpart(va)
            if not fns:
                continue
            done.add(va)
            mine = xbe_calls(va, starts[va], raw_img, sections, md)
            for fn in fns:
                if id(fn) not in calls_of:
                    calls_of[id(fn)] = lib_calls(fn, md)
                theirs = calls_of[id(fn)]
                if len(theirs) != len(mine):
                    continue
                pairs = list(zip(mine, theirs))
                if any(sym and symbols_at(t) and not any(same_name(n, sym) for n in symbols_at(t))
                       for t, sym in pairs):
                    disagreed.add(va)
                    break
                for t, sym in pairs:
                    if sym and not symbols_at(t) and t in starts:
                        votes[t].add(sym)
                lent.add(va)
                break
        fresh = 0
        for t, syms in votes.items():
            if len({c_name(x) for x in syms}) != 1:
                continue
            sym = sorted(syms)[0]
            by_addr[t].add((emit_name(sym, defs), sym, defs.get(sym, "?"), "calls", 0, "function"))
            fresh += 1
        named += fresh
        if not fresh:
            break
    return named, rounds, len(lent), len(disagreed)


# ── Likeness ────────────────────────────────────────────────

# Where each library's code is: an unnamed function there is compared with
# that library's functions only. In .text the C runtime and XAPI sit among the
# game's code, so a function there counts only between library functions.
SECTION_LIBS = {"D3D": ("D3D8",), "DSOUND": ("DSOUND",), "XPP": ("XAPILIB",),
                ".text": ("LIBCMT", "LIBCPMT", "XAPILIB")}
LIKE_MIN = 0.85         # the best likeness has to reach this
LIKE_GAP = 0.08         # and beat the second best by this much
NUMBER = re.compile(r"0x[0-9a-f]+|\b\d+\b")


def shape(code, md):
    """A function's instructions with every number hidden."""
    return [ins.mnemonic + " " + NUMBER.sub("N", ins.op_str) for ins in md.disasm(code, 0)]


def name_by_likeness(by_addr, known, by_symbol, raw_img, sections, starts, defs, check):
    """Step 8 of main. Adds to by_addr (unless check); returns how many."""
    import difflib
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    named = {va for va in starts if va in known or any(n[5] == "function" for n in by_addr.get(va, ()))}
    used = {n[1] for va in by_addr for n in by_addr[va]} | set(known.values())
    order = sorted(starts)

    def lib_named(va):
        return va in named and (va in known or any(n[3] in ("bytes", "reloc", "calls") for n in by_addr[va]))

    def in_library(i):
        """Whether the i-th function sits among library functions."""
        sec = section_of(sections, order[i])
        if sec in ("D3D", "DSOUND", "XPP"):
            return True
        if sec != ".text":
            return False
        before = any(lib_named(order[j]) for j in range(max(0, i - 4), i))
        after = any(lib_named(order[j]) for j in range(i + 1, min(len(order), i + 5)))
        return before and after

    def xbe_shape(va):
        sec = section_of(sections, va)
        base, data = raw_img[sec]
        return shape(data[va - base:starts[va] - base], md)

    if check:
        # functions named by bytes, each one's own .lib function among the
        # candidates: does likeness alone find it?
        targets = [va for va in order if va in by_addr and any(n[3] == "bytes" for n in by_addr[va])][::4]
        truth = {va: next(n[1] for n in by_addr[va] if n[3] == "bytes") for va in targets}
        pool_used = used - set(truth.values())
    else:
        targets = [order[i] for i in range(len(order)) if order[i] not in named and in_library(i)]
        truth = {}
        pool_used = used

    pools = {}
    for sym, fns in by_symbol.items():
        if sym in pool_used:
            continue
        fn = fns[0]
        pools.setdefault(fn["library"], []).append((sym, fn))
    shapes = {}

    best_of = {}
    for va in targets:
        sec = section_of(sections, va)
        mine = xbe_shape(va)
        if len(mine) < 6:
            continue
        cands = []
        for library in SECTION_LIBS.get(sec, ()):
            for sym, fn in pools.get(library, ()):
                n = len(fn["bytes"])
                if not 0.6 * (starts[va] - va) <= n <= 1.6 * (starts[va] - va):
                    continue
                if sym not in shapes:
                    shapes[sym] = shape(fn["bytes"], md)
                sm = difflib.SequenceMatcher(None, mine, shapes[sym], autojunk=False)
                if sm.real_quick_ratio() < LIKE_MIN or sm.quick_ratio() < LIKE_MIN:
                    continue
                cands.append((sm.ratio(), sym))
        cands.sort(reverse=True)
        if cands and cands[0][0] >= LIKE_MIN and (len(cands) == 1 or cands[0][0] - cands[1][0] >= LIKE_GAP):
            best_of[va] = cands[0]

    # one address per symbol: a symbol two addresses want names neither
    wanted = collections.Counter(sym for _, sym in best_of.values())
    found = {va: sym for va, (r, sym) in best_of.items() if wanted[sym] == 1}

    if check:
        right = sum(1 for va, sym in found.items() if c_name(sym) == c_name(truth[va]))
        print("likeness check: %d functions named by bytes; it names %d, %d of them right, %d wrong"
              % (len(targets), len(found), right, len(found) - right))
        for va, sym in found.items():
            if c_name(sym) != c_name(truth[va]):
                print("  0x%08X is %s, likeness says %s" % (va, truth[va], sym))
        return 0
    for va, sym in found.items():
        by_addr[va].add((emit_name(sym, defs), sym, defs.get(sym, "?"), "likeness", 0, "function"))
    return len(found)


# ── The XBE ─────────────────────────────────────────────────

def xbe_image(analysis):
    """{va: bytes} for every section, and the executable ones."""
    raw = open(XBE, "rb").read()
    sections = []
    for s in analysis["sections"]:
        va, ra = int(s["virtual_addr"], 16), int(s["raw_addr"], 16)
        sections.append((s["name"], va, raw[ra:ra + s["raw_size"]], s["executable"], s["virtual_size"]))
    return sections


def section_of(sections, va):
    for name, base, data, x, vsize in sections:
        if base <= va < base + vsize:
            return name
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--libs", default="D:/xdk/extracted/lib", help="folder with the XDK's .lib files")
    ap.add_argument("-o", "--out", default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="measure the likeness step on named functions and write nothing")
    args = ap.parse_args()

    analysis = json.load(open(ANALYSIS_JSON))
    sections = xbe_image(analysis)
    code_sections = [s for s in sections if s[3] and s[0] not in (".rdata", ".data")]
    # .rdata and .data are flagged executable in this XBE but hold no code

    # 1. Patterns, deduplicated by content: identical functions under several
    #    names (aliases) keep every name.
    patterns = {}
    defs = {}
    by_symbol = collections.defaultdict(list)
    for fname, library in LIBS.items():
        path = os.path.join(args.libs, fname)
        if not os.path.exists(path):
            print("missing %s, skipped" % path)
            continue
        for fn in lib_functions(path, library, defs):
            by_symbol[fn["symbol"]].append(fn)
            fixed = sum(fn["mask"])
            if len(fn["bytes"]) < MIN_SIZE or fixed < MIN_FIXED:
                continue
            key = (fn["bytes"], fn["mask"])
            patterns.setdefault(key, []).append(fn)
    print("patterns: %d distinct functions" % len(patterns))

    # 2. Anchor each pattern at its rarest fixed window.
    freq = collections.Counter()
    windows = {}
    for key in patterns:
        code, mask = key
        ws = []
        for off, run in fixed_runs(code, mask):
            for i in range(0, len(run) - ANCHOR + 1):
                ws.append((off + i, run[i:i + ANCHOR]))
        windows[key] = ws
        for _, w in set((0, w) for _, w in ws):
            freq[w] += 1
    index = collections.defaultdict(list)
    for key, ws in windows.items():
        if not ws:
            continue
        off, w = min(ws, key=lambda ow: (freq[ow[1]], ow[0]))
        index[w].append((key, off, len(key[0]), fixed_runs(*key)))

    # 3. Scan the code sections.
    hits = collections.defaultdict(set)
    for name, base, data, _, _ in code_sections:
        for q in range(len(data) - ANCHOR + 1):
            cands = index.get(data[q:q + ANCHOR])
            if not cands:
                continue
            for key, off, size, runs in cands:
                start = q - off
                if start < 0 or start + size > len(data):
                    continue
                if all(data[start + o:start + o + len(r)] == r for o, r in runs):
                    hits[key].add(base + start)

    # 4. Unique matches name their address.
    matched = {}
    ambiguous = 0
    for key, addrs in hits.items():
        if len(addrs) != 1:
            ambiguous += 1
            continue
        matched[next(iter(addrs))] = (key, patterns[key])

    raw_img = {}
    for name, base, data, _, vsize in sections:
        raw_img[name] = (base, data)

    def targets(va, fn):
        """(symbol, address) for each relocation of a match at va."""
        base, data = raw_img[section_of(sections, va)]
        for off, rtype, target, addend in fn["relocs"]:
            if rtype not in (REL_I386_DIR32, REL_I386_REL32):
                continue
            here = va - base + off
            if here + 4 > len(data):
                continue
            word = struct.unpack_from("<I", data, here)[0]
            if rtype == REL_I386_DIR32:
                tva = (word - addend) & 0xFFFFFFFF
            else:
                tva = (va + off + 4 + word - addend) & 0xFFFFFFFF
            tsym = target
            if tsym["class"] == 3 and tsym["value"] == 0 and tsym["name"].startswith("."):
                # a section symbol: the static it points into, by offset
                inner = [s for s in fn["obj"]["symbols"].values()
                         if s["section"] == tsym["section"] and s["value"] == addend
                         and not s["name"].startswith((".", "$"))]
                if not inner:
                    continue
                tsym = inner[0]
                tva = (tva + addend) & 0xFFFFFFFF
            if tsym["name"].startswith(("__imp_", "$", "??_C@")):
                continue
            # COFF types a function symbol 0x20, defined or not
            yield tsym["name"], tva, (tsym["type"] & 0xF0) == 0x20

    # 5. Coherence. A thin wrapper is one call with the target masked, so the
    #    same pattern fits several functions (Play and PauseEx); what tells
    #    them apart is where the call goes. A match is dropped when its own
    #    address has another name in XbSymbolDatabase, or when a call of it
    #    lands on an address that a surviving match or XbSymbolDatabase names
    #    as something else. Repeated until nothing more is dropped.
    known = load_known()

    def names_at(va):
        out = set()
        if va in matched:
            out |= {fn["symbol"] for fn in matched[va][1]}
        if va in known:
            out.add(known[va])
        return out

    def coherent(va, fn):
        if va in known and not same_name(known[va], fn["symbol"]):
            return False
        for sym, tva, _ in targets(va, fn):
            there = names_at(tva)
            if there and not any(same_name(n, sym) for n in there):
                return False
        return True

    # Each pattern's names are narrowed to the coherent ones; a pattern left
    # with none, or with two different functions (identical wrappers that
    # nothing tells apart), names nothing.
    dropped = 0
    while True:
        changed = False
        for va in list(matched):
            key, fns = matched[va]
            keep = [fn for fn in fns if coherent(va, fn)]
            if len(keep) != len(fns):
                changed = True
                if keep:
                    matched[va] = (key, keep)
                else:
                    del matched[va]
                    dropped += 1
        if not changed:
            break
    for va in list(matched):
        if len({c_name(fn["symbol"]) for fn in matched[va][1]}) > 1:
            del matched[va]
            dropped += 1

    by_addr = collections.defaultdict(set)
    for va, (key, fns) in matched.items():
        for fn in fns:
            by_addr[va].add((emit_name(fn["symbol"], defs), fn["symbol"], fn["library"], "bytes", len(key[0]),
                             "function"))

    # 6. Relocations of each match name their targets.
    votes = collections.defaultdict(collections.Counter)
    for va, (key, fns) in matched.items():
        fn = fns[0]
        for sym, tva, is_func in targets(va, fn):
            votes[sym][(tva, defs.get(sym, fn["library"]), is_func)] += 1

    reloc_named = 0
    for sym, cands in votes.items():
        if len(cands) != 1:
            continue
        (tva, library, is_func), _ = cands.most_common(1)[0]
        sec = section_of(sections, tva)
        if sec is None:
            continue
        if tva in by_addr and any(n[3] == "bytes" for n in by_addr[tva]):
            continue
        if tva in known and not same_name(known[tva], sym):
            continue
        by_addr[tva].add((emit_name(sym, defs), sym, library, "reloc", 0,
                          "function" if is_func else "variable"))
        reloc_named += 1

    # 7. Calls in order. A named function's version in the .lib calls X, Y, Z
    #    in that order; where its code in the XBE makes as many calls, its
    #    calls are X, Y, Z too, matched or not. Functions named this way lend
    #    their calls the same way, round after round. A function whose calls
    #    land on a name that says otherwise lends nothing (its 4721 version
    #    calls in another order), and a callee two callers name differently
    #    stays unnamed.
    starts = starts_of()
    called = name_by_calls(by_addr, known, by_symbol, raw_img, sections, starts, defs)

    # 8. Likeness, for what changed between 4721 and 5849: an unnamed function
    #    inside a library's code whose instructions, with every number
    #    hidden, read almost as one .lib function's not yet placed, and no
    #    other comes close. Measured first on functions already named, as if
    #    they were not (args.check).
    similar = name_by_likeness(by_addr, known, by_symbol, raw_img, sections, starts, defs, args.check)
    if args.check:
        return
    called = (called[0] + name_by_calls(by_addr, known, by_symbol, raw_img, sections, starts, defs)[0],) + called[1:]

    # 8. One entry per address; several names for one address are aliases,
    #    the first (sorted) is kept as the name and the rest listed.
    out = []
    for va in sorted(by_addr):
        names = sorted(by_addr[va], key=lambda n: (n[3] != "bytes", n[0]))
        name, sym, library, how, size, kind = names[0]
        entry = {"address": "0x%08X" % va, "name": name, "symbol": sym, "library": library,
                 "kind": kind, "how": how}
        if size:
            entry["size"] = size
        aliases = sorted(set(n[1] for n in names[1:]) - {sym})
        if aliases:
            entry["aliases"] = aliases
        out.append(entry)

    # A C name used at two addresses is a static of the same name in two
    # objects (write_char in output.obj and in woutput.obj): each takes its
    # object's name after the library prefix, crt_output_write_char.
    # The object is the matched one's; for a name placed otherwise, of the
    # objects defining that symbol the one whose function is closest in size.
    for e in out:
        va = int(e["address"], 16)
        fns = [fn for fn in matched[va][1] if fn["symbol"] == e["symbol"]] if va in matched else []
        if not fns and by_symbol.get(e["symbol"]):
            size = starts.get(va, va) - va
            fns = sorted(by_symbol[e["symbol"]], key=lambda fn: abs(len(fn["bytes"]) - size))
        if fns:
            e["object"] = os.path.splitext(fns[0]["member"].replace("\\", "/").split("/")[-1])[0]
    count = collections.Counter(e["name"] for e in out)
    for e in out:
        if count[e["name"]] > 1 and e.get("object"):
            prefix = PREFIX.get(e["library"], ("", ()))[0]
            rest = e["name"][len(prefix):] if prefix and e["name"].startswith(prefix) else e["name"]
            e["name"] = prefix + e["object"] + "_" + rest
    count = collections.Counter(e["name"] for e in out)
    left = sorted(e["name"] for e in out if count[e["name"]] > 1)
    if left:
        print("still at two addresses, left out: %s" % ", ".join(sorted(set(left))))
        out = [e for e in out if count[e["name"]] == 1]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(" " + json.dumps(e) for e in out) + "\n]\n")
    kinds = collections.Counter((e["library"], e["kind"], e["how"]) for e in out)
    print("matched by bytes: %d patterns at one place (%d dropped as incoherent), %d at several (left out)"
          % (len(matched), dropped, ambiguous))
    print("named by relocations: %d" % reloc_named)
    print("named by calls in order: %d in %d rounds (%d callers lent names, %d disagreed and lent none)"
          % called)
    print("named by likeness: %d" % similar)
    for k in sorted(kinds):
        print("  %-8s %-8s %-5s %5d" % (k + (kinds[k],)))
    print("wrote %s (%d entries)" % (os.path.relpath(args.out, REPO), len(out)))


if __name__ == "__main__":
    main()
