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
    py -3 tools/decompile.py write DIR  # their C, into DIR (not the build's)
    py -3 tools/decompile.py build      # their C into src/decompiled/, each in its recompiled version's
                                        # place (analysis/decompiled_functions.json: tools/hand_functions.py
                                        # hands them to the recompiler as the ones written by hand)
    py -3 tools/decompile.py subset LOW HIGH   # only the ones from LOW up to HIGH (hexadecimal), from
                                        # what build left in analysis/decompiled_cache.json

The functions of the XDK and Bink, and the ones written by hand (src/game/) or wrapped
(src/recomp_manual.c), are left as they are: a function that calls one of them is not decompiled yet.
"""
import argparse
import bisect
import glob
import collections
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TOOLS, "core"))
sys.path.insert(0, TOOLS)

from decompiler import cleanup, conditions, cpu, dataflow, expressions, knownbits, memory, pointers  # noqa: E402
from decompiler import preserved, signatures, stack, structure                                      # noqa: E402
from decompiler import emit as core_emit                                                            # noqa: E402
from decompiler.gotos import GotoError                                                              # noqa: E402
from v60 import ir                                                       # noqa: E402
from x86 import arguments, disassembler, function, lift                  # noqa: E402
from x86 import emit                                                     # noqa: E402
from x86.profile import ARG0, ARGUMENTS, EAX, X86                        # noqa: E402

import hand_functions                                                    # noqa: E402
import symbols                                                           # noqa: E402

GAME_CODE_END = 0x00147000    # the game's and the engine's code; past it the C runtime and XAPI
REPO = os.path.dirname(TOOLS)
BUILD_DIR = os.path.join(REPO, "src", "decompiled")
DECOMPILED_JSON = os.path.join(REPO, "analysis", "decompiled_functions.json")
DECOMPILED_SIGNATURES = os.path.join(REPO, "analysis", "decompiled_signatures.json")
DECOMPILED_CACHE = os.path.join(REPO, "analysis", "decompiled_cache.json")
MANUAL = os.path.join(REPO, "src", "recomp_manual.c")
REGISTER_GLOBALS = {0: "g_eax", 1: "g_ecx", 2: "g_edx", 3: "g_ebx", 5: "g_ebp", 6: "g_esi", 7: "g_edi"}


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


def left_alone(sym):
    """The functions the decompiler leaves as they are: the XDK's and Bink's (by their files), and the ones
    written by hand or wrapped."""
    files = sorted(sym["files"])
    starts = [address for address, _, _ in files]
    names = {name: address for address, name in sym["func"].items()}
    found = set(hand_functions.hand_functions()[0])
    # and the ones the C written by hand calls as recompiled code (CALL(vcQuadtreeRemove, ...)), or the
    # bridges by name: in C they would need their calls changed
    written = set()
    paths = glob.glob(os.path.join(REPO, "src", "game", "**", "*.c"), recursive=True)
    for path in paths + glob.glob(os.path.join(REPO, "src", "*.c")):
        written |= set(re.findall(r"\b[A-Za-z_]\w*\b", open(path, encoding="utf-8", errors="replace").read()))
    found |= {address for name, address in names.items() if name in written}
    for name in re.findall(r"(?m)^\w[\w \*]*?\b(\w+)\s*\(void\)\s*$", open(MANUAL, encoding="utf-8").read()):
        if name in names:
            found.add(names[name])

    def subject(address):
        position = bisect.bisect_right(starts, address) - 1
        return files[position][1] if position >= 0 else ""
    return found, subject


def overlapping_slots(f):
    """Whether two of a function's stack slots share bytes without being the same slot (a byte of a word
    the code wrote whole): the decompiler takes each slot for a variable of its own, so the C would not see
    the one change the other."""
    spans = set()
    for block in f.blocks.values():
        for statement in block.statements + [block.end]:
            if isinstance(statement, ir.SetStack):
                spans.add((statement.offset, statement.bits // 8))
            for expression in ir.statement_expressions(statement):
                for node in ir.walk(expression):
                    if isinstance(node, ir.Stack):
                        spans.add((node.offset, node.bits // 8))
    ordered = sorted(spans)
    for (offset, size), (next_offset, next_size) in zip(ordered, ordered[1:]):
        if next_offset < offset + size:
            return True
    return False


def lifted_closed(program, names, skip=frozenset(), subject=None):
    """The functions lifted with their stack in slots whose calls all go to such functions:
    {entry: Function}, their stacks analysed; but for those in 'skip', and those 'subject' says are the
    XDK's or Bink's."""
    builder = function.Builder(program)
    slotted, calls = {}, {}
    for entry in game_entries(program):
        if entry in skip or (subject is not None and subject(entry).startswith(("xdk/", "bink/"))):
            continue
        try:
            built = builder.build(entry)
        except lift.Unsupported:
            continue
        stack.analyse(built)
        if getattr(built, "memory_stack", False) or overlapping_slots(built):
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


def analyse(quiet=False, for_build=False):
    cpu.use(X86)
    dataflow.configure()
    dataflow.HANDLER_SLOTS = (None,)    # no object loop calls handlers through a field of its objects
    signatures.CONTEXT = ()
    sym = symbols.load()
    names = sym["func"]
    program = disassembler.Program(names)
    if for_build:
        skip, subject = left_alone(sym)
        built = lifted_closed(program, names, skip, subject)
    else:
        built = lifted_closed(program, names)
    counts = arguments.counts(built)
    try:
        arguments.rewrite(built, counts)
    except arguments.Straddles as problem:
        raise SystemExit(str(problem))
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
    flow.conditions_recovered = changed
    if quiet:
        return program, built, flow, found
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


class NoNames:
    """symbols.txt as the decompiler's writer reads it (tools/core/disassemble.py's Names): nothing yet
    names the game's memory, its structures or its functions' parameters and locals."""
    def __init__(self):
        self.structs, self.variables, self.tables, self.hardware, self.ports = {}, {}, {}, {}, {}
        self.fields, self.param_structs, self.local_structs, self.targets = {}, {}, {}, {}
        self.comments, self.params, self.results, self.locals = {}, {}, {}, {}
        self.rom_structs, self.arrays, self.record_tables, self.field_arrays = set(), {}, {}, {}
        self.scoped, self.overlays, self.scoped_overlays = {}, {}, {}


def call_results(function, found, flow):
    """For each call of 'function': the registers the C call hands back (through result pointers); as
    tools/core/decompile.py's."""
    results = {}
    for block in function.blocks.values():
        for statement in block.statements:
            if isinstance(statement, ir.Call):
                registers = set()
                if statement.slot is None:
                    for target in flow.call_targets(statement):
                        registers |= {value[1] for value in found[target].results if value[0] == "r"}
                results[id(statement)] = registers
    return results


def entry_text(emitter, entry, drops):
    """NAME_entry, the function as the recompiled code calls it: its arguments from the guest's stack
    (ARG32) and registers, its result into EAX, the return address (and, for one that drops its own
    arguments, those) popped. None when it takes or hands back a flag, which the recompiled code keeps
    in its own way."""
    values = []
    for value in emitter.by_value(entry):
        if value[0] != "r":
            return None
        index = value[1]
        if index in REGISTER_GLOBALS:
            values.append(REGISTER_GLOBALS[index])
        elif ARG0 <= index < ARG0 + ARGUMENTS:
            values.append("ARG32(%d)" % (index - ARG0))
        else:
            return None
    lines = ["void %s_entry(void)" % emitter.names[entry], "{"]
    copies = []
    for value in emitter.by_pointer(entry):
        if value[0] != "r" or value[1] not in REGISTER_GLOBALS:
            return None
        local = "%s_out" % REGISTER_GLOBALS[value[1]][2:]
        lines.append("\tuint32_t %s = %s;" % (local, REGISTER_GLOBALS[value[1]]))
        values.append("&" + local)
        copies.append("\t%s = %s;" % (REGISTER_GLOBALS[value[1]], local))
    call = "%s(%s);" % (emitter.names[entry], ", ".join(values))
    returned = emitter.returned(entry)
    if returned is not None:
        if returned[0] != "r" or returned[1] not in REGISTER_GLOBALS:
            return None
        call = "%s = %s" % (REGISTER_GLOBALS[returned[1]], call)
    lines.append("\t" + call)
    lines += copies
    lines.append("\tg_esp += %du;" % (4 + drops))
    lines.append("}")
    return "\n".join(lines) + "\n"


def file_header(name, description):
    return ("/**\n *    Name:        %s\n *    Description: %s\n *    Version:     0.1.0\n"
            " *    Created:     26-10-2026\n *    Modified:    26-10-2026\n *    Author:      Sebastian Toyos\n"
            " *\n *    Written by tools/decompile.py: edit the tool or symbols/symbols.txt, never this file.\n */\n"
            % (name, description))


def write(out_dir, for_build=False):
    program, built, flow, found = analyse(quiet=True, for_build=for_build)
    sym = symbols.load()
    names = {entry: program.functions[entry][1] for entry in built}
    arguments_by_value = {}
    for entry, signature in found.items():
        registers = {value[1] for value in signature.params - signature.results if value[0] == "r"}
        returned = next(iter(signature.results)) if len(signature.results) == 1 else None
        if returned is not None and returned[0] == "r" and returned in signature.params:
            registers.add(returned[1])
        arguments_by_value[entry] = registers
    whole = set()
    live_after, live_at_start = {}, {}
    for entry, f in built.items():
        after, start = cleanup.eliminate(flow, f, found[entry].results, (), arguments_by_value)
        expressions.tidy(f, flow, after, whole)
        results_of_calls = call_results(f, found, flow)
        if expressions.propagate_constants(f, results_of_calls, ()):
            after, start = cleanup.eliminate(flow, f, found[entry].results, (), arguments_by_value)
            expressions.tidy(f, flow, after, whole)
        if expressions.inline_registers(f, flow, after, whole):
            expressions.simplify_function(f)
        if expressions.switch_values(f, flow):
            after, start = cleanup.eliminate(flow, f, found[entry].results, (), arguments_by_value)
            expressions.tidy(f, flow, after, whole)
        knownbits.simplify(f, found[entry], (), results_of_calls)
        expressions.simplify_function(f)
        live_after[entry], live_at_start[entry] = after, start
    emit.use_memory_map()
    known = NoNames()
    typing = pointers.Program(built, flow, found, {entry: call_results(f, found, flow) for entry, f in built.items()},
                              (), known.targets, {}, {})
    fields, accesses = typing.run()
    named = memory.Memory(known, memory.accesses_of(built.values()), {})
    always = {entry: set(summary.always) for entry, summary in flow.summaries.items()}
    emitter = emit.X86Emitter(built, found, names, named, always, pointers.Layouts(accesses, known))
    emitter.writes = {entry: set(summary.writes) for entry, summary in flow.summaries.items()}
    emitter.flow = flow
    emitter.comments = dict(sym["comments"])
    for entry, f in built.items():
        structure.split_loop_entries(f, (live_after[entry], fields[entry]))
    texts, problems = {}, collections.Counter()
    examples = {}
    for entry, f in built.items():
        writer = emit.X86Writer(emitter, f, live_after[entry], fields[entry], live_at_start[entry])
        try:
            texts[entry] = writer.write()
        except (core_emit.EmitError, GotoError, ValueError, KeyError, AttributeError, TypeError) as problem:
            key = "%s: %s" % (type(problem).__name__, str(problem).split(":")[-1].strip()[:60])
            problems[key] += 1
            examples.setdefault(key, entry)
    if for_build:
        texts, entries = for_the_build(program, built, emitter, texts)
        cache = {}
        for entry in texts:
            f = built[entry]
            calls = {statement.target for block in f.blocks.values() for statement in block.statements
                     if isinstance(statement, ir.Call)}
            calls |= {block.end.target for block in f.blocks.values() if isinstance(block.end, ir.TailCall)}
            by_value = emitter.by_value(entry)
            cache["0x%08X" % entry] = {
                "name": emitter.names[entry], "prototype": emitter.prototype(entry), "text": texts[entry],
                "entry_text": entries.get(entry), "calls": ["0x%08X" % c for c in sorted(calls)],
                "registers": [REGISTER_GLOBALS[value[1]] for value in by_value if value[1] in REGISTER_GLOBALS],
                "arguments": sum(1 for value in by_value if ARG0 <= value[1] < ARG0 + ARGUMENTS),
                "by_pointer": len(emitter.by_pointer(entry)), "drops": f.drops or 0}
        with open(DECOMPILED_CACHE, "w") as out:
            json.dump(cache, out)
        write_build_files(cache, set(cache))
        gotos = sum(text.count("goto ") for text in texts.values())
        print("%d functions written to %s (%d gotos), %d not" % (len(texts), out_dir, gotos, len(built) - len(texts)))
        for key, count in problems.most_common(15):
            print("  %5d  %s  e.g. %08X" % (count, key, examples[key]))
        return
    entries = {}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "decompiled.h"), "w", encoding="ascii", newline="\n") as out:
        out.write(file_header("decompiled.h", "the game's functions the decompiler writes, by their prototypes"))
        out.write("#ifndef DECOMPILED_H\n#define DECOMPILED_H\n\n#include \"decomp.h\"\n#include \"x86.h\"\n\n")
        out.write("\n".join(emitter.prototype(entry) + ";" for entry in texts) + "\n\n#endif\n")
    with open(os.path.join(out_dir, "decompiled.c"), "w", encoding="ascii", errors="replace", newline="\n") as out:
        out.write(file_header("decompiled.c", "the game's functions the decompiler writes so far, and the entries "
                              "the recompiled code calls them by"))
        out.write("#include \"decompiled.h\"\n\n")
        out.write("\n".join(texts[entry] for entry in texts))
        out.write("\n" + "\n".join(entries[entry] for entry in sorted(entries)))
    if for_build:
        with open(DECOMPILED_JSON, "w") as out:
            json.dump({"0x%08X" % entry: emitter.names[entry] + "_entry" for entry in sorted(entries)}, out, indent=1)
        # what tools/verify_c.py --decompiled needs to call each as the original is called
        described = {}
        for entry in sorted(entries):
            by_value = emitter.by_value(entry)
            described["0x%08X" % entry] = {
                "entry": emitter.names[entry] + "_entry",
                "registers": [REGISTER_GLOBALS[value[1]] for value in by_value if value[1] in REGISTER_GLOBALS],
                "arguments": sum(1 for value in by_value if ARG0 <= value[1] < ARG0 + ARGUMENTS),
                "by_pointer": len(emitter.by_pointer(entry)),
                "drops": built[entry].drops or 0}
        with open(DECOMPILED_SIGNATURES, "w") as out:
            json.dump(described, out, indent=1)
    gotos = sum(text.count("goto ") for text in texts.values())
    print("%d functions written to %s (%d gotos), %d not" % (len(texts), out_dir, gotos, len(built) - len(texts)))
    for key, count in problems.most_common(15):
        print("  %5d  %s  e.g. %08X" % (count, key, examples[key]))


def write_build_files(cache, chosen):
    """src/decompiled/ and the lists of the functions in it (analysis/decompiled_functions.json, and
    decompiled_signatures.json for tools/verify_c.py) from the cache tools/decompile.py build keeps:
    the ones of 'chosen' (addresses as the cache writes them) whose calls all reach others chosen."""
    keep = set(chosen) & set(cache)
    changed = True
    while changed:
        changed = False
        for key in sorted(keep):
            if not set(cache[key]["calls"]) <= keep:
                keep.discard(key)
                changed = True
    ordered = sorted(keep, key=lambda key: int(key, 16))
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(os.path.join(BUILD_DIR, "decompiled.h"), "w", encoding="ascii", newline="\n") as out:
        out.write(file_header("decompiled.h", "the game's functions the decompiler writes, by their prototypes"))
        out.write("#ifndef DECOMPILED_H\n#define DECOMPILED_H\n\n#include \"decomp.h\"\n#include \"x86.h\"\n\n")
        out.write("\n".join(cache[key]["prototype"] + ";" for key in ordered) + "\n\n#endif\n")
    with open(os.path.join(BUILD_DIR, "decompiled.c"), "w", encoding="ascii", errors="replace", newline="\n") as out:
        out.write(file_header("decompiled.c", "the game's functions the decompiler writes so far, and the entries "
                              "the recompiled code calls them by"))
        out.write("#include \"decompiled.h\"\n\n")
        out.write("\n".join(cache[key]["text"] for key in ordered))
        out.write("\n" + "\n".join(cache[key]["entry_text"] for key in ordered))
    with open(DECOMPILED_JSON, "w") as out:
        json.dump({key: cache[key]["name"] + "_entry" for key in ordered}, out, indent=1)
    with open(DECOMPILED_SIGNATURES, "w") as out:
        json.dump({key: {"entry": cache[key]["name"] + "_entry", "registers": cache[key]["registers"],
                         "arguments": cache[key]["arguments"], "by_pointer": cache[key]["by_pointer"],
                         "drops": cache[key]["drops"]} for key in ordered}, out, indent=1)
    return ordered


def subset(low, high):
    """The build's decompiled functions narrowed to those from 'low' up to 'high', from the cache (to
    find the one that changes a scenario's frames, a half at a time)."""
    cache = json.load(open(DECOMPILED_CACHE))
    chosen = {key for key in cache if low <= int(key, 16) < high}
    ordered = write_build_files(cache, chosen)
    print("%d of the %d functions in src/decompiled/, %s up to %s" %
          (len(ordered), len(cache), ordered[0] if ordered else "-", ordered[-1] if ordered else "-"))


def for_the_build(program, built, emitter, texts):
    """The functions that go into the build and their entries: the ones written whose calls all reach
    others that go in, and that the recompiled code calls only if what they take was worked out with it
    (signatures.OPEN: every input a parameter, EAX handed back) and their entry can be made."""
    keep = set(texts)
    entries = {}
    changed = True
    while changed:
        changed = False
        for entry in sorted(keep):
            f = built[entry]
            calls = {statement.target for block in f.blocks.values() for statement in block.statements
                     if isinstance(statement, ir.Call)}
            calls |= {block.end.target for block in f.blocks.values() if isinstance(block.end, ir.TailCall)}
            # every one gets an entry: the recompiler leaves out its body and lists the entry in its
            # dispatch; the recompiled code calls only those of signatures.OPEN
            outside = entry not in signatures.OPEN and any(caller not in keep for caller in program.callers.get(entry, ()))
            text = entry_text(emitter, entry, f.drops or 0)
            if not calls <= keep or outside or text is None:
                keep.discard(entry)
                entries.pop(entry, None)
                changed = True
            elif text is not None:
                entries[entry] = text
    return ({entry: texts[entry] for entry in sorted(keep)},
            {entry: entries[entry] for entry in sorted(keep) if entry in entries})


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
    parser.add_argument("command", choices=["check", "analyse", "write", "build", "subset"])
    parser.add_argument("out_dir", nargs="?")
    parser.add_argument("high", nargs="?")
    args = parser.parse_args()
    if args.command == "check":
        check()
    elif args.command == "analyse":
        analyse()
    elif args.command == "build":
        write(BUILD_DIR, for_build=True)
    elif args.command == "subset":
        subset(int(args.out_dir, 16), int(args.high, 16))
    else:
        if not args.out_dir:
            parser.error("write needs the folder the C goes to")
        write(args.out_dir)


if __name__ == "__main__":
    main()
