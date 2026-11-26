"""The names the levels' designers gave their objects, by type: what a type without a name is.

    py -3 tools/level_names.py

A level (Media/vcResources/xbox/gcLevel/*.lvl) keeps each node it places as a record with 0xFFFFFFFF,
its family (11, Node), its type and, 0x4C bytes after the 0xFFFFFFFF, the name it has in the editor
("Helper - exhaust effect right", "vf1j parent folder"). Two tables from the 59 levels:

- the nodes, a type: how many the levels have, in how many levels, and their most frequent names with
  their numbers taken out;
- what the stand-ins stand for: a Node 1 ("Player Stand-in Entity") is where the level puts an object
  of another family, and its record holds that family and type 34 and 35 words after its name's 64
  bytes; its name is the editor's for that type ("Entity.BattlePod", "Item.PunyHuman",
  "Structure.ObjectSwap").

A type with a `type` line in symbols.txt goes with its name, which is the check: the names found agree
with every type already named (entity.battlepod is PodStandardWarrior, entity.laserturret
ZenCruiserTurret). Only the nodes' records are read this way: the same bytes elsewhere are other data.
"""
import collections, glob, json, os, re, struct

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVELS = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "Media", "vcResources", "xbox", "gcLevel", "*.lvl")
NODE = re.compile(rb"\xff\xff\xff\xff\x0b\x00\x00\x00(.)\x00\x00\x00", re.S)


def nodes(data):
    """(type, name, the 40 words after the name's 64 bytes) of each node record of a level's bytes."""
    for m in NODE.finditer(data):
        at = m.start() + 0x4C
        name = data[at:data.find(b"\0", at, at + 80)]
        if 2 < len(name) < 64 and all(32 <= c < 127 for c in name) and at + 0x40 + 160 <= len(data):
            yield m.group(1)[0], name.decode("latin1"), struct.unpack_from("<40I", data, at + 0x40)


def stem(name):
    """A name without what tells one object from another: its numbers, what follows a dash."""
    name = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", name.lower())
    return re.sub(r"\s+", " ", name.split(" - ")[0] if " - " in name else name).strip(" #_-") or "#"


def main():
    families = json.load(open(os.path.join(REPO, "symbols", "registries.json")))["families"]
    family_name = {f["number"]: f["name"] for f in families}
    typed = {}
    for t in open(os.path.join(REPO, "symbols", "symbols.txt"), encoding="utf-8"):
        p = t.split()
        if len(p) >= 4 and p[0] == "type" and p[2].isdigit():
            typed[(p[1], int(p[2]))] = p[3]
    names, levels = collections.defaultdict(collections.Counter), collections.defaultdict(set)
    stands = collections.defaultdict(collections.Counter)
    for path in sorted(glob.glob(LEVELS)):
        for num, name, words in nodes(open(path, "rb").read()):
            names[("Node", num)][stem(name)] += 1
            levels[("Node", num)].add(path)
            if num == 1 and words[34] in family_name and words[34] != 11 and words[35] < 256:
                stands[(family_name[words[34]], words[35])][stem(name)] += 1
    for title, table in (("the nodes", names), ("what the stand-ins stand for", stands)):
        print("== " + title)
        for key in sorted(table):
            most = ", ".join("%s %d" % (n, c) for n, c in table[key].most_common(6))
            where = " in %d levels" % len(levels[key]) if key in levels else ""
            print("%s %d %s: %d%s: %s" % (key[0], key[1], typed.get(key, "-"), sum(table[key].values()), where, most))


if __name__ == "__main__":
    main()
