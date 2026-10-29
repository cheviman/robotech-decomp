# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        function.py
Description: the game's x86 functions as control-flow graphs of IR blocks
Version:     0.3.0
Created:     26-10-2026
Modified:    28-10-2026
Author:      Sebastian Toyos

Takes the functions disassembler.py decodes and lifts every instruction to IR (lift.py for data, here
for control). A block starts at the function's entry, at every target of a branch, a jump or a jump table,
and after anything that branches, jumps or returns. A call is a statement: SP stays where it was across
it, as the decompiler expects (tools/core/decompiler/stack.py), but for a callee that drops its own
arguments ("ret N", stdcall), after which SP is N bytes up. A jump to another function is a tail call;
a jump through a table, a switch over the table's entries.

The x87's stack is a register for each depth (x87.py): a function whose depth is known at every
instruction, which takes nothing from it and leaves nothing on it or one float, and whose calls take and
leave nothing either (but for _ftol2, lifted as the conversion it is) or hand back a float where the
stack is empty, has its floating-point code lifted; the float a function hands back is its st(0) where
it returns, FLOAT0 (decompile.py). The compare idiom "fcom; fnstsw ax; test ah, mask; j(n)e/j(n)p"
becomes a branch on the compare's outcome.

What is not translated yet raises lift.Unsupported: an SSE instruction, an x87 one past those, a call or a
jump through a pointer, a branch on PF other than a compare's.
"""
from decompiler.function import Block, Function
from v60 import ir

from . import disassembler as dis
from . import lift
from . import x87
from .profile import ESP

CALL_FRAME = "x86_call_frame"
TAIL_FRAME = "x86_tail_frame"


class Builder:
    """Lifts the functions of a disassembler.Program."""

    def __init__(self, program):
        self.program = program
        self.dropped = {}
        self.x87 = x87.Depths(program)
        self.ftol = next((entry for entry, (end, name, section) in program.functions.items()
                          if name == x87.FTOL), None)

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
        self.depths = None
        if any(x87.is_x87(instruction.mnemonic) or self.leaves_floats(decoded, instruction)
               for instruction in decoded.instructions.values()):
            self.depths = self.x87.at(entry)
            if self.depths is None or self.x87.effect(entry) not in ((0, 0), (0, 1)):
                raise lift.Unsupported("x87: its stack's depth not known, or values taken or left but one float")
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
                self.state = x87.State()
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
                if self.depths is not None and following not in decoded.instructions \
                        and self.x87.effect(following) != (0, 0):
                    raise lift.Unsupported(f"x87: runs on into {following:08X}, which takes or leaves its values")
                current.end = self.leave(decoded, following)
        # where SP stands at a tail call: the callee's arguments are the slots above it (arguments.py)
        for block in function.blocks.values():
            if isinstance(block.end, ir.TailCall):
                block.statements.append(ir.Effect(TAIL_FRAME, (ir.Load(ir.Reg(ESP), 32),)))
        return function

    def leaves_floats(self, decoded, instruction):
        """Whether an instruction calls or jumps to a function that takes values from the x87's stack or
        leaves them on it: one without x87 code of its own that does has its depths worked out too
        (a float handed on from a call, or a call to _ftol2 of a float a call handed back)."""
        if instruction.flow not in (dis.FLOW_CALL, dis.FLOW_JUMP) or not instruction.targets:
            return False
        target = instruction.targets[0]
        if target in decoded.instructions:
            return False
        effect = self.x87.effect(target)
        return effect is not None and effect != (0, 0)

    def leave(self, decoded, target):
        """The end of a block that goes to 'target': a jump within the function, or a tail call."""
        if target in decoded.instructions:
            return ir.Goto(target)
        if target in self.program.functions:
            return ir.TailCall(target)
        raise lift.Unsupported(f"a jump to {target:08X}, in no function")

    def depth(self, instruction):
        if self.depths is None or instruction.address not in self.depths:
            raise lift.Unsupported(f"x87: {instruction.mnemonic} where its stack's depth is not known")
        return self.depths[instruction.address]

    def lift(self, decoded, block, instruction, position):
        flow = instruction.flow
        if flow == dis.FLOW_NONE:
            lifter = lift.Lifter(prefix=f"t{instruction.address:X}_")
            state = self.state
            try:
                if x87.is_x87(instruction.mnemonic):
                    x87.lift(lifter, instruction, self.depth(instruction), state)
                    handled = True
                elif x87.lift_test(lifter, instruction, state):
                    handled = True
                else:
                    handled = lift.lift_data(lifter, instruction)
                    # what the instruction changed of what a compare left: the flags, AH
                    if any(isinstance(statement, ir.SetFlag) for statement in lifter.statements):
                        state.test = None
                    if any(isinstance(statement, ir.SetReg) and statement.index == 0
                           for statement in lifter.statements):
                        state.status = None
            except x87.Unsupported as problem:
                raise lift.Unsupported(f"x87: {problem}")
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
            condition = x87.branch_condition(code, self.state)
            block.end = ir.Branch(condition if condition is not None else lift.condition(code), target,
                                  instruction.next)
            return
        if flow == dis.FLOW_JUMP:
            target = instruction.targets[0]
            if self.depths is not None and target not in decoded.instructions:
                if target == self.ftol:
                    # "jmp _ftol2": the conversion, and _ftol2's return is this function's
                    lifter = lift.Lifter(prefix=f"t{instruction.address:X}_")
                    x87.lift_ftol(lifter, self.depth(instruction))
                    block.statements.extend(lifter.statements)
                    block.end = ir.Return()
                    return
                # (one that hands back a float hands it back for this function, from an empty stack)
                if self.x87.effect(target) not in ((0, 0), (0, 1)) or self.depth(instruction) != 0:
                    raise lift.Unsupported(f"x87: a jump to {target:08X}, which takes or leaves its values")
            block.end = self.leave(decoded, target)
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
            if self.depths is not None:
                if target == self.ftol:
                    lifter = lift.Lifter(prefix=f"t{instruction.address:X}_")
                    x87.lift_ftol(lifter, self.depth(instruction))
                    block.statements.extend(lifter.statements)
                    self.state.status = self.state.test = None
                    return
                effect = self.x87.effect(target)
                if effect == (0, 1) and self.depth(instruction) != 0:
                    raise lift.Unsupported(f"x87: a call to {target:08X}, which hands back a float, with the stack not empty")
                if effect not in ((0, 0), (0, 1)):
                    raise lift.Unsupported(f"x87: a call to {target:08X}, which takes or leaves its values")
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
