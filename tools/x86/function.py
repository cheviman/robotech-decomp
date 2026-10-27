# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        function.py
Description: the game's x86 functions as control-flow graphs of IR blocks
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

Takes the functions disassembler.py decodes and lifts every instruction to IR (lift.py for data, here
for control). A block starts at the function's entry, at every target of a branch, a jump or a jump table,
and after anything that branches, jumps or returns. A call is a statement: SP stays where it was across
it, as the decompiler expects (tools/core/decompiler/stack.py), but for a callee that drops its own
arguments ("ret N", stdcall), after which SP is N bytes up. A jump to another function is a tail call;
a jump through a table, a switch over the table's entries.

What is not translated yet raises lift.Unsupported: an x87 or SSE instruction, a call or a jump through
a pointer, a branch on PF.
"""
from decompiler.function import Block, Function
from v60 import ir

from . import disassembler as dis
from . import lift
from .profile import ESP

CALL_FRAME = "x86_call_frame"
TAIL_FRAME = "x86_tail_frame"


class Builder:
    """Lifts the functions of a disassembler.Program."""

    def __init__(self, program):
        self.program = program
        self.dropped = {}

    def drops(self, entry):
        """The bytes of arguments a function drops when it returns (its "ret N"); None for no function."""
        if entry not in self.program.functions:
            return None
        if entry not in self.dropped:
            found = {instruction.operands[0].imm if instruction.operands else 0
                     for instruction in self.program.function(entry).instructions.values()
                     if instruction.flow == dis.FLOW_RETURN}
            self.dropped[entry] = found.pop() if len(found) == 1 else (0 if not found else None)
        return self.dropped[entry]

    def leaders(self, function):
        found = {function.entry}
        for instruction in function.instructions.values():
            for target in instruction.targets:
                if instruction.flow != dis.FLOW_CALL and function.entry <= target < function.end:
                    found.add(target)
            if instruction.flow in (dis.FLOW_BRANCH, dis.FLOW_JUMP, dis.FLOW_COMPUTED, dis.FLOW_RETURN,
                                    dis.FLOW_STOP):
                found.add(instruction.next)
        return found & set(function.instructions)

    def build(self, entry):
        decoded = self.program.function(entry)
        function = Function(entry, decoded.name)
        function.drops = self.drops(entry)
        if function.drops is None:
            raise lift.Unsupported("returns that drop different amounts")
        leaders = self.leaders(decoded)
        order = list(decoded.instructions)
        current = None
        for position, address in enumerate(order):
            instruction = decoded.instructions[address]
            if current is not None and address in leaders:
                if current.end is None:
                    current.end = ir.Goto(address)
                current = None
            if current is None:
                current = Block(address)
                function.blocks[address] = current
            current.addresses.append(address)
            before = len(current.statements)
            self.lift(decoded, current, instruction, position)
            # where each statement comes from: symbols.txt names a local by the instruction that writes it
            for statement in current.statements[before:]:
                statement.origin = address
            if current.end is not None and not hasattr(current.end, "origin"):
                current.end.origin = address
            following = instruction.next
            if current.end is None and (position + 1 >= len(order) or order[position + 1] != following):
                current.end = self.leave(decoded, following)
        # where SP stands at a tail call: the callee's arguments are the slots above it (arguments.py)
        for block in function.blocks.values():
            if isinstance(block.end, ir.TailCall):
                block.statements.append(ir.Effect(TAIL_FRAME, (ir.Load(ir.Reg(ESP), 32),)))
        return function

    def leave(self, decoded, target):
        """The end of a block that goes to 'target': a jump within the function, or a tail call."""
        if target in decoded.instructions:
            return ir.Goto(target)
        if target in self.program.functions:
            return ir.TailCall(target)
        raise lift.Unsupported(f"a jump to {target:08X}, in no function")

    def lift(self, decoded, block, instruction, position):
        flow = instruction.flow
        if flow == dis.FLOW_NONE:
            lifter = lift.Lifter(prefix=f"t{instruction.address:X}_")
            try:
                handled = lift.lift_data(lifter, instruction)
            except (IndexError, KeyError) as problem:
                raise lift.Unsupported(f"{instruction.mnemonic} {instruction.op_str}: {problem}")
            if not handled:
                raise lift.Unsupported(f"{instruction.mnemonic} {instruction.op_str}")
            block.statements.extend(lifter.statements)
            return
        if flow == dis.FLOW_BRANCH:
            code = instruction.mnemonic[1:]
            target = instruction.targets[0]
            if target not in decoded.instructions:
                raise lift.Unsupported(f"a branch out of the function, to {target:08X}")
            block.end = ir.Branch(lift.condition(code), target, instruction.next)
            return
        if flow == dis.FLOW_JUMP:
            block.end = self.leave(decoded, instruction.targets[0])
            return
        if flow == dis.FLOW_COMPUTED:
            if instruction.table is None:
                raise lift.Unsupported(f"jmp {instruction.op_str}")
            lifter = lift.Lifter(prefix=f"t{instruction.address:X}_")
            address = lifter.read(instruction.operands[0], "case")
            block.statements.extend(lifter.statements)
            block.end = ir.Switch(address, {target: target for target in instruction.targets})
            return
        if flow == dis.FLOW_CALL:
            if not instruction.targets:
                raise lift.Unsupported(f"call {instruction.op_str}")
            target = instruction.targets[0]
            drops = self.drops(target)
            if drops is None:
                raise lift.Unsupported(f"a call to {target:08X}, which drops different amounts or is no function")
            # where SP stands at the call, which the stack's analysis turns into the slot it points at: the
            # first argument (arguments.py reads it and takes the marker away)
            block.statements.append(ir.Effect(CALL_FRAME, (ir.Load(ir.Reg(ESP), 32),)))
            block.statements.append(ir.Call(target=target, return_address=instruction.next))
            if drops:
                block.statements.append(ir.SetReg(ESP, ir.op("add", (ir.Reg(ESP), ir.const(drops)), 32)))
            return
        if flow == dis.FLOW_RETURN:
            block.end = ir.Return()
            return
        if flow == dis.FLOW_STOP:
            block.end = ir.Return()
            return
        raise lift.Unsupported(instruction.mnemonic)
