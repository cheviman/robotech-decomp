# xemu as the reference

`xemu-reference.patch` makes [xemu](https://github.com/xemu-project/xemu), the original Xbox emulator,
into the reference the port's scenarios are set against, as MAME is for an arcade game's port: the
original game runs a scenario's pad script and its frames are dumped with the numbers the port's have.
`tools/xemu_reference.py` runs it.

The patch is against xemu's commit `dc10b4cea96e403d30c17ed53551fdaf023bc17f` (27-10-2026). It is
licensed as xemu is, GPL-2.0-or-later; xemu itself is not part of this repository.

## What it changes

Everything happens only when `XEMU_REFERENCE_DIR` is set; otherwise xemu runs as it always does.

- **Frames.** At each flip of the GPU (`NV097_FLIP_STALL`) the colour surface is read back and written as
  `fNNNNN.bmp` every `XEMU_REFERENCE_DUMP` frames (1280 x 480, the game's own buffer; the console halves it
  as it shows it, and `xemu_reference.py` does too). Frames count from the game's first present: the
  console's start flips some 30 times before it, which the port does not have. The run ends at
  `XEMU_REFERENCE_EXIT`.
- **The game's clock and pad, answered as the port answers them.** The port's scenarios run on a clock
  tied to the frames (`src/clock_bridge.c`) and answer the pad at `XInputGetState`
  (`src/input_bridge.c`); on the console the clock goes on while the game loads, some six seconds before
  the menu, and the pad comes over USB a few milliseconds late. So `XEMU_REFERENCE_HOOKS` names the same
  functions (`swap`, `counter`, `ticks`, `date`, `pad`, by their addresses in symbols.txt) and xemu
  answers them as the port does: the translator calls a helper before the function's first instruction,
  which counts a present or answers the call and returns from it. The pad script and everything the game
  times land on the same frames in both.
- **The pad over USB.** Without a `pad` hook the script goes through the emulated controller; xemu's
  controller test mode, on while a notification has the focus, is kept off so the game gets it.
- **Windows builds** without Developer Mode: the build tree's `qemu-bundle` is copied where symbolic links
  cannot be made (`scripts/symlink-install-tree.py`).

Still the console's, not the port's: the date the kernel's `KeQuerySystemTime` gives XAPI's own calls (a
save's folder times; the port points that thunk at its date too), and everything the GPU draws.

## Building it on Windows

In MSYS2's MINGW64 shell:

```bash
pacman -S --noconfirm --needed base-devel git bison flex diffutils make mingw-w64-x86_64-toolchain mingw-w64-x86_64-meson mingw-w64-x86_64-ninja mingw-w64-x86_64-pkgconf mingw-w64-x86_64-python mingw-w64-x86_64-python-yaml mingw-w64-x86_64-glib2 mingw-w64-x86_64-pixman mingw-w64-x86_64-SDL2 mingw-w64-x86_64-sdl3 mingw-w64-x86_64-cmake mingw-w64-x86_64-zstd mingw-w64-x86_64-libepoxy mingw-w64-x86_64-libsamplerate mingw-w64-x86_64-openssl mingw-w64-x86_64-curl mingw-w64-x86_64-glslang mingw-w64-x86_64-spirv-tools mingw-w64-x86_64-vulkan-headers mingw-w64-x86_64-vulkan-loader mingw-w64-x86_64-tomlplusplus
```

```bash
git clone https://github.com/xemu-project/xemu.git ../xemu
```

```bash
cd ../xemu && git checkout dc10b4cea96e403d30c17ed53551fdaf023bc17f && git apply ../robotech-decomp/tools/reference/xemu/xemu-reference.patch
```

```bash
./build.sh
```

`xemu_reference.py` looks for it in `../xemu/build/qemu-system-i386.exe` (`XEMU_EXE` to change it) and
for MINGW64's libraries in `msys64/mingw64/bin` on any drive (`XEMU_LIBRARIES`).

## Running it

What xemu needs that is the console's is your own: its MCPX boot ROM, a BIOS and a hard disk image, in
`../xemu-files` (`XEMU_FILES`): `mcpx/mcpx_1.0.bin`, `bios/*.bin`, `hdd/xbox_hdd.qcow2`. The hard disk is
never written (QEMU's `-snapshot`). The game is a disc image `tools/make_xiso.py` makes from `game/`.

```bash
py -3 tools/xemu_reference.py
```

The frames land in `analysis/reference/NAME/`, with `reference.log` (the hooks, the presses, the frame
each dump is at), and each is set against the port's frame of the same number: the mean difference of
their channels, 0 to 255; a scenario's `original` line is the most a frame may be, and a frame further
fails the run. On 27-10-2026 the menu, the first mission and the save stay at 1.23 or under for the
whole run (1.5 allowed): the same screens, the same flight and the same shots in the first mission, the
same save; what is left is the edges, xemu's 1280 halved to the port's 640. The training stays at 3.2
(6.0 allowed): its dialogue goes on as each voice line ends, and xemu's sound keeps the emulator's clock,
not the frames, so a portrait or a line shows a little earlier or later from run to run. On 28-10-2026
a mission of each chapter joined them, reached with the code that unlocks every mission (a scenario's
`code` line): Force of Arms, Ambush Hills, Rebel Revenge, Goodbye Graystone and Besieged, within 1.5
but for Goodbye Graystone's town, whose many edges keep it near that (2.0 allowed).
