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
        if it.get("type") == "poly":                 # a piece of furniture: its front view outline from the model
            pts = [tuple(p) for p in it["pts"]]
            S.fill(sp, pts, tuple(it.get("rgb", (226, 220, 210))), "SD_Мебель")
            S.poly(sp, pts, "SD_Мебель", True, (70, 66, 62), 25)
            g = Polygon(pts).buffer(0)
            if it.get("label") and not g.is_empty:
                c = g.representative_point()
                place_text(sp, occ, it["label"], [(c.x, c.y), (c.x, c.y + 150), (c.x, c.y - 150)], 2.2 * k, bold=True,
                           rgb=(90, 70, 40), mask=True)
            continue
        if it.get("type") == "sign":                 # a sign of the model at its place, in its words
            t = it["text"]
            hh = 160.0
            w = S.tw(t, hh) + 120
            x0_, z0_ = it["s"] - w / 2, it["z"] - hh / 2 - 60
            if it.get("light"):
                S.fill(sp, [(x0_, z0_), (x0_ + w, z0_), (x0_ + w, z0_ + hh + 120), (x0_, z0_ + hh + 120)], (255, 246, 214), "SD_Мебель")
            S.text(sp, t, (it["s"], it["z"]), hh, "MIDDLE_CENTER", "SD_Мебель", bold=True,
                   rgb=(200, 120, 20) if it.get("light") else (60, 60, 60))
            Y.dashed_shape(sp, box(x0_, z0_, x0_ + w, z0_ + hh + 120), 0.9 * k, 0.5 * k, (150, 120, 60), 13)
            occ.add(box(x0_, z0_, x0_ + w, z0_ + hh + 120), "sym")
            lab = ("%s " % it["mark"] if it.get("mark") else "") + ("вывеска, LED-неон" if it.get("light") else "вывеска")
            place_text(sp, occ, lab, [(it["s"], z0_ - 2.4 * k), (it["s"], z0_ + hh + 120 + 2.4 * k)], 1.7 * k,
                       rgb=(120, 90, 40), mask=True)
            continue
        if it.get("type") == "wall_light":
            c = (it["s"], it["z"])
            S.fill(sp, Point(c).buffer(1.6 * k, 24), (64, 186, 166), "SD_Свет")
            S.circle(sp, c, 1.6 * k, "SD_Свет", (30, 110, 100), 18)
            occ.add(Point(c).buffer(1.8 * k), "sym")
            place_text(sp, occ, "бра", [(c[0], c[1] + 3.0 * k), (c[0] + 4.0 * k, c[1], 0, "MIDDLE_LEFT")], 1.6 * k,
                       rgb=(30, 110, 100), mask=True)
            continue
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
    for zn in e.get("zones", []):
        if not zn.get("front"):
            continue
        pts = [(zn["s0"], zn["z0"]), (zn["s1"], zn["z0"]), (zn["s1"], zn["z1"]), (zn["s0"], zn["z1"])]
        S.fill(sp, pts, WALL_TILE, "SD_Мебель")
        tt = zn.get("tile", tile)
        S.grid_lines(sp, Polygon(pts), tt[0], tt[1], origin=tuple(zn.get("origin", (0, 0))), rgb=WALL_TILE_J)
        S.poly(sp, pts, "SD_Мебель", True, (70, 66, 62), 25)
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
        place_text(sp, occ, ("%s %+.3f" % ("балка" if z.get("kind") == "beam" else "короб", z["bottom"] / 1000.0)).replace(".", ","),
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
    for v in e.get("extra_s", []):
        if 0 <= v <= L:
            ss.add(round(v))
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


def group_room(P, g):
    """Elevations of several adjacent wet rooms (a WC lobby and its cubicles) drawn as one group: a pseudo-room with
    their union for the plan, the materials table and the waterproofing."""
    names = []
    for e in g["elevs"]:
        if e.get("room") in P.room_by_name and e["room"] not in names:
            names.append(e["room"])
    if not names:
        return None
    rs = [P.room_by_name[n] for n in names]
    shp = unary_union([r["shp"] for r in rs])
    return dict(name=g["name"], shp=shp, cls=rs[0].get("cls"), members=names, area=round(sum(r["area"] for r in rs), 2),
                area_exact=sum(r["area_exact"] for r in rs), perimeter=sum(r["perimeter"] for r in rs))


def elev_window(E, e, k):
    left = sc25(k, 520) if e.get("heights") else sc25(k, 250)
    bottom = sc25(k, 1300) if e.get("module_chain") else sc25(k, 950)
    return (-left, -bottom, E.L + sc25(k, 720), E.H + sc25(k, 350))


def elevation_sheets(A):
    P = A.P
    out = []
    for g in groups(P):
        room = P.room_by_name.get(g["name"]) or group_room(P, g)
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
        n_pages = len(pages)
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
        if with_plan and g.get("iso", True):           # wet rooms: axonometric views with the tile layout
            out.append(("%s. Аксонометрия" % g["name"], "б/м", iso_sheet, dict(group=g, room=room)))
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
    if not arg["plan"] and any(e.get("feature") for e in arg["elevs"]):
        _key_plan(A, psp, no, arg["elevs"])
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


def _key_plan(A, psp, no, elevs, w_mm=100.0, h_mm=78.0, x_mm=308.0, y_mm=40.0):
    """Small plan of the whole floor with the walls of these elevations marked by their letters (where the wall is)."""
    P = A.P
    name = "SD_%02d_key" % no                     # a band of its own in model space: never inside another viewport
    blk = A.doc.blocks.new(name)
    off = (no * 60000.0, -100000.0)
    A.msp.add_blockref(name, off)
    A._blocks[off] = (blk, A.cur_title)
    from . import placer
    placer.CUR_BLOCK = off
    x0, y0, x1, y1 = P.bounds
    kk = max((x1 - x0 + 1600) / w_mm, (y1 - y0 + 1600) / h_mm)
    for r in P.rooms:
        S.fill(blk, r["shp"], (248, 246, 242), "SD_Штриховка")
    Y.draw_walls(blk, P, kk)
    for e in elevs:
        a, b = e["a"], e["b"]
        S.line(blk, tuple(a), tuple(b), "SD_Акцент", BRONZE, 70)
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        nx, ny = (b[1] - a[1]) / L, -(b[0] - a[0]) / L          # the room is to the right of a->b
        m = ((a[0] + b[0]) / 2 + nx * 4.0 * kk, (a[1] + b[1]) / 2 + ny * 4.0 * kk)
        S.fill(blk, Point(m).buffer(2.4 * kk, 24), (255, 255, 255), "SD_Текст")
        S.circle(blk, m, 2.4 * kk, "SD_Текст", BRONZE, 25)
        S.text(blk, e.get("label", ""), m, 2.4 * kk, "MIDDLE_CENTER", bold=True, rgb=(90, 70, 40))
    win = (x0 - 800, y0 - 800, x1 + 800, y1 + 800)
    r = A.vp(psp, off, win, (x_mm + (w_mm - (win[2] - win[0]) / kk) / 2, y_mm), kk)
    A.title_note(psp, r[0], r[3] + 1.5, "Схема развёрток", "без масштаба", h=3.0)


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
    members = room.get("members") or [room["name"]]
    for f in P.furniture:
        if f.get("room") not in members or f.get("kind") not in ("shower", "bath"):
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
    F = P.finishes or {}
    if tile_area > 0:
        rows.append([F.get("tile_label") or "Керамогранит / плитка стен", fmt_area(tile_area), fmt_area(tile_area * 1.1)])
    if room is not None and not any(e.get("feature") for e in g["elevs"]):      # a wall of the hall: not its floor
        fl = P.floor_of_room((room.get("members") or [room["name"]])[0])
        if fl and fl.get("pattern") == "tile":
            rows.append(["Плитка пола %s" % "×".join(map(str, fl.get("tile", [600, 600]))), fmt_area(room["area"]),
                         fmt_area(room["area"] * 1.1)])
    if paint_area > 0:
        wet_ = room is not None and room.get("cls") == "wet"
        rows.append([("%s%s" % (F["base_label"], " (влагостойкая, защитный лак)" if wet_ else "")) if F.get("base_label")
                     else ("Окраска (влагостойкая)" if wet_ else "Окраска"), fmt_area(paint_area), "-"])
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
    bx0, by0, bx1, by1 = shp.bounds
    occ.bounds = box(bx0 - 950, by0 - 950, bx1 + 950, by1 + 950).buffer(-0.6 * k)     # = the viewport window below
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
    members = room.get("members") or [room["name"]]
    Y.furniture_all(blk, P, k, rooms=members)
    for f in P.furniture:
        if f.get("room") in members and f.get("kind") != "rug":
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
    # wall markers (one viewpoint circle per room of the group)
    elevs = [e for e in P.elevations if (e.get("group") or e.get("room")) == room["name"]]
    from shapely.ops import polylabel
    r = 2.2 * k if len(members) == 1 else 1.6 * k
    centres = {}
    for mn in members:
        mshp = P.room_by_name[mn]["shp"] if mn in P.room_by_name else shp
        free = mshp.buffer(-150)
        for f in P.furniture:
            if f.get("room") == mn:
                free = free.difference(Polygon(f["poly"]).buffer(80))
        if free.is_empty:
            free = mshp.buffer(-150)
        if free.is_empty:
            free = mshp
        fp = free if free.geom_type == "Polygon" else max(free.geoms, key=lambda g: g.area)
        c = polylabel(fp, 5)
        centres[mn] = (c.x, c.y)
        if not any((e.get("room") or room["name"]) == mn for e in elevs) and len(members) > 1:
            continue
        S.fill(blk, Point(c.x, c.y).buffer(r, 32), (255, 255, 255), "SD_Текст")
        S.circle(blk, (c.x, c.y), r, "SD_Тонкие", (30, 30, 30), 25)
        occ.add(Point(c.x, c.y).buffer(r + 3 * k), "sym")
    for e in elevs:
        cx, cy = centres.get(e.get("room"), next(iter(centres.values())))
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
        if f.get("room") not in members or f.get("kind") in ("rug", "rail", "mirror"):
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
    F = P.finishes or {}
    items = [(_lg_fill(WALL_TILE), F.get("tile_label") or "Плитка / керамогранит стен"), (_lg_floor_tile, "Плитка пола"),
             (_lg_fill(WALL_PAINT), F.get("base_label") or "Окраска влагостойкой краской"),
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
def _sash_symbol(sp, x0, z0, x1, z1, kind, hinge="L", k=40):
    """ГОСТ 23166 opening scheme seen from inside: the apex points to the handle; solid - turn, dashed - tilt."""
    g = (110, 110, 110)
    if kind in ("turn", "tilt-turn"):
        hx, ax = (x0, x1) if hinge == "L" else (x1, x0)
        S.line(sp, (hx, z0), (ax, (z0 + z1) / 2.0), "SD_Окна", g, 13)
        S.line(sp, (hx, z1), (ax, (z0 + z1) / 2.0), "SD_Окна", g, 13)
    if kind in ("tilt", "tilt-turn"):
        Y.dashed(sp, (x0, z0), ((x0 + x1) / 2.0, z1), 0.8 * k, 0.5 * k, g, 9)
        Y.dashed(sp, (x1, z0), ((x0 + x1) / 2.0, z1), 0.8 * k, 0.5 * k, g, 9)


def draw_window_divided(sp, spec, k=40, dims=True):
    """A window / shop front with its modules, transom, sashes and opening schemes (view from inside)."""
    W = spec["w"]
    H = spec.get("h", 1500)
    H0 = spec.get("sill", 900)
    H1 = H0 + H
    fw = spec.get("frame_w", 60)
    mods = spec.get("division") or [W]
    tr = spec.get("transom")
    tr = tr if tr and H0 + 200 < tr < H1 - 200 else None
    xs = [0]
    for m in mods:
        xs.append(xs[-1] + m)
    xs[-1] = W
    S.fill(sp, [(0, H0), (W, H0), (W, H1), (0, H1)], (70, 70, 74) if spec.get("system") == "storefront" else (236, 236, 236),
           "SD_Окна")
    sash = spec.get("sash") or ["fixed"] * len(mods)
    for i, (a, b) in enumerate(zip(xs[:-1], xs[1:])):
        tiers = [(H0, tr), (tr, H1)] if tr else [(H0, H1)]
        for j, (z0, z1) in enumerate(tiers):
            gx0, gz0, gx1, gz1 = a + fw / (1 if i == 0 else 2), z0 + fw / (1 if j == 0 else 2), \
                b - fw / (1 if i == len(mods) - 1 else 2), z1 - fw / (1 if j == len(tiers) - 1 else 2)
            S.fill(sp, [(gx0, gz0), (gx1, gz0), (gx1, gz1), (gx0, gz1)], (225, 236, 245), "SD_Окна")
            S.rect(sp, gx0, gz0, gx1, gz1, "SD_Окна", (60, 60, 64), 13)
            kind = sash[i] if (j == 0 or not tr) else "fixed"
            if kind != "fixed":
                inset = 25
                S.rect(sp, gx0 - inset, gz0 - inset, gx1 + inset, gz1 + inset, "SD_Окна", (40, 40, 44), 18)
                hinge = "L" if i < len(mods) / 2.0 else "R"
                _sash_symbol(sp, gx0, gz0, gx1, gz1, kind, hinge, k)
    S.rect(sp, 0, H0, W, H1, "SD_Окна", (20, 20, 20), 35)
    if H0 > 0:
        S.fill(sp, [(-40, H0 - 40), (W + 40, H0 - 40), (W + 40, H0), (-40, H0)], (200, 200, 200), "SD_Окна")
    if dims:
        if len(mods) > 1:
            DM.chain(sp, xs, -350, 0, k)
            DM.chain(sp, [0, W], -650, 0, k)
        else:
            DM.chain(sp, [0, W], -350, 0, k)
        DM.chain(sp, sorted(set([0, H0, H1] + ([tr] if tr else []))), W + 330, W, k, vertical=True)
    return W


def draw_opening_elev(sp, o_type, spec, k=40):
    W = spec["w"]
    H = spec.get("h", 2100)
    if spec.get("kind") == "window" and spec.get("division"):
        return draw_window_divided(sp, spec, k)
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


def _opening_specs(P):
    marks = []
    for o in P.openings:
        if o["kind"] == "passage":
            continue
        if o.get("mark") and o["mark"] not in marks:
            marks.append(o["mark"])
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
            for key_ in ("division", "transom", "sash", "frame_w", "system"):
                if t.get(key_) is not None:
                    spec[key_] = t[key_]
            label = m if hand is None else "%s %s" % (m, HAND[hand])
            spec["mark"] = m
            from . import topo as T_
            rooms = set(o_.get("room", "") for o_ in os_ if o_.get("room"))
            for o_ in os_:
                rooms.update(r["name"] for r, n, fp in T_.opening_sides(P, o_) if r is not None)
            spec["rooms"] = sorted(rooms)
            specs.append((label, spec, len(os_)))
    return specs


def _title_w(label, cnt):
    return S.tw(label, 4.2, True) + 3.0 + S.tw("%d шт." % cnt, 2.6) + 9.0


def openings_layout(P):
    """(rows, k): one row of schemes at the largest scale that fits, else two rows (a cafe: two shop fronts and
    five door types do not fit in 388 mm)."""
    specs = _opening_specs(P)
    top_all = max([2650] + [sp_["h"] + (sp_["sill"] if sp_["kind"] == "window" else 0) + 350 for _, sp_, _ in specs])
    for rn, kk in ((1, 40), (1, 50), (1, 60), (1, 75), (2, 50), (2, 60), (2, 75), (2, 100), (2, 125)):
        per = [max((sp_["w"] + 1200) / kk, _title_w(lb, cnt)) for lb, sp_, cnt in specs]
        if rn == 1:
            ok = sum(per) + 4 * (len(per) - 1) <= 388
        else:
            half = int(math.ceil(len(per) / 2.0))
            ok = max(sum(per[:half]), sum(per[half:])) + 4 * (half - 1) <= 388 and 2 * (top_all + 1250) / kk <= 108
        if ok:
            return rn, kk
    return 2, 150


def openings_k(P):
    return openings_layout(P)[1]


def openings_schedule(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, "Схемы заполнения проёмов (двери - вид со стороны открывания). Спецификация")
    specs = _opening_specs(P)
    rows_n, k = openings_layout(P)
    top_all = max([2650] + [sp_["h"] + (sp_["sill"] if sp_["kind"] == "window" else 0) + 350 for _, sp_, _ in specs])
    slots = [max((sp_["w"] + 1200) / k, _title_w(lb, cnt)) for lb, sp_, cnt in specs]   # a title never leaves its slot
    half = len(specs) if rows_n == 1 else int(math.ceil(len(specs) / 2.0))
    lines_ = [list(range(0, half)), list(range(half, len(specs)))] if rows_n == 2 else [list(range(len(specs)))]
    row_h = (top_all + 1250) / k
    for li, idx in enumerate(lines_):
        if not idx:
            continue
        gap = max(2.0, (388 - sum(slots[i] for i in idx)) / max(1, len(idx) - 1))
        x = 24.0
        y0 = 140.0 if rows_n == 1 else 140.0 + (1 - li) * (row_h + 6)
        for i in idx:
            m, spec, cnt = specs[i]
            blk, off = A.model_block(no, i)
            W = draw_opening_elev(blk, m, spec, k)
            S.line(blk, (-250, 0), (W + 250, 0), "SD_Стены", (20, 20, 20), 50)
            r = A.vp(psp, off, (-500, -900, W + 700, top_all), (x, y0), k)     # narrow frame dims sit outside
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


# ------------------------------------------------------------------ windows and shop fronts (types, glazing, node)
SASH_RU = {"fixed": "глухая", "tilt": "откидная", "turn": "поворотная", "tilt-turn": "поворотно-откидная"}


def window_types(P):
    """Window types with a construction described (division / glazing) -> [(mark, type, openings)]."""
    out = []
    for m, t in P.opening_types.items():
        if not t.get("division"):
            continue
        os_ = [o for o in P.openings if o.get("mark") == m and o["kind"] == "window"]
        if os_:
            out.append((m, t, os_))
    return out


def windows_k(P):
    """Scale of the window elevations: all in one row left of the node (270 mm) and under the title (100 mm high)."""
    wt = window_types(P)
    top = max([2650] + [os_[0]["h"] + os_[0].get("sill", 0) + 350 for m, t, os_ in wt])
    for k in (25, 40, 50, 60, 75, 100):
        if sum((os_[0]["w"] + 1100) / float(k) for m, t, os_ in wt) + 8 * max(0, len(wt) - 1) <= 270 and (top + 900) / k <= 98:
            return k
    return 125


def node_window_jamb(sp, k, storefront=False):
    """Horizontal section through the jamb of a window block in a wall opening (ГОСТ 30971): wall, frame, the three
    layers of the installation joint, glazing unit, anchor, inner reveal. Model units = mm. -> [(label point, text)]"""
    t_wall, x_in = 300.0, 300.0
    hatch_concrete(sp, [(0, -330), (t_wall, -330), (t_wall, 0), (0, 0)], k)          # wall pier, jamb face at y = 0
    S.fill(sp, [(-20, -330), (0, -330), (0, 40), (-20, 40)], (215, 205, 190), "SD_Штриховка")   # facade render
    S.poly(sp, [(-20, -330), (-20, 40)], "SD_Тонкие", False, (90, 90, 90), 18)
    fx0, fx1 = (95.0, 185.0) if storefront else (110.0, 180.0)          # frame depth 90 (alu) / 70 (PVC)
    fy0, fy1 = 20.0, 20.0 + (60.0 if storefront else 70.0)
    S.fill(sp, [(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1)], (70, 70, 74) if storefront else (245, 245, 245), "SD_Окна")
    S.rect(sp, fx0, fy0, fx1, fy1, "SD_Окна", (20, 20, 20), 35)
    for i in range(1, 4 if not storefront else 2):                      # PVC chambers
        xx = fx0 + (fx1 - fx0) * i / (4 if not storefront else 2)
        S.line(sp, (xx, fy0 + 6), (xx, fy1 - 6), "SD_Окна", (120, 120, 120) if not storefront else (200, 200, 200), 9)
    # installation joint: foam (centre), vapour barrier (inside), diffusion / PSUL tape (outside)
    S.fill(sp, [(fx0, 0), (fx1, 0), (fx1, fy0), (fx0, fy0)], (250, 228, 160), "SD_Штриховка")
    S.hatch(sp, [(fx0, 0), (fx1, 0), (fx1, fy0), (fx0, fy0)], (200, 160, 60), "ANSI37", scale=0.05 * k)
    S.line(sp, (fx1 + 2, -60), (fx1 + 2, fy0 + 25), "SD_Окна", (25, 95, 210), 70)          # inner vapour barrier tape
    Y.dashed(sp, (fx0 - 2, -40), (fx0 - 2, fy0 + 15), 0.5 * k, 0.3 * k, (214, 120, 40), 70)   # outer PSUL / diffusion
    # anchor plate into the wall
    S.line(sp, ((fx0 + fx1) / 2, fy0), ((fx0 + fx1) / 2, -110), "SD_Окна", (60, 60, 60), 35)
    S.line(sp, ((fx0 + fx1) / 2 - 15, -110), ((fx0 + fx1) / 2 + 15, -110), "SD_Окна", (60, 60, 60), 35)
    # glazing unit
    gx = (fx0 + fx1) / 2.0
    gt = 40.0 if storefront else 32.0
    for xx in (gx - gt / 2, gx + gt / 2):
        S.line(sp, (xx, fy0 + 15), (xx, 330), "SD_Окна", (60, 110, 160), 25)
    S.fill(sp, [(gx - gt / 2 + 6, fy0 + 15), (gx + gt / 2 - 6, fy0 + 15), (gx + gt / 2 - 6, fy0 + 30), (gx - gt / 2 + 6, fy0 + 30)],
           (120, 120, 125), "SD_Окна")
    # inner reveal (plaster / slope panel) and sill direction
    S.fill(sp, [(fx1 + 4, 0), (x_in, 0), (x_in, 12), (fx1 + 4, 12)], (250, 250, 250), "SD_Штриховка")
    S.rect(sp, fx1 + 4, 0, x_in, 12, "SD_Тонкие", (60, 60, 60), 18)
    S.text(sp, "снаружи", (-20, 320), 2.0 * k, "MIDDLE_LEFT", rgb=(120, 120, 120))
    S.text(sp, "внутри", (x_in, 320), 2.0 * k, "MIDDLE_RIGHT", rgb=(120, 120, 120))
    return [((gx, 250.0), "1"), ((fx0 + 20, fy0 + 30), "2"), (((fx0 + fx1) / 2, 10.0), "3"), ((fx1 + 2, -40.0), "4"),
            ((fx0 - 2, -30.0), "5"), (((fx0 + fx1) / 2, -100.0), "6"), (((fx1 + x_in) / 2, 6.0), "7")]


def windows_sheet(A, no, title, scale):
    P = A.P
    k = windows_k(P)
    psp = A.make_sheet(no, title, scale, "Конструкции окон и витражей (вид изнутри), заполнение, открывание. Узел примыкания")
    wt = window_types(P)
    x = 24.0
    top = max([2650] + [os_[0]["h"] + os_[0].get("sill", 0) + 350 for m, t, os_ in wt])
    for i, (m, t, os_) in enumerate(wt):
        o = os_[0]
        spec = dict(kind="window", w=o["w"], h=o["h"], sill=o.get("sill", 0), division=t.get("division"),
                    transom=t.get("transom"), sash=t.get("sash"), frame_w=t.get("frame_w", 60), system=t.get("system"))
        blk, off = A.model_block(no, i)
        W = draw_window_divided(blk, spec, k)
        S.line(blk, (-250, 0), (W + 250, 0), "SD_Стены", (20, 20, 20), 50)
        r = A.vp(psp, off, (-300, -900, W + 800, top), (x, 150.0), k)
        A.title_note(psp, r[0] + 7, r[3] + 3, m, "%d шт., 1:%d" % (len(os_), k), h=4.2, hn=2.6)
        x = r[2] + 8
    # node 1:10 on the right, legend under it
    kn = 10
    blk, off = A.model_block(no, 50)
    sf = any(t.get("system") == "storefront" for m, t, os_ in wt)
    marks = node_window_jamb(blk, kn, storefront=sf)
    lab_at = {"1": (420, 250), "2": (-10, 150), "3": (40, 80), "4": (300, -60), "5": (-10, -60), "6": (60, -200),
              "7": (380, 80)}
    for p, lab in marks:
        q = lab_at.get(lab, (p[0] + 100, p[1] + 60))
        S.line(blk, p, q, "SD_Тонкие", (90, 90, 90), 9)
        Y.mark_circle(blk, lab, q, kn, r=1.5, h=1.7)
    r = A.vp(psp, off, (-60, -260, 470, 345), (306.0, 150.0), kn)
    A.title_note(psp, r[0], r[3] + 3, "Узел 1", "разрез по откосу, 1:10", h=3.4, hn=2.2)
    legend = ["1 - стеклопакет (см. таблицу)", "2 - профиль рамы %s" % ("алюминиевый с терморазрывом" if sf else "ПВХ 70 мм"),
              "3 - монтажная пена (центральный теплоизоляционный слой)", "4 - пароизоляционная лента (внутренний слой)",
              "5 - ПСУЛ / диффузионная лента (наружный слой)", "6 - анкерная пластина / дюбель, шаг ≤ 700 мм",
              "7 - откос: штукатурка / панель, примыкание на герметике"]
    yy = r[1] - 4
    for ln in legend:
        S.text(psp, ln, (306.0, yy), 1.9, "MIDDLE_LEFT", rgb=(60, 60, 60))
        yy -= 3.3
    rows = []
    for m, t, os_ in wt:
        o = os_[0]
        area = sum(x_["w"] * x_["h"] for x_ in os_) / 1e6
        sash = ", ".join("%s×%d" % (SASH_RU.get(sv, sv), (t.get("sash") or []).count(sv)) if (t.get("sash") or []).count(sv) > 1
                         else SASH_RU.get(sv, sv) for sv in dict.fromkeys(t.get("sash") or []))
        rows.append([m, "%d×%d" % (o["w"], o["h"]), str(len(os_)), fmt_area(area), t.get("profile", ""), t.get("glazing", ""),
                     sash + (", ригель +%s" % ("%.3f" % (t["transom"] / 1000.0)).replace(".", ",") if t.get("transom") else ""),
                     t.get("sill_note", "")])
    yb = S.table(psp, 24, 104, [14, 22, 9, 16, 62, 62, 40, 50],
                 ["Марка", "Размер, мм", "Кол.", "Площадь, м²", "Профиль", "Заполнение", "Открывание", "Низ / подоконник"],
                 rows, h=1.6, aligns=["C", "C", "C", "C", "L", "L", "L", "L"], title="Спецификация окон и витражей", head_h=6.0)
    S.notes(psp, 24, min(yb - 8, 60), A.note_lines("windows", [
        "Монтаж - по ГОСТ 30971-2012: шов из трёх слоёв (наружный паропроницаемый, центральный теплоизоляционный, "
        "внутренний пароизоляционный); зазор 15-25 мм по периметру; крепёж - анкерные пластины / дюбели с шагом ≤ 700 мм.",
        "Нижний ярус витражей и остекление дверей - безопасное стекло (закалённое / многослойное триплекс).",
        "Открывание показано изнутри помещения: вершина треугольника - сторона ручки; сплошные линии - поворотное, "
        "штриховые - откидное.",
        "Размеры - по проёмам в чистоте; изготовление - после контрольного замера. Цвет профиля и фурнитура - по дизайну.",
    ]), 250)


def iso_sheet(A, no, title, scale, arg):
    """Two axonometric views of a wet room / WC block (from the two opposite corners): tile layout on the walls,
    fixtures, openings - what the tiler and the client look at first."""
    import os
    from . import iso3d
    P = A.P
    room = arg["room"]
    names = room.get("members") or [room["name"]]
    psp = A.make_sheet(no, title, scale, "Аксонометрические виды: раскладка плитки, сантехника, проёмы (стены перед зрителем срезаны)")
    views = list(zip(iso3d.views_for(P, names), ("Вид 1", "Вид 2")))
    x = 24.0
    for i, (az, lab) in enumerate(views):
        png = os.path.join(A.out_dir, "iso_%d_%d.png" % (no, i))
        try:
            ok = iso3d.render_rooms(P, names, png, azim=az)
        except Exception as ex:
            A.issues.append(dict(code="ISO_FAILED", level="warning", sheet=A.cur_title, msg=str(ex)))
            ok = None
        if not ok:
            continue
        from PIL import Image
        iw, ih = Image.open(png).size
        ww, hh = 185.0, 185.0 * ih / iw
        if hh > 175.0:
            hh, ww = 175.0, 175.0 * iw / ih
        img = A.image("iso_%d_%d.png" % (no, i), png)
        y0 = 68.0 + (175.0 - hh) / 2.0
        psp.add_image(img, insert=(x + (185.0 - ww) / 2.0, y0), size_in_units=(ww, hh),
                      dxfattribs={"layer": "SD_Рамка"}).rgb = (254, 254, 254)
        A.title_note(psp, x, 250.0, lab, "без масштаба", h=3.6, hn=2.4)
        x += 200.0
    S.notes(psp, 24, 58, A.note_lines("iso", [
        "Раскладка плитки - по развёрткам; швы стен совпадают со швами пола; подрезка - в углах у входа.",
        "Виды условные: сантехника и мебель показаны габаритами; стены перед зрителем срезаны на +0,300.",
    ]), 170)
