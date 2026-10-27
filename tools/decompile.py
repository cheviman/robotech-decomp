"""
Name:        decompile.py
Description: the game's functions decompiled to C by arcade-decomp's decompiler (tools/core) through the
             x86 frontend (tools/x86)
Version:     0.1.0
Created:     26-10-2026
Modified:    26-10-2026
Author:      Sebastian Toyos

The recompiled C (xboxrecomp) runs the game an instruction at a time; this is its way to C a person reads:
the game's code lifted to the decompiler's IR, its stack turned into slots, its data flow and structure
found, and the C written from that. It grows a step at a time, each checked against the game:

    py -3 tools/decompile.py check      # lift every function of the game's code and follow its stack;
                                        # what does not lift yet, by reason
    py -3 tools/decompile.py analyse    # the data flow and the signatures of the functions whose calls
                                        # all go to functions lifted with their stack in slots

Nothing it makes goes into the build yet.
"""
import argparse
import collections
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TOOLS, "core"))
sys.path.insert(0, TOOLS)

from decompiler import conditions, cpu, dataflow, preserved, signatures, stack  # noqa: E402  (tools/core)
from v60 import ir                                                       # noqa: E402
from x86 import arguments, disassembler, function, lift                  # noqa: E402
from x86.profile import EAX, X86                                         # noqa: E402

import symbols                                                           # noqa: E402

GAME_CODE_END = 0x00147000    # the game's and the engine's code; past it the C runtime and XAPI


def game_entries(program):
    return sorted(entry for entry, (end, name, section) in program.functions.items()
                  if section == ".text" and entry < GAME_CODE_END)


def check():
    cpu.use(X86)
    names = symbols.load()["func"]
    program = disassembler.Program(names)
    builder = function.Builder(program)
    reasons = collections.Counter()
    examples = {}
    lifted, stacked, instructions = {}, 0, 0
    entries = game_entries(program)
    for entry in entries:
        try:
            built = builder.build(entry)
        except lift.Unsupported as problem:
            reason = str(problem).split(" ", 1)[0] if " " in str(problem) else str(problem)
            key = classify(str(problem))
            reasons[key] += 1
            examples.setdefault(key, (entry, str(problem)))
            continue
        lifted[entry] = built
        instructions += sum(len(block.addresses) for block in built.blocks.values())
        try:
            stack.analyse(built)
            stacked += 1
        except stack.StackError as problem:
            key = "stack: " + str(problem).split(":")[0]
            reasons[key] += 1
            examples.setdefault(key, (entry, str(problem)))
    print("%d functions of the game's code: %d lift (%d instructions), %d with their stack followed"
          % (len(entries), len(lifted), instructions, stacked))
    for key, count in reasons.most_common():
        entry, text = examples[key]
        print("  %5d  %-40s e.g. %08X %s" % (count, key, entry, text[:70]))


class Analysis:
    """What the decompiler's data flow asks of the program's analysis: the code pointers the program stores
    (none followed yet, so no call through a pointer lifts)."""
    pointer_writes = ()
    table_writes = ()
    pointer_tables = {}
    symbols = {}
    table_targets = {}


def lifted_closed(program, names):
    """The functions lifted with their stack in slots whose calls all go to such functions:
    {entry: Function}, their stacks analysed."""
    builder = function.Builder(program)
    slotted, calls = {}, {}
    for entry in game_entries(program):
        try:
            built = builder.build(entry)
        except lift.Unsupported:
            continue
        stack.analyse(built)
        if getattr(built, "memory_stack", False):
            continue
        slotted[entry] = built
        calls[entry] = {statement.target for block in built.blocks.values() for statement in block.statements
                        if isinstance(statement, ir.Call)}
        calls[entry] |= {block.end.target for block in built.blocks.values() if isinstance(block.end, ir.TailCall)}
    closed = set(slotted)
    changed = True
    while changed:
        changed = False
        for entry in list(closed):
            if not calls[entry] <= closed:
                closed.discard(entry)
                changed = True
    return {entry: slotted[entry] for entry in sorted(closed)}


def called_from_outside(program, entry, built):
    """Whether code that is not in 'built' calls or jumps to 'entry', or nothing does."""
    callers = program.callers.get(entry, ())
    return not callers or any(caller not in built for caller in callers)


def analyse():
    cpu.use(X86)
    dataflow.configure()
    dataflow.HANDLER_SLOTS = (None,)    # no object loop calls handlers through a field of its objects
    signatures.CONTEXT = ()
    names = symbols.load()["func"]
    program = disassembler.Program(names)
    built = lifted_closed(program, names)
    counts = {entry: arguments.count(f) for entry, f in built.items()}
    arguments.rewrite(built, counts)
    flow = dataflow.Program(built, Analysis(), [], ())
    # a function the recompiled code calls (or nothing does) takes all it reads, and hands back EAX, as the
    # original leaves it for the recompiled callers
    signatures.OPEN = {entry for entry in built if called_from_outside(program, entry, built)}
    flow.declared = {entry: {EAX} for entry in signatures.OPEN}
    flow.solve()
    while sum(len(preserved.analyse(f, flow.call_writes)) for f in built.values()):
        flow.solve()
    changed = sum(conditions.recover(f, flow) for f in built.values())
    if changed:
        flow.reset()
        flow.solve()
    found = signatures.compute(flow)
    print("%d functions analysed, %d conditions recovered" % (len(built), changed))
    for entry in list(built)[:0] + [e for e in built if e in names][:25]:
        signature = found[entry]
        print("  %-28s args %d  in %s  out %s" % (names.get(entry, "%08X" % entry), counts[entry],
                                                 describe(signature.params), describe(signature.results)))
    return program, built, flow, found


def describe(values):
    out = []
    for value in sorted(values, key=str):
        if value[0] == "r":
            out.append(cpu.current.register_names.get(value[1], "r%d" % value[1]))
        else:
            out.append(value[1])
    return ",".join(out) or "-"


def classify(text):
    """What kind of thing did not lift: the mnemonic, or the kind of jump or call."""
    words = text.split()
    if text.startswith(("a call to", "a jump to", "a branch out", "returns that")):
        return " ".join(words[:3])
    if words and words[0] in ("call", "jmp"):
        return words[0] + " through a pointer"
    if words and words[0] in ("condition", "register", "segment"):
        return " ".join(words[:2])
    return words[0] if words else text


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check", "analyse"])
    args = parser.parse_args()
    if args.command == "check":
        check()
    else:
        analyse()


if __name__ == "__main__":
    main()
