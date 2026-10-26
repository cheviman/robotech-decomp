# symbols/

What this project knows about the XBE that the disassembler and the recompiler cannot find out alone.
Every entry was measured; this file says where each came from. A name is real -- it says what the thing
is -- or there is none: a type's number, a slot's offset or an address is not a name, and what is known
of a thing without its name stays as data in these files (`tools/noise_report.py` counts any that
reaches the C).

`symbols.txt` is the one place the names, the descriptions and the files of the C live. The JSON files
are what the tools found: `tools/symbols.py merge` writes their names into `symbols.txt`'s generated
sections, and `tools/symbols.py layout` its file lines; a line written by hand in `symbols.txt` wins.

| File | Read by | What |
|---|---|---|
| `symbols.txt` | `tools/apply_names.py`, `tools/apply_files.py`, `tools/organize_gen.py`, `tools/symbols.py header` | every name (`func`, `data`, `var`), each function's description (`comment`), the files the C is laid out in (`file`), the game's structures (`struct`, `field`); SegaSonic's format, its header says how to read it |
| `lib_matches.json` | `tools/symbols.py merge` | the XDK library functions and variables matched against the XDK's `.lib` files (`tools/match_libs.py` makes it); XbSymbolDatabase's names win where both name an address |
| `classes.json` | `tools/symbols.py merge`, `layout` | the engine's classes, their registering functions and callbacks, from the descriptors the game registers (`tools/find_classes.py` makes it) |
| `registries.json` | `tools/symbols.py merge`, `layout` | the game's object types (Entity, Effect, Weapon, Screen...), their families, registering functions and callbacks, from the families the game registers at start (`tools/find_registries.py` makes it); the type lines of `symbols.txt` name them |
| `xdk_symbols.json` | `tools/symbols.py merge` | the XDK library symbols XbSymbolDatabase finds (`tools/xdk_symbols.py` makes it) |
| `seed_functions.json` | `tools.disasm --seed-functions` | function starts the disassembler missed; each entry says why in its `why` field |
| `coalesce.json` | `tools.recomp --coalesce-functions` | functions the disassembler split at a false entry, made whole; the loader takes no extra keys, so the reasons are below |

## `lib_matches.json`

Each function of `d3d8.lib`, `dsound.lib`, `xapilib.lib`, `libcmt.lib` and `libcpmt.lib` (XDK 5849) is a
pattern: its bytes, with what its relocations cover as wildcards. A pattern found at exactly one place
names it (`"how": "bytes"`); each match's relocations then name what they point at, the variables it
reads and the functions it calls (`"how": "reloc"`). Measured on 25-10-2026: 607 functions by bytes,
332 functions and variables by relocations; of the 123 addresses XbSymbolDatabase also names, all 123
agree.

What changed between 4721 and 5849 does not match by bytes; two more steps name most of it:

- **Calls in order** (`"how": "calls"`): a named function whose `.lib` version calls X, Y, Z, and whose
  code in the XBE makes as many calls, calls X, Y, Z there too; round after round, as each function
  named lends its own calls. 850 functions lent names; 24 whose calls landed on a name that said
  otherwise (their 4721 version calls in another order) lent none. 83 functions.
- **Likeness** (`"how": "likeness"`): an unnamed function among a library's code whose instructions,
  every number hidden, read at least 85 % as one `.lib` function not yet placed, 8 points ahead of the
  next. Measured first on 151 functions named by bytes, as if they were not (`--check`): it named 137,
  all right. 74 functions, then 16 more by calls from them.
- 18 patterns found at several places are left out.
- A thin wrapper (one call, its target a wildcard) fits several functions: `IDirectSoundBuffer_Play`
  matched as `PauseEx`. A match is kept only when its own address and where its calls land do not
  contradict another name; that dropped 15.
- Names carry their library, because the generated C defines functions by them and the host links its
  own C runtime and Win32: `crt_` (LIBCMT, LIBCPMT), `xapi_`, `krnl_` (kernel import stubs), and `d3d_`
  or `dsound_` for the names of D3D8 and DSOUND that do not already start with `D3D` or `DirectSound`.
- 4 functions it names are not entries of the disassembly (`crt_strchr` and three more of the C
  runtime's assembly); `apply_names.py` skips them.

## `classes.json`

The engine's objects are handles, `(type << 16) | index`. Each type registers a descriptor (0x5C bytes,
built on the stack by a function of its own) with `vcRegisterClass`: its type, its name (`vcTexture`),
a file tag (`txr`) and callbacks at fixed offsets. Each slot is called from one generic function, which
says what it is: +0x34 `Create` (`vcObjectCreate`; every one allocates), +0x38 `Destroy`
(`vcObjectRelease`; every one frees), +0x3C `Collect` (`vcObjectCollectChanged`: the children to
save), +0x40 `Load` (`vcObjectLoad`, by file version), +0x44 `Reload` (`vcObjectLoad` and
`vcObjectReload`: reads an object that exists again), +0x48 `LoadChunk` (`vcObjectLoadChunk`), +0x4C
`Copy` (`vcObjectClone`), +0x50 `InUse` (`vcObjectReleaseLater`: whether it is still in use at a time)
and +0x54 `GetSize` (`vcObjectGetSize`). +0x44 was taken for `Save` until the object system was read
(26-10-2026): it reads. 35 classes (32 `vc*` of the engine, `gcComponent`, `gcAIData` and `gcLevel` of
the game), 193 callbacks named; the 9 several classes share are left unnamed here, and
`symbols.txt` names by hand the ones that are not the defaults (`gcComponent_Create`, gcAIData's too).
The registering functions are found from their calls to `vcRegisterClass`, the class's name from the
string their code points at (26-10-2026): finding them from the disassembler's references to the
names, as the tool did first, missed `vcBeamParticleSystem`, `vcMusic`, `vcDecalMgr`, `gcLevel` and
`gcAIData`, whose names the code reads a word at a time.

## `registries.json`

The game's own objects, besides the engine's classes (game/objects, the `GameObject` functions of
`symbols.txt`): each is of a type, and the types are in 13 families, by number: Player (1 type), Entity
(74), Weapon (43), Effect (87), Structure (2), Item (6), Component (1), Trigger (16), Action (35),
Steering (16), Node (26), ScreenElement (27), Screen (36). A family is a static `GameObjectFamily`: its
name, its startup and shutdown, its types from +0x10 by number from 0, how many numbers they take, the
newest version of its objects in a file. A function of its own sets it up and registers it with
`GameObjectRegisterFamily`, and `tools/find_registries.py` starts from that function's callers
(26-10-2026; its first version looked for a block pushed before five calls or more, which missed Player,
Structure and Component, and read the types' numbers one off). Each type's registering function fills a
static `GameObjectType`: its object's size, its callbacks and the newest version its load reads. Each
callback slot is said by the generic function that calls it: +0x04 the startup (the type's first use,
`GameObjectTypeUse`), +0x08 the shutdown (its last release), +0x0C the state machine (how its objects
answer a message in a state, `GameObjectDeliver`), +0x10 the load (`GameObjectLoad`), +0x18 the collect
(`GameObjectCollect`); +0x14 is called by `GameObjectsDestroyAll`, and no type has one. Measured: 370
types and 1,207 functions by type and slot. Each type lists the strings its functions use, as hints for
its name.

A type's name is a `type` line of `symbols.txt` (`type  Trigger  0  BooleanANDTrigger  # named "Boolean
AND"`), written by hand from the type's own strings: the name a trigger or an action copies into its
objects, the asset an entity, an effect or a screen loads. From it `tools/symbols.py merge` names the
type's functions in bulk, `BooleanANDTrigger_Register`, `_Startup`, `_Shutdown`, `_StateMachine`,
`_Load`, `_Collect`, each with its description; a function every type of a family with that slot
shares is the family's (`Entity_Collect`), and one that only some share is named by hand
(`Veritech_StateMachine`, every VF-1's). A type with no string of its own that says what it is takes
its name from what makes it: a weapon from the entities that create it (`WeaponCreate`) with its sound,
a missile from the launcher that fires it (`MissileLauncherCreateMissile`). 239 of the 370 types have a
line (26-10-2026), and 785 of the 1,207 functions a name. The others: the steering behaviours (no
strings), most nodes, screen elements and screens, and the types that differ from another only in their
numbers (the VF-1SX three times, the rdf_ missiles in pairs, the three Hiro Excaliburs); their names
will come from reading what they do.

## `symbols.txt`

The names given by hand so far (its section "names given by hand", each with its description): the
XDK's `Direct3DCreate8` and XAPI's `GetTickCount`, which XbSymbolDatabase does not know; and the
engine's object system whole, written in C in `src/game/engine/objects.c` (26-10-2026): its 27
functions (registering classes, creating, sharing, cloning and releasing objects, their names, the
release queue, reading them from files) and the classes' three default callbacks; its structures
(`vcClassDesc`, `vcClass`, `vcInstance`, `vcCollectList`, the part of `vcFile` it reads) and variables
(`vcClassByType`, `vcDataDir`, the release queue, the lookup cache the game inlines, `vcGameTime`); and
the engine's files (`vcFile`, read through a 64 KB buffer), formatted strings and rectangles
(`vcRect`, `vcScreenRect`), in `files.c`, `format.c` and `rects.c` beside it; its random numbers
(`random.c`); and its screen (`screen.c`, 26-10-2026): the Direct3D device and the variables it keeps
(`vcDirect3D`, `vcDevice`, the screen's size, the viewport's rectangle), the XDK's
`D3DPRESENT_PARAMETERS` and `D3DVIEWPORT8` by their own field names, XAPI's `XGetVideoFlags`, and the
two functions that start the renderer (`vcRenderInit`, `vcRenderBuffersInit`); and its text
(`text.c`): the fonts (`vcFonts`, the default one's character widths), the characters' height and
scale, the shadow's colour and offset, and `vcFontDrawString`, which draws a string with a font; and
the renderer's state setters (`render.c`), with the records they keep and the XDK's own variables and
tables they write and read (`D3D__DirtyFlags`, `D3D__RenderState`, `D3D__TextureState`,
`D3DSIMPLERENDERSTATEENCODE`, `D3DDIRTYFROMRENDERSTATE`, `D3DDIRTYFROMTEXTURESTATE`), typed; and
the scene objects (`scene.c`): `vcSceneObject` field by field, the table of functions each type
registers for it (`vcSceneObjectTypes`, its `get` slot), the functions of its tree and flags, and the
scene's two quadtrees (`vcSceneBoundsTree`, `vcSceneHitTree`, the `vcQuadtree` functions), and the
engine's vector maths (`vcBoxCenter`, which the linker keeps with the scene, and `vcTransformPoint`).

The file lines lay the 6,590 functions out in 72 files: `xdk/` (d3d8, dsound, xapi, xapi_usb, crt),
`bink/`, `engine/` (`objects`, `screen`, `render`, `text`, `scene`, `quadtree`, `vector` and a file per
class) and `game/` (a file per
registry family). A function goes with its class, type or library, or with the functions around it when
those on both sides share one (the linker lays out an object file's functions together); a name says its
subject by a whole word (`vcText` is the text's, `vcTexture_Load` the vcTexture class's), and a class's
callback goes with its class (`vcObject_Create` is the vcObject class's, not the object system's); the
rest, 1,688, is in `game/unsorted` until it is known what it is.

## `coalesce.json`

Empty for now. The one case so far was solved with a seed instead (below): the recompiler refuses to
merge a piece the disassembler already recorded as an entry, and a function split in pieces works as
long as every jump between them lands on a real function, each piece ending in a tail call.

## The mission tick at `0x00011370`

Called through a pointer (stored at `0x0001183F`), it runs every tick of a mission. The disassembler
split it in pieces (`0x00011370`, `0x00011424`) and left its shared epilogue at `0x0001166C`
(`cmp [0x1BC410], edi; pop edi; je/jmp 0x12440; ret`) inside a piece, so every jump to it was
recompiled as a call to an unresolved stub: the epilogue never ran, the guest stack lost bytes every
tick and the mission's logic stopped -- the opening scene's fade stayed at 98 % black. Found with
`RECOMP_STUB_LOG=1` (`[STUB] unresolved 0x0001166C reached`). Seeded as a function of its own
(`seed_functions.json`), the jumps are tail calls into real code.
