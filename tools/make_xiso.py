"""
Name:        make_xiso.py
Description: packs a folder of the game's files into an Xbox disc image (XDVDFS), for xemu
Version:     0.1.0
Created:     27-10-2026
Modified:    27-10-2026
Author:      Sebastian Toyos

xemu runs a game from a disc image; the game here is a folder (the one taken from Xbox 360
Originals). This writes the bare game partition XDVDFS keeps, as xboxrecomp's reader
(tools/xiso/xdvdfs.py) reads it:

  - 2048-byte sectors; the volume descriptor at sector 32: "MICROSOFT*XBOX*MEDIA", the root
    directory's sector and size, a time stamp, and the magic again at its end (0x7EC);
  - each directory a table of entries (left and right subtree offsets in 4-byte words from the
    table's start, the first sector, the size, the attributes, the name's length and the name,
    4-byte aligned, 0xFF filling), the entries a binary search tree by name compared in capitals,
    none across a sector's end;
  - each file from a sector of its own.

    py -3 tools/make_xiso.py "RB-XBE/Robotech Battlecry" analysis/robotech.iso

The image is the game's: it stays out of the repository, as the game's folder does.
"""
import os
import struct
import sys

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
DIRECTORY, NORMAL = 0x10, 0x80
FIRST_FREE = 33


def sectors(size):
    return (size + SECTOR - 1) // SECTOR


class Node:
    def __init__(self, path, name):
        self.path, self.name = path, name
        self.is_dir = os.path.isdir(path)
        self.children = sorted((Node(os.path.join(path, child), child) for child in os.listdir(path)),
                               key=lambda node: node.name.upper()) if self.is_dir else []
        self.size = 0 if self.is_dir else os.path.getsize(path)
        self.sector = 0
        self.table = b""


def table_of(directory):
    """The directory's table, the children's sectors filled in: a balanced tree, laid out in preorder."""
    out = bytearray()
    places = {}

    def entry_size(node):
        return (0x0E + len(node.name.encode("ascii")) + 3) & ~3

    def place(children):
        """Lays out the subtree of sorted 'children'; its offset in words, or 0 for none."""
        if not children:
            return None
        middle = len(children) // 2
        node = children[middle]
        size = entry_size(node)
        if len(out) % SECTOR + size > SECTOR:
            out.extend(b"\xff" * (SECTOR - len(out) % SECTOR))
        at = len(out)
        out.extend(b"\x00" * size)
        places[id(node)] = at
        left = place(children[:middle])
        right = place(children[middle + 1:])
        name = node.name.encode("ascii")
        entry = struct.pack("<HHIIBB", (left or 0) // 4, (right or 0) // 4, node.sector,
                            node.table_size if node.is_dir else node.size,
                            DIRECTORY if node.is_dir else NORMAL, len(name)) + name
        out[at:at + len(entry)] = entry
        out[at + len(entry):at + size] = b"\xff" * (size - len(entry))
        return at
    place(directory.children)
    if len(out) % SECTOR:
        out.extend(b"\xff" * (SECTOR - len(out) % SECTOR))
    return bytes(out)


def table_length(directory):
    """How long the directory's table is (the sectors do not change its length)."""
    directory.sector = 0
    for child in directory.children:
        child.sector, child.table_size = 0, 0
    return len(table_of(directory))


def main():
    if len(sys.argv) != 3:
        sys.exit("Uso: make_xiso.py CARPETA IMAGEN.iso")
    root = Node(sys.argv[1], "")
    # every directory's table, then every file, each from a sector of its own
    directories, files = [], []

    def walk(node):
        if node.is_dir:
            directories.append(node)
            for child in node.children:
                walk(child)
        else:
            files.append(node)
    walk(root)
    for directory in directories:
        directory.table_size = table_length(directory)
    next_free = FIRST_FREE
    for directory in directories:
        directory.sector = next_free
        next_free += sectors(directory.table_size)
    for node in files:
        node.sector = next_free
        next_free += max(sectors(node.size), 1)
    with open(sys.argv[2], "wb") as out:
        descriptor = bytearray(SECTOR)
        descriptor[0:20] = MAGIC
        struct.pack_into("<II", descriptor, 0x14, root.sector, root.table_size)
        descriptor[0x7EC:0x7EC + 20] = MAGIC
        out.seek(32 * SECTOR)
        out.write(descriptor)
        for directory in directories:
            table = table_of(directory)
            assert len(table) == directory.table_size
            out.seek(directory.sector * SECTOR)
            out.write(table)
        for node in files:
            out.seek(node.sector * SECTOR)
            with open(node.path, "rb") as source:
                while True:
                    chunk = source.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        out.seek(next_free * SECTOR - 1)
        out.write(b"\x00")
    print("%s: %d directories, %d files, %d sectors" % (sys.argv[2], len(directories), len(files), next_free))


if __name__ == "__main__":
    main()
