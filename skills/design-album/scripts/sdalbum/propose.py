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

SECTIONS = ("floors", "ceilings", "finishes", "plumbing", "lighting", "switches", "sockets", "panel", "circuits", "elevations")
LUX = {"living": 150, "kitchen": 150, "wet": 50, "circulation": 50, "storage": 75, "public": 200, "bar": 200}
FLUX, ETA, KZ = 500.0, 0.45, 1.25
MIN_SPOTS = {"living": 4, "kitchen": 4, "wet": 2, "circulation": 2, "storage": 1, "public": 6, "bar": 3}
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
    P = M.Project(d, base_dir)
    if "elevations" in want and not d.get("elevations"):
        _elevations(d, P, log)
    if log:                                  # a statement in the general notes, not a question to the client
        txt = "По нормам как проектное предложение выполнены (отмечены на листах): %s." % (
            ", ".join(sorted(set(e["section"] for e in log))))
        cur = d.get("notes", {}).get("general")         # the statement of an earlier run is replaced, not repeated
        if isinstance(cur, dict):
            cur["add"] = [x for x in cur.get("add", []) if not x.startswith("По нормам как проектное предложение выполнены")]
        _note(d, "general", txt)
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


def _on_face_point(P, room, q, n, along, clear=40, below=None):
    """Point on the face at q moved `along` (mm) along the wall; None if it leaves a free face of the room."""
    t = (-n[1], n[0])
    p = (q[0] + t[0] * along, q[1] + t[1] * along)
    return _validate_face(P, room, p, n, clear, below)


def _validate_face(P, room, p, n, clear=40, below=None):
    best = None
    for seg, nn in T.wall_faces(P, room, clear, below=below):
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
def _public(d):
    return d.get("meta", {}).get("building") == "public"


def _floors(d, P, log):
    if _public(d):
        return _floors_public(d, P, log)
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


def _floors_public(d, P, log):
    """Public interior: porcelain stoneware everywhere (wear, cleaning), anti-slip where water is (bar, WC)."""
    spec = [("public", "Керамогранит 600×1200 матовый, R10 (зал)", [600, 1200],
             "Керамогранит 10 мм; плиточный клей; стяжка"),
            ("bar", "Керамогранит 600×600 противоскользящий R11 (бар)", [600, 600],
             "Керамогранит 10 мм; плиточный клей; обмазочная гидроизоляция; стяжка"),
            ("storage", "Керамогранит 600×600 R10 (служебные)", [600, 600], "Керамогранит 10 мм; плиточный клей; стяжка"),
            ("wet", "Керамогранит 600×600 R10 (санузлы)", [600, 600],
             "Керамогранит 10 мм; плиточный клей; обмазочная гидроизоляция с заведением на стены 200 мм; стяжка")]
    cls_of = {r["name"]: r.get("cls", "living") for r in P.rooms}
    out = []
    used = set()
    for key, mat, tile, layers in spec:
        rooms = [n for n, c in cls_of.items() if (c == key) or (key == "storage" and c in ("storage", "circulation", "kitchen", "living"))]
        rooms = [n for n in rooms if n not in used]
        if not rooms:
            continue
        used.update(rooms)
        out.append(dict(id="П%d" % (len(out) + 1), material=mat, pattern="tile", tile=tile, rooms=rooms, layers=layers,
                        reserve=0.1, proposed=True))
    d["floors"] = out
    _note(d, "floors", "Покрытия - проектное предложение для общественного интерьера: износостойкий керамогранит, "
                       "противоскользящий в мокрых зонах. Раскладку и цвет согласовать с заказчиком.")
    L(log, "полы", "полы: " + "; ".join("%s - %s" % (f["id"], f["material"]) for f in out), len(out))


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
    if _public(d):
        types[0]["desc"] = "Окраска износостойкой моющейся краской (класс 1-2 по мокрому истиранию), цвет по дизайну"
    segs = []
    for f, g in T.furniture_shapes(P, ("kitchen_base", "sink", "basin")):
        room = _room_of(P, f, g)
        if room is None or (f.get("kind") != "kitchen_base" and room.get("cls") == "wet"):
            continue
        if f.get("kind") in ("sink", "basin"):
            g = g.buffer(150, join_style=2)          # the apron goes 150 beyond the sink on each side
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
        types.append(dict(id="О3", desc="Фартук: керамическая плитка / стеновая панель, h 550-650 над столешницей / мойкой",
                          rgb=[200, 160, 110], proposed=True))
    d["finishes"] = dict(types=types, by_class=by_class, segments=segs)
    L(log, "отделка", "отделка стен: О1 окраска%s%s" % (", О2 плитка в санузлах" if by_class else "", ", О3 фартук кухни" if segs else ""),
      len(types))


# ------------------------------------------------------------------ plumbing
def _plumbing(d, P, log):
    out, skipped = [], []
    for f, g in T.furniture_shapes(P, ("basin", "sink", "wc", "shower", "bath", "washer", "coffee", "heater", "dishwasher")):
        room = _room_of(P, f, g)
        if room is None:
            continue
        kind = f["kind"]
        name = {"basin": "Раковина", "sink": "Мойка", "wc": "Унитаз", "shower": "Смеситель душа", "bath": "Ванна",
                "washer": "Стиральная машина", "coffee": "Кофемашина", "heater": "Водонагреватель",
                "dishwasher": "Посудомоечная машина"}[kind]
        if kind == "wc" and f.get("hung"):
            name = "Унитаз подвесной (инсталляция)"
        if kind == "coffee" and f.get("on_counter"):     # on a free-standing counter: water and drain from the floor
            c = g.centroid
            out.append(dict(kind="ХВС", x=T.snap(c.x - 75), y=T.snap(c.y), h=0, fixture="Кофемашина (вода через фильтр, дренаж)",
                            proposed=True, floor=True))
            out.append(dict(kind="К50", x=T.snap(c.x + 75), y=T.snap(c.y), h=0, fixture="Кофемашина (вода через фильтр, дренаж)",
                            proposed=True, floor=True))
            continue
        if kind == "shower":
            c = g.centroid
            out.append(dict(kind="К50", x=T.snap(c.x), y=T.snap(c.y), h=0, fixture="Трап душевой", proposed=True))
        hung = "подвес" in f.get("name", "").lower() or f.get("hung")
        back = T.back_side(P, g, room, max_d=450 if (kind == "wc" and hung) else 150)
        if back is None:
            skipped.append(f["name"])
            continue
        seg, n, q = back
        lf = _left(n)

        def at(along, kd, h, fx=name):
            p = _on_face_point(P, room, q, n, -along, clear=10, below=h)   # +along = to the viewer's left
            if p is None:
                return False
            out.append(dict(kind=kd, x=p[0], y=p[1], h=h, fixture=fx, proposed=True))
            return True
        # along > 0 means to the viewer's left: _on_face_point moves along t = (-n1, n0) = -left
        if kind in ("basin", "sink"):
            hh = 550
            ok = at(50, "ГВС", hh) and at(-50, "ХВС", hh) and at(0, "К50", 450 if kind == "basin" else 500)
        elif kind == "wc":
            hc = 1000 if hung else 200
            if hung:                               # a window over the WC: low installation frame under the sill
                face = seg.buffer(40)
                sills = [o.get("sill", 0) for o in P.openings if o["kind"] == "window"
                         and P.open_shape[o["id"]].intersects(face) and 600 < o.get("sill", 0) < 1300]
                if sills:
                    hc = T.snap(min(sills) - 200, 50)
                    name = "Унитаз подвесной (инсталляция под окном, низкая рама)"
            ok = at(150, "ХВС", hc, name) and at(0, "К110", 230 if hung else 180, name)
        elif kind == "shower":
            ok = at(75, "ГВС", 1100) and at(-75, "ХВС", 1100)
        elif kind == "bath":
            ok = at(75, "ГВС", 800) and at(-75, "ХВС", 800) and at(0, "К50", 100, "Ванна (слив)")
        elif kind == "heater":
            ok = at(-100, "ХВС", 1200, "Водонагреватель 80 л") and at(100, "ГВС", 1200, "Водонагреватель 80 л")
        elif kind == "coffee":
            ok = at(-75, "ХВС", 500, "Кофемашина (вода через фильтр, дренаж)") and at(75, "К50", 400, "Кофемашина (вода через фильтр, дренаж)")
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


STAFF_KEYS = (("surface", "spot", "spot2", "spot_ip44", "spot2_ip44", "chandelier", "linear"), ("track", "track_spot", "track_rect"),
              ("pendant",), ("led",))
STAFF_DESC = ("общий свет", "шинопроводы, споты", "подвесы", "подсветка")


def _staff_switches(d, P, groups, log):
    """Public interior: the hall and the bar are switched by the staff, from the bar (a block of keys by kind of
    light: general / tracks / pendants), not at the guests' entrance. -> [switch] or [] when there is no bar."""
    bar = next((r for r in P.rooms if r.get("cls") == "bar"), None)
    if bar is None:
        return [], set()
    halls = [r for r in P.rooms if r.get("cls") == "public" and r["name"] in groups]
    ents = [e for e in T.room_entrances(P, bar) if e.get("other") is not None and e["other"].get("cls") == "public"]
    ents = ents or T.room_entrances(P, bar)
    if not ents:
        return [], set()
    ctl_all = []
    for r in [bar] + halls:
        if r["name"] not in groups:
            continue
        kinds = groups[r["name"]]
        for keyset, desc in zip(STAFF_KEYS, STAFF_DESC):
            ks = sorted(k for k in kinds if k in keyset)
            if ks:
                ctl_all.append(dict(group=r["name"], kinds=ks, desc="%s: %s" % (r["name"].lower(), desc)))
    if not ctl_all:
        return [], set()
    cands = []
    for e in ents:
        for i in (0, 1):
            cands += T.beside_points(P, bar, e["ends"][i], step=150.0, reach=400.0)
    cands.sort(key=lambda c: c[2])
    blocks = [ctl_all[i:i + 3] for i in range(0, len(ctl_all), 3)]
    out, used = [], []
    for blk in blocks:
        if used:                                   # the next block right beside the first one (one panel of keys)
            cands.sort(key=lambda c: math.hypot(c[0][0] - used[0][0], c[0][1] - used[0][1]))
        for q, nn, _ in cands:
            q2 = _snapq(q, nn)
            if any(math.hypot(q2[0] - u[0], q2[1] - u[1]) < 120 for u in used):
                continue
            ctl = [dict(c, key="абвгд"[i]) for i, c in enumerate(blk)]
            out.append(dict(x=q2[0], y=q2[1], h=900, wall=T.normal_code(nn), room=bar["name"], controls=ctl))
            used.append(q2)
            break
    done = {c["group"] for s in out for c in s["controls"]}
    if out:
        L(log, "выключатели", "свет зала и бара - блоком выключателей у входа персонала в бар (%d клав.)" % len(ctl_all), len(out))
    return out, done


def _switches(d, P, log):
    lights = d.get("lighting", [])
    groups = {}
    for f in lights:
        groups.setdefault(f["group"], set()).add(f["kind"])
    staff, done = _staff_switches(d, P, groups, log) if _public(d) else ([], set())
    entr = [o["id"] for o in P.openings if T.is_entrance(P, o)]
    sw = []
    missing = []
    for r in P.rooms:
        if r["name"] not in groups or r["name"] in done:
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
    sw = staff + _merge_switches(sw)
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
        elif cls == "public":                  # cleaning / service sockets every ~10 m of the perimeter
            need = max(2, int(math.ceil(r["perimeter"] / 10.0 - 1e-9)))
            _fill(P, r, mine, out, need, kind="Р", h=300)
            for s_ in out[start:]:
                s_.setdefault("note", "уборка / сервис")
            need = 0
        elif cls == "bar":
            _bar_sockets(P, r, mine, out)
            need = 2
        elif cls == "storage":
            _equipment_sockets(P, r, mine, out)
            need = 2 if r["area_exact"] >= 6 else 1
        else:
            need = 0
        have = sum(1 for s in out[start:] if s["kind"] in ("Р", "Р2", "РВ") and s.get("count", True))
        if need > have:
            _fill(P, r, mine, out, need - have, kind="РВ" if cls == "wet" else ("Р" if cls in ("bar", "storage") else "Р2"),
                  h=300)
        notes.append("%s: %d" % (r["name"], len(out) - start))
    for s in out:
        s.pop("count", None)
    d["sockets"] = out
    if _public(d):
        _note(d, "sockets", "Розетки зала - сервисные (уборка, оборудование) через ~10 м; оборудование бара - отдельные розетки "
                            "в корпусе стойки по паспортам; кофемашина - отдельная линия 32 А. Проектное предложение - уточнить "
                            "по выбранному оборудованию.")
    else:
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


def _staff_edges(P, r, counter):
    """Edges of a free-standing counter on the staff side (inside the room, not a wall, not the guests' front - the
    separation line). -> [(segment, outward axis normal)]"""
    out = []
    cs = list(counter.exterior.coords)
    for a, b in zip(cs[:-1], cs[1:]):
        seg = LineString([a, b])
        if seg.length < 200:
            continue
        mid = seg.interpolate(0.5, normalized=True)
        n = ((b[1] - a[1]) / seg.length, -(b[0] - a[0]) / seg.length)
        if counter.contains(Point(mid.x + n[0] * 30, mid.y + n[1] * 30)):
            n = (-n[0], -n[1])
        out_pt = Point(mid.x + n[0] * 120, mid.y + n[1] * 120)
        if not r["shp"].contains(out_pt) or P.mass.contains(out_pt):
            continue
        if any(LineString(s_).buffer(5).contains(seg) for s_ in P.separations):
            continue                                       # the guests' side
        out.append((seg, (int(round(n[0])), int(round(n[1])))))
    return out


def _in_counter(P, r, counter, near):
    """A point on the staff side of a free-standing counter, opposite `near` (equipment under / on it) - sockets of
    the bar equipment are built into the counter (mount 'furniture'). -> (point, outward normal) or None"""
    best = None
    for seg, n in _staff_edges(P, r, counter):
        L_ = seg.length
        q = seg.interpolate(min(max(seg.project(near), 100.0), L_ - 100.0))
        dd = q.distance(near)
        if best is None or dd < best[0]:
            best = (dd, (q.x, q.y), n)
    if best is None:
        return None
    return (T.snap(best[1][0]), T.snap(best[1][1])), best[2]


def _bar_sockets(P, r, mine, out):
    counters = [(f, g) for f, g in mine if f.get("kind") == "counter"]
    for f, g in mine:
        k = f.get("kind")
        if k not in ("coffee", "grinder", "pos", "fridge", "dishwasher", "ice"):
            continue
        host = next((cg for cf, cg in counters if cg.buffer(20).contains(g.centroid)), None)
        spec = {"coffee": ("Р32", 300, "кофемашина, отдельная линия"), "grinder": ("Р", 1100, "кофемолка"),
                "pos": ("Р", 300, "касса POS"), "fridge": ("Р", 300, "холодильник"), "dishwasher": ("Р", 300, "ПММ"),
                "ice": ("Р", 300, "льдогенератор")}[k]
        if host is not None:
            res = _in_counter(P, r, host, g.centroid)
            if res is not None:
                p, n = res
                out.append(_pt(spec[0], p, spec[1], n, note=spec[2] + " (в корпусе стойки)", mount="furniture"))
                if k == "pos":
                    t = (-n[1], n[0])
                    for sg in (1, -1):              # beside the socket, on the same face of the counter
                        q = (T.snap(p[0] + sg * t[0] * 150), T.snap(p[1] + sg * t[1] * 150))
                        if host.exterior.distance(Point(q)) <= 5 and host.buffer(-5).distance(Point(q)) > 0:
                            out.append(_pt("LAN", q, spec[1], n, mount="furniture", note="касса POS (LAN)"))
                            break
                continue
        back = T.back_side(P, g, r)
        if back is not None:
            _add(out, P, r, back[2], back[1], 0, spec[0], spec[1], spec[2])
    taken = [(s_["x"], s_["y"]) for s_ in out]
    for f, g in counters:                      # refrigerated tables under the counter top: one socket each
        m = re.search(r"×(\d+)", f.get("name", ""))
        n_fr = int(m.group(1)) if m else 0
        edges = _staff_edges(P, r, g)
        total = sum(e.length for e, _ in edges)
        if not n_fr or not total:
            continue
        for i in range(n_fr):
            t = (i + 0.5) / n_fr * total
            acc = 0.0
            for e, n in edges:
                if acc + e.length >= t:
                    for shift in (0, 300, -300, 600, -600):    # clear of the coffee machine / POS sockets
                        q = e.interpolate(min(max(t - acc + shift, 100.0), e.length - 100.0))
                        p = (T.snap(q.x), T.snap(q.y))
                        if all(math.hypot(p[0] - u[0], p[1] - u[1]) > 250 for u in taken):
                            out.append(_pt("Р", p, 300, n, note="холодильный стол (в корпусе стойки)", mount="furniture"))
                            taken.append(p)
                            break
                    break
                acc += e.length


def _equipment_sockets(P, r, mine, out):
    for f, g in mine:
        if f.get("kind") != "heater":
            continue
        back = T.back_side(P, g, r)
        if back is None:
            continue
        _, n, q = back
        x0, y0, x1, y1 = g.bounds
        half = ((y1 - y0) if abs(n[0]) > 0.5 else (x1 - x0)) / 2.0
        for side in (1, -1):
            if _add(out, P, r, q, n, side * (half + 150), "Р", 1800, "водонагреватель, отдельная линия", count=False):
                break


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
                public = getattr(P, "d", {}).get("meta", {}).get("building") == "public"
                out.append(_pt("РВ", p, 1100, n, note="IP44, сушилка для рук" if public else "IP44, фен"))
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
    if _public(d):
        staff = [r for r in P.rooms if r.get("cls") in ("storage",)] or [r for r in P.rooms if r.get("cls") == "bar"]
        if staff:
            return _panel_in(d, P, log, staff[0])
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


def _panel_in(d, P, log, room):
    """Public building: ЩР in a staff room next to its door (not in the guests' hall), bottom +1,500, clear of
    furniture and other points."""
    pts = [(s["x"], s["y"]) for s in d.get("switches", [])] + [(s["x"], s["y"]) for s in d.get("sockets", [])]
    furn = unary_union([g.buffer(50) for f, g in T.furniture_shapes(P) if f.get("kind") not in ("rug",)] or [Polygon()])
    doors = [P.open_shape[o["id"]].centroid for o, n, fp in T.room_openings(P, room)]
    best = None
    for seg, nn in T.wall_faces(P, room, 150):
        if seg.length < 600:
            continue
        s_ = 300.0
        while s_ <= seg.length - 300:
            q = seg.interpolate(s_)
            body = box(q.x - 260, q.y - 260, q.x + 260, q.y + 260)
            if (pts and min(math.hypot(q.x - x, q.y - y) for x, y in pts) < 450) or body.intersects(furn):
                s_ += 50
                continue
            dist = min((q.distance(c) for c in doors), default=0.0)
            if best is None or dist < best[0]:
                best = (dist, (q.x, q.y), nn)
            s_ += 50
    if best is None:
        return
    _, q, nn = best
    q = (_r(q[0]), T.snap(q[1])) if abs(nn[0]) > 0.5 else (T.snap(q[0]), _r(q[1]))
    d["panel"] = dict(name="ЩР", x=q[0], y=q[1], w=500, wall=T.normal_code(nn), bottom=1500, proposed=True)
    L(log, "щит", "щит распределительный ЩР в «%s» у входа (служебная зона, не в зале), низ +1,500" % room["name"], 1)


def _circuits_public(d, P, log):
    rows = [["Ввод", "ВА 3P C50 + реле контроля напряжения + УЗИП", "ВВГнг(А)-LS 5×16",
             "Ввод - по ТУ сетевой организации; мощность уточняется расчётом нагрузок"]]
    g = 0
    socks = d.get("sockets", [])
    room_of = {id(s): (P.room_of_point((s["x"], s["y"]), 80) or {}) for s in socks}

    def new(app, cab, txt):
        nonlocal g
        g += 1
        rows.append([str(g), app, cab, txt])
        return str(g)
    light_rooms = {}
    for f in d.get("lighting", []):
        r = P.room_by_name.get(f.get("group"))
        light_rooms.setdefault(r.get("cls") if r else "?", set()).add(f.get("group"))
    if light_rooms.get("public"):
        kinds = {f["kind"] for f in d.get("lighting", []) if P.room_by_name.get(f.get("group"), {}).get("cls") == "public"}
        new("АВ 1P C10", "ВВГнг(А)-LS 3×1,5", "Освещение зала: общее")
        if kinds & {"track", "track_spot"}:
            new("АВ 1P C10", "ВВГнг(А)-LS 3×1,5", "Освещение зала: шинопроводы")
    other = sorted(set().union(*[v for k, v in light_rooms.items() if k not in ("public",)])) if light_rooms else []
    if other:
        new("АВ 1P C10", "ВВГнг(А)-LS 3×1,5", "Освещение: " + ", ".join(n.lower() for n in other))
    new("АВ 1P C6", "ВВГнг(А)-FRLS 3×1,5", "Аварийное освещение, знак «ВЫХОД» (по разделу ЭО)")
    assign = {}
    hall = [s for s in socks if room_of[id(s)].get("cls") == "public" and s["kind"] in ("Р", "Р2")]
    if hall:
        gh = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Розетки зала (уборка, сервис)")
        for s in hall:
            assign[id(s)] = gh
    cof = [s for s in socks if s["kind"] == "Р32"]
    if cof:
        gc = new("АВДТ C32 30 мА", "ВВГнг(А)-LS 3×6", "Кофемашина")
        for s in cof:
            assign[id(s)] = gc
    fr = [s for s in socks if "холодильн" in s.get("note", "")]
    for i in range(0, len(fr), 2):
        gf = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Холодильное оборудование бара (%d шт.)" % len(fr[i:i + 2]))
        for s in fr[i:i + 2]:
            assign[id(s)] = gf
    bar = [s for s in socks if room_of[id(s)].get("cls") == "bar" and id(s) not in assign and s["kind"] in ("Р", "Р2", "РВ")]
    if bar:
        gb = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Розетки бара (кофемолка, касса, мелкая техника)")
        for s in bar:
            assign[id(s)] = gb
    heat = [s for s in socks if "водонагрев" in s.get("note", "")]
    if heat:
        gw = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Водонагреватель 80 л (2 кВт)")
        for s in heat:
            assign[id(s)] = gw
    serv = [s for s in socks if room_of[id(s)].get("cls") in ("storage", "circulation") and id(s) not in assign
            and s["kind"] in ("Р", "Р2")]
    if serv:
        gs = new("АВДТ C16 30 мА", "ВВГнг(А)-LS 3×2,5", "Розетки служебных помещений")
        for s in serv:
            assign[id(s)] = gs
    wet = [s for s in socks if s["kind"] == "РВ" and id(s) not in assign]
    if wet:
        gwt = new("АВДТ C16 10 мА", "ВВГнг(А)-LS 3×2,5", "Санузлы: сушилки для рук, розетки IP44")
        for s in wet:
            assign[id(s)] = gwt
    acs = [e for e in d.get("_equipment", []) if e.get("kind") == "ac"]
    for i, e in enumerate(acs, 1):
        new("АВ 1P C16", "ВВГнг(А)-LS 3×2,5", "Кондиционер кассетный %d (по модели)" % i)
    new("АВДТ C10 30 мА", "ВВГнг(А)-LS 3×1,5", "Вывеска, подсветка витрины")
    new("АВ 1P C16", "-", "Резерв")
    new("АВ 1P C16", "-", "Резерв")
    for s in socks:
        if s.get("group"):
            continue
        if s["kind"] in ("ТВ", "LAN"):
            s["group"] = "сл."
        else:
            s["group"] = assign.get(id(s)) or (list(assign.values())[0] if assign else "1")
    if any(s["kind"] in ("ТВ", "LAN") for s in socks):
        rows.append(["сл.", "-", "UTP cat.6", "LAN (касса) - от слаботочного шкафа / роутера"])
    d["circuits"] = rows
    L(log, "группы щита", "ЩР: %d групп (освещение, аварийное, оборудование бара отдельными линиями, УЗО 30 мА, санузлы 10 мА)"
      % g, len(rows))


def _circuits(d, P, log):
    if _public(d):
        return _circuits_public(d, P, log)
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


# ------------------------------------------------------------------ elevations (wet rooms, bar, utility walls)
ELEV_LETTERS = "АБВГДЕЖИКЛМНПРСТУФШЭЮЯ"


def _faces_cw(room):
    """Wall runs of a room, clockwise seen from above, the room on the right of a->b (the elevation seen from inside,
    left to right); collinear pieces merged."""
    ring = list(room["shp"].exterior.coords)[:-1]
    if Polygon(ring).exterior.is_ccw:
        ring = ring[::-1]
    pts = []
    for i, p in enumerate(ring):                    # drop collinear vertices
        a, b = ring[i - 1], ring[(i + 1) % len(ring)]
        cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
        if abs(cross) > 1.0:
            pts.append(p)
    return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _fixture_elev(f, g, E, room, P):
    """Front view of an item standing at the wall: items (cabinets, worktop) and fixtures (sanitary ware) in s, z."""
    x0, y0, x1, y1 = g.bounds
    ss = sorted(E.s_of(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    s0, s1 = max(0.0, ss[0]), min(E.L, ss[-1])
    if s1 - s0 < 50:
        return [], [], None
    c = (s0 + s1) / 2.0
    k = f.get("kind")
    items, fx, eq = [], [], None
    nm = f.get("name", "")
    if k == "wc":
        hung = f.get("hung")
        z0 = 230 if hung else 0
        fx.append(dict(name="унитаз", poly=[[c - 120, z0], [c + 120, z0], [c + 175, 330], [c + 180, 400], [c - 180, 400],
                                           [c - 175, 330]]))
        fx.append(dict(name="сиденье", poly=[[c - 185, 400], [c + 185, 400], [c + 185, 430], [c - 185, 430]]))
        if hung:                                   # the flush plate on the front of the installation box
            fx.append(dict(name="клавиша смыва", poly=[[c - 120, 780], [c + 120, 780], [c + 120, 930], [c - 120, 930]]))
        eq = [nm, "ХВС, К110" + (", рама инсталляции" if hung else "")]
        label = None
    elif k == "basin":
        w = max(min(s1 - s0, 700), 300)
        fx.append(dict(name="раковина", poly=[[c - w / 2, 700], [c + w / 2, 700], [c + w / 2, 850], [c - w / 2, 850]]))
        fx.append(dict(name="сифон", poly=[[c - 30, 450], [c + 30, 450], [c + 30, 700], [c - 30, 700]], outline_only=True))
        fx.append(dict(name="смеситель", poly=[[c - 25, 850], [c + 25, 850], [c + 25, 1050], [c - 25, 1050]]))
        eq = [nm, "ХВС, ГВС, К50"]
    elif k == "sink":
        items += [dict(type="plinth", s0=s0, s1=s1, z0=0, z1=100), dict(type="base", s0=s0, s1=s1, z0=100, z1=850),
                  dict(type="worktop", s0=s0 - 10, s1=s1 + 10, z0=850, z1=890, label="мойка")]
        fx.append(dict(name="смеситель", poly=[[c - 25, 890], [c + 25, 890], [c + 25, 1150], [c - 25, 1150]]))
        eq = [nm, "ХВС, ГВС, К50"]
    elif k == "heater":
        z = f.get("z") or [1300, 2100]
        fx.append(dict(name="водонагреватель", poly=[[c - 225, z[0]], [c + 225, z[0]], [c + 225, z[1]], [c - 225, z[1]]]))
        items.append(dict(type="panel", s0=c - 5, s1=c + 5, z0=z[0], z1=z[0] - 1, label=None))
        eq = [nm, "ХВС, ГВС, розетка 16 А"]
    elif k in ("cabinet", "wardrobe"):
        h = int(f.get("h") or (1800 if k == "cabinet" else 2000))
        if "стеллаж" in nm.lower():
            items += [dict(type="side", s0=s0, s1=s0 + 30, z0=0, z1=h), dict(type="side", s0=s1 - 30, s1=s1, z0=0, z1=h)]
            for zz in range(150, h, 400):
                items.append(dict(type="shelf", s0=s0 + 30, s1=s1 - 30, z0=zz, z1=zz + 25))
            items.append(dict(type="shelf", s0=s0 + 30, s1=s1 - 30, z0=h - 25, z1=h, label="стеллаж h%d" % h))
        else:
            items.append(dict(type="tall", s0=s0, s1=s1, z0=0, z1=h, label=nm.split(" ")[0].lower()))
    elif k == "mirror":
        z = f.get("z") or [1100, 1700]
        fx.append(dict(name="зеркало", poly=[[s0, z[0]], [s1, z[0]], [s1, z[1]], [s0, z[1]]], glass=True))
    elif k == "fridge":
        h = int(f.get("h") or 1850)
        items.append(dict(type="appliance", s0=s0, s1=s1, z0=0, z1=h, label="холодильник"))
    return items, fx, eq


def _backed_on(P, f, g, room, E):
    """The item stands against this very wall (its back face lies on the elevation line), not against the wall
    meeting it at the corner."""
    hung = f.get("kind") == "wc" and (f.get("hung") or "подвес" in (f.get("name") or "").lower())
    back = T.back_side(P, g, room, max_d=450 if hung else 150)      # a hung WC: in front of its box
    if back is None:
        return False
    seg = back[0]
    (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
    L_ = math.hypot(bx - ax, by - ay) or 1.0
    par = abs((bx - ax) / L_ * E.ux[1] - (by - ay) / L_ * E.ux[0]) < 0.05
    return par and E.line.distance(seg.interpolate(0.5, normalized=True)) < 5


def _elevations(d, P, log):
    """Elevations where the builder needs them: every tiled wall of the wet rooms (with fixtures, outlets, windows or
    long enough to need a layout) and the walls with sinks / basins / water heaters elsewhere (bar, utility)."""
    out = []
    wet = [r for r in P.rooms if r.get("cls") == "wet"]
    # adjacent wet rooms (a WC lobby with its cubicles) are one group: one plan, one materials table
    groups, seen = [], set()
    for r in wet:
        if r["name"] in seen:
            continue
        grp, todo = [r], [r]
        seen.add(r["name"])
        while todo:
            x = todo.pop()
            for e in T.room_entrances(P, x):
                o = e.get("other")
                if o is not None and o.get("cls") == "wet" and o["name"] not in seen:
                    seen.add(o["name"])
                    grp.append(o)
                    todo.append(o)
        groups.append(grp)
    wall_items = ("basin", "sink", "heater", "wc", "mirror", "cabinet", "wardrobe", "fridge")
    others = [r for r in P.rooms if r.get("cls") in ("bar", "storage", "kitchen")]
    for grp in groups + [[r] for r in others]:
        is_wet = grp[0].get("cls") == "wet"
        gname = grp[0]["name"] if len(grp) == 1 else ("Санузлы" if is_wet else grp[0]["name"])
        letters = iter(ELEV_LETTERS)
        n_before = len(out)
        for room in sorted(grp, key=lambda r: (-r["shp"].centroid.y, r["shp"].centroid.x)):
            H = int(room.get("ceiling_level") or P.ceiling)
            furn = [(f, g) for f, g in T.furniture_shapes(P, wall_items) if _room_of(P, f, g) is room]
            for a, b in _faces_cw(room):
                L_ = math.hypot(b[0] - a[0], b[1] - a[1])
                if L_ < 500:
                    continue
                e = dict(group=gname, room=room["name"], a=[_r(a[0]), _r(a[1])], b=[_r(b[0]), _r(b[1])], height=H,
                         tile=[600, 1200], proposed=True)
                from .sheets_details import Elev
                E = Elev(P, e)
                items, fixtures, eqs = [], [], []
                for f, g in furn:
                    if not _backed_on(P, f, g, room, E):
                        continue
                    it, fx, eq = _fixture_elev(f, g, E, room, P)
                    items += [x for x in it if x.get("z1", 0) > x.get("z0", 0)]
                    fixtures += fx
                    if eq:
                        eqs.append(eq)
                pts = [o for o in P.plumbing if o.get("h", 0) > 0 and E.on_wall(o["x"], o["y"])]
                socks = [o for o in P.sockets if E.on_wall(o["x"], o["y"], 60) and o.get("mount") != "furniture"]
                wins = [op for op in E.openings() if op["o"]["kind"] == "window"]
                busy = bool(items or fixtures or pts or socks or wins) if is_wet else bool(pts)
                if not busy and (not is_wet or L_ < 1800):
                    continue
                if any(f.get("kind") == "wc" and f.get("hung") and _backed_on(P, f, g, room, E) for f, g in furn):
                    top = min([op["z0"] for op in wins if op["z0"] > 600] + [1200])
                    ib = [b for b in P.boxes if b.get("box") == "install" and b["shape"].distance(E.line) < 300]
                    if ib:                               # the box of the partitions plan (its height decided there)
                        top = ib[0].get("h", top)
                    items.insert(0, dict(type="panel", s0=0, s1=_r(E.L), z0=0, z1=top,
                                         label=("короб инсталляции %+.3f" % (top / 1000.0)).replace(".", ",")))
                F = P.finishes or {}
                if is_wet and F.get("source") == "model" and not F.get("by_class", {}).get("wet"):
                    # the model's finish (plaster) with tile only where the model / the boxes have it: the
                    # installation box face; no tiled walls the designer did not draw
                    e["base"] = "paint"
                    tz = []
                    for b in P.boxes:
                        if b.get("box") not in ("install", "pipe") or b["shape"].distance(E.line) > 300:
                            continue
                        x0, y0, x1, y1 = b["shape"].bounds
                        ss = sorted(E.s_of(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
                        s0, s1 = max(0.0, ss[0]), min(E.L, ss[-1])
                        if s1 - s0 > 50:
                            tz.append((s0, s1, min(H, b.get("h", 1200))))
                    zones = []
                    cur = 0.0
                    for s0, s1, zt in sorted(tz):
                        if s0 > cur:
                            zones.append(dict(s0=_r(cur), s1=_r(s0), z0=0, z1=H, mat="paint"))
                        zones.append(dict(s0=_r(s0), s1=_r(s1), z0=0, z1=_r(zt), mat="tile",
                                          tile=list(F.get("tile") or [100, 100])))
                        if zt < H:
                            zones.append(dict(s0=_r(s0), s1=_r(s1), z0=_r(zt), z1=H, mat="paint"))
                        cur = s1
                    if cur < E.L:
                        zones.append(dict(s0=_r(cur), s1=_r(E.L), z0=0, z1=H, mat="paint"))
                    e["zones"] = zones
                elif is_wet:
                    e["base"] = "tile"
                    e["zones"] = [dict(s0=0, s1=_r(E.L), z0=0, z1=H, mat="tile")]
                else:
                    e["base"] = "paint"
                    zones = []
                    for f, g in furn:
                        if f.get("kind") not in ("sink", "basin"):
                            continue
                        back = T.back_side(P, g, room)
                        if back is None or back[0].distance(E.line) > 5:
                            continue
                        x0, y0, x1, y1 = g.buffer(150, join_style=2).bounds
                        ss = sorted(E.s_of(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
                        zones.append(dict(s0=_r(max(0.0, ss[0])), s1=_r(min(E.L, ss[-1])), z0=0, z1=1500, mat="apron"))
                    e["zones"] = zones
                    if not zones and not items and not fixtures:
                        continue
                e["items"] = items
                e["fixtures"] = fixtures
                if eqs:
                    e["equipment"] = eqs
                e["label"] = next(letters)
                out.append(e)
        if len(out) > n_before:
            L(log, "развёртки", "развёртки «%s»: %d стен%s" % (gname, len(out) - n_before,
                                                             (" (плитка на всю высоту)" if not (P.finishes or {}).get("source") == "model" else " (отделка по модели, плитка на коробе инсталляции)") if is_wet else " с сантехникой / оборудованием"),
              len(out) - n_before)
    try:
        n0 = len(out)
        out += _feature_walls(d, P)
        if len(out) > n0:
            L(log, "развёртки", "развёртки зала: %d стен с вывесками / светильниками / встроенной мебелью" % (len(out) - n0),
              len(out) - n0)
    except Exception as ex:                       # the album is built without them, the report says why
        L(log, "развёртки", "развёртки стен зала не построены: %r" % (ex,))
    if out:
        d["elevations"] = out
        _note(d, "elevations", "Развёртки - проектное предложение: раскладка плитки и высоты приборов уточняются по выбранной "
                               "сантехнике.")


def print_log(log):
    print("Проектное предложение по нормам: %d раздел(ов)" % len(log))
    for e in log:
        print("  * [%s] %s" % (e["section"], e["msg"]))



# ------------------------------------------------------------------ feature walls of the hall
def _silhouette(m, place, z0, E, px=12.0):
    """Front view outline of an item mesh standing at the wall of elevation E: [(s, z)] (rasterised, traced)."""
    from PIL import Image, ImageDraw
    import numpy as np
    T, _, _ = m.tris(props=True, colour=False)
    if not len(T):
        return None
    if len(T) > 40000:
        T = T[np.linspace(0, len(T) - 1, 40000).astype(int)]
    a = math.radians(place[2] if len(place) > 2 else 0.0)
    xw = T[:, :, 0] * math.cos(a) - T[:, :, 1] * math.sin(a) + place[0]
    yw = T[:, :, 0] * math.sin(a) + T[:, :, 1] * math.cos(a) + place[1]
    S_ = (xw - E.a[0]) * E.ux[0] + (yw - E.a[1]) * E.ux[1]
    Z = T[:, :, 2] + (z0 or 0)
    s0, s1, zt = float(S_.min()), float(S_.max()), float(Z.max())
    nx, ny = int((s1 - s0) / px) + 6, int(zt / px) + 6
    im = Image.new("L", (nx, ny), 0)
    dr = ImageDraw.Draw(im)
    X = (S_ - s0) / px + 3
    Y = ny - 3 - Z / px
    for xs, ys in zip(X, Y):
        dr.polygon([(xs[0], ys[0]), (xs[1], ys[1]), (xs[2], ys[2])], fill=255)
    arr = (np.asarray(im) > 0).astype(float)
    try:
        import contourpy
        lines = contourpy.contour_generator(z=arr).lines(0.5)
    except Exception:
        return None
    best = None
    for ln in lines:
        if len(ln) < 4:
            continue
        g = Polygon([((x - 3) * px + s0, (ny - 3 - y) * px) for x, y in ln]).buffer(0)
        if not g.is_empty and (best is None or g.area > best.area):
            best = g
    if best is None:
        return None
    if best.geom_type == "MultiPolygon":
        best = max(best.geoms, key=lambda q: q.area)
    best = best.simplify(8)
    return [[_r(x), _r(max(0.0, y))] for x, y in list(best.exterior.coords)[:-1]]


def _feature_walls(d, P):
    """Walls of public rooms that carry the design (a sign, wall lights, built-in furniture, tiled boxes) get an
    elevation: what hangs where and at what height - the builder places it by this sheet, not by the render."""
    from . import items as IT
    from . import items3d
    from .sheets_details import Elev
    out = []
    rooms = [r for r in P.rooms if r.get("cls") in ("public", "living", "hall") or r.get("cls") is None]
    texts = d.get("_texts") or []
    signs = [it for it in d.get("items") or [] if it.get("kind") == "sign"]
    F = P.finishes or {}
    for room in rooms:
        H = int(room.get("ceiling_level") or P.ceiling)
        letters = iter(ELEV_LETTERS)
        for a, b in _faces_cw(room):
            L_ = math.hypot(b[0] - a[0], b[1] - a[1])
            if L_ < 1500:
                continue
            if LineString([a, b]).intersection(P.mass.buffer(25)).length < 0.6 * L_:
                continue                                # a separation line (the bar's front), not a wall
            e = dict(group=room["name"], room=room["name"], a=[_r(a[0]), _r(a[1])], b=[_r(b[0]), _r(b[1])], height=H,
                     proposed=True, base="paint", feature=True)
            E = Elev(P, e)
            items, zones, labels, extra_s, extra_h, what = [], [], [], [], [], []
            # boxes at this wall: tiled faces
            for bx in P.boxes:
                if bx.get("box") not in ("seat", "pipe", "column", "low") or \
                        bx["shape"].distance(E.line) > (450 if bx.get("box") == "seat" else 150):
                    continue
                x0, y0, x1, y1 = bx["shape"].bounds
                ss = sorted(E.s_of(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
                s0, s1 = max(0.0, ss[0]), min(L_, ss[-1])
                if s1 - s0 < 100:
                    continue
                zt = min(H, bx.get("h", 1200))
                zones.append(dict(s0=_r(s0), s1=_r(s1), z0=0, z1=_r(zt), mat="tile", tile=list(F.get("tile") or [100, 100]),
                                  front=bx.get("box") == "seat"))
                labels.append(dict(text="%s %s" % (bx["id"], "плитка" if bx.get("box") == "seat" else "короб"),
                                   s=_r((s0 + s1) / 2), z=_r(min(zt * 0.5, 600))))
                extra_s += [_r(s0), _r(s1)]
                extra_h.append(_r(zt))
                what.append(bx["id"])
            # built-in / wall-backed furniture: its front view outline from the model
            for it in d.get("items") or []:
                if it.get("kind") not in IT.WALL_BACKED and it.get("kind") not in ("bench", "sofa"):
                    continue
                for place in it.get("places", []):
                    try:
                        g = IT.footprint(it, place)
                    except Exception:
                        continue
                    if g.distance(E.line) > 450 or not (-200 <= E.s_of(g.centroid.x, g.centroid.y) <= L_ + 200):
                        continue
                    try:
                        m = items3d.load(P, it)
                    except Exception:
                        m = None
                    pts = _silhouette(m, place, it.get("z0"), E) if m is not None else None
                    if not pts:
                        continue
                    items.append(dict(type="poly", pts=pts, rgb=[226, 220, 210], label=it.get("pos", "")))
                    xs = [p[0] for p in pts]
                    extra_s += [_r(max(0, min(xs))), _r(min(L_, max(xs)))]
                    extra_h.append(_r(max(p[1] for p in pts)))
                    what.append(it.get("pos", ""))
            # signs (text objects of the scene) on this wall
            for t in texts:
                x, y, z = t["pos"][0], t["pos"][1], (t["pos"][2] if len(t["pos"]) > 2 else 1500)
                if E.line.distance(Point(x, y)) > 350:
                    continue
                s_ = E.s_of(x, y)
                if not (0 <= s_ <= L_):
                    continue
                words = set(re.findall(r"\w{3,}", t["text"].lower()))
                mark = next((sg.get("pos") for sg in signs if words & set(re.findall(r"\w{3,}", (sg.get("name") or "").lower()))), None)
                items.append(dict(type="sign", s=_r(s_), z=_r(z), text=t["text"], light=t.get("light"), mark=mark))
                extra_s.append(_r(s_))
                extra_h.append(_r(z))
                what.append("«%s»" % t["text"])
            # wall lights
            for f in P.lighting:
                if f["kind"] != "wall" or E.line.distance(Point(f["x"], f["y"])) > 200:
                    continue
                s_ = E.s_of(f["x"], f["y"])
                if 0 <= s_ <= L_:
                    items.append(dict(type="wall_light", s=_r(s_), z=_r(f.get("h", 1600))))
                    extra_s.append(_r(s_))
                    extra_h.append(_r(f.get("h", 1600)))
                    what.append("бра")
            if not what or not any(w.startswith("«") or w == "бра" or w.startswith("М-") for w in what):
                continue
            if zones:                                   # the rest of the wall: its base finish
                cur, zz = 0.0, []
                for z_ in sorted(zones, key=lambda q: q["s0"]):
                    if z_["s0"] > cur:
                        zz.append(dict(s0=_r(cur), s1=z_["s0"], z0=0, z1=H, mat="paint"))
                    zz.append(z_)
                    if z_["z1"] < H:
                        zz.append(dict(s0=z_["s0"], s1=z_["s1"], z0=z_["z1"], z1=H, mat="paint"))
                    cur = max(cur, z_["s1"])
                if cur < L_:
                    zz.append(dict(s0=_r(cur), s1=_r(L_), z0=0, z1=H, mat="paint"))
                e["zones"] = zz
            e["items"] = items
            e["labels"] = labels
            e["extra_s"] = sorted(set(extra_s))
            e["extra_heights"] = sorted(set(extra_h))
            e["fixtures"] = []
            e["label"] = next(letters)
            out.append(e)
    return out
