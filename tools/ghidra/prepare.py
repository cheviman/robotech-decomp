# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        prepare.py
Description: what Ghidra needs to read the game: its image and the names known so far
Version:     0.1.0
Created:     11-11-2026
Modified:    11-11-2026
Author:      Sebastian Toyos

Ghidra is for reading what tools/decompile.py does not lift yet: its C never goes into the build. No XBE
loader is needed: this writes the XBE's sections as one flat image at their addresses
(analysis/ghidra/flat.bin, from 0x11000) and the list RobotechSeed.java marks before the analysis
(analysis/ghidra/seed.txt: "func ADDRESS [NAME]" for each function of analysis/disasm/functions.json and
of symbols.txt, "data ADDRESS NAME" for each place symbols.txt names).

    py -3 tools/ghidra/prepare.py

Then, once (51 seconds; G is the absolute path of analysis/ghidra, S of tools/ghidra):

    D:/ghidra/support/analyzeHeadless.bat G/project robotech -import G/flat.bin -overwrite
        -loader BinaryLoader -loader-baseAddr 0x11000 -processor x86:LE:32:default -cspec windows
        -scriptPath S -preScript RobotechSeed.java G/seed.txt

and for the C of some functions, by their addresses, with the project kept from that run:

    D:/ghidra/support/analyzeHeadless.bat G/project robotech -process flat.bin -noanalysis
        -scriptPath S -postScript RobotechDecompile.java G/out 6A180 1A700
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.join(REPO, "analysis", "ghidra")     # where the image, the list and Ghidra's project go
os.makedirs(HERE, exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "tools"))
import symbols  # noqa: E402
from x86 import disassembler  # noqa: E402

program = disassembler.Program()
base = min(s[1] for s in program.sections)
end = max(s[1] + s[2] for s in program.sections)
image = bytearray(end - base)
for name, start, size, _, raw_size in program.sections:
    stored = min(size, raw_size)
    image[start - base:start - base + stored] = program.read(start, stored)
with open(os.path.join(HERE, "flat.bin"), "wb") as out:
    out.write(image)

sym = symbols.load()
lines = []
starts = set()
for function in json.load(open(os.path.join(REPO, "analysis", "disasm", "functions.json"))):
    address = int(function["start"], 16)
    starts.add(address)
    name = sym["func"].get(address)
    lines.append("func %08X%s" % (address, " " + name if name else ""))
for address, name in sorted(sym["func"].items()):
    if address not in starts and base <= address < end:
        lines.append("func %08X %s" % (address, name))
for address, name in sorted(sym["data"].items()):
    if base <= address < end:
        lines.append("data %08X %s" % (address, name))
with open(os.path.join(HERE, "seed.txt"), "w", encoding="ascii", newline="\n") as out:
    out.write("\n".join(lines) + "\n")
print("flat.bin: 0x%X bytes from 0x%X; seed.txt: %d lines" % (len(image), base, len(lines)))

# types.txt, for RobotechTypes.java: symbols.txt's structures and variables, and the registers and
# arguments tools/decompile.py found each function takes (analysis/decompiled_signatures.json)
#   struct NAME SIZE / field STRUCT OFFSET NAME TYPE COUNT / var ADDRESS NAME TYPE COUNT / sig ADDRESS ARGUMENTS REGISTERS
# (hexadecimal but for the counts; COUNT 0 for one, -1 for an array of a length not given)
SAVED = {"ebx", "ebp", "esi", "edi"}
types = []
for name, struct in sorted(sym["structs"].items()):
    if not struct.get("size"):
        continue
    types.append("struct %s %X" % (name, struct["size"]))
    for field in sorted(struct["fields"], key=lambda f: f["offset"]):
        kind, count = symbols.TYPE_RE.match(field["type"]).groups()
        types.append("field %s %X %s %s %d" % (name, field["offset"], field["name"], kind,
                                              0 if count is None else int(count) if count else -1))
for address, var in sorted(sym["vars"].items()):
    if not base <= address < end:
        continue
    if var.get("struct"):
        kind, count = symbols.STRUCT_TYPE_RE.match(var["type"]).groups()
        if kind not in sym["structs"]:
            continue
    else:
        kind, count = symbols.TYPE_RE.match(var["type"]).groups()
    types.append("var %08X %s %s %d" % (address, var["name"], kind, 0 if count is None else int(count) if count else -1))
signatures = os.path.join(REPO, "analysis", "decompiled_signatures.json")
taken = 0
if os.path.exists(signatures):
    for key, signature in sorted(json.load(open(signatures)).items()):
        registers = [name[2:] for name in signature["registers"]]
        if SAVED <= set(registers):
            # the four it saves on entry and puts back, which it may leave as they were: not what it takes
            registers = [name for name in registers if name not in SAVED]
        if registers:
            types.append("sig %08X %d %s" % (int(key, 16), signature["arguments"], ",".join(registers)))
            taken += 1
with open(os.path.join(HERE, "types.txt"), "w", encoding="ascii", newline="\n") as out:
    out.write("\n".join(types) + "\n")
print("types.txt: %d structures, %d variables, %d functions that take a register"
      % (len(sym["structs"]), sum(1 for line in types if line.startswith("var ")), taken))
