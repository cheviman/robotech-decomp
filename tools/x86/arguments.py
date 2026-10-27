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
  - a function copies its arguments from ARG0 + n into its slots 4 + 4n as it starts, and works on the
    slots, which it may reuse as locals, as the original does;
  - at a call, the caller copies the callee's arguments, its slots from where SP stands at the call
    (the marker function.py leaves), into ARG0 up; at a tail call, from the slot above SP.
The ARG registers carry nothing else, so a call that sets them for its callee leaves the caller's own
arguments in its slots.
"""
from v60 import ir

from .function import CALL_FRAME, TAIL_FRAME
from .profile import ARG0, ARGUMENTS


class TooMany(Exception):
    """A function that takes more arguments than there are ARG registers."""


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


def frame_of(statement, name):
    """The SP offset a marker says, or None for any other statement."""
    if isinstance(statement, ir.Effect) and statement.name == name:
        slot = statement.args[0]
        if not isinstance(slot, ir.Stack):
            raise ValueError(f"a {name} marker without its slot: {slot}")
        return slot.offset
    return None


def rewrite(functions, counts):
    """Passes the arguments of 'functions' (entry -> Function, their stacks analysed) in registers, in
    place; 'counts' says how many each callee takes."""
    def placed(statement, origin):
        statement.origin = origin
        return statement

    for function in functions.values():
        taken = counts[function.entry]
        if taken:
            entry = function.blocks[function.entry]
            entry.statements[:0] = [placed(ir.SetStack(4 + 4 * n, ir.Reg(ARG0 + n)), function.entry)
                                    for n in range(taken)]
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
            block.statements = statements
