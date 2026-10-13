# -*- coding: utf-8 -*-
"""Wall elevations (bathrooms, kitchen, any wall), ceiling nodes, openings schedule."""
import math
from shapely.geometry import Polygon, box, LineString, Point
from shapely.ops import unary_union

from . import gfx as S
from . import symbols as Y
from . import dims as DM
from .album import Column, BRONZE
from .placer import Occ, place_text, ring_candidates
from .model import fmt_area

WALL_TILE = (234, 236, 239)
WALL_TILE_J = (196, 199, 204)
WALL_PAINT = (249, 247, 243)
APRON = (231, 225, 214)
ITEM_STYLE = {
    "plinth": ((70, 70, 74), None), "base": ((246, 246, 244), "front"), "tall": ((246, 246, 244), "front"),
    "upper": ((246, 246, 244), "front"), "worktop": ((75, 75, 80), None), "apron": (APRON, None),
    "shelf": ((214, 190, 156), None), "side": ((214, 190, 156), None), "appliance": ((110, 110, 115), None),
    "hob": ((20, 20, 22), None), "glass": (None, "glass"), "panel": ((240, 238, 232), None),
}


# ------------------------------------------------------------------ geometry of an elevation
class Elev:
    def __init__(self, P, e):
        self.P, self.e = P, e
        self.a = tuple(e["a"])
        self.b = tuple(e["b"])
        self.L = math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])
        self.ux = ((self.b[0] - self.a[0]) / self.L, (self.b[1] - self.a[1]) / self.L)
        self.H = e.get("height", P.ceiling)
        self.line = LineString([self.a, self.b])

    def s_of(self, x, y):
        return (x - self.a[0]) * self.ux[0] + (y - self.a[1]) * self.ux[1]

    def on_wall(self, x, y, tol=160):
        s = self.s_of(x, y)
        return self.line.distance(Point(x, y)) < tol and -5 <= s <= self.L + 5

    def openings(self):
        out = []
        for o in self.P.openings:
            r = self.P.open_shape[o["id"]]
            if r.buffer(40).intersection(self.line).length > 50:
                # the opening's own extent along the wall (no buffer: 900 must stay 900, lesson L-033)
                ss = sorted(self.s_of(x, y) for x, y in list(r.exterior.coords)[:-1])
                out.append(dict(o=o, s0=max(0.0, ss[0]), s1=min(self.L, ss[-1]), z0=o.get("sill", 0) if o["kind"] == "window" else 0,
                                z1=(o.get("sill", 0) + o["h"]) if o["kind"] == "window" else o["h"]))
        return out


def draw_elevation(sp, P, e, k=25, occ=None):
    E = Elev(P, e)
    L, H = E.L, E.H
    occ = occ or Occ()
    tile = e.get("tile", [600, 1200])
    base_fill = e.get("base", "paint")
    S.fill(sp, [(0, 0), (L, 0), (L, H), (0, H)], WALL_PAINT if base_fill == "paint" else WALL_TILE, "SD_Штриховка")
    for zn in e.get("zones", []):
        pts = [(zn["s0"], zn["z0"]), (zn["s1"], zn["z0"]), (zn["s1"], zn["z1"]), (zn["s0"], zn["z1"])]
        if zn["mat"] in ("tile", "apron"):
            S.fill(sp, pts, WALL_TILE if zn["mat"] == "tile" else APRON, "SD_Штриховка")
            tt = zn.get("tile", tile)
            S.grid_lines(sp, Polygon(pts), tt[0], tt[1], origin=tuple(zn.get("origin", (0, 0))),
                         rgb=WALL_TILE_J if zn["mat"] == "tile" else (200, 192, 178))
        else:
            S.fill(sp, pts, WALL_PAINT, "SD_Штриховка")
        S.poly(sp, pts, "SD_Тонкие", True, (150, 150, 150), 9)
    ops = E.openings()
    for op in ops:
        s0, s1, z0, z1 = op["s0"], op["s1"], op["z0"], op["z1"]
        o = op["o"]
        S.fill(sp, [(s0, z0), (s1, z0), (s1, z1), (s0, z1)], (255, 255, 255), "SD_Двери")
        S.rect(sp, s0, z0, s1, z1, "SD_Двери", (40, 40, 40), 25)
        if o["kind"] == "window":
            S.rect(sp, s0 + 60, z0 + 60, s1 - 60, z1 - 60, "SD_Окна", (110, 110, 110), 13)
        elif o["kind"] in ("door", "balcony"):
            S.rect(sp, s0 + 50, z0, s1 - 50, z1 - 50, "SD_Двери", (110, 110, 110), 13)
            S.circle(sp, (s1 - 120, 1000), 25, "SD_Двери", (60, 60, 60), 13)
        if o.get("mark"):
            g = place_text(sp, occ, o["mark"], [((s0 + s1) / 2, z0 + (z1 - z0) * f) for f in (0.68, 0.5, 0.82)], 2.4 * k, bold=True,
                           rgb=(80, 80, 80))
    for it in e.get("items", []):
        rgb, mode = ITEM_STYLE.get(it.get("type", "panel"), ((240, 240, 240), None))
        pts = [(it["s0"], it["z0"]), (it["s1"], it["z0"]), (it["s1"], it["z1"]), (it["s0"], it["z1"])]
        if rgb:
            S.fill(sp, pts, tuple(it.get("rgb", rgb)), "SD_Мебель")
        if mode == "front":
            gap = it.get("gap", 3)
            S.rect(sp, it["s0"] + gap, it["z0"] + gap, it["s1"] - gap, it["z1"] - gap, "SD_Мебель", (60, 60, 66), 18)
            if it.get("handle") == "gola":
                S.line(sp, (it["s0"], it["z1"] - 30), (it["s1"], it["z1"] - 30), "SD_Мебель", (150, 150, 150), 9)
        elif mode == "glass":
            S.rect(sp, *pts[0], *pts[2], "SD_Мебель", (90, 120, 150), 18)
        else:
            S.poly(sp, pts, "SD_Мебель", True, (90, 90, 95), 13)
        if it.get("label"):
            cx, cz = (it["s0"] + it["s1"]) / 2, (it["z0"] + it["z1"]) / 2
            rot = 90 if (it["s1"] - it["s0"]) < (it["z1"] - it["z0"]) * 0.6 else 0
            place_text(sp, occ, it["label"], [(cx, cz, rot), (cx, cz + 120, rot), (cx, cz - 120, rot)], 1.6 * k,
                       rgb=(110, 100, 90), mask=True)
        if it.get("type") == "led":
            Y.dashed(sp, (it["s0"], it["z0"]), (it["s1"], it["z0"]), 1.0 * k, 0.5 * k, S.C_AMBER, 35)
    for fx in e.get("fixtures", []):
        shp = Polygon(fx["poly"]).buffer(0)
        if shp.is_empty or shp.area < 100:
            continue
        shp = shp.intersection(box(-50, -10, L + 50, H))
        if fx.get("glass"):
            x0, y0, x1, y1 = shp.bounds
            S.rect(sp, x0, y0, x1, y1, "SD_Мебель", (90, 120, 150), 18)
            for t in (0.25, 0.32):
                S.line(sp, (x0 + (x1 - x0) * t, y0 + (y1 - y0) * 0.55), (x0 + (x1 - x0) * (t + 0.18), y0 + (y1 - y0) * 0.75),
                       "SD_Мебель", (120, 150, 180), 13)
            continue
        if not fx.get("outline_only"):
            S.fill(sp, shp, (255, 255, 255), "SD_Мебель")
        Y.outline(sp, shp, (60, 60, 66), 18, "SD_Мебель")
    # bulkheads / boxes of the ceiling plan that touch this wall (lesson L-038: the +2,490 box was missing)
    for z in P.ceilings.get("zones", []):
        if not z.get("bottom") or z["bottom"] >= H:
            continue
        zp = Polygon(z["poly"]).buffer(0)
        if zp.buffer(30).intersection(E.line).length < 50:
            continue
        ssz = sorted(E.s_of(x, y) for x, y in list(zp.exterior.coords)[:-1])
        s0, s1 = max(0.0, ssz[0]), min(L, ssz[-1])
        pts = [(s0, z["bottom"]), (s1, z["bottom"]), (s1, H), (s0, H)]
        S.fill(sp, pts, (232, 236, 242), "SD_Штриховка")
        S.hatch(sp, pts, (150, 160, 180), "ANSI31", scale=0.25 * k)
        S.poly(sp, pts, "SD_Тонкие", True, (60, 60, 66), 25)
        hs_extra = e.setdefault("_box_heights", [])
        hs_extra.append(float(z["bottom"]))
        place_text(sp, occ, ("короб %+.3f" % (z["bottom"] / 1000.0)).replace(".", ","),
                   [((s0 + s1) / 2, (z["bottom"] + H) / 2), ((s0 + s1) / 2, z["bottom"] - 2.5 * k)], 1.6 * k,
                   rgb=(60, 60, 70), mask=True)
    # ceiling & cut lines
    S.fill(sp, [(-120, H), (L + 120, H), (L + 120, H + 90), (-120, H + 90)], (215, 215, 218), "SD_Штриховка")
    S.hatch(sp, [(-120, H), (L + 120, H), (L + 120, H + 90), (-120, H + 90)], (120, 120, 125), "ANSI31", scale=0.2 * k)
    S.line(sp, (-120, 0), (L + 120, 0), "SD_Стены", (20, 20, 20), 50)
    for sx in (0, L):
        S.line(sp, (sx, 0), (sx, H), "SD_Стены", (20, 20, 20), 50)
    S.line(sp, (0, H), (L, H), "SD_Стены", (20, 20, 20), 35)
    # outlets
    hs, ss = {0.0, float(H)}, {0.0, L}
    for o in P.plumbing:
        if o.get("h", 0) > 0 and E.on_wall(o["x"], o["y"]):
            s = E.s_of(o["x"], o["y"])
            elev_water(sp, o["kind"], s, o["h"], k)
            hs.add(float(o["h"]))
            ss.add(round(s))
            occ.add(Point(s, o["h"]).buffer(1.3 * k), "sym")
    for so in P.sockets:
        if E.on_wall(so["x"], so["y"], 60):
            s = E.s_of(so["x"], so["y"])
            g = elev_socket(sp, so["kind"], s, so["h"], k)
            occ.add(g, "sym")
            hs.add(float(so["h"]))
            ss.add(round(s))
            if so.get("group") not in (None, ""):
                place_text(sp, occ, "гр.%s" % so["group"], [(s + 3.2 * k, so["h"], 0, "MIDDLE_LEFT"), (s - 3.2 * k, so["h"], 0, "MIDDLE_RIGHT"),
                                                          (s, so["h"] + 2.6 * k), (s, so["h"] - 2.6 * k)], 1.5 * k, rgb=(150, 40, 40), mask=True)
    for op in ops:
        ss.update([round(op["s0"]), round(op["s1"])])
        hs.add(float(op["z1"]))
        if op["z0"] > 0:
            hs.add(float(op["z0"]))
    for zn in e.get("zones", []):
        if 0 < zn["z1"] < H:
            hs.add(float(zn["z1"]))
    for v in e.get("extra_heights", []) + e.pop("_box_heights", []):
        hs.add(float(v))
    if len(set(round(v) for v in ss)) > 2:          # a chain equal to the overall one is noise (lesson L-039)
        DM.chain(sp, list(ss), -sc25(k, 380), 0, k, occ)
    DM.chain(sp, [0, L], -sc25(k, 700), 0, k, occ)
    if e.get("module_chain"):
        DM.chain(sp, e["module_chain"], -sc25(k, 1020), 0, k, occ)
    if e.get("heights"):
        DM.chain(sp, sorted(set(float(v) for v in e["heights"])), L + sc25(k, 330), L, k, occ, vertical=True)
        if len(hs) > 2:
            DM.chain(sp, sorted(hs), -sc25(k, 330), 0, k, occ, vertical=True)
    else:
        DM.chain(sp, sorted(hs), L + sc25(k, 330), L, k, occ, vertical=True)
    for t in e.get("labels", []):
        place_text(sp, occ, t["text"], [(t["s"], t["z"]), (t["s"], t["z"] + 2.5 * k), (t["s"], t["z"] - 2.5 * k)], 1.7 * k,
                   rgb=(90, 80, 70), mask=True)
    return E


def sc25(k, v):
    return v * k / 25.0


def elev_socket(sp, kind, s, z, k):
    col = Y.SOCKET_RGB.get(kind, S.C_RED)
    if kind in ("Р", "Р2", "РВ", "Р32"):
        n = 2 if kind == "Р2" else 1
        for i in range(n):
            cx = s + (i - (n - 1) / 2.0) * 2.8 * k
            S.fill(sp, Point(cx, z).buffer(1.3 * k, 24), (255, 255, 255), "SD_Электрика")
            S.circle(sp, (cx, z), 1.3 * k, "SD_Электрика", col, 25)
            for dx in (-0.45, 0.45):
                S.fill(sp, Point(cx + dx * k, z).buffer(0.18 * k, 8), col, "SD_Электрика")
            if kind == "РВ":
                S.line(sp, (cx - 1.3 * k, z + 1.0 * k), (cx + 1.3 * k, z + 1.0 * k), "SD_Электрика", col, 25)
        return box(s - (1.5 + 1.4 * (n - 1)) * k, z - 1.5 * k, s + (1.5 + 1.4 * (n - 1)) * k, z + 1.5 * k)
    if kind in ("БРА",):
        d = 0.8 * k
        S.rect(sp, s - d, z - d, s + d, z + d, "SD_Электрика", col, 25)
        S.line(sp, (s - d, z - d), (s + d, z + d), "SD_Электрика", col, 13)
        S.line(sp, (s - d, z + d), (s + d, z - d), "SD_Электрика", col, 13)
        return box(s - d, z - d, s + d, z + d).buffer(0.3 * k)
    d = 0.7 * k
    S.fill(sp, [(s - d, z - d), (s + d, z - d), (s + d, z + d), (s - d, z + d)], col, "SD_Электрика")
    return box(s - d, z - d, s + d, z + d).buffer(0.3 * k)


def elev_water(sp, kind, s, z, k):
    col = Y.WATER_RGB.get(kind, S.C_BLUE)
    r = 0.9 * k if kind != "К110" else 1.3 * k
    S.fill(sp, Point(s, z).buffer(r, 24), col, "SD_Вода")
    S.circle(sp, (s, z), r, "SD_Вода", (30, 30, 30), 13)


# ------------------------------------------------------------------ elevation sheets
def groups(P):
    out = []
    for e in P.elevations:                      # groups in project order, elevations by letter (А, Б, В, Г)
        g = e.get("group") or e.get("room") or "Развёртки"
        for x in out:
            if x["name"] == g:
                x["elevs"].append(e)
                break
        else:
            out.append(dict(name=g, elevs=[e]))
    for x in out:
        x["elevs"].sort(key=lambda e: e.get("label", ""))
    return out


def elev_window(E, e, k):
    left = sc25(k, 520) if e.get("heights") else sc25(k, 250)
    bottom = sc25(k, 1300) if e.get("module_chain") else sc25(k, 950)
    return (-left, -bottom, E.L + sc25(k, 720), E.H + sc25(k, 350))


def elevation_sheets(A):
    P = A.P
    out = []
    for g in groups(P):
        room = P.room_by_name.get(g["name"])
        with_plan = room is not None and g.get("plan", True) and room.get("cls") == "wet"
        k = 25
        widths = []
        for e in g["elevs"]:
            E = Elev(P, e)
            w = elev_window(E, e, k)
            widths.append((w[2] - w[0]) / k)
        pages = []
        cur, used = [], (140.0 if with_plan else 0.0)
        for e, w in zip(g["elevs"], widths):
            if cur and used + w + 6 > 388:
                pages.append(cur)
                cur, used = [], 0.0
            cur.append(e)
            used += w + 6
        if cur:
            pages.append(cur)
        for i, pg in enumerate(pages):
            labels = ", ".join(e.get("label", "") for e in pg)
            if with_plan and i == 0:
                title = "%s. План, развёртки %s" % (g["name"], labels)
            else:
                title = "%s. Развёртки %s" % (g["name"], labels) if len(pg) > 1 else "%s. Развёртка %s" % (g["name"], labels)
            if g["name"].lower().startswith("кухня") and len(pg) == 1:
                title = "%s. Развёртка %s" % (g["name"], labels)
            out.append((title, "1:25", elevation_sheet, dict(group=g, elevs=pg, plan=with_plan and i == 0,
                                                             last=(i == len(pages) - 1), room=room)))
    if P.nodes:
        out.append(("Узлы", "по видам", nodes_sheet, dict()))
    return out


def elevation_sheet(A, no, title, scale, arg):
    P = A.P
    k = 25
    sub = "Развёртки стен 1:25 (вид из помещения). Раскладка, выводы, размеры от чистого пола"
    psp = A.make_sheet(no, title, scale, sub)
    x0 = 24.0
    if arg["plan"]:
        x0 = bath_plan(A, psp, no, arg["room"]) + 10
    for i, e in enumerate(arg["elevs"]):
        blk, off = A.model_block(no, i + 1)
        occ = Occ()
        E = draw_elevation(blk, P, e, k, occ)
        win = elev_window(E, e, k)
        r = A.vp(psp, off, win, (x0, 64.0), k)
        A.title_note(psp, r[0] + 4, r[3] + 1.5, "Развёртка %s" % e.get("label", ""), "1:25")
        x0 = r[2] + 6
    # right part / below: materials + notes on the last sheet of a group
    room = arg["room"]
    if arg["last"]:
        free_x = max(x0, 250.0)
        if 412 - free_x >= 85:
            col = Column(A, psp, x=free_x, top=COL_TOP_D, width=412 - free_x)
            _group_tables(A, col, arg)
        else:
            col = Column(A, psp, x=24.0, top=58.0, width=150.0, bottom=8.0)
            _group_tables(A, col, arg, compact=True)


COL_TOP_D = 258.0


def elev_material_areas(P, elevs):
    """Tile / paint areas of a set of elevations, openings deducted; apron_h - height of the apron zone."""
    tile_area, paint_area, apron_h = 0.0, 0.0, 0.0
    for e in elevs:
        E = Elev(P, e)
        for zn in e.get("zones", []):
            a = (zn["s1"] - zn["s0"]) * (zn["z1"] - zn["z0"]) / 1e6
            if zn["mat"] in ("tile", "apron"):
                tile_area += a
            else:
                paint_area += a
            if zn["mat"] == "apron":
                apron_h = max(apron_h, zn["z1"] - zn["z0"])
        for op in E.openings():
            for zn in e.get("zones", []):
                ov = max(0.0, min(op["s1"], zn["s1"]) - max(op["s0"], zn["s0"])) * max(0.0, min(op["z1"], zn["z1"]) - max(op["z0"], zn["z0"])) / 1e6
                if zn["mat"] in ("tile", "apron"):
                    tile_area -= ov
                else:
                    paint_area -= ov
    return dict(tile=tile_area, paint=paint_area, apron_h=apron_h)


def waterproofing(P, room):
    """Floor + 200 mm up the walls + shower / bath zone up to 2000 mm on the walls the tray stands against."""
    a = room["area_exact"] + room["perimeter"] * 0.2
    b = room["shp"].boundary
    for f in P.furniture:
        if f.get("room") != room["name"] or f.get("kind") not in ("shower", "bath"):
            continue
        x0, y0, x1, y1 = Polygon(f["poly"]).bounds
        for (pa, pb) in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            ln = LineString([pa, pb])
            if ln.centroid.distance(b) < 40:
                a += ln.length / 1000.0 * 1.8
    return a


def _group_tables(A, col, arg, compact=False):
    P = A.P
    g = arg["group"]
    rows = []
    m = elev_material_areas(P, g["elevs"])
    tile_area, paint_area = m["tile"], m["paint"]
    room = arg["room"]
    if tile_area > 0:
        rows.append(["Керамогранит / плитка стен", fmt_area(tile_area), fmt_area(tile_area * 1.1)])
    if room is not None:
        fl = P.floor_of_room(room["name"])
        if fl and fl.get("pattern") == "tile":
            rows.append(["Плитка пола %s" % "×".join(map(str, fl.get("tile", [600, 600]))), fmt_area(room["area"]),
                         fmt_area(room["area"] * 1.1)])
    if paint_area > 0:
        rows.append(["Окраска (влагостойкая)", fmt_area(paint_area), "-"])
    if room is not None and room.get("cls") == "wet":
        rows.append(["Гидроизоляция обмазочная (пол, стены 200 мм, душ 2000 мм)", fmt_area(waterproofing(P, room)), "-"])
    for r in g.get("materials", []):
        rows.append(r)
    eq = []
    for e in g["elevs"]:
        eq += e.get("equipment", [])
    if rows:
        col.table([60, 22, 22], ["Материал", "Площадь, м²", "С запасом"], rows, title="Ведомость материалов", h=1.6,
                  aligns=["L", "C", "C"])
    if eq:
        col.table([70, 34], ["Оборудование", "Подключение"], eq, title="Оборудование и подключения", h=1.6, aligns=["L", "L"])
    notes = []
    for e in g["elevs"]:
        notes += [n for n in e.get("notes", []) if n not in notes]
    if room is not None and room.get("cls") == "wet":
        notes = notes or [
            "Раскладка - от угла по развёртке; вертикальные швы стен совпадают со швами пола.",
            "Наружные углы - запил 45°, внутренние - профиль / герметик в цвет затирки.",
            "Гидроизоляция: пол + стены 200 мм, зона душа - 2000 мм; ленты в углах и примыканиях.",
            "Выводы - по чистовой поверхности стен, допуск ±5 мм; сверить с паспортами сантехники.",
        ]
    col.notes(notes)


def bath_plan(A, psp, no, room):
    """Room plan at 1:25 with wall markers; returns right edge of its viewport on the sheet."""
    P = A.P
    k = 25
    blk, off = A.model_block(no, 0)
    occ = Occ()
    shp = room["shp"]
    from . import sheets_plans as SP
    for f, g in P.floor_zones():
        part = g.intersection(shp.buffer(250, join_style=2))
        if part.is_empty:
            continue
        if f.get("pattern") == "tile":
            S.fill(blk, part, Y.TILE, "SD_Штриховка")
            org, _ = Y.tile_origin(P, room["name"], part)
            S.grid_lines(blk, part, *f.get("tile", [600, 600]), origin=org, rgb=Y.TILE_J)
        else:
            S.fill(blk, part, Y.PARQUET, "SD_Штриховка")
    Y.furniture_all(blk, P, k, rooms=[room["name"]])
    for f in P.furniture:
        if f.get("room") == room["name"] and f.get("kind") != "rug":
            occ.add(Polygon(f["poly"]).buffer(0), "furn")
    Y.draw_walls(blk, P, k, show_boxes=True)
    Y.draw_openings(blk, P, k)
    occ.add(P.shell_cut, "wall")
    for g in P.parts.values():
        occ.add(g, "wall")
    for o in P.plumbing:
        if shp.buffer(80).contains(Point(o["x"], o["y"])):
            c, g = Y.water_icon(blk, P, o, k)
            occ.add(g, "sym")
    for so in P.sockets:
        if shp.buffer(80).contains(Point(so["x"], so["y"])):
            occ.add(Y.socket_icon(blk, so, k), "sym")
    # wall markers
    elevs = [e for e in P.elevations if (e.get("group") or e.get("room")) == room["name"]]
    from shapely.ops import polylabel
    free = shp.buffer(-150)
    for f in P.furniture:
        if f.get("room") == room["name"]:
            free = free.difference(Polygon(f["poly"]).buffer(80))
    if free.is_empty:
        free = shp.buffer(-150)
    fp = free if free.geom_type == "Polygon" else max(free.geoms, key=lambda g: g.area)
    c = polylabel(fp, 5)
    cx, cy = c.x, c.y
    r = 2.2 * k
    S.fill(blk, Point(cx, cy).buffer(r, 32), (255, 255, 255), "SD_Текст")
    S.circle(blk, (cx, cy), r, "SD_Тонкие", (30, 30, 30), 25)
    occ.add(Point(cx, cy).buffer(r + 3 * k), "sym")
    for e in elevs:
        E = Elev(P, e)
        # facing direction = normal from the room towards the wall
        n = (E.ux[1], -E.ux[0])          # right-hand normal of a->b (wall seen from inside, left->right)
        mid = ((E.a[0] + E.b[0]) / 2, (E.a[1] + E.b[1]) / 2)
        if (mid[0] - cx) * n[0] + (mid[1] - cy) * n[1] < 0:
            n = (-n[0], -n[1])
        tip = (cx + n[0] * (r + 2.6 * k), cy + n[1] * (r + 2.6 * k))
        t = (-n[1], n[0])
        b1 = (cx + n[0] * r + t[0] * 1.6 * k, cy + n[1] * r + t[1] * 1.6 * k)
        b2 = (cx + n[0] * r - t[0] * 1.6 * k, cy + n[1] * r - t[1] * 1.6 * k)
        S.fill(blk, [tip, b1, b2], (30, 30, 30), "SD_Текст")
        lp = (cx + n[0] * (r + 4.8 * k), cy + n[1] * (r + 4.8 * k))
        S.text(blk, e.get("label", ""), lp, 2.6 * k, "MIDDLE_CENTER", bold=True)
        occ.add(Point(lp).buffer(2.0 * k), "tag")
    # bindings: fixtures and outlets along each wall
    pts = [("pt", (o["x"], o["y"])) for o in P.plumbing if o.get("h", 0) > 0 and shp.buffer(80).contains(Point(o["x"], o["y"]))]
    for f in P.furniture:
        if f.get("room") != room["name"] or f.get("kind") in ("rug", "rail", "mirror"):
            continue
        pts.append(("box", Polygon(f["poly"]).buffer(0).bounds))
    _edge_chains_outside(blk, P, room, pts, k, occ)
    x0, y0, x1, y1 = shp.bounds
    m = 950
    win = (x0 - m, y0 - m, x1 + m, y1 + m)
    w = (win[2] - win[0]) / k
    h = (win[3] - win[1]) / k
    rr = A.vp(psp, off, win, (24.0, 254.0 - h), k)
    A.title_note(psp, rr[0], rr[3] + 1.5, "План", "1:25")
    # legend under the plan
    items = [(_lg_fill(WALL_TILE), "Плитка / керамогранит стен"), (_lg_floor_tile, "Плитка пола"),
             (_lg_fill(WALL_PAINT), "Окраска влагостойкой краской"),
             (_lg_water3, "Выводы ХВС / ГВС / канализация")]
    S.legend(psp, 24.0, rr[1] - 9.0, items, title="Обозначения", w1=16.0, w2=min(96.0, w - 16.0), rh=5.2)
    return rr[2]


def _wall_thickness(P, p, n, maxd=1200):
    """Thickness of the construction behind a room face point p in outward direction n."""
    ln = LineString([(p[0] + n[0] * 2, p[1] + n[1] * 2), (p[0] + n[0] * maxd, p[1] + n[1] * maxd)])
    g = ln.intersection(P.mass)
    if g.is_empty:
        return 0.0
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    first = min(parts, key=lambda q: q.distance(Point(p)))
    return first.distance(Point(p)) + first.length + 2


def _edge_chains_outside(sp, P, room, items, k, occ, merge=25.0):
    """One chain per room side, outside the room beyond the wall: outlets on that wall + the extents of the
    fixtures standing against it. Values closer than `merge` to each other / to the corners collapse."""
    shp = room["shp"]
    x0, y0, x1, y1 = shp.bounds
    sides = {"B": [], "T": [], "L": [], "R": []}
    for kind, v in items:
        if kind == "pt":
            d = {"B": abs(v[1] - y0), "T": abs(v[1] - y1), "L": abs(v[0] - x0), "R": abs(v[0] - x1)}
            sides[min(d, key=d.get)].append(v[0] if min(d, key=d.get) in "BT" else v[1])
        else:
            bx0, by0, bx1, by1 = v
            d = {"B": by0 - y0, "T": y1 - by1, "L": bx0 - x0, "R": x1 - bx1}
            s_ = min(d, key=d.get)
            sides[s_] += [bx0, bx1] if s_ in "BT" else [by0, by1]
    for s_, vs in sides.items():
        if not vs:
            continue
        horiz = s_ in "BT"
        lo, hi = (x0, x1) if horiz else (y0, y1)
        vals = [lo, hi] + [v for v in vs if lo + merge < v < hi - merge]
        face = {"B": y0, "T": y1, "L": x0, "R": x1}[s_]
        n = {"B": (0, -1), "T": (0, 1), "L": (-1, 0), "R": (1, 0)}[s_]
        mid = ((lo + hi) / 2.0, face) if horiz else (face, (lo + hi) / 2.0)
        t = _wall_thickness(P, mid, n) or 120
        sg = -1 if s_ in "BL" else 1
        ext = face + sg * min(t, 120)
        pos = face + sg * (t + 380)
        DM.chain(sp, vals, pos, ext, k, occ, vertical=not horiz, merge=merge)


def _lg_fill(rgb, outline=(110, 110, 110), w=12, h=3.6):
    def fn(psp, cx, cy):
        pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
        S.fill(psp, pts, rgb, "SD_Таблицы")
        S.poly(psp, pts, "SD_Таблицы", True, outline, 13)
    return fn


def _lg_floor_tile(psp, cx, cy, w=12, h=3.6):
    """Floor tile swatch differs from the wall tile one: grey with a joint grid (review s13)."""
    pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    S.fill(psp, pts, (206, 208, 212), "SD_Таблицы")
    for i in (1, 2, 3):
        S.line(psp, (cx - w / 2 + w * i / 4, cy - h / 2), (cx - w / 2 + w * i / 4, cy + h / 2), "SD_Таблицы", (150, 150, 155), 9)
    S.line(psp, (cx - w / 2, cy), (cx + w / 2, cy), "SD_Таблицы", (150, 150, 155), 9)
    S.poly(psp, pts, "SD_Таблицы", True, (110, 110, 110), 13)


def _lg_water3(psp, cx, cy):
    elev_water(psp, "ХВС", cx - 3, cy, 1.0)
    elev_water(psp, "ГВС", cx, cy, 1.0)
    elev_water(psp, "К50", cx + 3, cy, 1.0)


# ------------------------------------------------------------------ ceiling nodes
NODE_ITEMS = ["Плита перекрытия ж/б", "Стена; штукатурка, окраска", "ГКЛ / ГКЛВ 12,5 мм; шпаклёвка, окраска",
              "Профиль ПП 60×27 с прямым подвесом", "Профиль ПН 28×27", "Потолочный карниз", "LED-профиль алюм., лента 24 В",
              "Теневой профиль алюм.", "Перфоуголок, шпаклёвка", "Штора"]


def hatch_concrete(sp, pts, k):
    S.fill(sp, pts, (232, 232, 234), "SD_Штриховка")
    try:
        S.hatch(sp, pts, (140, 140, 145), "AR-CONC", scale=0.035 * k)
    except Exception:
        S.hatch(sp, pts, (140, 140, 145), "ANSI31", scale=0.3 * k)
    S.poly(sp, pts, "SD_Стены", True, (40, 40, 40), 35)


def gkl(sp, pts, k):
    S.fill(sp, pts, (250, 250, 250), "SD_Штриховка")
    S.hatch(sp, pts, (150, 150, 150), "ANSI37", scale=0.06 * k)
    S.poly(sp, pts, "SD_Тонкие", True, (40, 40, 40), 25)


def profile_pp(sp, x, z, k, w=60, h=27, rgb=(80, 80, 90)):
    S.poly(sp, [(x - w / 2, z + h), (x - w / 2, z), (x + w / 2, z), (x + w / 2, z + h)], "SD_Тонкие", False, rgb, 25)


def led_rays(sp, p, a0, a1, L, k):
    for a in (a0, (a0 + a1) / 2, a1):
        Y.dashed(sp, p, (p[0] + L * math.cos(math.radians(a)), p[1] + L * math.sin(math.radians(a))), 0.8 * k, 0.6 * k, S.C_AMBER, 13)


def node_marks(sp, items, k):
    for n_, p, q in items:
        if p != q:
            S.line(sp, p, q, "SD_Тонкие", (60, 60, 60), 13)
            S.fill(sp, Point(p).buffer(0.35 * k, 12), (60, 60, 60), "SD_Тонкие")
        Y.mark_circle(sp, str(n_), q, k, r=1.5, h=1.6, rgb=(60, 60, 60))


def node_curtain_niche(sp, k, p):
    W = p.get("niche", 130)
    lv = p.get("ceiling", 2800)
    sl = p.get("slab", 3200)
    hatch_concrete(sp, [(-200, lv - 250), (0, lv - 250), (0, sl), (-200, sl)], k)
    hatch_concrete(sp, [(-200, sl), (W + 430, sl), (W + 430, sl + 120), (-200, sl + 120)], k)
    gkl(sp, [(W, lv), (W + 430, lv), (W + 430, lv + 12.5), (W, lv + 12.5)], k)
    gkl(sp, [(W, lv), (W + 12.5, lv), (W + 12.5, sl), (W, sl)], k)
    S.rect(sp, W + 12.5, lv + 12.5, W + 40, sl, "SD_Тонкие", (80, 80, 90), 18)
    for x in (W + 170, W + 370):
        profile_pp(sp, x, lv + 12.5, k)
        S.line(sp, (x, lv + 39.5), (x, sl), "SD_Тонкие", (80, 80, 90), 18)
    S.fill(sp, [(40, sl - 30), (95, sl - 30), (95, sl), (40, sl)], (90, 90, 95), "SD_Тонкие")
    S.fill(sp, [(W - 18, sl - 80), (W, sl - 80), (W, sl - 50), (W - 18, sl - 50)], S.C_AMBER, "SD_Тонкие")
    led_rays(sp, (W - 18, sl - 65), 200, 250, 260, k)
    Y.dashed(sp, (60, sl - 30), (60, lv - 240), 1.2 * k, 0.8 * k, (150, 120, 90), 18)
    DM.chain(sp, [0, W], lv - 120, lv, k)
    DM.chain(sp, [lv, sl], W + 460, W + 430, k, vertical=True)
    Y.section_level(sp, (W + 230, lv), ("%+.3f" % (lv / 1000.0)).replace(".", ","), k)
    node_marks(sp, [(1, (250, sl + 60), (250, sl + 60)), (2, (-100, lv - 100), (-100, lv - 100)),
                    (3, (W + 350, lv + 6), (W + 350, lv - 100)), (4, (W + 170, lv + 30), (W + 270, lv + 180)),
                    (5, (W + 26, lv + 250), (W + 130, lv + 280)), (6, (67, sl - 15), (W + 90, sl - 50)),
                    (7, (W - 9, sl - 65), (W + 100, lv + 160)), (10, (60, lv - 150), (W + 60, lv - 180))], k)
    return (-260, lv - 260, W + 520, sl + 160)


def node_shadow_gap(sp, k, p):
    G = p.get("gap", 40)
    lv = p.get("ceiling", 2800)
    sl = p.get("slab", 3200)
    hatch_concrete(sp, [(-200, lv - 250), (0, lv - 250), (0, sl), (-200, sl)], k)
    hatch_concrete(sp, [(-200, sl), (560, sl), (560, sl + 120), (-200, sl + 120)], k)
    gkl(sp, [(G, lv), (560, lv), (560, lv + 12.5), (G, lv + 12.5)], k)
    S.poly(sp, [(0, lv + 60), (G, lv + 60), (G, lv), (G + 12, lv)], "SD_Тонкие", False, (60, 60, 70), 35)
    S.line(sp, (0, lv + 60), (0, lv - 10), "SD_Тонкие", (60, 60, 70), 35)
    S.fill(sp, [(6, lv + 48), (G - 6, lv + 48), (G - 6, lv + 58), (6, lv + 58)], S.C_AMBER, "SD_Тонкие")
    led_rays(sp, (G / 2, lv + 48), 250, 290, 220, k)
    for x in (200, 450):
        profile_pp(sp, x, lv + 12.5, k)
        S.line(sp, (x, lv + 39.5), (x, sl), "SD_Тонкие", (80, 80, 90), 18)
    DM.chain(sp, [0, G], lv - 120, lv, k)
    Y.section_level(sp, (300, lv), ("%+.3f" % (lv / 1000.0)).replace(".", ","), k)
    node_marks(sp, [(1, (250, sl + 60), (250, sl + 60)), (2, (-100, lv - 100), (-100, lv - 100)),
                    (3, (480, lv + 6), (480, lv - 100)), (4, (200, lv + 30), (320, lv + 180)),
                    (8, (G, lv + 40), (150, lv + 160)), (7, (G / 2, lv + 53), (110, lv + 300))], k)
    return (-260, lv - 260, 620, sl + 160)


def node_bulkhead(sp, k, p):
    W = p.get("width", 400)
    bot = p.get("bottom", 2400)
    lv = p.get("ceiling", 2800)
    sl = p.get("slab", 3200)
    x0, x1 = 0.0, W
    hatch_concrete(sp, [(-340, sl), (W + 360, sl), (W + 360, sl + 130), (-340, sl + 130)], k)
    gkl(sp, [(-340, lv), (x0, lv), (x0, lv + 12.5), (-340, lv + 12.5)], k)
    gkl(sp, [(x1, lv), (W + 360, lv), (W + 360, lv + 12.5), (x1, lv + 12.5)], k)
    gkl(sp, [(x0 - 12.5, bot), (x1 + 12.5, bot), (x1 + 12.5, bot + 12.5), (x0 - 12.5, bot + 12.5)], k)
    gkl(sp, [(x0 - 12.5, bot + 12.5), (x0, bot + 12.5), (x0, lv + 12.5), (x0 - 12.5, lv + 12.5)], k)
    gkl(sp, [(x1, bot + 12.5), (x1 + 12.5, bot + 12.5), (x1 + 12.5, lv + 12.5), (x1, lv + 12.5)], k)
    for x in (x0 + 20, x1 - 20):
        S.line(sp, (x, bot + 12.5), (x, sl), "SD_Тонкие", (80, 80, 90), 18)
    S.line(sp, (x0 + 20, bot + 40), (x1 - 20, bot + 40), "SD_Тонкие", (80, 80, 90), 18)
    DM.chain(sp, [x0, x1], bot - 150, bot, k)
    DM.chain(sp, [bot, lv, sl], W + 520, W + 360, k, vertical=True)
    Y.section_level(sp, (-280, lv), ("%+.3f" % (lv / 1000.0)).replace(".", ","), k)
    Y.section_level(sp, (90, bot), ("%+.3f" % (bot / 1000.0)).replace(".", ","), k)
    node_marks(sp, [(1, (-200, sl + 65), (-200, sl + 65)), (3, (W + 160, lv + 6), (W + 210, lv - 150)),
                    (5, (x0 + 20, (bot + sl) / 2 + 150), (-160, (bot + sl) / 2 + 230)), (9, (x1 + 12, bot), (W + 210, bot + 50))], k)
    return (-400, bot - 400, W + 700, sl + 200)


NODE_FN = {"curtain_niche": (node_curtain_niche, 10), "shadow_gap": (node_shadow_gap, 10), "bulkhead": (node_bulkhead, 20)}


def nodes_sheet(A, no, title, scale, arg):
    P = A.P
    psp = A.make_sheet(no, title, scale, "Узлы потолков. Позиции - см. экспликацию к узлам")
    x = 24.0
    y_top = 254.0
    placed = []
    row_h = 0.0
    for i, n in enumerate(P.nodes):
        fn, k = NODE_FN[n["type"]]
        k = n.get("scale", k)
        blk, off = A.model_block(no, i)
        p = dict(n.get("params", {}))
        p.setdefault("ceiling", P.ceiling)
        p.setdefault("slab", P.slab)
        win = fn(blk, k, p)
        w = (win[2] - win[0]) / k
        h = (win[3] - win[1]) / k
        if x + w > 300:
            x = 24.0
            y_top -= row_h + 14
            row_h = 0.0
        rr = A.vp(psp, off, win, (x, y_top - h), k)
        A.title_note(psp, rr[0], rr[3] + 2, "Узел %s. %s" % (n["num"], n.get("title", "")), "1:%d" % k, h=3.0, hn=2.2)
        placed.append(rr)
        x = rr[2] + 8
        row_h = max(row_h, h)
    col = Column(A, psp, x=306, width=106)
    rows = [[str(i + 1), t] for i, t in enumerate(NODE_ITEMS)]
    col.table([10, 96], ["Поз.", "Экспликация к узлам"], rows, h=1.6, aligns=["C", "L"], title="Экспликация")
    col.notes(A.note_lines("nodes", [
        "Узлы - типовые решения студии; размеры профилей уточнить по системе производителя.",
        "Места узлов - см. план потолков.",
    ]))


# ------------------------------------------------------------------ openings schedule
def draw_opening_elev(sp, o_type, spec, k=40):
    W = spec["w"]
    H = spec.get("h", 2100)
    if spec.get("kind") == "window":
        H0 = spec.get("sill", 900)
        H1 = H0 + H
        S.rect(sp, 0, H0, W, H1, "SD_Окна", (30, 30, 30), 35)
        S.rect(sp, 60, H0 + 60, W - 60, H1 - 60, "SD_Окна", (30, 30, 30), 18)
        S.fill(sp, [(110, H0 + 110), (W - 110, H0 + 110), (W - 110, H1 - 110), (110, H1 - 110)], (225, 236, 245), "SD_Окна")
        S.line(sp, (60, H0 + 60), (W - 60, (H0 + H1) / 2), "SD_Окна", (120, 120, 120), 13)
        S.line(sp, (60, H1 - 60), (W - 60, (H0 + H1) / 2), "SD_Окна", (120, 120, 120), 13)
        Y.dashed(sp, (60, H0 + 60), (W / 2, H1 - 60), 0.8 * k, 0.5 * k, (120, 120, 120), 9)
        Y.dashed(sp, (W - 60, H0 + 60), (W / 2, H1 - 60), 0.8 * k, 0.5 * k, (120, 120, 120), 9)
        S.fill(sp, [(-40, H0 - 40), (W + 40, H0 - 40), (W + 40, H0), (-40, H0)], (200, 200, 200), "SD_Окна")
        DM.chain(sp, [0, W], -350, 0, k)
        DM.chain(sp, [0, H0, H1], W + 330, W, k, vertical=True)
        return W
    leaf = spec.get("leaf", W - 100)
    kind = spec.get("style", "door")
    Y.dashed_poly(sp, [(0, 0), (W, 0), (W, H), (0, H)], 1.0 * k, 0.6 * k, (150, 150, 150), 13)
    fr = spec.get("frame") or 30
    bw = spec.get("block_w") or (leaf + 2 * fr)
    bw = min(bw, W)
    bx0, bx1 = (W - bw) / 2.0, (W + bw) / 2.0             # door block (frame) inside the opening
    fw = (W - leaf) / 2.0
    hb = min(H - 30, spec.get("block_h", H - 100))
    if W - bw > 40:                                        # opening wider than the block: infill shown and noted
        for xa, xb in ((0, bx0), (bx1, W)):
            S.hatch(sp, [(xa, 0), (xb, 0), (xb, H), (xa, H)], (150, 150, 150), "ANSI31", scale=0.35 * k / 10, layer="SD_Двери")
        S.hatch(sp, [(bx0, hb), (bx1, hb), (bx1, H), (bx0, H)], (150, 150, 150), "ANSI31", scale=0.35 * k / 10, layer="SD_Двери")
    S.fill(sp, [(bx0, 0), (bx1, 0), (bx1, hb), (bx0, hb)], (245, 245, 245) if kind != "steel" else (95, 95, 100), "SD_Двери")
    S.rect(sp, bx0, 0, bx1, hb, "SD_Двери", (30, 30, 30), 35)
    S.rect(sp, fw, 0, W - fw, hb - fr, "SD_Двери", (30, 30, 30) if kind != "steel" else (230, 230, 230), 18)
    if kind == "glass":
        S.fill(sp, [(fw + 90, 90), (W - fw - 90, 90), (W - fw - 90, hb - 120), (fw + 90, hb - 120)], (225, 236, 245), "SD_Двери")
    # opening scheme, seen from the side the leaf opens to: triangle base on the hinge side, apex at the handle
    mir = (lambda x: W - x) if spec.get("hand") == "R" else (lambda x: x)
    hx = W - fw - 60
    S.line(sp, (mir(fw), hb - fr), (mir(hx), (hb - fr) / 2), "SD_Двери", (130, 130, 130), 13)
    S.line(sp, (mir(fw), 0), (mir(hx), (hb - fr) / 2), "SD_Двери", (130, 130, 130), 13)
    S.line(sp, (mir(hx - 80), 1000), (mir(hx), 1000), "SD_Двери", (30, 30, 30) if kind != "steel" else (230, 230, 230), 35)
    if W - bw > 40:
        DM.chain(sp, [0, bx0, bx1, W], -350, 0, k)
        DM.chain(sp, [0, W], -650, 0, k)
        DM.chain(sp, [0, hb, H], W + 330, W, k, vertical=True)
    else:
        DM.chain(sp, [0, W], -350, 0, k)
        DM.chain(sp, [0, H], W + 330, W, k, vertical=True)
    return W


def openings_k(P):
    """1:40 when all schemes fit in one row of the sheet, else 1:50."""
    ws = []
    for o in P.openings:
        if o["kind"] != "passage" and o.get("mark"):
            key = (o["mark"], P.door_hand(o))
            if key not in [k_ for k_, _ in ws]:
                ws.append((key, o["w"]))
    for k in (40, 50, 60):
        if sum((w + 1000) / float(k) for _, w in ws) + 4 * max(0, len(ws) - 1) <= 388:
            return k
    return 75


def openings_schedule(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, "Схемы заполнения проёмов %s (двери - вид со стороны открывания). Спецификация" % scale)
    marks = []
    for o in P.openings:
        if o["kind"] == "passage":
            continue
        if o.get("mark") and o["mark"] not in marks:
            marks.append(o["mark"])
    k = openings_k(P)
    specs = []
    HAND = {"L": "лев.", "R": "прав."}
    for m in marks:
        os_all = [o for o in P.openings if o.get("mark") == m]
        hands = []
        for o in os_all:
            h = P.door_hand(o)
            if h not in hands:
                hands.append(h)
        for hand in hands:                       # one scheme per hand: a left and a right door are different products
            os_ = [o for o in os_all if P.door_hand(o) == hand]
            o = os_[0]
            t = P.opening_types.get(m, {})
            spec = dict(kind="window" if o["kind"] == "window" else "door", w=o["w"], h=o["h"], sill=o.get("sill", 900),
                        leaf=t.get("leaf", o.get("leaf", o["w"] - 100)), frame=t.get("frame", o.get("frame")),
                        block_w=t.get("block_w"), hand=hand,
                        style=t.get("style", "glass" if o["kind"] == "balcony" else ("steel" if o.get("steel") else "door")),
                        block_h=t.get("block_h", o["h"] - 100))
            label = m if hand is None else "%s %s" % (m, HAND[hand])
            spec["mark"] = m
            spec["rooms"] = sorted(set(o_.get("room", "") for o_ in os_ if o_.get("room")))
            specs.append((label, spec, len(os_)))
    def title_w(label, cnt):
        return S.tw(label, 4.2, True) + 3.0 + S.tw("%d шт." % cnt, 2.6) + 9.0
    slots = [max((sp_["w"] + 1000) / k, title_w(lb, cnt)) for lb, sp_, cnt in specs]   # a title never leaves its slot
    gap = max(2.0, (388 - sum(slots)) / max(1, len(specs) - 1))
    x = 24.0
    top_all = max([2650] + [sp_["h"] + (sp_["sill"] if sp_["kind"] == "window" else 0) + 350 for _, sp_, _ in specs])
    for i, (m, spec, cnt) in enumerate(specs):
        blk, off = A.model_block(no, i)
        W = draw_opening_elev(blk, m, spec, k)
        S.line(blk, (-250, 0), (W + 250, 0), "SD_Стены", (20, 20, 20), 50)
        r = A.vp(psp, off, (-300, -900, W + 700, top_all), (x, 140), k)     # one top -> titles on one line
        A.title_note(psp, r[0] + 7, r[3] + 3, m, "%d шт." % cnt, h=4.2, hn=2.6)
        x = x + slots[i] + gap
    rows = []
    for m, spec, cnt in specs:
        t = P.opening_types.get(spec["mark"], {})
        rows.append([m, t.get("oboz", ""), t.get("name", ""), str(cnt), ", ".join(spec["rooms"]), t.get("note", "")])
    S.table(psp, 24, 128, [16, 30, 92, 10, 52, 188], ["Марка", "Обозначение", "Наименование", "Кол.", "Помещение", "Примечание"],
            rows, h=1.75, aligns=["C", "L", "L", "C", "L", "L"], title="Спецификация элементов заполнения проёмов", head_h=6.0)
    S.notes(psp, 24, 58, A.note_lines("openings", [
        "Размеры проёмов - в чистоте; размеры блоков уточнить при заказе по факту.",
        "Схемы открывания: основание треугольника - сторона петель, вершина - сторона ручки; сплошные линии - "
        "поворотное открывание, штриховые - откидное. Двери - вид со стороны открывания (лев./прав. по ГОСТ 475), "
        "окна - изнутри помещения.",
        "Штриховка в проёме - заделка между блоком и проёмом (выполняет монтажник дверей).",
    ]), 150)
