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

1. **Big cyan-white shapes over the mission scene**: clouds or sky drawn as if additive with full alpha.
   Seen while the mission's logic was stopped (see Recompilation); not in the frames since. To recheck
   over a longer run before tracing them (`ROBOTECH_D3D11_TRACE=1`).
2. **The menu's Valkyrie looks wrongly posed** next to the pushbuffer executor's (a standing Battloid
   there). Its draws are FVF 0x112/0x142 with no vertex blending, 25 world matrices a frame for 124 draws;
   `SetModelView` is not used. Fixed on the way: the layer's `DrawIndexedPrimitiveUP` ignores
   `MinVertexIndex` (the bridge now passes ranges from 0). Not settled which picture is right.
3. **Vertex programs** (none measured yet: every draw so far is FVF) and **pixel shaders** (none
   measured either: `SetPixelShader` is counted, 0 draws with one).
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
  runs on another host thread). Bypassed by answering `XInputGetState` from the host; rumble
  (`XInputSetState`) still goes the USB way.

### Saves

- Memory units are not modelled: saves go to the hard disk only. Saving in a mission not tried yet.

### Recompilation

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
- **"The menu's Valkyrie is skinned."** `VERTEXBLEND` is 0 for all its draws.
