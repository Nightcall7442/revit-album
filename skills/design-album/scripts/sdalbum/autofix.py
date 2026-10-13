# -*- coding: utf-8 -*-
"""Safe automatic corrections of project.json (what an experienced designer fixes without asking).

    data2, log, rest, questions = fix(data, base_dir)

Only deterministic, convention-backed fixes are applied (each one is logged):
  draft clean-up   room classes from names, numbering, opening marks / types / leaves, door swing + hinge
  SNAP             positions to the 5-mm module (the across-wall coordinate of a point on a wall face is kept)
  ON_WALL          switch / socket / outlet that misses the wall face by <= 300 mm -> projected onto the face
  WALL_SIDE        'wall' code taken from the actual face normal
  HOT_LEFT         hot / cold outlets swapped (hot on the left, seen from the room)
  MULTIPOINT       group switched from 2 places -> 2 pass-through; 3+ -> 2 pass-through + cross
  WET_SOCKET       ordinary socket in a wet room -> IP44 (РВ)
  ELEV_ORDER       elevation letters re-ordered clockwise (А stays)
Design conflicts (door hits furniture, two doors clash, leaf from the source differs, modules almost equal) are
never "fixed": they become questions to the client.
"""
import copy
import math
import os
import re

from shapely.geometry import Point, Polygon

from . import model as M
from . import topo as T
from . import validate as V

QUESTION_CODES = {
    "DOORS_CLASH": "двери задевают друг друга - поменять сторону открывания или одну из дверей сделать раздвижной?",
    "DOOR_HITS_FURNITURE": "дверь при открывании задевает мебель - сдвинуть мебель / поменять сторону петель?",
    "LEAF_SOURCE_CONFLICT": "ширина полотна в исходнике отличается от проекта - какую принять?",
    "FURN_OVERLAP": "мебель пересекается - уточнить размеры / расстановку",
    "MODULES_NEAR_EQUAL": "модули кухни почти равны - сделать одинаковыми?",
    "ELEV_SMALL_GAP": "щель в развёртке меньше 15 мм - планка/зазор или выровнять?",
    "LIGHT_GROUP_NO_SWITCH": "группа светильников без выключателя - откуда управлять?",
    "FLOOR_UNCOVERED": "покрытие пола задано не во всём помещении - какое покрытие?",
    "ROOM_GAP": "есть площадь, не отнесённая к помещению - это отдельное помещение?",
}

LEAVES = (600, 700, 800, 900)
STEEL_LEAVES = (860, 960)


def _P(d, base_dir):
    return M.Project(d, base_dir)


def fix(data, base_dir="."):
    d = copy.deepcopy(data)
    log = []
    draft = bool(d.get("_todo")) or bool(d.get("_draft"))
    _defaults(d, log)
    if draft:
        _draft_snap(d, log)
        _auto_grid(d, base_dir, log)
    _auto_rooms(d, base_dir, log)
    _rooms(d, log, draft)
    P = _P(d, base_dir)
    if P.rooms:
        _openings(d, P, log)
        P = _P(d, base_dir)
        _swings(d, P, log)
        P = _P(d, base_dir)
        _snap(d, P, log)
        P = _P(d, base_dir)
        _on_wall(d, P, log)
        P = _P(d, base_dir)
        _furniture_rooms(d, P, log)
        _hot_left(d, P, log)
        _multipoint(d, log)
        _wet_sockets(d, P, log)
        _elev_order(d, P, log)
    P = _P(d, base_dir)
    rest = V.run(P)
    return d, log, rest, questions(d, P, rest)


def L(log, code, msg, n=1):
    log.append(dict(code=code, msg=msg, n=n))


# ------------------------------------------------------------------ defaults and draft clean-up
def _defaults(d, log):
    lv = d.setdefault("levels", {})
    miss = [k for k in ("floor", "ceiling", "slab") if k not in lv]
    lv.setdefault("floor", 0)
    lv.setdefault("ceiling", 2700)
    lv.setdefault("slab", max(3000, lv["ceiling"] + 200))
    if miss:
        L(log, "DEFAULTS", "высоты по умолчанию: %s (уточнить)" % ", ".join("%s=%d" % (k, lv[k]) for k in miss))
    meta = d.setdefault("meta", {})
    meta.setdefault("title", "ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА КВАРТИРЫ")
    meta.setdefault("object", "Дизайн-проект интерьера квартиры")
    meta.setdefault("studio", "Space Design Studio")
    meta.setdefault("stage", "Дизайн-проект")
    for k in ("walls", "openings", "rooms", "separations", "furniture", "lighting", "switches", "sockets", "plumbing",
              "floors", "elevations", "nodes", "circuits"):
        d.setdefault(k, [])
    d.setdefault("ceilings", {}).setdefault("types", [])
    d["ceilings"].setdefault("zones", [])
    d.setdefault("finishes", {})
    d.setdefault("grid", {"x": [], "y": []})


def _rooms(d, log, draft):
    seen = {}
    for i, r in enumerate(d.get("rooms", [])):
        name = re.sub(r"\s+", " ", str(r.get("name", "")).strip()) or "Помещение %d" % (i + 1)
        name = name[:1].upper() + name[1:]
        if name in seen:
            seen[name] += 1
            new = "%s %d" % (name, seen[name])
            L(log, "ROOM_NAME", "повтор имени «%s» -> «%s»" % (name, new))
            name = new
        else:
            seen[name] = 1
        if name != r.get("name"):
            r["name"] = name
        guess = T.room_class(name)
        if "cls" not in r or (draft and r.get("cls") != guess and guess != "living"):
            if r.get("cls") != guess:
                L(log, "ROOM_CLASS", "«%s»: класс %s (по названию)" % (name, guess))
            r["cls"] = guess
        if not r.get("num"):
            r["num"] = str(i + 1)


def _draft_snap(d, log):
    """A survey drawing exported to PDF / DXF carries 0.5-2 mm noise (1499, 5617): walls and openings of a draft
    are put on the 5-mm module (lesson L-011)."""
    n = 0
    for w in d.get("walls", []):
        if w.get("rect"):
            new = [T.snap(v) for v in w["rect"]]
            if new != w["rect"]:
                w["rect"] = new
                n += 1
        if w.get("poly"):
            new = [[T.snap(x), T.snap(y)] for x, y in w["poly"]]
            if new != w["poly"]:
                w["poly"] = new
                n += 1
    piece = {w["id"]: w for w in d.get("walls", []) if w.get("source") == "проём" and w.get("rect")}
    for o in d.get("openings", []):
        if o.get("wall") in piece:          # an opening found in a wall gap fills its gap piece exactly
            x0, y0, x1, y1 = piece[o["wall"]]["rect"]
            horiz = abs(x1 - x0) >= abs(y1 - y0)
            c, w = ((x0 + x1) / 2.0, abs(x1 - x0)) if horiz else ((y0 + y1) / 2.0, abs(y1 - y0))
            c = int(c) if c == int(c) else c
            if (o.get("c"), o.get("w")) != (c, w):
                o["c"], o["w"] = c, w
                n += 1
            continue
        for k in ("c", "w"):
            if k in o and o[k] != T.snap(o[k]):
                o[k] = T.snap(o[k])
                n += 1
    for r in d.get("rooms", []):
        if r.get("seed"):
            r["seed"] = [T.snap(v) for v in r["seed"]]
    if n:
        L(log, "DRAFT_SNAP", "стены и проёмы черновика приведены к шагу 5 мм (%d правок)" % n, n)


AXIS_LETTERS = "АБВГДЕЖИКЛМНПРСТУФШЭЮЯ"          # ГОСТ 21.101: without Ё З Й О Х Ц Ч Щ Ъ Ы Ь


def _auto_grid(d, base_dir, log):
    """No axes in a draft: axes on the centre lines of bearing walls (>= 150 thick, >= 1.5 m long), origin moved
    to axis 1 / А."""
    if d.get("grid", {}).get("x") or not d.get("walls"):
        return
    P0 = _P(dict(d, rooms=[]), base_dir)
    xs, ys = _wall_centres(P0.shell)
    def cluster(vals):
        # walls closer than 450 mm (a lining, an offset run of the same wall) share one axis: two bubbles 200 mm
        # apart on a 1:100 plan sit on top of each other (lesson L-064)
        out = []
        for v, L_ in sorted(vals):
            if out and abs(v - out[-1][0]) <= 450:
                c, LL = out[-1]
                out[-1] = ((c * LL + v * L_) / (LL + L_), LL + L_)
            else:
                out.append((v, L_))
        return [T.snap(v) for v, _ in out]
    gx, gy = cluster(xs), cluster(ys)
    if len(gx) < 2 or len(gy) < 2:
        return
    dx, dy = -gx[0], -gy[0]
    if dx or dy:
        from .editor import _shift
        P = _P(d, base_dir)
        for sec in ("walls", "openings", "rooms", "furniture", "lighting", "switches", "sockets", "plumbing", "nodes"):
            for it in d.get(sec, []):
                _shift(it, dx, dy, P)
        d["separations"] = [[[a[0] + dx, a[1] + dy], [b[0] + dx, b[1] + dy]] for a, b in d.get("separations", [])]
        shift_extras(d, dx, dy)
    d["grid"] = {"x": [[str(i + 1), v + dx] for i, v in enumerate(gx)],
                 "y": [[AXIS_LETTERS[i] if i < len(AXIS_LETTERS) else "Я%d" % i, v + dy] for i, v in enumerate(gy)]}
    L(log, "AXES", "оси по центрам несущих стен: %s / %s; начало координат - пересечение 1/А" % (
        ", ".join(n for n, _ in d["grid"]["x"]), ", ".join(n for n, _ in d["grid"]["y"])))


def shift_extras(d, dx, dy):
    """Evidence kept from the source scene (object names, lights, beams, ceiling sheets, curtains, equipment) moves
    with the plan - otherwise rooms are named by objects standing in the wrong place."""
    def rect(r):
        return [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
    d["_objects"] = [[n, x + dx, y + dy] for n, x, y in d.get("_objects", [])]
    d["_curtains"] = [rect(r) for r in d.get("_curtains", [])]
    for k in ("_beams", "_ceil_planes"):
        d[k] = [[rect(r), z] for r, z in d.get(k, [])]
    for k in ("_lights", "_equipment"):
        for it in d.get(k, []):
            it["rect"] = rect(it["rect"])
    for it in d.get("items", []):                 # furniture items of the scene: their places on the plan
        it["places"] = [[p[0] + dx, p[1] + dy] + list(p[2:]) for p in it.get("places", [])]
    for t in d.get("_texts", []):                 # signs of the scene (text objects)
        t["pos"] = [t["pos"][0] + dx, t["pos"][1] + dy] + list(t["pos"][2:])
    for lg in d.get("_ledges", []):               # wall parts standing proud under a window
        lg["rect"] = rect(lg["rect"])
        lg["wall_rect"] = rect(lg["wall_rect"])
    for k in ("_floor_src", "_box_src"):          # floor coverings and boxes of the scene
        for it in d.get(k, []):
            if it.get("poly"):
                it["poly"] = [[x + dx, y + dy] for x, y in it["poly"]]
            if it.get("polys"):
                it["polys"] = [[[x + dx, y + dy] for x, y in pg] for pg in it["polys"]]
            if it.get("rect"):
                it["rect"] = rect(it["rect"])
            if it.get("inner"):
                it["inner"] = rect(it["inner"])
            if it.get("origin"):
                it["origin"] = [it["origin"][0] + dx, it["origin"][1] + dy]


def _wall_centres(shell, tmin=150, tmax=700, lmin=1500):
    """Centre lines of bearing walls from the wall mass itself (any polygon shapes): two parallel faces 150-700
    apart with solid wall between them over >= 1.5 m. -> ([(x, overlap)], [(y, overlap)])"""
    from shapely.geometry import box
    edges = []
    for g in (shell.geoms if hasattr(shell, "geoms") else [shell]):
        for ring in [g.exterior] + list(g.interiors):
            cs = list(ring.coords)
            for a, b in zip(cs[:-1], cs[1:]):
                edges.append((a, b))
    vert = [(a[0], min(a[1], b[1]), max(a[1], b[1])) for a, b in edges if abs(a[0] - b[0]) < 1 and abs(a[1] - b[1]) >= lmin * 0.5]
    hor = [(a[1], min(a[0], b[0]), max(a[0], b[0])) for a, b in edges if abs(a[1] - b[1]) < 1 and abs(a[0] - b[0]) >= lmin * 0.5]
    xs, ys = [], []
    for lst, out, is_v in ((vert, xs, True), (hor, ys, False)):
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                c1, lo1, hi1 = lst[i]
                c2, lo2, hi2 = lst[j]
                t = abs(c1 - c2)
                lo, hi = max(lo1, lo2), min(hi1, hi2)
                if not (tmin <= t <= tmax) or hi - lo < lmin:
                    continue
                a, b = min(c1, c2), max(c1, c2)
                strip = box(a + 1, lo + 1, b - 1, hi - 1) if is_v else box(lo + 1, a + 1, hi - 1, b - 1)
                if shell.intersection(strip).area < 0.9 * strip.area:
                    continue
                out.append(((a + b) / 2.0, hi - lo))
    return xs, ys


def _auto_rooms(d, base_dir, log):
    """No rooms in a draft: every closed space of the plan becomes a room 'Помещение N' (name to be confirmed)."""
    if d.get("rooms") or not d.get("walls"):
        return
    from shapely.ops import unary_union, polylabel
    P = _P(dict(d, rooms=[]), base_dir)
    mass = P.mass
    outer = unary_union([Polygon(g.exterior) for g in (mass.geoms if hasattr(mass, "geoms") else [mass])])
    inner = outer.difference(mass)
    if any(w["kind"] == "existing" for w in P.walls):        # same pieces as model.Project._rooms: minus passages,
        th = P.throats()                                      # split by separations (a bar behind its counter)
        if th:
            inner = inner.difference(unary_union(th))
    from shapely.geometry import LineString as _LS
    pieces = list(inner.geoms) if hasattr(inner, "geoms") else [inner]
    for a, b in d.get("separations", []):
        new = []
        for p in pieces:
            parts = p.difference(_LS([a, b]).buffer(0.5, cap_style=2))
            new.extend(list(parts.geoms) if hasattr(parts, "geoms") else [parts])
        pieces = new
    pieces = [g for g in pieces if g.area > 1.0e6]
    pieces.sort(key=lambda g: (-g.centroid.y, g.centroid.x))
    names = _names_by_contents(d, pieces)
    seen = {}
    for i, g in enumerate(pieces, 1):
        c = polylabel(g, 10)
        nm, cls = names[i - 1] if names[i - 1] else ("Помещение %d" % i, None)
        if names[i - 1]:
            seen[nm] = seen.get(nm, 0) + 1
            if seen[nm] > 1:
                nm = "%s %d" % (nm, seen[nm])
        r = dict(num=str(i), name=nm, seed=[T.snap(c.x), T.snap(c.y)], auto=True)
        if cls:
            r["cls"] = cls
        d["rooms"].append(r)
    if pieces:
        named = sum(1 for n in names if n)
        L(log, "ROOMS_AUTO", "помещения найдены по контуру стен: %d%s" % (
            len(pieces), ", названы по содержимому: %d (проверить)" % named if named else " (названия - уточнить)"), len(pieces))


ROOM_BY_CONTENT = [   # (name, class, pattern of object / furniture names, weight)
    ("Санузел", "wet", r"toilet|унитаз|\bwc\b|urinal|писсуар|bidet|биде", 5),
    ("Ванная", "wet", r"bath\s*tub|bathtub|ванн", 4),
    ("Душевая", "wet", r"shower|душ", 3),
    ("Постирочная", "wet", r"washing machine|washer|стирал|dryer|сушил", 3),
    ("Кухня", "kitchen", r"fridge|refriger|холодил|hicold|freezer|oven|духов|stove|плит|\bhob\b|hood|вытяж|dishwash|посудом|"
                         r"fryer|grill|gastro|мойк|\bsink\b", 2),
    ("Бар", "kitchen", r"bar\s*counter|coffee\s*machine|кофемаш|espresso|barista", 3),
    ("Спальня", "living", r"\bbed\b|кроват", 5),
    ("Гардеробная", "storage", r"wardrobe|гардероб|closet", 2),
    ("Зал", "living", r"chair|стул|stool|табурет|table|стол|sofa|диван|armchair|кресл|banquette", 1),
]


def _names_by_contents(d, pieces):
    """Rooms of a 3D scene / CAD drawing without names: named by what stands in them (toilet -> «Санузел», fridges and
    stoves -> «Кухня», many seats -> «Зал», bed -> «Спальня»). -> [(name, cls) | None] per piece (lesson L-063)."""
    from shapely.geometry import Point as _Pt
    objs = [(str(n), x, y) for n, x, y in d.get("_objects", [])]
    for f in d.get("furniture", []):
        xs = [p[0] for p in f.get("poly", [])]
        ys = [p[1] for p in f.get("poly", [])]
        if xs:
            objs.append(("%s %s" % (f.get("kind", ""), f.get("name", "")), sum(xs) / len(xs), sum(ys) / len(ys)))
    pats = [(nm, cls, re.compile(rx, re.I), w) for nm, cls, rx, w in ROOM_BY_CONTENT]
    out = []
    for g in pieces:
        score = {}
        seats = 0
        zone = g.buffer(50)
        for n, x, y in objs:
            if not zone.contains(_Pt(x, y)):
                continue
            for nm, cls, rx, w in pats:
                if rx.search(n):
                    score[(nm, cls)] = score.get((nm, cls), 0) + w
                    if nm == "Зал":
                        seats += 1
                    break
        if not score:
            out.append(None)
            continue
        (nm, cls), sc = max(score.items(), key=lambda kv: kv[1])
        if sc < 2:
            out.append(None)
            continue
        if nm == "Зал" and seats < 8:
            nm = "Гостиная" if any(re.search(r"sofa|диван|\btv\b", n, re.I) for n, x, y in objs
                                   if zone.contains(_Pt(x, y))) else "Комната"
        out.append((nm, cls))
    return out


def _leaf(w, steel):
    std = STEEL_LEAVES if steel else LEAVES
    ok = [x for x in std if x <= w - (60 if steel else 80)]
    return max(ok) if ok else T.snap(w - 80, 10)


def _openings(d, P, log):
    ops = d.get("openings", [])
    used = {}
    for o in ops:
        m = re.match(r"^(ОК|ДБ|Д|ПР)-(\d+)$", str(o.get("mark", "")))
        if m:
            used[m.group(1)] = max(used.get(m.group(1), 0), int(m.group(2)))
    for o in ops:                                  # passages: ПР-n, no opening type (no infill)
        if o.get("kind") == "passage" and not re.match(r"^ПР-\d+$", str(o.get("mark", ""))):
            used["ПР"] = used.get("ПР", 0) + 1
            old = o["id"]
            o["mark"] = "ПР-%d" % used["ПР"]
            o["id"] = "%s.1" % o["mark"]
            _rename_refs(d, old, o["id"])
    todo = [o for o in ops if not re.match(r"^(ОК|ДБ|Д|ПР)-\d+$", str(o.get("mark", ""))) and o.get("kind") != "passage"]
    if not todo:
        return
    byid = {o["id"]: o for o in P.openings}
    groups = {}
    order = []
    for o in sorted(todo, key=lambda o: (-P.open_shape[o["id"]].centroid.y, P.open_shape[o["id"]].centroid.x)):
        po = byid[o["id"]]
        entr = T.is_entrance(P, po)
        pref = "ОК" if o["kind"] == "window" else "ДБ" if o["kind"] == "balcony" else "Д"
        key = (pref, entr, round(o["w"] / 10.0), round(po["h"] / 10.0))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(o)
    order.sort(key=lambda k: (k[0], not k[1]))            # entrance door first: Д-1
    types = d.setdefault("opening_types", {})
    n_new = 0
    for key in order:
        pref, entr, _, _ = key
        used[pref] = used.get(pref, 0) + 1
        mark = "%s-%d" % (pref, used[pref])
        for i, o in enumerate(groups[key], 1):
            old = o["id"]
            o["mark"] = mark
            o["id"] = "%s.%d" % (mark, i)
            n_new += 1
            if pref in ("Д", "ДБ") and "leaf" not in o:
                o["leaf"] = _leaf(o["w"], entr)
            if entr:
                o["steel"] = True
            _rename_refs(d, old, o["id"])
        o0 = groups[key][0]
        if mark not in types:
            types[mark] = {}
        if types[mark].get("auto", not types[mark]):
            h = o0.get("h", 1500 if pref == "ОК" else 2100)
            if pref == "ОК":
                types[mark] = dict(oboz="ГОСТ 30674-99", name="Блок оконный ПВХ %d×%d" % (o0["w"], h), note="размеры уточнить по месту")
            elif entr:
                types[mark] = dict(oboz="ГОСТ 31173-2016", name="Блок дверной стальной входной %d×%d" % (o0["leaf"], h - 50),
                                   leaf=o0["leaf"], style="steel", note="подбор по замеру проёма")
            elif pref == "ДБ":
                types[mark] = dict(oboz="ГОСТ 30970-2014", name="Блок дверной балконный ПВХ %d×%d" % (o0["w"], h), style="glass")
            else:
                types[mark] = dict(oboz="ГОСТ 475-2016", name="Блок дверной внутренний %d×%d" % (o0["leaf"], 2000 if h >= 2050 else h - 50),
                                   leaf=o0["leaf"], style="door")
            types[mark]["auto"] = True               # created here: senior / propose may refine it, a user's type never
    L(log, "OPENING_MARKS", "проёмы промаркированы (%d шт.), типы и полотна - по стандартным размерам" % n_new, n_new)


def _rename_refs(d, old, new):
    for s in d.get("switches", []):
        if s.get("door") == old:
            s["door"] = new


def _swing_options(P, o):
    """Swing directions allowed by convention for this door, best first: [(normal, reason)]."""
    sides = T.opening_sides(P, o)
    (ra, na, _), (rb, nb, _) = sides
    if ra is None or rb is None:                          # entrance: outward, balcony: into the room
        inside = (na, ra) if ra is not None else (nb, rb)
        outside = nb if ra is not None else na
        if o["kind"] == "balcony":
            return [(inside[0], "балконная - внутрь помещения")]
        return [(outside, "входная - наружу")]
    ca, cb = ra.get("cls"), rb.get("cls")
    if "wet" in (ca, cb) and ca != cb:
        return [(na if cb == "wet" else nb, "из санузла - наружу")]
    if "circulation" in (ca, cb) and ca != cb:
        return [(na if cb == "circulation" else nb, "в помещение, не в коридор")]
    big = (na, nb) if ra["area"] >= rb["area"] else (nb, na)
    return [(big[0], "в большее помещение"), (big[1], "в меньшее помещение")]


def _swings(d, P, log):
    from .symbols import door_swing_area
    furn = [g for f, g in T.furniture_shapes(P) if f.get("kind") not in ("rug", "kitchen_upper", "mirror", "rail", "tv")]
    raw = {o["id"]: o for o in d.get("openings", [])}
    placed = []
    n = 0
    for o in P.openings:
        if o["kind"] not in ("door", "balcony"):
            continue
        if o.get("swing"):
            try:
                placed.append(door_swing_area(P, o))
            except Exception:
                pass
            continue
        best = None
        for k, (nrm, why) in enumerate(_swing_options(P, o)):
            for hinge in ("min", "max"):
                oo = dict(o, swing=list(nrm), hinge=hinge)
                try:
                    g = door_swing_area(P, oo)
                except Exception:
                    continue
                hit = sum(g.intersection(f).area for f in furn) + sum(g.intersection(q).area for q in placed)
                corner = _corner_dist(P, oo, nrm, hinge)
                score = hit / 1e4 + corner / 1e3 + k * 50.0
                if best is None or score < best[0]:
                    best = (score, nrm, hinge, why, g)
        if best is None:
            continue
        _, nrm, hinge, why, g = best
        raw[o["id"]]["swing"] = [int(nrm[0]), int(nrm[1])]
        raw[o["id"]]["hinge"] = hinge
        placed.append(g)
        n += 1
    if n:
        L(log, "DOOR_SWING", "открывание дверей задано (%d шт.): входная наружу, санузлы наружу, комнаты - внутрь; петли - "
                             "у ближайшего угла, без удара в мебель" % n, n)


def _corner_dist(P, o, nrm, hinge):
    """Distance from the hinge jamb to the nearest corner on the side the leaf opens to (leaf lies along a wall)."""
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    a, b = o["c"] - o["w"] / 2.0, o["c"] + o["w"] / 2.0
    room = None
    for r, n, fp in T.opening_sides(P, o):
        if tuple(n) == tuple(nrm):
            room = r
    if room is None:
        return 0.0
    from shapely.geometry import LineString
    if w["dir"] == "H":
        face = y1 if nrm[1] > 0 else y0
        ln = LineString([(-1e6, face + nrm[1] * 2), (1e6, face + nrm[1] * 2)])
    else:
        face = x1 if nrm[0] > 0 else x0
        ln = LineString([(face + nrm[0] * 2, -1e6), (face + nrm[0] * 2, 1e6)])
    seg = ln.intersection(room["shp"])
    parts = list(seg.geoms) if hasattr(seg, "geoms") else [seg]
    for p in parts:
        if p.is_empty:
            continue
        cs = [c[0] if w["dir"] == "H" else c[1] for c in p.coords]
        lo, hi = min(cs), max(cs)
        if lo - 5 <= a and b <= hi + 5 or (lo <= o["c"] <= hi):
            return (a - lo) if hinge == "min" else (hi - b)
    return 0.0


# ------------------------------------------------------------------ positions
def _on_face(P, x, y, tol=1.0):
    r = P.room_of_point((x, y), 40)
    return r is not None and r["shp"].exterior.distance(Point(x, y)) <= tol


def _snap(d, P, log):
    n = 0
    for sec in ("lighting", "sockets", "switches", "plumbing"):
        for o in d.get(sec, []):
            keys = ["x", "y", "x2", "y2"] if sec == "lighting" else ["x", "y"]
            keep = None
            if sec != "lighting" and _on_face(P, o["x"], o["y"]):
                nrm = T.NORM.get(o.get("wall")) if o.get("wall") else None
                if nrm is None:
                    r = P.room_of_point((o["x"], o["y"]), 40)
                    nrm, _ = P.inward_normal((o["x"], o["y"]), r)
                keep = "x" if abs(nrm[0]) > 0.5 else "y"
            for k in keys:
                if k == keep or o.get(k) is None:
                    continue
                v = o[k]
                if abs(v - 5 * round(v / 5.0)) > 0.01:
                    o[k] = T.snap(v)
                    n += 1
    for f in d.get("furniture", []):
        new = [[T.snap(x), T.snap(y)] + list(p[2:]) for p in f.get("poly", []) for x, y in [p[:2]]]
        if new != f.get("poly"):
            n += 1
            f["poly"] = new
    for z in d.get("ceilings", {}).get("zones", []):
        new = [[T.snap(x), T.snap(y)] for x, y in z.get("poly", [])]
        if new != z.get("poly"):
            n += 1
            z["poly"] = new
    for e in d.get("elevations", []):
        for zn in e.get("zones", []):
            for k in ("s0", "s1", "z0", "z1"):
                if k in zn and abs(zn[k] - T.snap(zn[k])) > 0.01:
                    zn[k] = T.snap(zn[k])
                    n += 1
        for it in e.get("items", []):
            # cabinet modules only; shelves / side panels / hob / worktop carry real material thicknesses
            # (18, 22, 12 mm) that are not model noise (lesson L-050)
            if it.get("type") not in ("base", "upper", "tall", "plinth"):
                continue
            for a, b in (("s0", "s1"), ("z0", "z1")):
                if a in it and b in it and abs(it[b] - it[a]) < 40:
                    continue
                for k in (a, b):
                    if k in it and abs(it[k] - T.snap(it[k])) > 0.01:
                        it[k] = T.snap(it[k])
                        n += 1
        for k in ("heights", "module_chain"):
            if e.get(k):
                new = [T.snap(v) for v in e[k]]
                if new != e[k]:
                    e[k] = sorted(set(new))
                    n += 1
    if n:
        L(log, "SNAP", "координаты и размеры приведены к шагу 5 мм (%d правок, шум 3D-модели)" % n, n)


def _on_wall(d, P, log):
    n_move, n_side = 0, 0
    for sec, tol, label in (("switches", 30, "выключатель"), ("sockets", 30, "розетка"), ("plumbing", 160, "вывод")):
        for o in d.get(sec, []):
            if (sec == "plumbing" and o.get("h", 1) == 0) or o.get("mount") == "furniture":
                continue                       # floor outlets / sockets built into a counter are not on a wall
            p = (o["x"], o["y"])
            r = P.room_of_point(p, 320)
            if r is None:
                continue
            dist = r["shp"].exterior.distance(Point(p))
            if dist > tol:
                res = T.project_to_face(P, p, r, max_d=300)
                if res is None:
                    continue
                q, nrm, _ = res
                if abs(nrm[0]) > 0.5:
                    o["x"], o["y"] = round(q[0], 1), T.snap(q[1])
                else:
                    o["x"], o["y"] = T.snap(q[0]), round(q[1], 1)
                if abs(o["x"] - round(o["x"])) < 0.05:
                    o["x"] = int(round(o["x"]))
                if abs(o["y"] - round(o["y"])) < 0.05:
                    o["y"] = int(round(o["y"]))
                if sec != "plumbing":
                    o["wall"] = T.normal_code(nrm) or o.get("wall")
                n_move += 1
                continue
            if sec != "plumbing" and o.get("wall"):
                nrm, _ = P.inward_normal(p, r)
                code = T.normal_code(nrm)
                if code and code != o["wall"]:
                    o["wall"] = code
                    n_side += 1
    if n_move:
        L(log, "ON_WALL", "точки перенесены на чистовую поверхность стены (%d шт.)" % n_move, n_move)
    if n_side:
        L(log, "WALL_SIDE", "сторона установки исправлена по нормали стены (%d шт.)" % n_side, n_side)


def _furniture_rooms(d, P, log):
    """Furniture without a room (taken from a 3D scene) gets the room it stands in; outside every room -> dropped."""
    n, drop = 0, []
    for f in d.get("furniture", []):
        if f.get("room") and f["room"] in P.room_by_name:
            continue
        try:
            c = Polygon(f["poly"]).representative_point()
        except Exception:
            continue
        r = P.room_of_point((c.x, c.y), 200)
        if r is None:
            drop.append(f)
            continue
        f["room"] = r["name"]
        n += 1
    for f in drop:
        d["furniture"].remove(f)
    if n or drop:
        L(log, "FURN_ROOM", "мебель привязана к помещениям: %d%s" % (n, ", вне помещений удалено: %d" % len(drop) if drop else ""), n)
    # footprints taken from a 3D scene (check=true) are bounding boxes: one sticking into a wall or the next room is
    # trimmed to its room (a designer's own furniture is never touched - it becomes a question instead)
    k = 0
    for f in d.get("furniture", []):
        if not f.get("check") or f.get("room") not in P.room_by_name:
            continue
        g = Polygon(f["poly"]).buffer(0)
        rs = P.room_by_name[f["room"]]["shp"]
        part = g.intersection(rs)
        if g.area <= 0 or part.is_empty or g.difference(rs).area <= 0.01 * g.area:
            continue
        if part.area < 0.5 * g.area:
            continue
        x0, y0, x1, y1 = part.bounds
        x0, y0, x1, y1 = T.snap(x0), T.snap(y0), T.snap(x1), T.snap(y1)
        f["poly"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        k += 1
    if k:
        L(log, "FURN_TRIM", "габариты мебели из 3D-сцены обрезаны по помещению (заходили в стену): %d" % k, k)


def _hot_left(d, P, log):
    n = 0
    by = {}
    for o in d.get("plumbing", []):
        if o["kind"] in ("ХВС", "ГВС") and o.get("h", 0) > 0:
            by.setdefault(o.get("fixture", ""), []).append(o)
    for fx, lst in by.items():
        hots = [o for o in lst if o["kind"] == "ГВС"]
        colds = [o for o in lst if o["kind"] == "ХВС"]
        for h in hots:
            if not colds:
                continue
            c = min(colds, key=lambda q: math.hypot(q["x"] - h["x"], q["y"] - h["y"]))
            if math.hypot(c["x"] - h["x"], c["y"] - h["y"]) > 400:
                continue
            r = P.room_of_point((h["x"], h["y"]), 200)
            if r is None:
                continue
            nrm, _ = P.inward_normal((h["x"], h["y"]), r)
            f = (-nrm[0], -nrm[1])
            left = (-f[1], f[0])
            if (h["x"] - c["x"]) * left[0] + (h["y"] - c["y"]) * left[1] < 0:
                h["x"], c["x"] = c["x"], h["x"]
                h["y"], c["y"] = c["y"], h["y"]
                n += 1
    if n:
        L(log, "HOT_LEFT", "ГВС/ХВС поменяны местами: горячая слева при виде из помещения (%d прибор.)" % n, n)


def _multipoint(d, log):
    by = {}
    for s in d.get("switches", []):
        for c in s.get("controls", []):
            by.setdefault((c.get("group"), tuple(c.get("kinds") or ())), []).append((s, c))
    n = 0
    for (g, kinds), lst in by.items():
        if len(lst) < 2:
            continue
        modes = [c.get("mode") or ("pass" if s.get("pass_through") else None) for s, c in lst]
        need = len(lst) - 2
        if modes.count("pass") == 2 and modes.count("cross") == need:
            continue
        best = None
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                a, b = lst[i][0], lst[j][0]
                dd = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if best is None or dd > best[0]:
                    best = (dd, i, j)
        _, i, j = best
        for k, (s, c) in enumerate(lst):
            c["mode"] = "pass" if k in (i, j) else "cross"
            s.pop("pass_through", None)
        n += 1
        L(log, "MULTIPOINT", "«%s» из %d мест: %s - проходные%s" % (
            g, len(lst), ", ".join(lst[k][0]["id"] for k in (i, j)),
            ("; " + ", ".join(s["id"] for k, (s, c) in enumerate(lst) if k not in (i, j)) + " - перекрёстный") if need else ""))


def _wet_sockets(d, P, log):
    n = 0
    for s in d.get("sockets", []):
        r = P.room_of_point((s["x"], s["y"]), 60)
        if r is not None and r.get("cls") == "wet" and s["kind"] in ("Р", "Р2"):
            if s["kind"] == "Р2":
                s["note"] = (s.get("note", "") + " двойная").strip()
            s["kind"] = "РВ"
            n += 1
    if n:
        L(log, "WET_SOCKET", "розетки в санузлах заменены на влагозащищённые РВ IP44 (%d шт.)" % n, n)


def _elev_order(d, P, log):
    from shapely.ops import polylabel
    rooms = {}
    for e in d.get("elevations", []):
        rooms.setdefault(e.get("room") or e.get("group"), []).append(e)
    for name, es in rooms.items():
        r = P.room_by_name.get(name)
        if r is None or len(es) < 3:
            continue
        c = polylabel(r["shp"], 10)
        ang = {id(e): math.atan2((e["a"][1] + e["b"][1]) / 2.0 - c.y, (e["a"][0] + e["b"][0]) / 2.0 - c.x) for e in es}
        labels = sorted(e.get("label", "") for e in es)
        start = min(es, key=lambda e: e.get("label", ""))
        order = sorted(es, key=lambda e: (ang[id(start)] - ang[id(e)]) % (2 * math.pi))
        if [e.get("label") for e in order] != labels:
            for e, lab in zip(order, labels):
                e["label"] = lab
            L(log, "ELEV_ORDER", "развёртки «%s»: буквы по часовой стрелке" % name)


# ------------------------------------------------------------------ what remains for a human
def questions(d, P, rest):
    out = []
    seen = set()
    for i in rest:
        q = QUESTION_CODES.get(i["code"])
        if q is None:
            continue
        txt = "%s: %s" % (i["msg"], q)
        if txt not in seen:
            seen.add(txt)
            out.append(txt)
    for o in d.get("openings", []):
        if o.get("check") and not o.get("evidence"):
            out.append("%s: тип и ширина %d определены автоматически по разрыву стены - проверить по исходнику" % (o["id"], o["w"]))
    auto = [r["name"] for r in d.get("rooms", []) if r.get("auto") and not r.get("purpose_why")]
    unnamed = [n for n in auto if n.startswith("Помещение")]
    named = [n for n in auto if not n.startswith("Помещение")]
    if named:
        out.append("помещения %s названы по тому, что в них стоит в исходнике - проверить назначение" % ", ".join("«%s»" % n for n in named))
    if unnamed:
        out.append("помещения %s - назначение не определено (кухня, склад, кабинет...?): от него зависят отделка, свет, "
                   "розетки" % ", ".join("«%s»" % n for n in unnamed))
    lv = d.get("levels", {})
    if (d.get("_todo") or d.get("_draft")) and not lv.get("source"):
        out.append("высота потолка %d и плиты %d приняты по умолчанию - уточнить замером" % (lv.get("ceiling", 0), lv.get("slab", 0)))
    return out


def print_log(log, rest, qs):
    print("Автоисправления: %d" % len(log))
    for e in log:
        print("  + [%s] %s" % (e["code"], e["msg"]))
    V.print_report(rest)
    if qs:
        print("Вопросы к заказчику / проверить:")
        for q in qs:
            print("  ? " + q)
