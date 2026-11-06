"""
Name:        coverage.py
Description: byte map of the XBE: the functions' code, the data they point at, fill, and what is still unknown
Version:     0.1.0
Created:     05-11-2026
Modified:    05-11-2026
Author:      Sebastian Toyos

    py -3 tools/coverage.py           # writes analysis/coverage.txt and prints the bytes of each class

arcade-decomp's tools/core/coverage.py maps a program ROM this way; this is the XBE's. Every byte of every
section, as the section lies in memory (its part past the raw data, which the loader zeroes, included),
gets one class:
  code             the functions' bytes (analysis/disasm/functions.json), but for the tables in them
  described data   data whose layout is known: symbols.txt's var lines (a type and a count; of records
                   of a structure in place, their named fields), the jump
                   tables and the byte tables of sparse switches, the strings (analysis/disasm/strings.json),
                   the constants the code loads from .rdata by their address with a width the instruction
                   gives (the x87's floats, which the decompiled C writes as their values), the words that
                   hold a function's entry or a string's start, the kernel's import table, and the sections
                   that are one thing each: the title's image, the saves' image, the Dolby encoder's program
  referenced data  from a place the code reads, writes or takes the address of, a data line of
                   symbols.txt or a record of a structure in place, up to the next known thing
  fill             what lies between a function and the next function or jump table when it is only int3,
                   nop, zeros or MSVC's multi-byte nops ("lea ecx, [ecx+0]"); the zeros after described data
                   up to the next 4-byte word
  unknown          everything else

The game's own is what the decompilation names and types: its and the engine's code in .text (by symbols.txt's
file lines; the XDK's XAPI and C runtime lie among it) and its part of .rdata and .data, where the linker put
every object's constants and variables one after another: a place is the game's when its code (or
symbols.txt) reaches it, the libraries' when only theirs does, and the bytes after it go with it. The rest,
and the XDK's, Bink's and Dolby's own sections, are counted apart. The game's unknown runs are listed largest
first, with how many bytes of each decode as instructions from its start and how many 4-byte words of the
data sections hold its address.
"""
import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

import symbols  # noqa: E402
from x86 import disassembler  # noqa: E402

REPO = os.path.dirname(TOOLS)
ANALYSIS = os.path.join(REPO, "analysis")
SYMBOLS = os.path.join(REPO, "symbols", "symbols.txt")
STRINGS = os.path.join(ANALYSIS, "disasm", "strings.json")
XREFS = os.path.join(ANALYSIS, "disasm", "xrefs.json")
OUTPUT = os.path.join(ANALYSIS, "coverage.txt")

CODE = "code"
DESCRIBED = "described data"
DATA = "referenced data"
FILL = "fill"
UNKNOWN = "unknown"
CLASSES = (CODE, DESCRIBED, DATA, FILL, UNKNOWN)

GAME_DATA = (".rdata", ".data")
# sections that are one thing each, by what they hold
WHOLE = {"$$XTIMAGE": "the title's image", "$$XSIMAGE": "the saves' image",
         "DOLBY": "the Dolby Digital encoder's DSP program, which DirectSound loads"}
CODE_FILL = (0xCC, 0x90, 0x00)
# the instructions MSVC fills with up to an aligned place in code (a jump table, a loop): nothing done
NOPS = (bytes.fromhex("8da42400000000"), bytes.fromhex("8d9b00000000"), bytes.fromhex("8d642400"),
        bytes.fromhex("8d4900"), bytes.fromhex("8bff"), bytes.fromhex("8bc0"), b"\x90", b"\xcc", b"\x00")


def only_nops(data):
    """True when 'data' is nothing but MSVC's fill instructions, one after another."""
    while data:
        for nop in NOPS:
            if data.startswith(nop):
                data = data[len(nop):]
                break
        else:
            return False
    return True
TYPE_BYTES = {"u8": 1, "s8": 1, "char": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "f32": 4, "f64": 8}


def symbols_places():
    """symbols.txt's places: (variables as (address, bytes or None for a count not given), the stretches
    of records of a structure in place whose layout is known (their named fields), the records as (start,
    size), the data lines' addresses)."""
    sym = symbols.load()
    variables, fields, records = [], [], []
    for address, var in sym["vars"].items():
        if var.get("struct"):
            st = sym["structs"].get(var["struct"])
            if st is None or not st.get("size"):
                continue
            count = symbols.STRUCT_TYPE_RE.match(var["type"]).group(2)
            number = int(count) if count else 1
            for k in range(number):
                first = address + k * st["size"]
                records.append((first, st["size"]))
                for fld in st["fields"]:
                    m = symbols.TYPE_RE.match(fld["type"])
                    one = TYPE_BYTES[m.group(1)]
                    many = int(m.group(2)) if m.group(2) else 1
                    fields.append((first + fld["offset"], one * many))
            continue
        m = symbols.TYPE_RE.match(var["type"])
        size = TYPE_BYTES[m.group(1)]
        count = m.group(2)
        variables.append((address, None if count == "" else size * int(count or 1)))
    data = [address for address in sym["data"] if address not in sym["vars"]]
    return variables, fields, records, data


class Image:
    """The XBE's sections as the loader lays them out, and the functions in them, decoded."""

    def __init__(self):
        self.program = disassembler.Program()
        self.sections = []      # (name, start, end, raw_end)
        for name, base, size, _, raw_size in self.program.sections:
            self.sections.append((name, base, base + size, base + min(raw_size, size)))
        self.starts = [s[1] for s in self.sections]

    def section(self, address):
        position = bisect.bisect_right(self.starts, address) - 1
        if position >= 0:
            name, start, end, _ = self.sections[position]
            if start <= address < end:
                return name
        return None

    def byte(self, address):
        return self.program.read(address, 1)[0]


def byte_table(instructions, position, image):
    """(address, bytes) of a sparse switch's byte table when the jump through a table at 'position' indexes
    it by a byte loaded a few instructions before ("movzx reg, byte ptr [value + bytes]"), as many as the
    compare that guards the value allows ("cmp value, N"); else None."""
    jump = instructions[position].operands[0]
    for back in range(position - 1, max(-1, position - 5), -1):
        load = instructions[back]
        if load.mnemonic != "movzx" or len(load.operands) != 2:
            continue
        destination, source = load.operands
        if destination.kind != "reg" or destination.reg != jump.index or source.kind != "mem" or source.bits != 8 \
                or source.base is None or source.index is not None or image.section(source.disp) is None:
            return None
        for compare in reversed(instructions[max(0, back - 8):back]):
            if compare.mnemonic == "cmp" and len(compare.operands) == 2 and compare.operands[1].kind == "imm" \
                    and compare.operands[0].kind == "reg" and compare.operands[0].reg == source.base:
                return source.disp, compare.operands[1].imm + 1
        return None
    return None


def classify(image):
    """{section name: bytearray of class indexes}, and the references and described places found."""
    program = image.program
    code = set()
    described = {}          # first byte -> stop
    references = defaultdict(list)
    read_only = {name for name, *_ in image.sections if name == ".rdata"}

    def describe(first, size):
        if size > 0:
            described[first] = max(described.get(first, first), first + size)

    for entry, (end, _, _) in program.functions.items():
        code.update(range(entry, end))
    for entry in sorted(program.functions):
        try:
            function = program.function(entry)
        except Exception:
            continue
        listed = list(function.instructions.values())
        for position, instruction in enumerate(listed):
            if instruction.table is not None:
                describe(instruction.table, 4 * len(instruction.targets))
                found = byte_table(listed, position, image)
                if found is not None and found[1] <= 1024:
                    describe(*found)
            for operand in instruction.operands:
                if operand.kind == "mem" and not operand.segment:
                    # a fixed place, or a table's start a register indexes ("[eax + table]"): a displacement
                    # in a section of data (a structure's offsets are small numbers, below every section)
                    place = operand.disp
                    if place in program.functions or image.section(place) in (None, ".text"):
                        continue
                    references[place].append(instruction.address)
                    # a constant loaded by its address with the width the instruction gives
                    if operand.base is None and operand.index is None and image.section(place) in read_only \
                            and operand.bits in (32, 64, 80) and instruction.mnemonic.startswith("f"):
                        describe(place, operand.bits // 8)
                elif operand.kind == "imm" and operand.imm not in program.functions:
                    name = image.section(operand.imm)
                    if name is not None and name != ".text":
                        references[operand.imm].append(instruction.address)
    for x in json.load(open(XREFS)):
        if x["type"] in ("data_read", "data_imm"):
            place = int(x["to"], 16)
            if place not in program.functions and image.section(place) not in (None, ".text"):
                references[place].append(int(x["from"], 16))

    strings = {}
    for s in json.load(open(STRINGS)):
        address = int(s["address"], 16)
        strings[address] = s["length"] + 1
        describe(address, s["length"] + 1)

    variables, fields, records, data = symbols_places()
    variable_starts = sorted(a for a, _ in variables)
    for address, size in variables:
        if size is None:
            # a count not given: up to the next variable
            position = bisect.bisect_right(variable_starts, address)
            size = (variable_starts[position] - address) if position < len(variable_starts) else 4
        describe(address, size)
    # records of a structure in place: their named fields described, the rest of each record reached
    for address, size in fields:
        describe(address, size)
    for address, _ in records:
        references.setdefault(address, [])
    for address in data:
        references.setdefault(address, [])
    in_records = set()
    for first, size in records:
        in_records.update(range(first, first + size))

    # the kernel's import table: a word per import, then a zero
    thunk = int(json.load(open(disassembler.ANALYSIS_JSON))["kernel_thunk_addr"], 16)
    count = 0
    while program.word(thunk + 4 * count):
        count += 1
    describe(thunk, 4 * (count + 1))

    # words outside the code that hold a function's entry or a string's start
    for name, start, end, raw_end in image.sections:
        if name in WHOLE:
            continue
        for address in range(start + (-start) % 4, raw_end - 3, 4):
            if address in code:
                continue
            value = program.word(address)
            if value in program.functions or value in strings:
                describe(address, 4)
                if value in strings:
                    references[value].append(address)

    # the per-byte classes
    covered = set()
    for first, stop in described.items():
        covered.update(range(first, stop))
    classes = {}
    for name, start, end, raw_end in image.sections:
        row = bytearray(end - start)
        if name in WHOLE:
            row[:] = bytes([CLASSES.index(DESCRIBED)]) * len(row)
            classes[(name, start)] = row
            continue
        current = CLASSES.index(UNKNOWN)
        for address in range(start, end):
            if address in covered:
                row[address - start] = CLASSES.index(DESCRIBED)
                current = CLASSES.index(UNKNOWN)
            elif address in code:
                row[address - start] = CLASSES.index(CODE)
                current = CLASSES.index(UNKNOWN)
            else:
                if address in references:
                    current = CLASSES.index(DATA)
                # a record's bytes no field names are still the record's
                row[address - start] = CLASSES.index(DATA) if address in in_records else current
        # fill: what lies between a function and the next known thing (a function, its tables), when it is
        # only int3, nop or zeros; the zeros after described data up to the next 4-byte word
        unknown, known = CLASSES.index(UNKNOWN), (CLASSES.index(CODE), CLASSES.index(DESCRIBED))
        holds_code = CLASSES.index(CODE) in row
        offset = 1
        while offset < len(row):
            if row[offset] != unknown or row[offset - 1] not in known:
                offset += 1
                continue
            stop = offset
            while stop < len(row) and row[stop] == unknown:
                stop += 1
            values = {image.byte(start + k) for k in range(offset, stop)}
            after = row[stop] if stop < len(row) else None
            if holds_code and after in known and only_nops(image.program.read(start + offset, stop - offset)):
                row[offset:stop] = bytes([CLASSES.index(FILL)]) * (stop - offset)
            elif values == {0}:
                aligned = min(stop, offset + (-(start + offset)) % 4)
                row[offset:aligned] = bytes([CLASSES.index(FILL)]) * (aligned - offset)
            offset = stop
        classes[(name, start)] = row
    return classes, references, described


def code_stretches(start, end):
    """[(first, stop, the game's)] of .text by symbols.txt's file lines: the game's and the engine's code,
    or the XDK's (XAPI, the C runtime) that the game linked among it."""
    lines = []
    for line in open(SYMBOLS, encoding="utf-8"):
        fields = line.split("#")[0].split()
        if len(fields) >= 3 and fields[1] == "file" and re.fullmatch(r"[0-9A-Fa-f]{8}", fields[0]):
            lines.append((int(fields[0], 16), fields[2].split("/")[0] in ("game", "engine")))
    lines.sort()
    stretches = []
    for k, (first, own) in enumerate(lines):
        stop = lines[k + 1][0] if k + 1 < len(lines) else end
        first, stop = max(first, start), min(stop, end)
        if first < stop:
            stretches.append((first, stop, own))
    return stretches


def owners(image, references):
    """{section: bytearray, 1 for the game's bytes and 0 for the libraries'} of .rdata and .data, where the
    linker put the constants and variables of every object one after another: a place is the game's when
    its code (or symbols.txt) reaches it, the libraries' when only theirs does, and the bytes after it
    follow it up to the next place reached."""
    text = [s for s in image.sections if s[0] == ".text"][0]
    stretches = code_stretches(text[1], text[2])
    firsts = [first for first, _, _ in stretches]

    def game_code(address):
        if not text[1] <= address < text[2]:
            return False if image.section(address) not in GAME_DATA else None    # a word of data: no say
        return stretches[bisect.bisect_right(firsts, address) - 1][2]

    found = {}
    for name, start, end, _ in image.sections:
        if name not in GAME_DATA:
            continue
        row = bytearray(end - start)
        current = 1
        for address in range(start, end):
            if address in references:
                says = [game_code(at) for at in references[address]]
                says = [s for s in says if s is not None]
                if not references[address] or any(says):
                    current = 1
                elif says:
                    current = 0
            row[address - start] = current
        found[name] = row
    return found


def counts(image, classes, owned):
    """{row label: Counter of classes}: each section, then the game's and the libraries' totals."""
    rows = {}
    totals = {"game": Counter(), "libraries": Counter()}
    for name, start, end, _ in image.sections:
        row = classes[(name, start)]
        if name == ".text":
            own, linked = Counter(), Counter()
            for first, stop, game in code_stretches(start, end):
                (own if game else linked).update(CLASSES[k] for k in row[first - start:stop - start])
            parts = ((".text (game)", own, "game"), (".text (XDK)", linked, "libraries"))
        elif name in GAME_DATA:
            own, linked = Counter(), Counter()
            for k, game in zip(row, owned[name]):
                (own if game else linked)[CLASSES[k]] += 1
            parts = ((f"{name} (game)", own, "game"), (f"{name} (XDK)", linked, "libraries"))
        else:
            label = f"{name} {start:08X}" if name.startswith("BINKYUY2") else name
            parts = ((label, Counter(CLASSES[k] for k in row), "game" if name in GAME_DATA else "libraries"),)
        for label, c, kind in parts:
            rows[label] = c
            totals[kind].update(c)
    return rows, totals


def measure():
    """The game's bytes by class (for tools/noise_report.py)."""
    image = Image()
    classes, references, _ = classify(image)
    _, totals = counts(image, classes, owners(image, references))
    return totals["game"]


def sweep(image, first, stop):
    """Bytes of [first, stop) that decode as instructions, one after another, before the first that does not."""
    code = image.program.read(first, stop - first)
    length = 0
    for insn in image.program.md.disasm(code, first):
        if insn.address != first + length:
            break
        length += insn.size
    return length


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    image = Image()
    classes, references, described = classify(image)
    owned = owners(image, references)
    rows, totals = counts(image, classes, owned)

    lines = ["XBE coverage", "============", ""]
    header = f"{'section':<20}" + "".join(f"{name:>16}" for name in CLASSES) + f"{'total':>10}"
    lines.append(header)
    for label, c in rows.items():
        lines.append(f"{label:<20}" + "".join(f"{c[name]:16}" for name in CLASSES) + f"{sum(c.values()):10}")
    for kind in ("game", "libraries"):
        c = totals[kind]
        lines.append(f"{'total, ' + kind:<20}" + "".join(f"{c[name]:16}" for name in CLASSES)
                     + f"{sum(c.values()):10}")

    # the game's unknown runs, largest first
    runs = []
    data_words = defaultdict(int)
    for name, start, end, raw_end in image.sections:
        if name not in GAME_DATA and name != ".text":
            continue
        row = classes[(name, start)]
        own = [(first, stop) for first, stop, game in code_stretches(start, end) if game] \
            if name == ".text" else [(start, end)]
        for first, last in own:
            offset, limit = first - start, last - start
            mine = owned.get(name)
            while offset < limit:
                if row[offset] != CLASSES.index(UNKNOWN) or (mine is not None and not mine[offset]):
                    offset += 1
                    continue
                stop = offset
                while stop < limit and row[stop] == CLASSES.index(UNKNOWN) and (mine is None or mine[stop]):
                    stop += 1
                runs.append((start + offset, start + stop))
                offset = stop
    firsts = {first for first, _ in runs}
    for name, start, end, raw_end in image.sections:
        if name in GAME_DATA:
            for address in range(start + (-start) % 4, raw_end - 3, 4):
                value = image.program.word(address)
                if value in firsts:
                    data_words[value] += 1
    lines += ["", f"places the code reads, writes or takes the address of, or symbols.txt marks as data: "
                  f"{len(references)}",
              f"described stretches: {len(described)}",
              f"unknown runs in the game's sections: {len(runs)}, {sum(b - a for a, b in runs)} bytes"]
    title = "Unknown runs in the game's sections, largest first"
    lines += ["", title, "-" * len(title),
              f"{'first':<9} {'last':<9} {'section':<8} {'bytes':>7} {'decodes':>8} {'pointers':>8}  first bytes"]
    for first, stop in sorted(runs, key=lambda r: (r[0] - r[1], r[0])):
        decoded = sweep(image, first, stop) if image.section(first) == ".text" else 0
        verdict = "all" if decoded == stop - first else str(decoded)
        raw = image.program.read(first, min(stop - first, 12)).hex(" ")
        lines.append(f"{first:08X}  {stop - 1:08X}  {image.section(first):<8} {stop - first:7} {verdict:>8} "
                     f"{data_words.get(first, 0):>8}  {raw}")
    with open(OUTPUT, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:len(rows) + 8]))
    print(f"wrote {os.path.relpath(OUTPUT, REPO)}")


if __name__ == "__main__":
    main()
