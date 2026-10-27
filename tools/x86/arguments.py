# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        arguments.py
Description: the arguments a function takes on the stack, passed in registers ARG0 up
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

The decompiler's passes take a function's inputs and results from its registers (the V60's code passes
nothing on the stack). After the stack's analysis (tools/core/decompiler/stack.py), a function's slots from
offset 4 on are its arguments: the caller pushed them before the call, which pushed the return address,
slot 0. A function takes as many as the highest of those slots it reads or writes says. So:
  - a function copies its arguments from ARG0 + n into slots of its own as it starts (OWN_SLOTS up, in
    place of 4 + 4n, which are its caller's), and works on them, reusing them as locals where the
    original does;
  - at a call, the caller copies the callee's arguments, its slots from where SP stands at the call
    (the marker function.py leaves), into ARG0 up; at a tail call, from the slot above SP.
The ARG registers carry nothing else, so a call that sets them for its callee leaves the caller's own
arguments in its slots.
"""
from v60 import ir

from .function import CALL_FRAME, TAIL_FRAME
from .profile import ARG0, ARGUMENTS

OWN_SLOTS = -0x200000   # where a function keeps its arguments: slots of its own, below any its code makes


class TooMany(Exception):
    """A function that takes more arguments than there are ARG registers."""


class Straddles(Exception):
    """A function that reads or writes bytes of two of its arguments at once."""


def count(function):
    """How many arguments a function takes: up to the highest slot from 4 it reads or writes."""
    highest = None
    for block in function.blocks.values():
        for statement in block.statements + [block.end]:
            offsets = []
            if isinstance(statement, ir.SetStack):
                offsets.append((statement.offset, statement.bits))
            for expression in ir.statement_expressions(statement):
                for node in ir.walk(expression):
                    if isinstance(node, ir.Stack):
                        offsets.append((node.offset, node.bits))
            for offset, bits in offsets:
                if offset >= 4:
                    last = (offset + bits // 8 - 1 - 4) // 4
                    highest = last if highest is None else max(highest, last)
    taken = 0 if highest is None else highest + 1
    if taken > ARGUMENTS:
        raise TooMany(f"{function.name} takes {taken} arguments")
    return taken


def counts(functions):
    """How many arguments each of 'functions' takes: the slots from 4 it reads or writes itself, and the
    ones a call or a tail call hands on from its own arguments. A function that ends by jumping to
    another passes that one's arguments on, its caller's slots above its own (sub_000BF9C0 takes the
    five sub_000A50F0 reads, though it reads one itself); so does a call to a function that takes more
    than the caller pushed. Worked out until nothing changes, which covers recursion."""
    found = {entry: count(f) for entry, f in functions.items()}
    frames = {}
    for entry, f in functions.items():
        frames[entry] = []
        for block in f.blocks.values():
            for position, statement in enumerate(block.statements):
                sp = frame_of(statement, CALL_FRAME)
                if sp is not None:
                    frames[entry].append((sp, block.statements[position + 1].target))
                sp = frame_of(statement, TAIL_FRAME)
                if sp is not None:
                    frames[entry].append((sp + 4, block.end.target))
    changed = True
    while changed:
        changed = False
        for entry in functions:
            taken = found[entry]
            for first, target in frames[entry]:
                for n in range(found.get(target, 0)):
                    offset = first + 4 * n
                    if offset >= 4:
                        taken = max(taken, (offset - 4) // 4 + 1)
            if taken > ARGUMENTS:
                raise TooMany(f"{functions[entry].name} takes {taken} arguments")
            if taken != found[entry]:
                found[entry] = taken
                changed = True
    return found


def frame_of(statement, name):
    """The SP offset a marker says, or None for any other statement."""
    if isinstance(statement, ir.Effect) and statement.name == name:
        slot = statement.args[0]
        if not isinstance(slot, ir.Stack):
            raise ValueError(f"a {name} marker without its slot: {slot}")
        return slot.offset
    return None


def own_slot(offset):
    """The slot of the function's own where an argument's byte at 'offset' (4 up) lives."""
    return OWN_SLOTS + offset - 4


def rewrite(functions, counts):
    """Passes the arguments of 'functions' (entry -> Function, their stacks analysed) in registers, in
    place; 'counts' says how many each callee takes."""
    def placed(statement, origin):
        statement.origin = origin
        return statement

    def own(node):
        # an argument read whole, or a part of it: the part of the whole word, which is the slot the
        # function's start writes (the decompiler takes a slot at two widths for two variables)
        if isinstance(node, ir.Stack) and node.offset >= 4:
            first = node.offset - (node.offset - 4) % 4
            shift = (node.offset - first) * 8
            if shift + node.bits > 32:
                raise Straddles(f"{function.name} reads bytes of two arguments at once")
            whole = ir.Stack(own_slot(first), 32)
            if shift == 0 and node.bits == 32:
                return whole
            value = ir.op("shr", (whole, ir.const(shift, 8)), 32) if shift else whole
            return ir.trunc(value, node.bits)
        return None

    def own_store(statement):
        """A write to an argument, or to a part of it, as a write of the whole word."""
        first = statement.offset - (statement.offset - 4) % 4
        shift = (statement.offset - first) * 8
        if shift + statement.bits > 32:
            raise Straddles(f"{function.name} writes bytes of two arguments at once")
        if shift == 0 and statement.bits == 32:
            return ir.SetStack(own_slot(first), statement.value)
        keep = ~(((1 << statement.bits) - 1) << shift) & 0xFFFFFFFF
        placed = ir.zext(statement.value, 32)
        if shift:
            placed = ir.op("shl", (placed, ir.const(shift, 8)), 32)
        value = ir.op("or", (ir.op("and", (ir.Stack(own_slot(first), 32), ir.const(keep)), 32), placed), 32)
        return ir.SetStack(own_slot(first), value)

    for function in functions.values():
        for block in function.blocks.values():
            statements = []
            for position, statement in enumerate(block.statements):
                origin = getattr(statement, "origin", None)
                sp = frame_of(statement, CALL_FRAME)
                if sp is not None:
                    call = block.statements[position + 1]
                    statements += [placed(ir.SetReg(ARG0 + n, ir.Stack(sp + 4 * n)), origin)
                                   for n in range(counts.get(call.target, 0))]
                    continue
                sp = frame_of(statement, TAIL_FRAME)
                if sp is not None:
                    statements += [placed(ir.SetReg(ARG0 + n, ir.Stack(sp + 4 + 4 * n)), origin)
                                   for n in range(counts.get(block.end.target, 0))]
                    continue
                statements.append(statement)
            for position, statement in enumerate(statements):
                ir.map_statement(statement, own)
                if isinstance(statement, ir.SetStack) and statement.offset >= 4:
                    replaced = own_store(statement)
                    replaced.origin = getattr(statement, "origin", None)
                    statements[position] = replaced
            ir.map_statement(block.end, own)
            block.statements = statements
        taken = counts[function.entry]
        if taken:
            entry = function.blocks[function.entry]
            entry.statements[:0] = [placed(ir.SetStack(own_slot(4 + 4 * n), ir.Reg(ARG0 + n)), function.entry)
                                    for n in range(taken)]
