# Robotech: Battlecry — Pending

The working document: **what is missing, what has been measured, what comes next**. Finished work is in
git, in its commit message and in the code's comments; it leaves this file. What stays besides the
missing work: the **dead hypotheses with their measurement**, so nobody tries them again.

The method: across first. Video, sound, controls and saves each work in their basics before any one of
them goes deep; the easy entries go in batches; what the game asks for that the port lacks is measured
(call counters, what the runtime logs as unimplemented), not guessed.

## State

| Subsystem | State | How |
|---|---|---|
| Boot | legal screen, the TDK, Harmony Gold and Vicious Cycle logos, the intro movie, then the menu loads (`menu_f.lvl`, the main theme, the pilots' skins) | |
| Video | Direct3D 11 bridge: the movies play whole, at their speed; the menu: see below | `ROBOTECH_D3D11=1`, the default |
| Sound | works: xboxrecomp's emulated APU through XAudio2 (the logos' and the intro's sound measured in a WAV) | `RECOMP_AC97_READY=1`, the default |
| Controls | the USB pad: a host controller through XInput, the keyboard on top (arrows the d-pad, Enter START, Z X C V for A B X Y, W A S D the left stick); the game enumerates it and reads it | `RECOMP_USB=1`, `RECOMP_KEYBOARD=1`, the defaults |
| Saves | the hard disk (UDATA, TDATA) in `%LOCALAPPDATA%\RobotechBattlecry`; the game writes its title metadata and images there | `ROBOTECH_SAVE_DIR` moves it |
| Pacing | `Swap` held to 60 Hz; with nothing executing the pushbuffer nothing waited for the vertical blank, and the menu ran at the monitor's 144 Hz | `ROBOTECH_FPS` |

## Missing

### Video (`docs/d3d.md` has the map)

1. **Vertex programs.** `CreateVertexShader`, `LoadVertexShader`, `SelectVertexShader`, `SetVertexShader`
   with a program handle, the constants (`SetVertexShaderConstant1/4/NotInline`). Draws made with one are
   left out and counted (`left out (vertex program)` in the bridge's log). xboxrecomp's layer translates
   NV2A vertex microcode to HLSL (`src/d3d/d3d8_vsh.c`).
2. **Pixel shaders.** `CreatePixelShader`, `SetPixelShader`, `SetPixelShaderConstant`: register
   combiners, which the layer has (`d3d8_combiners.c`).
3. **Render targets.** `SetRenderTarget`, `GetRenderTarget2`, `GetDepthStencilSurface2`,
   `D3DTexture_GetSurfaceLevel2`.
4. **The game's own pushbuffer**: the three `BeginPush`/`EndPush` sites, and the NV2A methods behind
   `SetRenderState_Simple` for the states the game sends only that way.
5. **Resources released**: `D3DResource_Release` is not followed; host textures stay until their address
   is reused.
6. States with no layer state: `BLENDCOLOR`, `TWOSIDEDLIGHTING`, `BACKFILLMODE`, `ZBIAS`, `LOGICOP`, the
   multisample ones; texture ops `BLENDTEXTUREALPHAPM`, `MODULATE*_ADD*`, `BUMPENVMAP*` approximated.

### Sound

- Quality not checked by ear beyond "it plays": the APU's DSP runs in passthrough (`[APU] DSP GP/EP
  initialized (STUBBED - passthrough mode)`), so the DSP effects (reverb, Dolby) are missing.

### Controls

- Logos and intro cannot be skipped (measured: A and START pressed every 1.5 s, delivered to the game,
  and every movie played whole). Not a port bug; see dead hypotheses.

### Saves

- Memory units are not modelled: saves go to the hard disk only.

### Testing

- Every run waits about 2.5 minutes of movies before the menu.

## Dead hypotheses

- **"The logos and the intro do not skip because the pad does not reach the game."** Measured with
  `RECOMP_PAD_SCRIPT` and the OHCI trace: the pad is enumerated, the periodic list is read and every
  scripted press is delivered; the movies still play whole. They are not skippable.
