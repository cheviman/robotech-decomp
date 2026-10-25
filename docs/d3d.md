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

- `D3D_g_pDevice` at `0x00166B48` holds the device. Its GPU-time fence is the
  pair at +0x30 (time submitted) and +0x34 (address of the word the GPU writes
  back); see `src/main.c`.
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
