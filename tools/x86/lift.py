# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        lift.py
Description: translates decoded x86 data instructions into IR statements that do what the Pentium III does
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

The registers are the decompiler's (profile.py): EAX to EDI are 32-bit registers whose parts AX, AL and AH
(and so on) are read and written in place, the rest of the register kept. Every memory read becomes a
temporary in the order the instruction makes it, before anything it writes. Of the flags, ZF, SF, OF and
CF are kept as z, s, ov and cy, set as Intel's manual says for each instruction; PF and AF are not kept
(only the x87's compares branch on PF, and nothing reads AF). A flag the manual leaves undefined is given
the value the instruction would have set at its defined widths; nothing in the game reads one.

The game is compiled C: the direction flag is always clear, so a string instruction walks upwards.
Control instructions (jumps, calls, returns) are left to function.py.
"""
from v60 import ir

from .profile import EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI

# a register's name: (register, lowest bit, width)
REGISTERS = {}
for _index, (_full, _word, _low, _high) in enumerate((("eax", "ax", "al", "ah"), ("ecx", "cx", "cl", "ch"),
                                                       ("edx", "dx", "dl", "dh"), ("ebx", "bx", "bl", "bh"))):
    REGISTERS.update({_full: (_index, 0, 32), _word: (_index, 0, 16), _low: (_index, 0, 8), _high: (_index, 8, 8)})
for _index, (_full, _word) in ((ESP, ("esp", "sp")), (EBP, ("ebp", "bp")), (ESI, ("esi", "si")), (EDI, ("edi", "di"))):
    REGISTERS.update({_full: (_index, 0, 32), _word: (_index, 0, 16)})

# a condition code: the decompiler's name for it (tools/core/decompiler/function.py, flag_condition)
CONDITIONS = {"e": "e", "ne": "ne", "b": "l", "ae": "nl", "be": "nh", "a": "h", "s": "n", "ns": "p",
              "l": "lt", "ge": "ge", "le": "le", "g": "gt", "o": "v", "no": "nv"}
STRING_BITS = {"b": 8, "w": 16, "d": 32}


class Unsupported(Exception):
    """An instruction or operand the lifter does not translate."""


def mask(bits):
    return (1 << bits) - 1


class Lifter:
    """The IR statements of one instruction."""

    def __init__(self, prefix="t"):
        self.statements = []
        self.prefix = prefix
        self.count = 0

    def emit(self, statement):
        self.statements.append(statement)

    def temp(self, value, hint="value"):
        """Binds 'value' to a new temporary, so it is computed here, in order."""
        self.count += 1
        temp = ir.Temp(f"{self.prefix}{self.count}_{hint}", value.bits)
        self.emit(ir.SetTemp(temp, value))
        return temp

    def load(self, address, bits, hint="value"):
        return self.temp(ir.Load(address, bits), hint)

    # ---- operands ----

    def register(self, name):
        if name not in REGISTERS:
            raise Unsupported(f"register {name}")
        return REGISTERS[name]

    def read_register(self, name):
        index, low, bits = self.register(name)
        value = ir.Reg(index)
        if low:
            value = ir.op("shr", (value, ir.const(low, 8)), 32)
        return ir.trunc(value, bits)

    def write_register(self, name, value):
        index, low, bits = self.register(name)
        value = ir.trunc(value, bits) if value.bits > bits else ir.zext(value, bits)
        if bits == 32:
            self.emit(ir.SetReg(index, value))
            return
        kept = ir.op("and", (ir.Reg(index), ir.const(~(mask(bits) << low) & 0xFFFFFFFF)), 32)
        placed = ir.zext(value, 32)
        if low:
            placed = ir.op("shl", (placed, ir.const(low, 8)), 32)
        self.emit(ir.SetReg(index, ir.op("or", (kept, placed), 32)))

    def address(self, op):
        """The address a memory operand names."""
        if op.segment:
            raise Unsupported(f"segment {op.segment}")
        terms = []
        if op.base:
            terms.append(self.read_register(op.base))
        if op.index:
            index = self.read_register(op.index)
            terms.append(index if op.scale == 1 else ir.op("mul", (index, ir.const(op.scale)), 32))
        value = terms[0] if terms else None
        for term in terms[1:]:
            value = ir.op("add", (value, term), 32)
        if value is None:
            return ir.const(op.disp)
        return ir.op("add", (value, ir.const(op.disp)), 32) if op.disp else value

    def read(self, op, hint="source"):
        if op.kind == "reg":
            value = self.read_register(op.reg)
            # ESP read as a value (add esp, 8 sets flags from it): a temporary, which the stack's analysis
            # follows as an offset and the flags then read as a stack address no one uses
            # (tools/core/decompiler/stack.py)
            return self.temp(value, hint) if op.reg == "esp" else value
        if op.kind == "imm":
            return ir.const(op.imm & mask(op.bits), op.bits)
        return self.load(self.address(op), op.bits, hint)

    def write(self, op, value):
        if op.kind == "reg":
            self.write_register(op.reg, value)
        elif op.kind == "mem":
            self.emit(ir.Store(self.address(op), ir.trunc(value, op.bits), op.bits))
        else:
            raise Unsupported("a write to an immediate")

    # ---- flags ----

    def set_sz(self, result):
        for statement in ir.flags_of_result(result):
            self.emit(statement)

    def add_flags(self, a, b, carry, result):
        self.emit(ir.SetFlag("cy", ir.op("carry_add", (a, b, carry), 1)))
        self.emit(ir.SetFlag("ov", ir.op("overflow_add", (a, b, carry), 1)))
        self.set_sz(result)

    def sub_flags(self, a, b, borrow, result):
        self.emit(ir.SetFlag("cy", ir.op("carry_sub", (a, b, borrow), 1)))
        self.emit(ir.SetFlag("ov", ir.op("overflow_sub", (a, b, borrow), 1)))
        self.set_sz(result)

    def logic_flags(self, result):
        self.emit(ir.SetFlag("cy", ir.const(0, 1)))
        self.emit(ir.SetFlag("ov", ir.const(0, 1)))
        self.set_sz(result)

    # ---- the stack ----

    def push(self, value):
        value = ir.zext(value, 32)
        if not isinstance(value, (ir.Const, ir.Temp)):
            value = self.temp(value, "pushed")
        sp = self.temp(ir.op("sub", (ir.Reg(ESP), ir.const(4)), 32), "sp")
        self.emit(ir.SetReg(ESP, sp))
        self.emit(ir.Store(ir.Reg(ESP), value, 32))

    def pop(self, hint="popped"):
        value = self.load(ir.Reg(ESP), 32, hint)
        self.emit(ir.SetReg(ESP, ir.op("add", (ir.Reg(ESP), ir.const(4)), 32)))
        return value


def condition(code):
    """The IR condition of an x86 condition code ('e', 'ne', 'b'...), from the flags."""
    from decompiler.function import flag_condition
    if code not in CONDITIONS:
        raise Unsupported(f"condition {code}")
    return flag_condition(CONDITIONS[code])


def lift_data(lifter, instruction):
    """IR for an instruction that only moves data and sets flags; False if it is not one of them."""
    name, ops = instruction.mnemonic, instruction.operands
    emit, read, write = lifter.emit, lifter.read, lifter.write

    if name in ("nop", "int3"):
        return True
    if name == "mov":
        write(ops[0], read(ops[1]))
        return True
    if name in ("movzx", "movsx"):
        value = read(ops[1])
        write(ops[0], (ir.zext if name == "movzx" else ir.sext)(value, ops[0].bits))
        return True
    if name == "lea":
        write(ops[0], lifter.address(ops[1]))
        return True
    if name == "xchg":
        a, b = read(ops[0], "first"), read(ops[1], "second")
        if ops[0].kind == "reg":
            a = lifter.temp(a, "first")
        if ops[1].kind == "reg":
            b = lifter.temp(b, "second")
        write(ops[0], b)
        write(ops[1], a)
        return True

    if name in ("xor", "sub") and ops[0].kind == "reg" and ops[1].kind == "reg" and ops[0].reg == ops[1].reg:
        # xor R, R and sub R, R give 0 whatever R holds: the register is not read
        bits = ops[0].bits
        result = ir.const(0, bits)
        write(ops[0], result)
        emit(ir.SetFlag("cy", ir.const(0, 1)))
        emit(ir.SetFlag("ov", ir.const(0, 1)))
        lifter.set_sz(result)
        return True
    if name in ("add", "adc", "sub", "sbb", "cmp"):
        bits = ops[0].bits
        value = read(ops[0], "value")
        source = ir.zext(read(ops[1]), bits) if ops[1].kind == "imm" else read(ops[1])
        # the carry going in is read before the instruction sets a new one
        carry = lifter.temp(ir.Flag("cy"), "carry_in") if name in ("adc", "sbb") else ir.const(0, 1)
        if name in ("add", "adc"):
            total = ir.op("add", (ir.op("add", (value, source), bits), ir.zext(carry, bits)), bits)
            result = lifter.temp(total, "result")
            lifter.add_flags(value, source, carry, result)
        else:
            total = ir.op("sub", (ir.op("sub", (value, source), bits), ir.zext(carry, bits)), bits)
            result = lifter.temp(total, "result")
            lifter.sub_flags(value, source, carry, result)
        if name != "cmp":
            write(ops[0], result)
        return True
    if name in ("or", "and") and ops[1].kind == "imm"             and (ops[1].imm & mask(ops[0].bits)) == (mask(ops[0].bits) if name == "or" else 0):
        # or R, -1 and and R, 0 give -1 and 0 whatever R holds: R is not read
        result = ir.const(mask(ops[0].bits) if name == "or" else 0, ops[0].bits)
        write(ops[0], result)
        lifter.logic_flags(result)
        return True
    if name in ("and", "or", "xor", "test"):
        bits = ops[0].bits
        value = read(ops[0], "value")
        source = ir.zext(read(ops[1]), bits) if ops[1].kind == "imm" else read(ops[1])
        result = lifter.temp(ir.op("and" if name == "test" else name, (value, source), bits), "result")
        lifter.logic_flags(result)
        if name != "test":
            write(ops[0], result)
        return True
    if name in ("inc", "dec"):
        bits = ops[0].bits
        value = read(ops[0], "value")
        one = ir.const(1, bits)
        result = lifter.temp(ir.op("add" if name == "inc" else "sub", (value, one), bits), "result")
        emit(ir.SetFlag("ov", ir.op("overflow_add" if name == "inc" else "overflow_sub",
                                    (value, one, ir.const(0, 1)), 1)))
        lifter.set_sz(result)
        write(ops[0], result)
        return True
    if name == "neg":
        bits = ops[0].bits
        value = read(ops[0], "value")
        zero = ir.const(0, bits)
        result = lifter.temp(ir.op("sub", (zero, value), bits), "result")
        emit(ir.SetFlag("cy", ir.op("ne", (value, zero), 1)))
        emit(ir.SetFlag("ov", ir.op("overflow_sub", (zero, value, ir.const(0, 1)), 1)))
        lifter.set_sz(result)
        write(ops[0], result)
        return True
    if name == "not":
        bits = ops[0].bits
        write(ops[0], ir.op("not", (read(ops[0], "value"),), bits))
        return True

    if name in ("shl", "sal", "shr", "sar"):
        return shift(lifter, "shl" if name == "sal" else name, ops)

    if name == "imul" and len(ops) in (2, 3):
        bits = ops[0].bits
        a = read(ops[1] if len(ops) == 3 else ops[0], "value")
        b = read(ops[2] if len(ops) == 3 else ops[1], "factor")
        b = ir.zext(b, bits) if b.bits < bits else b
        wide = lifter.temp(ir.op("mul", (ir.sext(a, 64), ir.sext(b, 64)), 64), "product")
        result = lifter.temp(ir.trunc(wide, bits), "result")
        lost = ir.op("ne", (ir.sext(result, 64), wide), 1)
        emit(ir.SetFlag("cy", lost))
        emit(ir.SetFlag("ov", lost))
        lifter.set_sz(result)
        write(ops[0], result)
        return True
    if name in ("imul", "mul") and len(ops) == 1 and ops[0].bits == 32:
        extend = ir.sext if name == "imul" else ir.zext
        factor = read(ops[0], "factor")
        wide = lifter.temp(ir.op("mul", (extend(ir.Reg(EAX), 64), extend(factor, 64)), 64), "product")
        low = lifter.temp(ir.trunc(wide, 32), "low")
        high = lifter.temp(ir.trunc(ir.op("shr", (wide, ir.const(32, 8)), 64), 32), "high")
        lost = ir.op("ne", (ir.sext(low, 64), wide), 1) if name == "imul" else ir.op("ne", (high, ir.const(0)), 1)
        emit(ir.SetFlag("cy", lost))
        emit(ir.SetFlag("ov", lost))
        lifter.set_sz(low)
        emit(ir.SetReg(EAX, low))
        emit(ir.SetReg(EDX, high))
        return True
    if name in ("div", "idiv") and len(ops) == 1 and ops[0].bits == 32:
        # EDX:EAX by a 32-bit value: the quotient to EAX, the remainder to EDX (x86.h: x86_udiv64...)
        divisor = read(ops[0], "divisor")
        kind = "s" if name == "idiv" else "u"
        high, low = ir.Reg(EDX), ir.Reg(EAX)
        quotient = lifter.temp(ir.op(f"helper:x86_{kind}div64", (high, low, divisor), 32), "quotient")
        remainder = lifter.temp(ir.op(f"helper:x86_{kind}rem64", (high, low, divisor), 32), "remainder")
        emit(ir.SetReg(EAX, quotient))
        emit(ir.SetReg(EDX, remainder))
        return True
    if name == "cdq":
        emit(ir.SetReg(EDX, ir.op("sar", (ir.Reg(EAX), ir.const(31, 8)), 32)))
        return True
    if name == "cwde":
        emit(ir.SetReg(EAX, ir.sext(lifter.read_register("ax"), 32)))
        return True
    if name == "cbw":
        lifter.write_register("ax", ir.sext(lifter.read_register("al"), 16))
        return True
    if name.startswith("set") and len(ops) == 1:
        write(ops[0], ir.zext(condition(name[3:]), 8))
        return True

    if name == "push":
        value = read(ops[0], "pushed")
        if ops[0].kind == "imm":
            value = ir.const(ops[0].imm, 32)
        lifter.push(value)
        return True
    if name == "pop":
        write(ops[0], lifter.pop())
        return True
    if name == "leave":
        emit(ir.SetReg(ESP, ir.Reg(EBP)))
        emit(ir.SetReg(EBP, lifter.pop("saved_ebp")))
        return True

    if name.startswith("rep ") or name in ("stosb", "stosw", "stosd", "movsb", "movsw", "movsd"):
        return string(lifter, name)
    return False


def shift(lifter, name, ops):
    """SHL, SHR and SAR by an immediate count or by CL (masked to five bits, as the processor does); a
    count of 0 changes no flag."""
    bits = ops[0].bits
    value = lifter.read(ops[0], "value")
    if len(ops) == 1:
        count = ir.const(1, 8)
    elif ops[1].kind == "imm":
        count = ir.const(ops[1].imm & 31, 8)
    else:
        count = lifter.temp(ir.op("and", (lifter.read_register("cl"), ir.const(31, 8)), 8), "count")
    if isinstance(count, ir.Const) and count.value == 0:
        return True
    result = lifter.temp(ir.op(name, (value, count), bits), "result")
    # CF: the last bit shifted out
    if name == "shl":
        out = ir.op("shr", (value, ir.op("sub", (ir.const(bits, 8), count), 8)), bits)
    else:
        out = ir.op("sar" if name == "sar" else "shr", (value, ir.op("sub", (count, ir.const(1, 8)), 8)), bits)
    carry = ir.trunc(out, 1)
    if name == "shl":
        overflow = ir.op("xor", (ir.bit(result, bits - 1), carry), 1)
    elif name == "shr":
        overflow = ir.bit(value, bits - 1)
    else:
        overflow = ir.const(0, 1)
    flags = [("cy", carry), ("ov", overflow), ("z", ir.op("eq", (result, ir.const(0, bits)), 1)),
             ("s", ir.bit(result, bits - 1))]
    for flag, new in flags:
        if not isinstance(count, ir.Const):
            new = ir.op("select", (ir.op("eq", (count, ir.const(0, 8)), 1), ir.Flag(flag), new), 1)
        lifter.emit(ir.SetFlag(flag, new))
    lifter.write(ops[0], result)
    return True


def string(lifter, name):
    """STOS and MOVS, once or REP: the memory filled or copied as an Effect (x86.h: x86_rep_stos32...),
    EDI (and ESI) moved on past it and ECX left 0."""
    parts = name.split()
    repeat = parts[0] == "rep"
    base = parts[-1]
    if base[:-1] not in ("stos", "movs") or base[-1] not in STRING_BITS:
        raise Unsupported(name)
    bits = STRING_BITS[base[-1]]
    size = bits // 8
    edi, esi, ecx = ir.Reg(EDI), ir.Reg(ESI), ir.Reg(ECX)

    def advance(register, count):
        step = count if size == 1 else ir.op("mul", (count, ir.const(size)), 32)
        lifter.emit(ir.SetReg(register, ir.op("add", (ir.Reg(register), step), 32)))

    if base.startswith("stos"):
        value = lifter.read_register({8: "al", 16: "ax", 32: "eax"}[bits])
        if repeat:
            lifter.emit(ir.Effect(f"x86_rep_stos{bits}", (edi, value, ecx)))
            advance(EDI, ecx)
            lifter.emit(ir.SetReg(ECX, ir.const(0)))
        else:
            lifter.emit(ir.Store(edi, value, bits))
            advance(EDI, ir.const(1))
        return True
    if repeat:
        lifter.emit(ir.Effect(f"x86_rep_movs{bits}", (edi, esi, ecx)))
        advance(EDI, ecx)
        advance(ESI, ecx)
        lifter.emit(ir.SetReg(ECX, ir.const(0)))
    else:
        value = lifter.load(esi, bits, "moved")
        lifter.emit(ir.Store(edi, value, bits))
        advance(EDI, ir.const(1))
        advance(ESI, ir.const(1))
    return True
