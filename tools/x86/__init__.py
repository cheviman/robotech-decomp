# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        __init__.py
Description: the x86 frontend of the decompiler: the game's code decoded and lifted to the IR of
             arcade-decomp's decompiler (tools/core)
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

disassembler.py decodes the game's functions (the ones xboxrecomp's disassembler found,
analysis/disasm/functions.json) with Capstone; lift.py turns each instruction into IR statements;
function.py makes each function a graph of IR blocks, as tools/core/z80 does for the Z80. profile.py
tells the decompiler's passes about the processor (tools/core/decompiler/cpu.py).
"""
