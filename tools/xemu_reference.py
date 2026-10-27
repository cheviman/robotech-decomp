"""
Name:        xemu_reference.py
Description: runs a scenario on the original game in xemu, the reference the port's frames are set against
Version:     0.3.0
Created:     27-10-2026
Modified:    27-10-2026
Author:      Sebastian Toyos

The port's scenarios (tests/scenarios/NAME.txt, tools/scenario.py) compare its frames with frames an
earlier build of its own wrote. This runs the same scenario on the original XBE in xemu, built with the
reference hooks of tools/reference/xemu (built in MSYS2's MINGW64; a pad script by the frames the game
presents, a frame dumped every so many, an exit frame), as MAME is the reference of an arcade game's port.
The frames land in analysis/reference/NAME/ (fNNNNN.bmp, as the port's), and each is set against the
port's of the same number in analysis/scenarios/NAME/ when that run is there: how far apart they are, a
pixel at a time. A scenario's `original` line is the most a frame may be apart; with a frame further, the
run ends in failure, as the port's own comparison does when it moves from its last build.

The scenarios run the port on a clock tied to the frames (ROBOTECH_VIRTUAL_CLOCK, src/clock_bridge.c),
its pad answered at XInputGetState (src/input_bridge.c); on the console the game's clock goes on while it
loads, and its pad comes over USB. So xemu is handed the same functions the port replaces (HOOKS, by
their names in symbols.txt) and answers them as the port does: the frames are the game's presents, and
what the game times, and the pad script, land on the same frames in both.

    py -3 tools/xemu_reference.py menu                 # run the reference of a scenario
    py -3 tools/xemu_reference.py menu --compare-only  # only set the frames there side by side

What xemu needs that is the console's (its MCPX boot ROM, a BIOS and a hard disk image) is the user's
own, in XEMU_FILES (../xemu-files by default: mcpx/mcpx_1.0.bin, bios/*.bin, hdd/xbox_hdd.qcow2); the
game is a disc image made from game/ (tools/make_xiso.py), without its movies when the scenario runs
without them. The hard disk is never written (QEMU's -snapshot): every run starts from the same one.
"""
import argparse
import glob
import os
import subprocess
import sys

import scenario
import symbols

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.environ.get("XEMU_FILES", os.path.join(os.path.dirname(REPO), "xemu-files"))
XEMU = os.environ.get("XEMU_EXE", os.path.join(os.path.dirname(REPO), "xemu", "build", "qemu-system-i386.exe"))
# the libraries a build of xemu in MSYS2 links (MINGW64), where MSYS2 is on any drive
LIBRARIES = os.environ.get("XEMU_LIBRARIES") or next(
    (path for path in ("%s:/msys64/mingw64/bin" % drive for drive in "CDEFGH") if os.path.isdir(path)), "")
RUNS = os.path.join(REPO, "analysis", "reference")
# the functions the port replaces, answered in xemu as it answers them (xemu-reference.c)
HOOKS = {"swap": "D3DDevice_Swap", "counter": "xapi_QueryPerformanceCounter", "ticks": "xapi_GetTickCount",
         "date": "xapi_GetSystemTimeAsFileTime", "pad": "xapi_XInputGetState"}
EPOCH = 1028587044      # the XBE's build date, 2002-08-05 22:37:24 UTC: the port's virtual date
CONFIG = """[general]
show_welcome = false
skip_boot_anim = true

[input.bindings]
port1_driver = 'usb-xbox-gamepad'
port1 = 'keyboard'

[display]
renderer = 'OPENGL'

[display.quality]
surface_scale = 1

[sys.files]
bootrom_path = '{mcpx}'
flashrom_path = '{bios}'
eeprom_path = '{eeprom}'
hdd_path = '{hdd}'
dvd_path = '{dvd}'
"""


def disc(movies):
    """The disc image of the game the scenario runs, made from its folder the first time."""
    name = "robotech.iso" if movies != "no" else "robotech_nomovies.iso"
    path = os.path.join(REPO, "analysis", name)
    if not os.path.exists(path):
        subprocess.run([sys.executable, os.path.join(REPO, "tools", "make_xiso.py"),
                        scenario.game_dir(movies), path], check=True)
    return path


def hooks():
    """XEMU_REFERENCE_HOOKS: each hook at its function's address."""
    address = {name: va for va, name in symbols.load()["func"].items()}
    missing = [name for name in HOOKS.values() if name not in address]
    if missing:
        sys.exit("not in symbols.txt: " + ", ".join(missing))
    return ",".join("%s=%X" % (hook, address[name]) for hook, name in HOOKS.items())


def run(name, sc):
    out = os.path.join(RUNS, name)
    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "f*.bmp")):
        os.remove(old)
    bios = sorted(glob.glob(os.path.join(FILES, "bios", "*.bin")))
    if not bios or not os.path.exists(XEMU):
        sys.exit("xemu or its files are not there (%s, %s)" % (XEMU, FILES))
    config = os.path.join(out, "xemu.toml")
    with open(config, "w", encoding="utf-8", newline="\n") as f:
        f.write(CONFIG.format(mcpx=os.path.join(FILES, "mcpx", "mcpx_1.0.bin").replace("\\", "/"),
                              bios=bios[0].replace("\\", "/"),
                              eeprom=os.path.join(out, "eeprom.bin").replace("\\", "/"),
                              hdd=os.path.join(FILES, "hdd", "xbox_hdd.qcow2").replace("\\", "/"),
                              dvd=disc(sc["movies"]).replace("\\", "/")))
    env = dict(os.environ)
    # and the one it builds itself (subprojects/slirp)
    env["PATH"] = os.pathsep.join([LIBRARIES, os.path.join(os.path.dirname(XEMU), "subprojects", "slirp"),
                                   env.get("PATH", "")])
    env.update({"XEMU_REFERENCE_DIR": out, "XEMU_REFERENCE_SCRIPT": sc["script"],
                "XEMU_REFERENCE_DUMP": str(sc["dump"]), "XEMU_REFERENCE_EXIT": str(sc["frames"]),
                "XEMU_REFERENCE_HOOKS": hooks(), "XEMU_REFERENCE_EPOCH": str(EPOCH)})
    with open(os.path.join(out, "stderr.txt"), "w") as err:
        subprocess.run([XEMU, "-config_path", config, "-snapshot"], cwd=out, env=env,
                       stdout=subprocess.DEVNULL, stderr=err, timeout=sc["frames"] // 60 * 6 + 180)
    return sorted(glob.glob(os.path.join(out, "f*.bmp")))


def pixels(path):
    """(width, height, rows of (b, g, r) bytes from the top) of a 24-bit BMP."""
    data = open(path, "rb").read()
    offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    row_bytes = (width * 3 + 3) & ~3
    rows = [data[offset + y * row_bytes:offset + y * row_bytes + width * 3] for y in range(abs(height))]
    return width, abs(height), rows[::-1] if height > 0 else rows


def halved(width, rows):
    """A frame twice as wide as the display's (the game draws 1280 x 480, the console filtering it to
    640 x 480 as it shows it): each two pixels of a row as one, their mean."""
    out = []
    for row in rows:
        out.append(bytes((row[6 * x + c] + row[6 * x + 3 + c] + 1) // 2 for x in range(width // 2) for c in range(3)))
    return width // 2, out


def distance(a, b):
    """How far two frames are apart: the mean of the channels' absolute differences (0 to 255), or None
    when they are not of one size; xemu's (a) at the width it draws, halved to the port's."""
    wa, ha, ra = pixels(a)
    wb, hb, rb = pixels(b)
    if wa == 2 * wb and ha == hb:
        wa, ra = halved(wa, ra)
    if (wa, ha) != (wb, hb):
        return None
    total = sum(abs(x - y) for row_a, row_b in zip(ra, rb) for x, y in zip(row_a, row_b))
    return total / (wa * ha * 3)


def compare(name, most):
    """Each frame of xemu's against the port's; False when a frame is further from the original than the
    scenario allows (its `original` line), or none could be set side by side."""
    ours = os.path.join(REPO, "analysis", "scenarios", name)
    over, worst = [], None
    for path in sorted(glob.glob(os.path.join(RUNS, name, "f*.bmp"))):
        frame = os.path.basename(path)[:-4]
        port = os.path.join(ours, os.path.basename(path))
        found = distance(path, port) if os.path.exists(port) else None
        print("  %s  %s" % (frame, "no frame of the port's" if not os.path.exists(port) else
                            "sizes differ" if found is None else "%.2f" % found))
        if os.path.exists(port) and (found is None or (most is not None and found > most)):
            over.append(frame)
        if found is not None and (worst is None or found > worst[1]):
            worst = (frame, found)
    if worst is None:
        print("%-10s no frame of xemu's and the port's to set side by side" % name)
        return False
    print("%-10s the furthest from the original %s, at %.2f%s" % (
        name, worst[0], worst[1], "" if most is None else
        "; over %s: %s" % (most, " ".join(over)) if over else " (%s allowed)" % most))
    return not over


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="+", help="scenarios")
    ap.add_argument("--compare-only", action="store_true", help="set the frames there against the port's")
    ap.add_argument("--script", help="another pad script for the run, to try one")
    args = ap.parse_args()
    ok = True
    for name in args.names:
        sc = scenario.load(os.path.join(scenario.SCENARIOS, name + ".txt"))
        if args.script is not None:
            sc["script"] = args.script
        if not args.compare_only:
            frames = run(name, sc)
            print("%-10s %d of %d frames from xemu" % (name, len(frames), sc["frames"] // sc["dump"] + 1))
        ok = compare(name, float(sc["original"]) if "original" in sc else None) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
