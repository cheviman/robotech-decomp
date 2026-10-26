# Robotech: Battlecry — Pending

The working document: **what is missing, what has been measured, what comes next**. Finished work is in
git, in its commit message and in the code's comments; it leaves this file. What stays besides the
missing work: the **dead hypotheses with their measurement**, so nobody tries them again.

The method: across first. Video, sound, controls and saves each work in their basics before any one of
them goes deep; the easy entries go in batches; what the game asks for that the port lacks is measured
(call counters, traces, what the runtime logs as unimplemented), not guessed.

## State

| Subsystem | State | How |
|---|---|---|
| Boot | legal screen, the TDK, Harmony Gold and Vicious Cycle logos, the intro, the menu, and the first mission (`m101_f.lvl`) loads and plays: the Valkyrie flies over the coast with the HUD and the radar | |
| Video | Direct3D 11 bridge: the movies, the menu (backdrop, logo, boxes, text, prompts, the Valkyrie) and the first mission's scene and HUD; see below for what is wrong | `ROBOTECH_D3D11=1`, the default |
| Sound | native: the game's DirectSound (the 29 entries it and its Bink call) answered on the host and mixed to XAudio2 through xboxrecomp's audio output; menu and mission music, the briefing's streamed voice and the effects play. In the first mission: 73 buffers (all Xbox ADPCM, 48 and 44.1 kHz, mono and stereo), 202 voices started, 24 at once at most; as loud as on the emulated APU (0.1 dB the menu's music, 0.4 dB the mission) | `src/dsound_bridge.c`, `src/sound_mixer.c`; `RECOMP_AC97_READY=1` the XDK's DirectSound on the emulated APU instead |
| Controls | the game's `XInputGetState` answered from the host (XInput pads, the keyboard on port 0: arrows d-pad, Enter START, Z X C V = A B X Y, W A S D left stick); the menu takes the presses | `src/input_bridge.c`; `RECOMP_USB=1` still enumerates the pad |
| Saves | the hard disk (UDATA, TDATA) in `%LOCALAPPDATA%\RobotechBattlecry`; title metadata and images written | `ROBOTECH_SAVE_DIR` |
| Pacing | `Swap` held to 60 Hz | `ROBOTECH_FPS` |

For testing: `ROBOTECH_GAME_DIR` pointing at a copy of the game without `vcMovie` boots to the menu in
seconds (the game skips movies it cannot open); `ROBOTECH_PAD_SCRIPT="<ms>:<button>,..."` presses buttons.

## Missing

### Video (`docs/d3d.md` has the map)

1. **Big cyan-white shapes over the mission scene**: not seen since vertex programs run (25-10-2026,
   a minute of the first mission); they were most likely effects drawn by a program through the fixed
   pipeline. To confirm over a longer run.
2. **Vertex programs run on the CPU** (the bridge, with xboxrecomp's NV2A interpreter), which drew the
   Valkyrie whole in the menu and in the mission. Left: on the GPU instead (the layer's translator lays
   the inputs out in a fixed order instead of by the declaration, and takes oPos as clip space while XDK
   programs end in screen space); vertices behind the eye are not clipped (pre-transformed); the
   coordinates' z and w are dropped (two floats a set: the layer reads the FVF's texture size field
   otherwise than the XDK, 1 = 3 floats, 2 = 4, 3 = 1). **Pixel shaders**: `SetPixelShader` is counted,
   0 draws with one so far.
3. **The training's opening scene** draws the fighter as a white silhouette on black (seen once,
   25-10-2026; no draw there uses a vertex program).
4. **Render targets**, `D3DResource_Release`, the states with no layer state (`BLENDCOLOR`,
   `TWOSIDEDLIGHTING`, `BACKFILLMODE`, `ZBIAS`, `LOGICOP`, multisample), texture ops approximated
   (`BLENDTEXTUREALPHAPM`, `MODULATE*_ADD*`, `BUMPENVMAP*`).

### Sound

- **The 3D is a distance and a pan, not the console's HRTF.** The distance's fade is the XDK's own
  (`-2000 log10(d / min)` hundredths of a decibel, held from the maximum distance; the emulated APU shows
  the volume it programs for a voice close by, 1.56 dB, the one computed here). The side is a pan that
  keeps the power, where the console filters each 3D voice with a pair of impulse responses chosen by
  the azimuth: the XDK's light HRTF table is in the XBE (0x170140, 61 azimuths every 3 degrees, per ear
  31 coefficients of 8 bits and a delay byte, written to the APU as they are). Their sign looks
  sign-and-magnitude (as two's complement the responses jump from 10 to -120 halfway), which the
  emulated APU reads as two's complement; neither is confirmed. That a 3D voice also loses its mixbin's
  6 dB of headroom is measured, not read (the mission as loud as on the emulated APU with it, 6 dB
  louder without).
- **The effects image is not run**: `dsstdfx.bin` is taken and nothing of it plays, so the I3DL2 reverb
  (each 3D voice's send, `SetI3DL2Source`) and the DSP's effects are not heard. Of the mixbins, the
  fronts (0, 1) and the 3D ones (6 to 9) are mixed to the two sides; the centre, the LFE and the rears
  are not (only Bink sends to them, copies of its two channels).
- **Bink's sound is mixed but not compared**: Bink plays its movies' sound through DirectSound too (PCM,
  written with `Lock` into a buffer it owns), which the mixer reads; the intro's sound is in the mixer's
  output (26-10-2026), not yet set against the emulated APU's.
- **With `ROBOTECH_VIRTUAL_CLOCK` the sound follows the frames presented**, so it stutters while they
  come unevenly (a load) and the clock passes the game's waits at once (the 5 s legal screen); the
  scenarios' runs sound so. A game played runs on the host's clock: Sebas's session (26-10-2026),
  movies skipped, menu at 60 frames a second, the game's time exact, no XAudio2 underrun.

### Controls

- The emulated USB path stalls: after a few dozen reports the game's driver stops queueing the pad's
  transfer (its USB code guards itself with `cli`/`sti`, no-ops here, while the controller's interrupt
  runs on another host thread). The pad's state and its rumble go to the host's XInput instead
  (`XInputGetState`, `XInputSetState`). Rumble not felt yet: in a minute of the first mission the game
  asked for none (its rumble function checks a flag first: the option, or the pad's capabilities).
- In runs nobody plays, with the movies, the game mostly never opens the pad (no `XInputOpen`, even
  70 s into the menu; 26-10-2026, 7 of 11 runs), so a pad script does not reach it. Without the movies
  and in Sebas's sessions it opens. Not looked into.

### Saves

- Memory units are not modelled: saves go to the hard disk only. The menu's Save Game works there
  (25-10-2026: a profile saved with its name, date and screenshot thumbnail, and overwritten after the
  game's own prompt). Saving in a mission not tried yet.

### Recompilation

- **Names** (26-10-2026): 2,125 of the 6,590 functions have a real name: the XDK's libraries almost
  whole (D3D 234 of 251, DSOUND 298 of 360, XPP 211 of 233), the C runtime and XAPI in `.text`, the
  engine's 35 object classes and all their slots, the object system, the engine's files, formatted strings,
  rectangles, random numbers, screen, text, the renderer's start and state setters, and the scene
  objects; the game's own object system (game/objects: 27 `GameObject` functions, families of types,
  handles with a serial, pools, messages delivered to state machines, the update every frame) and its
  object types by family. The functions the bridges wrap are called by their names too
  (`D3DDevice_Swap`, not the recompiler's `sub_00157530`). No placeholders (Sebas: no name that is a
  number, an offset or an address; `tools/noise_report.py` counts them, 0).
  - The object types: 13 families, 370 types, 1,207 functions by type and slot
    (`tools/find_registries.py`). 203 types are named from their own strings, a `type` line each in
    `symbols.txt` (the name a trigger or an action copies into its objects, the asset an entity, an
    effect or a screen loads), and `tools/symbols.py merge` names their registering functions and
    callbacks in bulk with a description each (655), with 16 callbacks several types share named by
    hand: 673 of the 1,207. Left, 167 types whose strings do not say what they are: the 43 weapons
    (only their sounds), the 16 steering behaviours (no strings), most nodes and screen elements, the
    first screens (the main menu's, with the cheat codes, and the profile's), and the types whose asset
    another type loads too (three VF-1SX, two VF-1AX, the eight missiles in pairs, the three Hiro
    Excaliburs, two female power armours, effects 0 to 5, 23 to 25, 27, 28, 30, 42, 51). Their names
    come from reading what each does.
  - `game/unsorted` went up from 1,655 to 1,723 functions with this: the 179 between the screens'
    functions from 0x0001C510 to 0x000269C0 were laid out in `game/screens` because screen functions
    were on both sides, and the object system sits among them, so they were not the screens'.
  - Left: the rest of the game's own code (about 4,400 functions, a retail build whose strings name
    little; xboxrecomp's naming paths need RTTI, assert strings, a map file or a Fusion package, and
    this title has none; nor do the PlayStation 2 and GameCube builds, both stripped, with no map file
    on their discs).
- **The base for the decompilation** (25-10-2026), done: `symbols/symbols.txt` is the one place of the
  names, descriptions, files and types (SegaSonic's format: `func`, `data`, `var`, `struct`, `field`,
  `file`, `comment`; `tools/symbols.py header` makes `symbols.h`, an accessor per field and variable for
  the C written by hand, reading the guest's memory in place); the recompiled C is laid out in 61 files
  by subject with each function's description in its header; C written by hand goes in `src/game/` and
  takes its recompiled version's place (`tools/hand_functions.py`, the recompiler's
  `--manual-functions`); and two checks. `tools/verify_c.py` runs each function written by hand against
  the game's own machine code with xboxrecomp's conformance harness (it caught a function returning 2
  for 1 on purpose: 11 of 33 vectors). `tools/scenario.py` plays the menu, the first mission and a save
  to an empty hard disk with a pad script by frame and every clock the game reads tied to the frames
  (`ROBOTECH_VIRTUAL_CLOCK`: the engine's counter, the date time() seeds srand with and saves are
  stamped with, the tick count; the kernel thunk of KeQuerySystemTime points at it), so two runs
  repeat frame for frame and file for file (60 of 60), and compares them with saved references. The
  save's list of saves shows the host's file times, so the scenario ends before it.
- **The engine in C, so far** (26-10-2026), each function the original's in what it does, read from its
  machine code (which callers read eax after it decided which hand nothing back):
  - the object system, `src/game/engine/objects.c`: the 27 functions from 0x001102C0 to 0x00111160 and
    the classes' three default callbacks;
  - the files, `files.c`: the 15 from 0x001160C0 to 0x00116560 (opening, creating, the 64 KB buffer,
    reading, seeking) and the table of the objects read from one;
  - the formatted strings, `format.c`: the two static buffers `vcFormat` uses in turn, and
    `vcStrLower`;
  - the rectangles, `rects.c`: setting, copying, growing, moving, reading one, placing one against
    the screen's title-safe part;
  - the random numbers, `random.c`: the game's sequence (restarted by `vcRandomReset`) and the
    cosmetic one (the rumble, the string manager, line effects; never restarted), a hash of a seed and
    a count; the floats worked on the emulated x87 as the original rounds them, handed back in st(0)
    (`ENTRY_CDECL0_FLOAT`);
  - the screen, `screen.c`: 9 of the 12 functions from 0x00115CA0 to 0x001160B0, the device's
    creation (640 x 480, its present parameters by the XDK's names), the title-safe part, the viewport,
    the clears and the swap. Left recompiled: the gamma ramp's, `vcScreenSetGamma` (its floats go
    through the C runtime's `pow`), and two whose purpose is not known yet (0x00115D00, 0x00115D20). 8
    of the 9 run in the scenarios; `vcScreenShutdown` runs only when the game ends, which it never does;
  - the text, `text.c`: the 13 functions from 0x001165B0 to 0x00116B60, the fonts (the default one
    read from defaultfont.tga), the characters' height and scale, a string's width, and drawing one at
    a point, aligned, shadowed, or laid out in lines within a rectangle; nearly all of it x87
    arithmetic, each operation in the original's order and rounding. 8 run in the scenarios; the 5 that
    do not are setters and `vcTextShutdown`. A width or a height is handed back in st(0)
    (`ENTRY_CDECL1_FLOAT`, `ENTRY_CDECL2_FLOAT`), which `tools/verify_c.py` does not compare: those are
    checked by the scenarios, where all but `vcTextSetScale` run. The text drawing itself,
    `vcFontDrawString`, a quad per character pushed to the GPU, stays recompiled;
  - the renderer's state setters, `render.c`: a render state and a texture stage's state set only when
    they change (the engine keeps the last values), the XDK's `D3DDevice_SetRenderState` and
    `D3DDevice_SetTextureStageState` inlined around that: simple, deferred and complex states, by the
    XDK's tables (`D3DSIMPLERENDERSTATEENCODE`, `D3DDIRTYFROM*`) and its functions. Both run in the
    scenarios. The renderer's start, `vcRenderInit` and `vcRenderBuffersInit`, stays recompiled for
    now;
  - the classes' registrations, `classes.c`: 19 of the 35, the ones that only build their
    `vcClassDesc` and hand it to `vcRegisterClass`, each a table read from the descriptors the game
    registers and checked against them byte for byte (all 35, capacities too, the same with these in
    C). The other 16 do more (a scene object's table of functions, vcLight's and vcSound's own
    globals, gcLevel's objects) and stay recompiled until that is read. The callbacks themselves
    stay recompiled: each needs its class's object read and its fields named first;
  - the scene objects, `scene.c`: 20 functions of the `vcSceneObject` every object placed in the
    world has (its rotation and position in the world and in its parent's frame, a bounding box, the
    box the queries test, flags, the game's entity it belongs to, its handle, and a tree of parent,
    children and siblings by handles): the scene's start and end, finding an object's through its
    type's table of functions, its flags (and a child taking its parent's), user, transform and
    bounds, starting and copying one, attaching it to a parent and taking it off, removing it, and
    what a change of flags does: putting it in the bounds quadtree (6 levels) or taking it out, as a
    sphere around its box, and out of the hit quadtree (7 levels, which the queries go through). Five
    take their arguments in registers as the compiler passed them (`ENTRY_REGISTERS_VOID`: eax, ecx,
    edx, esi, edi, ebx and the stack); calling a recompiled one, the C keeps the caller's esi and ebx.
    23 run in the scenarios (`vcSceneShutdown`, `vcSceneObjectReleaseChildren` and
    `vcSceneObjectGetBounds` do not). Still recompiled: the quadtrees, placing an object in its
    parent's frame, what entering and leaving the bounds quadtree does besides (the vcLight module),
    and putting an object in the hit quadtree, `vcSceneObjectInsertHitBounds`: with a radius under a
    ten-thousandth it moves the entry it has to a centre it never worked out, whatever its stack
    held, which C cannot hold the same;
  - the vector maths, `vector.c`: `vcTransformPoint`, a point turned by a rotation and moved.

  Their locals handed to other code by address live in the guest's stack, in a frame of the
  original's size and at its offsets (`vcTextDrawInRect` aligns its frame to 8 bytes, as the original
  does); a word the original keeps in its own argument's slot is in the
  frame too, or in a C variable when only the x87 reads it (called from other C, that slot is the caller's). The menu, the first mission and the save
  play as before, frame for frame and file for file (134 functions); once in some ten runs, right
  after a build, the first mission's frame 2280 differed and the eight runs after it did not: a race
  between the game's threads that the clock tied to the frames does not cover, not looked into yet. Of the first 59, 45 run in them (36 called
  from the recompiled code, 9 only from other C). `tools/verify_c.py` compares 26 with the machine code
  (209 vectors, 0 different), the game's own memory too (26-10-2026: until then only the memory the
  arguments point into, so a function that writes the game's variables passed whatever it wrote,
  and the ones with no result were not checked; a constant broken on purpose fails now); until 26-10-2026 it compared 11 while it counted 16: the harness mapped
  only the bytes the XBE's file holds, and a function that reads a variable in `.data`'s uninitialised
  part (`vcRandomCount`, `vcScreenWidth`) faulted on the original with every vector. It maps them now
  (zero, as the console's loader leaves them) and names a function compared with nothing:
  `vcObjectGetName`, which reads the class table, empty there. The other 11 of the first 59 that do not
  run are read against the machine code only: `vcObjectCollectChanged`, `vcObjectSystemShutdown`,
  `vcObjectGetSize`, `vcClassForEach`, `vcClassAddRefAll`, `vcClassDecRefAll`, `vcObjectClearChanged`,
  `vcFileCreate`, `vcFileExists`, `vcFileReadRect`, `vcFormatAppend`. `vcSceneObjectGet` is counted
  among the ones compared but faults with every vector: it jumps through the table of types, empty in
  the harness. Next: the quadtrees themselves and the scene's queries, then the classes' objects
  and their callbacks, the small ones first.
- **The disassembly, run again from scratch** (26-10-2026): 6,590 functions where the one in use had
  6,646. The 59 starts it no longer has are each inside a function it has (mostly ones the indirect
  calls seeded, which now reach over them); the code is the same, lifted as part of its neighbour, and the scenarios play as before, with
  no indirect call left unresolved. The function count of `tools/noise_report.py` moved with it.
- **Noise that comes from xboxrecomp's conventions**, counted and explained: the recompiler calls a
  function written by hand through the replacement lookup (`RECOMP_ICALL_SAFE`, "manual call", so that
  a replacement in `recomp_lookup_manual` wins), and this project replaces none there:
  `tools/organize_gen.py` turns each into a direct call to the entry, a tail jump too (26-10-2026). And `tools/verify_c.py`
  compares eax and the memory, not edx: the harness compares edx as its recompiled code keeps every
  register, but after a call to a function that hands back 32 bits or nothing no caller reads edx (the
  calling convention leaves it undefined), and the original leaves there whatever it loaded last. A function the bridges wrap keeps
  its recompiled body under its real name, `NAME_gen` (26-10-2026; the toolkit names it
  `sub_<address>_gen` and finds the wrappers by that name, so the recompiler reads a copy of
  `src/recomp_manual.c` in its naming, `tools/hand_functions.py`, and `tools/organize_gen.py` names
  the bodies after): the 61 bodies left the "unnamed".
- **Noise** (`tools/noise_report.py`, baseline in `tools/noise_baseline.txt`): the generated C is a
  recompilation, every register a variable, every flag a temporary, every jump a label. The way to C
  that reads as written is xboxrecomp's decompilation path (`docs/DECOMP.md`): `tools.split` gives a
  function per file with its original bytes and signature, `tools.conformance` runs the original and
  the C side by side, and the recompiler's `--exclude-manual` lets each function written by hand take
  the generated one's place while the game keeps running. Both run here: `tools.split` wrote the 6,646
  functions to `analysis/split/` (with the manifest), and `tools/conformance.py` runs the toolkit's
  oracle with this machine's 32-bit MSVC (it looks only under Visual Studio 2022). First measure, 12
  functions of the game, 29 vectors: 4 differ, all in `sub_00011A80`, which hands back the x87 status
  word: the original has the precision bit (0x20) set and the recompiled C does not, the lifter not
  modelling the x87 exception flags. A finding for xboxrecomp, kept apart.
- Functions the disassembler missed are found when the game calls them through a pointer
  (`[ICALL] Failed to resolve`); `symbols/seed_functions.json` lists the ones seeded by hand, and the
  build records every target (`analysis/icall_targets.dump`, merged by the pipeline's `feedback` step).
- A function the disassembler splits in pieces works only if every jump between the pieces lands on a
  function start; a jump into the middle of a piece becomes a call to an unresolved stub, which returns
  without running anything. `RECOMP_STUB_LOG=1` shows them (`[STUB] unresolved 0x... reached`); each one
  found gets a seed. The mission tick's epilogue was one (`symbols/README.md`): the fade over the first
  mission never cleared and the guest stack lost bytes every tick.

## Dead hypotheses

- **"The game links D3DX8 or XGraphics"** (they leave no version in the XBE header). Matched against
  the XDK's `d3dx8.lib` (2,622 functions) and `xgraphics.lib` (3,096): none by bytes, none 85 % alike by
  instructions anywhere in `.text`. The engine does its own maths and texture work.
- **"Some of the game is C++"** (Sebas asked: C++ or C#). The XBE links no C++ runtime (no LIBCPMT), and
  the game's code has no `operator new`/`delete`, no C++ exception handling, no `type_info`, no
  `_purecall`; its objects are handles with tables of functions, C-style. Only Microsoft's D3D8 and
  DirectSound are C++. The decompilation is in C.

- **"The logos and the intro do not skip because the pad does not reach the game."** Measured: the pad
  is enumerated and every scripted press is delivered; the movies play whole. They are not skippable.
- **"The menu's text draws as rectangles because its texture is sampled wrong."** The trace showed
  swizzled textures with normalised coordinates; the cause was the simple render states (blending, alpha
  test), which the pure-device build never stores in its array.
- **"The mission's opening scene waits for a sound to finish."** Traced every buffer's status: none stays
  playing; the scene is drawn and moves under a fade quad that stays at 98 %.
- **"The mission voice `079.WAV.vo` stops after 656 ms"** (measured on the emulated APU). Natively it
  streams through the game's 73,728-byte ring (read, a play region, `Play` looping, the game refilling it
  behind the play cursor) from frame 1081 to 1260 of the mission scenario, where the script's A skips
  the briefing and the game stops it.
- **"With native sound the menu ignores the pad until the title music's first section ends"** (it took
  the A of frame 360 on the emulated APU and not natively). An A at frame 600, after the section ended at
  501, was ignored too: the pad was not reaching the game. Without the XDK's DirectSound taking 7.7 MB of
  contiguous memory first, the USB's HCCA came
  back at physical 0x00082000, inside the XBE's image, and xboxrecomp's USB model read the game's code
  for it. `src/main.c` keeps the image's pages out of the contiguous arena, as the console's kernel
  does.
- **"The menu's Valkyrie is skinned by the fixed pipeline's vertex blending."** `VERTEXBLEND` is 0 for
  all its draws: each part's matrix goes to a vertex program, in c0-c3.
- **"The layer combines the world matrix wrongly"** (the Valkyrie's parts floated apart while the
  terrain, drawn with an identity world, was right). The layer multiplies world, view and projection in
  the right order; the parts had no world matrix of their own: the bridge drew vertex-program draws
  through the fixed pipeline, with the last `SetTransform`.
