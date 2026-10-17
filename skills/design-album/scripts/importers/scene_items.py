# -*- coding: utf-8 -*-
"""Furniture and decor of a 3D scene -> items for the sheets «Мебель и изделия индивидуального изготовления».

    collect(rows, meshes, k, d, out_dir) -> (items, signs)

A unit is the highest group under the scene shell (a group larger than 6 m holds the building, its children are units
of their own) or a free object. Free objects resting on / touching one another (a bench base with its cushions and the
back cushion) are one unit; groups stacked one on another with the same footprint (an upper and a lower part of one
shelving) are one unit. A group holding several pieces of different make (a table with its chairs) is split.

Not furniture (dropped): lights, plants, decor and books standing on furniture, catering equipment, sanitary ware,
doors, curtains, ducts; walls and columns (h >= 2.8 m); thin panels (partitions, claddings); planes; things hanging
under the ceiling; the bar counter (it has its own elevation sheet).
Planes with an unevaluated Shell modifier are boards: they get a 20 mm thickness.
Identical units (same parts, same size) are one item with a quantity and the list of places.
Text objects (sign lettering: spline geometry is not readable) are returned as `signs` evidence.
"""
import math
import os
import pickle
import re

import numpy as np

SHELL_GROUP = 6000.0
SKIP = re.compile(
    r"(?i)arkoslight|light|lamp|sconce|chandelier|pendant|spot|track|plant|palm|ficus|pot\b|pot |ivy|licuala|howea|"
    r"monstera|flower|vase|decorative_set|airpod|cup|coffee_shop|bar_counter|mazzer|victoria|arduino|hicold|fridge|"
    r"conditioner|cassette|duct|diffuser|holder|tube|toilet|sink|basin|faucet|mixer|wc\b|urinal|accessor|paper|"
    r"brush|bin\b|pedal|mirror|door|curtain|blind|carpet|rug|camera|cam\b|target|donel|grille|vent|soil|branch|"
    r"leaf|leaves|tree|bush")
PROP = re.compile(r"(?i)book(?!shel|case)|vase|frame|photo|foto|sleeve|candle|decor|statue|sculpt|cup|bottle|plate|airpod")
SOFT_MAT = re.compile(r"(?i)sofa|fabric|textile|velvet|boucle|linen|flax|cushion|pillow|upholst|leather|ткань|обив")


def _num(s):
    return re.sub(r"[\s_\-.#]*\d+$", "", s or "").strip()


def _box(v):
    return v.min(0), v.max(0)


def _thicken(v, faces, t=20.0):
    """A plane (Shell modifier not evaluated) -> a board t thick, grown to the side its faces look at (a shelf plane
    stays the top of its board)."""
    lo, hi = _box(v)
    ax = int(np.argmin(hi - lo))
    f0 = faces[0]
    p = v[f0]
    q = np.roll(p, -1, axis=0)
    nrm = np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])), np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                    np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])
    sgn = 1.0 if nrm[ax] >= 0 else -1.0
    n = len(v)
    v2 = v.copy()
    v2[:, ax] += sgn * t
    out_f = [list(reversed(f)) for f in faces] + [[i + n for i in f] for f in faces]
    edges = {}
    for f in faces:
        for a, b in zip(f, f[1:] + f[:1]):
            key = (min(a, b), max(a, b))
            edges[key] = edges.get(key, 0) + 1
    for (a, b), c in edges.items():
        if c == 1:
            out_f.append([a, b, b + n, a + n])
    return np.vstack([v, v2]), out_f


def _box_primitive(r):
    """Box primitive with readable parameters (footprint + z range, mm) -> (verts, faces)."""
    if r.get("class") != "Box" or not r.get("footprint") or r.get("z0") is None:
        return None
    if any(not re.search(r"(?i)uvw|unwrap|material", m) for m in r.get("mods") or []):
        return None                                   # an edited box is not its parameters any more
    fp = r["footprint"]
    z0, z1 = float(r["z0"]), float(r["z1"])
    if len(fp) != 4 or z1 - z0 < 1:
        return None
    v = np.array([(x, y, z0) for x, y in fp] + [(x, y, z1) for x, y in fp], float)
    f = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return v, [(0, x) for x in f]


class Part:
    def __init__(self, row, v, faces):
        self.name = row.get("name") or ""
        self.row = row
        self.mats = list(row.get("materials") or ([row["material"]] if row.get("material") else []))
        self.cls = row.get("class") or ""
        self.mods = row.get("mods") or []
        self.v = v
        self.f = [list(f) for _, f in faces] if faces and isinstance(faces[0], tuple) else [list(f) for f in (faces or [])]
        lo, hi = _box(v)
        self.lo, self.hi = lo, hi
        self.flat = float(min(hi - lo)) < 3.0
        big = float(np.prod(sorted(hi - lo)[1:])) > 6e6
        if self.flat and self.f and "FloorGenerator" not in self.mods and not big:
            self.v, self.f = _thicken(v, self.f)
            self.lo, self.hi = _box(self.v)
            self.flat = False
        self.prop = bool(PROP.search(self.name))
        self.nv = int(len(v))

    @property
    def rect(self):
        return (float(self.lo[0]), float(self.lo[1]), float(self.hi[0]), float(self.hi[1]))


def _ov(a, b):
    """overlap area of two rects / area of the smaller"""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    sa = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    sb = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / min(sa, sb)


def _gap(a, b):
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


class Unit:
    def __init__(self, src, parts):
        self.src = src
        self.parts = [p for p in parts if not p.flat]
        self.ok = bool(self.parts)
        if self.ok:
            self._bounds(False)

    def _bounds(self, clean=False):
        body = [p for p in self.parts if not p.prop] or self.parts
        # a part whose broken box sticks out > 600 mm beyond the others and is mostly outside them (unevaluated
        # modifier) is dropped - once, on the finished unit (a long bench base is not «broken» half-way through merging)
        if clean and len(body) > 2:
            keep = []
            for p in body:
                others = [q for q in body if q is not p]
                lo = np.min([q.lo for q in others], 0)
                hi = np.max([q.hi for q in others], 0)
                out = max(float(np.max(lo[:2] - p.lo[:2])), float(np.max(p.hi[:2] - hi[:2])))
                a_p = max(1.0, float(np.prod(p.hi[:2] - p.lo[:2])))
                ix = max(0.0, min(p.hi[0], hi[0]) - max(p.lo[0], lo[0]))
                iy = max(0.0, min(p.hi[1], hi[1]) - max(p.lo[1], lo[1]))
                if out > 600 and ix * iy / a_p < 0.5 and float(np.prod(hi[:2] - lo[:2])) >= 0.6 * a_p:
                    continue
                keep.append(p)
            dropped = [p for p in body if p not in keep]
            self.parts = [p for p in self.parts if p not in dropped]
            body = keep
        self.body = body
        self.lo = np.min([p.lo for p in body], 0)
        self.hi = np.max([p.hi for p in body], 0)
        self.rect = (float(self.lo[0]), float(self.lo[1]), float(self.hi[0]), float(self.hi[1]))
        self.h = float(self.hi[2] - self.lo[2])
        self.z0 = float(self.lo[2])

    @property
    def names(self):
        return [p.name for p in self.parts]

    @property
    def mats(self):
        out = []
        for p in self.parts:
            for m in p.mats:
                if m and m not in out:
                    out.append(m)
        return out

    def merge(self, other):
        self.parts += other.parts
        if not self.src.startswith("+"):
            self.src = self.src
        self.src = "%s + %s" % (self.src, other.src) if other.src not in self.src else self.src
        self._bounds(False)


def _top_groups(rows):
    by = {r["name"]: r for r in rows if r.get("name")}
    kids = {}
    for r in rows:
        if r.get("parent"):
            kids.setdefault(r["parent"], []).append(r)
    box = {}

    def gbox(n, depth=0):
        if n in box:
            return box[n]
        b = None
        r = by.get(n)
        if r is not None and r.get("bbox"):
            b = [list(r["bbox"][0]), list(r["bbox"][1])]
        for c in kids.get(n, []):
            if depth > 12:
                break
            cb = gbox(c["name"], depth + 1)
            if cb:
                b = cb if b is None else [[min(b[0][i], cb[0][i]) for i in range(3)], [max(b[1][i], cb[1][i]) for i in range(3)]]
        box[n] = b
        return b

    def big(n):
        b = gbox(n)
        return b is not None and max(b[1][0] - b[0][0], b[1][1] - b[0][1]) > SHELL_GROUP

    def root(r):
        cur, seen = r, 0
        while cur.get("parent") and cur["parent"] in by and not big(cur["parent"]) and seen < 12:
            cur = by[cur["parent"]]
            seen += 1
        return cur["name"]
    return root, kids, by


def _split(parts):
    """Pieces of a group: parts nested in one another (plan) form a piece; pieces touching with the same material are
    one assembled piece. -> [[parts]]"""
    cl = []
    for p in sorted(parts, key=lambda q: -(q.hi[0] - q.lo[0]) * (q.hi[1] - q.lo[1])):
        for c in cl:
            if any(_ov(p.rect, q.rect) >= 0.6 for q in c):
                c.append(p)
                break
        else:
            cl.append([p])
    merged = True
    while merged and len(cl) > 1:
        merged = False
        for i in range(len(cl)):
            for j in range(i + 1, len(cl)):
                mi = {m for p in cl[i] for m in p.mats}
                mj = {m for p in cl[j] for m in p.mats}
                touch = min(_gap(a.rect, b.rect) for a in cl[i] for b in cl[j]) <= 30
                same = len(mi & mj) > 0
                stems_i = {_num(p.name) for p in cl[i]}
                stems_j = {_num(p.name) for p in cl[j]}
                if touch and same and not ({s for s in stems_i | stems_j if re.search(r"(?i)table|стол", s)}
                                           and (stems_i != stems_j)):
                    cl[i] += cl[j]
                    del cl[j]
                    merged = True
                    break
            if merged:
                break
    return cl


def _skip_unit(u, walls_rects, counters):
    nm = " ".join([u.src] + u.names)
    body = [p for p in u.parts if not p.prop]
    if not body:
        return "props"
    if sum(1 for p in u.parts if SKIP.search(p.name) or SKIP.search(u.src)) >= 0.5 * len(u.parts):
        return "not furniture (%s)" % nm[:40]
    w, d = u.hi[0] - u.lo[0], u.hi[1] - u.lo[1]
    if max(w, d) > SHELL_GROUP or u.h >= 2800:
        return "wall / column"
    if max(w, d, u.h) <= 300 or w * d < 40000:
        return "small"
    if min(w, d) < 80 and u.h < 150:
        return "trim / rail"
    if u.z0 > 1200:
        return "hangs high"
    if u.hi[2] <= 30 and u.h <= 60:              # top at the floor: a covering / inlay (floors), not a podium (L-112)
        return "in the floor"
    thin = min(w, d)
    nv = sum(p.nv for p in body)
    if thin <= 150 and max(w, d) >= 900 and u.h >= 900 and nv <= 40:
        return "panel"
    if u.h >= 2000 and thin <= 350:
        return "door / panel"
    if counters:
        from shapely.geometry import box
        b = box(*u.rect)
        if any(b.intersection(c).area > 0.3 * max(1.0, b.area) for c in counters):
            return "counter"
    return None


def _orient(u, walls_rects):
    """Angle of the long side and the front direction (away from the nearest wall): (theta, front_sign)."""
    from shapely.geometry import MultiPoint, Point, box
    pts = np.vstack([p.v[:, :2] for p in u.body])
    if len(pts) > 4000:
        pts = pts[np.linspace(0, len(pts) - 1, 4000).astype(int)]
    mrr = MultiPoint([tuple(q) for q in pts]).minimum_rotated_rectangle
    th = 0.0
    if mrr.geom_type == "Polygon":
        cs = list(mrr.exterior.coords)
        e1 = (cs[1][0] - cs[0][0], cs[1][1] - cs[0][1])
        e2 = (cs[2][0] - cs[1][0], cs[2][1] - cs[1][1])
        l1, l2 = math.hypot(*e1), math.hypot(*e2)
        e = e1 if l1 >= l2 else e2
        if max(l1, l2) > 1.12 * max(1.0, min(l1, l2)):
            th = math.degrees(math.atan2(e[1], e[0]))
            th = (th + 90) % 180 - 90
            if abs(abs(th) - 90) < 3:
                th = 90.0
            elif abs(th) < 3:
                th = 0.0
    c = ((u.lo[0] + u.hi[0]) / 2.0, (u.lo[1] + u.hi[1]) / 2.0)
    a = math.radians(th)
    ny = (-math.sin(a), math.cos(a))           # local +y in the world
    depth = abs((u.hi[0] - u.lo[0]) * math.sin(a)) + abs((u.hi[1] - u.lo[1]) * math.cos(a))
    walls = [box(*r) for r in walls_rects]
    sign = 1

    def near(s):
        p = Point(c[0] + s * ny[0] * (depth / 2 + 250), c[1] + s * ny[1] * (depth / 2 + 250))
        return min([w.distance(p) for w in walls] or [9e9])
    if walls:
        dp, dm = near(1), near(-1)
        if dp < 120 and dm >= 120:
            sign = 1                     # wall behind at local +y: front faces -y (the viewer of the front view)
        elif dm < 120 and dp >= 120:
            sign = -1
    return th, sign


def _local(u, th, sign):
    a = math.radians(th)
    R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])       # world -> local (rotate by -th)
    if sign < 0:
        R = -R                                                                      # 180 degrees: the wall goes to +y
    c = np.array([(u.lo[0] + u.hi[0]) / 2.0, (u.lo[1] + u.hi[1]) / 2.0])
    out = []
    for p in u.parts:
        v = p.v.copy()
        v[:, :2] = (v[:, :2] - c) @ R.T
        v[:, 2] -= u.z0
        out.append(v)
    body_idx = [i for i, p in enumerate(u.parts) if p in u.body]
    lo = np.min([out[i].min(0) for i in body_idx], 0)
    hi = np.max([out[i].max(0) for i in body_idx], 0)
    mid = (lo + hi) / 2.0
    for v in out:
        v[:, 0] -= mid[0]
        v[:, 1] -= mid[1]
    size = [round(float(hi[0] - lo[0])), round(float(hi[1] - lo[1])), round(float(hi[2] - lo[2]))]
    return out, size, c


def _sig(u, size):
    nv = sum(p.nv for p in u.parts)
    return (len(u.parts), nv)


def collect(rows, meshes, k, d, out_dir):
    """rows: inventory (mm), meshes: idx -> (name, verts in scene units, faces). -> (items, signs)"""
    root, kids, by = _top_groups(rows)
    walls_rects = [w["rect"] for w in d.get("walls", []) if w.get("rect")]
    counters = []
    from shapely.geometry import Polygon
    for f in d.get("furniture", []):
        if f.get("kind") == "counter" and f.get("poly"):
            counters.append(Polygon(f["poly"]).buffer(0))
    if walls_rects:
        bx0 = min(r[0] for r in walls_rects)
        by0 = min(r[1] for r in walls_rects)
        bx1 = max(r[2] for r in walls_rects)
        by1 = max(r[3] for r in walls_rects)
    else:
        bx0 = by0 = -1e9
        bx1 = by1 = 1e9
    groups = {}
    signs = []
    for r in rows:
        if r.get("class") == "Text":
            g = root(r)
            signs.append(dict(name=r.get("name"), group=g))
        if r.get("idx") not in meshes or not r.get("bbox"):
            box_p = _box_primitive(r)                 # a Box primitive (modifiers not evaluated): from its params
            if box_p is not None:
                v, faces = box_p
                c = v.mean(0)
                if bx0 - 100 <= c[0] <= bx1 + 100 and by0 - 100 <= c[1] <= by1 + 100:
                    groups.setdefault(root(r), []).append(Part(dict(r, bbox=[v.min(0).tolist(), v.max(0).tolist()]), v, faces))
            continue
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        if not (bx0 - 100 <= (x0 + x1) / 2 <= bx1 + 100 and by0 - 100 <= (y0 + y1) / 2 <= by1 + 100):
            continue
        name, vw, faces = meshes[r["idx"]]
        if vw is None or len(vw) == 0:
            continue
        v = np.asarray(vw, float) * k
        groups.setdefault(root(r), []).append(Part(r, v, faces))
    units = []
    for g, parts in groups.items():
        is_group = g in kids
        if is_group:
            whole = Unit(g, list(parts))
            if whole.ok and (_skip_unit(whole, walls_rects, counters) or "").startswith("not furniture"):
                continue                     # a WC group: its flush button is not a piece of furniture
            pieces = _split(parts)
            # a part whose modifiers are not computed lies where its cage lies, not where 3ds Max shows it (a sofa
            # roll stretched by FFD): the designer's group stays one piece then - L-107
            unsure = any(p.row.get("geom") == "unknown" for p in parts)
            if len(pieces) > 1 and not unsure:
                for i, pc in enumerate(pieces):
                    units.append(Unit("%s/%s" % (g, _num(pc[0].name) or pc[0].name), pc))
                continue
        units.append(Unit(g, parts))
    units = [u for u in units if u.ok]
    # free objects touching / resting on each other -> one unit; groups stacked with the same footprint -> one unit
    free = [u for u in units if u.src not in kids and "/" not in u.src]
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(units):
            for b in units[i + 1:]:
                fa, fb = a in free, b in free
                aa = (a.rect[2] - a.rect[0]) * (a.rect[3] - a.rect[1])
                ab = (b.rect[2] - b.rect[0]) * (b.rect[3] - b.rect[1])
                stacked = (_ov(a.rect, b.rect) > 0.8 and min(aa, ab) > 0.6 * max(aa, ab)
                           and (abs(a.hi[2] - b.lo[2]) < 60 or abs(b.hi[2] - a.lo[2]) < 60))
                if (fa and fb and _gap(a.rect, b.rect) <= 60 and a.lo[2] <= b.hi[2] + 60 and b.lo[2] <= a.hi[2] + 60
                        and not _skip_unit(a, walls_rects, counters) and not _skip_unit(b, walls_rects, counters)) \
                        or (not fa and not fb and stacked):
                    a.merge(b)
                    units.remove(b)
                    if b in free:
                        free.remove(b)
                    changed = True
                    break
            if changed:
                break
    for u in units:
        u._bounds(True)
    kept = []
    dbg = os.environ.get("SDA_ITEMS_DEBUG")
    for u in units:
        why = _skip_unit(u, walls_rects, counters)
        if dbg and dbg in u.src:
            print("unit", u.src, [round(x) for x in u.rect], round(u.z0), round(u.h), why)
        if why:
            continue
        kept.append(u)
    # props standing on another unit (decor, books on a shelving) are not items
    final = []
    for u in kept:
        on = [o for o in kept if o is not u and _ov(u.rect, o.rect) > 0.8 and u.z0 > o.z0 + 250
              and (o.hi[0] - o.lo[0]) * (o.hi[1] - o.lo[1]) >= (u.hi[0] - u.lo[0]) * (u.hi[1] - u.lo[1])
              and (u.z0 < o.hi[2] - 30 or abs(u.z0 - o.hi[2]) <= 30)]      # inside it or resting on its top
        if on and u.z0 > 300:
            if dbg and dbg in u.src:
                print("on", u.src, [o.src for o in on])
            continue
        final.append(u)
    # identical units -> one item
    items = []
    mdir = os.path.join(out_dir, "items")
    os.makedirs(mdir, exist_ok=True)
    for u in sorted(final, key=lambda q: (q.rect[0], q.rect[1])):
        th, sign = _orient(u, walls_rects)
        vs, size, c = _local(u, th, sign)
        sig = _sig(u, size)
        for it in items:
            if it["_sig"] == sig and abs(it["size"][2] - size[2]) <= 30:      # same mesh (rotation changes the box)
                it["places"].append([round(c[0]), round(c[1]), round(th + (180 if sign < 0 else 0)) % 360])
                it["qty"] += 1
                if size[0] * size[1] < it["size"][0] * it["size"][1] - 1:       # the tightest box is the true size
                    it["size"] = size
                    it["_mesh"] = (u, vs)
                break
        else:
            iid = "u%d" % (len(items) + 1)
            items.append(dict(id=iid, src=u.src, parts=sorted(set(_num(n) or n for n in u.names))[:12], mats=u.mats[:12],
                              size=size, qty=1, z0=round(u.z0), places=[[round(c[0]), round(c[1]), round(th + (180 if sign < 0 else 0)) % 360]],
                              _sig=sig, _mesh=(u, vs)))
            if any(any("решётке последнего FFD" in n for n in (p.row.get("geom_notes") or [])) for p in u.body):
                items[-1]["outline_only"] = True           # its shape is a lattice box, not the piece (L-107)
    for it in items:
        u, vs = it.pop("_mesh")
        # sound: the mesh is the scene's own (computed modifier stack, counts checked) - big faces are real faces
        mesh = dict(size=it["size"], parts=[dict(name=p.name, mats=p.mats, cls=p.cls, mods=p.mods, prop=p.prop and p not in u.body,
                                                 v=vs[i].astype(np.float32), f=p.f,
                                                 sound=p.row.get("geom") in ("replayed", "exact", "export"))
                                            for i, p in enumerate(u.parts)])
        pickle.dump(mesh, open(os.path.join(mdir, "%s.pkl" % it["id"]), "wb"))
    pre = "import/" if os.path.basename(os.path.abspath(out_dir)) == "import" else ""
    for it in items:
        it.pop("_sig", None)
        it["mesh"] = "%sitems/%s.pkl" % (pre, it["id"])
    return items, signs


LIGHT_ITEM = re.compile(r"(?i)chandelier|люстр|sconce|\bбра\b|eichholtz|tissot|pendant|подвесн")
MAX_FACES = 40000


def collect_lights(rows, meshes, k, d, out_dir, n0=0):
    """Decorative fixtures that get a sketch of their own: chandeliers (a body 450+ across hanging under the ceiling)
    and wall lights (sconces). Meshes of hundreds of thousands of faces (a fringe of chains) are thinned to
    MAX_FACES for the views. -> items with kind_hint 'chandelier' | 'sconce'."""
    root, kids, by = _top_groups(rows)
    walls = [w["rect"] for w in d.get("walls", []) if w.get("rect")]
    groups = {}
    for r in rows:
        txt = " ".join([r.get("name") or "", r.get("parent") or ""] + list(r.get("materials") or []))
        if not LIGHT_ITEM.search(txt) or r.get("idx") not in meshes or not r.get("bbox"):
            continue
        groups.setdefault(root(r), []).append(r)
    units = []
    for g, rs in groups.items():
        lo = np.min([np.array(r["bbox"][0], float) for r in rs], 0)
        hi = np.max([np.array(r["bbox"][1], float) for r in rs], 0)
        size = hi - lo
        plan = float(max(size[0], size[1]))
        c = ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0)
        near = min([_gap((lo[0], lo[1], hi[0], hi[1]), w) for w in walls] or [9e9])
        if plan >= 450 and size[2] >= 250 and lo[2] >= 1200:
            kind = "chandelier"
        elif lo[2] >= 900 and hi[2] <= 2700 and plan <= 700 and near <= 150:
            kind = "sconce"
        else:
            continue
        units.append((g, rs, lo, hi, c, kind))
    items = []
    mdir = os.path.join(out_dir, "items")
    os.makedirs(mdir, exist_ok=True)
    pre = "import/" if os.path.basename(os.path.abspath(out_dir)) == "import" else ""
    for g, rs, lo, hi, c, kind in sorted(units, key=lambda u: (u[4][0], u[4][1])):
        th = 0.0
        if kind == "sconce" and walls:              # the wall behind it at local +y
            from shapely.geometry import Point, box
            p = Point(c)
            w = min(walls, key=lambda r: box(*r).distance(p))
            q = box(*w).exterior.interpolate(box(*w).exterior.project(p))
            th = math.degrees(math.atan2(q.y - c[1], q.x - c[0])) - 90.0
        a = math.radians(th)
        R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
        nf = sum(len(meshes[r["idx"]][2] or []) for r in rs)
        step = max(1, int(math.ceil(nf / float(MAX_FACES))))
        parts = []
        for r in rs:
            name, vw, faces = meshes[r["idx"]]
            v = np.asarray(vw, float) * k
            v[:, :2] = (v[:, :2] - np.array(c)) @ R.T
            v[:, 2] -= lo[2]
            fl = [list(f[1] if isinstance(f, tuple) else f) for f in (faces or [])][::step]
            parts.append(dict(name=r.get("name") or "", mats=list(r.get("materials") or []), cls=r.get("class") or "",
                              mods=r.get("mods") or [], prop=False, v=v.astype(np.float32), f=fl))
        allv = np.vstack([p["v"] for p in parts])
        mid = (allv.min(0) + allv.max(0)) / 2.0
        for p in parts:
            p["v"][:, 0] -= mid[0]
            p["v"][:, 1] -= mid[1]
        allv = np.vstack([p["v"] for p in parts])
        size = [round(float(np.ptp(allv[:, i]))) for i in range(3)]
        sig = (len(parts), sum(len(p["v"]) for p in parts), kind)
        place = [round(c[0]), round(c[1]), round(th) % 360]
        for it in items:
            if it["_sig"] == sig and all(abs(a_ - b_) <= 30 for a_, b_ in zip(it["size"], size)):
                it["places"].append(place)
                it["qty"] += 1
                break
        else:
            iid = "l%d" % (n0 + len(items) + 1)
            pickle.dump(dict(size=size, parts=parts), open(os.path.join(mdir, "%s.pkl" % iid), "wb"))
            items.append(dict(id=iid, src=g, parts=sorted(set(_num(r.get("name")) or r.get("name") for r in rs))[:12],
                              mats=sorted(set(m for r in rs for m in (r.get("materials") or [])))[:12], size=size, qty=1,
                              z0=round(float(lo[2])), places=[place], kind_hint=kind, mesh="%sitems/%s.pkl" % (pre, iid),
                              _sig=sig))
    for it in items:
        it.pop("_sig", None)
    return items
