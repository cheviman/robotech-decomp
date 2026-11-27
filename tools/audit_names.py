"""The functions' names against the evidence: the names the code, the registries or the comments contradict.

    py -3.14 tools/audit_names.py                 every rule, a section each, each suspect with its evidence
    py -3.14 tools/audit_names.py RULE...         only those rules (1 to 9)
    py -3.14 tools/audit_names.py counts          how many names each rule flags
    py -3.14 tools/audit_names.py show NAME...    what the tool knows of a function: its callers with whose
                                                  they are, what it calls, the tables that hold it, its C
    py -3.14 tools/audit_names.py comments        the `comment` lines that name a function by a name it no
                                                  longer has, rewritten with today's names (to paste)

Reads symbols/symbols.txt (the names, their sections, the comments, the `type` lines), symbols/registries.json
(whose function each register and slot is) and src/decompiled/decompiled.c (the code). The decompiled C may be
older than symbols.txt (a round that names without building): build/symbols.before_types.txt, when it is
there, is the symbols.txt the C was written from, and every name of the C is taken to today's by its address.
The recompiled C (src/recomp/gen) gives the calls of the functions the decompiler does not write, and the XBE
the tables of functions in its data (a function nobody calls is reached through one).

A name is audited when a model or a reader gave it from the function's C (the sections "functions named from
their decompiled C"); the names given by hand and the generated ones are the evidence it is set against.
The rules:

  1  a type's own function (its register, or a slot only it has) under a name that is not the type's: of a
     type with a `type` line (symbols.py merge would name it, the hand line is in its way), or of a type
     without one (the name says a family or another type; only which slot it is can be said)
  2  a name with a type's or a family's word, reached only from types of another, or with no caller of its own
  3  names that differ only by a number or a filler word, and functions with the same body under names
     that do not agree
  4  comments that name a function by a name it no longer has, or that say another thing than the name
  5  names made of a banned word or of nothing but what the code moves, by how many functions call them
  6  "Family" in the name of a function that is not a family's
  7  a name whose verb the function's shape contradicts: a getter that hands nothing back, a predicate that
     writes, a name on a body that does nothing
  8  functions nobody calls, reached through a table of functions in the data: the table says what they are
  9  the engine's prefix written two ways (Vc and vc), and names that differ only in their case

Each suspect is a line `rule  ADDRESS  NAME  callers  evidence`; a name several rules flag is listed under
each. This lists; build/sessions/audit/proposal.txt is where each was settled (rename, unname or keep).
"""
import collections, json, os, re, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEPT = os.path.join(REPO, "symbols", "audit_kept.txt")
SYM = os.path.join(REPO, "symbols", "symbols.txt")
BEFORE = os.path.join(REPO, "build", "symbols.before_types.txt")
REGISTRIES = os.path.join(REPO, "symbols", "registries.json")
SRC = os.path.join(REPO, "src", "decompiled", "decompiled.c")
GEN = os.path.join(REPO, "src", "recomp", "gen")
XBE = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "default.xbe")

SLOTS = {"Register": "Register", "0x04": "Startup", "0x08": "Shutdown", "0x0C": "StateMachine", "0x10": "Load",
         "0x18": "Collect"}
SLOT_WORDS = {"Register": "its register (fills its GameObjectType and stores it in its family)",
              "Startup": "its first use (GameObjectTypeUse)", "Shutdown": "its last release (GameObjectTypeRelease)",
              "StateMachine": "its state machine (GameObjectDeliver)", "Load": "its load from a file (GameObjectLoad)",
              "Collect": "its collect for a save (GameObjectCollect)"}
ADDRESS = re.compile(r"^[0-9A-F]{8}$")
WORD = re.compile(r"\b([A-Za-z_]\w*)\b")
HEX = re.compile(r"\b0x([0-9A-Fa-f]{4,8})u\b")


def tokens(name):
    """A name's words: GameObjectTypeUse -> Game Object Type Use; VF1AXFighterInit -> VF1AX Fighter Init."""
    out = []
    for part in name.split("_"):
        out += re.findall(r"[A-Z]+[0-9]+[A-Z]*(?![a-z])|[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+", part)
    return out


class Symbols:
    """symbols.txt as the audit needs it."""

    def __init__(self, path):
        self.func, self.section, self.comment, self.types, self.other = {}, {}, {}, {}, set()
        self.comment_section = {}
        section = "head"
        for t in open(path, encoding="utf-8").read().split("\n"):
            if t.startswith("# ========"):
                section = t.strip("# =").strip()
                continue
            p = t.split()
            if len(p) >= 3 and ADDRESS.match(p[0]):
                if p[1] == "func":
                    self.func.setdefault(int(p[0], 16), p[2])
                    self.section.setdefault(int(p[0], 16), section)
                else:
                    self.other.add(p[2])
            elif len(p) >= 2 and p[0] == "comment":
                self.comment[p[1]] = t.split(None, 2)[2] if len(p) > 2 else ""
                self.comment_section[p[1]] = section
            elif len(p) >= 4 and p[0] == "type" and p[2].isdigit():
                self.types[(p[1], int(p[2]))] = p[3]
            elif len(p) >= 2 and p[0] == "struct":
                self.other.add(p[1])
            elif len(p) >= 4 and p[0] == "field":
                self.other.add(p[3])
                self.other.add("%s_%s" % (p[1], p[3]))
        self.address = {n: a for a, n in self.func.items()}

    def source(self, address):
        """Who gave a function its name: model (a wave's draft and review), reader (the fifth wave), hand,
        generated, or none."""
        s = self.section.get(address)
        if s is None:
            return "none"
        if s.startswith("functions named from their decompiled C"):
            return "reader" if "not reviewed" in s else "model"
        return "generated" if "(generated by" in s else "hand"

    def wave(self, address):
        m = re.search(r"\((w\d)", self.section.get(address, ""))
        return m.group(1) if m else self.source(address)


class Code:
    """The decompiled C with every name taken to today's: the functions, who calls whom, whose address
    is stored where, and the calls of the recompiled C."""

    def __init__(self, sym):
        before = Symbols(BEFORE) if os.path.exists(BEFORE) else sym
        old_address = dict(before.address)
        self.stale = {n: a for n, a in before.address.items() if sym.func.get(a) != n}   # old name: address
        lines = open(SRC, encoding="utf-8").read().split("\n")
        sig = re.compile(r"^([A-Za-z_][\w \*]*?)\b(\w+)\((.*)\)$")
        self.body, self.returns, self.params, self.entry_of = {}, {}, {}, {}
        named = {}                                   # the C's name: address
        i = 0
        while i < len(lines):
            m = sig.match(lines[i])
            if m and i + 1 < len(lines) and lines[i + 1] == "{":
                j = i + 2
                while lines[j] != "}":
                    j += 1
                name = m.group(2)
                a = old_address.get(name)
                if a is None and re.match(r"^sub_[0-9A-F]{8}$", name):
                    a = int(name[4:], 16)
                if a is not None:
                    named[name] = a
                    self.body[a] = lines[i + 2:j]
                    self.returns[a] = m.group(1).strip()
                    self.params[a] = [p.strip() for p in m.group(3).split(",") if p.strip() != "void"]
                i = j + 1
            else:
                i += 1
        self.c_name = {a: n for n, a in named.items()}
        self.calls, self.callers = collections.defaultdict(set), collections.defaultdict(set)
        self.refs, self.referrers = collections.defaultdict(set), collections.defaultdict(set)
        entries = set(sym.func) | set(self.body)
        for a, body in self.body.items():
            text = "\n".join(body)
            for w in set(WORD.findall(text)):
                if w.endswith("_entry"):
                    w = w[:-6]
                b = named.get(w, old_address.get(w))
                if b is not None and b != a:
                    self.calls[a].add(b)
                    self.callers[b].add(a)
            for x in set(HEX.findall(text)):
                b = int(x, 16)
                if b in entries and b != a and 0x11000 <= b < 0x1A0000:
                    self.refs[a].add(b)
                    self.referrers[b].add(a)
        # the recompiled C: the functions the decompiler does not write, by their calls' addresses
        self.recompiled = set()
        head, call = re.compile(r"^void (\w+)\(void\)$"), re.compile(r"RECOMP_ABI_CALL\(0x([0-9A-F]{8})u")
        if os.path.isdir(GEN):
            for folder, _, files in os.walk(GEN):
                for f in files:
                    if not f.endswith(".c") or os.path.basename(folder) == "xdk":
                        continue
                    a = None
                    for t in open(os.path.join(folder, f), encoding="utf-8", errors="replace"):
                        m = head.match(t)
                        if m:
                            n = m.group(1)
                            a = old_address.get(n, int(n[4:], 16) if re.match(r"^sub_[0-9A-F]{8}$", n) else None)
                            if a is not None and a in self.body:
                                a = None            # the decompiler writes it: its calls are read above
                            elif a is not None:
                                self.recompiled.add(a)
                            continue
                        if a is None:
                            continue
                        for x in call.findall(t):
                            b = int(x, 16)
                            if b != a:
                                self.calls[a].add(b)
                                self.callers[b].add(a)

    def text(self, address):
        return "\n".join(self.body.get(address, []))


def xbe_tables(entries):
    """{function address: [where in the XBE's data a word holds it]}: the tables of functions."""
    out = collections.defaultdict(list)
    if not os.path.exists(XBE):
        return out, None, None
    d = open(XBE, "rb").read()
    base = struct.unpack_from("<I", d, 0x104)[0]
    count, headers = struct.unpack_from("<II", d, 0x11C)
    secs = [struct.unpack_from("<IIIII", d, headers - base + i * 56)[1:] for i in range(count)]
    for va, size, raw, raw_size in secs:
        if va < 0x1A0000:               # the code: its constants are read from the C
            continue
        for o in range(0, min(size, raw_size) - 3, 4):
            w = struct.unpack_from("<I", d, raw + o)[0]
            if w in entries:
                out[w].append(va + o)

    def word(va):
        for v, size, raw, raw_size in secs:
            if v <= va < v + min(size, raw_size):
                return struct.unpack_from("<I", d, raw + va - v)[0]

    def string(va):
        for v, size, raw, raw_size in secs:
            if v <= va < v + min(size, raw_size):
                o = raw + va - v
                t = d[o:d.find(b"\0", o)]
                if 2 < len(t) < 70 and all(32 <= c < 127 for c in t):
                    return t.decode("latin1")
    return out, word, string


class Audit:
    def __init__(self):
        self.sym = sym = Symbols(SYM)
        self.code = code = Code(sym)
        self.families = json.load(open(REGISTRIES))["families"]
        self.owners = collections.defaultdict(list)          # address: [(family, type, slot)]
        self.family_functions = {}                           # address: (family, what)
        for f in self.families:
            for k in ("setup", "startup", "shutdown"):
                if f.get(k):
                    self.family_functions[int(f[k], 16)] = (f["name"], k)
            for t in f["types"]:
                self.owners[int(t["register"], 16)].append((f["name"], t["type"], "Register"))
                for off, va in t["slots"].items():
                    self.owners[int(va, 16)].append((f["name"], t["type"], SLOTS.get(off, off)))
        self.tables, self.word, self.string = xbe_tables(set(sym.func) | set(code.body))
        self.reach()

    # ── names ──
    def name(self, a):
        return self.sym.func.get(a) or "sub_%08X" % a

    def label(self, key):
        return self.sym.types.get(key) or "%s %d" % key

    def audited(self):
        """The functions whose names a model or a reader gave from the C."""
        return sorted(a for a in self.sym.func if self.sym.source(a) in ("model", "reader"))

    def users(self, a):
        """Who calls a function or stores its address."""
        return self.code.callers.get(a, set()) | self.code.referrers.get(a, set())

    # ── whose a function is ──
    def reach(self):
        """own[a]: the types whose functions alone lead to a (their own functions, and what only those
        call or store, however far down); None where some way in is no type's."""
        code = self.code
        down = collections.defaultdict(set)
        for a in set(code.calls) | set(code.refs):
            down[a] = code.calls.get(a, set()) | code.refs.get(a, set())
        every = set(code.body) | set(self.sym.func) | code.recompiled | set(self.owners)
        # the roots that are no type's: a function nobody calls or stores that is not a type's own
        free, queue = set(), []
        for a in every:
            if a not in self.owners and not self.users(a):
                free.add(a)
                queue.append(a)
        while queue:
            a = queue.pop()
            for b in down.get(a, ()):
                if b not in free and b not in self.owners:
                    free.add(b)
                    queue.append(b)
        self.free = free
        self.own = collections.defaultdict(set)
        for root, us in self.owners.items():
            keys = {(u[0], u[1]) for u in us}
            seen, queue = {root}, [root]
            while queue:
                a = queue.pop()
                self.own[a] |= keys
                for b in down.get(a, ()):
                    if b not in seen and b not in self.owners:
                        seen.add(b)
                        queue.append(b)

    def whose(self, a):
        """The types a function is reached from, when every way in is a type's; else an empty set."""
        if a in self.owners:
            return {(u[0], u[1]) for u in self.owners[a]}
        return set() if a in self.free else set(self.own.get(a, ()))

    def whose_text(self, a, most=4):
        keys = sorted(self.whose(a))
        if not keys:
            return ""
        fams = collections.Counter(k[0] for k in keys)
        if len(keys) > most:
            return "%d types (%s)" % (len(keys), ", ".join("%d %s" % (c, f) for f, c in fams.most_common()))
        return ", ".join(self.label(k) for k in keys)

    def callers_text(self, a, most=5):
        us = sorted(self.users(a), key=lambda b: (self.name(b).startswith("sub_"), self.name(b)))
        if not us:
            return "nobody"
        shown = []
        for b in us[:most]:
            w = self.whose_text(b, 2)
            shown.append(self.name(b) + (" [%s]" % w if w and w not in self.name(b) else ""))
        return ", ".join(shown) + (" and %d more" % (len(us) - most) if len(us) > most else "")

    # ── the words a name says a type or a family with ──
    @property
    def type_words(self):
        if not hasattr(self, "_type_words"):
            self._type_words = set()
            for n in self.sym.types.values():
                self._type_words |= {w.lower() for w in tokens(n)}
        return self._type_words

    def strong(self, name):
        """A name's words that stand for a type: a type's name's word or an alias, no common word."""
        return [w for w in (t.lower() for t in tokens(name))
                if (w in self.type_words or w in ALIASES) and w not in COMMON and w not in FAMILY_WORDS]

    def says(self, name):
        """The types and families a name's words stand for, as text."""
        said = ["%s (%s %d)" % (n, fam, num) for (fam, num), n in sorted(self.sym.types.items()) if n in name]
        said = [s for s in said if not any(s != o and s.split(" ")[0] in o.split(" ")[0] for o in said)]
        if "family" in [t.lower() for t in tokens(name)]:
            said.append("a family")
        return ", ".join(said or dict.fromkeys(self.strong(name)))

    def words_of(self, keys):
        """The words that stand for some types: their names' and their families', and the aliases'."""
        out = set()
        for fam, num in keys:
            n = self.sym.types.get((fam, num), "%s %d" % (fam, num))
            out |= {w.lower() for w in tokens(n)} | {w.lower() for w in tokens(fam)}
            out |= {w for w, test in ALIASES.items() if test(n, fam)}
        return out


FAMILY_WORDS = {"weapon": "Weapon", "effect": "Effect", "trigger": "Trigger", "steering": "Steering",
                "node": "Node", "element": "ScreenElement", "screen": "Screen", "item": "Item",
                "structure": "Structure", "component": "Component", "action": "Action", "entity": "Entity",
                "player": "Player"}
# words of the types' names that say nothing of a type on their own (a common word, a size, a colour)
COMMON = set("""object game set target state list text and ai message entry reset sound to transform clear
    motion apply level bounds mission collision spawn path point value in heavy damage box timer count model
    space x on complete group light music power random grid or disable pause visible fire load lock enabled
    enable stand time move select mode volume character turn hit friendly 1 objective activate particle setup
    re assign follow no has health key channel difficulty lite ii label loading save standard machine take
    gauge settings failed b hull disabled pulse val marker bar main confirm large small loop attack eye pack
    rifle compare orient visibility items doors choice med rep arm boolean g w 01 02 03 super impact held
    quota log freeze kill nav theme off button options dialog medium look auto post map pos immobile land queue
    animation scrolled switch control new flash around maintain dist boss military transport rick roy izzy
    swap paired tri barrel laser human training i folder helper link counters arrow ammo enemy prompt boundary
    story chapter video red blue big back leg spot dust rock foot fast glass strafe water sky camera ship male
    armor armour gun cannon mac bp controller splash versus select civilians cinema spline terrain
    recon scout sea cats building explosion smoke blast crate destroid fighter proximity type""".split())
# words that are no type's name and still say whose a function is: the types each stands for
ALIASES = {
    "veritech": lambda n, f: n.startswith("VF1") or n.startswith("GU11") or "Veritech" in n,
    "vf": lambda n, f: n.startswith("VF1"),
    "valkyrie": lambda n, f: n.startswith("VF1"),
    "vehicle": lambda n, f: n in ("MechHauler", "MilitaryTransport", "Centipede", "ZenRetrieval"),
    "hud": lambda n, f: f == "ScreenElement" or n == "HUDScreen",
    "menu": lambda n, f: f == "Screen" or n in ("MenuArrowElement", "MissionMenuElement", "TextLabelElement"),
    "fpa": lambda n, f: "FemalePowerArmor" in n or n.startswith("FPA") or n == "Entity 24",
    "female": lambda n, f: "FemalePowerArmor" in n or n.startswith("FPA") or n == "Entity 24",
    "mpa": lambda n, f: "MalePowerArmor" in n or "MPA" in n,
    "missile": lambda n, f: "Missile" in n,
    "trail": lambda n, f: "trail" in n.lower(),
    "muzzle": lambda n, f: "Muzzle" in n,
    "thruster": lambda n, f: "Thrust" in n,
    "chunk": lambda n, f: "Chunk" in n,
    "chunks": lambda n, f: "Chunk" in n,
    "pieces": lambda n, f: f == "ScreenElement",
    "gui": lambda n, f: f in ("Screen", "ScreenElement"),
    "zentraedi": lambda n, f: n.startswith("Zen") or n.startswith("Pod"),
}


def rule1(au):
    """A type's own function under a name that is not the type's."""
    sym, out = au.sym, []
    for a, us in sorted(au.owners.items()):
        src = sym.source(a)
        if src in ("generated", "none"):
            continue
        keys = sorted({(u[0], u[1]) for u in us})
        slots = sorted({u[2] for u in us})
        name = sym.func[a]
        if len(keys) == 1:
            if keys[0] in sym.types:
                if src == "hand":
                    continue        # one type's two slots, named by hand
                what = "typed: %s's %s; symbols.py merge would name it %s_%s, this line is in its way" % (
                    sym.types[keys[0]], "/".join(slots), sym.types[keys[0]], slots[0])
            else:
                said = au.says(name)
                what = "untyped: %s %d's %s%s" % (keys[0][0], keys[0][1], "/".join(slots),
                                                  "; the name says " + said if said else "")
        else:
            if src == "hand":
                continue            # shared callbacks named by hand, after the types that have them
            fams = collections.Counter(k[0] for k in keys)
            what = "shared: the %s of %d types (%s): %s" % (
                "/".join(slots), len(keys), ", ".join("%d %s" % (c, f) for f, c in fams.most_common()),
                ", ".join(au.label(k) for k in keys[:8]) + (" ..." if len(keys) > 8 else ""))
        out.append((a, what))
    return out


def rule2(au):
    """A name with a type's or a family's word, reached only from types of another."""
    sym, out = au.sym, []
    for a in au.audited():
        if a in au.owners:
            continue                # rule 1's
        name = sym.func[a]
        whose = au.whose(a)
        if not whose:
            continue
        have = au.words_of(whose)
        whose_names = [au.label(k) for k in whose]
        # a whole type's name in it: the longest one, and whether that type or a kin of it is among them
        said = max((n for n in sym.types.values() if n in name), key=len, default=None)
        rest = name.replace(said, "") if said else name
        if said and not any(n.startswith(said) or said.startswith(n) for n in whose_names):
            stem = re.sub(r"(Weapon|Effect|Screen|Element|Node|Trigger|Action|Steering|Pickup)$", "", said)
            if not any(stem and stem in n for n in whose_names):
                out.append((a, "says %s; reached only from %s (%s)" % (said, au.whose_text(a), au.callers_text(a, 3))))
                continue
        if said and any(n.startswith(said) or said.startswith(n) for n in whose_names):
            continue
        words = [w.lower() for w in tokens(rest)]
        strong = au.strong(rest)
        fams = {FAMILY_WORDS[w] for w in words if w in FAMILY_WORDS}
        if "ScreenElement" in fams:
            fams.discard("Screen")
        other = sorted(f for f in fams if f not in {k[0] for k in whose})
        if strong and not any(w in have for w in strong):
            out.append((a, "says %s; reached only from %s (%s)" % (
                ", ".join(dict.fromkeys(strong)), au.whose_text(a), au.callers_text(a, 3))))
        elif other and not strong:
            out.append((a, "says the %s family; reached only from %s (%s)" % (
                "/".join(other), au.whose_text(a), au.callers_text(a, 3))))
    return out


# numbers that are part of a word: a vector's or a matrix's size, a mech's model, an asset's number
NUMBER_OK = re.compile(r"(Vector[234]|Matrix[34](x[34])?|Multiply[34]x[34]|[234]D|D3D|VF1[A-Z]*|GU11|Log2|U?Int(8|16|32|64)"
                       r"|U(8|16|32)|Utf(8|16)|Float[234]|Explosion01|Chunk1|Turret1|12Hour|Vf1[a-z])")


def stray_numbers(name, types=()):
    """The numbers of a name that belong to no word: an offset, a state's or a slot's number."""
    for t in sorted(types, key=len, reverse=True):
        name = name.replace(t, "")
    return re.findall(r"[A-F]?[0-9]+[A-F0-9]*(?![a-z])", NUMBER_OK.sub("", name))
ORDINALS = {"First", "Second", "Third", "Fourth", "Fifth", "Sixth"}
FILLERS = {"Ex", "Internal", "Impl", "Inner", "Core", "Alt", "Other", "Variant", "Wrapper", "Thunk", "Stub", "Simple",
           "Basic", "Generic", "Common", "Raw", "Direct", "Unchecked", "Checked", "Real", "Actual", "Extended",
           "Custom", "Special", "A", "B"}
CLAUSES = {"And", "For", "With"}


def unnumbered(name):
    """A name without its numbers, ordinals and fillers: what two names that differ only by those share."""
    return "".join(w for w in tokens(name) if not w.isdigit() and w not in ORDINALS and w not in FILLERS)


def shape_groups(au, least=6):
    """The functions whose bodies are the same but for the addresses in them: [[address]]."""
    groups = collections.defaultdict(list)
    for a, body in au.code.body.items():
        text = [l.strip() for l in body if l.strip()]
        if len(text) >= least:
            groups[re.sub(r"\b0x[0-9A-Fa-f]{5,8}u\b", "K", "\n".join(text))].append(a)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def without_types(au, name):
    """A name without the words of the types' names: what two types' copies of one function should share."""
    said = max((n for n in au.sym.types.values() if n in name), key=len, default="")
    rest = name.replace(said, "") if said else name
    return "".join(w for w in tokens(rest) if w.lower() not in au.type_words or w.lower() in COMMON).replace("_", "")


def rule3(au):
    """Names that differ only by a number or a filler, and the same body under names that do not agree."""
    sym, out = au.sym, []
    audited = set(au.audited())
    stems = collections.defaultdict(list)
    for a, n in sym.func.items():
        stems[unnumbered(n)].append(n)
    every = set(sym.func.values())
    groups = {}
    for g in shape_groups(au):
        if len({without_types(au, au.name(a)) for a in g}) > 1:
            for a in g:
                groups[a] = g
    for a in sorted(audited):
        n, ws, why = sym.func[a], tokens(sym.func[a]), []
        odd = stray_numbers(n, [t for t in sym.types.values() if t in n])
        if odd:
            why.append("the number %s in it" % ", ".join(odd))
        twins = [m for m in stems[unnumbered(n)] if m != n]
        if twins and unnumbered(n) != n.replace("_", ""):
            why.append("differs from %s only by a number, an ordinal or a filler" % ", ".join(twins[:3]))
        for i, w in enumerate(ws):
            if w in CLAUSES and i > 1 and "".join(ws[:i]) in every and "".join(ws[:i]) != n:
                why.append("%s with a clause (%s)" % ("".join(ws[:i]), "".join(ws[i:])))
                break
        if a in groups:
            others = [au.name(b) for b in groups[a] if b != a]
            why.append("the same body, but for its addresses, as %s" % ", ".join(others[:4])
                       + (" and %d more" % (len(others) - 4) if len(others) > 4 else ""))
        if why:
            out.append((a, "; ".join(why)))
    return out


VERB_ECHO = {
    "Get": "get return fetch read cop writ hand look fill result output extract pack map convert",
    "Is": "return whether test check true nonzero compar",
    "Has": "return whether test check true nonzero compar",
    "Set": "set stor writ assign cop put install clear updat sav toggl appl build fill replac",
    "Create": "creat alloc build mak spawn clon construct new insert",
    "Destroy": "destroy releas free delet remov clear",
    "Release": "destroy releas free delet remov clear decrement drop",
    "Free": "destroy releas free delet remov clear",
    "Draw": "draw render submit display show blit push",
    "Send": "send deliver dispatch post hand forward call",
    "Fire": "fire shoot launch creat spawn",
    "Load": "load read open pars cop",
    "Register": "regist stor install fill add set",
}
READ_VERBS = {"Returns", "Gets", "Tests", "Compares", "Fetches"}
WRITE_VERBS = {"Sets", "Stores", "Writes", "Clears", "Zeroes", "Resets", "Destroys", "Releases", "Frees", "Creates"}


def rule4(au):
    """Comments that name a function by a name it no longer has, or that say another thing than the name."""
    sym, out = au.sym, []
    for a in au.audited():
        n = sym.func[a]
        text = sym.comment.get(n, "")
        if not text:
            continue
        why = []
        for old, new in stale_references(au, text):
            why.append("its comment says %s, now %s" % (old, new))
        ws, low, first = tokens(n), text.lower(), text.split(" ")[0]
        silent = [w for w in ws if w in VERB_ECHO and not any(x in low for x in VERB_ECHO[w].split())]
        if silent:
            why.append("its comment never says %s: \"%s\"" % ("/".join(silent), text[:110]))
        elif (first in READ_VERBS and {"Set", "Clear", "Reset", "Create", "Destroy"} & set(ws)
              and not {"Get", "Is", "Has", "Find"} & set(ws) and not re.search(r"\b(sets|stores|clears|creates|destroys)\b", low)):
            why.append("named as a change, its comment only reads: \"%s\"" % text[:110])
        if why:
            out.append((a, "; ".join(why)))
    return out


def stale_references(au, text):
    """[(the name a text gives a function, the one it has today)]: a name of the C's symbols.txt whose
    function has another today, or a sub_ of a function with a name."""
    sym, out = au.sym, []
    current = set(sym.func.values()) | sym.other
    for w in dict.fromkeys(WORD.findall(text)):
        if w in au.code.stale and w not in current:
            out.append((w, au.name(au.code.stale[w])))
        elif re.match(r"^sub_[0-9A-F]{8}$", w) and int(w[4:], 16) in sym.func:
            out.append((w, sym.func[int(w[4:], 16)]))
    return out


BANNED = {"Helper", "Process", "Do", "Func", "Unknown", "Misc", "Thing", "Stuff", "Generic", "Manager", "Internal",
          "Impl", "Something"}
# what follows Handle when it is the verb (HandleMessage) and not the game's word for an object's handle
HANDLED = {"Message", "Event", "Input", "Command", "Pad", "Create", "Face", "Lifecycle", "Cleanup", "Collision"}
GENERIC = set("""Game Object Objects Entity Entities Field Fields Slot Slots Table Value Values Set Get Clear Copy Init
    Initialize Update Data Flag Flags State And From To Reference Ref Refs Create Destroy Stamp Time Replace Handle
    Handles By With Index Entry Entries List Pointer Ptr Buffer Type Check Reset If Not Or Is Has Valid Store Load Read
    Write Add Remove Release Free Alloc Count First Next Find Send Message Dispatch Call Invoke Callback Callbacks
    Handler Handlers Global Local Pair Item Items Child Children Parent Id Kind Mode Param Params Result Source Info
    Record Records Struct Block Array Range Bit Bits Mask Byte Word Float Int Zero One Two Default Current Previous
    Active Enabled Disabled Pending All Any For In On Of At Into Internal Setup Family Manager Descriptor Vtable VTable
    Class Register Install Event Events Lifecycle System Generic Process Do Helper Func Unknown Misc Stuff Thing Number
    Size Length Offset Address Member Element Elements Node Nodes Attached Attach Detach Linked Link Apply Assign Swap
    Move Reverse Insert Append Push Pop Lookup Fetch Query Test Compare Equal Match Changed Change Mark Toggle Enable
    Disable Activate Deactivate Start Stop Begin End Open Close Run Step Tick Advance Fill Build Make New Old Temp Raw
    Other Same Each Every Nth Last Used Unused Empty Full Null Invalid Dirty Ready Done""".split())


def rule5(au):
    """Names made of a banned word or of nothing but what the code moves, the most called first."""
    sym, out = au.sym, []
    for a in au.audited():
        n, ws, why = sym.func[a], tokens(sym.func[a]), []
        banned = [w for w in ws if w in BANNED]
        if banned:
            why.append("the banned word %s" % ", ".join(banned))
        if any(w == "Handle" and i + 1 < len(ws) and ws[i + 1] in HANDLED for i, w in enumerate(ws)):
            why.append("Handle as its verb")
        if all(w in GENERIC for w in ws):
            why.append("only generic words")
        elif ws.count("And") and sum(w in GENERIC for w in ws) >= len(ws) - 1:
            why.append("a list of steps")
        if why:
            out.append((a, "; ".join(why) + "; called by " + au.callers_text(a, 3)))
    out.sort(key=lambda x: (-len(au.users(x[0])), x[0]))
    return out


def rule6(au):
    """Family in the name of a function that is not a family's."""
    sym, out = au.sym, []
    for a in au.audited():
        n = sym.func[a]
        if "Family" not in tokens(n) or a in au.owners:
            continue
        if a in au.family_functions:
            continue
        whose = au.whose(a)
        if len(whose) == 1:
            what = "reached only from %s: one type's, not its family's" % au.whose_text(a)
        elif whose:
            what = "reached only from %s" % au.whose_text(a)
        else:
            what = "no type's alone; called by " + au.callers_text(a, 4)
        out.append((a, what))
    return out


STORE = re.compile(r"^\s*(MEM(8|16|32|F|D)?\([^=]*\)|FLOAT_AT\([^=]*\)|[A-Z]\w*\([^=;]*\)|\*\w+) [-+|&^]?= ")


def rule7(au):
    """A name whose verb the function's shape contradicts."""
    sym, code, out = au.sym, au.code, []
    asks = {"Get", "Is", "Has", "Find", "Count", "Can", "Contains", "Lookup"}
    changes = {"Set", "Clear", "Reset", "Store", "Write"}
    for a in au.audited():
        if a not in code.body:
            continue
        n, ws = sym.func[a], set(tokens(sym.func[a]))
        body = [l.strip() for l in code.body[a] if l.strip()]
        real = [l for l in body if not re.match(r"^(u?int\d+_t|double|float|int)\b[^(]*;$", l)]
        stores = sum(1 for l in code.body[a] if STORE.match(l))
        calls = [au.name(b) for b in code.calls.get(a, ())]
        outs = [p for p in code.params.get(a, []) if "*" in p]
        if ws & asks and not ws & changes and code.returns.get(a) == "void" and not outs and not stores:
            out.append((a, "asks for something and hands nothing back: void, no output argument, no store"))
        elif ws & changes and not ws & asks and not stores and not calls:
            out.append((a, "named as a change and stores nothing and calls nothing (%d lines)" % len(real)))
        elif len(real) <= 3 and len(calls) == 1 and not stores and not any(w in calls[0] for w in ws if len(w) > 3):
            out.append((a, "only calls %s, and shares no word with it" % calls[0]))
    return out


def rule8(au):
    """Functions nobody calls, reached through a table of functions in the data."""
    sym, out = au.sym, []
    for a in au.audited():
        if au.users(a) or a in au.owners:
            continue
        places = au.tables.get(a, [])
        if not places:
            out.append((a, "nobody calls it and no word of the data holds its address"))
            continue
        shown = []
        for va in places[:2]:
            row = []
            for k in range(-2, 3):
                w = au.word(va + 4 * k) if au.word else None
                row.append("[%s]" % au.name(a) if k == 0 else
                           au.name(w) if w in sym.func or w in au.code.body else "-" if not w else "%X" % w)
            shown.append("0x%X: %s" % (va, " ".join(row)))
        out.append((a, "nobody calls it; held at %d place%s of the data: %s" % (
            len(places), "" if len(places) == 1 else "s", "; ".join(shown))))
    return out


def rule9(au):
    """The engine's prefix written two ways, and names that differ only in their case or an underscore."""
    sym, out = au.sym, []
    low = collections.defaultdict(list)
    for a, n in sym.func.items():
        low[n.lower().replace("_", "")].append(n)
    hand_vc = sorted({re.match(r"^vc[A-Z][a-z]+", n).group(0) for a, n in sym.func.items()
                      if re.match(r"^vc[A-Z][a-z]+", n) and sym.source(a) != "model"})
    for a in au.audited():
        n, why = sym.func[a], []
        m = re.match(r"^(Vc|Gc)([A-Z]\w*)$", n)
        if m:
            lower = m.group(1).lower() + m.group(2)
            same = [h for h in hand_vc if lower.startswith(h)]
            why.append("the engine's prefix is %s in the names given by hand%s: %s%s" % (
                m.group(1).lower(), " (%s...)" % same[0] if same else "", lower,
                " is taken" if lower in sym.address else ""))
        twins = [t for t in low[n.lower().replace("_", "")] if t != n]
        if twins:
            why.append("differs from %s only in its case or an underscore" % ", ".join(twins))
        if why:
            out.append((a, "; ".join(why)))
    return out


RULES = collections.OrderedDict()
RULES["1"] = ("a type's own function under a name that is not the type's", rule1)
RULES["2"] = ("a type's or a family's word in the name, reached only from types of another", rule2)
RULES["3"] = ("a number or a filler in the name, a clause on another's name, the same body under names that differ", rule3)
RULES["4"] = ("a comment that names a function by a name it no longer has, or says another thing than the name", rule4)
RULES["5"] = ("a banned word, or nothing but what the code moves, the most called first", rule5)
RULES["6"] = ("Family in the name of a function that is not a family's", rule6)
RULES["7"] = ("a verb the function's shape contradicts", rule7)
RULES["8"] = ("nobody calls it: a table of the data holds it, or nothing does", rule8)
RULES["9"] = ("the engine's prefix written two ways, or a name another has but for its case", rule9)


def siblings(au):
    """What the other sessions' proposals (build/sessions/*/proposal.txt) say of a function:
    {address: "session: rename to X"}."""
    out, root = {}, os.path.join(REPO, "build", "sessions")
    if not os.path.isdir(root):
        return out
    for s in sorted(os.listdir(root)):
        path = os.path.join(root, s, "proposal.txt")
        if s == "audit" or not os.path.exists(path):
            continue
        for t in open(path, encoding="utf-8", errors="replace"):
            p = t.split()
            if len(p) >= 3 and p[0] == "rename" and p[1] in au.sym.address:
                out[au.sym.address[p[1]]] = "%s: -> %s" % (s, p[2])
            elif len(p) >= 2 and p[0] == "unname" and p[1] in au.sym.address:
                out[au.sym.address[p[1]]] = "%s: unname" % s
            elif len(p) >= 3 and ADDRESS.match(p[0]) and p[1] == "func":
                a = int(p[0], 16)
                if au.sym.func.get(a) != p[2]:
                    out[a] = "%s: -> %s" % (s, p[2])
    return out


def show(au, what):
    """Everything the tool knows of one function, and its C with today's names."""
    sym, code = au.sym, au.code
    a = sym.address.get(what)
    if a is None and what in code.stale:
        a = code.stale[what]
    if a is None:
        try:
            a = int(what.replace("sub_", ""), 16)
        except ValueError:
            print("%s: no such function" % what)
            return
    n = au.name(a)
    print("=" * 100)
    print("%08X  %s  (%s)%s" % (a, n, sym.wave(a), "  in the C: " + code.c_name[a] if code.c_name.get(a, n) != n else ""))
    if n in sym.comment:
        print("comment: " + sym.comment[n])
    if a in au.owners:
        print("a type's own: " + ", ".join("%s's %s" % (au.label((f, t)), s) for f, t, s in au.owners[a][:8]))
    w = au.whose_text(a, 8)
    print("reached only from: " + (w or "(not only from types)"))
    us = sorted(au.users(a), key=au.name)
    print("called or stored by %d: %s" % (len(us), ", ".join(
        au.name(b) + (" [%s]" % au.whose_text(b, 2) if au.whose_text(b, 2) else "") for b in us[:25])))
    print("calls: " + ", ".join(sorted(au.name(b) for b in code.calls.get(a, ()))))
    if code.refs.get(a):
        print("stores the address of: " + ", ".join(sorted(au.name(b) for b in code.refs[a])))
    if au.tables.get(a):
        print("held in the data at: " + ", ".join("0x%X" % v for v in au.tables[a][:12]))
    made = makes(au, a)
    if made:
        print("makes or uses: " + ", ".join(made))
    if au.string:
        found = [au.string(int(x, 16)) for x in dict.fromkeys(re.findall(r"0x(1[0-9A-F]{5})u", code.text(a)))]
        if any(found):
            print("its strings: " + ", ".join('"%s"' % t for t in found if t))
    text = code.text(a)
    if not text:
        print("(the decompiled C does not have it: py -3.14 tools/ghidra/show.py %X)" % a)
        return
    def today(m):
        w = m.group(0)
        if w.endswith("_entry") and w[:-6] in code.stale:
            return au.name(code.stale[w[:-6]])
        return au.name(code.stale[w]) if w in code.stale else w
    print("%s %s(%s)" % (code.returns.get(a, ""), n, ", ".join(code.params.get(a, []))))
    print(WORD.sub(today, text))


def makes(au, a):
    """The types a function makes or takes a use of by a number: GameObjectCreate(family, type),
    GameObjectTypeUse, and the families' own makers with a number (tools/type_makers.py follows them)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import type_makers
    except ImportError:
        return []
    family = {f["number"]: f["name"] for f in au.families}
    out = []
    for callee, args in type_makers.calls_with_numbers(au.code.body.get(a, [])):
        if callee in ("GameObjectCreate", "GameObjectTypeUse", "GameObjectTypeRelease") and len(args) > 1                 and args[0] in family and args[1] is not None:
            out.append("%s(%s)" % (callee, au.label((family[args[0]], args[1]))))
        elif callee == "WeaponCreate" and args and args[0] is not None:
            out.append("WeaponCreate(%s)" % au.label(("Weapon", args[0])))
        elif callee == "EffectCreateInstance" and args and args[0] is not None:
            out.append("EffectCreateInstance(%s)" % au.label(("Effect", args[0])))
    return list(dict.fromkeys(out))


def comments(au):
    """The comment lines that name a function by a name it no longer has, rewritten with today's."""
    sym, n = au.sym, 0
    for name, text in sym.comment.items():
        if "(generated by" in sym.comment_section.get(name, ""):
            continue
        refs = stale_references(au, text)
        if not refs:
            continue
        for old, new in refs:
            text = re.sub(r"\b%s\b" % re.escape(old), new, text)
        print("comment %s %s" % (name, text))
        n += 1
    print("# %d comments rewritten" % n, file=sys.stderr)


NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9]*(_[A-Za-z][A-Za-z0-9]*)?$")


def check(au, path):
    """A proposal's rename, unname, keep and comment lines against symbols.txt: every old name is a
    function's today, no new name is taken or given twice, none has a banned word or a stray number."""
    sym, problems = au.sym, []
    renames, gone, kept, commented, seen_new = {}, set(), set(), [], {}
    for k, t in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
        p = t.split("#")[0].split()
        if not p or p[0] not in ("rename", "unname", "keep", "comment"):
            continue
        if p[0] == "rename":
            if len(p) != 3:
                problems.append("line %d: rename takes two names" % k)
                continue
            old, new = p[1], p[2]
            if old not in sym.address:
                problems.append("line %d: %s is no function's name today" % (k, old))
            if old in renames or old in gone or old in kept:
                problems.append("line %d: %s settled twice" % (k, old))
            if new in seen_new:
                problems.append("line %d: %s given twice (line %d)" % (k, new, seen_new[new]))
            seen_new[new] = k
            renames[old] = new
            if not NAME_OK.match(new):
                problems.append("line %d: %s is not a name" % (k, new))
            ws = tokens(new)
            bad = [w for w in ws if w in BANNED] + stray_numbers(new, [t for t in sym.types.values() if t in new])
            if bad:
                problems.append("line %d: %s has %s" % (k, new, ", ".join(bad)))
        elif p[0] in ("unname", "keep"):
            if len(p) < 2 or p[1] not in sym.address:
                problems.append("line %d: %s is no function's name today" % (k, p[1] if len(p) > 1 else "?"))
            elif p[1] in renames or p[1] in gone or p[1] in kept:
                problems.append("line %d: %s settled twice" % (k, p[1]))
            (gone if p[0] == "unname" else kept).add(p[1] if len(p) > 1 else "")
        else:
            commented.append((k, p[1] if len(p) > 1 else ""))
    for old, new in renames.items():
        if (new in sym.address or new in sym.other) and new not in renames and new not in gone:
            problems.append("%s -> %s: the new name is taken" % (old, new))
    news = set(renames.values())
    for k, n in commented:
        if n not in news and n not in sym.address:
            problems.append("line %d: comment of %s, which is no name today nor a new one here" % (k, n))
        if n in renames or n in gone:
            problems.append("line %d: comment of %s, which this file renames or unnames" % (k, n))
    print("%s: %d rename, %d unname, %d keep, %d comment; %d problem%s" % (
        os.path.relpath(path, REPO), len(renames), len(gone), len(kept), len(commented), len(problems),
        "" if len(problems) == 1 else "s"))
    for t in problems:
        print("  " + t)
    return not problems


def main():
    args = sys.argv[1:]
    au = Audit()
    sym = au.sym
    if args and args[0] == "show":
        for what in args[1:]:
            show(au, what)
        return
    if args and args[0] == "comments":
        comments(au)
        return
    if args and args[0] == "check":
        sys.exit(0 if all([check(au, p) for p in args[1:]]) else 1)
    wanted = [a for a in args if a in RULES] or list(RULES)
    said = siblings(au)
    # symbols/audit_kept.txt: `RULE  NAME  why`, a name a review read and kept under that rule; it is not
    # flagged by it again while it has that name (a rename makes it a new suspect)
    kept = set()
    if os.path.exists(KEPT):
        for l in open(KEPT, encoding="utf-8"):
            p = l.split()
            if len(p) >= 2 and not l.startswith("#"):
                kept.add((p[0], p[1]))
    counts, lines, flagged = collections.OrderedDict(), [], set()
    for r in wanted:
        title, rule = RULES[r]
        found = [(a, what) for a, what in rule(au) if (r, au.name(a)) not in kept]
        counts[r] = len(found)
        flagged |= {a for a, _ in found}
        lines.append("")
        lines.append("== rule %s: %s: %d" % (r, title, len(found)))
        for a, what in found:
            lines.append("%s  %08X  %-44s %-6s %3d  %s%s" % (
                r, a, au.name(a), sym.wave(a), len(au.users(a)), what, "  {%s}" % said[a] if a in said else ""))
    print("# tools/audit_names.py: %d functions with a name, %d of them a model's or a reader's from the C;"
          % (len(sym.func), len(au.audited())))
    print("# %d of those flagged by a rule or more (a line: rule, address, name, who named it, how many"
          % len(flagged))
    print("# functions call it or store its address, the evidence, and {what another session proposes})")
    for r, n in counts.items():
        print("# rule %s: %4d  %s" % (r, n, RULES[r][0]))
    if "counts" not in args:
        print("\n".join(lines))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    main()
