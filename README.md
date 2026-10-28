# Robotech: Battlecry — native port

A native port of Vicious Cycle's 2002 Xbox game *Robotech: Battlecry* — not an emulator. The original
Xbox executable is statically recompiled into C with [xboxrecomp](https://github.com/sp00nznet/xboxrecomp)
and linked against a runtime that stands in for the Xbox kernel, its GPU, its sound and its controllers.

Where it is going:

- **Windows, Xbox Series, Linux and Mac.** Direct3D 11 first, for Windows and Xbox Series; Vulkan after,
  for Linux and Mac.
- **The game brought up to date**: higher resolutions, widescreen, frame rate, and DLSS.
- **New to it**: multiplayer and mods.

**This repository contains no game data and none of the game's machine code.** The recompiled C the game
runs on is generated on your machine from your own copy of the game, which the build reads and never
changes; nothing generated from it is committed. What the repository holds of the game is the C written by
hand as it is decompiled (`src/game/`) and the names of `symbols/symbols.txt`.

## Status

- [x] XBE analysis: title TM-002 (NTSC, linked 2002-08-05), XDK 4721 (XAPILIB, XBOXKRNL, LIBCMT, D3D8 not
      LTCG, DSOUND), Bink 1; 115 kernel imports, all of them covered by the runtime
- [x] The whole executable recompiled into C: 6,590 functions, 5,203 of them the game and its engine
      (Vicious Cycle's own, `vc*` engine classes and `gc*` game classes, no RTTI), the rest the XDK's D3D8,
      DirectSound and peripheral libraries and Bink
- [x] Native build with MSVC (x64)
- [x] The XDK library code named: XbSymbolDatabase finds the entry points (all 77 Direct3D ones the game
      calls, DirectSound, XAPI; `symbols/xdk_symbols.json`), and matching the XBE against the XDK's own
      `.lib` files names the rest that did not change from 4721 to 5849 (`symbols/lib_matches.json`,
      with the libraries' variables); the engine's 35 object classes and their callbacks come from the
      descriptors the game registers (`symbols/classes.json`); the game's own object system (families
      of types, handles, messages and state machines) and 239 of its 370 object types, named from their
      own strings or from what makes them, their functions in bulk (`symbols/registries.json` and the
      type lines); with the engine named as it is decompiled, 2,239 functions with a real name
- [x] Boots: creates its Direct3D device and plays the legal screen and the TDK, Harmony Gold and
      Vicious Cycle logo movies, whole frames, through xboxrecomp's pushbuffer executor (slowly: the GPU
      is drawn in software)
- [x] The logo movies through Direct3D 11 (`ROBOTECH_D3D11=1`): the device, `Clear`, `Swap`, textures and
      `DrawVerticesUP` routed, at the movies' speed
- [x] The menu and the first mission through Direct3D 11: render states, vertex and index buffers, the
      engine's own 2D draws, vertex programs (run on the CPU for now); sound, the pad and the keyboard,
      saves on the hard disk (`PENDING.md` has
      what is wrong and what is missing)
- [x] The first of the engine decompiled into C (`src/game/engine/`): the object system (27 functions
      and the classes' default callbacks), the files, the formatted strings, the rectangles, the random
      numbers, the screen (the Direct3D device, the viewport, clearing and showing it), the text
      (fonts, measuring and laying out strings), the render state setters, 19 classes'
      registrations and the scene objects' tree, 134 functions, every name real; the menu, the first mission and a save as the recompiled ones played them, frame for frame
- [x] The structured decompiler: arcade-decomp's (SegaSonic's), with an x86 frontend of this project's
      (`tools/x86`); 2,910 of the game's functions in its C (`src/decompiled/`), with no goto, in the
      recompiled ones' place, calling the ones still recompiled as the recompiled code does, the menu,
      the first mission and a save frame for frame as before
- [x] Native sound: the 29 DirectSound entries the game and its Bink call answered on the host
      (`src/dsound_bridge.c`, with the XDK's own behaviour), the Xbox ADPCM decoded and mixed to 48 kHz
      stereo (`src/sound_mixer.c`) and played through xboxrecomp's audio output (XAudio2); the 3D is a
      distance and a pan, and the reverb is not heard yet
- [x] The original game as the reference: the scenarios played in xemu on the port's clock and pad, its
      frames set against the port's; the menu, the first mission and a save the same on both, the flight
      and the shots included, at a mean difference of 1.23 of 255 or less (1.5 fails), and the training,
      its shadow drawn to a texture, at 3.2 (its dialogue waits for voice lines, which end on other
      frames in xemu)
- [ ] The rest of Direct3D 8 routed to Direct3D 11 (`docs/d3d.md` maps how the game uses it): vertex
      programs on the GPU, pixel shaders, render targets
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

   The sound is the game's DirectSound answered on the host; `RECOMP_AC97_READY=1` plays it through
   xboxrecomp's emulated APU instead, and `RECOMP_AUDIO_WAV=<file>` records what is played.

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

## Changing the decompilation

The game's C is written by hand, a function at a time, into `src/game/` by subject; each takes its
recompiled version's place. Everything else under `src/recomp/gen/` is generated and never edited by
hand.

- **Names, descriptions, files, types**: `symbols/symbols.txt`, the one place they live (its header says
  how to read it); `struct`, `field` and `var` lines become `symbols.h`'s accessors for the C written by
  hand (`vcClassDesc_create(p)`, `vcClassByType(type)`). `tools/symbols.py merge` and `layout` write the tools' findings into its generated sections;
  a line written by hand wins. Then `py -3 tools/pipeline.py names` regenerates the C.
- **A function written by hand**: C in `src/game/`, by its name in `symbols.txt` and with a signature
  of its own, the guest's memory read through `symbols.h`'s accessors. Beside it, its entry
  (`ENTRY_CDECL2(vcObjectFind)`, `src/game/decomp.h`) is the function as the recompiled code calls
  it, its arguments on the guest stack (or in the registers the compiler used,
  `ENTRY_REGISTERS_VOID(vcSceneObjectUnlink, g_eax, g_esi, g_ebx)`) and its result in eax; the pipeline's `hand` step hands the
  entries to the recompiler, which generates no body for them and calls the entries instead. It calls
  the functions still recompiled with `CALL(vcFileReadU32, file, at)` and a callback with
  `CALL_AT(address, ...)`, and one written by hand directly (the build takes C4113 as an error, so a
  `CALL` left on a function that has become C fails); a local it hands them by address lives in the
  guest's stack.
- **Checking that nothing changed**, after every change:

  ```bash
  py -3 tools/verify_c.py
  ```

  ```bash
  py -3 tools/scenario.py
  ```

  ```bash
  py -3 tools/noise_report.py
  ```

  `verify_c.py` runs each function written by hand against the game's own machine code with
  xboxrecomp's conformance harness (it needs a 32-bit MSVC): eax and the memory, the game's variables
  included, and names any function it compared with nothing.
  `scenario.py` plays the scripted scenarios
  of `tests/scenarios/` (the menu, the first mission, a save, the training) with every clock the game reads tied to the
  frames and an empty save folder of its own, so runs repeat frame for frame, and compares every dumped
  frame and saved file with the reference the build before wrote (`--save` records it). `noise_report.py`
  counts what keeps the generated C from reading as written and fails if a count went up
  (`--save` after a round that brought some down).
- **Checking against the original**: the same scenarios run on the original game in xemu, patched to
  dump its frames with the port's numbers and to answer the game's clock and pad as the port does
  (`tools/reference/xemu/` has the patch, how to build it and what it needs of your own console), and
  each frame is set against the port's; it fails when a frame is further than the scenario's `original`
  line allows:

  ```bash
  py -3 tools/xemu_reference.py menu mission1 save training
  ```

## Layout

```
game/                   your game's folder (ignored by git)
src/main.c              host entry: loads the XBE, brings up the runtime, calls the recompiled entry point;
                        names the Direct3D device's GPU fence
src/game/               the game's C written by hand, by subject (engine/objects.c, files.c, format.c,
                        rects.c, random.c, screen.c, text.c, render.c, classes.c, scene.c, vector.c); decomp.h and
                        decomp.c, what joins it to the recompiled C
src/recomp_manual.c     the bridges' wrappers around recompiled functions, by the functions' names
src/d3d11_bridge.c      the Direct3D 11 bridge: what the game's D3D calls draw, through xboxrecomp's
                        D3D8 layer
src/input_bridge.c      the pad and the keyboard answered from the host's XInput, and the pad scripts
src/dsound_bridge.c     the game's DirectSound answered on the host: buffers, their 3D, the listener
src/sound_mixer.c       mixes the game's sounds from its memory (PCM, Xbox ADPCM) to the audio device
src/clock_bridge.c      the clock tied to the frames, for runs compared frame for frame
tests/scenarios/        the scripted scenarios and their reference frames (tools/scenario.py)
src/recomp/gen/         the recompiled C, laid out by subject: xdk/, bink/, engine/, game/ (ignored by git;
                        tools/pipeline.py writes it)
symbols/xdk_symbols.json  the XDK library symbols XbSymbolDatabase finds in the XBE (names and addresses)
symbols/lib_matches.json  the XDK library functions and variables matched against the XDK's .lib files
symbols/classes.json    the engine's object classes and their callbacks
symbols/registries.json the game's object types and their functions, by family
symbols/symbols.txt     the one place of the names, descriptions and files of the C
tools/pipeline.py       xboxrecomp's pipeline, with every output inside this repository
tools/symbols.py        writes the tools' names and the file lines into symbols/symbols.txt
tools/apply_names.py    writes the names of symbols.txt into the disassembly before recompiling
tools/apply_files.py    tells the recompiler each function's file, from symbols.txt
tools/organize_gen.py   lays the recompiled C out in its files, each function with its description
tools/noise_report.py   counts what keeps the generated C from reading as written (baseline beside it)
tools/conformance.py    runs xboxrecomp's oracle: the game's machine code and the C side by side
tools/hand_functions.py lists the functions written by hand (src/game/) and wrapped (src/recomp_manual.c),
                        for the recompiler
tools/verify_c.py       checks each function written by hand against the game's machine code
tools/scenario.py       plays the scenarios and compares their frames with the references
tools/xdk_symbols.py    makes symbols/xdk_symbols.json from XbSymbolDatabase's scan
tools/match_libs.py     makes symbols/lib_matches.json from the XDK's .lib files
tools/find_classes.py   makes symbols/classes.json from the class descriptors the game registers
tools/find_registries.py  makes symbols/registries.json from the game's object type registries
tools/make_xiso.py      packs the game's folder into an Xbox disc image (XDVDFS) for xemu
tools/xemu_reference.py runs the scenarios on the original game in xemu and sets its frames against the port's
tools/reference/xemu/   the patch that makes xemu the reference (GPL-2.0-or-later, as xemu), and its build
tools/decompile.py      the game's functions through arcade-decomp's decompiler: lifted, their stack and
                        data flow followed, their signatures found, their C written into src/decompiled/
tools/x86/              the decompiler's x86 frontend: the functions decoded, lifted to its IR, made graphs,
                        their C written; recompiled.py, what each function left recompiled reads, writes
                        and takes, read from its machine code, for the decompiled C that calls it
src/decompiled/         the decompiled C (tools/decompile.py build), each function in its recompiled
                        version's place, and x86.h, what it calls for the x86's own arithmetic and to call
                        the recompiled code
tools/core/             arcade-decomp (a git submodule), the decompiler the frontend feeds
docs/d3d.md             how the game uses Direct3D: the map for the Direct3D 11 path
analysis/               the pipeline's data: a copy of the XBE, disassembly, function and ABI databases
                        (ignored by git)
licenses/               licenses of the code this project starts from
```

## How the port works

- **Game code.** xboxrecomp lifts the XBE's x86 code into C, a function per function, with the CPU's
  registers and flags as variables and the Xbox's memory at the addresses the game expects; the C is
  compiled into a native executable. That includes the libraries the game linked statically (Direct3D,
  Bink), which run as recompiled code too.
- **Kernel.** The Xbox kernel calls the game imports are answered by the runtime with the host's
  operating system: files from `game/`, threads, events, memory.
- **Graphics.** For now the game's own Direct3D runs and writes GPU commands, which the runtime's
  pushbuffer executor draws in software. The port's way is to route the game's Direct3D calls to
  Direct3D 11 instead (`docs/d3d.md`).
- **Sound.** The game's DirectSound is not run: each of its entries is answered on the host, as the
  XDK's own would answer it, and each buffer the game fills is a voice of a mixer that reads it in the
  game's memory, decodes the Xbox's ADPCM and plays it through the host's audio device.
- **The game's files** are read where the game asks for them, from your copy, unchanged.

## Legal

- This project is licensed under the BSD 3-Clause License; see `LICENSE`.
- `CMakeLists.txt`, `src/main.c` and `src/recomp_manual.c` started from xboxrecomp's
  `templates/new-game` (MIT); see `licenses/xboxrecomp.txt`. xboxrecomp itself is not part of this
  repository.
- `tools/reference/xemu/xemu-reference.patch` changes xemu and is licensed as xemu is, GPL-2.0-or-later;
  xemu itself is not part of this repository, and neither are the console's MCPX ROM, BIOS or hard disk
  it runs with.
- `symbols/xdk_symbols.json` is the output of XbSymbolDatabase (MIT): names and addresses, no code.
- `symbols/lib_matches.json` holds names and addresses only: the XDK's libraries are read on your
  machine, and no XDK code or file is part of this repository.
- No game data and none of the game's machine code is distributed by this project: the recompiled C is
  generated from your own copy of the game and stays on your machine. The decompiled C in `src/game/` is
  written by hand for this project.
- Robotech is a trademark of Harmony Gold USA, Inc. Robotech: Battlecry was developed by Vicious Cycle
  Software and published by TDK Mediactive. This project is not affiliated with or endorsed by them or by
  Microsoft.
