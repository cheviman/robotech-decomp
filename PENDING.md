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
- **Bink's sound is not heard yet**: Bink plays its movies' sound through DirectSound too (PCM, written
  with `Lock` into a buffer it owns), which the mixer reads; the scenarios run without the movies, so it
  has not been listened to.

### Controls

- The emulated USB path stalls: after a few dozen reports the game's driver stops queueing the pad's
  transfer (its USB code guards itself with `cli`/`sti`, no-ops here, while the controller's interrupt
  runs on another host thread). The pad's state and its rumble go to the host's XInput instead
  (`XInputGetState`, `XInputSetState`). Rumble not felt yet: in a minute of the first mission the game
  asked for none (its rumble function checks a flag first: the option, or the pad's capabilities).

### Saves

- Memory units are not modelled: saves go to the hard disk only. The menu's Save Game works there
  (25-10-2026: a profile saved with its name, date and screenshot thumbnail, and overwritten after the
  game's own prompt). Saving in a mission not tried yet.

### Recompilation

- **Names** (25-10-2026): 1,246 of the 6,646 functions have a real name: the XDK's libraries almost
  whole (D3D 234 of 251, DSOUND 298 of 360, XPP 211 of 233), the C runtime and XAPI in `.text`, the
  engine's 30 object classes and their measured slots. No placeholders (Sebas: no name that is a number,
  an offset or an address; `tools/noise_report.py` counts them, 0). Left: the game's own code (about
  5,400 functions, a retail build whose strings name nothing; xboxrecomp's naming paths need RTTI, assert
  strings, a map file or a Fusion package, and this title has none), and the 366 types of the game's
  registries, found but not named: next, what each registry slot is (the generic function that calls
  it) and each type's name (its strings and behaviour).
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
  save's list of saves shows the host's file times, so the scenario ends before it. First functions
  written by hand: the object system's three default callbacks; first types: the object system's
  `vcClassDesc`, `vcClass`, `vcInstance`.
- **Noise that comes from xboxrecomp's conventions**, counted and explained: a direct call to a function
  written by hand goes through the replacement lookup (`RECOMP_ICALL_SAFE`, "manual call": the toolkit
  makes sure no caller bypasses a replacement; 21 of the "indirect calls" for the first three
  functions); it goes away as the callers are written by hand too. A function the bridges wrap keeps
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
