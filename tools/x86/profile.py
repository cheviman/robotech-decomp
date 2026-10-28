# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        profile.py
Description: what the decompiler's passes need to know about the Pentium III the game runs on
Version:     0.1.0
Created:     26-10-2026
Modified:    28-10-2026
Author:      Sebastian Toyos

The registers by their encoding's numbers (EAX 0, ECX 1, EDX 2, EBX 3, ESP 4, EBP 5, ESI 6, EDI 7), the
stack pointer ESP; the decompiler's own registers 32 (a stack kept in memory) and 33 (a call that returned
for its caller too) as for the V60 (tools/core/decompiler/stack.py). The flags the code branches on: ZF,
SF, OF and CF, as the decompiler's z, s, ov and cy. A function hands its result back in EAX.

The arguments a caller pushes are registers too, ARG0 up (arguments.py): the decompiler's passes take a
function's inputs and results from its registers, and the V60's code passes nothing on the stack.

The x87's registers are FLOAT0 up, one for each depth of its stack (x87.py): st(i) at an instruction
where the stack holds n values is FLOAT0 + n - 1 - i, a floating-point value of the function's own
(tools/core/decompiler/floats.py), f0 to f7 in the C.
"""
from decompiler import cpu

EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)
NAMES = {EAX: "eax", ECX: "ecx", EDX: "edx", EBX: "ebx", ESP: "esp", EBP: "ebp", ESI: "esi", EDI: "edi"}
ARG0 = 40           # the first argument on the stack; the n-th is ARG0 + n
ARGUMENTS = 32      # as many as a function may take
ARGS = tuple(range(ARG0, ARG0 + ARGUMENTS))
NAMES.update({ARG0 + n: f"arg{n}" for n in range(ARGUMENTS)})
FLOAT0 = ARG0 + ARGUMENTS
FLOATS = tuple(range(FLOAT0, FLOAT0 + 8))
NAMES.update({FLOAT0 + n: f"f{n}" for n in range(8)})
KEPT = (EAX, ECX, EDX, EBX, EBP, ESI, EDI, 32, 33) + ARGS + FLOATS

X86 = cpu.Profile(
    name="x86",
    registers=KEPT,
    sp=ESP,
    address_bits=32,
    flags=("z", "s", "ov", "cy"),
    return_address_bytes=4,
    interrupt_effects=(),
    result_register=EAX,
    register_bits={index: 64 if index in FLOATS else 32 for index in KEPT},
    register_names={**NAMES, 33: "left_caller"},
    flag_names={"z": "zero", "s": "negative", "ov": "overflow", "cy": "carry"},
    variable_names={**NAMES, 33: "left_caller"},
    invalid_jump="invalid_jump",
    float_registers=FLOATS,
)
