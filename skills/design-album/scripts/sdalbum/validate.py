# -*- coding: utf-8 -*-
"""Data QA on project.json: everything that makes a drawing *wrong* even if it looks clean.

Each rule returns issues dict(code, level, msg, where). Levels: error (block delivery) / warning (review).
Rules are deliberately concrete; every mistake found in real projects becomes a rule here (see references/lessons.md).
"""
import math
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

KNOWN_SOCKETS = ("Р", "Р2", "РВ", "Р32", "ТВ", "LAN", "КОНД", "БРА", "ВЫВ")
KNOWN_LIGHTS = ("spot", "spot_ip44", "spot2", "spot2_ip44", "surface", "chandelier", "pendant", "linear", "track",
                "track_rect", "track_spot", "led")
STACKABLE = {("kitchen_upper", "kitchen_base"), ("kitchen_upper", "fridge"), ("sink", "kitchen_base"), ("hob", "kitchen_base"),
             ("tv", "tv_stand"), ("tv", "cabinet"), ("mirror", "shoe_cabinet"), ("mirror", "cabinet"), ("rail", "wc"),
             ("basin", "wc"), ("mirror", "basin"), ("kitchen_upper", "sink"), ("kitchen_upper", "hob"), ("chair", "table"),
             ("kitchen_upper", "kitchen_base"), ("armchair", "table"), ("sofa", "table"), ("coffee", "counter"),
             ("pos", "counter"), ("grinder", "counter"), ("dishwasher", "counter"), ("heater", "sink"), ("heater", "basin"),
             ("heater", "cabinet"), ("mirror", "sink")}


def I(code, level, msg, where=None):
    return dict(code=code, level=level, msg=msg, where=[round(v) for v in where] if where else None)


def run(P):
    out = []
    out += _openings(P)
    out += _rooms(P)
    out += _furniture(P)
    out += _lighting(P)
    out += _switches(P)
    out += _sockets(P)
    out += _plumbing(P)
    out += _floors(P)
    out += _ceilings(P)
    out += _elevations(P)
    out += _doors(P)
    out += _multipoint(P)
    out += _hot_left(P)
    out += _snapped(P)
    out += _elev_order(P)
    return out


def _multipoint(P):
    """A light group switched from n places: 2 places -> two pass-through switches, 3+ -> 2 pass-through + cross."""
    out = []
    by = {}
    for s in P.switches:
        for c in s.get("controls", []):
            key = (c.get("group"), tuple(c.get("kinds") or ()))
            by.setdefault(key, []).append((s, c))
    for (g, kinds), lst in by.items():
        n = len(lst)
        if n < 2:
            continue
        modes = [c.get("mode") or ("pass" if s.get("pass_through") else None) for s, c in lst]
        need_cross = n - 2
        ok = modes.count("pass") == 2 and modes.count("cross") == need_cross
        if not ok:
            out.append(I("SWITCH_MULTIPOINT", "error", "«%s» управляется из %d мест (%s): нужны 2 проходных%s, указано: %s" % (
                g, n, ", ".join(s["id"] for s, _ in lst), " + %d перекрёстный" % need_cross if need_cross else "",
                ", ".join(m or "обычный" for m in modes))))
    return out


def _hot_left(P):
    """Hot water outlet to the LEFT of the cold one as seen from the room (sanitary practice)."""
    out = []
    by = {}
    for o in P.plumbing:
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
            n, _ = P.inward_normal((h["x"], h["y"]), r)
            f = (-n[0], -n[1])                    # viewer faces the wall
            left = (-f[1], f[0])
            if (h["x"] - c["x"]) * left[0] + (h["y"] - c["y"]) * left[1] < 0:
                out.append(I("WATER_HOT_LEFT", "warning", "%s: ГВС справа от ХВС (при виде из помещения горячая - слева)" % fx,
                             (h["x"], h["y"])))
    return out


def _snapped(P):
    """Positions from a 3D model come with 1-mm noise (439 / 1022 / 1059): drawings want a 5-mm module."""
    bad = []
    for lst, name in ((P.lighting, "светильник"), (P.sockets, "розетка"), (P.switches, "выключатель"), (P.plumbing, "вывод")):
        for o in lst:
            keep = _face_coord(P, o) if lst is not P.lighting else None
            for k in ("x", "y", "x2", "y2"):
                v = o.get(k)
                if k == keep:          # a point on a wall face keeps the face coordinate (walls from a survey)
                    continue
                if v is not None and abs(v - 5 * round(v / 5.0)) > 0.01:
                    bad.append("%s %s=%s" % (name, k, ("%.1f" % v).rstrip("0").rstrip(".")))
                    break
    for f in P.furniture:
        if any(abs(c - 5 * round(c / 5.0)) > 0.01 for pt in f.get("poly", []) for c in pt[:2]):
            bad.append("мебель «%s»" % f["name"])
    if bad:
        return [I("POINT_NOT_SNAPPED", "warning", "%d позиций не кратны 5 мм (шум модели), напр.: %s" % (len(bad), "; ".join(bad[:4])))]
    return []


def _face_coord(P, o):
    """'x' / 'y' - the coordinate across the wall of a point lying on a wall face (within 1 mm), else None."""
    r = P.room_of_point((o["x"], o["y"]), 40)
    if r is None or r["shp"].exterior.distance(Point(o["x"], o["y"])) > 1.0:
        return None
    n = NORM.get(o.get("wall")) if o.get("wall") else None
    if n is None:
        n, _ = P.inward_normal((o["x"], o["y"]), r)
    return "x" if abs(n[0]) > 0.5 else "y"


def _elev_order(P):
    """Elevation labels of one room go clockwise (as the plan markers are read)."""
    out = []
    from shapely.ops import polylabel
    rooms = {}
    for e in P.elevations:
        rooms.setdefault(e.get("room") or e.get("group"), []).append(e)
    for name, es in rooms.items():
        r = P.room_by_name.get(name)
        if r is None or len(es) < 3:
            continue
        c = polylabel(r["shp"], 10)
        ang = []
        for e in sorted(es, key=lambda e: e.get("label", "")):
            mx, my = (e["a"][0] + e["b"][0]) / 2.0, (e["a"][1] + e["b"][1]) / 2.0
            ang.append(math.atan2(my - c.y, mx - c.x))
        steps = [((ang[i] - ang[i + 1]) % (2 * math.pi)) for i in range(len(ang) - 1)]
        if not all(0 < st < math.pi * 1.2 for st in steps):          # clockwise = decreasing angle
            out.append(I("ELEV_LABEL_ORDER", "warning", "развёртки «%s»: буквы %s идут не по часовой стрелке" % (
                name, ", ".join(e.get("label", "") for e in sorted(es, key=lambda e: e.get("label", ""))))))
    return out


def _openings(P):
    out = []
    for o in P.openings:
        w = P.wall_by_id.get(o["wall"])
        if w is None:
            out.append(I("OPENING_NO_WALL", "error", "%s: стена %s не найдена" % (o["id"], o["wall"])))
            continue
        x0, y0, x1, y1 = w["shape"].bounds
        lo, hi = (x0, x1) if w["dir"] == "H" else (y0, y1)
        if o["c"] - o["w"] / 2 < lo - 1 or o["c"] + o["w"] / 2 > hi + 1:
            out.append(I("OPENING_OUT_OF_WALL", "error", "%s выходит за пределы стены %s" % (o["id"], o["wall"]), P.open_shape[o["id"]].centroid.coords[0]))
        if o["kind"] == "window" and o.get("sill", 0) + o["h"] > P.slab:
            out.append(I("WINDOW_TOO_HIGH", "error", "%s: верх окна выше плиты" % o["id"]))
        if o["kind"] in ("door", "balcony"):
            fr = o.get("frame", 40)
            leaf = o.get("leaf")
            if leaf and leaf > o["w"] - fr - 10:
                out.append(I("LEAF_WIDER_THAN_OPENING", "error", "%s: полотно %d не помещается в проём %d" % (o["id"], leaf, o["w"])))
            sl = o.get("leaf_in_source")
            if sl and abs(sl - o.get("leaf", o["w"] - 2 * fr)) > 50:
                out.append(I("LEAF_SOURCE_CONFLICT", "warning", "%s: в исходнике полотно %d, в проекте %d - решить с заказчиком"
                             % (o["id"], sl, o.get("leaf", o["w"] - 2 * fr))))
            if o["h"] > P.ceiling:
                out.append(I("DOOR_ABOVE_CEILING", "error", "%s: высота проёма больше высоты потолка" % o["id"]))
    by_wall = {}
    for o in P.openings:
        by_wall.setdefault(o["wall"], []).append(o)
    for wid, os_ in by_wall.items():
        os_ = sorted(os_, key=lambda o: o["c"])
        for a, b in zip(os_[:-1], os_[1:]):
            if a["c"] + a["w"] / 2 > b["c"] - b["w"] / 2 - 50:
                out.append(I("OPENINGS_OVERLAP", "error", "%s и %s в стене %s перекрываются / простенок < 50 мм" % (a["id"], b["id"], wid)))
    return out


def _rooms(P):
    out = []
    if not P.rooms:
        return [I("NO_ROOMS", "error", "не заданы помещения")]
    from .dims import outline_of
    interior = outline_of(P).difference(P.mass)
    covered = unary_union([r["shp"] for r in P.rooms] + list(getattr(P, "passages", [])))
    rest = interior.difference(covered.buffer(2))
    for g in (rest.geoms if hasattr(rest, "geoms") else [rest]):
        if g.area > 0.3e6:
            out.append(I("ROOM_GAP", "warning", "область %.2f м² не отнесена ни к одному помещению" % (g.area / 1e6), g.centroid.coords[0]))
    names = [r["name"] for r in P.rooms]
    for n in set(names):
        if names.count(n) > 1:
            out.append(I("ROOM_DUP_NAME", "error", "повтор имени помещения «%s» (нужны уникальные имена)" % n))
    for r in P.rooms:
        if r["area"] < 0.5:
            out.append(I("ROOM_TINY", "warning", "помещение «%s» площадью %.2f м²" % (r["name"], r["area"])))
    return out


def _furniture(P):
    out = []
    items = []
    for f in P.furniture:
        try:
            g = Polygon(f["poly"]).buffer(0)
        except Exception:
            out.append(I("FURN_BAD_POLY", "error", "«%s»: некорректный контур" % f.get("name")))
            continue
        items.append((f, g))
        r = P.room_by_name.get(f.get("room"))
        if r is None:
            out.append(I("FURN_NO_ROOM", "warning", "«%s»: помещение «%s» не найдено" % (f["name"], f.get("room")), g.centroid.coords[0]))
            continue
        outside = g.difference(r["shp"].buffer(30)).area
        if outside > 0.05 * g.area and outside > 0.01e6:
            out.append(I("FURN_OUTSIDE_ROOM", "error", "«%s» выходит за пределы «%s» на %.2f м²" % (f["name"], r["name"], outside / 1e6),
                         g.centroid.coords[0]))
        if g.intersection(P.mass).area > 0.05 * g.area and f.get("kind") not in ("rail", "mirror", "tv"):
            out.append(I("FURN_IN_WALL", "error", "«%s» заходит в стену" % f["name"], g.centroid.coords[0]))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (fa, ga), (fb, gb) = items[i], items[j]
            ka, kb = fa.get("kind"), fb.get("kind")
            if "rug" in (ka, kb) or (ka, kb) in STACKABLE or (kb, ka) in STACKABLE:
                continue
            ov = ga.intersection(gb).area
            if ov > 0.002e6:                    # 2000 mm² - two wardrobes overlapping by 47 mm must be caught
                out.append(I("FURN_OVERLAP", "warning", "«%s» и «%s» пересекаются (%.2f м²)" % (fa["name"], fb["name"], ov / 1e6),
                             ga.intersection(gb).centroid.coords[0]))
    return out


def _lighting(P):
    out = []
    pts = []
    tracks = []
    for f in P.lighting:
        if f["kind"] not in KNOWN_LIGHTS:
            out.append(I("LIGHT_KIND", "warning", "неизвестный тип светильника %s" % f["kind"], (f["x"], f["y"])))
        if f["kind"] in ("track", "linear", "led"):
            tracks.append(LineString([(f["x"], f["y"]), (f["x2"], f["y2"])]))
        elif f["kind"] == "track_rect":
            tracks.append(box(f["x"], f["y"], f["x2"], f["y2"]).exterior)
        else:
            pts.append(f)
        if P.room_of_point((f["x"], f["y"]), 10) is None:
            out.append(I("LIGHT_OUTSIDE", "error", "светильник %s вне помещений" % f["kind"], (f["x"], f["y"])))
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            a, b = pts[i], pts[j]
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 60:
                out.append(I("LIGHT_DUPLICATE", "error", "два светильника в одной точке (%s / %s) - дубль?" % (a["kind"], b["kind"]), (a["x"], a["y"])))
    for f in pts:
        if f["kind"] == "track_spot":
            if not tracks or min(t.distance(Point(f["x"], f["y"])) for t in tracks) > 80:
                out.append(I("TRACK_SPOT_OFF_TRACK", "warning", "трековый спот не на шинопроводе", (f["x"], f["y"])))
    groups = set(f.get("group") for f in P.lighting)
    for s in P.switches:
        for c in s.get("controls", []):
            if c.get("group") not in groups:
                out.append(I("SWITCH_GROUP_MISSING", "error", "%s управляет группой «%s», которой нет среди светильников" % (s["id"], c.get("group"))))
    controlled = set(c.get("group") for s in P.switches for c in s.get("controls", []))
    for g in groups:
        if P.switches and g not in controlled:
            out.append(I("LIGHT_GROUP_NO_SWITCH", "warning", "группа светильников «%s» без выключателя" % g))
    return out


NORM = {"X+": (1, 0), "X-": (-1, 0), "Y+": (0, 1), "Y-": (0, -1)}


def _on_wall(P, x, y, wall, tol, label, prefix):
    out = []
    r = P.room_of_point((x, y), tol + 20)
    if r is None:
        return [I(prefix + "_NOT_ON_WALL", "error", "%s: точка вне помещений" % label, (x, y))]
    d = r["shp"].exterior.distance(Point(x, y))
    if d > tol:
        out.append(I(prefix + "_NOT_ON_WALL", "error", "%s: не на стене (%.0f мм от поверхности)" % (label, d), (x, y)))
    if wall:
        n, _ = P.inward_normal((x, y), r)
        e = NORM.get(wall)
        if e and (abs(n[0] - e[0]) > 0.5 or abs(n[1] - e[1]) > 0.5):
            out.append(I(prefix + "_WALL_SIDE", "error", "%s: сторона %s не совпадает с нормалью стены (%+.0f,%+.0f)" % (label, wall, n[0], n[1]), (x, y)))
    return out


def _switches(P):
    out = []
    for s in P.switches:
        out += _on_wall(P, s["x"], s["y"], s.get("wall"), 30, "выключатель %s" % s["id"], "SWITCH")
        h = s.get("h", 900)
        if not 600 <= h <= 1200:
            out.append(I("SWITCH_HEIGHT", "warning", "выключатель %s на высоте %d" % (s["id"], h), (s["x"], s["y"])))
    ids = [s["id"] for s in P.switches]
    for i in set(ids):
        if ids.count(i) > 1:
            out.append(I("SWITCH_DUP", "error", "повтор марки выключателя %s" % i))
    return out


def _sockets(P):
    out = []
    for s in P.sockets:
        lab = "розетка %s (%d,%d)" % (s["kind"], s["x"], s["y"])
        if s["kind"] not in KNOWN_SOCKETS:
            out.append(I("SOCKET_KIND", "warning", "%s: неизвестный тип" % lab, (s["x"], s["y"])))
        if s.get("mount") == "furniture":       # built into a counter / cabinet: on its face, not on a wall
            pt = Point(s["x"], s["y"])
            if not any(Polygon(f["poly"]).buffer(0).exterior.distance(pt) <= 30 for f in P.furniture if f.get("poly")):
                out.append(I("SOCKET_NOT_ON_FURNITURE", "error", "%s: не на корпусе мебели" % lab, (s["x"], s["y"])))
        else:
            out += _on_wall(P, s["x"], s["y"], s.get("wall"), 30, lab, "SOCKET")
        if not 150 <= s.get("h", 300) <= 2600:
            out.append(I("SOCKET_HEIGHT", "warning", "%s: высота %d" % (lab, s.get("h", 0)), (s["x"], s["y"])))
        if s.get("group") in (None, ""):
            out.append(I("SOCKET_NO_GROUP", "warning", "%s: не задана группа щита" % lab, (s["x"], s["y"])))
        r = P.room_of_point((s["x"], s["y"]), 60)
        if r is not None and r.get("cls") == "wet" and s["kind"] in ("Р", "Р2"):
            out.append(I("SOCKET_WET", "error", "%s в санузле - должна быть влагозащищённая (РВ)" % lab, (s["x"], s["y"])))
    return out


def _plumbing(P):
    out = []
    for o in P.plumbing:
        lab = "вывод %s (%s)" % (o["kind"], o.get("fixture", ""))
        if o.get("h", 0) == 0:
            if P.room_of_point((o["x"], o["y"]), 10) is None:
                out.append(I("DRAIN_OUTSIDE", "error", "%s вне помещений" % lab, (o["x"], o["y"])))
            continue
        out += _on_wall(P, o["x"], o["y"], None, 160, lab, "WATER")
        if not 50 <= o["h"] <= 2200:
            out.append(I("WATER_HEIGHT", "warning", "%s: высота %d" % (lab, o["h"]), (o["x"], o["y"])))
    return out


def _floors(P):
    out = []
    zones = P.floor_zones()
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            ov = zones[i][1].intersection(zones[j][1]).area
            if ov > 0.1e6:
                out.append(I("FLOOR_OVERLAP", "error", "покрытия %s и %s перекрываются (%.2f м²)" % (zones[i][0]["id"], zones[j][0]["id"], ov / 1e6)))
    if zones:
        allz = unary_union([g for _, g in zones])
        for r in P.rooms:
            cov = r["shp"].intersection(allz).area / r["shp"].area
            if cov < 0.95:
                out.append(I("FLOOR_UNCOVERED", "warning", "«%s»: покрытие пола задано на %.0f%% площади" % (r["name"], cov * 100)))
    return out


def _ceilings(P):
    out = []
    if P.ceiling > P.slab:
        out.append(I("CEILING_ABOVE_SLAB", "error", "потолок %d выше плиты %d" % (P.ceiling, P.slab)))
    rooms = unary_union([r["shp"] for r in P.rooms] + list(getattr(P, "passages", []))) if P.rooms else Polygon()
    for z in P.ceilings.get("zones", []):
        g = Polygon(z["poly"]).buffer(0)
        if g.difference(rooms.buffer(20)).area > 0.02e6:
            out.append(I("CEILING_ZONE_OUTSIDE", "warning", "зона потолка «%s» выходит за помещения" % z.get("name", z.get("type"))))
        if z.get("bottom") and z["bottom"] >= P.ceiling:
            out.append(I("BULKHEAD_LEVEL", "error", "короб «%s»: низ %d не ниже потолка %d" % (z.get("name", ""), z["bottom"], P.ceiling)))
    return out


def _elevations(P):
    out = []
    from .sheets_details import Elev
    for e in P.elevations:
        E = Elev(P, e)
        lab = "развёртка %s %s" % (e.get("group", ""), e.get("label", ""))
        r = P.room_by_name.get(e.get("room") or e.get("group"))
        if r is not None:
            d = max(r["shp"].exterior.distance(Point(E.a)), r["shp"].exterior.distance(Point(E.b)))
            if d > 30:
                out.append(I("ELEV_NOT_ON_WALL", "error", "%s: концы стены не на контуре помещения (%.0f мм)" % (lab, d)))
            # seen from inside: room must be on the right-hand side of a->b ... i.e. left of the viewer facing the wall
            mid = ((E.a[0] + E.b[0]) / 2, (E.a[1] + E.b[1]) / 2)
            n = (E.ux[1], -E.ux[0])
            if not r["shp"].contains(Point(mid[0] + n[0] * 60, mid[1] + n[1] * 60)):
                out.append(I("ELEV_MIRRORED", "error", "%s: направление a->b даёт зеркальный вид (смотреть из помещения: слева направо)" % lab))
        for zn in e.get("zones", []):
            if zn["s0"] < -2 or zn["s1"] > E.L + 2 or zn["z0"] < -2 or zn["z1"] > E.H + 2:
                out.append(I("ELEV_ZONE_OUT", "error", "%s: зона отделки вне стены" % lab))
        for it in e.get("items", []):
            if it.get("type") == "worktop" and not 850 <= it["z1"] <= 950:
                out.append(I("WORKTOP_HEIGHT", "warning", "%s: столешница на %d (норма 850-950)" % (lab, it["z1"])))
        out += _chain_quality(lab, "высоты", e.get("heights"))
        out += _chain_quality(lab, "модули", e.get("module_chain"))
        out += _modules_equal(lab, e)
    return out


def _chain_quality(lab, what, vals, min_gap=15.0):
    """A 3D model exported to drawings leaves slivers (13 mm between a cabinet and the ceiling, 4 mm between
    fronts). On a drawing they look like mistakes: flag them so the designer snaps or explains them (filler, gap)."""
    out = []
    if not vals:
        return out
    v = sorted(vals)
    for a, b in zip(v[:-1], v[1:]):
        if 0 < b - a < min_gap:
            out.append(I("ELEV_SMALL_GAP", "warning", "%s, %s: отрезок %d мм (%d-%d) - привести к модулю или пояснить "
                         "(планка, зазор)" % (lab, what, round(b - a), round(a), round(b))))
    for x in v:
        if abs(x - round(x)) > 0.01 or round(x) % 5 != 0:
            out.append(I("NOT_SNAPPED", "warning", "%s, %s: значение %s не кратно 5 мм - вероятно, неточность 3D-модели"
                         % (lab, what, ("%.1f" % x).rstrip("0").rstrip("."))))
            break
    return out


def _modules_equal(lab, e):
    """Fronts of one row that differ by a few millimetres are meant to be equal (model noise)."""
    out = []
    rows = {}
    for it in e.get("items", []):
        if it.get("type") in ("base", "upper"):
            rows.setdefault(it["type"], []).append(it["s1"] - it["s0"])
    for t, ws in rows.items():
        if len(ws) >= 2 and 0 < max(ws) - min(ws) <= 25:
            out.append(I("MODULES_NEAR_EQUAL", "warning", "%s: модули «%s» почти равны (%s мм) - выровнять или подтвердить"
                         % (lab, t, "/".join(str(round(w)) for w in ws))))
    return out


def _doors(P):
    out = []
    from .symbols import door_swing_area
    swings = []
    for o in P.openings:
        if o["kind"] in ("door", "balcony"):
            try:
                swings.append((o, door_swing_area(P, o)))
            except Exception:
                continue
    for o, g in swings:
        for f in P.furniture:
            if f.get("kind") in ("rug", "kitchen_upper", "mirror", "rail"):
                continue
            fg = Polygon(f["poly"]).buffer(0)
            ov = g.intersection(fg).area
            if ov > 0.02e6:
                out.append(I("DOOR_HITS_FURNITURE", "warning", "дверь %s при открывании задевает «%s»" % (o["id"], f["name"]),
                             g.intersection(fg).centroid.coords[0]))
    for i in range(len(swings)):
        for j in range(i + 1, len(swings)):
            ov = swings[i][1].intersection(swings[j][1]).area
            if ov > 0.02e6:
                out.append(I("DOORS_CLASH", "warning", "двери %s и %s задевают друг друга" % (swings[i][0]["id"], swings[j][0]["id"])))
    return out


def print_report(issues):
    e = sum(1 for i in issues if i["level"] == "error")
    w = sum(1 for i in issues if i["level"] == "warning")
    print("Данные: ошибок %d, предупреждений %d" % (e, w))
    for i in sorted(issues, key=lambda x: (x["level"] != "error", x["code"])):
        print("  [%s] %s %s  %s" % ("E" if i["level"] == "error" else "w", i["code"], i.get("where") or "", i["msg"]))
