"""
Name:        scenario.py
Description: runs the game through scripted scenarios and compares every dumped frame with the reference
Version:     0.1.0
Created:     25-10-2026
Modified:    25-10-2026
Author:      Sebastian Toyos

A scenario (tests/scenarios/NAME.txt) is a pad script by frame, how many
frames to run and how often to dump one. The game runs it with the clock tied
to the frames (ROBOTECH_VIRTUAL_CLOCK, src/clock_bridge.c) and an empty save
folder of its own (ROBOTECH_SAVE_DIR), so two runs of one build present the
same frames; each dumped frame's hash is compared with the
reference kept beside the scenario (NAME.frames), which the build before a
change wrote. A function rewritten by hand has to leave every frame as it was.

    py -3 tools/scenario.py              # every scenario, against its reference
    py -3 tools/scenario.py menu         # one
    py -3 tools/scenario.py --save       # the current build's frames become the references

Scenario lines (# starts a comment):
    script  f<frame>:<button>[+<button>][:<hold>],...   (src/input_bridge.c's pad script)
    frames  N        run until frame N is presented
    dump    K        dump every K-th frame
    movies  no       run from a copy of the game without its movies (analysis/game_nomovies,
                     made from game/ the first time), which boots to the menu in seconds
    saves   compare  compare the files the game saved too (their hashes, by path)

xboxrecomp's runtime has no deterministic time and no frame comparison, so
this is the project's own; the frames come from the Direct3D 11 bridge
(ROBOTECH_D3D11_DUMP), the exit from ROBOTECH_EXIT_FRAME.
"""
import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = os.path.join(REPO, "tests", "scenarios")
EXE = os.path.join(REPO, "build", "Release", "robotech_battlecry.exe")
GAME = os.path.join(REPO, "game")
NOMOVIES = os.path.join(REPO, "analysis", "game_nomovies")
RUNS = os.path.join(REPO, "analysis", "scenarios")


def load(path):
    out = {"script": "", "frames": 600, "dump": 60, "movies": "yes", "saves": "no"}
    for line in open(path, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        key, _, value = line.partition(" ")
        out[key] = value.strip()
    out["frames"], out["dump"] = int(out["frames"]), int(out["dump"])
    return out


def game_dir(movies):
    if movies != "no":
        return GAME
    if not os.path.isdir(NOMOVIES):
        def skip(_, names):
            return [n for n in names if n.lower() == "vcmovie"]
        shutil.copytree(GAME, NOMOVIES, ignore=skip)
    return NOMOVIES


def run(name, sc):
    out = os.path.join(RUNS, name)
    shutil.rmtree(out, ignore_errors=True)
    saves = os.path.join(out, "saves")
    os.makedirs(saves)
    env = dict(os.environ)
    env.update({
        "ROBOTECH_VIRTUAL_CLOCK": "1",
        "ROBOTECH_PAD_SCRIPT": sc["script"],
        "ROBOTECH_D3D11_DUMP": os.path.join(out, "f"),
        "ROBOTECH_D3D11_DUMP_EVERY": str(sc["dump"]),
        "ROBOTECH_EXIT_FRAME": str(sc["frames"]),
        "ROBOTECH_GAME_DIR": game_dir(sc["movies"]),
        # its own empty save folder: what the game finds saved changes its menus
        "ROBOTECH_SAVE_DIR": saves,
        "RECOMP_WATCHDOG_SECS": str(sc["frames"] // 60 * 3 + 60),
    })
    with open(os.path.join(out, "stderr.txt"), "w") as err:
        subprocess.run([EXE], cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=err,
                       timeout=sc["frames"] // 60 * 4 + 120)
    frames = {}
    for path in sorted(glob.glob(os.path.join(out, "f*.bmp"))):
        frame = int(os.path.basename(path)[1:-4])
        frames["%05d" % frame] = hashlib.md5(open(path, "rb").read()).hexdigest()
    if sc["saves"] == "compare":
        # the saves, not the partition images the runtime keeps beside them
        for root, _, names in os.walk(saves):
            for n in names:
                path = os.path.join(root, n)
                rel = os.path.relpath(path, saves).replace("\\", "/")
                if rel.startswith(("UDATA/", "TDATA/")):
                    frames["save:" + rel] = hashlib.md5(open(path, "rb").read()).hexdigest()
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="scenarios to run (all by default)")
    ap.add_argument("--save", action="store_true", help="write the frames as the references")
    args = ap.parse_args()
    if not os.path.exists(EXE):
        sys.exit("no build at %s" % os.path.relpath(EXE, REPO))
    names = args.names or sorted(os.path.splitext(os.path.basename(p))[0]
                                 for p in glob.glob(os.path.join(SCENARIOS, "*.txt")))
    failed = 0
    for name in names:
        sc = load(os.path.join(SCENARIOS, name + ".txt"))
        frames = run(name, sc)
        ref_path = os.path.join(SCENARIOS, name + ".frames")
        expected_count = sc["frames"] // sc["dump"]
        if sum(1 for k in frames if not k.startswith("save:")) < expected_count:
            print("%-10s ran %d of %d dumps: the game stopped early (analysis/scenarios/%s/stderr.txt)"
                  % (name, len(frames), expected_count, name))
            failed += 1
            continue
        if args.save:
            with open(ref_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("# tools/scenario.py --save: each dumped frame (or saved file) and its hash\n")
                for key, h in sorted(frames.items()):
                    f.write("%s %s\n" % (key, h))
            print("%-10s %d frames and files saved as the reference" % (name, len(frames)))
            continue
        if not os.path.exists(ref_path):
            print("%-10s no reference yet (--save)" % name)
            failed += 1
            continue
        ref = {}
        for line in open(ref_path, encoding="utf-8"):
            line = line.split("#")[0].split()
            if len(line) == 2:
                ref[line[0]] = line[1]
        differ = [k for k in sorted(ref) if frames.get(k) != ref[k]]
        extra = sorted(k for k in frames if k.startswith("save:") and k not in ref)
        if differ or extra:
            print("%-10s %d of %d differ from the reference, the first %s%s"
                  % (name, len(differ), len(ref), differ[0] if differ else "-",
                     ("; saved too: " + ", ".join(extra)) if extra else ""))
            failed += 1
        else:
            print("%-10s %d frames and files, all as the reference" % (name, len(ref)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
