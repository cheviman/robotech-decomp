"""
Name:        find_registries.py
Description: names the game's object types and their callbacks from the registries the game fills at start
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

Next to the engine's classes (find_classes.py), the game keeps registries of
its own object types: Entity, Effect, Weapon, Screen, Action, ScreenElement,
Node, Steering, Trigger, Item. Each is a static block -- a pointer to its
name, two words, an array of 128 type descriptors from +0x0C, a count -- set
up by one function that writes the name and then calls a registering
function per type, passing the block. Each registering function fills a
static descriptor (its first word the object's size, then pointers to the
type's functions) and stores it in the array: block[0x0C + 4 * type].

This finds the set-up functions (a block address pushed before five or more
calls, its first word a name string), replays each registering function's
stores, and writes symbols/registries.json: per family its block and types,
per type its descriptor, size, functions by slot and the strings its
functions use (hints for a name of its own). No names yet: a type's number
and a slot's offset are not names, and what each slot is and what each
type is called come from measuring them (the generic functions that call
the slots, the types' strings and behaviour).

    py -3 tools/find_registries.py
"""
import collections
import json
import os
import struct

import capstone
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XBE = os.path.join(REPO, "analysis", "default.xbe")
ANALYSIS_JSON = os.path.join(REPO, "analysis", "default_analysis.json")
DISASM = os.path.join(REPO, "analysis", "disasm")
OUT = os.path.join(REPO, "symbols", "registries.json")

TYPES_AT = 0x0C         # the descriptor array's offset in a block
TYPES = 128
DESC_SPAN = 0x40        # the descriptor head the slots are read from
MIN_CALLS = 5


def main():
    analysis = json.load(open(ANALYSIS_JSON))
    raw = open(XBE, "rb").read()
    sections = [(s["name"], int(s["virtual_addr"], 16), int(s["raw_addr"], 16), s["raw_size"])
                for s in analysis["sections"]]
    # .data whole, its uninitialised tail included: the blocks live there
    data_lo, data_hi = next((int(s["virtual_addr"], 16), int(s["virtual_addr"], 16) + s["virtual_size"])
                            for s in analysis["sections"] if s["name"] == ".data")

    def read(va, n):
        for name, base, ra, size in sections:
            if base <= va < base + size:
                return raw[ra + va - base:ra + va - base + n]
        return b""

    def cstr(va):
        s = read(va, 64)
        if b"\0" not in s:
            return None
        s = s[:s.index(b"\0")]
        return s.decode("latin-1") if s and all(32 <= c < 127 for c in s) else None

    funcs = json.load(open(os.path.join(DISASM, "functions.json")))
    ends = {int(f["start"], 16): int(f["end"], 16) for f in funcs}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True

    def insns(a):
        return list(md.disasm(read(a, ends[a] - a), a))

    def imm(op):
        return op.imm & 0xFFFFFFFF if op.type == X86_OP_IMM else None

    # 1. Set-up functions: a .data block pushed before MIN_CALLS calls or
    #    more, its first word set to a name string in the same function.
    families = []
    for a in sorted(ends):
        if a >= data_lo:
            continue
        code = insns(a)
        pushed, calls, names = None, collections.defaultdict(list), {}
        for i in code:
            ops = i.operands
            if i.mnemonic == "push" and ops and imm(ops[0]) is not None:
                pushed = imm(ops[0])
                continue
            if i.mnemonic == "call":
                # the last immediate pushed is the first argument
                if ops and imm(ops[0]) is not None and pushed is not None:
                    calls[pushed].append(imm(ops[0]))
                pushed = None
            if (i.mnemonic == "mov" and len(ops) == 2 and ops[0].type == X86_OP_MEM and not ops[0].mem.base
                    and not ops[0].mem.index and imm(ops[1]) is not None):
                names.setdefault(ops[0].mem.disp & 0xFFFFFFFF, cstr(imm(ops[1])))
        for block, targets in calls.items():
            if len(targets) >= MIN_CALLS and data_lo <= block < data_hi and names.get(block):
                families.append({"name": names[block], "block": block, "setup": a,
                                 "registers": [t for t in targets if t in ends]})

    # 2. Each registering function: the descriptor it stores in the block,
    #    and what it writes into the descriptor's head.
    starts = set(ends)
    for fam in families:
        fam["types"] = []
        for reg in fam["registers"]:
            t = replay(insns(reg), data_lo, data_hi)
            if not t or not TYPES_AT <= t["slot_offset"] < TYPES_AT + 4 * TYPES:
                continue
            desc, fields = t["desc"], t["writes"]
            head = {off - desc: v for off, v in fields.items() if desc <= off < desc + DESC_SPAN}
            fam["types"].append({
                "type": (t["slot_offset"] - TYPES_AT) // 4, "register": reg, "desc": desc,
                "size": head.get(0),
                "slots": {o: v for o, v in sorted(head.items()) if o and v in starts},
            })

    # 3. Hints: the strings each type's functions refer to.
    strings = {int(s["address"], 16): s["string"] for s in json.load(open(os.path.join(DISASM, "strings.json")))}
    refs = collections.defaultdict(set)
    for x in json.load(open(os.path.join(DISASM, "xrefs.json"))):
        to = int(x["to"], 16)
        if to in strings:
            refs[int(x["from"], 16)].add(strings[to])
    ordered = sorted(ends)

    def strings_of(fn):
        import bisect
        lo = bisect.bisect_left(ordered, fn)
        out = set()
        for site, ss in refs.items():
            if fn <= site < ends[fn]:
                out |= ss
        return out

    site_list = sorted(refs)
    import bisect

    def strings_in(fn):
        out = set()
        i = bisect.bisect_left(site_list, fn)
        while i < len(site_list) and site_list[i] < ends[fn]:
            out |= refs[site_list[i]]
            i += 1
        return out

    for fam in families:
        for t in fam["types"]:
            found = set()
            for fn in [t["register"]] + list(t["slots"].values()):
                found |= strings_in(fn)
            t["strings"] = sorted(found)[:12]

    out = {"families": [{"name": f["name"], "block": "0x%08X" % f["block"], "setup": "0x%08X" % f["setup"],
                         "types": [{"type": t["type"], "register": "0x%08X" % t["register"],
                                    "desc": "0x%08X" % t["desc"], "size": t["size"],
                                    "slots": {"0x%02X" % o: "0x%08X" % v for o, v in t["slots"].items()},
                                    "strings": t["strings"]}
                                   for t in sorted(f["types"], key=lambda t: t["type"])]}
                        for f in families]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    for fam in families:
        print("%-14s block 0x%08X, %3d of %3d registering functions read" %
              (fam["name"], fam["block"], len(fam["types"]), len(fam["registers"])))
    print("wrote %s" % os.path.relpath(OUT, REPO))


def replay(code, data_lo, data_hi):
    """A registering function's stores: [block + off] = descriptor (the block
    the function's first argument), and every store to an absolute address,
    immediate or from a register holding one. None when it stores no
    descriptor."""
    regs, arg_regs, writes, found = {}, set(), {}, None
    for i in code:
        ops = i.operands
        m = i.mnemonic

        def reg(o):
            return i.reg_name(o.reg) if o.type == X86_OP_REG else None

        if m == "mov" and len(ops) == 2 and reg(ops[0]):
            src = ops[1]
            if src.type == X86_OP_MEM and i.reg_name(src.mem.base) == "esp" and src.mem.disp == 4:
                arg_regs.add(reg(ops[0]))
                regs.pop(reg(ops[0]), None)
            elif src.type == X86_OP_IMM:
                regs[reg(ops[0])] = src.imm & 0xFFFFFFFF
                arg_regs.discard(reg(ops[0]))
            else:
                regs.pop(reg(ops[0]), None)
                arg_regs.discard(reg(ops[0]))
            continue
        if m == "xor" and len(ops) == 2 and reg(ops[0]) and reg(ops[0]) == reg(ops[1]):
            regs[reg(ops[0])] = 0
            arg_regs.discard(reg(ops[0]))
            continue
        if m == "mov" and len(ops) == 2 and ops[0].type == X86_OP_MEM:
            mem = ops[0].mem
            val = ops[1].imm & 0xFFFFFFFF if ops[1].type == X86_OP_IMM else regs.get(reg(ops[1]))
            if val is None:
                continue
            base = i.reg_name(mem.base) if mem.base else None
            if base in arg_regs and not mem.index and data_lo <= val < data_hi:
                found = (mem.disp, val)
            elif not mem.base and not mem.index:
                writes[mem.disp & 0xFFFFFFFF] = val
            continue
        if ops and reg(ops[0]) and m not in ("push", "cmp", "test"):
            regs.pop(reg(ops[0]), None)
            arg_regs.discard(reg(ops[0]))
    if not found:
        return None
    return {"slot_offset": found[0], "desc": found[1], "writes": writes}


if __name__ == "__main__":
    main()
