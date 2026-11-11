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
   right since 28-10-2026. With `ROBOTECH_VP_GPU=1` the program's oFog is in the shader
   (`vertex_program_hlsl.c`, `finish`), dropped the same way, where it could go to the layer's fog.
2. **Vertex programs run on the CPU by default** (the bridge, with xboxrecomp's NV2A interpreter), which
   drew the Valkyrie whole in the menu and in the mission; **on the GPU with `ROBOTECH_VP_GPU=1`**
   (29-10-2026, `src/vertex_program_hlsl.c`): every program of the nine scenarios on the GPU, the frames
   as the CPU's but for a pixel here and there (0.0002 of 255 apart at most), each scenario within its
   limit against the original. Measured in Goodbye Graystone, unpaced (`ROBOTECH_FPS=0`, the virtual
   clock, 3,600 frames): the run in 48.0 s on the CPU, 42.1 s on the GPU (75.0 and 85.6 frames a
   second); the two-second windows' median 47.5 and 61.5 fps, the heavy stretch 41 to 44 and 48 to 54
   fps. Timed in the bridge (a QueryPerformanceCounter around each part, not kept): the vertex programs
   from 4 to 5 ms a frame to 0.6 in that stretch; paced at 60, the scenario's worst windows went from
   18.6, 33.2 and 36.7 fps to 27.8, 55.5 and 55.5. The programs were not what made the frame long (4).
   Left: the GPU path as the default; vertices behind the eye are not clipped (pre-transformed); the
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
4. **The indexed draws without a program are what makes a heavy frame long**: Goodbye Graystone's heavy
   stretch, 17 to 20 ms a frame with the programs on the GPU, spends 13 to 17 of them in
   `D3DDevice_DrawIndexedVertices`, some 1,150 calls a frame of an FVF (about 12 us each; the programs'
   draws 0.6 ms, the pushed ones and `DrawVertices` 0.2, `Present` 0.7; 29-10-2026, timed in the bridge).
   Each goes to the layer's `DrawIndexedPrimitiveUP`, which makes an immutable vertex buffer and index
   buffer a draw and prepares its shaders' constants (three maps) again; a ring of the bridge's own, as
   the GPU path's vertices have, would leave the layer only its preparation.
5. **After the decompilation** (Sebas, 29-10-2026: the decompiled C first, a clean project to work on):
   options off by default, so that the scenarios' frames stay the original's: 16× anisotropic filtering
   (the sampler where the game asks for linear or mipmapped filtering), FXAA, SMAA (iryoku/smaa, MIT, three
   passes before Present), as the Colin McRae Rally 2005 port on XboxXBERecomp has them; the reverb and
   the other effects of the Xbox's DSP, with xemu's DSP56300 interpreter (GPL: the build would be GPL
   too, Sebas's call).

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
  GPU's DPC still runs on another thread. Load brings it out: on 05-11-2026, with another heavy process
  running beside them (tools/coverage.py), Besieged and Force of Arms both went their own way at frame
  2880 (6 of 30 dumps each), and run again alone both were their references, as the other seven were.
  Left: the date the
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
  functions). Not lifted yet: the x87 (about 1,100 functions; the IR had integers only, see below), calls and
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
- **3,328 in the build: the x87** (28-10-2026, from 2,910; 4,424 of the game's 5,150 lift, from
  3,860). The x87's stack is not a stack in the C: its depth at each instruction is known before the
  code runs (`tools/x86/x87.py`: empty where a function starts and calls, one value left by one that
  hands a float back, the C runtime's helpers taking theirs from it), and st(i) is the register of its
  depth, f0 to f7. 1,010 of the 1,104 functions of the game that use the x87 have a depth at every
  instruction. The core takes floating-point values as 64-bit values with operators of their own
  ("f.something", `tools/core/decompiler/floats.py`), which its integer passes leave alone, and writes
  them as doubles, as the recompiled code keeps the x87's registers: a float loaded as FLD loads it
  (FLOAT_AT: a signaling NaN made quiet), each operation rounded as the control word says
  (x87_round), a value written to a float's memory rounded then (MEMF), the trigonometry and the
  conversions to integers as the recompiled code works them out (`src/decompiled/x86.h`). The compare
  idiom, "fcom; fnstsw ax; test ah, mask; j(n)e or j(n)p", is a branch on the compare's outcome, NaN
  as the x87 has it: `!(f0 <= t1)`, `MEMF(...) != ...`. A call or a jump to the C runtime's _ftol2 is
  the conversion it does (x87_ftol). This first step takes the functions whose x87 stays inside them:
  nothing taken from its stack or left on it, and every call to one that takes and leaves nothing.
  SegaSonic's C comes out of the core as it did, byte for byte. The nine scenarios frame for frame as
  their references. Found on the way: the game's control word is not always the 24 bits of precision
  the Xbox starts with: 0x023F (53 bits) in the missions, which x87_round follows; a "jmp _ftol2" that
  ends a function (the animations' frame count, 0x0011CE20) had its conversion lost, and the missions
  went their own way from frame 2400 (a missile's trail drawn across the screen) until it was the
  conversion too. Left: the functions that take or hand back x87 values (56 hand a float back in
  st(0); their callers with them), the 94 without a depth known, fptan, fsincos, frndint and the like;
  the floats' names (f0 is a register's, not a value's).
- **3,726 in the build: the floats handed back** (28-10-2026, from 3,328; 4,789 of the game's 5,150
  lift, from 4,424). A function that hands back a float in st(0) is C that returns a double (32 of
  them), or hands it back through `double *p_f0` when it hands back registers too (15): its st(0)
  where it returns is FLOAT0, the st(0) of a caller whose stack was empty at the call, the only way the
  game calls one. The recompiled code that calls one finds the float on its stack (the entry pushes it,
  x87_push); a call to one still recompiled takes it off (x87_pop, 244 calls). In the data flow the
  values a function keeps on the x87's stack are its own, since a callee's go above its caller's
  (decompile.py's Flow drops the float registers from what a callee writes, but for the float it hands
  back). Of the 1,008 calls of the 79 functions that hand back a float, none reads EAX after it before
  writing it but one in the C runtime (crt_fload_withFB, past the game's code): they hand back the float
  alone. A function with no x87 code of its own that hands on the float a call left it, or converts it
  with _ftol2, has its depths worked out too, so that its C does with the float what the original does.
  Found on the way: one function the C writer refuses (sub_0001D1A0, which copies a structure onto the
  stack for its callee, newly in reach once its callee lifted) took 459 others out of the build, its
  callers having been written calling its C, and theirs calling them; the build now goes through the
  analysis again without the ones refused, which stay recompiled alone. The nine scenarios frame for
  frame as their references, on the core with SegaSonic's latest (fa3fadc) under it. For a processor
  without floating-point registers the core's change writes the same types as before; it was not run on
  SegaSonic and OutRunners this time (OutRunners' session had its checkout in use). Left of the x87: 73
  functions without a depth known, 19 that call the C runtime's helpers that take their values from the
  stack (_CIacos, _CIpow and their kin), 22 that take floats on the stack themselves, 24 with an
  instruction the depth's walk does not reach, 7 with fnstsw outside a compare, 4 with fptan; the
  floats' names.
- **3,762 in the build: the calls through a pointer** (29-10-2026, from 3,726; 4,896 of the game's 5,150
  lift, from 4,789). A call through a pointer ("call [eax + 0x3A0]", the objects' callbacks and the
  classes' functions) is a call of its own in the C, as the recompiled code makes it: x86_icall finds the
  function at the address by the recompiler's tables (one written by hand, recompiled or decompiled, or
  the kernel's), as RECOMP_ICALL_SAFE_AT does, with its arguments and return address on the guest's
  stack; for the data flow it is code the compiler cannot see, with the convention that comes with it
  (EAX, ECX and EDX written; ECX and EDX read where the functions a run saw it reach read them,
  recompiled.py). It goes in only where what the callee drops is certain, which recompiled.py's
  summaries now keep by the call's address: a kernel function's, the drop the functions a run saw it
  reach agree on, or nothing where the caller drops the arguments itself right after it; a stdcall
  guessed because the function comes out even that way would put the C's frame where the original may
  not have it. Its words: what it drops, when it drops them; what its caller drops after it ("add esp,
  N", "pop ecx"); or what was pushed for it, the registers the caller saved too when the functions seen
  read more (a register passed as it came, ESI holding an object). 49 calls in the C; the recompiled
  code's own, from 897 to 850. The nine scenarios frame for frame as their references. Left: 28
  functions whose calls through a pointer drop what is only a guess, 17 that jump through one; of the
  107 more that lift, 36 more in the build (the rest drop out in the analysis or with their callers, not
  looked into yet).
- **4,259 in the build: the roots of the code not known** (29-10-2026, from 3,762; 4,921 of the game's
  5,150 lift, from 4,896). Of the 71 more that lift, the ones out of the build were the XDK's and Bink's,
  which stay out; what kept the game's own out was the code recompiled.py does not know, which the C
  never calls: 993 of the game's functions, nearly all through a few roots of the C runtime's and the
  XDK's. Now known: the C runtime's x87 helpers _CIacos, _CIasin, _CIpow and _CIfmod, which run on through
  their return address, by MSVC's contract for its intrinsics (their values on the x87's stack, none on
  the guest's, EAX, ECX and EDX theirs to change: 235 functions with them); DirectSound's MemFree, whose
  PoolFree ends in "jmp [ExFreePool]" through the kernel's table, followed as the kernel's function
  returning for it (160); memmove, whose last bytes' table is indexed from -4 to -1 after "sub ecx, 4; jb"
  (141); MSVC's sparse switches, their index a byte of a table of its own (`tools/x86/disassembler.py`:
  sub_0002FAA0, sub_0001A700, D3D_PixelJar_GetSurfaceFormat); frames set below their locals ("lea ebp,
  [esp - 0x54]") put back by "add ebp, 0x54" before "mov esp, ebp"; and the kernel's DbgPrint, reached by
  a jump the stdcall table of xboxrecomp's has no drop for: cdecl, as every call drops its arguments
  right after it, and as many as each call hands it. 429 of the game's functions still not known. Found on
  the way: DbgPrint's arguments counted first by the most a call drops after it, 70 words where one
  caller drops several calls' together ("add esp, 0x118"), made the summaries of the functions that print
  read 70 words of their stack, and three missions went their own way from frame 2640, until each call
  counted them (found by turning the round's changes off one at a time: a build of part of the
  decompiled functions does not test the rest, since a function's signature comes out of its callers
  being decompiled or not); and a byte table its compare does not bound (D3D_LazySetTextureTransform's)
  took the D3D draws and 162 functions out of the build until its entries were read as before. The build
  keeps the functions the C writer refuses (analysis/refused_functions.json) and goes through the
  analysis once. The nine scenarios frame for frame as their references. Left as roots: jumps through a
  pointer whose callers do not all drop the arguments right after (sub_0001EAD0, an object's callback, 33
  functions with it; vcSceneObjectGet, 24), sub_00133FB0, which reads its return address (24).
- **4,332 in the build: the last roots of the code not known** (29-10-2026, from 4,259; 4,922 lift).
  A jump through a pointer is cdecl where one call of its function drops the arguments right after it
  (a function has one convention for all its calls; the others drop them later with another call's:
  sub_0001EAD0, vcSceneObjectGet), its arguments as many as each call hands it. "lea esp, [esp]", the
  compiler's fill before a loop, is nothing to recompiled.py, which took it for the address of the
  return address (sub_00133FB0). 330 of the game's functions not known, from 429, nearly all pieces of
  others the disassembler took for functions of their own, reached by a jump (they return with ESP
  where their owner has it, or hand its return address on). Found on the way: a call of a function that
  counts its arguments by its callers was handed the words pushed for it without the registers the
  caller saved, and a register passed as it came ("push esi; push 0x10") went missing: ambush_hills went
  its own way from frame 2880, goodbye_graystone from 3240. decompile.site_count now takes what the
  caller drops right after the call, else every word pushed for it, never fewer than the callee reads
  (a word more is one it never looks at), for the C runtime's sprintf and its kin too. The nine
  scenarios frame for frame as their references.
- **4,365 in the build: functions with variable arguments whose stack stays in memory** (29-10-2026,
  from 4,332). Of the game's functions that lift and stayed out, 88 took the address of their arguments
  (a variable argument list: GameObjectSendMessage, a message and what goes with it) and kept their stack
  in memory, which lays the arguments out on the guest's stack as it starts, as many as it takes. Such a
  function now lays out the most any call of it hands it (decompile.calls_count, each call counted by
  site_count; none where a call does not say, a jump reaches the function or a run saw it called through
  a pointer), and each call hands it its own words (decompile.escaping_calls), the rest 0, words it
  never looks at. Found on the way: a caller whose stack stays in memory took the most words, past its
  own pushes up to its return address, and the C writer refused 21 functions that were in before; and the
  words a call does not hand left unset made every caller seem to carry its caller's on (2,479 functions
  out of the build) until they were 0 (arguments.unhanded). The nine scenarios frame for frame as their
  references. Of the rest that lift and stay out, some 200 are pieces of other functions; 21 have a frame
  "mov esp, ebp" ends where the scan lost EBP; 23 call code not known; 16 go with a function they call or
  that calls them.
- **4,374 in the build: the C runtime's x87 helpers called from the C** (29-10-2026, from 4,365; 4,932
  lift, from 4,922). A call of _CIacos, _CIasin or _CIfmod, which take their values from the top of the
  x87's stack and leave their result in st(0), is an expression of x86.h's (`f0 = x87_CIacos(0x...u, f0)`):
  the values onto the recompiled code's stack, the deepest first, the recompiled helper run with the
  original's return address under it, its result taken off (x87.lift_crt). 9 calls in the C. _CIpow is
  in no function of the disassembler's own (crt_CIpow_default lies inside another's bounds), and its
  callers stay out. The nine scenarios frame for frame as their references.
- **The data by name, before the functions' names** (30-10-2026; the order arcade-decomp's kit now
  follows, Sebas: the data named and typed before the C, so that the C never reads the program's bytes
  by their address). The decompiled C read 23,536 places at an address (12,974 of them): 17,550 words of
  `.data` (the game's variables), 3,904 floats of `.rdata` (the compiler's constants), 1,014 floats of
  `.data`, some 530 others. First step: a finite float or double the x87 loads from `.rdata`, which the
  XBE's header marks read-only and nothing writes, is its value (`x87.READ_ONLY`), written as the C
  literal in the fewest digits that make that float (`0.033f`; `0.5`, `255.0` without the f where the
  digits are the float exactly, so that no two float literals are worked out as floats in one
  expression: none are). Reads at an address: 23,536 to 19,611. The nine scenarios frame for frame as
  their references. Next: the XBE's bytes classified (code, data, fill), then its tables and variables
  named and typed (symbols.txt `var`, `struct`, `field`), the strings and the integer constants of
  `.rdata`; the functions' names after that.
- **The XBE's bytes classified** (05-11-2026): `tools/coverage.py` gives every byte of every section, as the
  loader lays it out, one class, as arcade-decomp's coverage does for a program ROM: code (the functions'
  bytes), described data (symbols.txt's var lines, jump tables and the byte tables of sparse switches, the
  strings, the constants the code loads from `.rdata` by address with the instruction's width, the words
  that hold a function's entry or a string's start, the kernel's import table, the title's and the saves'
  images and Dolby's program), referenced data (from a place the code reaches up to the next known thing),
  fill (int3, nop, zeros and MSVC's multi-byte nops such as "lea ecx, [ecx+0]" between a function and its
  jump table or the next function; zeros up to a word after described data) and unknown. The game's own is
  its and the engine's code (symbols.txt's file lines: XAPI and the C runtime lie among it in `.text`) and
  the part of `.rdata` and `.data` its code reaches, the linker having put each object's constants and
  variables one after another: a place is the game's when its code (or symbols.txt) reaches it, the
  libraries' when only theirs does, the bytes after it with it. The game's: 1,237,883 bytes of code, none
  unknown; 64,267 described, 898,918 referenced (nearly all of `.data`'s uninitialised part, the game's
  variables), 39,408 fill, 15,284 unknown (12,964 in `.rdata`, 2,320 in `.data`). The libraries': 34,730
  unknown, most of it Bink's, DirectSound's and the C runtime's tables in `.rdata` that their code reaches
  through a register. `tools/noise_report.py` counts the game's unknown and referenced bytes
  (`xbe_unknown_bytes`, `xbe_untyped_bytes`). What the unknown data is: elements of tables the code walks by
  an index (records of 0xA8 bytes from 0x1B00C0, each a mission's, "v602", "v103"...; a run of float
  records in `.rdata` from 0x1922D8; pairs of halfwords from 0x1BA55C) after a string the scanner found
  inside one of them, which ends the referenced run before it; they go once the tables are typed. Left in
  the code: two pieces of XAPI that only an exception's scope table reaches (0x15E21, 0x1601B), counted
  with the libraries. Next: the tables typed (their count and their record's structure), then the
  variables, named in batches by the subsystem whose functions reach them.
- **The core on arcade-decomp's c069e35** (05-11-2026, from a832d1d: the game's state as one structure,
  pointers kept into it, tables by name, counted indexes, the other games' commits). For x86 the only change
  is 16 `unreachable();` after a switch whose every case returns (`src/decompiled/x86.h` defines it as
  `__assume(0)`, as the other games' support headers do); the game's state as a structure is a profile's
  setting (`memory.STATE`) Robotech's does not set yet: the Xbox's memory left behind (below) is that step.
  Counted now: the control flags the structurer keeps where a jump has no other C (`bool L_<address>`,
  `decompiled_control_flags`), 206 in 81 functions; four of those end in a chain of ifs over their flags
  after a switch, which MSVC warns can run off the end without a value (C4715: sub_000A2540,
  sub_000CBD10, sub_000CC0A0, sub_000D4680), where the original's cases always set one of them.
- **Tables of records in place, by their fields** (05-11-2026). A `var` of symbols.txt takes a structure
  for its type: one record in place (`var EntityFamily GameObjectFamily`) or a table of them (`var Levels
  Level[76]`); symbols.h gives the table's address, `NAME_VA`, and each record's, `NAME(i)`, which the
  fields' accessors take. The decompiled C reads a record's field by name where the code reaches it at a
  fixed address or by an index times the record's size (`Level_chapter(Levels(level))`,
  `GameObjectType_size(ReconLightEffectType_VA) = 0x70u;`), a record's address worked out from an index as
  `Levels(level)`, and any address of a place symbols.txt names that the C uses as a value by that name
  (`ecx = Levels_VA;`, `x86_rep_stos32(PlayerFamily_VA, 0u, 0x86u);`): tools/x86/emit.py's GuestNames, and
  the X86Emitter's address_text, the core's hook for an address used as a value (the board's memories and
  ROM of the core's are not the Xbox's). The macros are the numbers they replace, so the C does the same.
  Typed so: the levels (75 and the one that ends them; a level's file, `m101`, which the game loads as
  NAME_f, and its title's number in the string table); the four pads' records (0x210 bytes from 0x2BE140,
  each ending in the pad's last two reads, `read` where vcPadRead writes and `read_before` where the read
  before it is moved; the two arrays of 24 words at 0x60 and 0x120 and the floats before them not named
  yet); the default font's character offsets in their texture cells (vcDefaultFontLefts); and the object
  system's records, which `tools/symbols.py merge` now writes from symbols/registries.json and the type
  lines in a section of its own: each family's GameObjectFamily (13, `EntityFamily`) and the GameObjectType
  of each type with a name (239, `ReconLightEffectType`), which its registering function fills in.
  tools/coverage.py counts a record's named fields as described and the rest of it as referenced; and it
  counts a table a register indexes ("[eax + table]") as a reference too (the font's offsets were unknown
  for that). Measured: reads and writes at a raw address 19,611 to 15,663; data addresses written as
  numbers (a new kind, `decompiled_data_addresses`) 15,513 to 14,047; memory at a computed address
  112,854 to 112,805 and at a named place no field names (a new kind, `decompiled_unnamed_fields`: what was
  a raw address and is now `MEM32(vcPads(1) + 0x78u)`) 30 to 1,720; the XBE's unknown bytes of the game
  15,284 to 14,448 (the levels' records went; the bytes after a typed record that only an earlier
  reference had reached became unknown), untyped 898,918 to 856,201. The nine scenarios frame for frame as
  their references. Left: the 131 types without a name, whose records keep their addresses.
- **The pads by their controls, the vehicles' constants and the names' buffers** (10-11-2026). The pad's
  record is typed whole. `vcPadUpdate` goes through eight pads once a frame, not four (`vcPadInit` clears
  eight, and the table ends where `vcObjectCacheData` starts): the four ports', read with `vcPadRead`, and
  four more that code not read yet fills (0x23D258 to 0x23D270, sub_00111720, sub_001128B0; a recording
  played back, by its looks). Of a pad's last two reads, a byte a control in the engine's own order of 24
  (0 to 3 the sticks' axes, 4 and 5 the sticks pressed in, 6 to 9 the d-pad, 10 and 12 the triggers, 14 to
  17 X A Y B, 18 white, 19 black, 20 START, 21 BACK; 11, 13, 22 and 23 none of the Xbox's), it makes five
  arrays: each control's value as a float (a stick's axis -1 to 1, a button 0 to 1), whether it was
  pressed or released in this frame, whether it was pressed twice within `vcPadDoublePressTime`, and when
  it was pressed. A field for each control in each array, 100 of them, since the game asks for a control
  at a fixed address (3,482 instructions reach the pads' records): `vcPad_pressed_up(vcPads(1))`,
  `FLOAT_AT(vcPad_left_y_VA(vcPads(1)))`. With them the pad's functions by name, in a file of their own
  (engine/pad: `vcPadInit`, `vcPadShutdown`, `vcPadReset`, `vcPadClearPresses`, `vcPadUpdate`,
  `vcPadSetDeadZones`, `vcPadCloseAll`, `vcPadIsOpen`, `vcPadGetHandle`, `vcPadUpdateDevices`), the dead
  zones, the ports' handles and the sticks' calibration (`vcPadCalibrations`). The vehicles: each of the
  four vehicle types keeps 62 constants in `.rdata` after its model's and its shadow's names
  (`VehicleParameters`, no field named yet; its registering function stores each one's address in the
  type's record), and after the four lie the same four again, byte for byte, which no code and no word of
  the image points at: what this file had as records of 0x12C bytes from 0x1922A4 were those copies with
  their strings between them. `tools/coverage.py` counts the rest of a name's buffer as described: the
  zeros after a string the code reaches, up to 16, 32, 64, 128 or 256 bytes from where the code takes it,
  when the next known thing or a -1 comes there (the types' files keep each name in a char[64]; 8,522 of
  the unknown bytes were those zeros). Measured: memory at a named place no field names 1,720 to 684;
  data addresses written as numbers 14,047 to 13,773; reads and writes at a raw address 15,663 to 15,654;
  functions without a name in the decompiled C 3,376 to 3,366; the XBE's unknown bytes of the game 14,448
  to 3,841, untyped 856,201 to 853,701. The nine scenarios frame for frame as their references;
  `tools/verify_c.py` 209 vectors, 0 different. `tools/decompile.py build` took 28 minutes with another
  project's decompilation running beside it. Left: a pad's control reached by a pad's offset worked out
  before (`MEM32(eax_2 + vcPad_pressed_start_VA(vcPads_VA))`, `MEM8(eax_2 + (vcPads_VA + 0x1E6u))` for
  `read_before[6]`: the emitter names a field's start, not a place inside an array field, and takes an
  index for a record's only where it sees the multiplication); the floats through `FLOAT_AT` of a
  field's address, not the field; `VehicleParameters`' fields, from the vehicles' state machine; the
  pads' recording; and the unknown bytes that are left: the -1 and the word after each name's buffer
  (172 runs of 4 bytes: the effects' and sounds' references, a name and the handle found for it), the
  tables in `.data` that sub_0012C5C0 walks up to 0x1BA66C (pairs of halfwords, by their looks the edges
  between the points of rings of 5 and of 9; the function is not read yet), the tables of words at
  0x1B9974 and 0x1B99D8, and constants nothing reaches by an address after a name (0x18FF60, the runs of
  33 to 37 bytes from 0x1930C1 and 0x19394D).
- **What the types get by name, and the players** (10-11-2026). Measured first: of the decompiled C's 15,654
  reads and writes at a raw address (10,523 addresses), 7,281 are in game/entities' functions, 2,279 in
  game/unsorted's, 1,521 in the weapons', 1,310 in the screens' and under 500 in all the engine's; 4,171 in
  the types' `X_Register` and 2,197 in their `X_Startup`. Named in this round, 179 `var` lines: what 82
  types get by name in their `X_Startup` and keep at a fixed place until their `X_Shutdown` (176: 78 numbers
  of a model's node, 24 scenes, 22 materials, 16 objects of a model, 10 sounds, 10 first objects of a scene,
  6 motions, 4 textures, 3 particle systems, and three tables the type walks as one: `SumoPackWeaponModels`
  15, `SuperVeritechPackWeaponModels` 5, `CiviliansNodeMotions` 4), by the type, the name asked for and what
  it is (`MacIIModel`, `FighterPodFrontGunNode`, `PauseScreenCursorSound`); and the players: `Players` (each
  player's object, a handle of the Player family; 201 places in the C), `PlayerCount` (38) and `PlayerPorts`
  (the pad's port each plays with; 27). Read for it: what the object system's classes are by number (1
  vcTexture, 2 vcMaterial, 8 vcSceneExport, 9 vcMotionFiles, 10 vcMultiSub, 11 vcParticleSystem, 12
  vcMultiSubObject, 15 vcSnd, 29 vcSound) and the four functions that get these, not named yet: sub_00121DF0
  (a new vcMultiSubObject from the vcMultiSub of a name), sub_0011EA70 (the number of a model's node, by its
  name; -1 for none), sub_0010E920 (a new vcSound from the vcSnd of a name), sub_00133CF0 (the first object
  of a scene). Left without a line, 95 of the 292 found: the first word of something larger, which is
  whatever the C hands on the address of or has bytes after it nothing else reaches (the screens' textures,
  each the start of a record of 0x3C bytes that sub_00126A10, sub_00126CE0 and sub_00126D00 take; the
  effects' particle systems and the veritechs' models, each the start of what the type's objects share,
  which a function of the type hands back the address of; the turrets' four motions, the record their
  parameters point at); a name a type stores at several places; and what functions without a name get (193
  places). The emitter (`tools/x86/emit.py`, GuestNames): a place inside an array field goes by the field
  (`MEM8(eax + (vcPad_read_before_VA(vcPads_VA) + 0x9u))`, 77 places), and a 16-bit read of the high half
  of a 32-bit variable is the variable shifted (`vcClassByType(((uint16_t)(ZenScoutShipScene >> 16)))`: a
  handle's class). Measured: reads and writes at a raw address 15,654 to 14,778; data addresses written as
  numbers 13,773 to 13,736; memory at a computed address 112,797 to 112,779; memory at a named place no
  field names 684, as before; the XBE's untyped bytes of the game 853,701 to 852,889, its unknown bytes
  3,841 to 3,845: the word at 0x1BC994, between `PlayerCount` and `EntityFamily`, which no instruction of
  the program touches and was counted as reached only for lying after 0x1BC990. The nine scenarios frame for
  frame as their references; `tools/verify_c.py` 209 vectors, 0 different. `tools/decompile.py build` twice, 28 minutes each (the first with the 292, which
  made 12,672 bytes unknown after the words that start something larger). Left, by what removes the most:
  the entities' records of 65 pointers (61 types' `X_Register` clear and fill one, 0x104 bytes: 62 pointers
  to the type's constants in `.rdata`, +0x34 to its target node's number, +0xC0 to its record of motions,
  +0x100 to another record of its own; an entity's first word points at its type's; about 3,900 reads; some
  35 of the 65 offsets have a reader in the decompiled C and no more than a dozen say what the constant is:
  hit points at +0x00 by its looks, 1000, 100 and 250 at +0x18 to +0x20 for every type), which wants the
  mechs' state machine (0x6A180, not lifted) read; the mechs' records of motions (0x55 words, 36 handles
  from +0x58, each stored and released by a statement of its own: slide back, run back, idle, idle or alarm,
  walk, run, slide forward, slide left, strafe left, strafe right, slide right, turn in place left, turn in
  place, up, land soft, land, five more "up", five "fall", run back, run, strafe left, strafe right, alert
  pose, alarm, the two turns in alarm, two with no name; about 2,300 reads with the Shutdowns); the weapons'
  records (27 words a type) and the effects' (14); the screens' records of 0x3C bytes; and the most-read
  addresses still raw: 0x1EAB20 to 0x1EAB2C (205 reads, the main menu's state), 0x1EA7F4 (96, floats),
  0x2B5E60 (38), 0x219A04 (36), 0x1BC760 (35), 0x1EA5F8 (32), 0x1B0A64 (30).
- **The sprites, the menus' sounds and the floats by name** (11-11-2026). An image drawn on the screen is a
  record of 0x3C bytes, read whole from the ten functions of the engine that take one and typed as
  `vcSprite`: its texture, its width and height, where it hangs from the place it is drawn at (`offset_x`,
  `offset_y`: half its size back when centred), a scale, the texture's coordinates of its four edges and a
  colour for each corner; the word at +4 nothing reads. The functions, not named yet: sub_00126D20 (sets
  one up: a texture, a width, a height, the whole texture, white), sub_00126D90 (a part of a texture, from a
  rectangle in texels, flipped across or down if asked), sub_00126C90 (its texture), sub_00126CC0 (its
  offset), sub_00126CE0 (centred), sub_00126D00 (its four colours the same), sub_00126C40 (a copy),
  sub_00126C70 (lets go of its texture), sub_00126890 (draws it at a place, if any of it is on the screen),
  sub_00126A10 (draws it turned by an angle in degrees). 200 sprites lie at fixed addresses (624 reads at a
  raw address inside them); 19 have a line, the ones of types with a name whose texture, got by name, says
  which each is (`PauseScreenGUIPauseHeaderSprite`, `PickupReticleElementPickUpRet04Sprite`). The menus'
  sounds: the screens' code asks for one by setting a word, and the screen on top plays its own sound for it
  and clears the word: `MenuCursorSoundAsked`, `MenuCancelSoundAsked`, `MenuConfirmSoundAsked` (55, 76 and
  59 places in the C; each screen keeps cursor.wav, Cancel_Back_S.wav and Confirm_S.wav in that order).
  The mission complete screen's `MissionCompleteScreenLineY` and `MissionCompleteScreenLineX`: where it
  writes its next line, each line moving the next down by its height. The emitter
  (`tools/x86/emit.py`, GuestNames.float_place): a float symbols.txt names (a variable or an element of an
  array of f32, an f32 field of a record in place, at a fixed address or by a table's index) is read as its
  value, `(double)vcPad_left_x(vcPads(0))`, and written by its name, `MissionCompleteScreenLineY =
  (float)x87_round(...)`, where it was `FLOAT_AT(vcPad_left_x_VA(vcPads(0)))` and `MEMF(...)`: the
  conversion to a double makes a signaling NaN quiet as FLD does (x86.h's x87_float), and the value goes
  into the arithmetic as a double, as before. 708 reads of a float by name, 647 of them the pads'.
  Measured: reads and writes at a raw address 14,778 to 14,392; memory at a named place no field names 684
  to 65 (what is left: a float's bits moved as a word, `MEM32(vcSprite_width_VA(...))`, and the screen's
  and the viewport's rectangles reached past their first word); data addresses written as numbers 13,736
  to 13,651; the XBE's untyped bytes of the game 852,889 to 851,805, its unknown bytes 3,845, as before.
  The nine scenarios frame for frame as their references; `tools/verify_c.py` 209 vectors, 0 different.
  Left: the other 181 sprites (a screen's several cut from one texture, each to be named for what it
  shows; the ones of types without a name; the two headings with a word after their sprite that nothing
  reaches, at 0x1E6420 and 0x20FED0); the mission complete screen's other statics (two tables of 7 words
  from 0x1EA7B4 and 0x1EA7D0, a float at 0x1EA7FC it prints); 0x2BF2F4 and 0x2BF2F8 (45 reads: the right
  edge its lines end 5 pixels before, by its looks); and the floats of `.data` to name now that a float
  goes by its name (about 1,000 reads through `FLOAT_AT` of a raw address).
- **Ghidra for reading, and the entities' record read with it** (11-11-2026, Sebas: Ghidra alone, headless,
  as a reading aid; its C never goes into the build). `tools/ghidra/`: `prepare.py` writes the XBE's
  sections as one flat image at their addresses and the list of function starts and names;
  `RobotechSeed.java` marks them before the analysis and turns the analysis of non-returning functions off
  (Ghidra took GameObjectFromHandle, vcObjectRelease and twelve more for functions that never return and
  ended their callers at the call); `RobotechDecompileAll.java` writes every function's C to
  `analysis/ghidra/out/all.c` (6,598 functions, one not decompiled; the import and the analysis take 32
  seconds); `show.py` prints some functions of it and `readers.py` lists who reads each word of the record
  an object's first word points at. No XBE loader is needed (BinaryLoader at 0x11000, x86:LE:32:default,
  the windows compiler spec); Ghidra 12.2 at `D:\ghidra`, a JDK of 25 or newer. What it adds: the 2,200
  functions tools/decompile.py does not lift, as C. 48 of the 65 words of the entities' record have a
  reader in it, against 35 in the project's own C. Read so far (each word a pointer to the constant, but
  for the three that point at other things): +0x00 the hit points (an entity's own count starts from it,
  and the damage that finishes it is this times a factor); +0x2C the mass (a change of speed times it is
  the force; a collision's damage is speed times it); +0x30 the radius (the box around its position, how
  near counts as arrived, two radii summed for a collision); +0x34 points at the number of the model's
  node "target"; +0x38 and +0x3C the forces that speed it up and stop it forward, +0x40 and +0x44 up and
  down, +0x48 and +0x4C sideways (sub_0004EDB0 works out, for each of its three axes, the force that takes
  its speed to the top speed times what the entity asks for at +0x20, +0x28 and +0x24, and keeps it within
  the second of the pair where it goes against the speed, the first otherwise); +0x50 what the top speeds
  are multiplied by, and +0x54 what those limits are, while it boosts (the entity's +0x2C above 0); +0x68 and +0x6C the top speed forward and backward;
  +0x70 the top speed up and down and +0x74 sideways (its speed along each of its axes over these is what
  it keeps at +0x20 to +0x28); +0x78 the speed it starts at (over +0x68; 100 for the pod officer, 0 for
  the rest); +0xC0 points at its record of motions; +0xC4, +0xCC and +0xD0 the camera's place behind it
  (added to the player's own, the first doubled with two players), +0xD4 a count of at most 60 for the
  camera and +0xD8 to +0xE4 two pairs for its two angles; +0xEC the angle in degrees of the cone ahead of
  it a point is tested against (120, 90, 160); +0xF0 the chance it blows up when its death's motion ends
  (it goes on to fade otherwise), +0xF4 the milliseconds it waits after that motion before either (its
  state's timer is the motion's length plus this), +0xF8 the milliseconds its remains take to fade; +0x100 points at its
  record of death motions (two lists of pairs, a motion and how many times it plays, counted at +4 and +8,
  from +0x84 and +0x94; one is picked at random). Not read yet: +0x04 (0 for every type), +0x08, +0x10 and
  +0x18 (copied to the entity at +0xA8, +0xB0 and +0x178 when it is set up), +0x24 and +0x28 (a value
  scaled by a factor of the entity's side, sub_0002D450), +0x64 (a limit of the vector at +0x78), +0xB0 and
  +0xB8, +0xE8 (a flag), +0xFC, and the 17 with no reader. The words from +0x0C to +0x2C also show
  readers that are another record's (sub_000218F0 copies them from an object that is not an entity: the
  weapons' record, by its looks). `RobotechTypes.java` gives Ghidra what the project knows, from the `types.txt` `prepare.py` writes:
  symbols.txt's 19 structures and 538 variables at their addresses, and the registers and stack arguments
  of the 1,607 functions that take a register (`analysis/decompiled_signatures.json`, less the four a
  function only saves). In its C of the whole program: a field by its name 461 to 5,699 times
  (`vcPads[0].pressed_a`), `unaff_` registers 14,432 to 10,263, `in_E..` 5,305 to 2,420, addresses as
  `DAT_` 50,876 to 44,825. Next for Ghidra: the entities' record and the entity itself as structures, with
  the types' callbacks' second argument as a pointer to one, so that it writes those fields through
  pointers by name; and each round's new names (run `prepare.py` and the three scripts again).
- **The entities' record typed: `EntitySpec`** (11-11-2026). The record of 65 words an entity's first word
  points at is a structure, with the 21 fields read so far (above: `hit_points`, `mass`, `radius`,
  `target_node`, the six forces `thrust`, `brake` and their `_vertical` and `_sideways`, `boost`,
  `boost_force`, the four top speeds `speed_forward`, `speed_backward`, `speed_vertical`,
  `speed_sideways`, `motions`, `explode_chance`, `death_wait`, `fade_time`, `death_motions`), each a
  pointer to the constant, and the records of the 48 types with a name are in place (`MacIISpec`,
  `GladiatorSpec`): `EntitySpec_hit_points(MacIISpec_VA) = 0x19DB24u;` where it was
  `MEM32(0x208618u) = 0x19DB24u;`. Measured: reads and writes at a raw address 14,392 to 11,519; memory
  at a named place no field names 65 to 2,009, as it was meant to: the 44 words nobody has read yet, in 48
  records (`MEM32(MacIISpec_VA + 0x4u)`), each of which goes by its name in all of them once it is read;
  data addresses written as numbers 13,651 to 13,565; the XBE's untyped bytes 851,805 to 847,773, its
  unknown bytes 3,845, as before. `tools/verify_c.py` 209 vectors, 0 different. The nine scenarios frame
  for frame as their references, two of them (ambush_hills from frame 2520, besieged from 2760) only on a
  second run alone: the first went beside another project's decompilation. `tools/decompile.py build` now
  ends with the seconds each of its four stages took (the analysis, each function tidied, the typing, each
  function written), to see what of its 28 minutes can be shared among processes or kept between builds
  (a change of names only changes the last stage); what of that falls in `tools/core` goes to
  arcade-decomp first. Left: the 13 records of types without a name and the player's veritech's
  (0x1EB740); the constants themselves, each type's block in `.rdata` that these words point at (the
  vehicles' are `VehicleParameters`), which the same field names would type; the 44 words not read; the
  weapons' record (19 words a type, 18 types with a name, with 7 more words before it; an object that is
  not an entity points at it the same way) and the effects'.
- **`tools/decompile.py build` from 26 minutes to 2 and a quarter, or 10 and a half** (11-11-2026, Sebas:
  under 10). Measured first, by stage: the analysis of the whole program 1,360 s of 1,534 (the data flow,
  solved five times, 80 % of it), each function tidied 89 s, the typing 25 s, each function written 60 s.
  Three things, each leaving `src/decompiled` byte for byte as it was: (1) the analysis is kept
  (`analysis/decompile_analysis.pickle`, 61 MB, the tool's own file) and read by the next build when
  nothing it is worked out from has changed (`analysis_key`: the XBE and what the disassembler found, the
  functions' names and files, the ones left recompiled, the calls through a pointer seen, and the code of
  the analysis; not symbols.txt's variables, structures and fields, nor the code that only writes the C):
  a round of names or of the emitter takes 136 s; `--fresh` works it out again. (2) The data flow goes
  through a function again only where its summary can come out different (`Flow.solve_summaries`: the
  summaries it looked up, what is live where it ends, its code or the summary kept has changed), in the
  core's order, each seeing what it sees in the core's rounds: 280,000 times a function is gone through
  to 32,875, every summary, signature and exit the same as before (compared one by one). (3) Python 3.14
  in place of 3.10 (1.28 times as fast, the same C) with its own compiler on (`PYTHON_JIT=1`, which the
  tool sets by itself; an eighth less): run it as `py -3.14 tools/decompile.py build`, the launcher's
  default being the free-threaded 3.14t, which has no such compiler and is slower. A build that works the
  analysis out: 625 s (lifting 46, the calls' summaries 91, the data flow 307, each function tidied 51,
  the typing 16, written 40). Tried and left out: the writing shared among six processes (slower, and a
  prototype's widths are known only to the process that wrote the function); threads on 3.14t (the
  structurer keeps its modes in the module's globals). The data flow's part is in the core since
  (`decompiler/dataflow.py`, `Program.solve_summaries`; arcade-decomp's branch `faster-summaries`, 59b4f57,
  on c069e35, which `tools/core` points at), for the other games, whose C has to come out the same before
  it joins arcade-decomp's main; Robotech's own Flow keeps only what is the x87's. Left: what is left of
  the analysis is the calls' summaries (91 s) and the data flow's three solves after the first.
- **The entity types' constants: `EntityConstants`** (11-11-2026). What an `EntitySpec`'s words point at
  is a record too: each type's file keeps its constants one after another in `.rdata` (the mass, the
  radius, the hit points, the forces, the top speeds...), and 35 of the 40 types with a name and a whole
  record lay them out the same where a field of the record has a name (0xF4 bytes from the mass; two
  words nobody has read swap places in 8 of them). `EntityConstants`, 19 fields with `EntitySpec`'s names
  and their own types (floats, but `death_wait`, `fade_time` and `camera_lag`, counts), and each of the 35
  types' blocks in place (`MacIIConstants`): `EntitySpec_hit_points(MacIISpec_VA) =
  EntityConstants_hit_points_VA(MacIIConstants_VA);`. Not typed: ZenCruiserTurret1, ZenReEntryPod,
  ZenReconShip, ZenShuttle and SeaSergeant, which keep constants of their own among them (two after the
  radius in four, three before the mass in one). Read with Ghidra and named in `EntitySpec`: `camera_lag`
  (+0xD4), how many of the entity's last places the camera's is the mean of (sub_000213A0 keeps them, 60 at
  most, in what the player's camera works on). Still not told apart there: +0xC4, +0xCC and +0xD0, three
  values the camera's own move towards step by step (the first doubled with two players), and +0xD8 to
  +0xE4, two pairs for the two angles it turns by towards what the entity aims at (sub_00021700).
  Measured: data addresses written as numbers 13,565 to 11,430; memory at a named place no field names
  2,009 to 1,965; the XBE's untyped bytes 847,773 to 845,024, its unknown bytes 3,845 to 3,839; reads at a
  raw address 11,519, as before. `tools/verify_c.py` 209 vectors, 0 different. The nine scenarios frame
  for frame as their references, `training` (from frame 2400) only on a second run alone. The round took
  6 minutes 22 seconds from symbols.txt to the executable (the analysis read from the build before).
  Two things seen under another project's decompilation running beside: a scenario of play differs in its
  last frames (ambush_hills, besieged, training so far) and comes out right when run again alone; and
  `verify_c.py` run right after another run of the title says "0 function vectors", which is no
  comparison, not a pass: run it again.
- **The Xbox's memory left behind as the functions are decompiled** (28-10-2026, Sebas): the game keeps
  its state in a copy of the Xbox's 64 MB, its pointers 32-bit addresses into it and its variables at
  fixed places, read through `MEM32` and `symbols.h`'s accessors; in readable C that is noise like the
  rest, and the port never goes back to an Xbox. A structure goes over to the host's memory, with real
  pointers and its variables plain C ones, once every function that touches it is C by hand or
  decompiled: by subsystem, not all at the end, since the recompiled code reads the Xbox's layout until
  then. What it opens: fields added to the game's structures (a network id, a skin's palette, a team),
  more than one world in a process (the server and the client of a quick match, replays), sizes that
  grow, ARM (Switch, Android, Mac) without translating addresses, a debugger that shows the objects by
  their fields. What it takes: a reader wherever a structure comes from disk as it is laid out in memory
  (the `VC2` objects' chunk readers to be looked at for it), and the saves' format kept, with a reader of
  its own, so the saves made before still open. The game's behaviour stays the original's: the engine's
  fixed limits (objects, missiles, particles), which decide what is drawn, are a change of their own.

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
