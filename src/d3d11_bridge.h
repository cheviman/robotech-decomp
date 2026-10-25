/**
 *    Name:        d3d11_bridge.h
 *    Description: the entries of the Direct3D 11 bridge that recomp_manual.c's wrappers call
 *    Version:     0.1.0
 *    Created:     25-10-2026
 *    Modified:    25-10-2026
 *    Author:      Sebastian Toyos
 *
 *    Each one is called by the wrapper of the D3D function it is named after, before the generated body,
 *    so the guest stack still holds the arguments (d3d11_bridge.c).
 */
#ifndef D3D11_BRIDGE_H
#define D3D11_BRIDGE_H

int d3d11_BridgeOn(void);

void d3d11_CreateDevice(void);
void d3d11_Clear(void);
void d3d11_Swap(void);
void d3d11_SetTexture(void);
void d3d11_TextureLockRect(void);
void d3d11_SetVertexShader(void);
void d3d11_SetTexCoordIndex(void);
void d3d11_SetTransform(void);
void d3d11_SetViewport(void);
void d3d11_SetMaterial(void);
void d3d11_SetLight(void);
void d3d11_LightEnable(void);
void d3d11_SetStreamSource(void);
void d3d11_SetIndices(void);
void d3d11_DrawVerticesUP(void);
void d3d11_DrawVertices(void);
void d3d11_DrawIndexedVertices(void);

#endif
