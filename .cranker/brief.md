Project: Robotech: Battlecry (Xbox, 2002) decompiled to C. The C in src/decompiled/ is written by a tool
(tools/decompile.py) from the game's x86; nobody edits it by hand. Names, types and descriptions live in
symbols/symbols.txt and reach the C from there.

- MEM32(addr), MEM16, MEM8, MEMF read the Xbox's memory at a raw address; `ignored` and register-named
  locals (eax, ecx, esi...) are the decompiler's. sub_XXXXXXXX is a function nobody named yet.
- A name is real -- it says what the thing is -- or there is none. Never a number, an offset, an address or a
  generic word (Helper, Func, Unknown, Process, Handle alone). When the code does not say what it is, say so.
- Names are CamelCase, subject first: EntityTakeDamage, LevelIsOpen, CheatsClear, PaintDesignIsOpen,
  vcStringManagerGetText. A slot of a game object type is Type_Slot (Player_Update).
- Descriptions are one sentence, in the game's terms, using the C's names of what the function calls.
  Say only what the code shows; a guess about the gameplay is marked as one ("probably").
