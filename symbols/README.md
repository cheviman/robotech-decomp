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
| `registries.json` | `tools/symbols.py layout` | the game's object types (Entity, Effect, Weapon, Screen...), their registering functions and slots, from the registries the game fills at start (`tools/find_registries.py` makes it) |
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
(26-10-2026): it reads. 30 classes (29 `vc*` of the engine, `gcComponent` of the game), 175 callbacks
named; the 5 several classes share (the defaults below) are left unnamed.

## `registries.json`

The game keeps registries of its own object types, besides the engine's classes: Entity (74 types),
Effect (87), Weapon (43), Screen (36), Action (35), ScreenElement (27), Node (26), Steering (16), Trigger
(16), Item (6). Each is a static block: a pointer to its name, two words, 128 type descriptors from
+0x0C, a count. One function per family writes the name and calls a registering function per type with
the block; each fills a static descriptor (the object's size, then the type's functions) and stores it
at `block[0x0C + 4 * type]`. Measured on 25-10-2026: 366 types and 1,151 functions by type and slot.
No names yet: what each slot is will come from the generic function that calls it (as with the
classes), what each type is called from its strings and behaviour. Each type lists the strings its
functions use (type 1 of Entity `VF-1DX`, type 2 `rdf_heavy_missile`, Item's type 1 `spy_capsule`,
Trigger's type 1 `Boolean AND`), as hints.

## `symbols.txt`

The names given by hand so far (its section "names given by hand", each with its description): the
XDK's `Direct3DCreate8` and XAPI's `GetTickCount`, which XbSymbolDatabase does not know; and the
engine's object system whole, written in C in `src/game/engine/objects.c` (26-10-2026): its 27
functions (registering classes, creating, sharing, cloning and releasing objects, their names, the
release queue, reading them from files) and the classes' three default callbacks; its structures
(`vcClassDesc`, `vcClass`, `vcInstance`, `vcCollectList`, the part of `vcFile` it reads) and variables
(`vcClassByType`, `vcDataDir`, the release queue, the lookup cache the game inlines, `vcGameTime`); and
the engine's file and string functions it calls (`vcFileOpen`, `vcFileReadU32`, `vcFormat`...), still
recompiled.

The file lines lay the 6,647 functions out in 61 files: `xdk/` (d3d8, dsound, xapi, xapi_usb, crt),
`bink/`, `engine/` (`objects` and a file per class) and `game/` (a file per registry family). A function
goes with its class, type or library, or with the functions around it when those on both sides share
one (the linker lays out an object file's functions together); the rest, 1,782, is in `game/unsorted`
until it is known what it is.

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
