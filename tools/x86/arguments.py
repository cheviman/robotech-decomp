# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        arguments.py
Description: the arguments a function takes on the stack, passed in registers ARG0 up
Version:     0.3.0
Created:     26-10-2026
Modified:    29-10-2026
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
arguments in its slots. A function whose stack stays in memory (stack.MEMORY_SP, the guest's g_esp)
takes them in ARG registers too, and lays them out in memory as it starts (in_memory).
"""
from decompiler.stack import MEMORY_SP
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


def counts(functions, outside=None, in_memory=None):
    """How many arguments each of 'functions' takes: the slots from 4 it reads or writes itself, and the
    ones a call or a tail call hands on from its own arguments. A function that ends by jumping to
    another passes that one's arguments on, its caller's slots above its own (sub_000BF9C0 takes the
    five sub_000A50F0 reads, though it reads one itself); so does a call to a function that takes more
    than the caller pushed. Worked out until nothing changes, which covers recursion. 'outside': what
    the functions they call that are not among them take (recompiled.py); 'in_memory': what the ones
    whose stack stays in memory take (recompiled.py too: they read their arguments from memory)."""
    found = dict(outside or {})
    found.update({entry: (in_memory or {}).get(entry, 0) if getattr(f, "memory_stack", False) else count(f)
                  for entry, f in functions.items()})
    frames = {}
    for entry, f in functions.items():
        frames[entry] = []
        if getattr(f, "memory_stack", False):
            continue        # its arguments stay in memory, where its calls find theirs (decompile.py)
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
    return {entry: found[entry] for entry in functions}


def frame_of(statement, name):
    """The SP offset a marker says, or None for any other statement."""
    if isinstance(statement, ir.Effect) and statement.name == name:
        slot = statement.args[0]
        if not isinstance(slot, ir.Stack):
            raise ValueError(f"a {name} marker without its slot: {slot}")
        return slot.offset
    return None


def unhanded(target, handed, counts):
    """The arguments a call of a function that counts them by its callers does not hand it, of the
    ones the function lays out (as many as the most a call hands it): 0, words it never looks at. Left
    unset, the caller's ARG registers would seem to carry its own caller's on to it, and so up every
    caller (2,479 functions out of the build)."""
    return [ir.SetReg(ARG0 + n, ir.const(0)) for n in range(handed, counts.get(target, 0))]


def in_memory(function, counts, sites=None):
    """A function whose stack stays in memory (the guest's, g_esp: stack.MEMORY_SP) takes its arguments
    in ARG registers as the others do, and as it starts lays its frame out in memory as the original's
    caller left it: SP down by the return address's word and theirs, its arguments over the return
    address's place, which it never reads (recompiled.py makes sure); every way out puts SP back. A call
    of its takes its callee's arguments from where it pushed them, a tail call from above its return
    address; a call of one that counts them by its callers, as many as 'sites' says this call hands it
    (more would reach this function's own return address: GameObjectSendMessage's callers)."""
    sp = ir.Reg(MEMORY_SP, 32)
    sites = sites or {}
    taken = counts[function.entry]
    for block in function.blocks.values():
        statements = []
        for position, statement in enumerate(block.statements):
            name = frame_of_any(statement)
            if name is None:
                statements.append(statement)
                continue
            marker = statement.args[0]
            address = marker.address if isinstance(marker, ir.Load) else sp
            target = block.statements[position + 1].target if name == CALL_FRAME else block.end.target
            first = 0 if name == CALL_FRAME else 4
            words = counts.get(target, 0)
            if name == CALL_FRAME:
                words = sites.get(block.statements[position + 1].return_address, words)
            for n in range(words):
                moved = ir.SetReg(ARG0 + n, ir.Load(ir.op("add", (address, ir.const(first + 4 * n)), 32), 32))
                moved.origin = getattr(statement, "origin", None)
                statements.append(moved)
            for zero in unhanded(target, words, counts):
                zero.origin = getattr(statement, "origin", None)
                statements.append(zero)
        if taken and isinstance(block.end, (ir.Return, ir.TailCall)):
            statements.append(ir.SetReg(MEMORY_SP, ir.op("add", (sp, ir.const(4 + 4 * taken)), 32)))
        block.statements = statements
    if taken:
        entry = function.blocks[function.entry]
        frame = [ir.SetReg(MEMORY_SP, ir.op("sub", (sp, ir.const(4 + 4 * taken)), 32))]
        frame += [ir.Store(ir.op("add", (sp, ir.const(4 + 4 * n)), 32), ir.Reg(ARG0 + n), 32) for n in range(taken)]
        for statement in frame:
            statement.origin = function.entry
        entry.statements[:0] = frame


def frame_of_any(statement):
    """The marker's name (CALL_FRAME, TAIL_FRAME) of a marker statement, whatever it holds; else None."""
    if isinstance(statement, ir.Effect) and statement.name in (CALL_FRAME, TAIL_FRAME):
        return statement.name
    return None


def own_slot(offset):
    """The slot of the function's own where an argument's byte at 'offset' (4 up) lives."""
    return OWN_SLOTS + offset - 4


def rewrite(functions, counts, sites=None):
    """Passes the arguments of 'functions' (entry -> Function, their stacks analysed) in registers, in
    place; 'counts' says how many each callee takes, 'sites' how many a call hands one that counts
    them by its callers (a variable argument list: {the call's return address: count})."""
    sites = sites or {}
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
        if getattr(function, "memory_stack", False):
            in_memory(function, counts, sites)
            continue
        for block in function.blocks.values():
            statements = []
            for position, statement in enumerate(block.statements):
                origin = getattr(statement, "origin", None)
                sp = frame_of(statement, CALL_FRAME)
                if sp is not None:
                    call = block.statements[position + 1]
                    taken = sites.get(call.return_address, counts.get(call.target, 0))
                    statements += [placed(ir.SetReg(ARG0 + n, ir.Stack(sp + 4 * n)), origin)
                                   for n in range(taken)]
                    statements += [placed(statement, origin) for statement in unhanded(call.target, taken, counts)]
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
        pass_pushes(function)
        taken = counts[function.entry]
        if taken:
            entry = function.blocks[function.entry]
            entry.statements[:0] = [placed(ir.SetStack(own_slot(4 + 4 * n), ir.Reg(ARG0 + n)), function.entry)
                                    for n in range(taken)]
            read_in_place(function, taken)


def slot_reads(statement):
    return {node.offset for expression in ir.statement_expressions(statement) for node in ir.walk(expression)
            if isinstance(node, ir.Stack)}


def pass_pushes(function):
    """A word pushed for a call that nothing else reads goes into its ARG register where it is pushed,
    when no call comes in between: "push 4; push edx; call" sets arg1 and arg0 there, not two slots the
    call then reads (stack_18 = 4u; arg1_2 = stack_18)."""
    blocks = function.blocks
    # the slots live after each statement: read later before they are written whole
    live_in = {label: set() for label in blocks}
    changed = True
    while changed:
        changed = False
        for label, block in blocks.items():
            live = set().union(*[live_in[successor] for successor in block.successors() if successor in live_in])
            live |= slot_reads(block.end)
            for statement in reversed(block.statements):
                if isinstance(statement, ir.SetStack) and statement.bits == 32:
                    live.discard(statement.offset)
                live |= slot_reads(statement)
            if live != live_in[label]:
                live_in[label] = live
                changed = True
    for label, block in blocks.items():
        statements = block.statements
        live = set().union(*[live_in[successor] for successor in block.successors() if successor in live_in])
        live |= slot_reads(block.end)
        live_after = [None] * len(statements)
        for position in range(len(statements) - 1, -1, -1):
            live_after[position] = set(live)
            statement = statements[position]
            if isinstance(statement, ir.SetStack) and statement.bits == 32:
                live.discard(statement.offset)
            live |= slot_reads(statement)
        dropped = set()
        for position, statement in enumerate(statements):
            if not (isinstance(statement, ir.SetReg) and ARG0 <= statement.index < ARG0 + ARGUMENTS
                    and isinstance(statement.value, ir.Stack) and statement.value.bits == 32
                    and statement.value.offset not in live_after[position]):
                continue
            offset, register = statement.value.offset, statement.index
            for earlier in range(position - 1, -1, -1):
                if earlier in dropped:
                    continue        # the setting of another argument of the call, gone to its push
                found = statements[earlier]
                if isinstance(found, ir.SetStack) and found.offset == offset:
                    if found.bits == 32:
                        replaced = ir.SetReg(register, found.value)
                        replaced.origin = getattr(found, "origin", None)
                        statements[earlier] = replaced
                        dropped.add(position)
                    break
                if isinstance(found, (ir.Call, ir.Effect)) or offset in slot_reads(found) \
                        or (isinstance(found, ir.SetReg) and found.index == register) \
                        or any(isinstance(node, ir.Reg) and node.index == register
                               for expression in ir.statement_expressions(found) for node in ir.walk(expression)):
                    break
        if dropped:
            block.statements = [statement for position, statement in enumerate(statements) if position not in dropped]


def read_in_place(function, taken):
    """An argument the function never changes is read where it came, ARG0 + n, wherever nothing before has
    set ARG0 + n for a call or made a call: its copy into the function's own slot goes when no read of
    it is left (saved_arg0 = arg0, and saved_arg0 read after, is arg0 read)."""
    written = set()
    for block in function.blocks.values():
        for statement in block.statements:
            if isinstance(statement, ir.SetStack) and statement.offset < 0 and \
                    not (isinstance(statement.value, ir.Reg) and statement.value.index == ARG0 + (statement.offset - OWN_SLOTS) // 4):
                written.add(statement.offset)
    kept = [n for n in range(taken) if own_slot(4 + 4 * n) not in written]
    if not kept:
        return
    # where each argument still holds what came (nothing before set it for a call, or called)
    predecessors = {label: [] for label in function.blocks}
    for label, block in function.blocks.items():
        for successor in block.successors():
            predecessors.setdefault(successor, []).append(label)

    def after(block, holding):
        holding = set(holding)
        for statement in block.statements:
            if isinstance(statement, ir.SetReg) and statement.index - ARG0 in holding:
                holding.discard(statement.index - ARG0)
            elif isinstance(statement, (ir.Call, ir.Effect)):
                holding.clear()
        return holding
    start = {label: set(kept) for label in function.blocks}
    changed = True
    while changed:
        changed = False
        for label, block in function.blocks.items():
            # the start holds them all; a block nothing reaches, none; another, what every way in leaves
            holding = set(kept) if label == function.entry or predecessors.get(label) else set()
            for before in predecessors.get(label, []):
                holding &= after(function.blocks[before], start[before])
            if holding != start[label]:
                start[label] = holding
                changed = True
    slots = {own_slot(4 + 4 * n): n for n in kept}
    left = set()

    def rewrite_reads(statement, holding):
        def change(node):
            if isinstance(node, ir.Stack) and node.offset in slots and node.bits == 32:
                if slots[node.offset] in holding:
                    return ir.Reg(ARG0 + slots[node.offset])
                left.add(node.offset)
            return None
        ir.map_statement(statement, change)

    for label, block in function.blocks.items():
        holding = set(start[label])
        for statement in block.statements:
            if not (isinstance(statement, ir.SetStack) and statement.offset in slots):
                rewrite_reads(statement, holding)
            if isinstance(statement, ir.SetReg) and statement.index - ARG0 in holding:
                holding.discard(statement.index - ARG0)
            elif isinstance(statement, (ir.Call, ir.Effect)):
                holding.clear()
        rewrite_reads(block.end, holding)
    # the copies no read needs any more
    entry = function.blocks[function.entry]
    entry.statements = [statement for statement in entry.statements
                        if not (isinstance(statement, ir.SetStack) and statement.offset in slots
                                and statement.offset not in left and isinstance(statement.value, ir.Reg))]
