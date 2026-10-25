# Robotech: Battlecry — static recompilation

A native port of *Robotech: Battlecry* (Xbox, 2002, Vicious Cycle / TDK Mediactive) built with
[xboxrecomp](https://github.com/sp00nznet/xboxrecomp): the original x86 code is lifted to C and linked
against a runtime that replaces the Xbox kernel, D3D8 (to D3D11), DirectSound and input.

No game code or data is in this repo. You need your own copy of the game.

## Layout

| Path | What |
|---|---|
| `src/main.c` | host entry: loads the XBE, brings up the runtime, calls the recompiled entry point |
| `src/recomp_manual.c` | hand-written overrides of recompiled functions |
| `src/recomp/gen/` | generated C (not committed; `tools/pipeline.py` writes it) |
| `tools/pipeline.py` | runs the xboxrecomp pipeline with every output inside this repo |
| `analysis/` | pipeline data: a copy of the XBE, disassembly, function and ABI databases (not committed) |
| `game/` | the extracted game folder (`default.xbe`, `Media/`); a junction or a copy, not committed |

Changes that would help any title go to the xboxrecomp clone as separate commits, so they can be sent
upstream; only what is specific to this game lives here.

## Build

Needs Python 3.10+ with `capstone`, CMake 3.20+ and MSVC (x64). The toolkit is expected at `../xboxrecomp`.

```
py -3 tools/pipeline.py
cmake -S . -B build
cmake --build build --config Release --parallel
build\Release\robotech_battlecry.exe 2> stderr.txt
```

Run it from the repo root, so `game\default.xbe` resolves.

## The game

- XBE: title TM-002, NTSC, linked 2002-08-05; XDK 4721 (XAPILIB, XBOXKRNL, LIBCMT, D3D8, DSOUND), Bink.
- ~6,650 functions: 5,556 in `.text`, the rest in the D3D, DSOUND, BINK* and XPP library sections.
- Engine: Vicious Cycle's own (`vc*` engine classes, `gc*` game classes); no RTTI.
- Data: `VC2\x1A` resource containers (`.lvl`, `.pak`, `.spt`, `.txr`), raw Xbox ADPCM audio (`.vo`, `.moo`),
  Bink 1 movies.
