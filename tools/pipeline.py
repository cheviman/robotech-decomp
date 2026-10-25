"""Run the xboxrecomp pipeline for Robotech: Battlecry.

Every output lands in this repo: analysis data under analysis/, generated C under
src/recomp/gen/. The toolkit clone and the extracted game folder are never
written to.

    py -3 tools/pipeline.py              # all steps
    py -3 tools/pipeline.py recomp       # from that step on
    py -3 tools/pipeline.py --only abi   # just that step
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(REPO, "analysis")
XBE = os.path.join(ANALYSIS, "default.xbe")
GAME_XBE = os.path.join(REPO, "game", "default.xbe")
GEN_DIR = os.path.join(REPO, "src", "recomp", "gen")


def steps():
    """(name, argv) pairs. An argv starting with "tools." is a toolkit module,
    run from the toolkit clone; anything else is a script of this repo."""
    disasm = os.path.join(ANALYSIS, "disasm")
    func_id = os.path.join(ANALYSIS, "func_id")
    abi = os.path.join(ANALYSIS, "abi")
    return [
        ("parse", ["tools.xbe_parser", XBE, "--json", os.path.join(ANALYSIS, "default_analysis.json")]),
        ("disasm", ["tools.disasm", XBE, "-o", disasm]),
        ("names", [os.path.join(REPO, "tools", "apply_names.py")]),
        ("func_id", ["tools.func_id", XBE,
                     "--functions", os.path.join(disasm, "functions.json"),
                     "--strings", os.path.join(disasm, "strings.json"),
                     "--xrefs", os.path.join(disasm, "xrefs.json"),
                     "-o", func_id]),
        ("abi", ["tools.abi_analysis", XBE, "--disasm-dir", disasm, "--func-id-dir", func_id,
                 "--output-dir", abi]),
        ("recomp", ["tools.recomp", XBE, "--all", "--split", "250", "--gen-dir", GEN_DIR,
                    "-o", os.path.join(ANALYSIS, "recomp"),
                    "--game-name", "Robotech: Battlecry",
                    "--disasm-dir", disasm, "--func-id-dir", func_id, "--abi-dir", abi,
                    "--icall-sites", os.path.join(ANALYSIS, "icall_sites.json"),
                    "--exclude-manual", os.path.join(REPO, "src", "recomp_manual.c")]),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("start", nargs="?", help="step to start from")
    ap.add_argument("--only", help="run just this step")
    ap.add_argument("--toolkit", default=os.path.join(os.path.dirname(REPO), "xboxrecomp"),
                    help="xboxrecomp clone (default: ../xboxrecomp)")
    args = ap.parse_args()

    names = [n for n, _ in steps()]
    first = args.only or args.start or names[0]
    if first not in names:
        sys.exit("unknown step '%s' (steps: %s)" % (first, ", ".join(names)))
    todo = [s for s in steps() if s[0] == args.only] if args.only else steps()[names.index(first):]

    os.makedirs(ANALYSIS, exist_ok=True)
    if not os.path.exists(XBE):
        shutil.copyfile(GAME_XBE, XBE)

    for name, cmd in todo:
        print("== %s" % name, flush=True)
        t0 = time.time()
        if cmd[0].startswith("tools."):
            rc = subprocess.call([sys.executable, "-m"] + cmd, cwd=args.toolkit)
        else:
            rc = subprocess.call([sys.executable] + cmd + ["--toolkit", args.toolkit], cwd=REPO)
        print("== %s: exit %d in %.0fs" % (name, rc, time.time() - t0), flush=True)
        if rc:
            sys.exit(rc)


if __name__ == "__main__":
    main()
