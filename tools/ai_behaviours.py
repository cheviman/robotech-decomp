"""The behaviours of gcAIData/aidata.spt, the file's third part, as GcAIDataLoadGroupRecords reads it.

    py -3 tools/ai_behaviours.py [table|themes]

After the rules (tools/ai_script.py) and the states (0x12C to 0x12D), the file lists the behaviours
(a theme, below, gives an AI one by its number), between 0x191 and 0x192: each 0x193, 0x195 and a word (the record's +0,
the state it starts in; the file writes 0x195 twice, the second where 0x196 and the record's +0xC would
be), 0x197 and its name in 100 bytes, then for each state it has 0x199 and the state's number in the
behaviour (1 to 13, the slot at +0x78 + 4 * number) and 0x198 and the state's name in 50 bytes, which
the reader looks up among the states read before; 0x194 ends it. The slot's number is the one the
actions hand to the state setter (AIActionGoIdle hands 1 and every behaviour's slot 1 is its _Idle), so
the numbers no action's name gives get their names here. Prints each behaviour with its slots, and with
`table` one line per state number with the names the behaviours give it.

`themes` prints the file's fourth part, which AIDataReadEntries reads up to 0x63DD: the AI themes (the
Action type 19 is "AI Set Theme"; a level's entity holds its theme's number, not a name). Each is its
number, a version (2), its name in 256 bytes, a word that says the rest follows, 15 words and, from
version 2, one more; FileRecordLoad puts them in an AI object of 0x300 bytes at the theme's +0x104,
the offsets printed in the heading: the first is the behaviour's number among the ones above.
"""
import collections, os, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "Media", "vcResources", "xbox", "gcAIData", "aidata.spt")


def behaviours(d):
    """[(name, [words of 0x195], [(number, state name)])] of the file's bytes."""
    u = lambda o: struct.unpack_from("<I", d, o)[0]
    text = lambda o, n: d[o:o + n].split(b"\0")[0].decode("latin1")
    p = d.find(struct.pack("<II", 0x12D, 0x191))
    if p < 0:
        raise SystemExit("no behaviours: 0x12D, 0x191 not found")
    p += 8
    out, cur, number = [], None, -1
    while p + 4 <= len(d):
        tag = u(p)
        p += 4
        if tag == 0x192:
            break
        if tag == 0x193:
            cur, number = ["", [], []], -1
        elif tag in (0x195, 0x196):
            cur[1].append((tag, u(p)))
            p += 4
        elif tag == 0x197:
            cur[0] = text(p, 100)
            p += 100
        elif tag == 0x199:
            number = u(p)
            p += 4
        elif tag == 0x198:
            cur[2].append((number, text(p, 50)))
            p += 50
        elif tag == 0x194:
            out.append(tuple(cur))
        else:
            raise SystemExit("tag %X at %X: not one the reader knows" % (tag, p - 4))
    return out


# where FileRecordLoad puts each of a theme's words in the AI object; "f8" is bit 3 of its +0
THEME_FIELDS = ("3C", "38", "34", "2C", "24", "30", "40", "A4", "2AC", "2B0", "298", "29C", "2B4", "28", "f8", "2A0")


def themes(d):
    """[(number, version, name, [words])] of the file's fourth part."""
    u = lambda o: struct.unpack_from("<I", d, o)[0]
    # the behaviours end at the 0x192 that is a tag: walk them as the reader does
    q = d.find(struct.pack("<II", 0x12D, 0x191)) + 8
    while u(q) != 0x192:
        tag = u(q)
        q += 4 + {0x195: 4, 0x196: 4, 0x199: 4, 0x197: 100, 0x198: 50}.get(tag, 0)
    p, out = q + 4, []
    while p + 4 <= len(d) and u(p) != 0x63DD:
        number, version = u(p), u(p + 4)
        name = d[p + 8:p + 264].split(b"\0")[0].decode("latin1")
        p += 264
        words = []
        if u(p):
            n = 15 + (version > 1)
            words = [u(p + 4 + 4 * i) for i in range(n)]
            p += 4 * n
        p += 4
        out.append((number, version, name, words))
    return out


def main():
    d = open(DATA, "rb").read()
    if len(sys.argv) > 1 and sys.argv[1] == "themes":
        bs = behaviours(d)
        print("%-30s %s" % ("theme", " ".join("%5s" % f for f in THEME_FIELDS)))
        for number, version, name, words in themes(d):
            cells = []
            for f, w in zip(THEME_FIELDS, words):
                cells.append("%5g" % struct.unpack("<f", struct.pack("<I", w))[0] if f == "A4" else
                             "%5d" % (w - (1 << 32) if w >> 31 else w))
            b = bs[words[0]][0] if words and words[0] < len(bs) else "-"
            print("%2d %-27s %s  %s" % (number, name, " ".join(cells), b))
        return
    bs = behaviours(d)
    if len(sys.argv) > 1 and sys.argv[1] == "table":
        by = collections.defaultdict(list)
        for name, _, slots in bs:
            for number, state in slots:
                by[number].append(state)
        for number in sorted(by):
            print("%2d %s" % (number, ", ".join(sorted(set(by[number])))))
        return
    for i, (name, words, slots) in enumerate(bs):
        print("%2d %-22s %s  %s" % (i, name, " ".join("%X=%X" % w for w in words),
                                    ", ".join("%d %s" % s for s in slots)))


if __name__ == "__main__":
    main()
