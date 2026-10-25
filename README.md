# Robotech: Battlecry — native port

A native port of Vicious Cycle's 2002 Xbox game *Robotech: Battlecry* — not an emulator. The original
Xbox executable is statically recompiled into C with [xboxrecomp](https://github.com/sp00nznet/xboxrecomp)
and linked against a runtime that stands in for the Xbox kernel, its GPU, its sound and its controllers.

Where it is going:

- **Windows, Xbox Series, Linux and Mac.** Direct3D 11 first, for Windows and Xbox Series; Vulkan after,
  for Linux and Mac.
- **The game brought up to date**: higher resolutions, widescreen, frame rate, and DLSS.
- **New to it**: multiplayer and mods.

**This repository contains no game data and no game code.** The C the game runs on is generated on your
machine from your own copy of the game, which the build reads and never changes; nothing generated from it
is committed.

## Status

- [x] XBE analysis: title TM-002 (NTSC, linked 2002-08-05), XDK 4721 (XAPILIB, XBOXKRNL, LIBCMT, D3D8 not
      LTCG, DSOUND), Bink 1; 115 kernel imports, all of them covered by the runtime
- [x] The whole executable recompiled into C: 6,646 functions, 5,556 of them the game and its engine
      (Vicious Cycle's own, `vc*` engine classes and `gc*` game classes, no RTTI), the rest the XDK's D3D8,
      DirectSound and peripheral libraries and Bink
- [x] Native build with MSVC (x64)
- [x] The XDK library code named: XbSymbolDatabase finds the entry points (all 77 Direct3D ones the game
      calls, DirectSound, XAPI; `symbols/xdk_symbols.json`), and matching the XBE against the XDK's own
      `.lib` files names the rest that did not change from 4721 to 5849 (`symbols/lib_matches.json`,
      with the libraries' variables); the engine's 30 object classes and their callbacks come from the
      descriptors the game registers (`symbols/classes.json`): 1,271 functions named in all
- [x] Boots: creates its Direct3D device and plays the legal screen and the TDK, Harmony Gold and
      Vicious Cycle logo movies, whole frames, through xboxrecomp's pushbuffer executor (slowly: the GPU
      is drawn in software)
- [x] The logo movies through Direct3D 11 (`ROBOTECH_D3D11=1`): the device, `Clear`, `Swap`, textures and
      `DrawVerticesUP` routed, at the movies' speed
- [x] The menu and the first mission through Direct3D 11: render states, vertex and index buffers, the
      engine's own 2D draws; sound, the pad and the keyboard, saves on the hard disk (`PENDING.md` has
      what is wrong and what is missing)
- [ ] The rest of Direct3D 8 routed to Direct3D 11 (`docs/d3d.md` maps how the game uses it): vertex
      programs, pixel shaders, render targets
- [ ] Higher resolutions, widescreen, frame rate
- [ ] Xbox Series (UWP, Direct3D 11)
- [ ] Vulkan, for Linux and Mac
- [ ] DLSS
- [ ] Multiplayer
- [ ] Mods
- [ ] The game's code decompiled into readable C, and its formats (the `VC2` resource containers of
      levels, packs and textures, the Xbox ADPCM sound and music) as editable files

## Getting started

Requirements: Python 3.10 or newer with `capstone` (`pip install capstone`), CMake 3.20 or newer, and
Visual Studio Build Tools (MSVC, x64).

1. The toolkit: clone xboxrecomp next to this repository (`../xboxrecomp`), as it is released; this
   project uses it unchanged (built and run with v0.16.0, `f0f8a46`). What the game needs from it is
   set up from here: `src/main.c` and `src/recomp_manual.c`.

2. Your game: the game's folder (`default.xbe`, `dsstdfx.bin` and `Media/`), from the Xbox disc or from
   the Xbox 360 "Xbox Originals" package, at `game/`: a copy, or a link to where you keep it:

   ```
   mklink /J game "D:\Games\Robotech Battlecry"
   ```

3. Recompile the XBE into C (`src/recomp/gen/`). The analysis goes to `analysis/`:

   ```bash
   py -3 tools/pipeline.py
   ```

4. Build:

   ```bash
   cmake -S . -B build -A x64
   ```

   ```bash
   cmake --build build --config Release --parallel
   ```

5. Run, from the repository's root (where `game\` is):

   ```bash
   RECOMP_PB_EXEC=1 RECOMP_VBLANK=paced RECOMP_FB_WINDOW=1 build/Release/robotech_battlecry.exe
   ```

   `RECOMP_PB_EXEC` executes the game's GPU commands, `RECOMP_VBLANK=paced` gives it a 60 Hz vertical
   blank and `RECOMP_FB_WINDOW` shows what it draws in a window. The runtime's other switches are in
   xboxrecomp's documentation.

   Or through the Direct3D 11 bridge, which is where the port is going (`src/d3d11_bridge.c`; not with
   `RECOMP_PB_EXEC`). `ROBOTECH_WINDOW_SCALE` sizes its window, 2 by default:

   ```bash
   ROBOTECH_D3D11=1 RECOMP_VBLANK=paced build/Release/robotech_battlecry.exe
   ```

`symbols/xdk_symbols.json` comes from scanning the XBE with
[XbSymbolDatabase](https://github.com/Cxbx-Reloaded/XbSymbolDatabase)'s command-line tool; to make it
again:

```
XbSymbolDatabaseCLI analysis\default.xbe -e > analysis\xbsymbols.txt
py -3 tools/xdk_symbols.py analysis/xbsymbols.txt
```

`symbols/lib_matches.json` comes from matching the XBE against the static libraries of an XDK (5849
here: `d3d8.lib`, `dsound.lib`, `xapilib.lib`, `libcmt.lib`, `libcpmt.lib`, `xboxkrnl.lib`, in one folder);
to make it again:

```
py -3 tools/match_libs.py --libs D:/xdk/lib
```

## Layout

```
game/                   your game's folder (ignored by git)
src/main.c              host entry: loads the XBE, brings up the runtime, calls the recompiled entry point;
                        names the Direct3D device's GPU fence
src/recomp_manual.c     hand-written overrides and wrappers of recompiled functions
src/d3d11_bridge.c      the Direct3D 11 bridge: what the game's D3D calls draw, through xboxrecomp's
                        D3D8 layer
src/recomp/gen/         the recompiled C (ignored by git; tools/pipeline.py writes it)
symbols/xdk_symbols.json  the XDK library symbols XbSymbolDatabase finds in the XBE (names and addresses)
symbols/lib_matches.json  the XDK library functions and variables matched against the XDK's .lib files
symbols/classes.json    the engine's object classes and their callbacks
symbols/names.json      function names given by hand
tools/pipeline.py       xboxrecomp's pipeline, with every output inside this repository
tools/apply_names.py    writes the names above into the disassembly before recompiling
tools/xdk_symbols.py    makes symbols/xdk_symbols.json from XbSymbolDatabase's scan
tools/match_libs.py     makes symbols/lib_matches.json from the XDK's .lib files
tools/find_classes.py   makes symbols/classes.json from the class descriptors the game registers
docs/d3d.md             how the game uses Direct3D: the map for the Direct3D 11 path
analysis/               the pipeline's data: a copy of the XBE, disassembly, function and ABI databases
                        (ignored by git)
licenses/               licenses of the code this project starts from
```

## How the port works

- **Game code.** xboxrecomp lifts the XBE's x86 code into C, a function per function, with the CPU's
  registers and flags as variables and the Xbox's memory at the addresses the game expects; the C is
  compiled into a native executable. That includes the libraries the game linked statically (Direct3D,
  DirectSound, Bink), which run as recompiled code too.
- **Kernel.** The Xbox kernel calls the game imports are answered by the runtime with the host's
  operating system: files from `game/`, threads, events, memory.
- **Graphics.** For now the game's own Direct3D runs and writes GPU commands, which the runtime's
  pushbuffer executor draws in software. The port's way is to route the game's Direct3D calls to
  Direct3D 11 instead (`docs/d3d.md`).
- **The game's files** are read where the game asks for them, from your copy, unchanged.

## Legal

- This project is licensed under the BSD 3-Clause License; see `LICENSE`.
- `CMakeLists.txt`, `src/main.c` and `src/recomp_manual.c` started from xboxrecomp's
  `templates/new-game` (MIT); see `licenses/xboxrecomp.txt`. xboxrecomp itself is not part of this
  repository.
- `symbols/xdk_symbols.json` is the output of XbSymbolDatabase (MIT): names and addresses, no code.
- `symbols/lib_matches.json` holds names and addresses only: the XDK's libraries are read on your
  machine, and no XDK code or file is part of this repository.
- No game data and no game code is distributed by this project: the recompiled C is generated from your
  own copy of the game and stays on your machine.
- Robotech is a trademark of Harmony Gold USA, Inc. Robotech: Battlecry was developed by Vicious Cycle
  Software and published by TDK Mediactive. This project is not affiliated with or endorsed by them or by
  Microsoft.
