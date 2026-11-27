"""A level's file read as the game reads it: every object's record, walked by the format.

    py -3 tools/level_dump.py m101_f              the level's objects as a tree
    py -3 tools/level_dump.py m101_f --logic      its components: each entry's triggers and actions
    py -3 tools/level_dump.py m101_f --fields     the tree with every field read
    py -3 tools/level_dump.py --check             the 59 levels: records by type, and how many end where
                                                  their header says (against tools/level_names.py's pattern)

A level (Media/vcResources/xbox/gcLevel/*.lvl) is one VC2 file: the magic "VC2\\x1a", a word, and one
engine object, the gcLevel (class 0x20), read by vcObjectLoad and gcLevel_Load. An engine object's
reference in a file is a word (0: none), an index (0 or more: the object of that number among the ones
this file has made so far; -1: a new one), and for a new one its class, its flags (1: only its name is
here, the game gets it by name), its name (a 16-bit length, the bytes), 16 bytes, the file on a multiple
of 4, a word, its version and the offset it ends at. The gcLevel holds, in this order: the level's own
vcPak (class 0x1C: every texture, mesh, sound and model the level uses), the level's settings (ambient
colours, fog, near and far planes, bounds, the types it uses, its music) and the root of its game
objects, read by GameObjectLoad.

A game object's reference is the same idea (GameObjectLoad, 0x1DCD0): a word (0: none), an index (as
above, into the same list: the engine objects and the game objects of a file are numbered together, in
the order they are made), and for a new one its family, its type, a word nothing reads, its family's
version, its type's version and the offset its record ends at; then what the type's load function reads
(GameObjectType +0x10), which is what this file follows, a function a type. A node's (family 11) common
part is GameObjectNodeLoad's: position, rotation, the 64-byte name, flags, placement, the state it
starts in and its children, each a record of its own inside its parent's; the type's own part follows
the children.

Every record must end at the offset its header gives: the check of this reader. The names of the types
are symbols.txt's `type` lines.
"""
import collections, glob, json, os, re, struct, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEVELS = os.path.join(REPO, "RB-XBE", "Robotech Battlecry", "Media", "vcResources", "xbox", "gcLevel")

# The engine's classes by number: src/game/engine/classes.c's registrations and the register functions
# of the decompiled C (the word each stores first in its vcClassDesc).
CLASSES = {1: "vcTexture", 2: "vcMaterial", 3: "vcLight", 4: "vcSpline", 5: "vcSplineObject", 6: "vcMesh",
           7: "vcObject", 8: "vcSceneExport", 9: "vcMotionFiles", 10: "vcMultiSub", 11: "vcParticleSystem",
           12: "vcMultiSubObject", 13: "vcGeometryTrail", 14: "vcTerrain", 15: "vcSnd", 16: "vcRefObject",
           17: "vcSkybox", 18: "vcStringManager", 20: "vcShadow", 21: "vcSpaceScene", 22: "vcLineEffect",
           23: "vcSkyScene", 24: "vcLensFlare", 26: "vcVolumeObject", 27: "vcMusic", 28: "vcPak", 29: "vcSound",
           31: "vcDecalMgr", 32: "gcLevel", 33: "gcComponent", 34: "gcAIData", 48: "vcPhysiqueManager",
           49: "vcSFXBank"}


def names():
    """The families' names and versions (registries.json) and the types' names (symbols.txt)."""
    reg = json.load(open(os.path.join(REPO, "symbols", "registries.json")))["families"]
    family = {f["number"]: f["name"] for f in reg}
    has_load = {(f["number"], t["type"]): "0x10" in t["slots"] for f in reg for t in f["types"]}
    typed = {}
    for line in open(os.path.join(REPO, "symbols", "symbols.txt"), encoding="utf-8"):
        p = line.split()
        if len(p) >= 4 and p[0] == "type" and p[2].isdigit():
            typed[(p[1], int(p[2]))] = p[3]
    return family, typed, has_load


FAMILY, TYPED, HAS_LOAD = names()


def type_name(family, number):
    f = FAMILY.get(family, "Family%d" % family)
    return TYPED.get((f, number), "%s %d" % (f, number))


class Wrong(Exception):
    pass


class Thing:
    """An object of the file: an engine object (kind "vc") or a game object (kind "game")."""

    def __init__(self, kind, at):
        self.kind, self.at, self.index, self.end = kind, at, None, None
        self.family = self.type = self.cls = None
        self.name, self.fields, self.children, self.parts = "", [], [], []
        self.ok, self.note, self.by_name = True, "", False

    def label(self):
        if self.kind == "vc":
            return "%s \"%s\"%s" % (CLASSES.get(self.cls, "class 0x%X" % self.cls), self.name,
                                    " (by name)" if self.by_name else "")
        return "%s \"%s\"" % (type_name(self.family, self.type), self.name)

    def get(self, key, default=None):
        for k, v in self.fields:
            if k == key:
                return v
        return default


class Ref:
    """A reference to an object the file made before: its number in the file's list."""

    def __init__(self, index, thing):
        self.index, self.thing = index, thing


class Level:
    def __init__(self, path):
        self.path, self.d, self.p = path, open(path, "rb").read(), 0
        self.objects, self.records, self.bad = [], [], []
        self.settings, self.root, self.pak, self.level = [], None, None, None
        self.read()

    # ---- the file's words
    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def s32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def floats(self, n):
        v = struct.unpack_from("<%df" % n, self.d, self.p)
        self.p += 4 * n
        return tuple(round(x, 4) for x in v)

    def words(self, n):
        v = struct.unpack_from("<%dI" % n, self.d, self.p)
        self.p += 4 * n
        return v

    def text(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b.split(b"\0")[0].decode("latin-1")

    def add(self, thing):
        thing.index = len(self.objects)
        self.objects.append(thing)

    def ref(self, index):
        return Ref(index, self.objects[index] if index < len(self.objects) else None)

    # ---- an engine object's reference (vcObjectLoad, 0x110E90)
    def vc(self, walk=None):
        at = self.p
        if self.u32() == 0:
            return None
        index = self.s32()
        if index >= 0:
            return self.ref(index)
        t = Thing("vc", at)
        t.cls, flags = self.u32(), self.u32()
        n = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        t.name = self.text(n)
        self.p = (self.p + 16 + 3) & ~3
        t.fields.append(("flags", flags))
        self.add(t)
        if flags & 1:
            t.by_name = True
            return t
        self.u32()
        t.fields.append(("version", self.u32()))
        t.end = self.u32()
        if walk:
            walk(t)
        else:
            self.inside(t)
        self.p = t.end
        return t

    def inside(self, t):
        """The engine objects inside one whose class this reader does not follow: found by their
        headers (a word 1, -1, a class, flags, a name of the length given), each checked."""
        d, p = self.d, self.p
        while True:
            p = d.find(b"\x01\0\0\0\xff\xff\xff\xff", p)
            if p < 0 or p >= t.end:
                return
            cls, flags = struct.unpack_from("<II", d, p + 8)
            n = struct.unpack_from("<H", d, p + 16)[0]
            name = d[p + 18:p + 18 + n]
            if cls < 0x40 and flags < 0x100 and 0 < n <= 0x80 and name[-1:] == b"\0" and \
                    all(32 <= c < 127 for c in name[:-1]):
                self.p = p
                child = self.vc()
                if child.end is None or p < child.end <= t.end:
                    t.children.append(child)
                    p = self.p
                    continue
                self.objects.pop()
            p += 4

    # ---- a game object's reference (GameObjectLoad, 0x1DCD0)
    def game(self):
        at = self.p
        if self.u32() == 0:
            return None
        index = self.s32()
        if index >= 0:
            return self.ref(index)
        t = Thing("game", at)
        t.family, t.type, unread = self.u32(), self.u32(), self.u32()
        self.p = (self.p + 3) & ~3
        fv, tv, t.end = self.u32(), self.u32(), self.u32()
        t.fields += [("family_version", fv), ("version", tv)]
        self.records.append(t)
        if not (0 < t.family < 14 and t.type < 127 and at < t.end <= len(self.d)):
            raise Wrong("no game object's header at 0x%X" % at)
        load = LOADERS.get((t.family, t.type)) or LOADERS.get(t.family)
        if load is None or not HAS_LOAD.get((t.family, t.type), False):
            t.ok, t.note = False, "no loader"
        else:
            try:
                load(self, t, fv, tv)
                if self.p != t.end:
                    t.ok, t.note = False, "read to 0x%X, ends at 0x%X" % (self.p, t.end)
            except (Wrong, struct.error, IndexError) as e:
                t.ok, t.note = False, "%s" % e
        if not t.ok:
            self.bad.append(t)
        self.p = t.end
        return t

    # ---- the file
    def read(self):
        if self.d[:4] != b"VC2\x1a":
            raise Wrong("not a VC2 file")
        self.p = 8
        self.level = self.vc(self.gclevel)
        self.trailer = struct.unpack_from("<I", self.d, self.p)[0] if self.p + 4 <= len(self.d) else None

    def gclevel(self, t):
        """gcLevel_Load (0x273B0), by the version the header gives (15 in every level of the disc)."""
        v, s = t.get("version"), self.settings
        if v > 3:
            self.pak = self.vc()
        s.append(("light_colour", self.floats(4)))            # +0x58: ColorSetGlobalRenderState
        if v >= 6:
            s.append(("object_colour", self.floats(4)))       # +0x68: ColorSetObjectColor
        if v >= 8:
            s.append(("vertex_colour", self.floats(4)))       # +0x78: ColorSetVertexColor
        s.append(("fog_start", self.f32()))                   # +0x28
        s.append(("fog_end", self.f32()))                     # +0x2C
        s.append(("fog_colour", "0x%08X" % self.u32()))       # +0x30
        s.append(("near_plane", self.f32()))                  # +0x34: LevelNearPlane
        s.append(("far_plane", self.f32()))                   # +0x38: LevelFarPlane
        s.append(("vector_08", self.floats(3)))
        s.append(("vector_18", self.floats(3)))
        s.append(("float_14", self.f32()))
        if v != 0:
            s.append(("bounds_min", self.floats(3)))          # LevelFileBoundsMin
            s.append(("bounds_max", self.floats(3)))          # LevelFileBoundsMax
            if v > 1:
                s.append(("fog_on", self.u32()))              # +0x24
            if v > 2:
                s.append(("timed", self.u32()))               # +0x88: LevelTimeSet(-50) when set
            if v > 4:
                s.append(("words_90", self.words(32)))        # +0x90: 32 words
            if v > 6:
                s.append(("word_8C", self.u32()))
        if v >= 9:
            s.append(("word_110", self.s32()))
        if v >= 10:
            s.append(("word_114", self.u32()))
            s.append(("word_118", self.u32()))
        if v >= 12:
            s.append(("word_11C", self.u32()))
        if v >= 15:
            s.append(("word_120", self.s32()))
        if v >= 11:
            s.append(("music", self.text(64)))                # +0x124: the vcMusic it plays
        if v >= 13:
            s.append(("name_1A4", self.text(64)))             # +0x1A4
        if v >= 14:
            s.append(("music_alternate", self.text(64)))      # +0x164: the vcMusic when 0x1BC490 is set
        self.root_at = self.p
        self.root = self.game()

    # ---- what the level's game objects are, flat
    def walk(self, t=None, depth=0, parent=None):
        """Every new record under t (the root when None), with its depth and the record it is in."""
        if t is None:
            t = self.root
        if not isinstance(t, Thing):
            return
        yield t, depth, parent
        for kind, child in t.parts:
            if isinstance(child, Thing):
                yield from self.walk(child, depth + 1, t)


# ---- the types' load functions, a function each. L is the Level, t the object, fv and tv the versions

def part(L, t, what, value):
    """One nested reference of a record: a new object, a reference to one made before, or none."""
    t.parts.append((what, value))
    return value


def node(L, t, fv, tv):
    """GameObjectNodeLoad (0x39740): every node's common part."""
    f = t.fields
    f.append(("position", L.floats(3)))                 # the creation's: +0x7C once made
    f.append(("rotation", L.floats(9)))
    L.add(t)                                            # GameObjectCreateInFile(file, 11, type, ...)
    t.name = L.text(64)                                 # +0x00
    f.append(("flags", L.u32()))                        # +0x40
    f.append(("word_44", L.u32()))
    f.append(("word_48", L.u32()))
    # which is which: GameObjectUpdateHierarchyTransforms (0x38CE0) makes the world matrix (+0x88) of the
    # parent's times the matrix of the angles at +0xAC times +0x58, and the world position (+0x7C) of
    # the parent's matrix times +0x4C plus the parent's position
    f.append(("rotation_angles", L.floats(3)))          # +0xAC (Node.rotation_angles)
    f.append(("position_world", L.floats(3)))           # +0x7C (Node.position)
    f.append(("position_in_parent", L.floats(3)))       # +0x4C
    f.append(("rotation_world", L.floats(9)))           # +0x88 (Node.rotation)
    f.append(("rotation_in_parent", L.floats(9)))       # +0x58
    f.append(("start_state", L.u32()))                  # +0xC8
    for _ in range(L.u32()):
        child = part(L, t, "child", L.game())
        if child is None:
            break                                       # the loader gives up at a child it cannot make


def folder(L, t, fv, tv):                               # FolderNode_Load (0xDE6D0)
    node(L, t, fv, tv)
    t.fields.append(("word_D0", L.u32()))


def stand_in(L, t, fv, tv):                             # PlayerStandInEntityNode_Load (0x4CA60)
    node(L, t, fv, tv)
    part(L, t, "stands_for", L.game())                  # +0xD0: the object it places
    if tv >= 1:
        part(L, t, "second", L.game())                  # +0xD4


def vc_only(L, t, fv, tv):                              # GameObjectLoadVcObject (0xC80A0) and the like
    node(L, t, fv, tv)
    part(L, t, "object", L.vc())                        # +0xD0


def stand_in_mso(L, t, fv, tv):                         # PlayerStandInMSONode_Load (0xDE260)
    node(L, t, fv, tv)
    part(L, t, "game_object", L.game())                 # +0xD4
    part(L, t, "object", L.vc())                        # +0xD0
    if tv >= 1:
        part(L, t, "linked", L.game())                  # +0xD8
        if tv < 3:
            for i in range(7 if tv == 1 else 9):
                part(L, t, "linked_%d" % i, L.game())


def helper(L, t, fv, tv):                               # HelperNode_Load (0xDD580)
    node(L, t, fv, tv)
    t.fields.append(("word_D4", L.u32()))
    part(L, t, "object", L.vc())                        # +0xD0


def model(L, t, fv, tv):                                # ModelNode_Load (0xD89A0)
    node(L, t, fv, tv)
    if tv < 1:
        part(L, t, "object", L.vc())
        return
    t.fields.append(("model", L.text(64)))              # +0xD4: the vcMultiSub it is cloned from
    if tv >= 2:
        t.fields.append(("collision_flags", L.u32()))   # +0x114: 8 when 0


def camera(L, t, fv, tv):                               # CameraNode_Load (0xAD3D0)
    node(L, t, fv, tv)
    t.fields.append(("vector_D4", L.floats(3)))
    t.fields.append(("float_E0", L.f32()))
    if tv > 0:
        t.fields.append(("word_E4", L.u32()))
    part(L, t, "target", L.game())                      # +0xD0


def spline(L, t, fv, tv):                               # SplineNode_Load (0x3AC40)
    node(L, t, fv, tv)
    t.fields.append(("words_D8", L.words(8)))
    part(L, t, "spline_object", L.vc())                 # +0xD0: a vcSplineObject
    part(L, t, "spline", L.vc())                        # +0xD4: its vcSpline


def point(L, t, fv, tv):                                # PointNode_Load (0xDC050)
    node(L, t, fv, tv)
    t.fields.append(("words_D0", L.words(3)))


def sky(L, t, fv, tv):                                  # SkyNode_Load (0xACC40)
    node(L, t, fv, tv)
    t.fields.append(("kind", L.u32()))                  # +0xD0
    part(L, t, "object", L.vc())                        # +0xD4
    if tv > 0:
        part(L, t, "second_object", L.vc())             # +0xE4
    if tv >= 2:
        t.fields.append(("word_D8", L.u32()))
        t.fields.append(("word_E0", L.u32()))
        t.fields.append(("word_DC", L.u32()))


def path(L, t, fv, tv):                                 # PathNode_Load (0x3C240)
    node(L, t, fv, tv)
    f = t.fields
    count = L.u32()                                     # +0xD0: its points
    f.append(("capacity", L.u32()))                     # +0xD4: 32 bytes a point allocated
    points = [L.floats(3) for _ in range(count)]
    f.append(("words_DC", L.words(7)))                  # +0xDC, +0xE8, +0xE0, +0xE4, +0xEC, +0xF0, +0xF4
    if tv > 1:
        f.append(("word_FC", L.u32()))
    if tv > 2:
        f.append(("word_100", L.u32()))                 # 150 without it
    if tv > 3:
        f.append(("float_104", L.f32()))                # 100.0 without it
        extra = [L.floats(2) for _ in range(count)]     # each point's +0xC and +0x10: 1.0 and 1.0 without
        points = [p + e for p, e in zip(points, extra)]
    f.append(("points", points))


def spawn_group(L, t, fv, tv):                          # SpawnGroupNode_Load (0x9F4C0)
    node(L, t, fv, tv)
    f = t.fields
    f.append(("words_42C", L.words(25)))                # 25 words, to +0x42C ... +0x428 in the code's order
    count = L.u32()                                     # +0xD0: its places
    f.append(("capacity", L.u32()))                     # +0xD4
    f.append(("places", [(L.floats(3), L.floats(9)) for _ in range(count)]))   # +0xD8: position, rotation
    f.append(("words_48C", L.words(13)))                # +0x48C ... +0xE0
    if tv >= 1:
        f.append(("words_4BC", L.words(4)))             # one not kept, then +0x4BC, +0x4C0, +0x4C4
    if tv >= 2:
        part(L, t, "object_4B8", L.game())              # +0x4B8
        part(L, t, "object_4D0", L.game())              # +0x4D0
    if tv > 3:
        f.append(("word_E4", L.u32()))
    if tv > 4:
        f.append(("word_DC", L.u32()))
    if tv > 5:
        f.append(("word_4C8", L.u32()))
    if tv > 8:
        f.append(("word_4D4", L.u32()))
    if 9 < tv < 14:
        f.append(("word_old", L.u32()))
    if tv > 10:
        f.append(("word_484", L.u32()))
    if tv > 11:
        f.append(("word_4D8", L.u32()))
    if tv > 12:
        f.append(("word_4CC", L.u32()))
    if tv > 13:
        f.append(("float_4DC", L.f32()))


def water(L, t, fv, tv):                                # WaterNode_Load (0xA3FD0)
    node(L, t, fv, tv)
    kind = L.u32()                                      # +0xD0
    t.fields.append(("kind", kind))
    obj = part(L, t, "object", L.vc())                  # +0xD4
    if kind == 0 and obj is not None and tv >= 1:
        t.fields.append(("name_a", L.text(64)))
        t.fields.append(("name_b", L.text(64)))


def cinema(L, t, fv, tv):                               # CinemaNode_Load (0x16BF0)
    node(L, t, fv, tv)
    f = t.fields
    f.append(("words_E0", L.words(5)))                  # +0xE0, +0xE4, +0xE8, +0xEC, +0xF4
    events = []
    for i in range(L.u32()):                            # its events, 0x3C bytes each in memory
        e = {"kind": L.u32()}
        if tv >= 4:
            e["flags"] = L.u32()                        # +0x04
        e["words"] = L.words(6)                         # +0x10 ... +0x24
        e["object"] = part(L, t, "event_%d_object" % i, L.game())      # +0x08
        if tv > 1:
            e["second"] = part(L, t, "event_%d_second" % i, L.game())  # +0x0C
        if e["kind"] == 2:                              # a text on the screen
            if tv <= 2:
                e["text"] = L.text(0xFF)
            e["rect"] = L.words(4)                      # vcFileReadRect
            e["text_words"] = L.words(4)                # +0x110 ... +0x11C
        events.append(e)
    f.append(("events", events))


def link(L, t, fv, tv):                                 # LinkNode_Load (0x3A1E0)
    node(L, t, fv, tv)
    part(L, t, "target", L.game())                      # +0xD0
    if tv >= 1:
        t.fields.append(("word_D4", L.u32()))
    if tv >= 2:
        t.fields.append(("vector_E4", L.floats(3)))
    if tv >= 3:
        t.fields.append(("vector_D8", L.floats(3)))


def sound(L, t, fv, tv):                                # SoundNode_Load (0xDB560)
    node(L, t, fv, tv)
    t.fields.append(("playing", L.u32()))               # +0xD4: nonzero sends it its start state
    t.fields.append(("word_D8", L.u32()))
    t.fields.append(("range", L.floats(2)))             # ObjectSetRange's two
    part(L, t, "sound", L.vc())                         # +0xD0


def collision_volume(L, t, fv, tv):                     # CollisionVolumeNode_Load (0xDAEB0)
    node(L, t, fv, tv)
    obj = part(L, t, "volume", L.vc())                  # +0xD0: a vcVolumeObject
    if obj is not None and tv >= 1:
        t.fields.append(("collision_flags", L.u32()))   # +0xD4: 8 when 0


def node22(L, t, fv, tv):                               # 0xDAB80
    node(L, t, fv, tv)
    t.fields.append(("vector_D0", L.floats(3)))
    t.fields.append(("words_100", L.words(2)))
    t.fields.append(("matrix_DC", L.floats(9)))


def node23(L, t, fv, tv):                               # 0xDA6B0
    node(L, t, fv, tv)
    t.fields.append(("text_D0", L.text(0x100)))


def civilians(L, t, fv, tv):                            # CiviliansNode_Load (0xDA2F0)
    node(L, t, fv, tv)
    part(L, t, "object", L.game())                      # +0xD0
    t.fields.append(("word_D4", L.u32()))
    lanes = []
    for _ in range(16):                                 # 16 records of 0x4C bytes from +0xD8
        if tv >= 2:
            lane = {"box": (L.floats(3), L.floats(3)), "word": L.u32(), "direction": L.floats(3), "count": L.u32()}
            if tv >= 6:
                lane["words"] = L.words(2)
            if tv >= 7:
                lane["word_28"] = L.u32()
            lanes.append(lane)
    t.fields.append(("lanes", lanes))


def keyval(L, t, fv, tv):                               # KeyValCountersNode_Load (0xD8C80)
    node(L, t, fv, tv)
    t.fields.append(("counters", L.words(5)))           # +0xD0: five words


def entity(L, t, fv, tv):
    """Entity_Load (0x19500) and EntityReadFromFile (0x19220); the versions are the family's."""
    f = t.fields
    f.append(("position", L.floats(3)))
    f.append(("word_a", L.u32()))
    f.append(("word_b", L.u32()))
    part(L, t, "object", L.game())
    if fv >= 1:
        f.append(("word_c", L.s32()))
    L.add(t)                                            # GameObjectCreateInFile(file, 2, type, ...)
    if fv > 6:
        f.append(("word_240", L.u32()))
    if fv > 7:
        f.append(("word_260", L.u32()))
    if fv > 9:
        f.append(("word_244", L.u32()))
    has_ai = L.u32()
    f.append(("has_ai", has_ai))
    if has_ai:
        f.append(("ai_word", L.u32()))
        f.append(("ai_words_38", L.words(6)))           # the AI's +0x38, +0x34, +0x2C, +0x24, +0x30, +0x50
        f.append(("ai_vector_58", L.floats(3)))
        f.append(("ai_vector_88", L.floats(3)))
        f.append(("ai_words_40", L.words(4)))           # +0x40, +0xA4, +0x2AC, +0x2B0
        if fv < 1:
            f.append(("ai_word_298", L.u32()))
        f.append(("ai_word_local", L.u32()))
        f.append(("ai_word_29C", L.u32()))
        f.append(("ai_word_2B4", L.u32()))
        f.append(("ai_theme", L.s32()))                 # +0x2DC: the theme's number in aidata.spt
        f.append(("ai_words_2E0", L.words(2)))
        f.append(("ai_word_local2", L.u32()))
        f.append(("ai_words_28", L.words(3)))           # +0x28, +0x08, +0x00
        part(L, t, "ai_object_70", L.game())            # +0x70
        if fv > 1:
            part(L, t, "ai_path", L.game())             # +0xC8: the path it follows
            f.append(("ai_word_04", L.u32()))
        if fv > 2:
            f.append(("ai_word_20", L.u32()))
        if fv > 3:
            f.append(("ai_word_84", L.s32()))
        if fv > 5:
            f.append(("ai_word_2A0", L.u32()))


def vehicle(L, t, fv, tv):                              # Vehicle_Load (0x52EB0)
    entity(L, t, fv, tv)
    if tv >= 2:
        part(L, t, "path", L.game())                    # +0x270
        t.fields.append(("word_274", L.u32()))


def player(L, t, fv, tv):                               # Player_Load (0x3E6B0), PlayerCreateFromFile
    t.name = L.text(64)
    t.fields.append(("word_a", L.u32()))
    t.fields.append(("word_b", L.u32()))
    L.add(t)
    if tv >= 1:
        t.fields.append(("word_3F0", L.u32()))
        t.fields.append(("word_3EC", L.u32()))
    if tv >= 2:
        t.fields.append(("word_3F4", L.u32()))
    if tv > 2:
        t.fields.append(("word_3F8", L.u32()))


def structure(L, t, fv, tv):                            # StructureReadFromFile (0xD8190)
    f = t.fields
    f.append(("position", L.floats(3)))
    f.append(("rotation", L.floats(9)))
    f.append(("word_a", L.u32()))
    f.append(("word_b", L.u32()))
    L.add(t)
    if fv > 0:
        f.append(("word_44", L.u32()))


def building(L, t, fv, tv):                             # Building_Load (0x10A320)
    structure(L, t, fv, tv)
    f = t.fields
    t.name = L.text(64)                                 # the model it is made from (BuildingCreateFromName)
    f.append(("bytes_470", L.d[L.p:L.p + 8].hex()))
    L.p += 8
    if tv >= 1:
        f.append(("word_478", L.u32()))
    if 2 <= tv < 5:
        f.append(("word_old", L.u32()))
    if tv >= 3:
        if tv >= 4:
            f.append(("word_484", L.u32()))
        part(L, t, "object_40", L.game())
    if tv >= 5:
        f.append(("bytes_490", L.words(4)))
    if tv >= 6:
        f.append(("word_last", L.u32()))


def object_swap(L, t, fv, tv):                          # ObjectSwapStructure_Load (0x107970)
    structure(L, t, fv, tv)
    f = t.fields
    f.append(("word_150", L.u32()))
    f.append(("word_154", L.u32()))
    f.append(("model", L.text(64)))
    f.append(("second_model", L.text(64)))
    f.append(("pooled_object", L.text(64)))
    t.name = L.text(64)


def item(L, t, fv, tv):                                 # Item_Load (0xD7910)
    t.fields.append(("position", L.floats(3)))
    t.fields.append(("vector", L.floats(3)))
    L.add(t)


def puny_human(L, t, fv, tv):                           # PunyHumanPickup_Load (0x105E80)
    item(L, t, fv, tv)
    if tv:
        t.name = L.text(64)


def component(L, t, fv, tv):                            # ObjectGroupComponent_Load (0xD7330)
    t.name = L.text(64)
    L.add(t)
    part(L, t, "object", L.game())                      # +0x00
    entries = []
    for i in range(16):                                 # 16 entries of 0x9C bytes from +0x44
        e = {"used": L.u32()}
        if tv >= 1:
            e["word_44"] = L.u32()
        e["name"] = L.text(64)
        if e["used"]:
            e["triggers"] = [part(L, t, "entry_%d_trigger" % i, L.game()) for _ in range(10)]
            e["actions"] = [part(L, t, "entry_%d_action" % i, L.game()) for _ in range(10)]
        entries.append(e)
    t.fields.append(("entries", entries))
    if fv >= 2:
        t.fields.append(("timers", L.words(16)))        # +0xA04: -1 for none
    if fv >= 3:
        t.fields.append(("word_A44", L.u32()))


def trigger(L, t, fv, tv):
    """BooleanTrigger_Load (0xD3240): every trigger's common part."""
    f = t.fields
    f.append(("words_a", L.words(3)))
    L.add(t)
    f.append(("word_2C", L.u32()))
    t.name = L.text(32)
    for i in range(L.u32()):
        part(L, t, "listed", L.game())


def trigger_own(read):
    def load(L, t, fv, tv):
        trigger(L, t, fv, tv)
        read(L, t, tv)
    return load


def t_player_proximity(L, t, tv):                       # 0x2BBE0
    f = t.fields
    f.append(("point", L.floats(3)))
    f.append(("float_4C", L.f32()))
    if tv >= 1:
        f.append(("word_50", L.u32()))
    if tv >= 2:
        f.append(("word_54", L.u32()))
    if tv >= 3:
        f.append(("word_58", L.u32()))
        f.append(("box", (L.floats(3), L.floats(3))))
    if tv >= 4:
        f.append(("words_74", L.words(2)))


def t_objective_state(L, t, tv):                        # 0x104AA0
    t.fields.append(("words_40", L.words(2)))
    if tv >= 1:
        t.fields.append(("word_48", L.u32()))


def t_entity_proximity(L, t, tv):                       # 0x2C260
    f = t.fields
    f.append(("point", L.floats(3)))
    f.append(("float_50", L.f32()))
    if tv >= 1:
        f.append(("word_74", L.u32()))
        f.append(("box", (L.floats(3), L.floats(3))))
    if tv >= 2:
        f.append(("words_6C", L.words(2)))
    part(L, t, "object", L.game())


def t_on_time(L, t, tv):                                # 0x104840
    t.fields.append(("words_40", L.words(3)))
    if tv >= 1:
        t.fields.append(("word_4C", L.u32()))


def t_five(L, t, tv):                                   # 0x1045B0
    t.fields.append(("word_48", L.u32()))
    part(L, t, "object", L.game())
    if tv > 0:
        t.fields.append(("word_44", L.u32()))


def t_entity_health(L, t, tv):                          # 0x104270
    t.fields.append(("words_44", L.words(2)))
    part(L, t, "object", L.game())


def t_item_held(L, t, tv):                              # 0x103B70
    if tv > 0:
        part(L, t, "object", L.game())


def t_spawn_quota(L, t, tv):                            # 0x1038F0
    part(L, t, "object", L.game())
    t.fields.append(("word_44", L.u32()))


def t_keyval(L, t, tv):                                 # 0x103680
    t.fields.append(("words_40", L.words(4)))


def t_ai_target(L, t, tv):                              # 0x1033C0
    t.fields.append(("word_4C", L.s32()))
    part(L, t, "object", L.game())
    part(L, t, "second", L.game())


def t_weapon_hit(L, t, tv):                             # 0xA0E70
    part(L, t, "object", L.game())
    t.fields.append(("words_44", L.words(2)))


def t_entity_to_entity(L, t, tv):                       # 0x1028C0
    part(L, t, "object", L.game())
    part(L, t, "second", L.game())
    t.fields.append(("float_48", L.f32()))


def t_random(L, t, tv):                                 # 0x102540
    t.fields.append(("word_40", L.u32()))


def t_los(L, t, tv):                                    # 0x102350
    part(L, t, "object", L.game())
    part(L, t, "second", L.game())


def action(L, t, fv, tv):
    """AIEnabledAction_Load (0x39B10): every action's common part."""
    L.add(t)
    t.name = L.text(64)
    part(L, t, "object_48", L.game())
    part(L, t, "object_4C", L.game())
    part(L, t, "object_44", L.game())


def action_own(read):
    def load(L, t, fv, tv):
        action(L, t, fv, tv)
        read(L, t, tv)
    return load


def a_none(L, t, tv):
    pass


def a_value(L, t, tv):                                  # 0xE0E80
    t.fields.append(("value", L.s32()))


def a_value_v1(L, t, tv):                               # 0xDF500
    if tv >= 1:
        t.fields.append(("value", L.s32()))


def a_target(L, t, tv):                                 # 0xDFFA0
    part(L, t, "target", L.game())


def a_assign_path(L, t, tv):                            # 0xE4220
    if tv >= 1:
        part(L, t, "path", L.game())
        if tv > 3:
            for i in range(4):
                part(L, t, "path_%d" % (i + 1), L.game())
    if tv > 2:
        t.fields.append(("word_54", L.u32()))
    if tv > 3:
        t.fields.append(("words_60", L.words(4)))
        t.fields.append(("words_58", L.words(5)))


def a_log_text(L, t, tv):                               # 0xE3C90
    if tv >= 1:
        t.fields.append(("text", L.u32()))              # +0x50: the text's number in the string table
        if tv > 1:
            t.fields.append(("voice", L.text(0x104)))   # +0x54
            part(L, t, "voice_object", L.vc())          # +0x158
    else:
        t.fields.append(("text_name", L.text(0x100)))
    if tv >= 3:
        t.fields.append(("word_15C", L.u32()))


def a_orient_spawn(L, t, tv):                           # 0xE34C0
    if tv == 1:
        t.fields.append(("vector", L.floats(3)))
        t.fields.append(("word_54", L.u32()))
    elif tv > 1:
        t.fields.append(("words_50", L.words(2)))


def a_post_objective(L, t, tv):                         # 0xE2FB0
    f = t.fields
    f.append(("word_50", L.u32()))
    f.append(("word_5C", L.u32()))
    if tv < 3:
        f.append(("text_a", L.text(0x80)))
        if tv >= 1:
            f.append(("text_b", L.text(0x80)))
    if tv >= 2:
        f.append(("word_60", L.u32()))
    if tv >= 3:
        f.append(("texts", L.words(2)))                 # +0x54, +0x58: numbers in the string table
    if tv >= 4:
        f.append(("voice", L.text(0x104)))              # +0x64
        part(L, t, "voice_object", L.vc())              # +0x168
    if tv >= 5:
        f.append(("word_16C", L.u32()))


def a_complete_objective(L, t, tv):                     # 0xE2C40
    f = t.fields
    f.append(("words_50", L.words(4)))
    if tv >= 1:
        f.append(("text", L.u32()))                     # +0x64
    else:
        f.append(("text_name", L.text(0x80)))
    if tv > 1:
        f.append(("word_60", L.u32()))
    if tv > 2:
        f.append(("voice", L.text(0x104)))              # +0x68
        part(L, t, "voice_object", L.vc())              # +0x16C
    if tv >= 4:
        f.append(("word_170", L.u32()))


def a_timer(L, t, tv):                                  # 0xE28E0
    t.fields.append(("words_50", L.words(5)))
    if tv >= 1:
        t.fields.append(("word_64", L.u32()))


def a_freeze(L, t, tv):                                 # 0xE2630
    if tv > 0:
        t.fields.append(("value", L.u32()))


def a_load_map(L, t, tv):                               # 0xE2220
    t.fields.append(("map", L.text(64)))


def a_objective_pos(L, t, tv):                          # 0xE1DB0
    t.fields.append(("word_50", L.u32()))
    t.fields.append(("point", L.floats(3)))


def a_ai_channel(L, t, tv):                             # 0xE1BD0
    t.fields.append(("channel", L.u32()))
    if tv > 0:
        t.fields.append(("word_54", L.u32()))


def a_bfo(L, t, tv):                                    # 0xE17D0
    part(L, t, "object", L.game())
    t.fields.append(("word_54", L.u32()))
    if tv > 1:
        t.fields.append(("word_58", L.u32()))


def a_keyval(L, t, tv):                                 # 0xDFCE0
    t.fields.append(("words_50", L.words(7)))
    if tv >= 2:
        t.fields.append(("word_68", L.u32()))


def a_music(L, t, tv):                                  # 0xDFA00
    if tv > 1:
        t.fields.append(("value", L.u32()))


def a_move_player(L, t, tv):                            # 0xDF190
    t.fields.append(("point", L.floats(3)))             # +0x50
    L.words(6)                                          # FileReadTriples is asked for three: the heading and
    if tv > 1:                                          # five words past the object, as they were written
        t.fields.append(("heading", L.f32()))           # +0x5C, in degrees


def a_rumble(L, t, tv):                                 # 0xDEE40
    t.fields.append(("words_54", L.words(3)))


LOADERS = {
    1: player, 2: entity, (2, 33): vehicle, (2, 36): vehicle, (2, 37): vehicle, (2, 48): vehicle,
    (5, 0): building, (5, 1): object_swap, 6: item, (6, 4): puny_human, 7: component,
    (8, 0): trigger, (8, 7): trigger, (8, 1): trigger_own(t_player_proximity),
    (8, 2): trigger_own(t_objective_state), (8, 3): trigger_own(t_entity_proximity),
    (8, 4): trigger_own(t_on_time), (8, 5): trigger_own(t_five), (8, 6): trigger_own(t_entity_health),
    (8, 8): trigger_own(t_item_held), (8, 9): trigger_own(t_spawn_quota), (8, 10): trigger_own(t_keyval),
    (8, 11): trigger_own(t_ai_target), (8, 12): trigger_own(t_weapon_hit),
    (8, 13): trigger_own(t_entity_to_entity), (8, 14): trigger_own(t_random), (8, 15): trigger_own(t_los),
    (9, 0): action_own(a_value_v1), (9, 31): action_own(a_value_v1), (9, 1): action,
    (9, 2): action_own(a_assign_path), (9, 3): action_own(a_log_text), (9, 4): action_own(a_orient_spawn),
    (9, 6): action_own(a_post_objective), (9, 7): action_own(a_complete_objective),
    (9, 8): action_own(a_timer), (9, 9): action_own(a_freeze), (9, 10): action_own(a_load_map),
    (9, 11): action, (9, 17): action, (9, 12): action_own(a_objective_pos),
    (9, 13): action_own(a_ai_channel), (9, 15): action_own(a_bfo), (9, 22): action_own(a_target),
    (9, 25): action_own(a_target), (9, 24): action, (9, 26): action_own(a_keyval),
    (9, 28): action_own(a_music), (9, 32): action_own(a_move_player), (9, 34): action_own(a_rumble),
    (11, 0): folder, (11, 1): stand_in, (11, 2): vc_only, (11, 3): stand_in_mso, (11, 4): helper,
    (11, 5): vc_only, (11, 6): model, (11, 7): vc_only, (11, 8): camera, (11, 9): spline, (11, 10): point,
    (11, 11): vc_only, (11, 12): vc_only, (11, 13): sky, (11, 14): path, (11, 15): spawn_group,
    (11, 16): water, (11, 17): cinema, (11, 18): link, (11, 19): sound, (11, 21): collision_volume,
    (11, 22): node22, (11, 23): node23, (11, 24): civilians, (11, 25): keyval,
}
for _n in (5, 14, 16, 18, 19, 20, 21, 23, 29, 30, 35, 36):
    LOADERS[(9, _n)] = action_own(a_value)


# ---- printing

def show(v):
    if isinstance(v, float):
        return "%g" % v
    if isinstance(v, tuple) and v and all(isinstance(x, float) for x in v):
        return "(" + ", ".join("%g" % x for x in v) + ")"
    if isinstance(v, (Thing, Ref)):
        return target(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(show(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (k, show(x)) for k, x in v.items()) + "}"
    return repr(v) if isinstance(v, str) else str(v)


def target(v):
    """A reference told: the object's number and what it is."""
    if v is None:
        return "none"
    t = v.thing if isinstance(v, Ref) else v
    if t is None:
        return "#%d (not made yet)" % v.index
    return "#%d %s" % (t.index if t.index is not None else -1, t.label())


def tree(L, fields=False, out=sys.stdout):
    def line(t, depth, what):
        mark = "" if t.ok else "   !! " + t.note
        out.write("%s%s#%s %s%s\n" % ("  " * depth, what + ": " if what and what != "child" else "",
                                     t.index, t.label(), mark))
        if fields:
            for k, v in t.fields:
                out.write("%s    %s = %s\n" % ("  " * depth, k, show(v)))
        for kind, child in t.parts:
            if isinstance(child, Thing):
                if child.kind == "game":
                    line(child, depth + 1, kind)
                else:
                    out.write("%s%s: #%s %s\n" % ("  " * (depth + 1), kind, child.index, child.label()))
            elif isinstance(child, Ref):
                out.write("%s%s -> %s\n" % ("  " * (depth + 1), kind, target(child)))
    out.write("%s: gcLevel version %d, %d bytes; its vcPak holds %d engine objects\n" % (
        os.path.basename(L.path), L.level.get("version"), len(L.d),
        sum(1 for o in L.objects[:L.root.index if L.root.index else None] if o.kind == "vc") - 2))
    for k, v in L.settings:
        if k != "words_90" or fields:
            out.write("  %s = %s\n" % (k, show(v)))
    line(L.root, 0, "")


def logic(L, out=sys.stdout):
    """The level's components: each entry's triggers and actions, and what each is tied to."""
    def told(t, depth):
        refs = ", ".join("%s -> %s" % (k, target(c)) for k, c in t.parts if c is not None and
                         not (isinstance(c, Thing) and c.kind == "game" and c.family in (8, 9)))
        own = ", ".join("%s %s" % (k, show(v)) for k, v in t.fields if k not in ("family_version", "version"))
        out.write("%s#%s %s  %s%s\n" % ("    " * depth, t.index, t.label(), own, "; " + refs if refs else ""))
        for k, c in t.parts:
            if isinstance(c, Thing) and c.kind == "game" and c.family in (8, 9):
                told(c, depth + 1)
    for t, depth, parent in L.walk():
        if t.family != 7:
            continue
        out.write("== #%s %s (in %s), object -> %s\n" % (t.index, t.label(), parent.label() if parent else "-",
                                                         target(dict(t.parts).get("object"))))
        for n, e in enumerate(t.get("entries")):
            if not e["used"]:
                continue
            out.write("  entry %d \"%s\"%s\n" % (n, e["name"], "" if "word_44" not in e else " (%d)" % e["word_44"]))
            for what in ("triggers", "actions"):
                for c in e[what]:
                    if isinstance(c, Thing):
                        told(c, 1)
                    elif isinstance(c, Ref):
                        out.write("    %s -> %s\n" % (what[:-1], target(c)))


def check(out=sys.stdout):
    """The 59 levels: every record by type, how many end where their header says, and the nodes the
    pattern of tools/level_names.py finds against the ones this reader walks."""
    pattern = re.compile(rb"\xff\xff\xff\xff\x0b\x00\x00\x00(.)\x00\x00\x00", re.S)
    count, wrong, by_pattern, levels = collections.Counter(), collections.Counter(), collections.Counter(), 0
    unread = collections.Counter()
    notes = collections.defaultdict(collections.Counter)
    for path in sorted(glob.glob(os.path.join(LEVELS, "*.lvl"))):
        L = Level(path)
        levels += 1
        for t in L.records:
            count[(t.family, t.type)] += 1
            if not t.ok:
                wrong[(t.family, t.type)] += 1
                notes[(t.family, t.type)][os.path.basename(path)] += 1
        d = L.d
        for m in pattern.finditer(d):                   # level_names.py's nodes()
            at = m.start() + 0x4C
            name = d[at:d.find(b"\0", at, at + 80)]
            if 2 < len(name) < 64 and all(32 <= c < 127 for c in name) and at + 0x40 + 160 <= len(d):
                by_pattern[m.group(1)[0]] += 1
        if L.root is None or L.root.end != L.level.end or L.trailer is None:
            out.write("%s: the root does not end with the gcLevel\n" % os.path.basename(path))
    out.write("%d levels, %d records, %d not read to their end\n" % (levels, sum(count.values()), sum(wrong.values())))
    for key in sorted(count):
        extra = ""
        if key[0] == 11:
            extra = "   level_names.py's pattern: %d" % by_pattern[key[1]]
            if by_pattern[key[1]] != count[key]:
                extra += "  (differs)"
        out.write("%-9s %3d %-32s %6d%s%s\n" % (FAMILY.get(key[0], "?"), key[1], TYPED.get((FAMILY.get(key[0]), key[1]), "-"),
                                               count[key], "  WRONG %d (%s)" % (wrong[key], ", ".join(list(notes[key])[:4])) if wrong[key] else "", extra))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if "--check" in flags:
        return check()
    if not args:
        sys.exit(__doc__)
    name = args[0]
    path = name if os.path.exists(name) else os.path.join(LEVELS, name if name.endswith(".lvl") else name + ".lvl")
    L = Level(path)
    if "--logic" in flags:
        logic(L)
    else:
        tree(L, fields="--fields" in flags)
    if L.bad:
        sys.stderr.write("%d records not read to their end\n" % len(L.bad))


if __name__ == "__main__":
    main()
