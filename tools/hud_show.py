"""Ghidra's C of some functions with today's names in it, to read a function before the build has them.

    py -3.14 tools/hud_show.py 28A30 HUDScreen_CreateWidgets ...   the C of those functions (address or name)
    py -3.14 tools/hud_show.py -c 20CD0                            who calls it (the functions, by name)
    py -3.14 tools/hud_show.py -r 1B2810                           the functions that mention that address
    py -3.14 tools/hud_show.py -t ScreenElement 9                  a type's record and its callbacks' C
    py -3.14 tools/hud_show.py -w 1B2810 8                         8 words at an address, as numbers, texts, names
    py -3.14 tools/hud_show.py -d B9790 60 [TEXT]                  60 instructions from an address (capstone),
                                                                   only the ones with TEXT and their neighbours

analysis/ghidra/out/all.c is Ghidra's C of every function, written with FUN_ and DAT_ and the addresses
it had no name for; symbols/symbols.txt has today's names. This puts the second into the first: a FUN_ or a
DAT_ gets its name, a number that is the address of a string of the XBE gets the string beside it, one that
is a function's or a variable's gets its name, and a number the texts' table knows as a text
(analysis/string_table.txt) gets it where a call that takes a text's number has it.
"""
import json, os, re, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = os.path.join(REPO, "analysis", "ghidra", "out", "all.c")
SYM = os.path.join(REPO, "symbols", "symbols.txt")
REG = os.path.join(REPO, "symbols", "registries.json")
XBE = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "default.xbe")
TEXTS = os.path.join(REPO, "analysis", "string_table.txt")


class Xbe:
    def __init__(self):
        self.d = d = open(XBE, "rb").read()
        self.base = struct.unpack_from("<I", d, 0x104)[0]
        count, headers = struct.unpack_from("<II", d, 0x11C)
        self.secs = [struct.unpack_from("<IIIII", d, headers - self.base + i * 56)[1:] for i in range(count)]

    def off(self, va):
        for v, _, raw, size in self.secs:
            if v <= va < v + size:
                return raw + va - v
        return None

    def u32(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from("<I", self.d, o)[0]

    def f32(self, va):
        o = self.off(va)
        return None if o is None else struct.unpack_from("<f", self.d, o)[0]

    def string(self, va):
        o = self.off(va)
        if o is None:
            return None
        t = self.d[o:self.d.find(b"\0", o)]
        if 2 < len(t) < 90 and all(32 <= c < 127 for c in t):
            return t.decode("latin1")
        return None


def symbols():
    names, by_name = {}, {}
    for line in open(SYM, encoding="utf-8"):
        m = re.match(r"^([0-9A-F]{8})\s+(func|data|var)\s+(\S+)", line)
        if m:
            names[int(m.group(1), 16)] = m.group(3)
            by_name[m.group(3)] = int(m.group(1), 16)
    return names, by_name


def texts():
    out = {}
    if os.path.exists(TEXTS):
        for line in open(TEXTS, encoding="utf-8", errors="replace"):
            m = re.match(r"^\s*(0x[0-9A-Fa-f]+|\d+)\s+(.*)$", line)
            if m:
                out[int(m.group(1), 0)] = m.group(2).strip()
    return out


def functions():
    """{address: (Ghidra's name, [lines])} of all.c."""
    out, current, lines = {}, None, []
    for line in open(ALL, encoding="utf-8", errors="replace"):
        head = re.match(r"// ==== ([0-9A-F]{8}) (\S+)", line)
        if head:
            if current is not None:
                out[current[0]] = (current[1], lines)
            current, lines = (int(head.group(1), 16), head.group(2)), []
        else:
            lines.append(line.rstrip("\n"))
    if current is not None:
        out[current[0]] = (current[1], lines)
    return out


def renamer(names, xbe, txt):
    def fun(m):
        a = int(m.group(1), 16)
        return names.get(a, m.group(0))

    def dat(m):
        a = int(m.group(2), 16)
        return names.get(a, m.group(0))

    def num(m):
        a = int(m.group(0), 16)
        if a in names:
            return "%s /*%X*/" % (names[a], a)
        if 0x10000 <= a < 0x400000:
            s = xbe.string(a)
            if s is not None:
                return '%s /*"%s"*/' % (m.group(0), s)
        return m.group(0)

    def line(text):
        text = re.sub(r"\bFUN_([0-9a-f]{8})\b", fun, text)
        text = re.sub(r"\b(_?DAT|PTR_DAT|PTR_FUN|PTR_LAB|LAB|s_\w+?|PTR_s_\w+?|u_\w+?)_([0-9a-f]{8})\b", dat, text)
        text = re.sub(r"\b0x[0-9a-f]{5,6}\b", num, text)
        return text
    return line


def show(addr, funcs, rename, names):
    if addr not in funcs:
        print("// %08X: not in all.c" % addr)
        return
    print("// ==== %08X %s" % (addr, names.get(addr, funcs[addr][0])))
    for l in funcs[addr][1]:
        if l.strip():
            print(rename(l))


def main():
    args = sys.argv[1:]
    names, by_name = symbols()
    xbe = Xbe()
    txt = texts()
    funcs = functions()
    rename = renamer(names, xbe, txt)

    def address(a):
        if a in by_name:
            return by_name[a]
        return int(a, 16)

    if args and args[0] == "-c":
        for a in args[1:]:
            target = address(a)
            pat = re.compile(r"\bFUN_%08x\b" % target)
            print("callers of %s:" % names.get(target, "%08X" % target))
            for f in sorted(funcs):
                n = sum(1 for l in funcs[f][1] if pat.search(l))
                if n and f != target:
                    print("    %08X %-44s %d" % (f, names.get(f, funcs[f][0]), n))
        return
    if args and args[0] == "-r":
        for a in args[1:]:
            target = address(a)
            pat = re.compile(r"(?<![0-9a-f])%x\b|_%08x\b" % (target, target))
            print("mentions of %08X %s:" % (target, names.get(target, "")))
            for f in sorted(funcs):
                hits = [l.strip() for l in funcs[f][1] if pat.search(l)]
                if hits:
                    print("    %08X %-40s %s" % (f, names.get(f, funcs[f][0]), rename(hits[0])[:110]))
        return
    if args and args[0] == "-w":
        va, n = int(args[1], 16), int(args[2]) if len(args) > 2 else 8
        for i in range(n):
            w = xbe.u32(va + 4 * i)
            if w is None:
                print("%08X  (not in the file)" % (va + 4 * i))
                continue
            note = []
            if w in names:
                note.append(names[w])
            s = xbe.string(w) if 0x10000 <= w < 0x400000 else None
            if s is not None:
                note.append('"%s"' % s)
            if w in txt and w < 0x1000:
                note.append("text: " + txt[w][:60])
            f = struct.unpack("<f", struct.pack("<I", w))[0]
            if 1e-3 < abs(f) < 1e6:
                note.append("%g" % f)
            print("%08X  %08X  %s" % (va + 4 * i, w, "  ".join(note)))
        return
    if args and args[0] == "-d":
        import capstone
        va, n = address(args[1]), int(args[2]) if len(args) > 2 else 40
        want = args[3].lower() if len(args) > 3 else None
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        o = xbe.off(va)
        out = []
        for ins in md.disasm(xbe.d[o:o + n * 8], va):
            text = "%08X  %-7s %s" % (ins.address, ins.mnemonic, ins.op_str)
            text = re.sub(r"0x[0-9a-f]{5,6}", lambda m: rename(m.group(0)), text)
            out.append(text)
            if len(out) >= n:
                break
        for i, text in enumerate(out):
            if want is None or any(want in t.lower() for t in out[max(0, i - 6):i + 7]):
                print(text)
        return
    if args and args[0] == "-t":
        reg = json.load(open(REG))
        fam = [f for f in reg["families"] if f.get("name") == args[1]]
        if not fam:
            print("families:", [f.get("name") for f in reg["families"]])
            return
        for t in fam[0].get("types", []):
            if str(t.get("type")) != args[2]:
                continue
            print("%s %s: register %s, record %s, %d bytes an object, version %s, flags %s" % (
                args[1], args[2], t["register"], t["desc"], t["size"], t["version"], t["flags"]))
            for slot, f in sorted(t["slots"].items()):
                print("    +%s  %s  %s" % (slot, f, names.get(int(f, 16), "")))
            print("    strings: %s" % ", ".join(t.get("strings", [])))
            for f in [t["register"]] + [f for _, f in sorted(t["slots"].items())]:
                show(int(f, 16), funcs, rename, names)
        return
    for a in args:
        show(address(a), funcs, rename, names)


if __name__ == "__main__":
    main()
