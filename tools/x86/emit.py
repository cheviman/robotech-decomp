# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        emit.py
Description: writes the game's functions as C, through the decompiler's writer
Version:     0.4.0
Created:     26-10-2026
Modified:    05-11-2026
Author:      Sebastian Toyos

The decompiler's FunctionWriter does the work (tools/core/decompiler/emit.py); this gives it the Xbox's
memory and the x86's effects. The game's memory is the guest's, the one the recompiled C reads and
writes: MEM8, MEM16 and MEM32 of an address (xboxrecomp's recomp_types.h), so that the C and the
recompiled code share it. A place symbols.txt names goes by that name, as symbols.h spells it
(GuestNames: vcGameTime, D3D__TextureState(3), MEM32(vcDataDir_VA + 0x4u)); a field of a record of a
structure in place by its name, the record by its table's index (Level_chapter(Levels(level))); and an
address the C uses as a value by its name too (ecx = Levels_VA; eax = Levels(level)). A field a pointer
reaches has no name in the C yet. The string instructions' effects and the 64-bit divisions print as the calls of x86.h
(x86_rep_stos32, x86_udiv64...). A call of a function that stays recompiled goes as the recompiled code
makes it: the registers it reads in the globals g_eax..., its arguments on the guest's stack
(x86_call), what it hands back read from the globals after.
"""
import bisect
import decimal
import fractions
import re
import struct

from decompiler import cprint, emit
from decompiler.stack import MEMORY_SP
from v60 import ir

from .profile import ARG0, ARGUMENTS, EAX, FLOAT0


def float_literal(bits):
    """C's float literal of a float's bits, in the fewest digits that make that float ("0.5f", "0.1f"); a
    literal is rounded to the nearest float, so one between the halves to the float's neighbours is the
    float, as loading its bits is. None for a NaN or an infinity."""
    if (bits >> 23) & 0xFF == 0xFF:
        return None
    sign = "-" if bits & 0x80000000 else ""
    magnitude = bits & 0x7FFFFFFF
    if magnitude == 0:
        return sign + "0.0f"

    def value(of):
        return fractions.Fraction(struct.unpack("<f", struct.pack("<I", of))[0])
    exact = value(magnitude)
    below = (exact + value(magnitude - 1)) / 2
    above = (exact + value(magnitude + 1)) / 2 if magnitude + 1 < 0x7F800000 else exact + (exact - value(magnitude - 1)) / 2
    for digits in range(1, 10):
        text = format(float(exact), f".{digits}g")
        near = fractions.Fraction(decimal.Decimal(text))
        if below < near < above or (near in (below, above) and magnitude % 2 == 0):
            if "." not in text and "e" not in text:
                text += ".0"
            # a float those digits are exactly (0.5, 255.0) is a double literal: C works out two float
            # literals in the same expression as floats, the x87 as its doubles
            return sign + text + ("" if near == exact else "f")
    return None

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
    header): a variable NAME, an element of one NAME(i), a field of a record of a structure in place
    STRUCT_field(NAME(i)) (STRUCT_field(NAME_VA) for one record), and any other place in one, or at a data
    label, by its address NAME_VA. 'variables': {address: (name, type or structure, count: None for one, -1
    for an array of a count not given)}; 'labels': {address: name}; 'structs': {name: (size, [(offset, field,
    type, count)])}, its fields' types integers or floats as the variables' are."""

    def __init__(self, variables, labels, structs=None):
        self.variables = variables
        self.labels = labels
        self.structs = structs or {}
        self.starts = sorted(variables)

    def containing(self, address):
        """(start, name, type or structure, count, size of one) of the variable 'address' lies in, or None."""
        position = bisect.bisect_right(self.starts, address) - 1
        if position < 0:
            return None
        start = self.starts[position]
        name, kind, count = self.variables[start]
        size = TYPE_BYTES.get(kind) or self.structs.get(kind, (0,))[0]
        if not size:
            return None
        # an array of a count not given (-1) goes on up to the next variable
        end = (self.starts[position + 1] if position + 1 < len(self.starts) else start + 0x10000) \
            if count == -1 else start + size * (count or 1)
        return (start, name, kind, count, size) if address < end else None

    @staticmethod
    def record(name, count, number):
        """C for the guest address of record 'number' (C text or a number) of the records in place NAME."""
        return f"{name}_VA" if count is None else f"{name}({number})"

    def field(self, struct, record, inner, bits):
        """(C text, signed) of the memory 'bits' wide 'inner' bytes into the record of 'struct' whose guest
        address is the C 'record': its field by name where one is there."""
        size = self.structs[struct][0]
        for offset, name, kind, count in self.structs[struct][1]:
            one = TYPE_BYTES[kind]
            extent = size - offset if count == -1 else one * (count or 1)
            if not offset <= inner < offset + extent:
                continue
            within = inner - offset
            integer = INTEGER_TYPES.get(kind)
            if integer is not None and integer[0] == bits and within % one == 0:
                accessor = f"{struct}_{name}({record})"
                return (accessor if count is None else f"{accessor}[{within // one}]"), integer[1]
            place = f"{struct}_{name}_VA({record})"
            return (f"MEM{bits}({place} + 0x{within:X}u)" if within else f"MEM{bits}({place})"), False
        return (f"MEM{bits}({record} + 0x{inner:X}u)" if inner else f"MEM{bits}({record})"), False

    def place(self, address, bits):
        """(C text, signed) of the memory at a constant address 'bits' wide, or None."""
        found = self.containing(address)
        if found is not None:
            start, name, kind, count, size = found
            offset = address - start
            if kind in self.structs:
                number, inner = divmod(offset, size)
                return self.field(kind, self.record(name, count, number), inner, bits)
            integer = INTEGER_TYPES.get(kind)
            if integer is not None and integer[0] == bits and offset % size == 0:
                return (f"{name}({offset // size})" if count else name), integer[1]
            return f"MEM{bits}({name}_VA + 0x{offset:X}u)" if offset else f"MEM{bits}({name}_VA)", False
        if address in self.labels:
            return f"MEM{bits}({self.labels[address]}_VA)", False
        return None

    def half(self, address, bits):
        """(C text, signed) of a 16-bit read of the low or the high half of a 32-bit variable (a handle's
        class is its high half: NAME >> 16), or None."""
        found = self.containing(address) if bits == 16 else None
        if found is None or INTEGER_TYPES.get(found[2], (0,))[0] != 32:
            return None
        start, name, _, count, _ = found
        number, inner = divmod(address - start, 4)
        if inner not in (0, 2):
            return None
        whole = f"{name}({number})" if count else name
        return (f"((uint16_t)({whole} >> 16))" if inner else f"((uint16_t){whole})"), False

    def float_field(self, struct, record, inner):
        """C for the float 'inner' bytes into the record of 'struct' at the C 'record', by its field's
        accessor (a volatile float), or None where no f32 field lies there."""
        size = self.structs[struct][0]
        for offset, name, kind, count in self.structs[struct][1]:
            extent = size - offset if count == -1 else TYPE_BYTES[kind] * (count or 1)
            if offset <= inner < offset + extent:
                if kind != "f32" or (inner - offset) % 4:
                    return None
                accessor = f"{struct}_{name}({record})"
                return accessor if count is None else f"{accessor}[{(inner - offset) // 4}]"
        return None

    def float_place(self, address, exact):
        """C for the float at 'address' (a constant, or "base + index * size" into a table of records in
        place) where symbols.txt gives it a name: a variable or an element of an array of f32, or an f32
        field of a record in place; None otherwise. An lvalue of type float."""
        if isinstance(address, ir.Const):
            found = self.containing(address.value & 0xFFFFFFFF)
            if found is None:
                return None
            start, name, kind, count, size = found
            offset = (address.value & 0xFFFFFFFF) - start
            if kind in self.structs:
                number, inner = divmod(offset, size)
                return self.float_field(kind, self.record(name, count, number), inner)
            if kind != "f32" or offset % 4:
                return None
            return f"{name}({offset // 4})" if count else name
        table = self.indexed(address)
        if table is None:
            return None
        name, kind, count, value, number, inner = table
        return self.float_field(kind, self.record(name, count, self.numbered(exact(value), number)), inner)

    @staticmethod
    def scaled(index, size):
        """What 'index' multiplies by 'size' ("i * size", "i << n"), or None."""
        if size == 1:
            return index
        if isinstance(index, ir.Op) and index.name in ("mul", "shl") and len(index.args) == 2:
            for value, factor in (index.args, index.args[::-1]):
                if isinstance(factor, ir.Const) and not isinstance(value, ir.Const) and \
                        ((index.name == "mul" and factor.value == size) or
                         (index.name == "shl" and factor is index.args[1] and 1 << factor.value == size)):
                    return value
        return None

    def indexed(self, address):
        """For an address "base + index * size" into a table of records in place: (name, structure, count,
        the index, the records the base is past the table's start, the bytes into the record); else None."""
        if not (isinstance(address, ir.Op) and address.name == "add"):
            return None
        left, right = address.args
        base, index = (left, right) if isinstance(left, ir.Const) else (right, left)
        if not isinstance(base, ir.Const) or isinstance(index, ir.Const):
            return None
        found = self.containing(base.value & 0xFFFFFFFF)
        if found is None or found[2] not in self.structs or found[3] is None:
            return None
        start, name, kind, count, size = found
        value = self.scaled(index, size)
        if value is None:
            return None
        number, inner = divmod((base.value & 0xFFFFFFFF) - start, size)
        return name, kind, count, value, number, inner

    @staticmethod
    def numbered(text, number):
        """An index's C plus records more: "i", "i + 2", "(a - b) + 2"."""
        if not number:
            return text
        simple = re.fullmatch(r"[\w.]+", text) is not None
        return f"{text if simple else '(' + text + ')'} + {number}"

    def element(self, address, bits, exact):
        """For an address "base + index * size": (C text, signed) of the element of the array of integers
        starting at base whose elements are 'bits' wide and size bytes apart, or of the field of the record
        the index picks in a table of records in place; None if it is neither. 'exact' prints the index."""
        table = self.indexed(address)
        if table is not None:
            name, kind, count, value, number, inner = table
            return self.field(kind, self.record(name, count, self.numbered(exact(value), number)), inner, bits)
        if not (isinstance(address, ir.Op) and address.name == "add"):
            return None
        left, right = address.args
        base, index = (left, right) if isinstance(left, ir.Const) else (right, left)
        if not isinstance(base, ir.Const) or isinstance(index, ir.Const):
            return None
        found = self.variables.get(base.value & 0xFFFFFFFF)
        if found is None or found[2] is None or INTEGER_TYPES.get(found[1], (None,))[0] != bits:
            return None
        size = TYPE_BYTES[found[1]]
        if size == 1:
            return f"{found[0]}({exact(index)})", INTEGER_TYPES[found[1]][1]
        if isinstance(index, ir.Op) and isinstance(index.args[1], ir.Const) and \
                ((index.name == "mul" and index.args[1].value == size) or
                 (index.name == "shl" and 1 << index.args[1].value == size)):
            return f"{found[0]}({exact(index.args[0])})", INTEGER_TYPES[found[1]][1]
        return None

    def record_place(self, kind, record, inner):
        """(C, precedence) of the guest address 'inner' bytes into the record of 'kind' at the C 'record':
        the record's, a field's (STRUCT_field_VA(record)), a place inside an array field from the field's
        (STRUCT_field_VA(record) + bytes), or past the record's."""
        if not inner:
            return record, cprint.PRIMARY
        size = self.structs[kind][0]
        for offset, name, of, count in self.structs[kind][1]:
            if offset == inner:
                return f"{kind}_{name}_VA({record})", cprint.PRIMARY
            extent = size - offset if count == -1 else TYPE_BYTES[of] * (count or 1)
            if count is not None and offset < inner < offset + extent:
                return f"{kind}_{name}_VA({record}) + 0x{inner - offset:X}u", cprint.ADD
        return f"{record} + 0x{inner:X}u", cprint.ADD

    def address(self, value):
        """(C, precedence) of a constant that is the guest address of a place symbols.txt names, as the C
        uses it for a value (a pointer handed on, a table to walk): NAME_VA, a record of a table NAME(i), a
        field's address in one, NAME_VA + bytes into a variable; None for any other number."""
        found = self.containing(value)
        if found is not None:
            start, name, kind, count, size = found
            offset = value - start
            if not offset:
                return f"{name}_VA", cprint.PRIMARY
            if kind in self.structs:
                number, inner = divmod(offset, size)
                return self.record_place(kind, self.record(name, count, number) if number else f"{name}_VA",
                                         inner)
            return f"{name}_VA + 0x{offset:X}u", cprint.ADD
        if value in self.labels:
            return f"{self.labels[value]}_VA", cprint.PRIMARY
        return None

    def sum(self, node, exact):
        """(C, precedence) of "index * size + base" where base is in a table of records in place: the
        address of the record the index picks (NAME(i)), or of a place in it; None otherwise."""
        table = self.indexed(node)
        if table is None:
            return None
        name, kind, count, value, number, inner = table
        return self.record_place(kind, self.record(name, count, self.numbered(exact(value), number)), inner)


class X86Names(emit.Names):
    # The core writes "(x & 0xFFFF0000) | link" as LINKED(x, link) where a pointer moves within its 64 KB
    # page (an arcade board's links); the x86 has none of those, and that is a write of AX.
    def pointer(self, node):
        return False

    def link(self, load):
        return False

    def memory(self, load):
        found = super().memory(load)
        if found is not None:
            return found
        guest = getattr(self.writer.emitter, "guest", None)
        if guest is not None and isinstance(load.address, ir.Const):
            half = guest.half(load.address.value & 0xFFFFFFFF, load.bits)
            if half is not None:
                return half
            named = guest.place(load.address.value & 0xFFFFFFFF, load.bits)
            if named is not None:
                return named
        if guest is not None:
            element = guest.element(load.address, load.bits, self.writer.exact)
            if element is not None:
                return element
        return f"MEM{load.bits}({self.writer.exact(load.address)})", False


class X86Printer(emit.Printer):
    def __init__(self, writer):
        super().__init__(writer)
        self.names = X86Names(writer)

    def emit(self, node):
        guest = getattr(self.writer.emitter, "guest", None)
        if guest is not None and isinstance(node, ir.Op) and node.name == "add":
            # the address of a record of a table in place, from its index: Levels(level)
            found = guest.sum(node, self.writer.exact)
            if found is not None:
                return cprint.Value(found[0], found[1], True, "u32")
        if guest is not None and isinstance(node, ir.Op) and node.name == "f.from32" \
                and isinstance(node.args[0], ir.Load) and node.args[0].bits == 32:
            # a float symbols.txt names, as FLD loads it: its value as a double (the conversion makes a
            # signaling NaN quiet, as x87_float does)
            place = guest.float_place(node.args[0].address, self.writer.exact)
            if place is not None:
                return cprint.Value(f"(double){place}", cprint.UNARY, True, "f64")
        if isinstance(node, ir.Op) and node.name == "f.const32" and isinstance(node.args[0], ir.Const):
            # a float of the program's constants, or of fld1 and fldz: its literal
            literal = float_literal(node.args[0].value & 0xFFFFFFFF)
            if literal is not None:
                from decompiler.cprint import PRIMARY, UNARY, Value
                return Value(literal, UNARY if literal.startswith("-") else PRIMARY, True, "f64")
        return super().emit(node)

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
            return self.recompiled_call(statement.target, statement.return_address, address=statement.address)
        return super().call(statement)

    def ending(self, end):
        if isinstance(end, ir.TailCall) and end.target in self.emitter.recompiled:
            self.current = end
            return self.recompiled_call(end.target, None, tail=True) + self.copy_out() + [self.return_text()]
        return super().ending(end)

    def register_input(self, index):
        """What the caller's register holds where the call reads it: its variable, or 0 when nothing has
        set it (as the core passes a register a function never sets)."""
        if self.never_set(index):
            return "0u"
        name = self.implicit_value(index)
        declared = set(self.widths) | {self.emitter.param_name(self.entry, value) for value in self.params + self.results}
        return name if name in declared else "0u"

    def recompiled_call(self, target, return_address, tail=False, address=None):
        """A call of a function left recompiled (decompile.py, recompiled.py): the registers it reads, and
        the ones it may leave as they were, into the register globals; its arguments on the guest's stack,
        under the return address the original pushes (x86_call); what it hands back from the globals. From
        a function whose stack stays in memory its arguments are there already: only the return address
        goes on, and a jump to it pushes nothing (x86_jump). A call through a pointer is one of the code at
        'address', which the recompiled code's tables find (x86_icall)."""
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
        icalls = getattr(emitter, "icalls", {})
        if target in icalls:
            call = (f"x86_icall({self.exact(address)}, 0x{icalls[target]:08X}u, 0x{return_address:08X}u, "
                    f"{len(arguments)}{values})")
        elif tail and getattr(self.function, "memory_stack", False):
            call = f"x86_jump({emitter.names[target]})"
        else:
            call = f"x86_call({emitter.names[target]}, 0x{return_address or 0:08X}u, {len(arguments)}{values})"
        results = [value for value in by_pointer] + ([returned] if returned is not None else [])
        if returned is not None and returned[1] == EAX:
            lines.append(f"{self.register_set(EAX)} = {call};")
        else:
            lines.append(call + ";")
        lines += [f"{self.register_set(value[1])} = {REGISTER_GLOBALS[value[1]]};"
                  for value in results if not (value is returned and value[1] == EAX) and value[1] != FLOAT0]
        if target in getattr(emitter, "float_returns", ()):
            # the float it hands back in st(0), off the recompiled code's stack, read or not
            read = any(value[1] == FLOAT0 for value in results)
            lines.append(f"{self.register_set(FLOAT0)} = x87_pop();" if read else "x87_pop();")
        return lines

    def statement(self, statement):
        if isinstance(statement, ir.Store) and isinstance(statement.value, ir.Op) \
                and statement.value.name in ("f.bits32", "f.bits64"):
            guest = getattr(self.emitter, "guest", None)
            if guest is not None and statement.value.name == "f.bits32" and statement.bits == 32:
                # a float symbols.txt names: NAME = value, rounded to a float as MEMF's is
                place = guest.float_place(statement.address, self.exact)
                if place is not None:
                    stored = ir.op("f.round32", (statement.value.args[0],), 64)
                    return [f"{place} = {self.expr(stored)};"]
            return super().statement(statement)     # a float or a double: MEMF(address) = value
        if isinstance(statement, ir.Store):
            target = self.memory(statement.address, statement.bits, id(statement))
            if target is not None and target[2]:
                return [self.assignment(target[0], statement, target[1])]
            guest = getattr(self.emitter, "guest", None)
            if guest is not None and isinstance(statement.address, ir.Const):
                named = guest.place(statement.address.value & 0xFFFFFFFF, statement.bits)
                if named is not None:
                    return [f"{named[0]} = {self.stored(statement.value, statement.bits)};"]
            element = guest.element(statement.address, statement.bits, self.exact) if guest is not None else None
            if element is not None:
                return [f"{element[0]} = {self.stored(statement.value, statement.bits)};"]
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
        # the one register the whole program shares: the guest's SP, g_esp, where a function's stack stays
        # in memory (stack.MEMORY_SP)
        super().__init__(functions, signatures, names, (MEMORY_SP,), set(), memory_, always, lambda address: 0)
        self.register_names = {MEMORY_SP: "g_esp"}
        self.layouts = layouts
        self.saved_locals = True
        self.flow = None
        self.recompiled = set()     # the functions called that stay recompiled (decompile.py)
        self.guest = None           # the game's memory by name (GuestNames, decompile.py)

    def restores_current(self, entry):
        return None, None

    def address_text(self, value):
        """(C, precedence) of a constant the C uses as a value that is the address of a place symbols.txt
        names (GuestNames.address), or None: the board's memories and ROM of the core's are not the Xbox's."""
        return self.guest.address(value & 0xFFFFFFFF) if self.guest is not None else None
