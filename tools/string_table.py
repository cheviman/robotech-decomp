# license:BSD-3-Clause
# copyright-holders:Sebastian Toyos
"""
Name:        string_table.py
Description: reads the game's string table, the texts the code asks for by their number
Version:     0.1.0
Created:     13-11-2026
Modified:    13-11-2026
Author:      Sebastian Toyos

The game's texts are not in the XBE: the code hands a number to vcStringManagerGetText, with the
vcStringManager object "stringtable" (StringTable), which main.pak holds. In the pak, after the object's
class (0x12), its name and a GUID: how many texts there are and the size of their block, twice, then a
record a text (its name, IDS_..., in 16 bytes, and where its text starts, from the end of the records),
then the texts, each ending in a 0. A record's place is its text's number (0x796 is IDS_CHEAT_P9).

    py -3 tools/string_table.py              writes analysis/string_table.txt: each text's number, name, text
    py -3 tools/string_table.py 796 7B6      prints those texts (their numbers in hexadecimal)

The texts are the game's: they go to analysis/, never into the repository.
"""
import os
import re
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAK = os.path.join(REPO, "game", "Media", "vcResources", "xbox", "vcPak", "main.pak")
OUT = os.path.join(REPO, "analysis", "string_table.txt")
NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{0,15}\x00")


def read(path=PAK):
    """The texts in their order: (name, text), text None for a record without one."""
    data = open(path, "rb").read()
    at = data.find(b"\x0c\x00stringtable\x00")
    if at < 0:
        sys.exit("no object named stringtable in %s" % path)
    # the count and the size of the texts' block, twice, somewhere after the name and its GUID
    for count_at in range(at + 14, at + 14 + 64):
        count, size, count_again, _ = struct.unpack_from("<4I", data, count_at)
        records = count_at + 16
        if 0 < count < 0x10000 and count == count_again and NAME.match(data[records:records + 16]):
            break
    else:
        sys.exit("the string table's records were not found after its name")
    texts = records + count * 20
    out = []
    for n in range(count):
        name = data[records + n * 20:records + n * 20 + 16].split(b"\0")[0].decode("ascii")
        offset = struct.unpack_from("<i", data, records + n * 20 + 16)[0]
        if offset < 0 or offset >= size:
            out.append((name, None))
            continue
        end = data.index(b"\0", texts + offset)
        out.append((name, data[texts + offset:end].decode("latin-1")))
    return out


def main():
    table = read()
    wanted = [int(a, 16) for a in sys.argv[1:]]
    if wanted:
        for number in wanted:
            name, text = table[number] if number < len(table) else ("(none)", None)
            print("0x%03X  %-16s %s" % (number, name, text if text is not None else "(no text)"))
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# The game's string table (tools/string_table.py from main.pak): number, name, text\n")
        for number, (name, text) in enumerate(table):
            f.write("0x%03X  %-16s %s\n" % (number, name, text if text is not None else "(no text)"))
    print("%d texts to %s" % (len(table), OUT))


if __name__ == "__main__":
    main()
