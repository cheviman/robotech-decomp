"""The AI's script, gcAIData/aidata.spt, as the game reads it: its rules by name with their functions.

    py -3 tools/ai_script.py [rules]

GcAIDataReadTypeTable reads the file as cells of 32 bits behind tags. A rule: 0xC8, its action's number
(the function is the table's at 0x1B1BB8 + 4 * number, 0 to 0x2F; an empty entry is an action with no
function of its own), three words, its name in 50 bytes and a word; then its conditions, each 0xD0, a
word, the value asked for (over 0 is true), a word, the condition's number (the table's at 0x1B1A48 + 4 *
number, 0 to 0x24) and 0xD5; 0xCF ends it. After the rules (0xFDE8), GcAIDataReadRecords' part: a
behaviour's states, each 0x12E, 0x132 and its number among all the states, 0x131 and its name, then 0x130
and a rule's name for each rule it runs. Prints, for each action and each condition, the function the
table gives it and the rules that use it, which say what it is for, and the states by their number; with
`rules`, every rule as read.
"""
import collections, os, re, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "Media", "vcResources", "xbox", "gcAIData", "aidata.spt")
XBE = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "default.xbe")
ACTIONS, CONDITIONS = 0x1B1BB8, 0x1B1A48


def rules(d):
    """[(action, words, name, [(condition, value)])] of the file's bytes."""
    u = lambda o: struct.unpack_from("<I", d, o)[0]
    out = []
    for m in re.finditer(rb"\xc8\x00\x00\x00", d):
        o = m.start()
        if o + 74 > len(d) or u(o + 4) >= 0x30:
            continue
        name = d[o + 20:o + 70].split(b"\0")[0]
        if len(name) < 3 or not all(32 <= c < 127 for c in name):
            continue
        conds, p = [], o + 74
        while p + 24 <= len(d) and u(p) == 0xD0 and u(p + 20) == 0xD5:
            conds.append((u(p + 16), u(p + 8)))
            p += 24
        out.append((u(o + 4), (u(o + 8), u(o + 12), u(o + 16), u(o + 70)), name.decode("latin1"), conds))
    return out


def main():
    d = open(DATA, "rb").read()
    x = open(XBE, "rb").read()
    base = struct.unpack_from("<I", x, 0x104)[0]
    count, headers = struct.unpack_from("<II", x, 0x11C)
    secs = [struct.unpack_from("<IIIII", x, headers - base + i * 56)[1:] for i in range(count)]

    def word(va):
        for v, _, raw, size in secs:
            if v <= va < v + size:
                return struct.unpack_from("<I", x, raw + va - v)[0]

    name_of = {}
    for t in open(os.path.join(REPO, "symbols", "symbols.txt"), encoding="utf-8"):
        p = t.split()
        if len(p) >= 3 and p[1] == "func" and re.match(r"^[0-9A-F]{8}$", p[0]):
            name_of[int(p[0], 16)] = p[2]

    def function(table, number):
        a = word(table + 4 * number)
        return "none" if not a else "%08X %s" % (a, name_of.get(a, "-"))

    rs = rules(d)
    if len(sys.argv) > 1 and sys.argv[1] == "rules":
        for action, words, name, conds in rs:
            print("%-42s action %02X %s  %s" % (name, action, " ".join("%X" % w for w in words),
                                               " ".join("%02X=%d" % (c, v > 0) for c, v in conds)))
        return
    acts, conds = collections.defaultdict(list), collections.defaultdict(list)
    for action, words, name, cs in rs:
        acts[action].append("%s(%X)" % (name, words[0]) if words[0] else name)
        for c, v in cs:
            conds[c].append("%s=%d" % (name, v > 0))
    print("== %d rules; the actions" % len(rs))
    for k in sorted(acts):
        print("%02X %s: %s" % (k, function(ACTIONS, k), ", ".join(sorted(set(acts[k]))[:12])))
    print("== the conditions")
    for k in sorted(conds):
        print("%02X %s: %s" % (k, function(CONDITIONS, k), ", ".join(sorted(set(conds[k]))[:12])))
    print("== the behaviours' states")
    for m in re.finditer(rb"\x32\x01\x00\x00(.)\x00\x00\x00\x31\x01\x00\x00", d, re.S):
        name = d[m.end():d.find(b"\0", m.end())].decode("latin1")
        ran = re.findall(rb"\x30\x01\x00\x00([\x20-\x7e]+)\0", d[m.end():d.find(b"\x2f\x01\x00\x00", m.end())])
        print("%2d %s: %s" % (m.group(1)[0], name, ", ".join(r.decode("latin1") for r in ran)))


if __name__ == "__main__":
    main()
