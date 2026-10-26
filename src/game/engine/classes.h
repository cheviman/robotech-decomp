/**
 *    Name:        engine/classes.h
 *    Description: the engine's classes' registrations (classes.c), for the C written by hand
 *    Version:     0.1.0
 *    Created:     26-10-2026
 *    Modified:    26-10-2026
 *    Author:      Sebastian Toyos
 *
 *    symbols.txt says what each function does.
 */
#ifndef ENGINE_CLASSES_H
#define ENGINE_CLASSES_H

void vcTexture_Register(void);
void vcMaterial_Register(void);
void vcSpline_Register(void);
void vcSceneExport_Register(void);
void vcMotionFiles_Register(void);
void vcMultiSub_Register(void);
void vcSnd_Register(void);
void vcRefObject_Register(void);
void vcSkybox_Register(void);
void vcStringManager_Register(void);
void vcSpaceScene_Register(void);
void vcLineEffect_Register(void);
void vcSkyScene_Register(void);
void vcLensFlare_Register(void);
void vcPak_Register(void);
void vcDecalMgr_Register(void);
void vcSFXBank_Register(void);
void gcComponent_Register(void);
void gcAIData_Register(void);

#endif
