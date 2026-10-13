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


def _auto_rooms(d, base_dir, log):
    """No rooms in a draft: every closed space of the plan becomes a room 'Помещение N' (name to be confirmed)."""
    if d.get("rooms") or not d.get("walls"):
        return
    from shapely.ops import unary_union, polylabel
    P = _P(dict(d, rooms=[]), base_dir)
    mass = P.mass
    outer = unary_union([Polygon(g.exterior) for g in (mass.geoms if hasattr(mass, "geoms") else [mass])])
    inner = outer.difference(mass)
    pieces = [g for g in (inner.geoms if hasattr(inner, "geoms") else [inner]) if g.area > 1.0e6]
    pieces.sort(key=lambda g: (-g.centroid.y, g.centroid.x))
    for i, g in enumerate(pieces, 1):
        c = polylabel(g, 10)
        d["rooms"].append(dict(num=str(i), name="Помещение %d" % i, seed=[T.snap(c.x), T.snap(c.y)], auto=True))
    if pieces:
        L(log, "ROOMS_AUTO", "помещения найдены по контуру стен: %d (названия - уточнить)" % len(pieces), len(pieces))


def _leaf(w, steel):
    std = STEEL_LEAVES if steel else LEAVES
    ok = [x for x in std if x <= w - (60 if steel else 80)]
    return max(ok) if ok else T.snap(w - 80, 10)


def _openings(d, P, log):
    ops = d.get("openings", [])
    used = {}
    for o in ops:
        m = re.match(r"^(ОК|ДБ|Д)-(\d+)$", str(o.get("mark", "")))
        if m:
            used[m.group(1)] = max(used.get(m.group(1), 0), int(m.group(2)))
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
            if sec == "plumbing" and o.get("h", 1) == 0:
                continue
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
        if o.get("check"):
            out.append("%s: тип и ширина %d определены автоматически по разрыву стены - проверить по исходнику" % (o["id"], o["w"]))
    lv = d.get("levels", {})
    if d.get("_todo") or d.get("_draft"):
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
