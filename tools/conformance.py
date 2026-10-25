"""
Name:        conformance.py
Description: runs xboxrecomp's conformance oracle on the game, with the 32-bit MSVC this machine has
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

xboxrecomp's tools.conformance maps the XBE where it was linked, calls the
game's own machine code and the C over the same arguments, and compares. It
needs a 32-bit MSVC and looks for one only under Visual Studio 2022; this
takes the Visual Studio found by vswhere (or ROBOTECH_VCVARS32, a path to
vcvars32.bat) and runs the toolkit's own tool, unchanged, with it.

    py -3 tools/conformance.py --only corpus --xbe analysis/default.xbe --xbe-limit 40
"""
import glob
import os
import runpy
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLKIT = os.path.join(os.path.dirname(REPO), "xboxrecomp")


def find_vcvars32():
    if os.environ.get("ROBOTECH_VCVARS32"):
        return os.environ["ROBOTECH_VCVARS32"]
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    roots = []
    if os.path.exists(vswhere):
        out = subprocess.run([vswhere, "-all", "-products", "*", "-property", "installationPath"],
                             capture_output=True, text=True).stdout
        roots = [l.strip() for l in out.splitlines() if l.strip()]
    roots += glob.glob(os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                                    "Microsoft Visual Studio", "*", "*"))
    for root in roots:
        p = os.path.join(root, "VC", "Auxiliary", "Build", "vcvars32.bat")
        if os.path.exists(p):
            return p
    return None


def main():
    vcvars = find_vcvars32()
    if not vcvars:
        sys.exit("no 32-bit MSVC (vcvars32.bat) found")
    # paths given relative to this repository
    argv = [os.path.abspath(a) if os.path.exists(a) else a for a in sys.argv[1:]]
    sys.path.insert(0, TOOLKIT)
    os.chdir(TOOLKIT)
    import tools.conformance.__main__ as conf
    conf._find_vcvars = lambda: vcvars
    sys.argv = ["tools.conformance"] + argv
    sys.exit(conf.main())


if __name__ == "__main__":
    main()
