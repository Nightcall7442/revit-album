# -*- coding: utf-8 -*-
"""3D scene objects -> draft project.json (walls, openings, furniture, named objects for room naming).

Input: objects = [dict(name, parent, cls, nverts, rect=(x0, y0, x1, y1) mm, z0, z1, flat, mods)] in millimetres.

  walls      thin (60-700 mm) long objects standing on the floor: tall simple meshes, or flat Plane/Box primitives
             extruded by Edit Poly; the group holding most of them is the architectural shell. Curtains, doors,
             mirrors, shelves, glass, furniture are never walls (by name).
  openings   gaps between wall ends (<= 2.6 m, or any length when glazing spans it - a shop front); a door object in
             the gap -> door, glazing -> window, otherwise by position.
  furniture  objects named like toilet / washbasin / fridge / table / chair / sofa / bed ... -> kind + footprint
             (parts of one item merged).
  _objects   names + positions of everything on the floor: autofix names the rooms by what stands in them.
"""
import json
import re

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

NOT_WALL = re.compile(r"curtain|штор|door|двер|mirror|зеркал|shelf|полк|book|glass|стекл|window|окн|wd_|rail|pipe|"
                      r"труб|duct|воздух|light|lamp|свет|plant|palm|tree|ficus|vase|table|стол|chair|стул|sofa|диван|"
                      r"counter|стойк|cabinet|шкаф|tv|screen|frame|рамк|text|camera|cam\b|sun|sky|ground|terrain|"
                      r"environment|floor|пол\b|ceiling|потол|carpet|ковёр|ковер|rug|picture|картин|foto|photo|art",
                      re.I)
DOOR = re.compile(r"door|двер", re.I)
GLAZING = re.compile(r"glass|стекл|window|окн|витраж|glazing|pcube", re.I)

FURN = [  # (regex, kind, display name) - first match wins
    (r"toilet\s*paper|paper\s*holder|brush|ерш|seat\b|seat cover|accessor|\bpos\b|_pos\b|terminal|касс", None, None),
    (r"table.{0,3}chairs?|chairs?.{0,3}table|обеденн\w* групп", "table", "Обеденная группа (стол + стулья)"),
    (r"toilet|унитаз|\bwc\b|closet bowl|urinal|писсуар", "wc", "Унитаз"),
    (r"wash\s*basin|washbasin|basin|раковин|lavabo|vanity|console sink", "basin", "Раковина"),
    (r"shower|душ", "shower", "Душевой поддон"),
    (r"bath\s*tub|bathtub|ванн", "bath", "Ванна"),
    (r"washing machine|washer|стирал", "washer", "Стиральная машина"),
    (r"fridge|refriger|холодил|hicold|freezer|морозил", "fridge", "Холодильник"),
    (r"\bhob\b|stove|cooker|плит[аы]|oven|духов|fryer|фритюр|grill", "hob", "Плита / жарочное"),
    (r"\bsink\b|мойк", "sink", "Мойка"),
    (r"bar\s*counter|counter|стойк|reception|ресепш", "cabinet", "Барная стойка"),
    (r"wardrobe|гардероб|closet", "wardrobe", "Шкаф"),
    (r"\bbed\b|кроват", "bed", "Кровать"),
    (r"sofa|диван|banquette|банкет", "sofa", "Диван"),
    (r"armchair|кресл|swivel chair|lounge", "armchair", "Кресло"),
    (r"chair|стул|stool|табурет", "chair", "Стул"),
    (r"table|стол", "table", "Стол"),
    (r"\btv\b|телевиз", "tv", "Телевизор"),
    (r"shelf|стеллаж|rack", "cabinet", "Стеллаж"),
]
FURN = [(re.compile(rx, re.I), k, n) for rx, k, n in FURN]


def furniture_kind(name):
    for rx, kind, disp in FURN:
        if rx.search(name or ""):
            return kind, disp
    return None, None


def _shellish(o):
    """A simple architectural solid: a flat / extruded primitive, a low-poly mesh, or a Box / Plane primitive whose
    modifiers the reader cannot evaluate (nverts unknown, rect from the primitive's parameters)."""
    if o.get("flat") and o["cls"] in ("Plane", "Box"):
        return True
    if o.get("nverts") is None:
        return o["cls"] in ("Box", "Plane")
    return o["nverts"] <= 64


def _decor(o):
    """Chamfered / smoothed boxes are furniture and decor panels, never the building's walls."""
    return any(re.search(r"chamfer|turbosmooth|meshsmooth|ffd", m, re.I) for m in o.get("mods", []))


def stack_walls(objects, tmin=60, tmax=700):
    """A wall modelled in parts - below the sill, above the window head, a panel - is one wall: thin objects with the
    same orientation, overlapping along >= 70 % and touching across (<= 50 mm) are merged; a vertical gap between
    the parts (>= 100 mm) is a window band (sill, head). Returns new objects (the parts are dropped)."""
    thin = []
    for i, o in enumerate(objects):
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        if 20 <= t <= tmax and L >= 600 and _shellish(o) and not NOT_WALL.search(o["name"] or "") and not _decor(o):
            thin.append((i, o, w >= h))
    used, out, merged_ids = set(), [], set()
    for a in range(len(thin)):
        if a in used:
            continue
        ia, oa, ha = thin[a]
        grp = [a]
        for b in range(a + 1, len(thin)):
            if b in used:
                continue
            ib, ob, hb = thin[b]
            if ha != hb or (oa.get("parent") or "") != (ob.get("parent") or ""):
                continue                         # parts of one wall are siblings (a beam / cabinet is not)
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = oa["rect"], ob["rect"]
            if ha:
                ov = min(ax1, bx1) - max(ax0, bx0)
                gap = max(by0 - ay1, ay0 - by1)
                La, Lb = ax1 - ax0, bx1 - bx0
                ta, tb, tu = ay1 - ay0, by1 - by0, max(ay1, by1) - min(ay0, by0)
            else:
                ov = min(ay1, by1) - max(ay0, by0)
                gap = max(bx0 - ax1, ax0 - bx1)
                La, Lb = ay1 - ay0, by1 - by0
                ta, tb, tu = ax1 - ax0, bx1 - bx0, max(ax1, bx1) - min(ax0, bx0)
            stacked = min(oa["z1"], ob["z1"]) - max(oa["z0"], ob["z0"]) <= 50
            if tu > max(ta, tb) + 50 and not stacked:
                continue                         # a plinth / beam beside the wall would thicken it
            if ov >= 0.7 * min(La, Lb) and gap <= 50:
                grp.append(b)
        if len(grp) < 2:
            continue
        parts = [thin[g][1] for g in grp]
        zs = sorted((p["z0"], p["z1"]) for p in parts)
        z0, z1 = zs[0][0], max(z for _, z in zs)
        if z0 > 300 or z1 - z0 < 2000:
            continue
        band, top = None, zs[0][1]
        for a0, a1 in zs[1:]:
            if a0 - top >= 100 and (band is None or a0 - top > band[1] - band[0]):
                band = (top, a0)
            top = max(top, a1)
        xs0 = min(p["rect"][0] for p in parts)
        ys0 = min(p["rect"][1] for p in parts)
        xs1 = max(p["rect"][2] for p in parts)
        ys1 = max(p["rect"][3] for p in parts)
        # a part under the window standing proud of the wall above it is a ledge (an installation box, a parapet):
        # evidence for the senior; the wall stays the union until the senior decides what the ledge is
        ledges = []
        if band is not None:
            tall = max(parts, key=lambda p: p["z1"] - p["z0"])
            ax = 1 if ha else 0
            lo_, hi_ = tall["rect"][ax], tall["rect"][ax + 2]
            for p in parts:
                if p is tall or p["z1"] > band[0] + 10:
                    continue
                for a_, b_ in ((p["rect"][ax], lo_), (hi_, p["rect"][ax + 2])):
                    if b_ - a_ >= 30:
                        r = list(p["rect"])
                        r[ax], r[ax + 2] = a_, b_
                        wr = [xs0, ys0, xs1, ys1]
                        wr[ax], wr[ax + 2] = lo_, hi_
                        ledges.append(dict(name=p["name"], rect=[round(v) for v in r], z0=round(p["z0"]), z1=round(p["z1"]),
                                           wall_rect=[round(v) for v in wr]))
        out.append(dict(parts[0], name="+".join(p["name"] for p in parts)[:80], rect=(xs0, ys0, xs1, ys1), z0=z0, z1=z1,
                        nverts=8, flat=False, window_band=band, ledges=ledges))
        used.update(grp)
        merged_ids.update(thin[g][0] for g in grp)
    return [o for i, o in enumerate(objects) if i not in merged_ids] + out


def storey_height(objects):
    """Floor-to-slab height of the scene: the tallest simple objects standing on the floor (walls)."""
    hs = sorted((o["z1"] - o["z0"]) for o in objects if o["z0"] <= 300 and _shellish(o) and not o.get("flat")
                and (o["z1"] - o["z0"]) >= 2000)
    return hs[int(0.9 * (len(hs) - 1))] if hs else 2700.0


def wall_candidates(objects, tmin=60, tmax=700, storey=None):
    objects = stack_walls(objects, tmin, tmax)
    storey = storey or storey_height(objects)
    cands = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        column = 150 <= t <= 1200 and L <= 1.6 * t and _shellish(o)      # columns / pilasters close the wall line
        pier = tmin <= t <= tmax and L >= 250 and _shellish(o)           # a short wall piece next to a door
        if not column and not pier and (not (tmin <= t <= tmax) or L < max(3 * t, 600) or L > 60000):
            continue
        if L > 60000 or NOT_WALL.search(o["name"] or "") or _decor(o):
            continue
        if o["z0"] > 300:                     # walls stand on the floor (a lintel / beam above a door is not a wall)
            continue
        hgt = o["z1"] - o["z0"]
        # a wall reaches the slab: a door leaf (2.1-2.2 m) or a cabinet standing in the shell group does not
        tall = hgt >= max(2000, 0.8 * storey)
        extruded = o.get("flat") and any(re.search(r"edit poly|extrude|shell", m, re.I) for m in o.get("mods", []))
        flat_prim = o.get("flat") and o["cls"] in ("Plane", "Box")
        if not (tall or extruded or flat_prim):
            continue
        if not o.get("flat") and (o.get("nverts") or 0) > 500:          # detailed meshes are furniture, not walls
            continue
        if (pier or column) and not (o.get("flat") or (o.get("nverts") or 0) <= 64):
            continue
        cands.append(dict(o, simple=True, pier=pier and L < max(3 * t, 600)))
    from collections import Counter
    groups = Counter(c.get("parent") for c in cands if c.get("parent"))
    shell = groups.most_common(1)[0][0] if groups and groups.most_common(1)[0][1] >= 3 else None
    out = []
    for c in cands:
        if c.get("parent") == shell or (not c["pier"] and (c["z1"] - c["z0"]) >= max(2000, 0.8 * storey)):
            out.append(c)
    # duplicates (a wall and its copy / finish layer): keep the bigger one
    out.sort(key=lambda c: -(c["rect"][2] - c["rect"][0]) * (c["rect"][3] - c["rect"][1]))
    keep = []
    for c in out:
        b = box(*c["rect"])
        if any(b.intersection(box(*k["rect"])).area > 0.8 * b.area for k in keep):
            continue
        keep.append(c)
    return keep, shell


def lintels(objects, storey):
    """Beams above doorways: thin, bottom at 1.8-2.45 m (door head), up to the slab - a door opening is under them.
    Frame beams (bottom ~2.6 m and higher, spanning column to column) are not lintels: see beams()."""
    out = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        t, L = min(x1 - x0, y1 - y0), max(x1 - x0, y1 - y0)
        if 60 <= t <= 700 and 500 <= L <= 3500 and 1800 <= o["z0"] <= 2450 and o["z1"] >= 0.85 * storey \
                and _shellish(o) and not NOT_WALL.search(o["name"] or ""):
            out.append(box(x0, y0, x1, y1))
    return out


def beams(objects, storey):
    """Down-stand beams of a frame building: thin long solids hanging from the slab (bottom >= 2.0 m, below the slab
    by >= 150) -> [(rect, bottom)]. Shown on the ceiling plan; an open ceiling goes round them."""
    out = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        t, L = min(x1 - x0, y1 - y0), max(x1 - x0, y1 - y0)
        if 150 <= t <= 800 and L >= 600 and 2450 < o["z0"] <= storey - 150 and o["z1"] >= storey - 60 \
                and _shellish(o) and not NOT_WALL.search(o["name"] or "") and not _decor(o):
            out.append(([round(v) for v in (x0, y0, x1, y1)], int(round(o["z0"] / 10.0) * 10)))
    return out


def door_objects(objects):
    out = []
    for o in objects:
        if not DOOR.search(o["name"] or "") or re.search(r"handle|ручк|knob|hinge|петл", o["name"] or "", re.I):
            continue
        if o["z1"] - o["z0"] < 1700 or o["z0"] > 300:
            continue
        x0, y0, x1, y1 = o["rect"]
        if max(x1 - x0, y1 - y0) < 500:
            continue
        out.append(dict(name=o["name"], rect=(x0, y0, x1, y1), horiz=(x1 - x0) >= (y1 - y0),
                        h=int(round(min(o["z1"] - o["z0"], 2400) / 50.0) * 50)))
    return out


def facades(objects, walls):
    """Shop fronts / curtain walls: long, tall, thin and detailed (frames, glass) objects that are not curtains or
    furniture -> a wall line with one glazing opening along it."""
    out = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        if not (20 <= t <= 300) or L < 2000 or (o["z1"] - o["z0"]) < 2000 or o["z0"] > 300:
            continue
        if (o.get("nverts") or 0) <= 64 or NOT_WALL.search(o["name"] or ""):
            continue
        b = box(*o["rect"])
        if any(b.intersection(box(*c["rect"])).area > 0.5 * b.area for c in walls):
            continue
        out.append(o)
    return out


def _crosses_walls(r, mass):
    """A footprint split by a wall into two sizeable parts is a broken bounding box (a Symmetry / FFD modifier the
    reader evaluates in the wrong frame), not a real item."""
    if mass is None:
        return False
    b = box(*r)
    rest = b.difference(mass)
    parts = [g for g in (rest.geoms if hasattr(rest, "geoms") else [rest]) if g.area > 0.1 * b.area]
    return len(parts) >= 2


def furniture(objects, rooms_hint=None, walls=None):
    mass = unary_union(walls) if walls else None
    items = []
    for o in objects:
        if o["z0"] > 1500 or (o["z1"] - o["z0"]) < 30:
            continue
        kind, disp = furniture_kind(o["name"])
        if kind and o["z0"] > 600 and kind not in ("basin", "wc", "tv", "sink"):
            continue                              # standing on a counter / hung high: not floor furniture
        if not kind:
            kind, disp = furniture_kind(o.get("parent") or "")
            if not kind:
                continue
        x0, y0, x1, y1 = o["rect"]
        if (x1 - x0) < 150 or (y1 - y0) < 150 or (x1 - x0) * (y1 - y0) > 30e6:
            continue
        if _crosses_walls(o["rect"], mass):
            continue
        items.append(dict(kind=kind, name=disp, rect=[x0, y0, x1, y1], src=o["name"], group=o.get("parent"), z1=o["z1"],
                          z0=o["z0"]))
    # a part with a broken bounding box (Symmetry / FFD evaluated in the wrong frame) sticks out of its siblings far
    # (> 600 mm) and is mostly uncovered by them; a chair beside a table sticks out less, a table inside its chairs not
    by_group = {}
    for it in items:
        if it["group"]:
            by_group.setdefault(it["group"], []).append(it)
    stray = set()
    for grp in by_group.values():
        if len(grp) < 3:
            continue
        for it in grp:
            b = box(*it["rect"])
            near = [o for o in grp if o is not it and box(*o["rect"]).distance(b) < 600]
            if len(near) < 2:
                continue
            others = unary_union([box(*o["rect"]) for o in near])
            ox0, oy0, ox1, oy1 = others.bounds
            x0, y0, x1, y1 = it["rect"]
            out = max(ox0 - x0, oy0 - y0, x1 - ox1, y1 - oy1)
            if b.area > 0 and out > 600 and b.intersection(others).area < 0.5 * b.area:
                stray.add(id(it))
    items = [it for it in items if id(it) not in stray]
    # parts of one item (legs, top, base of one table; a group of meshes) -> one footprint
    merged = []
    for it in sorted(items, key=lambda i: -(i["rect"][2] - i["rect"][0]) * (i["rect"][3] - i["rect"][1])):
        b = box(*it["rect"])
        for m in merged:
            mb = box(*m["rect"])
            same_group = it["group"] and it["group"] == m["group"]
            if m["kind"] == it["kind"] and (b.intersection(mb).area > 0.3 * min(b.area, mb.area) or
                                             (same_group and b.distance(mb) < 50)):
                u = b.union(mb).bounds
                m["rect"] = list(u)
                m["z1"] = max(m["z1"], it["z1"])
                m["z0"] = min(m["z0"], it["z0"])
                break
        else:
            merged.append(dict(it))
    out = []
    for m in merged:
        x0, y0, x1, y1 = [int(round(v / 5.0) * 5) for v in m["rect"]]
        name = m["name"]
        extra = {}
        if m["kind"] == "fridge" and m["z1"] < 1100:
            name = "Холодильный стол"                 # under-counter refrigeration (HICOLD GN ...)
        if m["kind"] == "wc" and m["z0"] >= 40:      # the bowl does not stand on the floor: wall-hung on a frame
            name, extra = "Унитаз подвесной (инсталляция)", dict(hung=True)
        out.append(dict(name=name, kind=m["kind"], poly=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], source=m["src"],
                        check=True, h=int(round(m["z1"] / 10.0) * 10), **extra))
    return out


BAR_HINT = re.compile(r"bar|coffee|кофе|espresso|\bpos\b|_pos\b|barista|cup|mug", re.I)


def counters(objects, furn, walls=None):
    """Counters built from panels (a FloorGenerator / plank front, no name): flat vertical faces 1-1.25 m high on the
    floor + a flat top at the same height. The body runs from the face towards the top, as deep as the equipment
    standing under it (600-1000, default 700). -> [furniture item] (kind 'counter')."""
    faces, tops = [], []
    for o in objects:
        r = o.get("rect")
        if not r or NOT_WALL.search((o.get("name") or "") + " ") and not re.search(r"counter|стойк", o.get("name") or "", re.I):
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if min(w, h) <= 30 and max(w, h) >= 1000 and o["z0"] <= 400 and 850 <= o["z1"] <= 1250:
            faces.append((r, o["z1"], w >= h))
        elif o["z1"] - o["z0"] <= 5 and 850 <= o["z0"] <= 1250 and w >= 500 and h >= 500:
            tops.append((r, o["z0"]))
    bodies = []
    mass = unary_union(walls) if walls else None
    for r, z, horiz in faces:
        top = next((t for t, zt in tops if abs(zt - z) <= 60 and t[0] - 30 <= r[0] and r[2] <= t[2] + 30
                    and t[1] - 30 <= r[1] and r[3] <= t[3] + 30), None)
        if top is None:
            continue
        line = (r[1] + r[3]) / 2.0 if horiz else (r[0] + r[2]) / 2.0
        lo, hi = (top[1], top[3]) if horiz else (top[0], top[2])
        sgn = -1 if abs(hi - line) < abs(line - lo) else 1          # the top lies on this side of the face
        a0, a1 = (r[0], r[2]) if horiz else (r[1], r[3])
        depth = 0.0
        for o in objects:
            q = o.get("rect")
            if not q or o["z0"] > 300 or not 600 <= o["z1"] <= 1300:
                continue
            q0, q1 = (q[1], q[3]) if horiz else (q[0], q[2])
            p0, p1 = (q[0], q[2]) if horiz else (q[1], q[3])
            if min(p1, a1) - max(p0, a0) < 200:
                continue
            near, far = (q0 - line, q1 - line) if sgn > 0 else (line - q1, line - q0)
            if -20 <= near <= 300 and far <= 1100:
                depth = max(depth, far)
        D = min(1000.0, max(600.0, depth)) if depth else 700.0
        if horiz:
            body = box(a0, min(line, line + sgn * D), a1, max(line, line + sgn * D))
        else:
            body = box(min(line, line + sgn * D), a0, max(line, line + sgn * D), a1)
        if horiz:
            fl = [(a0, line), (a1, line)]
        else:
            fl = [(line, a0), (line, a1)]
        bodies.append((body, z, fl))
    if not bodies:
        return []
    u = unary_union([b.buffer(2, join_style=2) for b, _, _ in bodies]).buffer(-2, join_style=2)
    if mass is not None:                       # a panel modelled into the wall: the counter stops at the wall face
        u = u.difference(mass)
    out = []
    pieces = []
    for g in (u.geoms if hasattr(u, "geoms") else [u]):
        if g.interiors:                         # built around columns: the part between the columns is the item
            x0, y0, x1, y1 = g.bounds
            along_y = (y1 - y0) >= (x1 - x0)
            cut = g
            for h in g.interiors:
                hx0, hy0, hx1, hy1 = Polygon(h).bounds
                cut = cut.difference(box(x0 - 1, hy0, x1 + 1, hy1) if along_y else box(hx0, y0 - 1, hx1, y1 + 1))
            parts = list(cut.geoms) if hasattr(cut, "geoms") else [cut]
            pieces.append(max(parts, key=lambda q: q.area))
        else:
            pieces.append(g)
    for g in pieces:
        if g.area < 0.15e6:
            continue
        g = g.simplify(5)
        z = max(zb for b, zb, _ in bodies if b.intersects(g))
        fronts = []
        for b, zb, fl in bodies:
            if not b.intersects(g):
                continue
            seg = LineString(fl).intersection(g.buffer(3))
            if not seg.is_empty and seg.length >= 300:
                cs_ = list(seg.coords) if seg.geom_type == "LineString" else list(max(seg.geoms, key=lambda q: q.length).coords)
                fronts.append([[int(round(cs_[0][0] / 5.0) * 5), int(round(cs_[0][1] / 5.0) * 5)],
                               [int(round(cs_[-1][0] / 5.0) * 5), int(round(cs_[-1][1] / 5.0) * 5)]])
        zone = g.buffer(1500)
        bar = any(BAR_HINT.search((o.get("name") or "") + " " + (o.get("parent") or "")) and o.get("rect")
                  and zone.contains(box(*o["rect"]).centroid) for o in objects)
        under = [f for f in furn if f["kind"] in ("fridge", "cabinet")
                 and box(*_bounds(f["poly"])).intersection(g).area >= 0.5 * box(*_bounds(f["poly"])).area]
        name = ("Барная стойка" if bar else "Стойка") if z >= 1000 else "Тумба h %d (по модели)" % int(round(z / 10.0) * 10)
        if under:
            n = sum(1 for f in under if f["kind"] == "fridge")
            if n:
                name += " (холодильные столы под столешницей ×%d)" % n
        cs = [[int(round(x / 5.0) * 5), int(round(y / 5.0) * 5)] for x, y in list(g.exterior.coords)[:-1]]
        out.append(dict(name=name, kind="counter" if z >= 1000 else "cabinet", poly=cs, source="панели стойки (по модели)",
                        check=True, h=int(round(z / 10.0) * 10), _under=[id(f) for f in under], front=fronts))
    return out


def _bounds(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


LIGHT_NAME = re.compile(r"arkos|light|lamp|светил|люстр|\bбра\b|spot|pendant|chandelier|track|downlight|sconce|luminaire",
                        re.I)
EQUIP = [(re.compile(r"cassette|кассетн|conditioner|кондицион|split|сплит", re.I), "ac", "Кондиционер кассетный"),
         (re.compile(r"espresso|coffee\s*machine|кофемаш|victor|arduino|marzocco|simonelli|nuova", re.I), "coffee",
          "Кофемашина"),
         (re.compile(r"grinder|кофемол", re.I), "grinder", "Кофемолка"),
         (re.compile(r"\bpos\b|_pos\b|terminal|касс", re.I), "pos", "POS-терминал (касса)"),
         (re.compile(r"dish\s*wash|посудомо", re.I), "dishwasher", "Посудомоечная машина"),
         (re.compile(r"ice\s*maker|льдоген", re.I), "ice", "Льдогенератор")]


def _by_parent(objs):
    """Parts of one item (a lamp's body and shade, an AC unit's panel and pipes) -> one record per parent group."""
    groups = {}
    for o in objs:
        key = o.get("parent") or o["name"]
        groups.setdefault(key, []).append(o)
    out = []
    for key, parts in groups.items():
        x0 = min(p["rect"][0] for p in parts)
        y0 = min(p["rect"][1] for p in parts)
        x1 = max(p["rect"][2] for p in parts)
        y1 = max(p["rect"][3] for p in parts)
        out.append(dict(name=parts[0]["name"] if len(parts) == 1 else key, rect=[round(x0), round(y0), round(x1), round(y1)],
                        z0=round(min(p["z0"] for p in parts)),
                        z1=round(max(p["z1"] for p in parts)), parts=len(parts)))
    return out


def lights(objects, zone, storey):
    """Light fixtures of the model: tracks / linear profiles (long thin) and point fixtures, with their heights; the
    classification (recessed / surface / pendant / track spot) needs the rooms' ceilings - senior.lighting_from_model.
    Fixtures outside the plan or above the slab (parked, hidden) are dropped."""
    lo = [o for o in objects if o.get("rect") and LIGHT_NAME.search((o["name"] or "") + " " + (o.get("parent") or ""))]
    tracks, points = [], []
    for o in lo:
        x0, y0, x1, y1 = o["rect"]
        if min(x1 - x0, y1 - y0) <= 80 and max(x1 - x0, y1 - y0) >= 600:
            tracks.append(dict(name=o["name"], rect=[round(v) for v in o["rect"]], z0=round(o["z0"]), z1=round(o["z1"])))
    rest = [o for o in lo if not (min(o["rect"][2] - o["rect"][0], o["rect"][3] - o["rect"][1]) <= 80
                                  and max(o["rect"][2] - o["rect"][0], o["rect"][3] - o["rect"][1]) >= 600)]
    for g in _by_parent(rest):
        x0, y0, x1, y1 = g["rect"]
        if max(x1 - x0, y1 - y0) > 1500:
            continue
        points.append(g)
    out = []
    for k, items in (("line", tracks), ("point", points)):
        for it in items:
            c = box(*it["rect"]).centroid
            if not zone.contains(c) or it["z0"] > storey - 30:
                continue                         # parked away / above the slab (a hanger into the slab is kept)
            if it["z0"] < 1500 and not (k == "point" and it["z0"] >= 900 and it["z1"] - it["z0"] <= 900):
                continue                         # table / floor lamps; a wall light (sconce) hangs from 900 up
            out.append(dict(it, kind=k, low=it["z0"] < 1500))
    return out


def equipment(objects, zone):
    found = []
    for rx, kind, disp in EQUIP:
        objs = [o for o in objects if o.get("rect") and rx.search((o["name"] or "") + " " + (o.get("parent") or ""))]
        own = [o for o in objs if rx.search(o["name"] or "")]
        if kind == "ac" and own:                 # the unit itself, not its pipes / hangers grouped with it
            objs = [o for o in own if not re.search(r"tube|pipe|holder|труб", o["name"], re.I)] or own
        for g in _by_parent(objs):
            if zone.contains(box(*g["rect"]).centroid):
                found.append(dict(g, kind=kind, title=disp))
    return found


def ceiling_planes(objects, storey):
    """Flat sheets hanging below the slab (suspended ceilings of wet rooms, a lowered zone) -> [(rect, level)]."""
    out = []
    for o in objects:
        r = o.get("rect")
        if not r or not (o.get("flat") or o["z1"] - o["z0"] <= 5) or _decor(o):
            continue
        if not 2000 <= o["z0"] <= storey - 20 or (r[2] - r[0]) * (r[3] - r[1]) < 0.5e6 or LIGHT_NAME.search(o["name"] or ""):
            continue
        out.append(([round(v) for v in r], int(round(o["z0"] / 10.0) * 10)))
    return out


LIGHTISH = re.compile(r"light|lamp|ark|track|spot|duct|tube|holder|condition|cassette|curtain|штор|свет", re.I)
FIXTURE = re.compile(r"basin|раковин|sink|мойк|toilet|унитаз|\bwc\b|mirror|зеркал|radiator|радиатор|heater|бойлер|"
                     r"console", re.I)


def _door_in_gap(dd, g, horiz):
    """A door object belongs to a gap when it lies in the same wall run: parallel to it, its centre inside the gap
    span (+-150) and on the wall line (+-300 across)."""
    if dd.get("used") or dd["horiz"] != horiz:
        return False
    x0, y0, x1, y1 = g.bounds
    dx0, dy0, dx1, dy1 = dd["rect"]
    cx, cy = (dx0 + dx1) / 2.0, (dy0 + dy1) / 2.0
    if horiz:
        return x0 - 150 <= cx <= x1 + 150 and y0 - 300 <= cy <= y1 + 300
    return y0 - 150 <= cy <= y1 + 150 and x0 - 300 <= cx <= x1 + 300


def _gap_evidence(g, horiz, objects):
    """Something hangs on / stands against the gap -> a wall the modeller did not build (it is never seen in the
    renders): a thin panel parallel to the gap above 0.5 m (menu board, mirror, picture), a wall-hung fixture inside it,
    or a cabinet backed onto it. -> (closed?, fixtures inside the gap, side of the fixtures: +1 / -1 across)."""
    x0, y0, x1, y1 = g.bounds
    span = (x0, x1) if horiz else (y0, y1)
    across = ((y0 + y1) / 2.0) if horiz else ((x0 + x1) / 2.0)
    t = (y1 - y0) if horiz else (x1 - x0)
    zone = g.buffer(150, join_style=2)
    hits, fixtures = 0.0, []
    for o in objects:
        r = o.get("rect")
        if not r or o["z1"] - o["z0"] < 30:
            continue
        ob = box(*r)
        if not ob.intersects(zone):
            continue
        a0, a1 = (r[0], r[2]) if horiz else (r[1], r[3])
        c0, c1 = (r[1], r[3]) if horiz else (r[0], r[2])
        ov = min(a1, span[1]) - max(a0, span[0])
        if ov <= 0:
            continue
        name = (o.get("name") or "") + " " + (o.get("parent") or "")
        if FIXTURE.search(name) and ob.intersects(g.buffer(30)):
            fixtures.append(o)
            continue
        thin = (c1 - c0) <= 120 and (a1 - a0) >= 300 and not LIGHTISH.search(name)
        if thin and 500 <= o["z0"] and o["z1"] <= 2500 and abs((c0 + c1) / 2.0 - across) <= t / 2.0 + 150:
            hits = max(hits, ov / (span[1] - span[0]))
        elif o["z0"] <= 300 and 700 <= o["z1"] <= 2600 and (c1 - c0) >= 300 and \
                min(abs(c0 - (across + t / 2.0)), abs(c1 - (across - t / 2.0))) <= 40:
            hits = max(hits, 0.8 * ov / (span[1] - span[0]))       # a cabinet / fridge backed onto the gap
    side = 0
    if fixtures:
        cs = [((f["rect"][1] + f["rect"][3]) / 2.0 if horiz else (f["rect"][0] + f["rect"][2]) / 2.0) for f in fixtures]
        side = 1 if sum(cs) / len(cs) >= across else -1
    return (hits >= 0.4 or bool(fixtures)), fixtures, side


def openings(walls_polys, objects, doors, lints, max_gap=2600):
    """Gaps between wall ends -> [(gap rect, horizontal?, kind, door object | None)].
    A 3D scene shows its doors (door objects, lintels): an interior gap with neither is an open space, not an opening
    (closing it split one room into two) - unless something hangs on it or is mounted in it: then it is a wall the
    modeller left out (kind 'wall'), or a niche when a lintel is above a wall-hung fixture (kind 'niche').
    Exterior gaps -> windows; long gaps only when glazing spans them."""
    from importers.dxf_plan import close_gaps
    from shapely.geometry import Polygon, Point
    mass = unary_union(walls_polys)
    gaps = []
    for g, horiz in close_gaps(walls_polys, max_gap=max(max_gap, 20000)):
        # a "gap" lying along a wall (a column sticking out of a wall faces the next wall) is not an opening
        x0, y0, x1, y1 = g.bounds
        if horiz:
            sides = [box(x0 + 20, y1, x1 - 20, y1 + 10), box(x0 + 20, y0 - 10, x1 - 20, y0)]
        else:
            sides = [box(x1, y0 + 20, x1 + 10, y1 - 20), box(x0 - 10, y0 + 20, x0, y1 - 20)]
        if any(s.area > 0 and s.intersection(mass).area >= 0.8 * s.area for s in sides):
            continue
        gaps.append((g, horiz))
    # modelled walls often miss each other by a few mm (a crack lets the "outside" in): close cracks <= 60 mm
    closed = unary_union(walls_polys + [g for g, _ in gaps]).buffer(30, join_style=2).buffer(-30, join_style=2)
    outline_of = unary_union([Polygon(q.exterior) for q in (closed.geoms if hasattr(closed, "geoms") else [closed])])
    glaz = [box(*o["rect"]).buffer(60) for o in objects if GLAZING.search(o["name"] or "") and not DOOR.search(o["name"] or "")
            and (o["z1"] - o["z0"]) >= 1200]
    glass = unary_union(glaz) if glaz else None
    out = []
    for g, horiz in gaps:
        x0, y0, x1, y1 = g.bounds
        width = (x1 - x0) if horiz else (y1 - y0)
        dr = next((dd for dd in doors if _door_in_gap(dd, g, horiz)), None)
        lint = any(g.intersection(l.buffer(30)).area > 0.6 * g.area for l in lints)
        cover = (g.intersection(glass).area / g.area) if glass is not None and g.area > 0 else 0.0
        if width > max_gap and cover < 0.5:
            continue
        c = g.centroid
        t = (y1 - y0) if horiz else (x1 - x0)
        n = (0, 1) if horiz else (1, 0)
        a = (c.x + n[0] * (t / 2 + 150), c.y + n[1] * (t / 2 + 150))
        b = (c.x - n[0] * (t / 2 + 150), c.y - n[1] * (t / 2 + 150))
        outside = not outline_of.contains(Point(a)) or not outline_of.contains(Point(b))
        ev, fixtures, side = (False, [], 0) if (dr is not None or outside) else _gap_evidence(g, horiz, objects)
        if dr is not None and width <= max_gap:
            dr["used"] = True
            kind = "door"
        elif lint and fixtures and width <= max_gap:
            kind = "niche"                             # basin / mirror under a lintel: a niche, its back is a wall
        elif ev and width <= max_gap:
            kind = "wall"
        elif lint and width <= max_gap:
            kind = "door"
        elif cover >= 0.3:
            kind = "window"
        elif outside:
            kind = "window" if width >= 600 else "door"
        else:
            continue                                   # open space inside: no evidence of a door / wall here
        out.append((g, horiz, kind, dr if kind == "door" else (side if kind == "niche" else None)))
    return out


def entrance_doors(facade, objects):
    """A door unit in a shop front: low glass panels (on the floor, top 1.8-2.6 m) along the facade line with a gap of
    0.7-2.4 m between them, a transom above the gap or an open leaf standing in it -> [(a, b, height)] along the
    facade (x for a horizontal facade)."""
    x0, y0, x1, y1 = facade["rect"]
    horiz = (x1 - x0) >= (y1 - y0)
    line = (y0 + y1) / 2.0 if horiz else (x0 + x1) / 2.0
    lo_f, hi_f = (x0, x1) if horiz else (y0, y1)

    def along(r):
        return (r[0], r[2]) if horiz else (r[1], r[3])

    def acr(r):
        return (r[1], r[3]) if horiz else (r[0], r[2])
    panels, tops, leaves = [], [], []
    for o in objects:
        r = o.get("rect")
        if not r or o is facade or re.search(r"curtain|штор|tulle|тюль", o.get("name") or "", re.I):
            continue
        c0, c1 = acr(r)
        a0, a1 = along(r)
        if a1 < lo_f - 50 or a0 > hi_f + 50:
            continue
        on_line = c0 >= line - 200 and c1 <= line + 200
        if on_line and o["z0"] <= 300 and 1800 <= o["z1"] <= 2600 and a1 - a0 >= 20:
            panels.append((a0, a1, o["z1"]))
        elif on_line and o["z0"] >= 1900 and a1 - a0 >= 500:
            tops.append((a0, a1))
        elif o["z0"] <= 300 and 1800 <= o["z1"] <= 2600 and (c1 - c0) >= 400 and min(abs(c0 - line), abs(c1 - line)) <= 150 \
                and (c1 - c0) <= 1300:
            leaves.append((a0, a1))
    if not panels:
        return []
    panels.sort()
    merged = []
    for a0, a1, z in panels:
        if merged and a0 <= merged[-1][1] + 15:
            merged[-1] = [merged[-1][0], max(merged[-1][1], a1), max(merged[-1][2], z)]
        else:
            merged.append([a0, a1, z])
    out = []
    for (pa0, pa1, za), (pb0, pb1, zb) in zip(merged[:-1], merged[1:]):
        a, b = pa1, pb0
        if not 700 <= b - a <= 2400:
            continue
        tr = [(t0, t1) for t0, t1 in tops if min(t1, b) - max(t0, a) >= 0.7 * (b - a)]
        lf = [(l0, l1) for l0, l1 in leaves if min(l1, b) - max(l0, a) >= 0.3 * (b - a)]
        if not tr and not lf:
            continue
        if tr:                                     # the transom spans the clear opening exactly
            t0, t1 = max(tr, key=lambda q: min(q[1], b) - max(q[0], a))
            a, b = max(a, t0), min(b, t1)
        out.append((a, b, int(round(max(za, zb) / 50.0) * 50)))
    return out


def _ray_face(mass, p, direction, maxd=4000):
    """Distance from p along direction to the first wall face."""
    from shapely.geometry import LineString, Point
    q = (p[0] + direction[0] * maxd, p[1] + direction[1] * maxd)
    hit = LineString([p, q]).intersection(mass)
    if hit.is_empty:
        return None
    return min(Point(p).distance(g) for g in (hit.geoms if hasattr(hit, "geoms") else [hit]))


def build(objects, ceil, path, png=None, slab=None):
    from shapely.geometry import Polygon
    storey = slab or storey_height(objects)
    walls, shell = wall_candidates(objects, storey=storey)
    ws = []
    front_ops = []
    ledges = []
    for i, c in enumerate(walls, 1):
        x0, y0, x1, y1 = [round(v) for v in c["rect"]]
        ws.append(dict(id="W%d" % i, kind="existing", rect=[x0, y0, x1, y1], source=c["name"], check=True))
        for lg in c.get("ledges") or []:
            ledges.append(dict(lg, wall="W%d" % i))
        if c.get("window_band"):                 # wall built from parts around a window: the window itself
            s0, s1 = c["window_band"]
            horiz = (x1 - x0) >= (y1 - y0)
            L = (x1 - x0) if horiz else (y1 - y0)
            front_ops.append(dict(id="ОК.W%d" % i, mark="ОК-?", kind="window", wall="W%d" % i,
                                  c=round((x0 + x1) / 2 if horiz else (y0 + y1) / 2), w=int(L - 100),
                                  h=int(round(s1 - s0)), sill=int(round(s0)), check=True,
                                  evidence="модель: стена из частей под и над окном"))
    for j, f in enumerate(facades(objects, walls), 1):
        x0, y0, x1, y1 = [round(v) for v in f["rect"]]
        horiz = (x1 - x0) >= (y1 - y0)
        if horiz and y1 - y0 < 100:
            y0, y1 = int((y0 + y1) / 2 - 50), int((y0 + y1) / 2 + 50)
        if not horiz and x1 - x0 < 100:
            x0, x1 = int((x0 + x1) / 2 - 50), int((x0 + x1) / 2 + 50)
        wid = "ВТ%d" % j
        ws.append(dict(id=wid, kind="existing", rect=[x0, y0, x1, y1], source=f["name"], check=True, note="витраж"))
        lo, hi = (x0, x1) if horiz else (y0, y1)
        hgt = int(min(ceil, 3000) - 100)
        doors_f = entrance_doors(f, objects)
        cuts = [lo + 100]
        for k_, (da, db, dh) in enumerate(doors_f, 1):
            w_ = int(round((db - da) / 10.0) * 10)
            front_ops.append(dict(id="Д.В%d%s" % (j, "" if len(doors_f) == 1 else k_), mark="Д-?", kind="door", wall=wid,
                                  c=round((da + db) / 2.0), w=w_, h=dh, check=True, entrance=True, evidence="модель: дверной блок витража",
                                  note="входная дверь витража (по модели: проём между стеклянными панелями, фрамуга над ним)"))
            cuts += [da - 50, db + 50]
        cuts.append(hi - 100)
        for k_ in range(0, len(cuts), 2):
            a_, b_ = cuts[k_], cuts[k_ + 1]
            if b_ - a_ < 300:
                continue
            front_ops.append(dict(id="ОК.В%d%s" % (j, "" if len(cuts) == 2 else chr(ord("а") + k_ // 2)), mark="ОК-?",
                                  kind="window", wall=wid, c=round((a_ + b_) / 2.0), w=int(b_ - a_), h=hgt, sill=0,
                                  check=True, note="витраж", evidence="модель: витраж"))
    doors = door_objects(objects)
    lints = lintels(objects, storey)
    polys = [box(*w["rect"]) for w in ws]
    ops = []
    np_ = 0
    for i, (g, horiz, kind, dr) in enumerate(openings(polys, objects, doors, lints) if polys else [], 1):
        x0, y0, x1, y1 = g.bounds
        if kind == "wall":                     # a wall the modeller left out (something hangs on / backs onto it)
            ws.append(dict(id="ЗС%d" % i, kind="existing", rect=[round(x0), round(y0), round(x1), round(y1)],
                           source="закрыто по оборудованию", check=True,
                           note="стены нет в модели - на ней висит / к ней приставлено оборудование"))
            continue
        if kind == "niche":                    # the back of a niche: a 50 mm board on the side away from the fixture
            side = dr
            if horiz:
                rect = [round(x0), round(y0 - 50), round(x1), round(y0)] if side > 0 else [round(x0), round(y1), round(x1), round(y1 + 50)]
            else:
                rect = [round(x0 - 50), round(y0), round(x0), round(y1)] if side > 0 else [round(x1), round(y0), round(x1 + 50), round(y1)]
            ws.append(dict(id="НШ%d" % i, kind="new", rect=rect, source="ниша", check=True,
                           material="Задняя стенка ниши: ГКЛВ 2×12,5 на металлокаркасе, 50 мм",
                           note="ниша под умывальник (перемычка над проёмом, прибор в проёме)"))
            continue
        wid = "ПР%d" % i
        ws.append(dict(id=wid, kind="existing", rect=[round(x0), round(y0), round(x1), round(y1)], source="проём", check=True))
        c = g.centroid
        width = (x1 - x0) if horiz else (y1 - y0)
        pref = {"window": "ОК", "door": "Д", "passage": "ПР"}[kind]
        o = dict(id="%s.%d" % (pref, i), mark="%s-?" % pref, kind=kind, wall=wid, c=round(c.x if horiz else c.y),
                 w=round(width), h=1500 if kind == "window" else (dr["h"] if dr else 2100), check=True)
        if kind == "door" and dr is None:
            o["note"] = "проём под дверь (перемычка в модели, полотна нет)"
            o["evidence"] = "модель: перемычка"
        elif kind == "door":
            o["evidence"] = "модель: полотно двери"
        if kind == "window":
            o["sill"] = 900 if width <= 2600 else 0
            if width > 2600:
                o["h"] = int(min(ceil, 3000))
        ops.append(o)
    # doors drawn inside a wall (the hole is cut by a modifier the reader does not evaluate) and doors standing free
    # (fronts of WC cubicles): an opening in that wall / a partition from wall to wall carrying the door
    mass = unary_union([box(*w["rect"]) for w in ws])
    k = 0
    for dr in doors:
        if dr.get("used"):
            continue
        db = box(*dr["rect"])
        x0, y0, x1, y1 = dr["rect"]
        horiz = dr["horiz"]
        L = (x1 - x0) if horiz else (y1 - y0)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        host = max(ws, key=lambda w: db.intersection(box(*w["rect"])).area)
        hb = box(*host["rect"])
        k += 1
        hx0, hy0, hx1, hy1 = host["rect"]
        host_h = (hx1 - hx0) >= (hy1 - hy0)
        if db.intersection(hb).area >= 0.3 * db.area and host_h == horiz:
            hl = (hx1 - hx0) if horiz else (hy1 - hy0)
            w_ = int(round(min(L, hl - 100) / 10.0) * 10)
            ops.append(dict(id="Д.D%d" % k, mark="Д-?", kind="door", wall=host["id"], c=round(cx if horiz else cy), w=w_,
                            h=dr["h"], check=True, note="дверь по модели: %s" % dr["name"], evidence="модель: полотно двери"))
            continue
        d_lo = _ray_face(mass, (cx, cy), (-1, 0) if horiz else (0, -1))
        d_hi = _ray_face(mass, (cx, cy), (1, 0) if horiz else (0, 1))
        if d_lo is None or d_hi is None or d_lo + d_hi > 6000:
            continue
        if horiz:
            a, b = cx - d_lo, cx + d_hi
            rect = [round(a), round(cy - 50), round(b), round(cy + 50)]
        else:
            a, b = cy - d_lo, cy + d_hi
            rect = [round(cx - 50), round(a), round(cx + 50), round(b)]
        pid = "ПГ%d" % k
        ws.append(dict(id=pid, kind="new", rect=rect, source=dr["name"], check=True,
                       material="Перегородка (стекло / ГКЛ по модели) 100 мм"))
        w_ = int(round(min(L, (b - a) - 100) / 10.0) * 10)
        c_ = (a + b) / 2.0 if abs(((a + b) / 2.0) - (cx if horiz else cy)) > (b - a) / 2.0 - w_ / 2.0 else (cx if horiz else cy)
        ops.append(dict(id="Д.D%d" % k, mark="Д-?", kind="door", wall=pid, c=round(c_), w=w_, h=dr["h"], check=True,
                        note="дверь по модели: %s" % dr["name"], evidence="модель: полотно двери"))
        mass = unary_union([box(*w["rect"]) for w in ws])
    ops = front_ops + ops
    wall_polys = [box(*w["rect"]) for w in ws]
    furn = furniture(objects, walls=wall_polys)
    zone = box(*unary_union(polys).bounds).buffer(500) if polys else None
    if zone is not None:                        # library objects parked away from the plan are not furniture
        furn = [f for f in furn if zone.contains(box(*_bounds(f["poly"])).centroid)]
    cnt = counters(objects, furn, wall_polys)
    if cnt:
        gone = set()
        for c in cnt:
            gone.update(c.pop("_under"))
        furn = [f for f in furn if id(f) not in gone] + cnt
    inside = box(*unary_union(polys).bounds) if polys else None
    named = [[o["name"], round((o["rect"][0] + o["rect"][2]) / 2), round((o["rect"][1] + o["rect"][3]) / 2)]
             for o in objects if o["z0"] < 2500 and o["name"]][:4000]
    curtains = [[round(v) for v in o["rect"]] for o in objects if re.search(r"curtain|штор|tulle|тюль", o["name"] or "", re.I)
                and (o["z1"] - o["z0"]) >= 1500]
    d = dict(meta=dict(title="ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА", studio="Space Design Studio", stage="Дизайн-проект"),
             levels=dict(floor=0, ceiling=int(round(ceil / 10.0) * 10),
                         slab=int(round((slab if slab and slab > ceil else ceil + 400) / 10.0) * 10),
                         **({"source": "модель 3D: высота стен до плиты"} if slab else {})),
             grid=dict(x=[], y=[]), walls=ws, openings=ops, rooms=[], furniture=furn, lighting=[], switches=[],
             sockets=[], plumbing=[], floors=[], ceilings=dict(types=[], zones=[]), elevations=[], nodes=[],
             _objects=named, _curtains=curtains,
             _lights=lights(objects, inside, storey) if inside is not None else [],
             _equipment=equipment(objects, inside) if inside is not None else [],
             _beams=[[r, z] for r, z in beams(objects, storey) if inside is None or inside.contains(box(*r).centroid)],
             _ceil_planes=[[r, z] for r, z in ceiling_planes(objects, storey)
                           if inside is None or inside.contains(box(*r).centroid)],
             _ledges=ledges,
             _todo=["проверить стены, проёмы и мебель (check=true) по plan_cut.png / draft_plan.png",
                    "назвать помещения (по содержимому названы автоматически)", "оси и высоты - уточнить"])
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if png:
        _plot(d, png)
    return d, shell


def _plot(d, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, ax = plt.subplots(figsize=(14, 14))
    for w in d["walls"]:
        x0, y0, x1, y1 = w["rect"]
        col = "#d08020" if w.get("source") == "проём" else "#222"
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, color=col, alpha=0.85))
    for o in d["openings"]:
        w = next(x for x in d["walls"] if x["id"] == o["wall"])
        x0, y0, x1, y1 = w["rect"]
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, "%s %d" % (o["id"], o["w"]), fontsize=7, color="#1060c0", ha="center")
    for f in d["furniture"]:
        xs = [p[0] for p in f["poly"]]
        ys = [p[1] for p in f["poly"]]
        from shapely.geometry import Polygon as _Pg
        pg = _Pg(f["poly"])
        ax.plot([p[0] for p in f["poly"]] + [f["poly"][0][0]], [p[1] for p in f["poly"]] + [f["poly"][0][1]], color="#2a8a2a", lw=0.7)
        c = pg.representative_point()
        ax.text(c.x, c.y, f["kind"], fontsize=5, color="#2a8a2a", ha="center")
    ax.autoscale()
    ax.set_aspect("equal")
    ax.grid(True, lw=0.3, alpha=0.4)
    ax.set_title("черновик: стены (чёрн.), закрытые проёмы (оранж.), мебель (зел.)")
    fig.savefig(png, dpi=110, bbox_inches="tight")
    plt.close(fig)
