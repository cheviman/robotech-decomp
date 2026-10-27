# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        disassembler.py
Description: the game's x86 functions decoded: their instructions, where each goes, their jump tables
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

The functions are the ones xboxrecomp's disassembler found (analysis/disasm/functions.json), each the
stretch from its start to its end, decoded with Capstone. An instruction's operands become Operand
values the lifter reads without Capstone's types. A jump through a table of addresses
("jmp [reg*4 + table]") gets the table's entries: as many as the compare that guards it allows
("cmp reg, N; ja default" before it: N + 1), else the words that point into the function.
"""
import json
import os
import struct
from dataclasses import dataclass, field

import capstone
from capstone import x86_const as X

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
XBE = os.path.join(REPO, "analysis", "default.xbe")
ANALYSIS_JSON = os.path.join(REPO, "analysis", "default_analysis.json")
FUNCTIONS = os.path.join(REPO, "analysis", "disasm", "functions.json")

FLOW_NONE, FLOW_BRANCH, FLOW_JUMP, FLOW_COMPUTED, FLOW_CALL, FLOW_RETURN, FLOW_STOP = range(7)
BRANCHES = {"je", "jne", "jb", "jae", "jbe", "ja", "js", "jns", "jl", "jge", "jle", "jg", "jo", "jno",
            "jp", "jnp", "jecxz"}


@dataclass(frozen=True)
class Operand:
    """kind 'reg', 'mem' or 'imm'; 'bits' its width. A register by its Capstone name (eax, al, ah, ax);
    a memory operand by its base and index registers (or None), scale, displacement and segment."""
    kind: str
    bits: int
    reg: str = None
    base: str = None
    index: str = None
    scale: int = 1
    disp: int = 0
    segment: str = None
    imm: int = 0


@dataclass
class Instruction:
    address: int
    length: int
    mnemonic: str            # with its prefix, as Capstone spells it: "rep stosd"
    op_str: str
    operands: tuple
    flow: int
    targets: tuple = ()      # where a branch, jump or call goes (a jump table's entries)
    table: int = None        # a jump table's address

    @property
    def next(self):
        return self.address + self.length


@dataclass
class Function:
    entry: int
    end: int
    name: str
    instructions: dict = field(default_factory=dict)    # address -> Instruction, in order


class Program:
    """The XBE's sections and the game's functions, decoded on demand."""

    def __init__(self, names=None):
        analysis = json.load(open(ANALYSIS_JSON))
        self.raw = open(XBE, "rb").read()
        self.sections = [(s["name"], int(s["virtual_addr"], 16), s["virtual_size"], int(s["raw_addr"], 16),
                          s["raw_size"]) for s in analysis["sections"]]
        self.functions = {}
        self.callers = {}       # entry -> the functions that call or jump to it (the disassembler's own)
        for f in json.load(open(FUNCTIONS)):
            entry = int(f["start"], 16)
            name = (names or {}).get(entry) or f["name"]
            self.functions[entry] = (int(f["end"], 16), name, f["section"])
            self.callers[entry] = {int(caller, 16) for caller in f.get("called_by", ())}
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.md.detail = True
        self.decoded = {}

    def read(self, va, n):
        for _, base, size, raw_at, raw_size in self.sections:
            if base <= va < base + size:
                at = va - base
                data = self.raw[raw_at + at:raw_at + min(at + n, raw_size)]
                return data + bytes(n - len(data))
        return None

    def word(self, va):
        data = self.read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    def function(self, entry):
        if entry not in self.decoded:
            end, name, _ = self.functions[entry]
            function = Function(entry, end, name)
            code = self.read(entry, end - entry)
            listed = list(self.md.disasm(code, entry))
            for position, insn in enumerate(listed):
                instruction = self.convert(insn)
                if instruction.flow == FLOW_COMPUTED and instruction.operands[0].kind == "mem":
                    self.jump_table(instruction, listed[:position], function)
                function.instructions[instruction.address] = instruction
            self.decoded[entry] = function
        return self.decoded[entry]

    def convert(self, insn):
        operands = []
        for op in insn.operands:
            bits = op.size * 8
            if op.type == X.X86_OP_REG:
                operands.append(Operand("reg", bits, reg=insn.reg_name(op.reg)))
            elif op.type == X.X86_OP_IMM:
                operands.append(Operand("imm", bits, imm=op.imm & 0xFFFFFFFF))
            elif op.type == X.X86_OP_MEM:
                m = op.mem
                operands.append(Operand("mem", bits,
                                        base=insn.reg_name(m.base) if m.base else None,
                                        index=insn.reg_name(m.index) if m.index else None,
                                        scale=m.scale, disp=m.disp & 0xFFFFFFFF,
                                        segment=insn.reg_name(m.segment) if m.segment else None))
        name = insn.mnemonic
        targets, flow = (), FLOW_NONE
        if name in BRANCHES:
            flow, targets = FLOW_BRANCH, (operands[0].imm,)
        elif name == "jmp":
            if operands[0].kind == "imm":
                flow, targets = FLOW_JUMP, (operands[0].imm,)
            else:
                flow = FLOW_COMPUTED
        elif name == "call":
            flow = FLOW_CALL
            if operands[0].kind == "imm":
                targets = (operands[0].imm,)
        elif name in ("ret", "retn"):
            flow = FLOW_RETURN
        elif name in ("int3", "hlt", "ud2"):
            flow = FLOW_STOP
        return Instruction(insn.address, insn.size, name, insn.op_str, tuple(operands), flow, targets)

    def jump_table(self, instruction, before, function):
        op = instruction.operands[0]
        if op.base is not None or op.index is None or op.scale != 4 or op.segment:
            return
        count = None
        # "cmp reg, N" then "ja" within the few instructions before: N + 1 entries
        for insn in reversed(before[-6:]):
            if insn.mnemonic == "cmp" and len(insn.operands) == 2 and insn.operands[1].type == X.X86_OP_IMM \
                    and insn.operands[0].type == X.X86_OP_REG and insn.reg_name(insn.operands[0].reg) == op.index:
                count = (insn.operands[1].imm & 0xFFFFFFFF) + 1
                break
        entries = []
        limit = count if count is not None else 512
        for k in range(limit):
            target = self.word(op.disp + 4 * k)
            if target is None or not function.entry <= target < function.end:
                if count is not None:
                    return       # a guarded table whose entries leave the function: not one of ours
                break
            entries.append(target)
        if entries:
            instruction.table = op.disp
            instruction.targets = tuple(entries)
