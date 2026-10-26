"""
Name:        find_registries.py
Description: the game's object types and their callbacks, from the families the game registers at start
Version:     0.2.0
Created:     25-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

Next to the engine's classes (find_classes.py), the game has objects of its
own (game/objects, the GameObject functions): each of a type, the types in
families -- Player, Entity, Structure, Screen, Weapon, Component, Node,
Action, ScreenElement, Effect, Steering, Trigger, Item. A family is a static
block, a GameObjectFamily (symbols.txt): a pointer to its name, its startup
and shutdown, its types from +0x10 (by number, from 0), how many numbers
they take and the newest version of its files. One function sets it up:
zeroes it, writes its name and fields, calls a registering function per
type with the block, and registers it by its number with
GameObjectRegisterFamily (0x0001D4E0). Each registering function fills a
static GameObjectType (its first word the object's size, then the type's
callbacks) and stores it in the block, at +0x10 + 4 * type. A callback slot
is said by the generic function that calls it:

    +0x04  Startup       GameObjectTypeUse: the type's first use
    +0x08  Shutdown      GameObjectTypeRelease: its last release
    +0x0C  StateMachine  GameObjectDeliver: how its objects answer a message in a state
    +0x10  Load          GameObjectLoad: reads one of its objects from a file
    +0x14  (none)        GameObjectsDestroyAll calls it after the type's objects are gone; no type has it
    +0x18  Collect       GameObjectCollect: what an object refers to that has to be saved

This reads every set-up function (the callers of GameObjectRegisterFamily),
replays its stores and calls, replays each registering function's stores,
and writes symbols/registries.json: per family its number, block, fields
and types, per type its descriptor, size, version, callbacks by slot and the
strings its functions use (hints for a name of its own). No names: a type's
number and a slot's offset are not names. A type's name is a type line of
symbols.txt, written by hand from what the type is (its strings, its
behaviour); tools/symbols.py merge names its functions from it.

    py -3 tools/find_registries.py
"""
import bisect
import collections
import json
import os

import capstone
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XBE = os.path.join(REPO, "analysis", "default.xbe")
ANALYSIS_JSON = os.path.join(REPO, "analysis", "default_analysis.json")
DISASM = os.path.join(REPO, "analysis", "disasm")
OUT = os.path.join(REPO, "symbols", "registries.json")

REGISTER_FAMILY = 0x0001D4E0    # GameObjectRegisterFamily(number, family)
STARTUP, SHUTDOWN = 0x04, 0x08  # a family's own, at the same offsets as a type's
TYPES_AT = 0x10                 # the types' array in a family, by number from 0
TYPES = 127
TYPE_COUNT, VERSION = 0x20C, 0x210
DESC_SPAN = 0x40                # the descriptor head the slots are read from
TYPE_VERSION, TYPE_FLAGS = 0x1C, 0x20


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
        if va is None:
            return None
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

    # 1. Set-up functions: the callers of GameObjectRegisterFamily. A call's
    #    first argument is the last value pushed before it; a value is an
    #    immediate or a register known to hold one (xor reg, reg; mov reg, imm).
    families, problems = [], []
    for a in sorted(ends):
        if a >= data_lo:
            continue
        code = insns(a)
        if not any(i.mnemonic == "call" and i.operands and imm(i.operands[0]) == REGISTER_FAMILY for i in code):
            continue
        pushed, regs, stores, calls, registered = [], {}, {}, [], None
        for i in code:
            ops, m = i.operands, i.mnemonic

            def value(o):
                if o.type == X86_OP_IMM:
                    return imm(o)
                return regs.get(i.reg_name(o.reg)) if o.type == X86_OP_REG else None

            if m == "push" and ops:
                pushed.append(value(ops[0]))
            elif m == "call":
                target = imm(ops[0]) if ops else None
                if target == REGISTER_FAMILY and len(pushed) >= 2:
                    registered = (pushed[-1], pushed[-2])
                elif target in ends and pushed:
                    calls.append((pushed[-1], target))
                pushed = []
                for r in ("eax", "ecx", "edx"):
                    regs.pop(r, None)
            elif m == "xor" and len(ops) == 2 and ops[0].type == X86_OP_REG and ops[0].reg == ops[1].reg:
                regs[i.reg_name(ops[0].reg)] = 0
            elif m == "mov" and len(ops) == 2 and ops[0].type == X86_OP_REG:
                regs[i.reg_name(ops[0].reg)] = value(ops[1])
            elif (m == "mov" and len(ops) == 2 and ops[0].type == X86_OP_MEM and not ops[0].mem.base
                    and not ops[0].mem.index):
                stores[ops[0].mem.disp & 0xFFFFFFFF] = value(ops[1])
            elif ops and ops[0].type == X86_OP_REG and m not in ("cmp", "test"):
                regs.pop(i.reg_name(ops[0].reg), None)
        if registered is None:
            problems.append("0x%08X registers a family whose number and block are not clear" % a)
            continue
        number, block = registered
        name = cstr(stores.get(block))
        if name is None or not data_lo <= block < data_hi:
            problems.append("0x%08X registers family %s, whose block's name is not clear" % (a, number))
            continue

        def field(off):
            return stores.get(block + off) or 0

        families.append({"name": name, "number": number, "block": block, "setup": a,
                         "version": field(VERSION), "type_count": field(TYPE_COUNT),
                         "startup": field(STARTUP), "shutdown": field(SHUTDOWN),
                         "registers": [t for b, t in calls if b == block]})

    # 2. Each registering function: the descriptor it stores in the block,
    #    and what it writes into the descriptor's head.
    starts = set(ends)
    for fam in families:
        fam["types"] = []
        for reg in fam["registers"]:
            # a type left out of the build: its registering function is a bare ret (DoNothing)
            if ends[reg] - reg == 1:
                continue
            t = replay(insns(reg), data_lo, data_hi)
            if not t or not TYPES_AT <= t["slot_offset"] < TYPES_AT + 4 * TYPES:
                problems.append("0x%08X, a registering function of %s, stores no type" % (reg, fam["name"]))
                continue
            desc, fields = t["desc"], t["writes"]
            head = {off - desc: v for off, v in fields.items() if desc <= off < desc + DESC_SPAN}
            fam["types"].append({
                "type": (t["slot_offset"] - TYPES_AT) // 4, "register": reg, "desc": desc,
                "size": head.get(0), "version": head.get(TYPE_VERSION, 0), "flags": head.get(TYPE_FLAGS, 0),
                "slots": {o: v for o, v in sorted(head.items()) if o and v in starts},
            })

    # 3. Hints: the strings each type's functions refer to.
    strings = {int(s["address"], 16): s["string"] for s in json.load(open(os.path.join(DISASM, "strings.json")))}
    refs = collections.defaultdict(set)
    for x in json.load(open(os.path.join(DISASM, "xrefs.json"))):
        to = int(x["to"], 16)
        if to in strings:
            refs[int(x["from"], 16)].add(strings[to])
    site_list = sorted(refs)

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

    def hexed(v):
        return "0x%08X" % v if v else None

    out = {"families": [{"name": f["name"], "number": f["number"], "block": hexed(f["block"]),
                         "setup": hexed(f["setup"]), "version": f["version"], "type_count": f["type_count"],
                         "startup": hexed(f["startup"]), "shutdown": hexed(f["shutdown"]),
                         "types": [{"type": t["type"], "register": hexed(t["register"]), "desc": hexed(t["desc"]),
                                    "size": t["size"], "version": t["version"], "flags": t["flags"],
                                    "slots": {"0x%02X" % o: hexed(v) for o, v in t["slots"].items()},
                                    "strings": t["strings"]}
                                   for t in sorted(f["types"], key=lambda t: t["type"])]}
                        for f in sorted(families, key=lambda f: f["number"])]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    for fam in sorted(families, key=lambda f: f["number"]):
        print("%2d %-14s block 0x%08X, %3d of %3d registering functions read" %
              (fam["number"], fam["name"], fam["block"], len(fam["types"]), len(fam["registers"])))
    for p in problems:
        print("  " + p)
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
