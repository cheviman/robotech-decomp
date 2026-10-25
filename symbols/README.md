# symbols/

What this project knows about the XBE that the disassembler and the recompiler cannot find out alone.
Every entry was measured; this file says where each came from.

| File | Read by | What |
|---|---|---|
| `lib_matches.json` | `tools/apply_names.py` | the XDK library functions and variables matched against the XDK's `.lib` files (`tools/match_libs.py` makes it); XbSymbolDatabase's names win where both name an address |
| `classes.json` | `tools/apply_names.py` | the engine's classes, their registering functions and callbacks, from the descriptors the game registers (`tools/find_classes.py` makes it) |
| `xdk_symbols.json` | `tools/apply_names.py` | the XDK library symbols XbSymbolDatabase finds (`tools/xdk_symbols.py` makes it) |
| `names.json` | `tools/apply_names.py` | function names given by hand |
| `seed_functions.json` | `tools.disasm --seed-functions` | function starts the disassembler missed; each entry says why in its `why` field |
| `coalesce.json` | `tools.recomp --coalesce-functions` | functions the disassembler split at a false entry, made whole; the loader takes no extra keys, so the reasons are below |

## `lib_matches.json`

Each function of `d3d8.lib`, `dsound.lib`, `xapilib.lib`, `libcmt.lib` and `libcpmt.lib` (XDK 5849) is a
pattern: its bytes, with what its relocations cover as wildcards. A pattern found at exactly one place
names it (`"how": "bytes"`); each match's relocations then name what they point at, the variables it
reads and the functions it calls (`"how": "reloc"`). Measured on 25-10-2026: 607 functions by bytes,
332 functions and variables by relocations; of the 123 addresses XbSymbolDatabase also names, all 123
agree.

- What changed between 4721 and 5849 does not match; 18 patterns found at several places are left out.
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
(`vcObjectRelease`; every one frees), +0x3C `Cb3C` (`vcObjectCall3C`, walks the children ORing flags;
what for is not known yet), +0x40 `Load` (`vcObjectLoad`, by file version), +0x44 `Save`, +0x48 `Cb48`,
+0x4C `Copy` (`vcObjectClone`), +0x50 `Cb50`, +0x54 `GetSize`. Measured on 25-10-2026: 30 classes (29
`vc*` of the engine, `gcComponent` of the game), 175 callbacks named; the 5 several classes share
(the defaults below) are left unnamed.

## `names.json`

- `0x00157AC0` `Direct3DCreate8`: `mov eax, 1; ret 4`, called once before `Direct3D_CreateDevice`.
- The object system (`classes.json` above): `0x00110370` `vcRegisterClass` (copies the descriptor to the
  class table at `0x0023B4E8`, 0x70 bytes a class, and points `0x002BF1E0[type]` at it; allocates the
  instance table, 0x4C bytes an instance), `0x001103C0` `vcObjectCreate`, `0x00110510`
  `vcObjectRelease`, `0x00110780` `vcObjectClone`, `0x00110810` `vcObjectCall3C`, `0x00110E90`
  `vcObjectLoad`: the one function that calls each slot.
- The default callbacks: `0x00147480` `vcDefault_ReturnZero` (`xor eax, eax; ret`), `0x00147490`
  `vcDefault_ReturnOne`, `0x0013FDD0` `vcDefault_ReturnArg3` (the default +0x3C).

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
