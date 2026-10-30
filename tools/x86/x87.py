# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        x87.py
Description: how deep the x87's register stack is at each instruction of a function, and which functions
             hand back a value in st(0)
Version:     0.1.0
Created:     28-10-2026
Modified:    30-10-2026
Author:      Sebastian Toyos

The x87 keeps its values on a stack of eight registers, st(0) its top. In compiled C the stack is empty
where a function starts and where it calls another; a function that hands back a float leaves it in
st(0) and nothing else. So the depth at each instruction is known before the code runs, from what each
instruction pushes and pops, and st(i) at an instruction is the value the push at depth - 1 - i made:
the lifter (lift.py) names it by that depth, as a variable of the function's own, not a stack.

A function takes the values it finds on the stack (none in compiled C; the C runtime's helpers, _ftol
and its kin, take st(0) and pop it) and leaves its own where it returns (0, or 1 for a float handed
back): a call goes on with the depth less what the callee takes, plus what it leaves, worked out for
every function together. Where two ways into an instruction come with different depths, or a call goes
to a function whose returns leave different depths, the function has no depth (None): it stays as the
recompiled code has it.
"""
from . import disassembler as dis

# what an instruction pops and then pushes, by Capstone's mnemonic
PUSH = {"fld", "fild", "fld1", "fldz", "fldpi", "fldl2e", "fldl2t", "fldlg2", "fldln2", "fbld"}
POP = {"fstp", "fistp", "fisttp", "fbstp", "fcomp", "fucomp", "ficomp", "faddp", "fsubp", "fsubrp", "fmulp",
       "fdivp", "fdivrp", "ffreep", "fcomip", "fucomip", "fpatan", "fyl2x", "fyl2xp1"}
POP2 = {"fcompp", "fucompp"}
PUSH_AFTER = {"fptan", "fsincos", "fxtract"}       # works on st(0) and pushes one more
SAME = {"fst", "fist", "fadd", "fsub", "fsubr", "fmul", "fdiv", "fdivr", "fiadd", "fisub", "fisubr", "fimul",
        "fidiv", "fidivr", "fcom", "fucom", "ficom", "fcomi", "fucomi", "fxch", "fchs", "fabs", "fsqrt", "fsin",
        "fcos", "frndint", "fscale", "fprem", "fprem1", "f2xm1", "ftst", "fxam", "fnstsw", "fstsw", "fnstcw",
        "fstcw", "fldcw", "fnclex", "fclex", "fwait", "wait", "fnop", "ffree", "fnstenv", "fldenv"}
DEPTH = 8

# The C runtime's x87 helpers (MSVC's "intrinsics"): they take their arguments from the stack and hand
# their result back in st(0), or in eax for _ftol2, and jump about in code they share, which the walk
# does not follow; what each takes and leaves is the C runtime's contract.
HELPERS = {"crt_ftol2": (1, 0), "crt_CIacos": (1, 1), "crt_CIasin": (1, 1), "crt_CIpow_default": (2, 1),
           "crt_CIfmod": (2, 1)}


def change(mnemonic):
    """How an instruction moves the depth; None for one that leaves no depth known (fninit, the
    explicit stack moves)."""
    if mnemonic in PUSH or mnemonic in PUSH_AFTER:
        return 1
    if mnemonic in POP:
        return -1
    if mnemonic in POP2:
        return -2
    if mnemonic in SAME or not mnemonic.startswith("f"):
        return 0
    return None


def is_x87(mnemonic):
    return mnemonic.startswith("f") and change(mnemonic) is not None or mnemonic in ("fninit", "fdecstp",
                                                                                   "fincstp")


class Depths:
    """The x87's depth at each instruction of the program's functions, and what each function takes from
    the stack and leaves on it."""

    def __init__(self, program):
        self.program = program
        self.effects = {}
        self._busy = set()

    def effect(self, entry):
        """(the values a function takes from the stack, the depth it leaves where it returns), or None when
        its returns differ or it has none known. A function in a cycle of calls being worked out is taken
        to take none and leave none, as compiled C does."""
        if entry in self.effects:
            return self.effects[entry]
        if entry in self._busy:
            return (0, 0)
        if entry not in self.program.functions:
            return None
        named = HELPERS.get(self.program.functions[entry][1])
        if named is not None:
            self.effects[entry] = named
            return named
        self._busy.add(entry)
        result = None
        try:
            decoded = self.program.function(entry)
            for takes in range(DEPTH):
                found = self.walk(decoded, takes)
                if found is not None:
                    ends = found[1]
                    if len(ends) <= 1:
                        result = (takes, ends.pop() if ends else 0)
                    break
        except Exception:
            result = None
        finally:
            self._busy.discard(entry)
        self.effects[entry] = result
        return result

    def returned(self, entry):
        """The depth a function leaves where it returns, when it takes nothing; None otherwise."""
        found = self.effect(entry)
        return found[1] if found is not None and found[0] == 0 else None

    def at(self, entry):
        """{address: depth before the instruction} of a function that takes nothing, or None when it has no
        depth."""
        found = self.walk(self.program.function(entry), 0)
        return None if found is None else found[0]

    def walk(self, decoded, takes):
        """({address: depth before it}, {depths at its returns}) starting with 'takes' values on the stack,
        or None when the depth goes under 0 or two ways differ."""
        depth = {decoded.entry: takes}
        ends = set()
        work = [decoded.entry]
        while work:
            address = work.pop()
            instruction = decoded.instructions.get(address)
            if instruction is None:
                return None
            moved = change(instruction.mnemonic)
            if moved is None:
                return None
            after = depth[address] + moved
            if instruction.flow == dis.FLOW_CALL:
                callee = self.effect(instruction.targets[0]) if instruction.targets else (0, 0)
                if callee is None or depth[address] < callee[0]:
                    return None
                after += callee[1] - callee[0]
            if not 0 <= after <= DEPTH:
                return None
            if instruction.flow in (dis.FLOW_RETURN, dis.FLOW_STOP):
                ends.add(after)
                continue
            following = []
            if instruction.flow in (dis.FLOW_NONE, dis.FLOW_CALL, dis.FLOW_BRANCH):
                following.append(instruction.next)
            if instruction.flow in (dis.FLOW_BRANCH, dis.FLOW_JUMP, dis.FLOW_COMPUTED):
                following.extend(instruction.targets)
            for target in following:
                if target not in decoded.instructions:
                    # a tail call: the callee takes what is on the stack
                    callee = self.effect(target)
                    if callee is None or callee[0] != after:
                        return None
                    ends.add(callee[1])
                    continue
                if target in depth:
                    if depth[target] != after:
                        return None
                    continue
                depth[target] = after
                work.append(target)
        return depth, ends


# ---- the instructions as IR ----

from v60 import ir                                   # noqa: E402
from decompiler import floats                        # noqa: E402

from .profile import FLOAT0                           # noqa: E402

FTOL = "crt_ftol2"        # the C runtime's float to integer, by truncation: lifted as the conversion it is
ARITHMETIC = {"fadd": ("f.add", False), "fsub": ("f.sub", False), "fsubr": ("f.sub", True),
              "fmul": ("f.mul", False), "fdiv": ("f.div", False), "fdivr": ("f.div", True)}
COMPARES = {"fcom", "fcomp", "fcompp", "fucom", "fucomp", "fucompp", "ficom", "ficomp", "ftst"}
# the condition bits of AH after fnstsw, for each outcome of a compare: C0 (bit 0), C2 (bit 2), C3 (bit 6)
AH_BITS = {"G": 0x00, "L": 0x01, "E": 0x40, "U": 0x45}


class Unsupported(Exception):
    """An x87 instruction or form the lifter does not translate."""


class State:
    """What a block's instructions have left that a later one reads: the values the last compare set
    against each other, the compare whose condition bits AH holds (fnstsw ax), and the outcomes the
    flags of "test ah, mask" stand for."""

    def __init__(self):
        self.compare = None      # (a, b)
        self.status = None       # (a, b)
        self.test = None         # (a, b, outcomes when ZF is set, outcomes when PF is set)


def register(depth, i):
    """The register of st(i) where the stack holds 'depth' values."""
    if not 0 <= i < depth:
        raise Unsupported(f"st({i}) of {depth}")
    return FLOAT0 + depth - 1 - i


def st(depth, i):
    return ir.Reg(register(depth, i), 64)


def st_index(op):
    if op.kind != "reg" or not op.reg.startswith("st"):
        raise Unsupported(f"operand {op.reg}")
    return int(op.reg[3]) if len(op.reg) > 2 else 0


def memory_value(lifter, op, integer=False):
    """A memory operand as a floating-point value: a float or a double, or an integer made a double."""
    if op.kind != "mem":
        raise Unsupported("a register for a memory operand")
    if integer:
        if op.bits not in (16, 32, 64):
            raise Unsupported(f"an integer of {op.bits} bits")
        loaded = lifter.load(lifter.address(op), op.bits, "integer")
        return ir.op("f.int", (loaded, ir.const(op.bits, 8)), 64)
    if op.bits not in (32, 64):
        raise Unsupported(f"a floating-point value of {op.bits} bits")
    if READ_ONLY is not None and op.base is None and op.index is None and op.segment is None:
        bits = READ_ONLY(op.disp & 0xFFFFFFFF, op.bits)
        if bits is not None:
            # a constant of the program's: its value, as FLD loads it (a finite one, which FLD leaves as it is)
            return ir.op("f.const32" if op.bits == 32 else "f.const64", (ir.const(bits, op.bits),), 64)
    loaded = lifter.load(lifter.address(op), op.bits, "float")
    return ir.op("f.from32" if op.bits == 32 else "f.from64", (loaded,), 64)


READ_ONLY = None   # (address, bits) -> the bits of the finite constant there in memory nothing writes (function.py)


def outcomes_where(mask, test):
    """The compare's outcomes for which 'test' holds of AH & mask."""
    return "".join(outcome for outcome, bits in AH_BITS.items() if test(bits & mask))


def even(value):
    return bin(value & 0xFF).count("1") % 2 == 0


def lift(lifter, instruction, depth, state):
    """IR for an x87 instruction where the stack holds 'depth' values before it."""
    name, ops = instruction.mnemonic, instruction.operands
    emit = lifter.emit

    def set_st(i, value, at=depth):
        emit(ir.SetReg(register(at, i), value))

    if name in ("fwait", "wait", "fnop"):
        return
    if name == "fld":
        if ops[0].kind == "reg":
            set_st(0, st(depth, st_index(ops[0])), depth + 1)
        else:
            set_st(0, memory_value(lifter, ops[0]), depth + 1)
        return
    if name == "fild":
        set_st(0, memory_value(lifter, ops[0], integer=True), depth + 1)
        return
    if name in ("fld1", "fldz"):
        set_st(0, ir.op("f.const32", (ir.const(0x3F800000 if name == "fld1" else 0),), 64), depth + 1)
        return
    if name in ("fst", "fstp"):
        if ops[0].kind == "reg":
            i = st_index(ops[0])
            if i:
                set_st(i, st(depth, 0))
            return
        if ops[0].bits not in (32, 64):
            raise Unsupported(f"{name} of {ops[0].bits} bits")
        kind = "f.bits32" if ops[0].bits == 32 else "f.bits64"
        emit(ir.Store(lifter.address(ops[0]), ir.op(kind, (st(depth, 0),), ops[0].bits), ops[0].bits))
        return
    if name in ("fist", "fistp"):
        if ops[0].kind != "mem" or ops[0].bits not in (16, 32, 64):
            raise Unsupported(f"{name} {instruction.op_str}")
        converted = ir.op("f.toint:x87_fist", (st(depth, 0), ir.const(ops[0].bits)), 64)
        emit(ir.Store(lifter.address(ops[0]), ir.trunc(converted, ops[0].bits), ops[0].bits))
        return
    base = name[:-1] if name.endswith("p") and name[:-1] in ARITHMETIC else name
    integer = base.startswith("fi") and "f" + base[2:] in ARITHMETIC
    if integer:
        base = "f" + base[2:]
    if base in ARITHMETIC:
        operator, reverse = ARITHMETIC[base]
        pops = name.endswith("p")

        def combine(dst, src):
            return ir.op(operator, (src, dst) if reverse else (dst, src), 64)
        if ops and ops[0].kind == "mem":
            set_st(0, combine(st(depth, 0), memory_value(lifter, ops[0], integer)))
        elif len(ops) >= 2:
            di, si = st_index(ops[0]), st_index(ops[1])
            set_st(di, combine(st(depth, di), st(depth, si)))
        elif len(ops) == 1:
            si = st_index(ops[0])
            if pops:
                set_st(si, combine(st(depth, si), st(depth, 0)))
            else:
                set_st(0, combine(st(depth, 0), st(depth, si)))
        else:
            set_st(1, combine(st(depth, 1), st(depth, 0)))
        return
    if name in ("fchs", "fabs", "fsqrt"):
        operator = {"fchs": "f.neg", "fabs": "f.abs", "fsqrt": "f.sqrt"}[name]
        set_st(0, ir.op(operator, (st(depth, 0),), 64))
        return
    if name in ("fsin", "fcos"):
        set_st(0, ir.op("f.helper:x87_" + name[1:], (st(depth, 0),), 64))
        return
    if name == "fpatan":
        set_st(1, ir.op("f.helper:atan2", (st(depth, 1), st(depth, 0)), 64))
        return
    if name == "fxch":
        i = st_index(ops[-1]) if ops else 1
        top = lifter.temp(st(depth, 0), "swapped")
        other = lifter.temp(st(depth, i), "swapped")
        set_st(0, other)
        set_st(i, top)
        return
    if name in COMPARES:
        if name == "ftst":
            source = ir.op("f.const32", (ir.const(0),), 64)
        elif ops and ops[0].kind == "mem":
            source = memory_value(lifter, ops[0], name.startswith("fi"))
        elif ops:
            source = st(depth, st_index(ops[-1]))
        else:
            source = st(depth, 1)
        # held where a later branch reads them, as Lifter.operand holds the operands of a cmp
        state.compare = (lifter.temp(st(depth, 0), "compared"), lifter.temp(source, "against"))
        return
    if name == "fnstsw":
        if not ops or ops[0].kind != "reg" or ops[0].reg != "ax" or state.compare is None:
            raise Unsupported(f"fnstsw {instruction.op_str}")
        a, b = state.compare
        word = ir.op("f.toint:x87_status", (a, b, ir.const(depth)), 64)
        lifter.write_register("ax", ir.trunc(word, 16))
        state.status = state.compare
        return
    raise Unsupported(f"{name} {instruction.op_str}")


def lift_test(lifter, instruction, state):
    """"test ah, mask" on the condition bits of a compare (after fnstsw ax): the flags it sets, each a test
    of the compare's outcome; True when it was that."""
    ops = instruction.operands
    if instruction.mnemonic != "test" or state.status is None or len(ops) != 2 or ops[0].kind != "reg" \
            or ops[0].reg != "ah" or ops[1].kind != "imm" or ops[1].imm & 0xB8:
        return False
    a, b = state.status
    mask = ops[1].imm & 0xFF
    zero = outcomes_where(mask, lambda bits: bits == 0)
    parity = outcomes_where(mask, even)
    lifter.emit(ir.SetFlag("z", floats.compare(zero, a, b)))
    for flag in ("s", "ov", "cy"):
        lifter.emit(ir.SetFlag(flag, ir.const(0, 1)))
    state.test = (a, b, zero, parity)
    return True


def branch_condition(code, state):
    """The condition of "j<code>" on the flags of a compare's test, or None when they are not that."""
    if state.test is None or code not in ("e", "ne", "p", "np"):
        return None
    a, b, zero, parity = state.test
    outcomes = zero if code in ("e", "ne") else parity
    if code in ("ne", "np"):
        outcomes = "".join(outcome for outcome in floats.OUTCOMES if outcome not in outcomes)
    return floats.compare(outcomes, a, b)


def lift_ftol(lifter, depth):
    """A call of the C runtime's _ftol2: st(0) truncated to a 64-bit integer in EDX:EAX, popped."""
    converted = lifter.temp(ir.op("f.toint:x87_ftol", (st(depth, 0),), 64), "integer")
    lifter.emit(ir.SetReg(0, ir.trunc(converted, 32)))
    lifter.emit(ir.SetReg(2, ir.trunc(ir.op("shr", (converted, ir.const(32, 8)), 64), 32)))


# The C runtime's x87 helpers the C calls by their contract (recompiled.CONTRACTS): x86.h's expression for
# each, which hands the values to the recompiled helper on the recompiled code's stack
CRT_HELPERS = {"crt_CIacos": "x87_CIacos", "crt_CIasin": "x87_CIasin", "crt_CIfmod": "x87_CIfmod"}


def lift_crt(lifter, name, takes, depth, return_address):
    """A call of one of the C runtime's x87 helpers, where the stack holds 'depth' values: the 'takes' on
    its top are its arguments, the deepest first, and its result is st(0) after it, as an expression of
    x86.h's (x87_CIacos(return address, x)), the return address the original's call pushes."""
    args = (ir.const(return_address),) + tuple(st(depth, i) for i in reversed(range(takes)))
    lifter.emit(ir.SetReg(register(depth - takes + 1, 0), ir.op("f.helper:" + CRT_HELPERS[name], args, 64)))
