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
| Sound | works: xboxrecomp's emulated APU through XAudio2; movies, menu and mission music play | `RECOMP_AC97_READY=1`, the default |
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

- The mission voice `079.WAV.vo` lasts 10-30 s, but the buffer that starts with it reports stopped after
  656 ms (`ROBOTECH_TRACE_DSOUND=1`). Unclear whether that is the voice or a short effect.
- The APU's DSP runs in passthrough: no DSP effects (reverb, Dolby).

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
- **Noise** (`tools/noise_report.py`, baseline in `tools/noise_baseline.txt`): the generated C is a
  recompilation, every register a variable, every flag a temporary, every jump a label. The way to C
  that reads as written is xboxrecomp's decompilation path (`docs/DECOMP.md`): `tools.split` gives a
  function per file with its original bytes and signature, `tools.conformance` runs the original and
  the C side by side, and the recompiler's `--exclude-manual` lets each function written by hand take
  the generated one's place while the game keeps running.
- Functions the disassembler missed are found when the game calls them through a pointer
  (`[ICALL] Failed to resolve`); `symbols/seed_functions.json` lists the ones seeded by hand, and the
  build records every target (`analysis/icall_targets.dump`, merged by the pipeline's `feedback` step).
- A function the disassembler splits in pieces works only if every jump between the pieces lands on a
  function start; a jump into the middle of a piece becomes a call to an unresolved stub, which returns
  without running anything. `RECOMP_STUB_LOG=1` shows them (`[STUB] unresolved 0x... reached`); each one
  found gets a seed. The mission tick's epilogue was one (`symbols/README.md`): the fade over the first
  mission never cleared and the guest stack lost bytes every tick.

## Dead hypotheses

- **"The logos and the intro do not skip because the pad does not reach the game."** Measured: the pad
  is enumerated and every scripted press is delivered; the movies play whole. They are not skippable.
- **"The menu's text draws as rectangles because its texture is sampled wrong."** The trace showed
  swizzled textures with normalised coordinates; the cause was the simple render states (blending, alpha
  test), which the pure-device build never stores in its array.
- **"The mission's opening scene waits for a sound to finish."** Traced every buffer's status: none stays
  playing; the scene is drawn and moves under a fade quad that stays at 98 %.
- **"The menu's Valkyrie is skinned by the fixed pipeline's vertex blending."** `VERTEXBLEND` is 0 for
  all its draws: each part's matrix goes to a vertex program, in c0-c3.
- **"The layer combines the world matrix wrongly"** (the Valkyrie's parts floated apart while the
  terrain, drawn with an identity world, was right). The layer multiplies world, view and projection in
  the right order; the parts had no world matrix of their own: the bridge drew vertex-program draws
  through the fixed pipeline, with the last `SetTransform`.
