# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        recompiled.py
Description: what a function left recompiled reads, writes and takes, as the decompiled C that calls it sees it
Version:     0.1.0
Created:     27-10-2026
Modified:    27-10-2026
Author:      Sebastian Toyos

The decompiled C calls the functions that stay recompiled (the x87's, the ones that call through a
pointer, the XDK's...) through the guest's stack and the register globals, as the recompiled code calls
them (decompile.py). For the decompiler's data flow such a call needs what it works out for its own
functions: the parts of the registers the function reads before writing them, the ones it may write and
the ones it writes on every way back, and how many arguments it takes from the stack. The game passes
values in registers of the compiler's choosing between its own functions (ESI, EDI, EBX), so none of that
is assumed: it is read from the function's machine code, followed an instruction at a time with ESP, EBP
as a frame, and the registers it saves and puts back.

Each part of a register (bits 0-7, 8-15, 16-31, as the data flow's variables) is as the caller left it
(ORIG), written (NEW), or either, by the way taken (MAYBE). A part read while it may hold the caller's
value is an input. "push esi" with ESI as the caller left it saves it, and "pop esi" from that slot gives
it back: a function that saves and restores a register does not write it. ESP is an offset from where it
stood at the function's start, or from where an "and esp, -16" left it (a frame aligned for the x87's
doubles, left by "mov esp, ebp"). A stack access from offset 4 on, through ESP or the frame EBP holds,
reads an argument; one that takes the address of an argument (a variable argument list, a structure
passed whole) leaves the count to the caller: as many as it drops after the call (escapes).

A call takes its callee's summary. A call through a pointer takes the compiler's convention for code it
cannot see (ECX and EDX in, EAX, ECX and EDX written) and, the game's C being C, drops nothing: its caller
drops the arguments when it likes ("add esp, 8" or "pop ecx", a few instructions on). When the function
does not come out even that way, it is followed again with each such call dropping what was pushed for it
(stdcall, as the kernel's functions are). A jump into another function's code that is not a call of it
(the tail of memmove, the x87 control word put back) is followed as this function's own.

A function is not known, and the decompiled code does not call it, when ESP cannot be followed (it moves
by a value, as _chkstk's does), when it reads its return address, when it jumps through a pointer, or
when it calls a function not known.
"""
import bisect
import os
import re

from . import disassembler as dis
from .profile import EAX, EBP, ECX, EDX, ESP

ORIG, NEW, MAYBE = 0, 1, 2
FULL_NAMES = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")
PARTS_OF = {}       # Capstone's register name -> (register, its parts)
for _index, _name in enumerate(FULL_NAMES):
    PARTS_OF[_name] = (_index, (0, 1, 2))
    PARTS_OF[_name[1:]] = (_index, (0, 1))
    if _index < 4:
        PARTS_OF[_name[1] + "l"] = (_index, (0,))
        PARTS_OF[_name[1] + "h"] = (_index, (1,))
ALL_PARTS = frozenset((register, part) for register in range(8) if register != ESP for part in range(3))
UNSEEN_CALLS_READ = frozenset((register, part) for register in (ECX, EDX) for part in range(3))
UNSEEN_CALLS_WRITE = frozenset((register, part) for register in (EAX, ECX, EDX) for part in range(3))
KERNEL_THUNKS = (0x0018EA40, 0x0018EA40 + 4 * 512)   # the XBE's table of the kernel's functions
# the bytes of arguments each of the kernel's functions drops, by its ordinal: xboxrecomp's
# stdcall_args_for_ordinal, which its kernel bridges keep the stack even by
KERNEL_BRIDGE = os.path.join(dis.REPO, "..", "xboxrecomp", "src", "kernel", "kernel_bridge.c")


def kernel_drops():
    if not os.path.exists(KERNEL_BRIDGE):
        return {}
    text = open(KERNEL_BRIDGE, encoding="utf-8", errors="replace").read()
    start = text.find("static int stdcall_args_for_ordinal")
    body = text[start:text.find("\n}", start)] if start >= 0 else ""
    return {int(ordinal): int(count) for ordinal, count in re.findall(r"case\s+(\d+):\s*return\s+(\d+);", body)}
# the ways a function is followed, in turn, until it comes out even: what a call through a pointer drops
# (by the call: nothing when an "add esp" or a "pop" follows before the next jump, else what was pushed
# for it; nothing; the arguments pushed for it; those and the registers pushed since the last call, which
# may be arguments too), and a call of the kernel's not in xboxrecomp's table (the arguments pushed; with
# the registers)
MODES = (("site", "pushed"), ("cdecl", "pushed"), ("pushed", "pushed_all"), ("pushed_all", "pushed_all"))
PUSHED = -1     # a slot of the saved ones that holds something this function pushed, not a register


class NotKnown(Exception):
    pass


class Summary:
    def __init__(self, inputs=frozenset(), writes=frozenset(), always=ALL_PARTS, arguments=0, drops=0,
                 escapes=False, known=True, why=""):
        self.inputs = frozenset(inputs)     # (register, part) read while it may hold the caller's value
        self.writes = frozenset(writes)     # written on some way back
        self.always = frozenset(always)     # written on every way back
        self.arguments = arguments          # the words of arguments it reads from the stack itself
        self.drops = drops                  # the bytes of them it drops when it returns ("ret N")
        self.escapes = escapes              # takes the address of its arguments: its callers say how many
        self.known = known
        self.why = why

    def key(self):
        return (self.inputs, self.writes, self.always, self.arguments, self.drops, self.escapes, self.known)


class State:
    """ESP as (base, offset): base 0 the function's start, another the address of the "and esp" that
    aligned it (None: not known); the frame EBP holds, the same way; each register part's state; the
    slots holding a register as the caller left it {(base, offset): register}; the bytes pushed since the
    last call, without the registers saved and with them (the arguments of the next call); the constants
    pushed and the one EAX holds ({slot or "eax": value}: what _chkstk and __SEH_prolog are handed)."""
    __slots__ = ("esp", "frame", "status", "saved", "pushed", "pushed_all", "constants")

    def __init__(self, esp, frame, status, saved, pushed, pushed_all, constants):
        self.esp, self.frame, self.status, self.saved = esp, frame, status, saved
        self.pushed, self.pushed_all, self.constants = pushed, pushed_all, constants

    def copy(self):
        return State(self.esp, self.frame, list(self.status), dict(self.saved), self.pushed, self.pushed_all,
                     dict(self.constants))

    def merged(self, other):
        status = [a if a == b else MAYBE for a, b in zip(self.status, other.status)]
        saved = {slot: register for slot, register in self.saved.items() if other.saved.get(slot) == register}
        constants = {key: value for key, value in self.constants.items() if other.constants.get(key) == value}
        return State(self.esp if self.esp == other.esp else None, self.frame if self.frame == other.frame else None,
                     status, saved, self.pushed if self.pushed == other.pushed else None,
                     self.pushed_all if self.pushed_all == other.pushed_all else None, constants)

    def same(self, other):
        return (self.esp, self.frame, self.status, self.saved, self.pushed, self.pushed_all, self.constants) == \
            (other.esp, other.frame, other.status, other.saved, other.pushed, other.pushed_all, other.constants)

    def forget(self, base, low, high):
        """The slots from 'low' up to 'high' of 'base' were written."""
        for slot in [slot for slot in self.saved if slot[0] == base and low < slot[1] + 4 and slot[1] < high]:
            del self.saved[slot]
        for slot in [slot for slot in self.constants if slot != "eax" and slot[0] == base
                     and low < slot[1] + 4 and slot[1] < high]:
            del self.constants[slot]


def signed(value):
    return value - (1 << 32) if value & 0x80000000 else value


def restored(held, register):
    """The state of a register popped from a slot that holds 'held': as the caller left it if it saved
    it there, written if this function pushed something else, either when the slot is not known (it
    may be put back from a place this does not follow: the decompiled caller then hands its value in)."""
    if held == register:
        return ORIG
    return NEW if held is not None else MAYBE


def moved(position, amount):
    return None if position is None else (position[0], position[1] + amount)


class Summaries:
    """The summaries of a program's functions (disassembler.Program), worked out together until none
    changes: a function's depends on its callees'. 'targets': {call site: functions a run saw it reach}
    (analysis/icall_sites.json), which say what a call through a pointer drops."""

    def __init__(self, program, targets=None):
        self.program = program
        self.targets = targets or {}
        self.found = {}
        self.callees = {}
        self.entries = sorted(program.functions)
        self.fragments = {}
        self.kernel = kernel_drops()

    def fragment(self, address):
        """Code no function's bounds hold (memmove's tails, past where the disassembler ends it), decoded
        from 'address' up to the next function."""
        if address not in self.fragments:
            position = bisect.bisect_right(self.entries, address)
            end = self.entries[position] if position < len(self.entries) else address + 0x1000
            listed = list(self.program.md.disasm(self.program.read(address, end - address) or b"", address))
            code = dis.Function(address, end, "fragment")
            for n, insn in enumerate(listed):
                instruction = self.program.convert(insn)
                if instruction.flow == dis.FLOW_COMPUTED and instruction.operands[0].kind == "mem":
                    self.program.jump_table(instruction, listed[:n], code)
                code.instructions[instruction.address] = instruction
            self.fragments[address] = code
        return self.fragments[address]

    def containing(self, address):
        """The function whose code holds 'address' (not at its start), or None."""
        position = bisect.bisect_right(self.entries, address) - 1
        if position < 0:
            return None
        entry = self.entries[position]
        end = self.program.functions[entry][0]
        if entry < address < end and address in self.program.function(entry).instructions:
            return entry
        return None

    def compute(self, entries):
        """Summaries of 'entries' and everything they call, in self.found."""
        needed, pending = set(), list(entries)
        owners = {}
        while pending:
            entry = pending.pop()
            if entry in needed or entry not in self.program.functions:
                continue
            needed.add(entry)
            self.callees[entry], owners[entry] = self.called(entry)
            pending.extend(self.callees[entry] | owners[entry])
        # a function that runs another's code as its own depends on what that code calls
        changed = True
        while changed:
            changed = False
            for entry in needed:
                for owner in owners[entry]:
                    more = (self.callees.get(owner, set()) | {owner}) - self.callees[entry] - {entry}
                    if more:
                        self.callees[entry] |= more
                        changed = True
        callers = {entry: set() for entry in needed}
        for entry in needed:
            for callee in self.callees[entry]:
                if callee in callers:
                    callers[callee].add(entry)
        for entry in needed:
            self.found.setdefault(entry, Summary(drops=self.ret_drops(entry)))
        work = sorted(needed)
        queued = set(work)
        while work:
            entry = work.pop()
            queued.discard(entry)
            new = self.scan(entry)
            if new.key() != self.found[entry].key():
                self.found[entry] = new
                for caller in callers[entry]:
                    if caller not in queued:
                        queued.add(caller)
                        work.append(caller)
        return {entry: self.found[entry] for entry in entries if entry in self.found}

    def called(self, entry):
        """The functions a function calls or jumps to, and the ones whose code it may run as its own."""
        decoded = self.program.function(entry)
        found, owners = set(), set()
        for instruction in decoded.instructions.values():
            if instruction.flow == dis.FLOW_CALL and not instruction.targets:
                # what a run saw a call through a pointer reach says what it drops and reads
                found |= {target for target in self.targets.get(instruction.address, ())
                          if target in self.program.functions}
            places = list(instruction.targets)
            if instruction.flow in (dis.FLOW_NONE, dis.FLOW_CALL, dis.FLOW_BRANCH):
                places.append(instruction.next)
            for place in places:
                if place in decoded.instructions and instruction.flow != dis.FLOW_CALL:
                    continue
                if place in self.program.functions:
                    found.add(place)
                    if instruction.flow != dis.FLOW_CALL:
                        owners.add(place)       # a jump to it, which may run it as this one's own code
                else:
                    owner = self.containing(place)
                    if owner is not None and owner != entry:
                        owners.add(owner)
                    elif owner is None and instruction.flow != dis.FLOW_CALL:
                        for inner in self.fragment(place).instructions.values():
                            found |= {target for target in inner.targets if target in self.program.functions}
        return found, owners

    def ret_drops(self, entry):
        drops = {instruction.operands[0].imm if instruction.operands else 0
                 for instruction in self.program.function(entry).instructions.values()
                 if instruction.flow == dis.FLOW_RETURN}
        return drops.pop() if len(drops) == 1 else 0

    def scan(self, entry):
        problem = None
        for mode in MODES:
            try:
                return Scan(self, entry, mode).run()
            except NotKnown as found:
                problem = problem or found
                if not getattr(found, "uneven", False):
                    break
        return Summary(known=False, why=str(problem))


def uneven(text):
    """A NotKnown that a call through a pointer dropping other than assumed may cause."""
    problem = NotKnown(text)
    problem.uneven = True
    return problem


class Scan:
    """One function followed from its start; calls through a pointer taken as 'mode' says."""

    def __init__(self, summaries, entry, mode):
        self.summaries = summaries
        self.program = summaries.program
        self.mode = mode
        self.decoded = self.program.function(entry)
        self.instructions = dict(self.decoded.instructions)
        self.inputs = set()
        self.arguments = 0
        self.escapes = False
        self.exits = []
        self.drops = set()

    def run(self):
        start = State((0, 0), None, [ORIG] * 24, {}, 0, 0, {})
        states = {self.decoded.entry: start}
        work = [self.decoded.entry]
        while work:
            address = work.pop()
            state = states[address].copy()
            for successor in self.step(self.instructions[address], state):
                old = states.get(successor)
                new = state.copy() if old is None else old.merged(state)
                if old is None or not old.same(new):
                    states[successor] = new
                    work.append(successor)
        if len(self.drops) > 1:
            raise uneven("returns dropping different amounts")
        writes, always = set(), set(ALL_PARTS) if self.exits else set()
        for status in self.exits:
            for register, part in ALL_PARTS:
                value = status[register * 3 + part]
                if value != ORIG:
                    writes.add((register, part))
                if value != NEW:
                    always.discard((register, part))
        return Summary(self.inputs, writes, always, self.arguments, self.drops.pop() if self.drops else 0,
                       self.escapes)

    # ---- the parts of registers ----

    def read(self, state, name):
        found = PARTS_OF.get(name)
        if found is None or found[0] == ESP:
            return
        register, parts = found
        for part in parts:
            if state.status[register * 3 + part] != NEW:
                self.inputs.add((register, part))

    def read_whole(self, state, register):
        for part in range(3):
            if state.status[register * 3 + part] != NEW:
                self.inputs.add((register, part))

    def write(self, state, name):
        found = PARTS_OF.get(name)
        if found is None or found[0] == ESP:
            return
        register, parts = found
        for part in parts:
            state.status[register * 3 + part] = NEW
        if register == EBP:
            state.frame = None

    def as_caller_left(self, state, register):
        return all(state.status[register * 3 + part] == ORIG for part in range(3))

    # ---- the stack ----

    def position(self, state, operand):
        """Where on the stack a memory operand reaches, as (base, offset); None when it is not the stack."""
        if operand.kind != "mem" or operand.segment == "fs":
            return None
        if operand.base == "esp":
            if state.esp is None:
                raise uneven("a stack access where ESP is not known")
            where = moved(state.esp, signed(operand.disp))
        elif operand.base == "ebp" and state.frame is not None:
            where = moved(state.frame, signed(operand.disp))
        else:
            return None
        if operand.index is not None and where[0] == 0 and where[1] >= 0:
            self.escapes = True     # an argument by an index: as many as the caller passes
            return None
        return where

    def touch(self, state, operand, writes, address_only=False):
        where = self.position(state, operand)
        if where is None:
            return
        size = max(operand.bits // 8, 1)
        base, offset = where
        if base == 0 and offset < 4 and offset + (1 if address_only else size) > 0:
            raise NotKnown("reads its return address")
        if address_only:
            if base == 0 and offset >= 4:
                self.escapes = True
            return
        if base == 0 and offset >= 4:
            self.arguments = max(self.arguments, (offset + size - 1 - 4) // 4 + 1)
        held = state.saved.get(where)
        if writes:
            state.forget(base, offset, offset + size)
        elif held not in (None, PUSHED):
            self.read_whole(state, held)

    def moved_up(self, state):
        if state.esp is not None:
            base, offset = state.esp
            state.forget(base, -(1 << 31), offset)

    # ---- one instruction ----

    def step(self, instruction, state):
        """Changes 'state' to the one after 'instruction'; the addresses that may run next."""
        m = instruction.mnemonic
        operands = instruction.operands
        if m in ("pushal", "popal", "pushad", "popad", "enter", "into", "iretd", "retf"):
            raise NotKnown(m)
        if instruction.flow == dis.FLOW_CALL:
            return self.call(instruction, state)
        if instruction.flow == dis.FLOW_RETURN:
            if state.esp != (0, 0):
                raise uneven("returns with ESP at %s" % (state.esp,))
            self.drops.add(operands[0].imm if operands else 0)
            self.exits.append(list(state.status))
            return []
        if instruction.flow == dis.FLOW_STOP:
            return []
        if m == "push":
            self.push(instruction, state)
        elif m == "pop":
            self.pop(instruction, state)
        elif m in ("pushfd", "popfd"):
            if state.esp is None:
                raise uneven("a push where ESP is not known")
            state.esp = moved(state.esp, -4 if m == "pushfd" else 4)
            self.moved_up(state)
        elif m == "leave":
            if state.frame is None:
                raise uneven("leave without a frame")
            state.esp = state.frame
            self.moved_up(state)
            held = state.saved.get(state.esp)
            for part in range(3):
                state.status[EBP * 3 + part] = restored(held, EBP)
            state.esp = moved(state.esp, 4)
            state.frame = None
            self.moved_up(state)
        elif m == "int":
            # the kernel's debug services (int 2Dh: OutputDebugString): what they read, and the
            # registers they may change; the kernel goes on past the int3 that follows
            for name in ("eax", "ecx", "edx"):
                self.read(state, name)
                self.write(state, name)
            following = self.instructions.get(instruction.next)
            if following is not None and following.mnemonic == "int3":
                return self.go(following.next, state)
        else:
            self.data(instruction, state)
        return self.successors(instruction, state)

    def data(self, instruction, state):
        m = instruction.mnemonic
        operands = instruction.operands
        same = len(operands) == 2 and operands[0].kind == "reg" and operands[1].kind == "reg" \
            and operands[0].reg == operands[1].reg
        # what does not depend on the register's value: xor eax, eax; sbb eax, eax; or eax, -1; and eax, 0
        unread = None
        if same and m in ("xor", "sub", "sbb"):
            unread = operands[0].reg
        elif len(operands) == 2 and operands[0].kind == "reg" and operands[1].kind == "imm" and \
                ((m == "or" and operands[1].imm == (1 << operands[0].bits) - 1) or (m == "and" and operands[1].imm == 0)):
            unread = operands[0].reg
        for position, operand in enumerate(operands):
            if operand.kind == "mem":
                written = position == 0 and m.startswith(("mov", "set", "fst", "fist", "fbstp", "fnst")) \
                    and not m.startswith("movs")
                self.touch(state, operand, written, address_only=(m == "lea"))
        if "esp" in instruction.writes:
            self.moves_esp(instruction, state)
        for name in instruction.reads:
            if name != unread:
                self.read(state, name)
        frame = None
        if m == "mov" and operands[0].kind == "reg" and operands[0].reg == "ebp" and operands[1].kind == "reg" \
                and operands[1].reg == "esp":
            frame = state.esp
        elif m == "lea" and operands[0].kind == "reg" and operands[0].reg == "ebp" and operands[1].base == "esp" \
                and operands[1].index is None:
            frame = moved(state.esp, signed(operands[1].disp))
        for name in instruction.writes:
            self.write(state, name)
            if name in PARTS_OF:
                state.constants.pop(("thunk", PARTS_OF[name][0]), None)
        if any(PARTS_OF.get(name, (None,))[0] == EAX for name in instruction.writes):
            state.constants.pop("eax", None)
            if m == "mov" and operands[0].kind == "reg" and operands[0].reg == "eax" and operands[1].kind == "imm":
                state.constants["eax"] = operands[1].imm
        if m == "mov" and operands[0].kind == "reg" and operands[0].bits == 32 and operands[1].kind == "mem" \
                and operands[1].base is None and operands[1].index is None \
                and KERNEL_THUNKS[0] <= operands[1].disp < KERNEL_THUNKS[1]:
            state.constants[("thunk", PARTS_OF[operands[0].reg][0])] = self.program.word(operands[1].disp)
        if frame is not None:
            state.frame = frame

    def moves_esp(self, instruction, state):
        m = instruction.mnemonic
        operands = instruction.operands
        if m in ("add", "sub") and operands[0].kind == "reg" and operands[0].reg == "esp" and operands[1].kind == "imm":
            if state.esp is None:
                raise uneven("moves ESP where it is not known")
            amount = signed(operands[1].imm)
            state.esp = moved(state.esp, amount if m == "add" else -amount)
        elif m == "lea" and operands[0].reg == "esp" and operands[1].base == "esp" and operands[1].index is None:
            if state.esp is None:
                raise uneven("moves ESP where it is not known")
            state.esp = moved(state.esp, signed(operands[1].disp))
        elif m == "mov" and operands[0].kind == "reg" and operands[0].reg == "esp" and operands[1].kind == "reg" \
                and operands[1].reg == "ebp" and state.frame is not None:
            state.esp = state.frame
        elif m == "and" and operands[0].kind == "reg" and operands[0].reg == "esp" and operands[1].kind == "imm" \
                and state.frame is not None:
            state.esp = (instruction.address, 0)     # aligned: a place of its own, below the frame
        else:
            raise NotKnown("moves ESP by a value (%s %s)" % (m, instruction.op_str))
        self.moved_up(state)

    def push(self, instruction, state):
        if state.esp is None:
            raise uneven("a push where ESP is not known")
        operand = instruction.operands[0]
        size = operand.bits // 8 if operand.kind != "imm" else 4
        if operand.kind == "mem":
            self.touch(state, operand, False)
        state.esp = moved(state.esp, -size)
        base, offset = state.esp
        state.forget(base, offset, offset + size)
        if operand.kind == "imm":
            state.constants[state.esp] = operand.imm
        if state.pushed_all is not None:
            state.pushed_all += size
        if operand.kind == "reg" and operand.bits == 32 and operand.reg in PARTS_OF:
            register = PARTS_OF[operand.reg][0]
            if self.as_caller_left(state, register):
                state.saved[state.esp] = register      # a register saved, or an argument: the pop says
                return
        state.saved[state.esp] = PUSHED
        if state.pushed is not None:
            state.pushed += size
        for name in instruction.reads:
            self.read(state, name)

    def pop(self, instruction, state):
        if state.esp is None:
            raise uneven("a pop where ESP is not known")
        operand = instruction.operands[0]
        held = state.saved.get(state.esp)
        if operand.kind == "reg" and operand.bits == 32 and operand.reg in PARTS_OF:
            register = PARTS_OF[operand.reg][0]
            if held is not None and held not in (register, PUSHED):
                self.read_whole(state, held)
            for part in range(3):
                state.status[register * 3 + part] = restored(held, register)
            if register == EBP:
                state.frame = None
        elif operand.kind == "mem":
            if held not in (None, PUSHED):
                self.read_whole(state, held)
            state.esp = moved(state.esp, 4)
            self.touch(state, operand, True)
            state.esp = moved(state.esp, -4)
        state.esp = moved(state.esp, operand.bits // 8 if operand.kind != "imm" else 4)
        if state.pushed is not None and held not in range(8):
            state.pushed = max(state.pushed - 4, 0)
        if state.pushed_all is not None:
            state.pushed_all = max(state.pushed_all - 4, 0)
        self.moved_up(state)

    # ---- calls and the ways out ----

    def callee(self, target):
        summary = self.summaries.found.get(target)
        if summary is None:
            raise NotKnown("calls %08X, no function" % target)
        if not summary.known:
            raise NotKnown("calls %s, not known" % self.program.functions[target][1])
        return summary

    def take(self, state, summary, first):
        """What a call reads and writes, its arguments from offset 'first' (where ESP stands at a call; 4
        above it at a jump to another function)."""
        if state.esp is None:
            raise uneven("a call where ESP is not known")
        base, offset = state.esp
        for n in range(summary.arguments):
            where = (base, offset + first + 4 * n)
            if base == 0 and 0 <= where[1] < 4:
                raise NotKnown("hands its return address on")
            if base == 0 and where[1] >= 4:
                self.arguments = max(self.arguments, (where[1] - 4) // 4 + 1)
            held = state.saved.get(where)
            if held not in (None, PUSHED):
                self.read_whole(state, held)
        if summary.escapes and base == 0 and offset + first >= 4:
            self.escapes = True     # the arguments of this function go on to one that counts them by its callers
        for register, part in summary.inputs:
            if state.status[register * 3 + part] != NEW:
                self.inputs.add((register, part))
        for register, part in summary.writes:
            k = register * 3 + part
            if (register, part) in summary.always:
                state.status[k] = NEW
            elif state.status[k] == ORIG:
                state.status[k] = MAYBE
        if any(register == EBP for register, _ in summary.writes):
            state.frame = None

    def unseen_drops(self, instruction, state):
        """What a call through a pointer drops: what the functions a run saw it reach drop, if they agree;
        else nothing (cdecl) or, followed the other way, what was pushed for it (stdcall); a call of the
        kernel's, what was pushed."""
        operand = instruction.operands[0]
        ordinal = None
        if operand.kind == "mem" and operand.base is None and operand.index is None \
                and KERNEL_THUNKS[0] <= operand.disp < KERNEL_THUNKS[1]:
            ordinal = self.program.word(operand.disp)
        elif operand.kind == "reg" and operand.reg in PARTS_OF:
            ordinal = state.constants.get(("thunk", PARTS_OF[operand.reg][0]))   # mov edi, [thunk]; call edi
        kernel = ordinal is not None
        if kernel and ordinal & 0x80000000 and (ordinal & 0xFFFF) in self.summaries.kernel:
            return self.summaries.kernel[ordinal & 0xFFFF]
        seen = {self.summaries.found[target].drops for target in self.summaries.targets.get(instruction.address, ())
                if target in self.summaries.found}
        if len(seen) == 1 and not kernel:
            return seen.pop()
        way = self.mode[1] if kernel else self.mode[0]
        if way == "site":
            if self.cleaned_after(instruction):
                return 0
            way = "pushed"
        if way == "cdecl":
            return 0
        pushed = getattr(state, way)
        if pushed is None:
            raise uneven("a call through a pointer whose arguments are not known")
        return pushed

    def unseen_reads(self, instruction, state):
        """The registers a call through a pointer reads: none for a function of the kernel's that takes
        its arguments on the stack; of ECX and EDX, the ones the functions a run saw it reach read; else
        both."""
        operand = instruction.operands[0]
        ordinal = None
        if operand.kind == "mem" and operand.base is None and operand.index is None \
                and KERNEL_THUNKS[0] <= operand.disp < KERNEL_THUNKS[1]:
            ordinal = self.program.word(operand.disp)
        elif operand.kind == "reg" and operand.reg in PARTS_OF:
            ordinal = state.constants.get(("thunk", PARTS_OF[operand.reg][0]))
        if ordinal is not None and ordinal & 0x80000000 and self.summaries.kernel.get(ordinal & 0xFFFF):
            return frozenset()
        seen = [self.summaries.found.get(target) for target in self.summaries.targets.get(instruction.address, ())]
        if seen and all(summary is not None and summary.known for summary in seen):
            return frozenset().union(*[summary.inputs for summary in seen]) & UNSEEN_CALLS_READ
        return UNSEEN_CALLS_READ

    def cleaned_after(self, instruction):
        """Whether the caller drops the arguments itself after a call: an "add esp" or a "pop" among the
        instructions before the next jump or call."""
        at = instruction.next
        for _ in range(12):
            following = self.instructions.get(at)
            if following is None or following.flow != dis.FLOW_NONE:
                return False
            if following.mnemonic == "pop" or (following.mnemonic == "add" and following.operands[0].kind == "reg"
                                               and following.operands[0].reg == "esp"):
                return True
            at = following.next
        return False

    def frame_helper(self, instruction, state):
        """The C runtime's functions that make or undo their caller's frame, as they do it; False for a
        call of any other. _chkstk: ESP down by EAX. __SEH_prolog, handed the size of the locals and the
        scope table: EBP saved in the size's slot and the frame there, the locals below the two words it
        pushes, EBX, ESI and EDI saved under them. __SEH_epilog: EDI, ESI and EBX back, then "leave"."""
        if not instruction.targets or instruction.targets[0] not in self.program.functions:
            return False
        name = self.program.functions[instruction.targets[0]][1]
        if name not in ("crt_chkstk", "crt_SEH_prolog", "crt_SEH_epilog"):
            return False
        if state.esp is None and name != "crt_SEH_epilog":
            raise uneven("a call where ESP is not known")
        base, offset = state.esp or (None, None)
        if name == "crt_chkstk":
            size = state.constants.get("eax")
            if size is None:
                raise NotKnown("_chkstk with a size not known")
            state.esp = (base, offset - size)
            for part in range(3):
                state.status[EAX * 3 + part] = NEW
        elif name == "crt_SEH_prolog":
            size = state.constants.get((base, offset + 4))
            if size is None:
                raise NotKnown("__SEH_prolog with a size not known")
            state.forget(base, offset + 4, offset + 8)
            if self.as_caller_left(state, EBP):
                state.saved[(base, offset + 4)] = EBP
            low = offset - 12 - size
            for n, register in enumerate((3, 6, 7)):      # EBX, ESI, EDI
                slot = (base, low - 4 * (n + 1))
                state.forget(base, slot[1], slot[1] + 4)
                if self.as_caller_left(state, register):
                    state.saved[slot] = register
            for part in range(3):
                state.status[EAX * 3 + part] = NEW
                state.status[EBP * 3 + part] = NEW
            state.frame = (base, offset + 4)
            state.esp = (base, low - 12)
        else:
            if state.frame is None:
                raise uneven("__SEH_epilog without a frame")
            for n, register in enumerate((7, 6, 3)):      # EDI, ESI, EBX
                held = state.saved.get((base, offset + 4 * n)) if state.esp is not None else None
                for part in range(3):
                    state.status[register * 3 + part] = restored(held, register)
            held = state.saved.get(state.frame)
            for part in range(3):
                state.status[EBP * 3 + part] = restored(held, EBP)
                state.status[ECX * 3 + part] = NEW
            state.esp = moved(state.frame, 4)
            state.frame = None
        state.constants.pop("eax", None)
        state.pushed = state.pushed_all = 0
        self.moved_up(state)
        return True

    def call(self, instruction, state):
        if self.frame_helper(instruction, state):
            return self.successors(instruction, state)
        if instruction.targets:
            summary = self.callee(instruction.targets[0])
            self.take(state, summary, 0)
            drops = summary.drops
        else:
            operand = instruction.operands[0]
            if operand.kind == "mem":
                self.touch(state, operand, False)
            for name in instruction.reads:
                self.read(state, name)
            drops = self.unseen_drops(instruction, state)
            self.take(state, Summary(self.unseen_reads(instruction, state), UNSEEN_CALLS_WRITE, UNSEEN_CALLS_WRITE), 0)
        state.esp = moved(state.esp, drops)
        state.pushed = state.pushed_all = 0
        self.moved_up(state)
        return self.successors(instruction, state)

    def leave_to(self, target, state):
        """A jump to another function that returns for this one; one where ESP is not where this function
        started runs the other's code as this one's."""
        if state.esp != (0, 0):
            return self.run_as_own(target)
        summary = self.callee(target)
        exit_state = state.copy()
        self.take(exit_state, summary, 4)
        self.drops.add(summary.drops)
        self.exits.append(list(exit_state.status))
        return []

    def run_as_own(self, address):
        owner = address if address in self.program.functions else self.summaries.containing(address)
        code = self.program.function(owner) if owner is not None else self.summaries.fragment(address)
        for at, instruction in code.instructions.items():
            self.instructions.setdefault(at, instruction)
        if address not in self.instructions:
            raise NotKnown("goes to %08X, which does not decode" % address)
        return [address]

    def go(self, address, state):
        """The addresses a jump or a fall to 'address' leads to: in this function, or out of it."""
        if address in self.instructions:
            return [address]
        if address in self.program.functions:
            return self.leave_to(address, state)
        return self.run_as_own(address)

    def table(self, instruction):
        """The entries of a jump table the disassembler did not take (memmove's, whose entries lie past
        where it ends the function): as many as the compare or the mask before it allows."""
        if instruction.table is not None:
            return list(instruction.targets)
        operand = instruction.operands[0]
        if operand.kind != "mem" or operand.base is not None or operand.index is None or operand.scale != 4:
            return None
        before = [at for at in sorted(self.instructions) if at < instruction.address][-6:]
        for at in reversed(before):
            guard = self.instructions[at]
            if len(guard.operands) == 2 and guard.operands[0].kind == "reg" and guard.operands[0].reg == operand.index \
                    and guard.operands[1].kind == "imm" and guard.mnemonic in ("cmp", "and"):
                count = guard.operands[1].imm + 1
                if count > 256:
                    return None
                entries = [self.program.word(operand.disp + 4 * k) for k in range(count)]
                # the ones in the code between the function's start and the next function: an entry that
                # is not code is one the index never takes (memmove's first, when the copy is aligned)
                position = bisect.bisect_right(self.summaries.entries, instruction.address)
                low = self.summaries.entries[position - 1] if position else 0
                high = self.summaries.entries[position] if position < len(self.summaries.entries) else low + 0x10000
                found = [entry for entry in entries if entry is not None and low <= entry < high]
                return found if len(found) >= max(1, count - 1) else None
        return None

    def successors(self, instruction, state):
        flow = instruction.flow
        if flow == dis.FLOW_COMPUTED:
            targets = self.table(instruction)
            if targets is None:
                raise NotKnown("jumps through a pointer")
            found = []
            for target in targets:
                found += self.go(target, state.copy())
            return found
        found = []
        if flow in (dis.FLOW_BRANCH, dis.FLOW_JUMP):
            found += self.go(instruction.targets[0], state.copy())
            if flow == dis.FLOW_JUMP:
                return found
        return found + self.go(instruction.next, state)
