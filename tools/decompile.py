"""
Name:        decompile.py
Description: the game's functions decompiled to C by arcade-decomp's decompiler (tools/core) through the
             x86 frontend (tools/x86)
Version:     0.2.0
Created:     26-10-2026
Modified:    27-10-2026
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
(src/recomp_manual.c), are left as they are. The decompiled C calls them, and every other function that
stays recompiled (the x87's, the ones that call through a pointer...), as the recompiled code does: the
registers it reads in the globals, its arguments on the guest's stack (x86_call, src/decompiled/x86.h),
its results read back; what each reads, writes and takes is read from its machine code
(tools/x86/recompiled.py). A function that calls one whose effects that cannot say stays recompiled.
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
from x86 import arguments, disassembler, function, lift, recompiled      # noqa: E402
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
ICALL_SITES = os.path.join(REPO, "analysis", "icall_sites.json")
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


def lifted(program, chosen, skip=frozenset(), subject=None):
    """The functions of 'chosen' (all of the game's code when None) lifted with their stack in slots:
    {entry: Function}, their stacks analysed; but for those in 'skip', and those 'subject' says are the
    XDK's or Bink's."""
    builder = function.Builder(program)
    slotted = {}
    for entry in game_entries(program) if chosen is None else sorted(chosen):
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
    return slotted


def calls_of(f):
    """(the calls of a function, its tail calls): [(target, return address)], [target]."""
    calls = [(statement.target, statement.return_address) for block in f.blocks.values()
             for statement in block.statements if isinstance(statement, ir.Call)]
    tails = [block.end.target for block in f.blocks.values() if isinstance(block.end, ir.TailCall)]
    return calls, tails


def call_targets_seen():
    """{call site: the functions a run saw a call through a pointer there reach} (xboxrecomp's icall
    feedback): recompiled.py takes what they drop."""
    if not os.path.exists(ICALL_SITES):
        return {}
    sites = json.load(open(ICALL_SITES))
    return {int(site, 16): [int(target, 16) for target in found["targets"] if int(target, 16) < 0xFE000000]
            for site, found in sites.items()}


def site_count(program, caller, return_address, summary):
    """How many words a call hands a function that counts its arguments by its callers (escapes): what the
    caller drops after it ("add esp, N", or "pop ecx" a word at a time), or what the callee drops itself;
    None when neither says."""
    if summary.drops:
        return summary.drops // 4
    instructions = program.function(caller).instructions
    following = instructions.get(return_address)
    if following is not None and following.mnemonic == "add" and following.operands[0].kind == "reg" \
            and following.operands[0].reg == "esp" and following.operands[1].kind == "imm":
        return following.operands[1].imm // 4
    words = 0
    while following is not None and following.mnemonic == "pop" and following.operands[0].kind == "reg" \
            and following.operands[0].reg == "ecx":
        words += 1
        following = instructions.get(following.next)
    return words or None


def outside_problem(program, builder, caller, target, return_address, summary, tail):
    """Why the decompiled C cannot call 'target', a function left recompiled, from 'caller'; None if it can."""
    if summary is None or not summary.known:
        return "calls a function whose effects are not known"
    if builder.drops(target) != summary.drops:
        return "calls a function that drops otherwise than its returns say"
    if summary.arguments > ARGUMENTS:
        return "calls a function that takes too many arguments"
    if summary.escapes and (tail or site_count(program, caller, return_address, summary) is None):
        return "calls a function that counts its arguments by its callers, with no count"
    return None


class Flow(dataflow.Program):
    """The decompiler's data flow (tools/core/decompiler/dataflow.py) over the functions decompiled, with
    the ones they call that stay recompiled known by summaries of their own ('outside': entry ->
    dataflow.Summary, from recompiled.py), which the analysis never changes."""

    def __init__(self, functions, analysis, outside):
        super().__init__(functions, analysis, [], ())
        self.outside = outside

    def summary_of(self, target):
        found = self.summaries.get(target)
        return found if found is not None else self.outside.get(target)

    def combine(self, targets):
        reads, writes = set(), set()
        always = None
        for target in targets:
            summary = self.summary_of(target)
            if summary is None:
                continue
            reads |= summary.reads
            writes |= summary.writes
            always = set(summary.always) if always is None else always & summary.always
        return reads, writes, always or set()

    def target_reads(self, targets, live_after):
        reads = set()
        for target in targets:
            summary = self.summary_of(target)
            if summary is None:
                continue
            reads |= summary.base
            for variable in live_after & summary.writes:
                found = summary.passes.get((variable[0], variable[1]))
                reads |= summary.reads if found is None else found
        return reads

    def outcome_kills(self, call, mask, zero):
        if call.slot is not None:
            return set()
        always = None
        for target in self.call_targets(call):
            summary = self.summary_of(target)
            if summary is None:
                continue
            outcome = summary.always_when.get((mask, zero))
            if outcome is None:
                outcome = summary.always
            always = set(outcome) if always is None else always & outcome
        return always or set()


class Typing(pointers.Program):
    """The core's pointer typing (tools/core/decompiler/pointers.py) over the functions decompiled: what
    a caller passes a function that stays recompiled goes nowhere, since there is no C of it to type."""

    def tell_callee(self, target, state):
        if target in self.functions:
            super().tell_callee(target, state)


def outside_summary(summary, count):
    """A function left recompiled as the data flow sees it: it reads its inputs and its arguments (ARG0
    up); a register it may leave as it was it reads only when the caller reads it afterwards (passes);
    it writes the flags on every way back (no caller reads them after a call: decompile.py checks)."""
    found = dataflow.Summary()
    base = {("r", register, part) for register, part in summary.inputs}
    base |= {("r", ARG0 + n, part) for n in range(count) for part in range(3)}
    found.base = base
    found.writes = {("r", register, part) for register, part in summary.writes}
    found.always = {("r", register, part) for register, part in summary.always} | set(dataflow.FLAGS)
    found.reads = base | (found.writes - found.always)
    found.passes = {}
    for register, _ in summary.writes:
        key = ("r", register)
        kept = {("r", register, part) for part in range(3)} - found.always
        found.passes[key] = base | kept
    found.always_when = {}
    return found


def called_from_outside(program, entry, built):
    """Whether code that is not in 'built' calls or jumps to 'entry', or nothing does."""
    callers = program.callers.get(entry, ())
    return not callers or any(caller not in built for caller in callers)


SITES = 0x00F00000     # where the calls of a function that counts its arguments by its callers go, one each


def analyse(quiet=False, for_build=False):
    """The functions decompiled, their data flow solved: (program, built, flow, found). A function goes in
    when it lifts with its stack in slots and each function it calls is decompiled too or stays
    recompiled with its effects known (recompiled.py); a call of one of those is a call of the recompiled
    code (emit.py). flow.outside: the functions called that stay recompiled, by their summaries;
    flow.aliases: for a call of one that counts its arguments by its callers, the target of its own
    (SITES up) that stands for it, and the function."""
    cpu.use(X86)
    dataflow.configure()
    dataflow.HANDLER_SLOTS = (None,)    # no object loop calls handlers through a field of its objects
    signatures.CONTEXT = ()
    sym = symbols.load()
    names = sym["func"]
    program = disassembler.Program(names)
    skip, subject = left_alone(sym) if for_build else (frozenset(), None)
    summaries = recompiled.Summaries(program, call_targets_seen())
    builder = function.Builder(program)
    chosen = None
    while True:
        built = lifted(program, chosen, skip, subject)
        changed = True
        while changed:
            changed = False
            calls = {entry: calls_of(f) for entry, f in built.items()}
            summaries.compute(set(built) | {target for found, _ in calls.values() for target, _ in found}
                              | {target for _, tails in calls.values() for target in tails})
            for entry, (found, tails) in calls.items():
                # its own machine code has to come out even too: a piece of another function's code the
                # disassembler took for one (sub_0001166C, "pop edi" of a register its jumper saved, then
                # "ret") does not, and its C would leave ESP where the original does not
                own = summaries.found.get(entry)
                problems = ["is no function of its own"] if own is None or not own.known or \
                    own.drops != builder.drops(entry) else []
                problems += [outside_problem(program, builder, entry, target, address, summaries.found.get(target), False)
                             for target, address in found if target not in built]
                problems += [outside_problem(program, builder, entry, target, None, summaries.found.get(target), True)
                             for target in tails if target not in built]
                if any(problems):
                    del built[entry]
                    changed = True
        # the calls of the ones that count their arguments by their callers, each a target of its own
        aliases, outside_counts = {}, {}
        for entry, f in built.items():
            for block in f.blocks.values():
                for statement in block.statements:
                    if isinstance(statement, ir.Call) and statement.target not in built:
                        summary = summaries.found[statement.target]
                        if summary.escapes:
                            alias = SITES + len(aliases)
                            aliases[alias] = statement.target
                            outside_counts[alias] = max(summary.arguments,
                                                        site_count(program, entry, statement.return_address, summary))
                            statement.target = alias
                        else:
                            outside_counts[statement.target] = summary.arguments
                if isinstance(block.end, ir.TailCall) and block.end.target not in built:
                    outside_counts[block.end.target] = summaries.found[block.end.target].arguments
        counts = arguments.counts(built, outside_counts)
        try:
            arguments.rewrite(built, {**outside_counts, **counts})
        except arguments.Straddles as problem:
            raise SystemExit(str(problem))
        flow = Flow(built, Analysis(), {target: outside_summary(summaries.found[aliases.get(target, target)], count)
                                        for target, count in outside_counts.items()})
        flow.aliases = aliases
        flow.recompiled = summaries
        # a function the recompiled code calls (or nothing does) takes all it reads, and hands back EAX, as
        # the original leaves it for the recompiled callers
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
        # a flag read after a call of a recompiled function, which the C does not hand back: the caller
        # stays recompiled, and the analysis goes again without it
        flagged = {entry for entry in built for call, live in flow.live_after_calls(entry)
                   if call.target in flow.outside and any(variable[0] == "f" for variable in live)}
        if not flagged:
            break
        chosen = set(built) - flagged
    outside_signatures(flow, built, found)
    # what writes the C from here (pointers.py, emit.py) looks a callee up among the summaries; the
    # analysis, which works the summaries of its own functions out, is done
    for target, summary in flow.outside.items():
        flow.summaries.setdefault(target, summary)
    if quiet:
        return program, built, flow, found
    print("%d functions analysed, %d conditions recovered" % (len(built), changed))
    for entry in list(built)[:0] + [e for e in built if e in names][:25]:
        signature = found[entry]
        print("  %-28s args %d  in %s  out %s" % (names.get(entry, "%08X" % entry), counts[entry],
                                                 describe(signature.params), describe(signature.results)))
    return program, built, flow, found


def outside_signatures(flow, built, found):
    """The signatures of the functions called that stay recompiled, into 'found': what they read for
    themselves (their arguments too) are their parameters; what some caller reads after a call, of what
    they may write, their results (a register they may leave as it was goes in and out)."""
    results = {target: set() for target in flow.outside}
    for entry, f in built.items():
        for call, live in flow.live_after_calls(entry):
            if call.slot is None and call.target in flow.outside:
                results[call.target] |= signatures.scratch(live & flow.outside[call.target].writes)
        leaving = flow.exit_live.get(entry, frozenset())
        for block in f.blocks.values():
            if isinstance(block.end, ir.TailCall) and block.end.target in flow.outside:
                results[block.end.target] |= signatures.scratch(leaving & flow.outside[block.end.target].writes)
    for target, summary in flow.outside.items():
        signature = signatures.Signature()
        signature.params = signatures.scratch(summary.base)
        signature.results = results[target]
        found[target] = signature


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


def entry_text(emitter, entry, drops, keeps=False):
    """NAME_entry, the function as the recompiled code calls it: its arguments from the guest's stack
    (ARG32) and registers, its result into EAX, the return address (and, for one that drops its own
    arguments, those) popped. None when it takes or hands back a flag, which the recompiled code keeps
    in its own way. 'keeps': it calls recompiled code (itself or through the decompiled functions it
    calls), handing registers in the globals: EBX, EBP, ESI and EDI go back as they came, as the
    original's pops put them back, but for the ones it hands back."""
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
    handed = {value[1] for value in emitter.by_pointer(entry)}
    returned = emitter.returned(entry)
    if returned is not None:
        handed.add(returned[1])
    kept = [register for register in (3, 5, 6, 7) if register not in handed] if keeps else []
    if kept:
        lines.append("\tuint32_t " + ", ".join("%s_kept = %s" % (REGISTER_GLOBALS[register][2:], REGISTER_GLOBALS[register])
                                               for register in kept) + ";")
    for value in emitter.by_pointer(entry):
        if value[0] != "r" or value[1] not in REGISTER_GLOBALS:
            return None
        local = "%s_out" % REGISTER_GLOBALS[value[1]][2:]
        lines.append("\tuint32_t %s = %s;" % (local, REGISTER_GLOBALS[value[1]]))
        values.append("&" + local)
        copies.append("\t%s = %s;" % (REGISTER_GLOBALS[value[1]], local))
    call = "%s(%s);" % (emitter.names[entry], ", ".join(values))
    if returned is not None:
        if returned[0] != "r" or returned[1] not in REGISTER_GLOBALS:
            return None
        call = "%s = %s" % (REGISTER_GLOBALS[returned[1]], call)
    lines.append("\t" + call)
    lines += ["\t%s = %s_kept;" % (REGISTER_GLOBALS[register], REGISTER_GLOBALS[register][2:]) for register in kept]
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
    # a function called that stays recompiled, by the name the recompiled code calls it by: the entry of
    # one written by hand, the recompiled function's own name
    hand = hand_functions.hand_functions()[0]
    for target in flow.outside:
        real = flow.aliases.get(target, target)
        names[target] = hand[real][0] if real in hand and real not in built else program.functions[real][1]
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
    typing = Typing(built, flow, found, {entry: call_results(f, found, flow) for entry, f in built.items()},
                    (), known.targets, {}, {})
    fields, accesses = typing.run()
    named = memory.Memory(known, memory.accesses_of(built.values()), {})
    always = {entry: set(summary.always) for entry, summary in list(flow.summaries.items()) + list(flow.outside.items())}
    emitter = emit.X86Emitter(built, found, names, named, always, pointers.Layouts(accesses, known))
    emitter.writes = {entry: set(summary.writes)
                      for entry, summary in list(flow.summaries.items()) + list(flow.outside.items())}
    emitter.recompiled = set(flow.outside)
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
        texts, entries = for_the_build(program, built, emitter, texts, flow)
        cache = {}
        for entry in texts:
            f = built[entry]
            targets = targets_of(f)
            by_value = emitter.by_value(entry)
            cache["0x%08X" % entry] = {
                "name": emitter.names[entry], "prototype": emitter.prototype(entry), "text": texts[entry],
                "entry_text": entries.get(entry),
                "calls": ["0x%08X" % c for c in sorted(targets & set(built))],
                "recompiled": sorted({emitter.names[c] for c in targets if c in flow.outside}),
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
    recompiled_names = sorted({name for key in ordered for name in cache[key].get("recompiled", ())})
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(os.path.join(BUILD_DIR, "decompiled.h"), "w", encoding="ascii", newline="\n") as out:
        out.write(file_header("decompiled.h", "the game's functions the decompiler writes, by their prototypes, "
                              "and the recompiled ones they call"))
        out.write("#ifndef DECOMPILED_H\n#define DECOMPILED_H\n\n#include \"decomp.h\"\n#include \"x86.h\"\n\n")
        out.write("\n".join(cache[key]["prototype"] + ";" for key in ordered) + "\n\n")
        out.write("/* the functions they call that stay recompiled, as the recompiled code calls them (x86_call) */\n")
        out.write("\n".join("void %s(void);" % name for name in recompiled_names) + "\n\n#endif\n")
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


def targets_of(f):
    """The functions a function calls or jumps to (a call's own target, SITES up, for one of a function
    that counts its arguments by its callers)."""
    calls, tails = calls_of(f)
    return {target for target, _ in calls} | set(tails)


def for_the_build(program, built, emitter, texts, flow):
    """The functions that go into the build and their entries: the ones written whose calls all reach
    others that go in or recompiled code, and that the recompiled code calls only if what they take was
    worked out with it (signatures.OPEN: every input a parameter, EAX handed back) and their entry can
    be made."""
    keep = set(texts)
    entries = {}
    # the ones that call recompiled code, themselves or through decompiled functions: their entries
    # keep EBX, EBP, ESI and EDI (entry_text)
    calling = {entry for entry in built if targets_of(built[entry]) & set(flow.outside)}
    changed = True
    while changed:
        changed = False
        for entry in built:
            if entry not in calling and targets_of(built[entry]) & calling:
                calling.add(entry)
                changed = True
    changed = True
    while changed:
        changed = False
        for entry in sorted(keep):
            f = built[entry]
            calls = targets_of(f) - set(flow.outside)
            # every one gets an entry: the recompiler leaves out its body and lists the entry in its
            # dispatch; the recompiled code calls only those of signatures.OPEN
            outside = entry not in signatures.OPEN and any(caller not in keep for caller in program.callers.get(entry, ()))
            text = entry_text(emitter, entry, f.drops or 0, entry in calling)
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
