# Direct3D in Robotech: Battlecry

Map of how the title uses Direct3D, as the base for replacing the statically
linked XDK D3D8 with xboxrecomp's D3D8-on-D3D11 layer (`src/d3d`). Addresses are
guest VAs in `default.xbe` (TM-002, XDK 4721, D3D8 not LTCG).

## Where the names come from

`tools/xdk_symbols.py` turns an XbSymbolDatabase scan of the XBE into
`symbols/xdk_symbols.json`; `tools/apply_names.py` writes the function names into
the disassembly before recompiling (pipeline step `names`), together with the
hand-given ones in `symbols/names.json`.

| Section | Functions found | Named by XbSymbolDatabase |
|---|---:|---:|
| D3D | 251 | 115 |
| DSOUND | 360 | 86 |
| XPP | 233 | 15 |
| .text (XAPI, CRT pieces) | 5,556 | 33 |

The unnamed D3D functions are library internals; every D3D entry the game calls
has a name (one, `Direct3DCreate8`, given by hand: `mov eax, 1; ret 4`).

## The device

- `D3D_g_pDevice` at `0x00166B48` holds the device, which is a static object at
  `0x00163EF0`. Its GPU-time fence is the pair at +0x30 (time submitted) and
  +0x34 (address of the word the GPU writes back). That word is the program's
  first contiguous allocation, `0x80001000`; see `src/main.c`.
- Created once, in `sub_00115DE0`, from presentation parameters the game builds
  at `0x002BE060`: 640x480, `D3DFMT_X8R8G8B8` (7), `MultiSampleType` 0x1121
  (2 samples, horizontal supersample: a 1280x480 back buffer), auto depth
  `D3DFMT_D24S8` (0x2A). Three 1280x480x32 surfaces are allocated after it.
- Then clear + `D3DDevice_Swap` twice to blank both buffers.

## The API the game calls

77 entry points in the D3D section are called from game code (`.text`). Callers
is the number of call sites.

| Group | Address | Callers | Signature (XbSymbolDatabase) |
|---|---|---:|---|
| device | `0x00155D10` | 1 | `stdcall Direct3D_CreateDevice(Adapter, DeviceType, hFocusWindow, BehaviorFlags, pPresentationParameters, ppReturnedDeviceInterface)` |
| device | `0x00155DC0` | 1 | `stdcall D3DDevice_SetRenderTarget(pRenderTarget, pNewZStencil)` |
| device | `0x00155DE0` | 1 | `stdcall D3DDevice_SetGammaRamp(dwFlags, pRamp)` |
| device | `0x00155E70` | 1 | `stdcall D3DDevice_GetGammaRamp(pRamp)` |
| device | `0x00155FE0` | 1 | `stdcall D3DDevice_Release()` |
| device | `0x001561C0` | 1 | `stdcall D3DDevice_GetRenderTarget2()` |
| device | `0x001561E0` | 1 | `stdcall D3DDevice_GetDepthStencilSurface2()` |
| device | `0x00157530` | 4 | `stdcall D3DDevice_Swap(Flags)` |
| device | `0x001576D0` | 7 | `stdcall D3DDevice_Clear(Count, pRects, Flags, Color, Z, Stencil)` |
| device | `0x00157AC0` | 1 | `stdcall Direct3DCreate8(SDKVersion)` |
| device | `0x00159250` | 1 | `stdcall D3DDevice_SetRenderState_MultiSampleRenderTargetMode(Value)` |
| resource | `0x0015A940` | 1 | `stdcall D3DTexture_GetSurfaceLevel2(pThis, Level)` |
| resource | `0x0015A990` | 2 | `stdcall D3DTexture_LockRect(pThis, Level, pLockedRect, pRect, Flags)` |
| resource | `0x0015A9C0` | 3 | `stdcall D3DDevice_CreateTexture2(Width, Height, Depth, Levels, Usage, Format, D3DResource)` |
| resource | `0x0015AC30` | 5 | `stdcall D3DResource_Release(pThis)` |
| resource | `0x0015ACF0` | 2 | `stdcall D3DDevice_CreateVertexBuffer2(Length)` |
| resource | `0x0015AD40` | 7 | `stdcall D3DVertexBuffer_Lock2(pVertexBuffer, Flags)` |
| draw | `0x001567B0` | 19 | `stdcall D3DDevice_SetIndices(pIndexData, BaseVertexIndex)` |
| draw | `0x00159C20` | 5 | `stdcall D3DDevice_SetStreamSource(StreamNumber, pStreamData, Stride)` |
| draw | `0x0015A3B0` | 1 | `stdcall D3DDevice_DrawVerticesUP(PrimitiveType, VertexCount, pVertexStreamZeroData, VertexStreamZeroStride)` |
| draw | `0x0015A510` | 13 | `stdcall D3DDevice_DrawVertices(PrimitiveType, StartVertex, VertexCount)` |
| draw | `0x0015A5B0` | 12 | `stdcall D3DDevice_DrawIndexedVertices(PrimitiveType, VertexCount, pIndexData)` |
| state | `0x00155EA0` | 6 | `stdcall D3DDevice_SetTransform(State, pMatrix)` |
| state | `0x00155FB0` | 1 | `stdcall D3DDevice_SetMaterial(pMaterial)` |
| state | `0x00156200` | 1 | `stdcall D3DDevice_SetViewport(pViewport)` |
| state | `0x00156360` | 1 | `stdcall D3DDevice_SetLight(Index, pLight)` |
| state | `0x00156540` | 2 | `stdcall D3DDevice_LightEnable(Index, bEnable)` |
| state | `0x00156630` | 3 | `stdcall D3DDevice_SetTexture(Stage, pTexture)` |
| state | `0x00157AD0` | 1 | `stdcall D3DDevice_SetRenderState_PSTextureModes(Value)` |
| state | `0x00157B00` | 18 | `fastcall D3DDevice_SetRenderState_Simple(Method, Value)` |
| state | `0x00157E00` | 3 | `stdcall D3DDevice_SetRenderState_EdgeAntiAlias(Value)` |
| state | `0x00157E40` | 1 | `stdcall D3DDevice_SetRenderState_ShadowFunc(Value)` |
| state | `0x00157E80` | 3 | `stdcall D3DDevice_SetRenderState_FogColor(Value)` |
| state | `0x00157ED0` | 12 | `stdcall D3DDevice_SetRenderState_CullMode(Value)` |
| state | `0x00157F40` | 1 | `stdcall D3DDevice_SetRenderState_FrontFace(Value)` |
| state | `0x00157F80` | 1 | `stdcall D3DDevice_SetRenderState_NormalizeNormals(Value)` |
| state | `0x00157FC0` | 7 | `stdcall D3DDevice_SetRenderState_TextureFactor(Value)` |
| state | `0x00158020` | 1 | `stdcall D3DDevice_SetRenderState_LineWidth(Value)` |
| state | `0x00158090` | 1 | `stdcall D3DDevice_SetRenderState_Dxt1NoiseEnable(Value)` |
| state | `0x00158110` | 4 | `stdcall D3DDevice_SetRenderState_ZBias(Value)` |
| state | `0x00158190` | 2 | `stdcall D3DDevice_SetRenderState_LogicOp(Value)` |
| state | `0x001581F0` | 4 | `stdcall D3DDevice_SetRenderState_FillMode(Value)` |
| state | `0x00158240` | 2 | `stdcall D3DDevice_SetRenderState_BackFillMode(Value)` |
| state | `0x001582A0` | 1 | `stdcall D3DDevice_SetRenderState_TwoSidedLighting(Value)` |
| state | `0x00158310` | 1 | `stdcall D3DDevice_SetRenderState_VertexBlend(Value)` |
| state | `0x00158360` | 8 | `stdcall D3DDevice_SetTextureState_TexCoordIndex(Stage, Value)` |
| state | `0x00158470` | 2 | `stdcall D3DDevice_SetTextureState_BumpEnv(Stage, Type, Value)` |
| state | `0x001584E0` | 2 | `stdcall D3DDevice_SetTextureState_BorderColor(Stage, Value)` |
| state | `0x00158520` | 2 | `stdcall D3DDevice_SetTextureState_ColorKeyColor(Stage, Value)` |
| state | `0x00158F10` | 3 | `stdcall D3DDevice_SetRenderState_ZEnable(Value)` |
| state | `0x00158FA0` | 4 | `stdcall D3DDevice_SetRenderState_StencilEnable(Value)` |
| state | `0x00159030` | 1 | `stdcall D3DDevice_SetRenderState_StencilFail(Value)` |
| state | `0x001590A0` | 2 | `stdcall D3DDevice_SetRenderState_YuvEnable(Value)` |
| state | `0x001590D0` | 1 | `stdcall D3DDevice_SetRenderState_OcclusionCullEnable(Value)` |
| state | `0x00159140` | 1 | `stdcall D3DDevice_SetRenderState_StencilCullEnable(Value)` |
| state | `0x001591B0` | 1 | `stdcall D3DDevice_SetRenderState_RopZCmpAlwaysRead(Value)` |
| state | `0x001591D0` | 1 | `stdcall D3DDevice_SetRenderState_RopZRead(Value)` |
| state | `0x001591F0` | 1 | `stdcall D3DDevice_SetRenderState_DoNotCullUncompressed(Value)` |
| state | `0x00159210` | 1 | `stdcall D3DDevice_SetRenderState_MultiSampleMode(Value)` |
| state | `0x00159290` | 1 | `stdcall D3DDevice_SetRenderState_MultiSampleAntiAlias(Value)` |
| state | `0x00159310` | 2 | `stdcall D3DDevice_SetRenderState_MultiSampleMask(Value)` |
| state | `0x00159360` | 1 | `stdcall D3DDevice_SetRenderState_SampleAlpha(Value)` |
| shader | `0x001598B0` | 1 | `stdcall D3DDevice_CreateVertexShader(pDeclaration, pFunction, pHandle, Usage)` |
| shader | `0x001599F0` | 6 | `fastcall D3DDevice_SetVertexShaderConstant1(Register, pConstantData)` |
| shader | `0x00159A50` | 3 | `fastcall D3DDevice_SetVertexShaderConstant4(Register, pConstantData)` |
| shader | `0x00159BE0` | 3 | `fastcall D3DDevice_SetVertexShaderConstantNotInline(Register, pConstantData, ConstantCount)` |
| shader | `0x00159CB0` | 1 | `stdcall D3DDevice_LoadVertexShader(Handle, Address)` |
| shader | `0x00159D10` | 1 | `stdcall D3DDevice_SelectVertexShader(Handle, Address)` |
| shader | `0x00159D90` | 1 | `stdcall D3DDevice_GetVertexShaderSize(Handle, pSize)` |
| shader | `0x00159EF0` | 1 | `stdcall D3DDevice_DeleteVertexShader(Handle)` |
| shader | `0x0015A010` | 2 | `stdcall D3DDevice_SetVertexShader(Handle)` |
| shader | `0x0015A170` | 2 | `stdcall D3DDevice_SetVertexShaderInput(Handle, StreamCount, pStreamInputs)` |
| shader | `0x0015AD90` | 1 | `stdcall D3DDevice_CreatePixelShader(pPSDef, pHandle)` |
| shader | `0x0015ADE0` | 1 | `stdcall D3DDevice_SetPixelShader(Handle)` |
| shader | `0x0015AFE0` | 1 | `stdcall D3DDevice_SetPixelShaderConstant(Register, pConstantData, ConstantCount)` |
| push | `0x00155720` | 3 | `stdcall D3DDevice_EndPush(pPush)` |
| push | `0x00155CC0` | 3 | `stdcall D3DDevice_BeginPush_4(Count)` |

Most render states arrive through `D3DDevice_SetRenderState_Simple(Method, Value)`,
which takes an NV2A method number, not a `D3DRENDERSTATETYPE`: a bridge has to
translate the method back into the state it sets.

## D3D inlined into the engine

The XDK headers inline part of D3D into the title. 28 engine functions (about
24 KB, the largest at `0x0012CEC0`, `0x00142550`, `0x00118980`, `0x001271E0`)
write D3D's own globals instead of calling it:

- `D3D_g_DeferredTextureState` (`0x00166B58`, 0x80 bytes per stage) and
  `D3D_g_DeferredRenderState` (`0x00166EC8`): deferred texture-stage and render
  states, stored for D3D to send at the next draw.
- `0x00166B54`: a mask the same code ORs bits into after each store; from that
  use, the device's dirty flags (not named by XbSymbolDatabase).

So the state behind a draw is only complete in those arrays: a bridge that
intercepts the API calls alone misses it, and has to read the deferred arrays at
draw time.

## Pushbuffer written by the game

`D3DDevice_BeginPush_4` / `D3DDevice_EndPush` have 3 call sites: there the game
writes NV2A methods itself, which only an executor (or a bridge that decodes
those methods) sees.

## The bridge

`src/d3d11_bridge.c`, on with `ROBOTECH_D3D11=1`. The game's D3D keeps running
as its own bookkeeping -- it creates its objects in guest memory and keeps
their state -- but its pushbuffer is not executed (no `RECOMP_PB_EXEC`, the GPU
fence mirrored). Each routed entry is wrapped in `src/recomp_manual.c`
(`sub_X` calling the generated `sub_X_gen`): the bridge sees the call first,
with the arguments still on the guest stack, and draws it through `src/d3d`.
So entries move over one at a time and the rest keep working.

| Entry | Routed | Notes |
|---|---|---|
| `Direct3D_CreateDevice` | yes | the guest's presentation parameters copied field by field (its `HWND` is 32 bits); the host device is windowed |
| `D3DDevice_Clear` | yes | Xbox clear flags (target 0xF0, Z 0x01, stencil 0x02) translated to the layer's PC values |
| `D3DDevice_Swap` | yes | presents and pumps the window's messages; `ROBOTECH_D3D11_DUMP=<prefix>` writes the back buffer to BMPs (one in `ROBOTECH_D3D11_DUMP_EVERY`, 30 by default) |
| `D3DDevice_SetTexture` | yes | the guest texture (a D3DPixelContainer: Data, Format, Size) mirrored by a host texture of the same format and size, remade if the game reuses the address; no texture is a white 1x1, as on the console, and the stage's `COLOROP` is sent again, which the layer's `SetTexture` changes |
| `D3DTexture_LockRect` | yes | marks the texture for upload before its next draw: the game writes the texels after the lock (Bink decodes every movie frame so) |
| `D3DDevice_SetVertexShader` | yes | an FVF to the layer; a vertex program (handle with bit 0 set) loaded at 0 and run from there, as below |
| `D3DDevice_CreateVertexShader`, `LoadVertexShader`, `SelectVertexShader`, `SetVertexShaderInput`, `SetVertexShaderConstant1/4/NotInline` | yes | vertex programs, run on the CPU with xboxrecomp's NV2A interpreter (`src/kernel/nv2a_vsh_interp.c`): the declaration says which stream, offset and type each `v` register reads; the program goes into program memory where `LoadVertexShader` puts it; the constants are the game's, plus `c-38`/`c-37` (the viewport scale and offset the XDK loads itself) set to 1 and 0 so the screen-space epilogue every XDK program ends in leaves x, y, z divided by w; the bridge maps them through the viewport and draws them as `XYZRHW` vertices with two colours and four coordinate sets |
| `D3DDevice_DrawVerticesUP` | yes | Xbox primitive types (TRIANGLELIST 5 ... QUADSTRIP 9, POLYGON 10) translated to the layer's PC ones; a linear texture's coordinates, in texels on the Xbox, divided by its size |
| `D3DDevice_SetStreamSource` | yes | the vertex buffer's Data is a physical address, like a texture's; an FVF draw reads stream 0, a vertex program the streams its declaration names |
| `D3DDevice_SetIndices` | yes | the base vertex; the XDK's indexed draw takes its indices as a pointer |
| `D3DDevice_DrawVertices` | yes | from stream 0, as `DrawPrimitiveUP` |
| `D3DDevice_DrawIndexedVertices` | yes | 16-bit indices from the game's pointer, as `DrawIndexedPrimitiveUP` |
| `D3DDevice_SetTransform` | yes | XDK numbering (VIEW 0, PROJECTION 1, TEXTURE0-3 2-5, WORLD 6-9) to the layer's; the texture matrices kept and given before each draw as D3D applies them: the identity where `TEXTURETRANSFORMFLAGS` is off, and for a set of one or two elements the row its 1 meets moved to the fourth (D3D completes (u, v) as (u, v, 1, 0), the layer's shader as (u, v, 0, 1)); a lit draw's normals times W^-T W, since the layer turns them by W^-1; the view's z turned and the projection's with it, since the layer's table fog takes -z for the depth (D3D's cameras look down +z), and the coordinates generated in camera space turned back by their texture matrix |
| `D3DDevice_SetViewport`, `SetMaterial`, `SetLight`, `LightEnable` | yes | same structures on both sides |
| `D3DDevice_SetTextureState_TexCoordIndex` | yes | nothing more: the value is in the texture-stage array (index 28), where the game also writes it itself (the training's shadow, a camera-space position), and is read there with the other states |
| `D3DDevice_SetRenderTarget` | yes | not by entry: the device keeps its surfaces (+0x21B4 the target, +0x21B8 the depth), which the bridge follows before each clear and draw. A level of a texture (the surface's +0x14) makes the texture a render target on the host, with a depth buffer of its size; a projective sampling of it (`PROJECTED`) samples a cube whose +Z face it is copied to, the coordinates made a direction (2s - q, q - 2t, q), since the layer divides by nothing |
| render states, texture-stage states | yes | not by entry: before each draw the bridge reads the game's own arrays (`D3D__RenderState` at `0x00166D58`, `D3D__TextureState[4][32]` at `0x00166B58`; the inlined `SetRenderState` stores every value there) and sends what changed, translated from the XDK's values (D3D8Types.h: `D3DCMP_*` 0x200.., `D3DBLEND_*` 0x300.., `D3DCULL_*` 0x900.. against `D3DRS_FRONTFACE`, write masks and wrap bits in other places, a different `D3DTOP_*` order) to the layer's |
| everything else | no | |

The engine's movie player (`0x00118740` opens, `0x00118980` draws a frame,
`0x00118940` closes; Bink itself calls no D3D) needs just those: the legal
screen and the TDK and Harmony Gold logos play through D3D11 at their speed,
30 fps, the movies' textures being 640x448 `LIN_X8R8G8B8` (0x1E). Render states
are not routed yet; the layer's defaults happen to suit a full-screen quad.

## Consequences for the D3D11 path

`src/d3d` is a native D3D8: host pointers, COM-style interfaces, its own
resource objects. Nothing in xboxrecomp connects it to a recompiled title's
statically linked D3D, so the bridge is this project's to write:

1. Override the 77 entries (by address, `recomp_manual.c`) with functions that
   read their arguments from the guest stack per the calling conventions above
   and call `src/d3d`.
2. Keep guest resource objects (textures, vertex buffers) in step with the D3D11
   ones: the game reads their fields and locks them (`D3DVertexBuffer_Lock2`,
   `D3DTexture_LockRect`) and writes the data in guest memory.
3. Before each draw, fold in the deferred render and texture states.
4. Decode the methods behind `SetRenderState_Simple` and the 3 `BeginPush`
   sites.
