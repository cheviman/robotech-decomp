# symbols/

What this project knows about the XBE that the disassembler and the recompiler cannot find out alone.
Every entry was measured; this file says where each came from.

| File | Read by | What |
|---|---|---|
| `xdk_symbols.json` | `tools/apply_names.py` | the XDK library symbols XbSymbolDatabase finds (`tools/xdk_symbols.py` makes it) |
| `names.json` | `tools/apply_names.py` | function names given by hand |
| `seed_functions.json` | `tools.disasm --seed-functions` | function starts the disassembler missed; each entry says why in its `why` field |
| `coalesce.json` | `tools.recomp --coalesce-functions` | functions the disassembler split at a false entry, made whole; the loader takes no extra keys, so the reasons are below |

## `names.json`

- `0x00157AC0` `Direct3DCreate8`: `mov eax, 1; ret 4`, called once before `Direct3D_CreateDevice`.

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
