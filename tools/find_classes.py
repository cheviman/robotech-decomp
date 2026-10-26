"""
Name:        find_classes.py
Description: names the engine's object classes and their callbacks from the descriptors the game registers
Version:     0.2.0
Created:     25-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

Vicious Cycle's engine has no C++ classes to speak of (no RTTI, few vtables):
its objects are handles, (type << 16) | index, and each type registers a
descriptor with vcRegisterClass (0x00110370), built on the stack by a function
of its own: the class name (vcTexture), a file tag (txr) and the callbacks the
object system calls through it. Each callback slot is called from one generic
function, which says what the slot is:

    +0x34  Create      vcObjectCreate (0x001103C0): calloc of the object
    +0x38  Destroy     vcObjectRelease (0x00110510): frees the children and the object
    +0x3C  Collect     vcObjectCollectChanged (0x00110810): goes over the children to save
    +0x40  Load        vcObjectLoad (0x00110E90): reads it, by file version
    +0x44  Reload      vcObjectLoad, vcObjectReload (0x00111160): reads one that exists again
    +0x48  LoadChunk   vcObjectLoadChunk (0x00110A80): reads one chunk of it
    +0x4C  Copy        vcObjectClone (0x00110780): fills a new object from another
    +0x50  InUse       vcObjectReleaseLater (0x001108B0): whether it is still in use
    +0x54  GetSize     vcObjectGetSize (0x001107C0): the object's size in bytes

(src/game/engine/objects.c has the object system written in C, slot by slot.)

This reads every registering function (the ones that call vcRegisterClass),
replays its stack writes and writes symbols/classes.json:
per class its registering function, tag and callbacks, and the names they get
(<Class>_Register, <Class>_Load...). A callback several classes share (the
defaults: return 0, return 1, return the third argument) is left unnamed.

    py -3 tools/find_classes.py
"""
import collections
import json
import os
import re
import struct

import capstone
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XBE = os.path.join(REPO, "analysis", "default.xbe")
ANALYSIS_JSON = os.path.join(REPO, "analysis", "default_analysis.json")
DISASM = os.path.join(REPO, "analysis", "disasm")
OUT = os.path.join(REPO, "symbols", "classes.json")

REGISTER_CLASS = 0x00110370
DESCRIPTOR_SIZE = 0x5C
# Each slot's meaning, from the generic function that calls it. +0x44 was
# taken for Save before the object system was read: it reads (26-10-2026).
SLOTS = {0x34: "Create", 0x38: "Destroy", 0x3C: "Collect", 0x40: "Load", 0x44: "Reload", 0x48: "LoadChunk",
         0x4C: "Copy", 0x50: "InUse", 0x54: "GetSize"}
SLOT_RANGE = range(0x34, 0x58, 4)
TAG = 0x24
CLASS_NAME = re.compile(r"^(vc|gc)[A-Z][A-Za-z0-9_]+$")


def main():
    analysis = json.load(open(ANALYSIS_JSON))
    raw = open(XBE, "rb").read()
    sections = [(int(s["virtual_addr"], 16), int(s["raw_addr"], 16), s["raw_size"]) for s in analysis["sections"]]

    def read(va, n):
        for base, ra, size in sections:
            if base <= va < base + size:
                return raw[ra + va - base:ra + va - base + n]
        return b""

    funcs = json.load(open(os.path.join(DISASM, "functions.json")))
    starts = {int(f["start"], 16): int(f["end"], 16) for f in funcs}
    ordered = sorted(starts)
    strings = json.load(open(os.path.join(DISASM, "strings.json")))
    refs = collections.defaultdict(list)
    for x in json.load(open(os.path.join(DISASM, "xrefs.json"))):
        refs[int(x["to"], 16)].append(int(x["from"], 16))

    def containing(va):
        lo, hi = 0, len(ordered) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if ordered[mid] <= va:
                lo = mid + 1
            else:
                hi = mid - 1
        return ordered[hi] if hi >= 0 and va < starts[ordered[hi]] else None

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True

    def class_name_at(va):
        """The class name a string at va spells, if it is one."""
        text = read(va, 64).split(b"\0")[0].decode("latin-1")
        return text if CLASS_NAME.match(text) else None

    # Every function that calls vcRegisterClass. Its class's name is the one
    # string of a class name its code points at: an immediate (mov esi, NAME
    # for a rep movsd) or a memory operand (mov eax, [NAME], a dword of it at
    # a time). The disassembler's cross references miss the second kind, so
    # the instructions are read here: finding the registering functions by
    # the references to the names, as this did first, missed five classes
    # (vcBeamParticleSystem, vcMusic, vcDecalMgr, gcLevel, gcAIData).
    registering = sorted({containing(src) for src in refs.get(REGISTER_CLASS, [])} - {None})
    classes = []
    for fn in registering:
        code = read(fn, starts[fn] - fn)
        desc = replay(md, fn, code)
        if desc is None or desc["call"] != REGISTER_CLASS:
            continue
        named = []
        for ins in md.disasm(code, fn):
            for op in ins.operands:
                va = op.imm if op.type == X86_OP_IMM else op.mem.disp if op.type == X86_OP_MEM else None
                if va is not None and 0 < va < 0x80000000:
                    name = class_name_at(va & 0xFFFFFFFF)
                    if name and name not in named:
                        named.append(name)
        if len(named) != 1:
            print("0x%08X registers a class whose name is not clear: %s" % (fn, named or "none"))
            continue
        slots = {off: va for off, va in desc["writes"].items() if off in SLOT_RANGE and va in starts}
        tag = desc["writes"].get(TAG)
        classes.append({"class": named[0], "register": fn, "registers_with": desc["call"],
                        "tag": struct.pack("<I", tag).rstrip(b"\0").decode("latin-1") if tag else None,
                        "slots": slots})

    # A callback more than one class uses is a shared default: no class name.
    users = collections.Counter(va for c in classes for va in set(c["slots"].values()))
    names = []
    for c in classes:
        names.append({"address": "0x%08X" % c["register"], "name": c["class"] + "_Register",
                      "class": c["class"]})
        for off, va in sorted(c["slots"].items()):
            if users[va] == 1 and off in SLOTS:
                names.append({"address": "0x%08X" % va, "name": "%s_%s" % (c["class"], SLOTS[off]),
                              "class": c["class"], "slot": "0x%02X" % off})

    out = {"classes": [{"class": c["class"], "register": "0x%08X" % c["register"],
                        "registers_with": "0x%08X" % c["registers_with"], "tag": c["tag"],
                        "slots": {"0x%02X" % off: "0x%08X" % va for off, va in sorted(c["slots"].items())}}
                       for c in sorted(classes, key=lambda c: c["register"])],
           "names": sorted(names, key=lambda n: n["address"])}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    with_cb = sum(1 for n in names if "slot" in n)
    print("%d classes, %d registering functions and %d callbacks named (%d shared, left unnamed)"
          % (len(classes), len(classes), with_cb, sum(1 for va, n in users.items() if n > 1)))
    print("wrote %s" % os.path.relpath(OUT, REPO))


def replay(md, start, code):
    """The descriptor a registering function builds: its stack writes, by
    offset from the descriptor's start, up to the call it is passed to.
    The descriptor is the block the function zeroes first (lea edi, [esp+N];
    rep stosd); a register keeps the immediate last moved into it."""
    delta, base, regs, writes, pushed_desc = 0, None, {}, {}, False
    for ins in md.disasm(code, start):
        m, ops = ins.mnemonic, ins.operands
        reg = lambda o: ins.reg_name(o.reg) if o.type == X86_OP_REG else None
        if m in ("sub", "add") and reg(ops[0]) == "esp" and ops[1].type == X86_OP_IMM:
            delta += -ops[1].imm if m == "sub" else ops[1].imm
        elif m == "push":
            if base is not None and reg(ops[0]) and regs.get(reg(ops[0])) == ("desc",):
                pushed_desc = True
            delta -= 4
        elif m == "pop":
            delta += 4
        elif m == "lea" and ops[1].type == X86_OP_MEM and ins.reg_name(ops[1].mem.base) == "esp":
            here = delta + ops[1].mem.disp
            if base is None:
                base = here
            if here == base:
                regs[reg(ops[0])] = ("desc",)
        elif m == "mov" and reg(ops[0]) and ops[1].type == X86_OP_IMM:
            regs[reg(ops[0])] = ops[1].imm
        elif m == "xor" and reg(ops[0]) and reg(ops[0]) == reg(ops[1]):
            regs[reg(ops[0])] = 0
        elif m == "mov" and ops[0].type == X86_OP_MEM and ins.reg_name(ops[0].mem.base) == "esp" and base is not None:
            off = delta + ops[0].mem.disp - base
            if 0 <= off < DESCRIPTOR_SIZE:
                if ops[1].type == X86_OP_IMM:
                    writes[off] = ops[1].imm & 0xFFFFFFFF
                elif reg(ops[1]) and isinstance(regs.get(reg(ops[1])), int):
                    writes[off] = regs[reg(ops[1])] & 0xFFFFFFFF
        elif m == "call":
            if pushed_desc and ops[0].type == X86_OP_IMM:
                return {"writes": writes, "call": ops[0].imm}
        elif reg(ops[0]) if ops else False:
            regs.pop(reg(ops[0]), None)
    return None


if __name__ == "__main__":
    main()
