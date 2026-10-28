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

1. **Fog drawn by a vertex program, and on pre-transformed vertices**: the bridge runs vertex programs on
   the CPU and hands the layer screen positions, which it fogs not at all (nor any XYZRHW draw: the
   layer's depth for them is 0); a program's oFog is dropped. The table fog of the fixed pipeline is
   right since 28-10-2026.
2. **Vertex programs run on the CPU** (the bridge, with xboxrecomp's NV2A interpreter), which drew the
   Valkyrie whole in the menu and in the mission. Left: on the GPU instead (the layer's translator lays
   the inputs out in a fixed order instead of by the declaration, and takes oPos as clip space while XDK
   programs end in screen space); vertices behind the eye are not clipped (pre-transformed); the
   coordinates' z and w are dropped (two floats a set: the layer reads the FVF's texture size field
   otherwise than the XDK, 1 = 3 floats, 2 = 4, 3 = 1). **Pixel shaders**: `SetPixelShader` is counted,
   0 draws with one so far.
3. `D3DResource_Release`, the states with no layer state (`BLENDCOLOR`, `TWOSIDEDLIGHTING`,
   `BACKFILLMODE`, `ZBIAS`, `LOGICOP`, multisample), texture ops approximated (`BLENDTEXTUREALPHAPM`,
   `MODULATE*_ADD*`, `BUMPENVMAP*`). Render targets: a texture's first level only, and a projective
   sampling only of a square one the game draws to (a cube's face, `bridge_make_cube`); texture
   transforms on pre-transformed vertices (the layer leaves them out). The camera-space normal the
   layer gives `TCI_CAMERASPACENORMAL` and `REFLECTIONVECTOR` still turns the wrong way on a rotated
   object (the bridge mends the world normals only).

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
- **To fix: a save's profile name overflows the stack when the game loads it** (27-10-2026, Sebas).
  robohaxx (github.com/InvoxiPlayGames/robohaxx) is a savegame exploit for the Xbox and GameCube
  versions: its README calls it a stack overflow in the profile name, set off by Load Game at the
  main menu, which the port runs as the original does. Not looked into yet: the function that copies
  the name, the buffer's size; the fix is the copy bounded to the buffer, a name too long refused as
  a damaged save, in the C of that function (src/game/ or the decompiled), with a save that overflows
  as a scenario.

### Recompilation

- **Names** (26-10-2026): 2,239 of the 6,590 functions have a real name: the XDK's libraries almost
  whole (D3D 234 of 251, DSOUND 298 of 360, XPP 211 of 233), the C runtime and XAPI in `.text`, the
  engine's 35 object classes and all their slots, the object system, the engine's files, formatted strings,
  rectangles, random numbers, screen, text, the renderer's start and state setters, and the scene
  objects; the game's own object system (game/objects: 27 `GameObject` functions, families of types,
  handles with a serial, pools, messages delivered to state machines, the update every frame) and its
  object types by family. The functions the bridges wrap are called by their names too
  (`D3DDevice_Swap`, not the recompiler's `sub_00157530`). No placeholders (Sebas: no name that is a
  number, an offset or an address; `tools/noise_report.py` counts them, 0).
  - The object types: 13 families, 370 types, 1,207 functions by type and slot
    (`tools/find_registries.py`). 239 types have a `type` line in `symbols.txt`, named from their own
    strings (the name a trigger or an action copies into its objects, the asset an entity, an effect or
    a screen loads) or from what makes them (a weapon from the entity that creates it, with its sound;
    a missile from the launcher that fires it, `MissileLauncherCreateMissile`; the HUD from the
    elements it creates), and `tools/symbols.py merge` names their registering functions and callbacks
    in bulk with a description each (767), with 16 callbacks several types share named by hand: 785 of
    the 1,207. By family: Player 1 of 1, Entity 57 of 74, Weapon 30 of 43, Effect 71 of 87, Structure
    1 of 2, Item 5 of 6, Component 0 of 1, Trigger 15 of 16, Action 35 of 35, Steering 0 of 16, Node 5
    of 26, ScreenElement 6 of 27, Screen 13 of 36. Left, 131 types whose strings and makers do not say
    what they are: the steering behaviours (no strings; the vehicles create three of them), most nodes,
    screen elements and screens, and the types that differ from another only in their numbers (three
    VF-1SX and two VF-1AX whose registrations hand the shared Veritech code different tables; the four
    rdf_ missiles and their launchers, the VF-1s' guns, the female power armours' weapons at two sizes;
    the three Hiro Excaliburs; effects 0 to 5, 23 to 25, 27, 28, 30, 42, 51). Their names come from
    reading what each does.
  - `game/unsorted` went up from 1,655 to 1,723 functions with this: the 179 between the screens'
    functions from 0x0001C510 to 0x000269C0 were laid out in `game/screens` because screen functions
    were on both sides, and the object system sits among them, so they were not the screens'.
  - Left: the rest of the game's own code (about 4,400 functions, a retail build whose strings name
    little; xboxrecomp's naming paths need RTTI, assert strings, a map file or a Fusion package, and
    this title has none; nor do the PlayStation 2 and GameCube builds, both stripped, with no map file
    on their discs, nor the sequel, Robotech: Invasion: see the dead hypotheses).
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
- **The original as the reference** (27-10-2026), done: xemu runs the scenarios on the original XBE
  (`tools/xemu_reference.py`, with the patch and its build in `tools/reference/xemu/`) and dumps its frames
  with the port's numbers, as MAME does for an arcade game. Counting xemu's flips was not enough: the
  console's clock goes on while the game loads (some six seconds of console time between flip 34 and 38
  before the menu, none on the port's), so the animations were shifted and the distance to the port grew
  from 6 to 27; and the console's start flips 33 times before the game's first present. xemu answers the
  same functions the port replaces as the port does (Swap counted, QueryPerformanceCounter,
  GetTickCount, GetSystemTimeAsFileTime, XInputGetState: a helper the translator calls before their first
  instruction), and its frames count from the first present. Now the menu, the first mission and the save
  are the same on both, the flight and the shots included, at a distance of 1.23 or less (the mean
  difference of the channels, 0 to 255) for the whole run, and each scenario's `original` line (1.5)
  fails the comparison when a frame goes further. The first thing it found: the menu's background emblem
  scrolls a texture by its texture matrix, which the port left still (5.0 at frame 840, now 0.98; the
  bridge now gives the layer the texture matrices as D3D applies them). What is left is the edges, from
  the console's 1280 halved to 640. The training (27-10-2026) was 121.9 apart, a black screen and a
  white fighter: the game draws the fighter's shadow to a texture, and the bridge drew everything to the
  back buffer; now 3.2 (its `original` 6.0), what is left the dialogue's timing. Every mission is in
  reach of a scenario (28-10-2026): the game menu takes codes (MainMenuScreen: with L and R held,
  left, up, down, A, right, B, START open a keyboard, whose text it sets against twelve codes, each a
  bit of the cheats' word), and WEWILLWIN unlocks every mission; a scenario's `code` line types one with
  the pad, so xemu runs it as the port does. A mission of each chapter is a scenario now: Force of Arms
  (m104, in space) at 1.25 from the start; Ambush Hills (m201), Goodbye Graystone (m1401) and Besieged
  (m2101) were 4.22, 5.20 and 18.61 apart, the table fog missing: the layer's pixel shader takes -z of
  the camera-space position for the depth, as if the camera looked down -z, and D3D's look down +z.
  The bridge turns the camera space's z for the layer (the view's third column, the projection's third
  row; the coordinates generated in camera space turned back by their texture matrix), and they are at
  1.35, 1.49 and 1.25; the training went from 3.2 to 1.60 with it (its scaffolds' edges), Rebel Revenge
  (m701) is at 1.45. All 22 missions of the Story Mode's menu were set against the original once
  (28-10-2026; with the code, chapter by chapter: R moves a chapter, right goes round a row of three,
  down to the second row; the second chapter's fourth is under its middle). Of the other 16, fourteen
  are within 1.25 to 2.55 of it, what is left the edges and the finest textures (the console draws
  1280 across, and so at another mip level), and two went apart. Deadly Storm (m1201) was 8.5 at a frame where the port still showed a
  line of dialogue: two runs of xemu differ there, its sound's clock. Backlash (m1701) went its own way
  from frame 3240 (39.1): two of the port's runs differ there and xemu's repeat, as Rebel Revenge's
  first run did (from 3240 too, the Battloid somewhere else, 32.7). The game has one thread of its
  own; beside it run the runtime's (the GPU interrupt's DPC, some six a frame, on xboxrecomp's timer
  thread) and the sound mixer's. The mixer brought the mix up to the frames presented, frames x 800
  samples, where a read of the game's brings it to the clock, whose frame rounds down to a sample short
  of that: which thread came first set where a voice the game started began, a sample apart. It goes
  up to the clock's own value for the frames now (clock_FramesTime). Whether that was Backlash's race is
  not shown: of nine runs of Backlash before the change one went its own way; after it, the survey's
  sixteen missions run again are as close to the original as before, Backlash's one run too; the
  GPU's DPC still runs on another thread. Left: the date the
  kernel gives XAPI's own calls is still the console's in xemu (a save's folder times); xemu's sound
  keeps the emulator's clock, so a voice line, and the dialogue that waits for it, ends on frames that
  change from run to run.
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
  the clock tied to the frames does not cover (the game has one thread of its own; see the original
  as the reference, Backlash). Of the first 59, 45 run in them (36 called
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

### Decompilation to C

- **The structured decompiler** (26-10-2026), started: the recompiled C runs the game an instruction at a
  time, with the CPU's registers and flags as variables; the way to C a person reads is arcade-decomp's
  decompiler (SegaSonic's, `tools/core`, a git submodule), which takes any processor lifted to its IR,
  with an x86 frontend of this repository's (`tools/x86`: Capstone decodes, the integer instructions and
  their flags lift as Intel's manual says, the functions become graphs; the stack's arguments pass in
  registers ARG0 up, since the decompiler's passes take inputs from registers). `tools/decompile.py
  check`: of the 5,150 functions of the game's code, 3,860 lift (213,492 instructions) and the core's
  stack analysis follows them all, 3,219 with the stack as slots and 641 kept in memory (a local whose
  address is passed on, about 370; EBP as a frame pointer, about 90; the rest pieces of other
  functions). Not lifted yet: the x87 (about 1,100 functions; the IR has integers only), calls and
  jumps through a pointer (147), and a few odd ones. `tools/decompile.py analyse`: the 1,395 whose
  calls all reach functions with their stack in slots go through the core's data flow, its registers
  saved and put back, its conditions (1,004 branches compare values instead of flags) and its
  signatures (`GameObjectFromHandle`: one argument, its result in EAX).
- **The decompiled C in the game** (27-10-2026): `tools/decompile.py build` writes 1,333 functions
  through the core's writer into `src/decompiled/decompiled.c`, structured, with no goto, the game's
  memory the recompiled C's (MEM8/16/32, the same bytes), and an entry each, NAME_entry, which the
  recompiled code calls in their place (`tools/hand_functions.py` hands them to the recompiler with
  the ones written by hand); `src/decompiled/x86.h` has what the C calls for the x86's own arithmetic.
  Left out: the XDK's and Bink's functions, the ones written by hand or wrapped, and the ones the C
  written by hand calls as recompiled code. The game plays the menu, the first mission and the save
  frame for frame and file for file as the references, 60 of 60. Found on the way, by halving the set
  with `tools/decompile.py subset` and the menu's
  scenario: a function that ends by jumping to another passes that one's arguments on, its caller's
  slots above its own, so it takes as many (`sub_000BF9C0`, whose tail call reads five where it reads
  one). `tools/verify_c.py --decompiled` runs them against the original too, but the toolkit's harness
  calls the game's code with arguments of its own, which most functions of the game take for
  pointers and fault on, and loses the XBE's mapping to Windows' address randomisation in long runs:
  the scenarios are the check.
- **The decompiled C calls the recompiled code** (27-10-2026): 2,610 functions in the build (from
  1,333), 0 goto, the menu, the first mission and the save as the references, 60 of 60. A function no
  longer needs every function it calls decompiled: a call of one that stays recompiled (390 of them:
  the x87's, the XDK's, the ones written by hand, the ones that call through a pointer...) goes as the
  recompiled code makes it, the registers it reads in the globals, its arguments on the guest's stack
  under the return address the original pushes (`x86_call`, `src/decompiled/x86.h`), its results
  read back; 4,238 such calls. An entry whose function calls recompiled code puts EBX, EBP, ESI and EDI
  back as they came, as the original's pops did. What such a function reads, writes on some way back
  and on every one, and the arguments it takes, comes from its machine code: `tools/x86/recompiled.py`
  follows each function with ESP (from its start, or from where "and esp, -16" aligned it), EBP as a
  frame and the registers it saves and puts back, per part of register as the core's data flow, its
  callees' summaries worked out together; a call through a pointer by the compiler's convention for
  code it cannot see, dropping what the run saw its targets drop, what the caller drops after it, or
  what was pushed for it (stdcall); the kernel's by xboxrecomp's table of their arguments
  (`stdcall_args_for_ordinal`); the C runtime's `_chkstk`, `__SEH_prolog` and `__SEH_epilog` by what
  they do to their caller's frame; a function that takes the address of its arguments (`vcFormat`,
  `GameObjectSendMessage`) with as many as each caller drops. When it cannot tell, a register is
  "maybe" written, and the C hands the caller's value in and reads it back, which is right either
  way. It knows 4,111 of the game's 5,150 functions; set against the core's data flow for the 1,389
  both see, it never says a register is always written where the core does not, and where they differ
  the core is the one that cannot tell (a register saved inside an if). Not known, and code that calls
  them stays recompiled: the C runtime's x87 helpers that read their caller's caller's frame
  (`sub_001485F1`, 235 functions behind it), DirectSound's pool, whose switch has no guard (170),
  `memmove`'s jumps by tables past where the disassembler ends it (145), and calls through a pointer
  whose arguments cannot be told. Found by halving the new functions against the first mission (it
  stayed in the briefing from frame 1200): `sub_0001166C` is no function but a piece of another's
  code ("pop edi" of a register the code that jumps there saved, then "ret"), which came in once its
  callee no longer had to be decompiled; every function decompiled now has to come out even in its
  own machine code too.
- The decompiled C's noise is counted apart (`tools/noise_report.py`, the decompiled_ kinds), with the
  bridge to the recompiled code: 1,896 functions without a name, 2,057 without a description, 60,814
  registers kept as variables by their names (23.3 a function, 17.6 before the bridge: each call of
  recompiled code hands its registers in and reads its results back by the globals), 666 flags,
  30,806 parameters named arg0 up (11.8 a function, 4.3 before: the arguments of every x86_call), 2,968
  stack slots named by their offset, 11,760 reads and writes at a raw address (4.5 a function, 7.4
  before).
- **The comparisons back** (27-10-2026): flags 12,171 to 664. The lifter binds the registers an
  instruction that sets the flags reads to temporaries (`Lifter.operand`), as the V60's does, so the
  core's condition recovery finds the values compared still holding at the branch: "cmp eax, ebx; jl"
  is `if (eax < ebx)`; "test eax, eax" the flags of EAX itself, `if (eax != 0u)`, not
  `(eax & eax) != 0u`. Left: the borrow idioms ("neg eax; sbb eax, eax", a boolean by the carry) and
  flags a call or another block sets. And a call through a pointer reads no register from the game's
  C and the C runtime's (their callbacks are cdecl), only from the XDK's C++ (ECX, "this"): 4,419
  registers fewer handed to the recompiled code (`GameObjectTypeRelease` alone took ECX and EDX at
  575 calls, for the type callbacks it calls).
- **The arguments where they are** (27-10-2026): stack slots 39,382 to 2,968. A function's argument it
  never changes is read where it came (ARG0 + n), wherever nothing before set that register for a call
  or called, and its copy into the function's own slot goes when no read needs it
  (`arguments.read_in_place`); a word pushed for a call that nothing else reads goes into its ARG
  register where it is pushed, when no call comes in between (`arguments.pass_pushes`): "push 4; push
  edx; call calloc" is `arg1_2 = 4u; arg0_2 = edx;`, not two slots the call reads after. Left: the
  arguments of a call as their own variables (arg0_2 = edx; then the call), 32,675 of them with the
  parameters, since the core's calls read their registers implicitly: putting the values into the call
  needs calls with their arguments as expressions in tools/core, which SegaSonic shares.
- **The game's variables by name in the decompiled C** (27-10-2026): reads and writes at a raw address
  13,918 to 11,760. A place `symbols.txt` names goes by the name `symbols.h` gives it (`emit.GuestNames`):
  `GameObjectTime = vcGameTime;`, an element of an array `D3D__TextureState(3)`, any other place in a
  variable or at a data label by its address, `MEM32(vcDataDir_VA + 0x4u)`; a float or a string by its
  address too, since their C types are no integers. Left: the 11,760 at places of `.data` nothing names
  yet (about 10,000 addresses, most read or written once: structures the game keeps in place, set up
  field by field), which want `var` and `struct` lines. An array's element by a computed index goes by
  name too, when the address is its start plus the index times its elements' size:
  `GameObjectFamilies(edx)`.
- **Parameters and locals by name** (27-10-2026): `symbols.txt` takes SegaSonic's `param FUNCTION REG
  NAME` (a register, eax..., or an argument on the stack, arg0 up) and `local FUNCTION WHERE REG NAME`
  (by the instructions that write it, or "entry"), which `tools/decompile.py` hands the core's writer.
  Eight param lines of the object system (`GameObjectPauseFamily(uint32_t family, uint32_t paused)`)
  took 1,869 arg names out of the C, since the core calls what a caller passes by the callee's name for
  it. Next: the naming itself, in batches (parameters, locals, the game's variables and structures),
  each batch checked by the scenarios; the functions written by hand calling the decompiled ones
  directly; the x87.
- **2,749 functions in the build** (27-10-2026, from 2,610): 139 that called a function taking the
  address of an argument (`vcObjectGet` passes `&name` on, 118 of them; `vcFileSkip`, `vcFormat`...)
  from a caller that drops the arguments later, after more code, had no count for the call. The count
  is now what `tools/x86/recompiled.py` saw pushed for the call since the call before it (the registers
  the caller saved left out), before what the caller drops right after it: six calls of `vcObjectGet`
  in a row, dropped together by one "add esp, 0x30" after the last, each hand it its 2 arguments, not
  the last 12. Of the game's 2,401 functions still out: the x87 (about 1,070, the IR has integers
  only), the stack kept in memory (603: a local whose address is passed on, EBP as a frame), the XDK's,
  Bink's and the ones written by hand (265), callees whose effects `recompiled.py` cannot tell (about
  120), calls and jumps through a pointer (52).
- **2,910 in the build: the stack in memory** (27-10-2026, from 2,749). A function whose stack the core
  cannot turn into slots (a local whose address is handed on, EBP as a frame) keeps it in the guest's
  memory, as the V60's do (stack.MEMORY_SP): its SP is the guest's, `g_esp`, a register the whole
  program shares, and its pushes, pops and locals are `MEM32(g_esp + n)`. It takes its arguments in
  ARG registers as the others do and lays them out over its return address's place as it starts, SP
  put back on every way out (`arguments.in_memory`; as many as `recompiled.py` reads it take, none
  counted by its callers); its calls take their callees' arguments from where it pushed them, and of
  recompiled code it calls only the return address goes on (`x86_call(..., 0)`, `x86_jump` for a jump).
  Found on the way: the core keeps a register the whole program shares live where a function ends only
  when told it is one (`cleanup.eliminate`'s context, and the other passes' too): without it the pops
  and the frame's putting back went, and the menu stopped at its first frame. The noise grows with
  them: 14,020 stack accesses of theirs counted among the memory at a computed address, 18,384
  registers (big functions, 114 each). Left: their frames by name.

## Dead hypotheses

- **"The game links D3DX8 or XGraphics"** (they leave no version in the XBE header). Matched against
  the XDK's `d3dx8.lib` (2,622 functions) and `xgraphics.lib` (3,096): none by bytes, none 85 % alike by
  instructions anywhere in `.text`. The engine does its own maths and texture work.
- **"Some of the game is C++"** (Sebas asked: C++ or C#). The XBE links no C++ runtime (no LIBCPMT), and
  the game's code has no `operator new`/`delete`, no C++ exception handling, no `type_info`, no
  `_purecall`; its objects are handles with tables of functions, C-style. Only Microsoft's D3D8 and
  DirectSound are C++. The decompilation is in C.
- **"Robotech: Invasion (Xbox, 2004, Vicious Cycle's next game) shares the engine's code and names
  some of it"** (27-10-2026, the USA disc). Its XBE is a retail build (XDK 5849, built 17-08-2004) with
  no symbols, no RTTI, no assert or source-file strings but Havok's, and not even the engine's class
  names (`vcTexture`, `vcSound`: one string with `vc` in it). The two XBEs share 224 strings, nearly
  all the C runtime's and XAPI's. Matched function by function (xboxrecomp's disassembly of both, each
  function's instructions with the image's addresses and the calls' targets masked, then the mnemonics
  alone, then the callees of the pairs): 223 pairs of Battlecry's 5,500 functions in `.text` and
  Invasion's 10,881, 221 of them the C runtime's and XAPI's and 2 of the game's; by each function's set
  of distinctive constants and floats, for the same source built by another compiler: 32, all the
  runtime's. Invasion's engine is another one (Havok, files by hashed names, Xbox Live); nothing in it
  names Battlecry's code.

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
