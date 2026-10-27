# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        emit.py
Description: writes the game's functions as C, through the decompiler's writer
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

The decompiler's FunctionWriter does the work (tools/core/decompiler/emit.py); this gives it the Xbox's
memory and the x86's effects. The game's memory is the guest's, the one the recompiled C reads and
writes: MEM8, MEM16 and MEM32 of an address (xboxrecomp's recomp_types.h), so that the C and the
recompiled code share it. No variable or structure has a name in it yet (symbols.txt's var and struct
lines will). The string instructions' effects and the 64-bit divisions print as the calls of x86.h
(x86_rep_stos32, x86_udiv64...).
"""
from decompiler import emit
from v60 import ir


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


class X86Names(emit.Names):
    def memory(self, load):
        found = super().memory(load)
        if found is not None:
            return found
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

    def statement(self, statement):
        if isinstance(statement, ir.Store):
            target = self.memory(statement.address, statement.bits, id(statement))
            if target is not None and target[2]:
                return [self.assignment(target[0], statement, target[1])]
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

    def restores_current(self, entry):
        return None, None
