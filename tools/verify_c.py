"""
Name:        verify_c.py
Description: checks each function written by hand against the game's own machine code, with xboxrecomp's
             conformance harness
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

    py -3 tools/verify_c.py

xboxrecomp's tools.conformance maps the XBE where it was linked in a 32-bit
process, calls one of its functions with a set of argument vectors, runs a
C function `lifted_<address>` over the same arguments, and compares eax, edx
and the memory it was handed. It fills `lifted_` with its own recompiled C;
here each one calls the function src/game/ writes by hand instead
(tools/hand_functions.py finds them), so the oracle is the shipped binary
itself. The harness, its argument vectors and its build are the toolkit's
(tools.conformance.xbe_run, unchanged); the 32-bit MSVC is the one
tools/conformance.py finds.

The harness calls the original with four arguments and a plain return, as
it does its own candidates: a function written by hand is checked here when
it is cdecl and calls nothing that is not written by hand too; the others
are verified by the scenarios (tools/scenario.py).
"""
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLKIT = os.path.join(os.path.dirname(REPO), "xboxrecomp")
XBE = os.path.join(REPO, "analysis", "default.xbe")
WORK = os.path.join(REPO, "analysis", "verify_c")
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, TOOLKIT)
import conformance  # noqa: E402  (tools/conformance.py: the 32-bit MSVC)
import hand_functions  # noqa: E402


def main():
    from tools.conformance import xbe_run
    import tools.conformance.__main__ as conf

    vcvars = conformance.find_vcvars32()
    if not vcvars:
        sys.exit("no 32-bit MSVC (vcvars32.bat) found")
    funcs, _ = hand_functions.hand_functions()
    if not funcs:
        sys.exit("no functions written by hand in src/game/")
    data, sections, base = xbe_run.load(XBE)

    # Each lifted_ calls the function written by hand; the files that define
    # them come in ahead of the first.
    files = sorted({path for _, path in funcs.values()})
    lifted = [(va, name, "void lifted_%08X(void) { %s(); }" % (va, name))
              for va, (name, _) in sorted(funcs.items())]
    includes = "".join('#include "%s"\n' % os.path.join(REPO, p).replace("\\", "/") for p in files)
    lifted[0] = (lifted[0][0], lifted[0][1], includes + lifted[0][2])
    entries = [(va, name, None) for va, name, _ in lifted]

    os.makedirs(WORK, exist_ok=True)
    for old in ("xbe_harness.exe", "xbe_harness.obj"):
        if os.path.exists(os.path.join(WORK, old)):
            os.remove(os.path.join(WORK, old))      # never run a harness of an earlier build
    with open(os.path.join(WORK, "xbe_harness.c"), "w", encoding="utf-8") as f:
        f.write(xbe_run.harness_source(os.path.abspath(XBE), sections, lifted, entries))
    runtime_inc = os.path.join(TOOLKIT, "templates", "runtime")
    game_inc = os.path.join(REPO, "src", "game")
    gen_inc = os.path.join(REPO, "src", "recomp", "gen")        # symbols.h
    # The harness maps the XBE where it was linked, low in the address space,
    # and what Windows randomises there (ASLR) takes some of it now and then:
    # one run in three found the code's sections taken ("mapped nothing", or a
    # section skipped and no vector run). Linking the harness fixed and high
    # made it worse (its stack and heap then always land there), so a run that
    # could not map the code is started again instead.
    r = conf._cl(vcvars, WORK, '/W3 /EHa /I"%s" /I"%s" /I"%s" xbe_harness.c /Fexbe_harness.exe'
                 % (runtime_inc, game_inc, gen_inc))
    if r.returncode != 0:
        sys.exit("harness build failed:\n" + r.stdout + r.stderr)

    # As the toolkit does: a function that brings the harness down is left
    # out and the run starts again.
    exe = os.path.join(WORK, "xbe_harness.exe")
    skips, run, unmapped = [], None, 0
    for _ in range(40):
        cmd = [exe, os.path.abspath(XBE)]
        if skips:
            cmd.append(",".join("%08X" % va for va in skips))
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        # the code and its data (up to .data's end) have to be mapped; the
        # sections above (DOLBY, BINKDATA, the title images) never are
        skipped = [int(a, 16) for a in re.findall(r"note: ([0-9A-Fa-f]{8})\.\.", run.stdout)]
        # and a run where every call of the original faulted compared nothing,
        # or one that went down before its summary without naming a function:
        # the same collision, further in
        summary = re.search(r"(\d+) function vectors from the title", run.stdout)
        started = re.findall(r"@RUN ([0-9A-Fa-f]{8})", run.stdout)
        lost = (summary and summary.group(1) == "0") or (not summary and run.returncode not in (0, 1)
                                                          and not started)
        if "mapped nothing" in run.stdout or any(a < 0x002C0000 for a in skipped) or lost:
            unmapped += 1
            if unmapped < 12:
                continue
            sys.exit("the harness could not map the XBE's code in 12 runs:\n" + run.stdout)
        started = re.findall(r"@RUN ([0-9A-Fa-f]{8})", run.stdout)
        if run.returncode in (0, 1) or not started:
            break
        casualty = int(started[-1], 16)
        if casualty in skips:
            break
        skips.append(casualty)
    vectors = re.search(r"(\d+) function vectors from the title", run.stdout)
    names = {va: name for va, name, _ in lifted}
    out = run.stdout
    for va, name in names.items():
        out = out.replace("sub_%08X" % va, "%s (0x%08X)" % (name, va))
    print("\n".join(l for l in out.splitlines() if not l.startswith("@RUN ")).strip())
    if skips:
        print("not checked, they brought the harness down: %s"
              % ", ".join(names.get(va, "0x%08X" % va) for va in skips))
    if not vectors or int(vectors.group(1)) == 0:
        # nothing compared is not a pass
        print("no vector was compared")
        sys.exit(1)
    sys.exit(0 if run.returncode == 0 and not skips else 1)


if __name__ == "__main__":
    main()
