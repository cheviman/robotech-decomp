# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        emit.py
Description: writes the game's functions as C, through the decompiler's writer
Version:     0.2.0
Created:     26-10-2026
Modified:    27-10-2026
Author:      Sebastian Toyos

The decompiler's FunctionWriter does the work (tools/core/decompiler/emit.py); this gives it the Xbox's
memory and the x86's effects. The game's memory is the guest's, the one the recompiled C reads and
writes: MEM8, MEM16 and MEM32 of an address (xboxrecomp's recomp_types.h), so that the C and the
recompiled code share it. A place symbols.txt names goes by that name, as symbols.h spells it
(GuestNames: vcGameTime, D3D__TextureState(3), MEM32(vcDataDir_VA + 0x4u)); no structure's field has a
name in the C yet. The string instructions' effects and the 64-bit divisions print as the calls of x86.h
(x86_rep_stos32, x86_udiv64...). A call of a function that stays recompiled goes as the recompiled code
makes it: the registers it reads in the globals g_eax..., its arguments on the guest's stack
(x86_call), what it hands back read from the globals after.
"""
from decompiler import emit
from v60 import ir

from .profile import ARG0, ARGUMENTS, EAX

REGISTER_GLOBALS = {0: "g_eax", 1: "g_ecx", 2: "g_edx", 3: "g_ebx", 5: "g_ebp", 6: "g_esi", 7: "g_edi"}


def use_memory_map():
    """Makes the guest's memory the one decompiler/memory.py and decompiler/pointers.py work on: no area
    of it holds named variables, tables or structures yet."""
    from decompiler import memory
    from decompiler import pointers
    memory.WORK_RAM = (0, 0)
    memory.ROM_AREAS = ()
    memory.ADDRESS_MASK = 0xFFFFFFFF
    memory.ADDRESS_DIGITS = 8
    memory.RAM_MACRO, memory.ROM_MACRO = "MEM", "MEM"
    memory.RAM_FUNCTION, memory.ROM_FUNCTION = "guest_at", "guest_at"
    memory.PAGED = False
    memory.PLAYER_FIELDS = None
    memory.CANONICAL = lambda address: address
    memory.ROM_NAMES_FROM = 0xFFFFFFFF
    memory.VARIABLES = None
    memory.HARDWARE = []
    memory.BUS_ONLY = []
    memory.BYTE_INDEXES = True
    memory.NAMED_BASES = {}
    memory.NOTES = {"variables": [], "scoped": [], "tables": [], "hardware": []}
    pointers.STRUCTS = {}
    pointers.PLAYERS = (0, 0, 0)
    pointers.VARIABLES = None
    pointers.CONTEXT_KINDS = {}
    pointers.OBJECT_REGISTERS = ()
    pointers.HANDLER_FIELD = None
    pointers.WORK_RAM = (0, 0)
    pointers.ADDRESS_MASK = 0xFFFFFFFF
    pointers.POINTER_BITS = 32
    pointers.PAGE_LINKS = False
    pointers.ROM_DATA = (0, 0)
    pointers.ARRAYS = {}
    pointers.INSTANCES = {}
    pointers.VARIABLE_BLOCKS = {}
    pointers.BASE_KINDS = {}
    pointers.PAGE_LINK_KINDS = {}
    pointers.NESTED = {}
    pointers.BELOW = {}
    pointers.OWN_REGISTERS = ()
    pointers.STRUCT_FUNCTION = "guest_at"
    pointers.ROM_STRUCTS = set()
    pointers.RUNS = set()
    pointers.ELEMENTS = {}
    pointers.RECORD_TABLES = {}
    pointers.FIELD_ARRAYS = {}
    pointers.ROM_FUNCTION = "guest_at"
    pointers.CONSTANTS = True
    pointers.PAGED = False


INTEGER_TYPES = {"u8": (8, False), "s8": (8, True), "u16": (16, False), "s16": (16, True),
                 "u32": (32, False), "s32": (32, True)}
TYPE_BYTES = {"u8": 1, "s8": 1, "u16": 2, "s16": 2, "u32": 4, "s32": 4, "f32": 4, "f64": 8, "char": 1}


class GuestNames:
    """The game's memory by the names symbols.txt gives it, as symbols.h spells them for C (tools/symbols.py
    header): a variable NAME, an element of one NAME(i), and any other place in one, or at a data label,
    by its address NAME_VA. 'variables': {address: (name, type, count: None for one, -1 for an array of a
    count not given)}; 'labels': {address: name}."""

    def __init__(self, variables, labels):
        self.variables = variables
        self.labels = labels
        self.starts = sorted(variables)

    def place(self, address, bits):
        """(C text, signed) of the memory at a constant address 'bits' wide, or None."""
        import bisect
        position = bisect.bisect_right(self.starts, address) - 1
        if position >= 0:
            start = self.starts[position]
            name, kind, count = self.variables[start]
            size = TYPE_BYTES[kind]
            offset = address - start
            # an array of a count not given (-1) goes on up to the next variable
            end = (self.starts[position + 1] if position + 1 < len(self.starts) else start + 0x10000) \
                if count == -1 else start + size * (count or 1)
            if address < end:
                integer = INTEGER_TYPES.get(kind)
                if integer is not None and integer[0] == bits and offset % size == 0:
                    return (f"{name}({offset // size})" if count else name), integer[1]
                return f"MEM{bits}({name}_VA + 0x{offset:X}u)" if offset else f"MEM{bits}({name}_VA)", False
        if address in self.labels:
            return f"MEM{bits}({self.labels[address]}_VA)", False
        return None


class X86Names(emit.Names):
    def memory(self, load):
        found = super().memory(load)
        if found is not None:
            return found
        guest = getattr(self.writer.emitter, "guest", None)
        if guest is not None and isinstance(load.address, ir.Const):
            named = guest.place(load.address.value & 0xFFFFFFFF, load.bits)
            if named is not None:
                return named
        return f"MEM{load.bits}({self.writer.exact(load.address)})", False


class X86Printer(emit.Printer):
    def __init__(self, writer):
        super().__init__(writer)
        self.names = X86Names(writer)

    def helper(self, name, args, bits):
        if name.startswith("x86_"):
            from decompiler.cprint import PRIMARY, Value
            values = ", ".join(self.exact(arg).text for arg in args)
            return Value(f"{name}({values})", PRIMARY, True, "u32")
        return super().helper(name, args, bits)


class X86Writer(emit.FunctionWriter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.printer = X86Printer(self)

    def call(self, statement):
        if statement.target is not None and statement.target in self.emitter.recompiled:
            return self.recompiled_call(statement.target, statement.return_address)
        return super().call(statement)

    def ending(self, end):
        if isinstance(end, ir.TailCall) and end.target in self.emitter.recompiled:
            self.current = end
            return self.recompiled_call(end.target, None) + self.copy_out() + [self.return_text()]
        return super().ending(end)

    def register_input(self, index):
        """What the caller's register holds where the call reads it: its variable, or 0 when nothing has
        set it (as the core passes a register a function never sets)."""
        if self.never_set(index):
            return "0u"
        name = self.implicit_value(index)
        declared = set(self.widths) | {self.emitter.param_name(self.entry, value) for value in self.params + self.results}
        return name if name in declared else "0u"

    def recompiled_call(self, target, return_address):
        """A call of a function left recompiled (decompile.py, recompiled.py): the registers it reads, and
        the ones it may leave as they were, into the register globals; its arguments on the guest's stack,
        under the return address the original pushes (x86_call); what it hands back from the globals."""
        emitter = self.emitter
        by_value, by_pointer, returned = emitter.by_value(target), emitter.by_pointer(target), emitter.returned(target)
        params = emitter.signatures[target].params
        live = self.after.get(id(self.current))
        arguments, handed = [], set()
        for value in by_value + by_pointer:
            index = value[1]
            if ARG0 <= index < ARG0 + ARGUMENTS:
                arguments.append(index)
            elif value in params:
                handed.add(index)
            elif not emitter.always_written(target, value) and \
                    (live is None or any(variable[0] == "r" and variable[1] == index for variable in live)):
                handed.add(index)   # one it may leave as it was, which the caller reads afterwards
        lines = [f"{REGISTER_GLOBALS[index]} = {self.register_input(index)};" for index in sorted(handed)]
        values = "".join(", " + self.register_input(index) for index in sorted(arguments))
        call = f"x86_call({emitter.names[target]}, 0x{return_address or 0:08X}u, {len(arguments)}{values})"
        results = [value for value in by_pointer] + ([returned] if returned is not None else [])
        if returned is not None and returned[1] == EAX:
            lines.append(f"{self.register_set(EAX)} = {call};")
        else:
            lines.append(call + ";")
        lines += [f"{self.register_set(value[1])} = {REGISTER_GLOBALS[value[1]]};"
                  for value in results if not (value is returned and value[1] == EAX)]
        return lines

    def statement(self, statement):
        if isinstance(statement, ir.Store):
            target = self.memory(statement.address, statement.bits, id(statement))
            if target is not None and target[2]:
                return [self.assignment(target[0], statement, target[1])]
            guest = getattr(self.emitter, "guest", None)
            if guest is not None and isinstance(statement.address, ir.Const):
                named = guest.place(statement.address.value & 0xFFFFFFFF, statement.bits)
                if named is not None:
                    return [f"{named[0]} = {self.stored(statement.value, statement.bits)};"]
            return [f"MEM{statement.bits}({self.exact(statement.address)}) = "
                    f"{self.stored(statement.value, statement.bits)};"]
        return super().statement(statement)

    def effect(self, statement):
        name = statement.name
        if name.startswith("x86_rep_"):
            values = ", ".join(self.exact(arg) for arg in statement.args)
            return [f"{name}({values});"]
        raise emit.EmitError(f"{self.function.name}: effect {name}")


class X86Emitter(emit.Emitter):
    """emit.Emitter with nothing of the V60 program's: no context registers, no structures yet."""

    def __init__(self, functions, signatures, names, memory_, always, layouts):
        super().__init__(functions, signatures, names, (), set(), memory_, always, lambda address: 0)
        self.layouts = layouts
        self.saved_locals = True
        self.flow = None
        self.recompiled = set()     # the functions called that stay recompiled (decompile.py)
        self.guest = None           # the game's memory by name (GuestNames, decompile.py)

    def restores_current(self, entry):
        return None, None
