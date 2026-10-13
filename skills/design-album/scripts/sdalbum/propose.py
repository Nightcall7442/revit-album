# -*- coding: utf-8 -*-
"""Design proposal by norms: fills EMPTY sections of project.json the way an experienced designer would start,
so a bare plan (walls + openings + rooms [+ furniture]) becomes a complete album. Never overwrites given data;
every generated item carries "proposed": true and the sheets get a note "проектное предложение - согласовать".

    data2, log = propose(data, base_dir, sections=None)

Rules (references/drawing-standards.md):
  floors     plank in living rooms (laid along the light from the main window), porcelain 600x600 in kitchen /
             hall, porcelain + waterproofing in wet rooms
  ceilings   Т1 plasterboard, Т2 moisture-resistant plasterboard in wet rooms, at the clear ceiling level
  finishes   О1 paint, О2 tiles in wet rooms, О3 kitchen apron behind the base units
  plumbing   outlets behind every fixture (basin, sink, wc, shower, bath, washer) at typical heights, hot on the left
  lighting   spots by the lumen method (E: living / kitchen 150 lx, hall / wet 50 lx, Ф 500 lm, η 0.45, Кз 1.25),
             even grid >= 300 mm from walls, none above wardrobes / upper units; pendant over a dining table;
             LED strip under kitchen upper units
  switches   at the room entrance on the latch side (150 mm from the opening, h 900); wet rooms - outside the door;
             bedroom - second (pass-through) switch at the bed, h 700; neighbouring switches merged into one block
  sockets    СП 256.1325800: living room - 1 per started 4 m of perimeter, kitchen >= 4, hall - 1 per started 10 m²;
             by furniture: bed (h 600 at nightstands), TV (Р2 + TV + LAN), worktop (h 1100, away from sink / hob),
             fridge, hob 32 A, hood, dishwasher, washer (IP44), basin (IP44 for a hair dryer, >= 600 from a shower),
             air conditioner outlet in living rooms with a window (hot climate); the rest spread evenly at h 300
  panel      ЩК in the entrance hall near the entrance door, bottom 1500
  circuits   recommended group table; every socket gets its group
"""
import copy
import math
import re

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from . import model as M
from . import topo as T

SECTIONS = ("floors", "ceilings", "finishes", "plumbing", "lighting", "switches", "sockets", "panel", "circuits")
LUX = {"living": 150, "kitchen": 150, "wet": 50, "circulation": 50, "storage": 75}
FLUX, ETA, KZ = 500.0, 0.45, 1.25
MIN_SPOTS = {"living": 4, "kitchen": 4, "wet": 2, "circulation": 2, "storage": 1}
BLOCK_WALL = ("wardrobe", "kitchen_base", "fridge", "shower", "bath", "wc", "basin", "washer", "sofa", "bed",
              "cabinet", "shoe_cabinet", "tv_stand", "armchair", "nightstand")
NO_LIGHT_ABOVE = ("wardrobe", "kitchen_upper", "fridge", "cabinet")
LIGHT_SPEC = {"spot": "Светильник встраиваемый поворотный, GU10, 7 Вт, 3000 K",
              "spot2": "Светильник встраиваемый двойной карданный, 2×GU10, 2×7 Вт, 3000 K",
              "spot2_ip44": "Светильник встраиваемый двойной IP44, 2×GU10",
              "spot_ip44": "Светильник встраиваемый влагозащищённый IP44, GU10, 7 Вт",
              "pendant": "Светильник подвесной над столом",
              "led": "Светодиодная лента 24 В, 9,6 Вт/м, в профиле"}


def propose(data, base_dir=".", sections=None):
    d = copy.deepcopy(data)
    log = []
    want = tuple(sections or SECTIONS)
    P = M.Project(d, base_dir)
    if not P.rooms:
        return d, log
    if "floors" in want and not d.get("floors"):
        _floors(d, P, log)
    if "ceilings" in want and not d.get("ceilings", {}).get("types"):
        _ceilings(d, P, log)
    if "finishes" in want and not d.get("finishes", {}).get("types"):
        _finishes(d, P, log)
    P = M.Project(d, base_dir)
    if "plumbing" in want and not d.get("plumbing"):
        _plumbing(d, P, log)
    if "lighting" in want and not d.get("lighting"):
        _lighting(d, P, log)
    P = M.Project(d, base_dir)
    if "switches" in want and not d.get("switches") and d.get("lighting"):
        _switches(d, P, log)
    P = M.Project(d, base_dir)
    if "sockets" in want and not d.get("sockets"):
        _sockets(d, P, log)
    P = M.Project(d, base_dir)
    if "panel" in want and not d.get("panel") and d.get("sockets"):
        _panel(d, P, log)
    if "circuits" in want and not d.get("circuits") and d.get("sockets"):
        _circuits(d, P, log)
    if log:
        qs = d.setdefault("meta", {}).setdefault("questions", [])
        txt = "Разделы %s выполнены как проектное предложение агента по нормам - подтвердить или скорректировать." % (
            ", ".join(sorted(set(e["section"] for e in log))))
        if txt not in qs:
            qs.append(txt)
    return d, log


def L(log, section, msg, n=0):
    log.append(dict(code="PROPOSE", section=section, msg=msg, n=n))


def _note(d, key, text):
    notes = d.setdefault("notes", {})
    cur = notes.get(key)
    if isinstance(cur, list):
        if text not in cur:
            cur.append(text)
        return
    cur = cur or {}
    add = cur.setdefault("add", [])
    if text not in add:
        add.append(text)
    notes[key] = cur


# ------------------------------------------------------------------ geometry helpers
def _room_of(P, f, g):
    r = P.room_by_name.get(f.get("room"))
    if r is None:
        c = g.representative_point()
        r = P.room_of_point((c.x, c.y), 300)
    return r


def _left(n):
    return (n[1], -n[0])


def _on_face_point(P, room, q, n, along, clear=40):
    """Point on the face at q moved `along` (mm) along the wall; None if it leaves a free face of the room."""
    t = (-n[1], n[0])
    p = (q[0] + t[0] * along, q[1] + t[1] * along)
    return _validate_face(P, room, p, n, clear)


def _validate_face(P, room, p, n, clear=40):
    best = None
    for seg, nn in T.wall_faces(P, room, clear):
        if abs(nn[0] - n[0]) > 0.5 or abs(nn[1] - n[1]) > 0.5:
            continue
        dd = seg.distance(Point(p))
        if dd < 2 and (best is None or dd < best[0]):
            q = seg.interpolate(seg.project(Point(p)))
            best = (dd, (q.x, q.y))
    if best is None:
        return None
    x, y = best[1]
    if abs(n[0]) > 0.5:
        return (_r(x), T.snap(y))
    return (T.snap(x), _r(y))


def _r(v):
    return int(round(v)) if abs(v - round(v)) < 0.05 else round(v, 1)


def _pt(kind, p, h, n, **kw):
    o = dict(kind=kind, x=p[0], y=p[1], h=h, wall=T.normal_code(n))
    o.update(kw)
    o["proposed"] = True
    return o


def _fixture_back(P, f, g, room):
    if f.get("head") and f.get("kind") == "bed":
        hd = {"W": (-1, 0), "E": (1, 0), "S": (0, -1), "N": (0, 1)}[f["head"]]
        n = (-hd[0], -hd[1])
        x0, y0, x1, y1 = g.bounds
        edge = {(-1, 0): x0, (1, 0): x1, (0, -1): y0, (0, 1): y1}[hd]
        c = g.centroid
        p = (edge, c.y) if hd[1] == 0 else (c.x, edge)
        res = T.project_to_face(P, p, room, max_d=250)
        if res is not None and abs(res[1][0] - n[0]) < 0.5 and abs(res[1][1] - n[1]) < 0.5:
            seg = None
            return seg, n, res[0]
    return T.back_side(P, g, room)


# ------------------------------------------------------------------ floors / ceilings / finishes
def _floors(d, P, log):
    by = {"plank": [], "tile": [], "wet": []}
    for r in P.rooms:
        c = r.get("cls", "living")
        by["wet" if c == "wet" else "tile" if c in ("kitchen", "circulation") else "plank"].append(r["name"])
    out = []
    if by["plank"]:
        along = _plank_direction(P, by["plank"])
        out.append(dict(id="П1", material="Ламинат 33 класс, планка 1380×193", pattern="plank", plank=[1380, 193], along=along,
                        rooms=by["plank"], layers="Ламинат 8 мм; подложка 3 мм; стяжка", reserve=0.1, proposed=True))
    if by["tile"]:
        out.append(dict(id="П%d" % (len(out) + 1), material="Керамогранит 600×600", pattern="tile", tile=[600, 600],
                        rooms=by["tile"], layers="Керамогранит 10 мм; плиточный клей; стяжка", reserve=0.1, proposed=True))
    if by["wet"]:
        out.append(dict(id="П%d" % (len(out) + 1), material="Керамогранит 600×600 (санузлы)", pattern="tile", tile=[600, 600],
                        rooms=by["wet"], layers="Керамогранит 10 мм; плиточный клей; обмазочная гидроизоляция с заведением на стены 200 мм; стяжка",
                        reserve=0.1, proposed=True))
    d["floors"] = out
    _note(d, "floors", "Покрытия - проектное предложение: материал и раскладку согласовать с заказчиком.")
    L(log, "полы", "полы по назначению помещений: %s" % "; ".join("%s - %s" % (f["id"], f["material"]) for f in out), len(out))


def _plank_direction(P, names):
    """Planks run along the light: perpendicular to the wall of the biggest window of the biggest room."""
    rooms = sorted((P.room_by_name[n] for n in names), key=lambda r: -r["area"])
    for r in rooms:
        wins = [(o, n) for o, n, fp in T.room_openings(P, r, kinds=("window", "balcony"))]
        if wins:
            o, n = max(wins, key=lambda q: q[0]["w"])
            return "y" if abs(n[1]) > 0.5 else "x"
    r = rooms[0]
    x0, y0, x1, y1 = r["shp"].bounds
    return "x" if x1 - x0 >= y1 - y0 else "y"


def _ceilings(d, P, log):
    lvl = P.ceiling
    lt = ("+%.3f" % (lvl / 1000.0)).replace(".", ",")
    types = [dict(id="Т1", short="потолок ГКЛ, окраска, %s" % lt, desc="ГКЛ 12,5 мм по металлокаркасу, шпатлёвка, окраска", level=lvl,
                  proposed=True)]
    wet = [r for r in d["rooms"] if P.room_by_name[r["name"]].get("cls") == "wet"]
    if wet:
        types.append(dict(id="Т2", short="потолок ГКЛВ, влагостойкая окраска, %s" % lt,
                          desc="ГКЛВ 12,5 мм по металлокаркасу, шпатлёвка, влагостойкая окраска", level=lvl, proposed=True))
    for r in d["rooms"]:
        r.setdefault("ceiling_type", "Т2" if wet and P.room_by_name[r["name"]].get("cls") == "wet" else "Т1")
    d.setdefault("ceilings", {})["types"] = types
    d["ceilings"].setdefault("zones", [])
    L(log, "потолки", "потолки: Т1 ГКЛ%s на отм. %s" % (", Т2 ГКЛВ в санузлах" if wet else "", lt), len(types))


def _finishes(d, P, log):
    types = [dict(id="О1", desc="Окраска интерьерной матовой краской по подготовленной поверхности", rgb=[205, 205, 210], proposed=True)]
    by_class = {}
    if any(r.get("cls") == "wet" for r in P.rooms):
        types.append(dict(id="О2", desc="Керамическая плитка / керамогранит на всю высоту (санузлы)", rgb=[60, 130, 200], proposed=True))
        by_class["wet"] = "О2"
    segs = []
    for f, g in T.furniture_shapes(P, ("kitchen_base",)):
        room = _room_of(P, f, g)
        if room is None:
            continue
        back = T.back_side(P, g, room)
        if back is None:
            continue
        seg, n, q = back
        x0, y0, x1, y1 = g.bounds
        if abs(n[0]) > 0.5:
            a, b = [q[0], max(y0, seg.bounds[1])], [q[0], min(y1, seg.bounds[3])]
        else:
            a, b = [max(x0, seg.bounds[0]), q[1]], [min(x1, seg.bounds[2]), q[1]]
        segs.append(dict(type="О3", a=[_r(v) for v in a], b=[_r(v) for v in b], proposed=True))
    if segs:
        types.append(dict(id="О3", desc="Фартук: керамическая плитка / стеновая панель, h 550-650 над столешницей", rgb=[200, 160, 110],
                          proposed=True))
    d["finishes"] = dict(types=types, by_class=by_class, segments=segs)
    L(log, "отделка", "отделка стен: О1 окраска%s%s" % (", О2 плитка в санузлах" if by_class else "", ", О3 фартук кухни" if segs else ""),
      len(types))


# ------------------------------------------------------------------ plumbing
def _plumbing(d, P, log):
    out, skipped = [], []
    for f, g in T.furniture_shapes(P, ("basin", "sink", "wc", "shower", "bath", "washer")):
        room = _room_of(P, f, g)
        if room is None:
            continue
        kind = f["kind"]
        name = {"basin": "Раковина", "sink": "Мойка", "wc": "Унитаз", "shower": "Смеситель душа", "bath": "Ванна",
                "washer": "Стиральная машина"}[kind]
        if kind == "shower":
            c = g.centroid
            out.append(dict(kind="К50", x=T.snap(c.x), y=T.snap(c.y), h=0, fixture="Трап душевой", proposed=True))
        back = T.back_side(P, g, room)
        if back is None:
            skipped.append(f["name"])
            continue
        seg, n, q = back
        lf = _left(n)
        hung = "подвес" in f.get("name", "").lower() or f.get("hung")

        def at(along, kd, h, fx=name):
            p = _on_face_point(P, room, q, n, -along, clear=10)         # +along = to the viewer's left
            if p is None:
                return False
            out.append(dict(kind=kd, x=p[0], y=p[1], h=h, fixture=fx, proposed=True))
            return True
        # along > 0 means to the viewer's left: _on_face_point moves along t = (-n1, n0) = -left
        if kind in ("basin", "sink"):
            hh = 550
            ok = at(50, "ГВС", hh) and at(-50, "ХВС", hh) and at(0, "К50", 450 if kind == "basin" else 500)
        elif kind == "wc":
            ok = at(150, "ХВС", 1000 if hung else 200) and at(0, "К110", 230 if hung else 180)
        elif kind == "shower":
            ok = at(75, "ГВС", 1100) and at(-75, "ХВС", 1100)
        elif kind == "bath":
            ok = at(75, "ГВС", 800) and at(-75, "ХВС", 800) and at(0, "К50", 100, "Ванна (слив)")
        else:
            ok = at(150, "ХВС", 600) and at(-100, "К50", 600)
        if not ok:
            skipped.append(f["name"])
    if not out:
        return
    d["plumbing"] = out
    _note(d, "plumbing", "Выводы - проектное предложение по типовым высотам: уточнить по паспортам выбранной сантехники.")
    L(log, "сантехника", "выводы ХВС/ГВС/канализации у %d приборов (горячая слева)%s" % (
        len({o["fixture"] for o in out}), "; не размещены: " + ", ".join(skipped) if skipped else ""), len(out))


# ------------------------------------------------------------------ lighting
def _lighting(d, P, log):
    out = []
    blocked = unary_union([g.buffer(100) for f, g in T.furniture_shapes(P, NO_LIGHT_ABOVE)] or [Polygon()])
    summary = []
    for r in P.rooms:
        cls = r.get("cls", "living")
        E = LUX.get(cls, 150)
        big = r["area_exact"] > 30.0          # a hall: double cardan fixtures (~1000 lm), not a forest of GU10 spots
        flux = FLUX * (2 if big else 1)
        n = max(MIN_SPOTS.get(cls, 2), int(math.ceil(E * r["area_exact"] * KZ / (flux * ETA))))
        kind = ("spot2_ip44" if big else "spot_ip44") if cls == "wet" else ("spot2" if big else "spot")
        region = r["shp"].buffer(-300, join_style=2)
        if region.is_empty or region.area < 0.05e6:
            region = r["shp"].buffer(-120, join_style=2)
        free = region.difference(blocked)
        if free.is_empty or free.area < 0.05e6:
            free = region
        tables = [g for f, g in T.furniture_shapes(P, ("table",)) if _room_of(P, f, g) is r]
        if tables:                                   # the pendant lights the table: no spots crowding it
            free2 = free.difference(unary_union([g.centroid.buffer(450) for g in tables]))
            if not free2.is_empty and free2.area > 0.05e6:
                free = free2
        pts = _grid(free, n)
        for p in pts:
            out.append(dict(kind=kind, x=p[0], y=p[1], group=r["name"], proposed=True))
        extra = []
        for g in tables:
            c = g.centroid
            out.append(dict(kind="pendant", x=T.snap(c.x), y=T.snap(c.y), group=r["name"], proposed=True))
        if tables:
            extra.append("подвес над столом" if len(tables) == 1 else "подвесы над столами ×%d" % len(tables))
        for f, g in T.furniture_shapes(P, ("kitchen_upper",)):
            if _room_of(P, f, g) is not r:
                continue
            back = T.back_side(P, g, r)
            if back is None:
                continue
            seg, nn, q = back
            x0, y0, x1, y1 = g.bounds
            if abs(nn[0]) > 0.5:
                xf = (x1 if nn[0] > 0 else x0) - nn[0] * 40
                a, b = (xf, y0 + 50), (xf, y1 - 50)
            else:
                yf = (y1 if nn[1] > 0 else y0) - nn[1] * 40
                a, b = (x0 + 50, yf), (x1 - 50, yf)
            out.append(dict(kind="led", x=T.snap(a[0]), y=T.snap(a[1]), x2=T.snap(b[0]), y2=T.snap(b[1]), group=r["name"],
                            proposed=True))
            extra.append("LED рабочей зоны")
        summary.append("%s %d шт.%s (%d лк)%s" % (r["name"], len(pts), " двойных" if big else "", E,
                                                   (" + " + ", ".join(extra)) if extra else ""))
    d["lighting"] = out
    spec = d.setdefault("lighting_spec", {})
    for o in out:
        if o["kind"] in LIGHT_SPEC:
            spec.setdefault(o["kind"], LIGHT_SPEC[o["kind"]])
    _note(d, "lighting", "Количество светильников - по методу коэффициента использования (освещённость по СП 52.13330: жилые "
                         "комнаты и кухни 150 лк, коридоры и санузлы 50 лк). Проектное предложение - согласовать.")
    L(log, "освещение", "светильники: " + "; ".join(summary), len(out))


def _grid(region, n):
    x0, y0, x1, y1 = region.bounds
    W, H = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    best = []
    for m in range(n, 3 * n + 1):
        cols = max(1, int(round(math.sqrt(m * W / H))))
        rows = max(1, int(math.ceil(m / float(cols))))
        if rows * cols < m:
            continue
        pts = []
        for j in range(rows):
            for i in range(cols):
                p = (x0 + (i + 0.5) * W / cols, y0 + (j + 0.5) * H / rows)
                if region.contains(Point(p)):
                    pts.append((T.snap(p[0]), T.snap(p[1])))
        if len(pts) >= n:
            return pts
        if len(pts) > len(best):
            best = pts
    if not best:
        c = region.representative_point()
        best = [(T.snap(c.x), T.snap(c.y))]
    return best


# ------------------------------------------------------------------ switches
def _snapq(q, n):
    return (_r(q[0]), T.snap(q[1])) if abs(n[0]) > 0.5 else (T.snap(q[0]), _r(q[1]))


def _entrance_switch(P, room, ent, approach=None):
    """Switch point next to an entrance: latch side of a door first (never behind the leaf opened into the room),
    on the face that continues the door wall first, then the return wall at the jamb. -> (point, normal) or None."""
    o = ent["opening"]
    ends = list(ent["ends"])
    order = [0, 1]
    allow = [True, True]
    if o is not None and o["kind"] in ("door", "balcony"):
        latch = 1 if o.get("hinge", "min") == "min" else 0
        order = [latch, 1 - latch]
        n = ent["n"]
        opens_here = bool(o.get("swing")) and abs(o["swing"][0] - n[0]) < 0.5 and abs(o["swing"][1] - n[1]) < 0.5
        allow[1 - latch] = not opens_here
    elif approach is not None:
        order.sort(key=lambda i: math.hypot(ends[i][0] - approach[0], ends[i][1] - approach[1]))
    for i in order:
        if not allow[i]:
            continue
        cands = T.beside_points(P, room, ends[i])
        if not cands:
            continue
        # face continuing the door wall first (collinear: same normal as the opening face)
        def pref(c):
            q, nn, dist = c
            same = ent["n"] is not None and abs(nn[0] - ent["n"][0]) < 0.5 and abs(nn[1] - ent["n"][1]) < 0.5
            return (0 if same and dist < 60 else 1, dist)
        q, nn, _ = sorted(cands, key=pref)[0]
        return _snapq(q, nn), nn
    return None


def _approach(P, room, ent):
    """Where people come from into the room through an open edge: the nearest door of the neighbouring room."""
    other = ent.get("other")
    if other is None:
        return None
    best = None
    for e2 in T.room_entrances(P, other):
        if e2["opening"] is None:
            continue
        c = P.open_shape[e2["opening"]["id"]].centroid
        dist = min(math.hypot(c.x - x, c.y - y) for x, y in ent["ends"])
        if best is None or dist < best[0]:
            best = (dist, (c.x, c.y))
    return best[1] if best else None


def _switches(d, P, log):
    lights = d.get("lighting", [])
    groups = {}
    for f in lights:
        groups.setdefault(f["group"], set()).add(f["kind"])
    entr = [o["id"] for o in P.openings if T.is_entrance(P, o)]
    sw = []
    missing = []
    for r in P.rooms:
        if r["name"] not in groups:
            continue
        kinds = groups[r["name"]]
        ctl = []
        main = sorted(k for k in kinds if k not in ("pendant", "led"))
        letters = iter("абвгд")
        if main:
            ctl.append(dict(key=next(letters), group=r["name"], kinds=main, desc="свет: %s" % r["name"].lower()))
        if "pendant" in kinds:
            ctl.append(dict(key=next(letters), group=r["name"], kinds=["pendant"], desc="подвес над столом"))
        if "led" in kinds:
            ctl.append(dict(key=next(letters), group=r["name"], kinds=["led"], desc="LED рабочей зоны"))
        ents = [e for e in T.room_entrances(P, r) if e["kind"] != "balcony"]
        if not ents:
            missing.append(r["name"])
            continue

        def rank(e):
            o = e["opening"]
            oc = e["other"].get("cls") if e["other"] else None
            return (0 if o is not None and o["id"] in entr else 1 if oc == "circulation" else 2,
                    0 if o is not None else 1, -(o["w"] if o else 0))
        ents.sort(key=rank)
        res, host = None, r
        for e in ents:
            if r.get("cls") == "wet" and e["opening"] is not None and e["other"] is not None:
                o = e["opening"]                          # switch outside the wet room, next to its door
                x = e["other"]
                e2 = [q for q in T.room_entrances(P, x) if q["opening"] is not None and q["opening"]["id"] == o["id"]]
                if e2:
                    res = _entrance_switch(P, x, e2[0])
                    host = x
            else:
                res = _entrance_switch(P, r, e, _approach(P, r, e))
                host = r
            if res is not None:
                break
        if res is None:
            missing.append(r["name"])
            continue
        q, nn = res
        sw.append(dict(x=q[0], y=q[1], h=900, wall=T.normal_code(nn), room=host["name"], controls=ctl))
        # bedroom: second (pass-through) switch at the bed for the main light, h 700
        beds = [(f, g) for f, g in T.furniture_shapes(P, ("bed",)) if _room_of(P, f, g) is r]
        if beds and main:
            f, g = beds[0]
            back = _fixture_back(P, f, g, r)
            if back is not None:
                _, nb, qb = back
                x0, y0, x1, y1 = g.bounds
                half = ((y1 - y0) if abs(nb[0]) > 0.5 else (x1 - x0)) / 2.0
                for side in (1, -1):
                    pb = _on_face_point(P, r, qb, nb, side * (half + 250), clear=50)
                    if pb is not None:
                        sw[-1]["controls"][0]["mode"] = "pass"
                        sw.append(dict(x=pb[0], y=pb[1], h=700, wall=T.normal_code(nb), room=r["name"],
                                       controls=[dict(ctl[0], mode="pass")]))
                        break
    sw = _merge_switches(sw)
    used = [int(s["id"][1:]) for s in d.get("switches", []) if s.get("id", "")[1:].isdigit()]
    k = max(used) if used else 0
    for s in sw:
        k += 1
        s["id"] = "В%d" % k
        s["keys"] = len(s["controls"])
        s["proposed"] = True
    d["switches"] = d.get("switches", []) + sw
    _note(d, "lighting", "Выключатели - у входа со стороны ручки двери, h 900; для санузлов - снаружи. Проектное предложение.")
    L(log, "выключатели", "выключатели: %d шт. у входов со стороны ручки%s%s" % (
        len(sw), ", проходные у кровати" if any(s["h"] == 700 for s in sw) else "",
        "; не размещены (нет входа): " + ", ".join(missing) if missing else ""), len(sw))


def _merge_switches(sw):
    out = []
    for s in sw:
        for t in out:
            if t["wall"] == s["wall"] and t["h"] == s["h"] and math.hypot(t["x"] - s["x"], t["y"] - s["y"]) < 200 \
                    and len(t["controls"]) + len(s["controls"]) <= 3:
                letters = "абвгд"
                for c in s["controls"]:
                    t["controls"].append(dict(c, key=letters[len(t["controls"])]))
                break
        else:
            out.append(s)
    return out


# ------------------------------------------------------------------ sockets
def _sockets(d, P, log):
    out = []
    notes = []
    furn = T.furniture_shapes(P)
    for r in P.rooms:
        cls = r.get("cls", "living")
        mine = [(f, g) for f, g in furn if _room_of(P, f, g) is r]
        start = len(out)
        if cls == "living":
            _bed_sockets(P, r, mine, out)
            _tv_sockets(P, r, mine, out)
            _ac_outlet(P, r, out, mine)
            need = int(math.ceil(r["perimeter"] / 4.0 - 1e-9))
        elif cls == "kitchen":
            _kitchen_sockets(P, r, mine, out)
            _tv_sockets(P, r, mine, out)
            need = 4
        elif cls == "wet":
            _wet_sockets(P, r, mine, out)
            need = 0
        elif cls == "circulation":
            need = max(1, int(math.ceil(r["area_exact"] / 10.0 - 1e-9)))
        else:
            need = 0
        have = sum(1 for s in out[start:] if s["kind"] in ("Р", "Р2", "РВ") and s.get("count", True))
        if need > have:
            _fill(P, r, mine, out, need - have, kind="РВ" if cls == "wet" else "Р2", h=300)
        notes.append("%s: %d" % (r["name"], len(out) - start))
    for s in out:
        s.pop("count", None)
    d["sockets"] = out
    _note(d, "sockets", "Количество розеток - не менее норм СП 256.1325800 (жилая комната - 1 на каждые 4 м периметра, кухня - "
                        "не менее 4, коридор - 1 на 10 м²). Проектное предложение - уточнить по расстановке техники.")
    L(log, "розетки", "розетки и выводы: " + "; ".join(notes), len(out))


def _add(out, P, r, q, n, along, kind, h, note=None, count=True, clear=40):
    p = _on_face_point(P, r, q, n, along, clear)
    if p is None:
        return False
    for s in out:
        if s["x"] == p[0] and s["y"] == p[1] and s["h"] == h:
            return False
    o = _pt(kind, p, h, n)
    if note:
        o["note"] = note
    if not count:
        o["count"] = False
    out.append(o)
    return True


def _bed_sockets(P, r, mine, out):
    beds = [(f, g) for f, g in mine if f.get("kind") == "bed"]
    stands = [(f, g) for f, g in mine if f.get("kind") == "nightstand"]
    for f, g in beds:
        back = _fixture_back(P, f, g, r)
        if back is None:
            continue
        _, n, q = back
        x0, y0, x1, y1 = g.bounds
        half = ((y1 - y0) if abs(n[0]) > 0.5 else (x1 - x0)) / 2.0
        near = [sg for sf, sg in stands if sg.distance(g) < 250]
        if near:
            for sg in near:
                c = sg.centroid
                along = (c.y - q[1]) if abs(n[0]) > 0.5 else (c.x - q[0])
                t = (-n[1], n[0])
                along = along * (t[1] if abs(n[0]) > 0.5 else t[0])
                _add(out, P, r, q, n, along, "Р2", 600, "у кровати")
        else:
            for side in (1, -1):
                _add(out, P, r, q, n, side * (half + 200), "Р2", 600, "у кровати")


def _tv_sockets(P, r, mine, out):
    tvs = [(f, g) for f, g in mine if f.get("kind") == "tv"]
    stands = [(f, g) for f, g in mine if f.get("kind") == "tv_stand"]
    items = [(g, 1100, "за ТВ") for f, g in tvs] or [(g, 700, "ТВ") for f, g in stands]
    for g, h, note in items[:1]:
        back = T.back_side(P, g, r)
        if back is None:
            continue
        _, n, q = back
        _add(out, P, r, q, n, -150, "Р2", h, note)
        _add(out, P, r, q, n, 0, "ТВ", h, count=False)
        _add(out, P, r, q, n, 150, "LAN", h, count=False)
    if tvs and stands:
        g = stands[0][1]
        back = T.back_side(P, g, r)
        if back is not None:
            _, n, q = back
            _add(out, P, r, q, n, -350, "Р2", 300, "ТВ-тумба")


def _ac_outlet(P, r, out, mine=()):
    if r["area_exact"] < 8.0:
        return
    # never above the head of a bed (cold air on the sleeper)
    heads = []
    for f, g in mine:
        if f.get("kind") == "bed":
            back = _fixture_back(P, f, g, r)
            if back is not None:
                heads.append((back[1], g.buffer(700)))
    wins = T.room_openings(P, r, kinds=("window", "balcony"))
    if not wins:
        return
    o, nw, fpw = max(wins, key=lambda q: q[0]["w"])
    h = min(2600, P.ceiling - 150)
    # perpendicular faces near the window wall: 300 from the corner, short freon route to the facade
    best = None
    for seg, n in T.wall_faces(P, r, 100):
        if abs(n[0] * nw[0] + n[1] * nw[1]) > 0.5:
            continue
        a, b = seg.coords[0], seg.coords[-1]
        for e in (a, b):
            dist_win = abs((e[0] - fpw[0]) * nw[0] + (e[1] - fpw[1]) * nw[1])
            if dist_win > 150:
                continue
            other = b if e == a else a
            L_ = math.hypot(other[0] - e[0], other[1] - e[1])
            if L_ < 700:
                continue
            u = ((other[0] - e[0]) / L_, (other[1] - e[1]) / L_)
            p = (e[0] + u[0] * 300, e[1] + u[1] * 300)
            if any(abs(hn[0] - n[0]) < 0.5 and abs(hn[1] - n[1]) < 0.5 and hz.contains(Point(p)) for hn, hz in heads):
                continue
            if best is None or L_ > best[0]:
                best = (L_, p, n)
    if best is None:
        return
    _, p, n = best
    q = _validate_face(P, r, p, n, 50)
    if q is not None:
        out.append(_pt("КОНД", q, h, n, note="кондиционер", count=False))


def _kitchen_sockets(P, r, mine, out):
    kb = [(f, g) for f, g in mine if f.get("kind") == "kitchen_base"]
    sinks = [g.centroid for f, g in mine if f.get("kind") == "sink"]
    hobs = [g.centroid for f, g in mine if f.get("kind") == "hob"]
    for f, g in kb:
        back = T.back_side(P, g, r)
        if back is None:
            continue
        seg, n, q = back
        x0, y0, x1, y1 = g.bounds
        vert = abs(n[0]) > 0.5
        lo, hi = (y0, y1) if vert else (x0, x1)
        base = q[1] if vert else q[0]
        t = (-n[1], n[0])
        sgn = t[1] if vert else t[0]
        avoid = [((c.y if vert else c.x), 300) for c in sinks] + [((c.y if vert else c.x), 350) for c in hobs]
        cands = []
        s = lo + 150
        while s <= hi - 150:
            if all(abs(s - c) >= rr for c, rr in avoid):
                cands.append(s)
            s += 50
        picks = []
        if cands:
            picks.append(cands[0])
            far = max(cands, key=lambda v: abs(v - cands[0]))
            if abs(far - cands[0]) >= 600:
                picks.append(far)
        for s in picks:
            _add(out, P, r, q, n, (s - base) * sgn, "Р2", 1100, "над столешницей")
        for c in hobs:
            if g.buffer(50).contains(c):
                along = ((c.y if vert else c.x) - base) * sgn
                _add(out, P, r, q, n, along, "Р32", 300, "варочная панель 32А", count=False)
                _add(out, P, r, q, n, along, "Р", 2150, "вытяжка", count=False)
        for c in sinks:
            if g.buffer(50).contains(c):
                along = ((c.y if vert else c.x) - base + 350) * sgn
                _add(out, P, r, q, n, along, "Р", 300, "ПММ / измельчитель")
    for f, g in mine:
        if f.get("kind") != "fridge":
            continue
        back = T.back_side(P, g, r)
        if back is not None:
            _add(out, P, r, back[2], back[1], 0, "Р", 300, "холодильник")


def _wet_sockets(P, r, mine, out):
    wet_zone = unary_union([g.buffer(600) for f, g in mine if f.get("kind") in ("shower", "bath")] or [Polygon()])
    for f, g in mine:
        if f.get("kind") == "washer":
            back = T.back_side(P, g, r)
            if back is not None:
                _add(out, P, r, back[2], back[1], 0, "РВ", 1100, "стиральная машина")
    for f, g in mine:
        if f.get("kind") != "basin":
            continue
        back = T.back_side(P, g, r)
        if back is None:
            continue
        _, n, q = back
        x0, y0, x1, y1 = g.bounds
        half = ((y1 - y0) if abs(n[0]) > 0.5 else (x1 - x0)) / 2.0
        for side in (1, -1):
            p = _on_face_point(P, r, q, n, side * (half + 150), 40)
            if p is not None and not wet_zone.contains(Point(p)):
                out.append(_pt("РВ", p, 1100, n, note="IP44, фен"))
                break


def _fill(P, r, mine, out, k, kind, h):
    """Spread k more sockets evenly over the free wall (not behind furniture, not in door / window reveals)."""
    blocks = [g.buffer(120) for f, g in mine if f.get("kind") in BLOCK_WALL]
    blocked = unary_union(blocks) if blocks else None
    cands = []
    for seg, n in T.wall_faces(P, r, 200):
        if seg.length < 400:
            continue
        s = 150.0
        while s <= seg.length - 150:
            q = seg.interpolate(s)
            if blocked is None or not blocked.contains(q):
                cands.append(((q.x, q.y), n))
            s += 100.0
    if not cands:
        return
    have = [(s["x"], s["y"]) for s in out if P.room_of_point((s["x"], s["y"]), 60) is r]
    doors = [P.open_shape[o["id"]].centroid for o, _, _ in T.room_openings(P, r)]
    for _ in range(k):
        best = None
        for p, n in cands:
            if have:
                sc = min(math.hypot(p[0] - x, p[1] - y) for x, y in have)
            else:
                sc = min((math.hypot(p[0] - c.x, p[1] - c.y) for c in doors), default=0.0)
                sc = -abs(sc - 1500)                   # first one ~1.5 m from the entrance
            if best is None or sc > best[0]:
                best = (sc, p, n)
        if best is None or (have and best[0] < 600):
            break
        _, p, n = best
        q = _validate_face(P, r, p, n, 50)
        if q is None:
            cands = [c for c in cands if c[0] != p]
            continue
        out.append(_pt(kind, q, h, n))
        have.append(q)


# ------------------------------------------------------------------ panel and circuits
def _panel(d, P, log):
    entr = [o for o in P.openings if T.is_entrance(P, o)]
    pts = [(s["x"], s["y"]) for s in d.get("switches", [])] + [(s["x"], s["y"]) for s in d.get("sockets", [])]
    best = None
    for o in entr:
        for r, n, fp in T.opening_sides(P, o):
            if r is None:
                continue
            for seg, nn in T.wall_faces(P, r, 150):
                if seg.length < 500:
                    continue
                s = 250.0
                while s <= seg.length - 250:
                    q = seg.interpolate(s)
                    if pts and min(math.hypot(q.x - x, q.y - y) for x, y in pts) < 450:
                        s += 50
                        continue
                    dist = q.distance(Point(fp))
                    if best is None or dist < best[0]:
                        best = (dist, (q.x, q.y), nn)
                    s += 50
    if best is None:
        return
    _, q, nn = best
    q = (_r(q[0]), T.snap(q[1])) if abs(nn[0]) > 0.5 else (T.snap(q[0]), _r(q[1]))
    flat = bool(re.search(r"квартир|дом", d.get("meta", {}).get("object", "квартиры"), re.I))
    name = "ЩК" if flat else "ЩР"
    d["panel"] = dict(name=name, x=q[0], y=q[1], w=300 if flat else 500, wall=T.normal_code(nn), bottom=1500, proposed=True)
    L(log, "щит", "%s у входа, низ +1,500" % ("щит квартирный ЩК" if flat else "щит распределительный ЩР"), 1)


def _circuits(d, P, log):
    rows = [["Ввод", "ВА 2P C40 + реле напряжения 63 А + УЗИП", "ВВГнг(А)-LS 3×10", "Вводной кабель - по ТУ"],
            ["1", "АВ 1P C10", "ВВГнг(А)-LS 3×1,5", "Освещение"]]
    g = 1
    assign = {}

    def new(app, cab, txt):
        nonlocal g
        g += 1
        rows.append([str(g), app, cab, txt])
        return str(g)
    socks = d.get("sockets", [])
    room_of = {id(s): (P.room_of_point((s["x"], s["y"]), 80) or {}) for s in socks}
    living = [r for r in P.rooms if r.get("cls") in ("living", "circulation", "storage")]
    living_groups = {}
    for i in range(0, len(living), 2):
        names = [r["name"] for r in living[i:i + 2]]
        if any(room_of[id(s)].get("name") in names and s["kind"] in ("Р", "Р2") for s in socks):
            gid = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Розетки: " + ", ".join(n.lower() for n in names))
            for n in names:
                living_groups[n] = gid
    kit = [s for s in socks if room_of[id(s)].get("cls") == "kitchen" and s["kind"] in ("Р", "Р2")]
    gk = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Розетки кухни, холодильник, вытяжка") if kit else None
    hob = [s for s in socks if s["kind"] == "Р32"]
    gh = new("АВДТ C32 30 мА", "ВВГнг(А)-LS 3×6", "Варочная панель") if hob else None
    wash = [s for s in socks if "стирал" in s.get("note", "")]
    gw = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Стиральная машина") if wash else None
    wet = [s for s in socks if s["kind"] == "РВ" and s not in wash]
    gwet = new("АВДТ C16 10 мА", "ВВГнг(А)-LS 3×2,5", "Санузлы: розетки IP44") if wet else None
    ac = [s for s in socks if s["kind"] == "КОНД"]
    gac = new("АВ 1P C16", "ВВГнг(А)-LS 3×2,5", "Кондиционеры") if ac else None
    for s in socks:
        if s.get("group"):
            continue
        rn = room_of[id(s)].get("name")
        if s["kind"] in ("ТВ", "LAN"):
            s["group"] = "сл."
        elif s["kind"] == "Р32":
            s["group"] = gh
        elif s in wash:
            s["group"] = gw
        elif s["kind"] == "РВ":
            s["group"] = gwet
        elif s["kind"] == "КОНД":
            s["group"] = gac
        elif room_of[id(s)].get("cls") == "kitchen":
            s["group"] = gk
        else:
            s["group"] = living_groups.get(rn) or (living_groups and list(living_groups.values())[0]) or gk or "2"
    if any(s["kind"] in ("ТВ", "LAN") for s in socks):
        rows.append(["сл.", "-", "UTP cat.6, RG-6", "TV / LAN от слаботочного щитка"])
    d["circuits"] = rows
    L(log, "группы щита", "групповые линии: %d (УЗО 30 мА на розетки, 10 мА - санузлы)" % (len(rows) - 1), len(rows))


def print_log(log):
    print("Проектное предложение по нормам: %d раздел(ов)" % len(log))
    for e in log:
        print("  * [%s] %s" % (e["section"], e["msg"]))
