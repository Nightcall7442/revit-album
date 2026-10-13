# -*- coding: utf-8 -*-
"""Drawing primitives of the album in model space (mm). k = drawing scale (paper mm -> model mm)."""
import math
from shapely.geometry import Polygon, box, LineString, Point
from shapely.ops import unary_union

from . import gfx as S

WHITE = (255, 255, 255)
PARQUET = (236, 222, 196)
PARQUET_J = (205, 182, 145)
TILE = (232, 233, 235)
TILE_J = (190, 192, 196)
BRONZE = (168, 132, 82)


# ------------------------------------------------------------------ basics
def outline(sp, shp, rgb=None, lw=35, layer="SD_Стены"):
    polys = list(shp.geoms) if hasattr(shp, "geoms") else [shp]
    for p in polys:
        if p.is_empty or p.geom_type != "Polygon":
            continue
        S.poly(sp, list(p.exterior.coords)[:-1], layer, True, rgb, lw)
        for ring in p.interiors:
            S.poly(sp, list(ring.coords)[:-1], layer, True, rgb, lw)


def dashed(sp, a, b, dash, gap, rgb=None, lw=None, layer="SD_Тонкие"):
    (ax, ay), (bx, by) = a, b
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-6:
        return
    ux, uy = (bx - ax) / L, (by - ay) / L
    t = 0.0
    while t < L:
        t2 = min(L, t + dash)
        S.line(sp, (ax + ux * t, ay + uy * t), (ax + ux * t2, ay + uy * t2), layer, rgb, lw)
        t = t2 + gap


def dashed_poly(sp, pts, dash, gap, rgb=None, lw=None, closed=True, layer="SD_Тонкие"):
    n = len(pts)
    for i in range(n if closed else n - 1):
        dashed(sp, pts[i], pts[(i + 1) % n], dash, gap, rgb, lw, layer)


def dashed_shape(sp, shp, dash, gap, rgb=None, lw=None, layer="SD_Тонкие"):
    for p in (shp.geoms if hasattr(shp, "geoms") else [shp]):
        if p.geom_type == "Polygon" and not p.is_empty:
            dashed_poly(sp, list(p.exterior.coords)[:-1], dash, gap, rgb, lw, True, layer)


def mark_circle(sp, s, p, k, r=2.0, h=2.0, fill_rgb=WHITE, rgb=(40, 40, 40), txt_rgb=None, layer="SD_Текст"):
    S.fill(sp, Point(p).buffer(r * k, 32), fill_rgb, layer)
    S.circle(sp, p, r * k, "SD_Тонкие", rgb, 18)
    S.text(sp, s, p, h * k, "MIDDLE_CENTER", layer, bold=True, rgb=txt_rgb)
    return Point(p).buffer(r * k + 0.3 * k)


def tag_box(sp, s, p, k, h=1.8, rgb=WHITE, txt_rgb=None, border=(80, 80, 80), bold=False, rot=0.0):
    w = S.tw(s, h * k, bold) + 1.6 * k
    hh = h * k + 1.4 * k
    g = box(p[0] - w / 2, p[1] - hh / 2, p[0] + w / 2, p[1] + hh / 2)
    if rot:
        from shapely import affinity
        g = affinity.rotate(g, rot, origin=p)
    S.fill(sp, g, rgb, "SD_Текст")
    outline(sp, g, border, 13, "SD_Тонкие")
    S.text(sp, s, p, h * k, "MIDDLE_CENTER", rot=rot, bold=bold, rgb=txt_rgb)
    return g


def level_mark(sp, p, s, k, rgb=(40, 40, 40)):
    x, y = p
    S.poly(sp, [(x - 1.2 * k, y + 1.6 * k), (x + 1.2 * k, y + 1.6 * k), (x, y)], "SD_Тонкие", True, rgb, 18)
    S.fill(sp, [(x, y + 1.6 * k), (x + 1.2 * k, y + 1.6 * k), (x, y)], rgb, "SD_Тонкие")
    L = S.tw(s, 1.9 * k) + 1.4 * k
    S.line(sp, (x, y + 1.6 * k), (x + L, y + 1.6 * k), "SD_Тонкие", rgb, 13)
    S.text(sp, s, (x + 1.2 * k, y + 2.1 * k), 1.9 * k, "BOTTOM_LEFT", rgb=rgb)
    return box(x - 1.3 * k, y - 0.2 * k, x + L + 0.2 * k, y + 2.1 * k + 2.6 * k)


def ceiling_mark(sp, p, s, k, rgb=(40, 40, 40)):
    x, y = p
    S.poly(sp, [(x - 1.2 * k, y - 1.6 * k), (x + 1.2 * k, y - 1.6 * k), (x, y)], "SD_Тонкие", True, rgb, 18)
    S.fill(sp, [(x - 1.2 * k, y - 1.6 * k), (x, y - 1.6 * k), (x, y)], rgb, "SD_Тонкие")
    L = S.tw(s, 1.9 * k) + 1.4 * k
    S.line(sp, (x, y), (x + L, y), "SD_Тонкие", rgb, 13)
    S.text(sp, s, (x + 1.2 * k, y + 0.5 * k), 1.9 * k, "BOTTOM_LEFT", rgb=rgb)
    return box(x - 1.3 * k, y - 1.7 * k, x + L + 0.2 * k, y + 0.5 * k + 2.6 * k)


def section_level(sp, p, s, k, side=1, rgb=(40, 40, 40)):
    """Level of an underside (ceiling, box bottom) on a section / node, GOST 21.101: the 90° arrow touches the line
    from below, stem down, shelf to `side`, value above the shelf - the value never sits inside the construction."""
    x, y = p
    a = 1.0 * k
    S.poly(sp, [(x, y), (x - a, y - a), (x + a, y - a)], "SD_Тонкие", True, rgb, 18)
    S.fill(sp, [(x, y), (x, y - a), (x + side * a, y - a)], rgb, "SD_Тонкие")
    h = 1.9 * k
    L = S.tw(s, h) + 2.0 * k
    ys = y - a - h * 1.45
    S.line(sp, (x, y - a), (x, ys), "SD_Тонкие", rgb, 13)
    S.line(sp, (x, ys), (x + side * L, ys), "SD_Тонкие", rgb, 13)
    S.text(sp, s, (x + side * 0.6 * k, ys + 0.35 * k), h, "BOTTOM_LEFT" if side > 0 else "BOTTOM_RIGHT", rgb=rgb)
    x0, x1 = sorted((x - a, x + side * L))
    return box(x0, ys - 0.2 * k, x1, y)


def arrow(sp, a, b, k, rgb=BRONZE, lw=35, both=True):
    S.line(sp, a, b, "SD_Тонкие", rgb, lw)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    ends = [(b, ang)] + ([(a, ang + math.pi)] if both else [])
    for p, an in ends:
        S.fill(sp, [p, (p[0] - 2.2 * k * math.cos(an + 0.32), p[1] - 2.2 * k * math.sin(an + 0.32)),
                    (p[0] - 2.2 * k * math.cos(an - 0.32), p[1] - 2.2 * k * math.sin(an - 0.32))], rgb, "SD_Тонкие")
    return LineString([a, b]).buffer(1.2 * k)


def start_mark(sp, p, k, rgb=BRONZE):
    x, y = p
    S.fill(sp, Point(x, y).buffer(1.3 * k, 24), WHITE, "SD_Текст")
    S.circle(sp, (x, y), 1.3 * k, "SD_Тонкие", rgb, 25)
    S.fill(sp, [(x, y), (x + 1.3 * k, y), (x + 0.92 * k, y + 0.92 * k), (x, y + 1.3 * k)], rgb, "SD_Текст")
    S.fill(sp, [(x, y), (x - 1.3 * k, y), (x - 0.92 * k, y - 0.92 * k), (x, y - 1.3 * k)], rgb, "SD_Текст")
    return Point(x, y).buffer(1.5 * k)


def callout(sp, p, num, sheet, k, r=2.6):
    x, y = p
    S.fill(sp, Point(x, y).buffer(r * k, 32), WHITE, "SD_Текст")
    S.circle(sp, (x, y), r * k, "SD_Тонкие", (30, 30, 30), 25)
    S.line(sp, (x - r * k, y), (x + r * k, y), "SD_Тонкие", (30, 30, 30), 13)
    S.text(sp, str(num), (x, y + 1.15 * k), 1.9 * k, "MIDDLE_CENTER", bold=True)
    S.text(sp, str(sheet), (x, y - 1.2 * k), 1.6 * k, "MIDDLE_CENTER", rgb=(90, 90, 90))
    return Point(x, y).buffer(r * k + 0.3 * k)


# ------------------------------------------------------------------ walls & openings
def draw_walls(sp, P, k, shell_rgb=S.C_WALL, part_mode="solid", show_boxes=False):
    S.fill(sp, P.shell_cut, shell_rgb, "SD_Стены")
    outline(sp, P.shell_cut, (20, 20, 20), 35)
    for wid, shp in P.parts.items():
        if part_mode == "solid":
            S.fill(sp, shp, S.C_PART, "SD_Перегородки")
            outline(sp, shp, (40, 40, 40), 25, "SD_Перегородки")
        elif part_mode == "new":
            S.fill(sp, shp, (253, 232, 232), "SD_Перегородки")
            S.hatch(sp, shp, S.C_RED, "ANSI31", scale=0.2 * k, layer="SD_Перегородки")
            outline(sp, shp, S.C_RED, 35, "SD_Перегородки")
        elif part_mode == "ghost":
            dashed_shape(sp, shp, 1.2 * k, 0.7 * k, (150, 150, 155), 13)
    if show_boxes:
        for b in P.boxes:
            S.fill(sp, b["shape"], (226, 238, 252), "SD_Перегородки")
            S.hatch(sp, b["shape"], S.C_BLUE, "ANSI37", scale=0.28 * k, layer="SD_Перегородки")
            outline(sp, b["shape"], S.C_BLUE, 30, "SD_Перегородки")


def wall_obstacles(P, with_parts=True):
    g = [P.shell_cut]
    if with_parts:
        g += list(P.parts.values())
    return unary_union(g)


def _inside_sign(P, o):
    """+1 if the room side is the max side of the host wall (y1 for H walls, x1 for V)."""
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    if w["dir"] == "H":
        pmax, pmin = (o["c"], y1 + 120), (o["c"], y0 - 120)
    else:
        pmax, pmin = (x1 + 120, o["c"]), (x0 - 120, o["c"])
    inmax = any(r["shp"].contains(Point(pmax)) for r in P.rooms)
    inmin = any(r["shp"].contains(Point(pmin)) for r in P.rooms)
    if inmax and not inmin:
        return 1
    if inmin and not inmax:
        return -1
    return 1


def door_geom(P, o):
    """(hinge point, closed dir, open dir, leaf length, frame) for a door / balcony opening."""
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    sw = o.get("swing")
    sgn = _inside_sign(P, o)
    if sw is None:
        sw = (0, sgn) if w["dir"] == "H" else (sgn, 0)
    sx, sy = sw
    fr = o.get("frame", 40)
    a, b = o["c"] - o["w"] / 2.0, o["c"] + o["w"] / 2.0
    L = o.get("leaf", o["w"] - 2 * fr)
    hinge_side = o.get("hinge", "min")
    if "hinge_at" in o:
        hp = o["hinge_at"]
        cd = 1 if hinge_side == "min" else -1
    elif hinge_side == "min":
        hp, cd = a + fr, 1
    else:
        hp, cd = b - fr, -1
    if w["dir"] == "H":
        face = y1 if sy > 0 else y0
        return (hp, face), (cd, 0), (0, sy), L, fr
    face = x1 if sx > 0 else x0
    return (face, hp), (0, cd), (sx, 0), L, fr


def door_swing_area(P, o):
    hinge, cdir, odir, L, fr = door_geom(P, o)
    pts = [hinge]
    a0 = math.atan2(cdir[1], cdir[0])
    a1 = math.atan2(odir[1], odir[0])
    d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    for i in range(13):
        a = a0 + d * i / 12
        pts.append((hinge[0] + L * math.cos(a), hinge[1] + L * math.sin(a)))
    return Polygon(pts).buffer(0)


def draw_door(sp, P, o, k, rgb=(30, 30, 30), arc_rgb=(120, 120, 120)):
    hinge, cdir, odir, L, fr = door_geom(P, o)
    t = 70 if o.get("steel") else 40
    hx, hy = hinge
    p1 = (hx + odir[0] * L, hy + odir[1] * L)
    p2 = (p1[0] + cdir[0] * t, p1[1] + cdir[1] * t)
    p3 = (hx + cdir[0] * t, hy + cdir[1] * t)
    S.fill(sp, [hinge, p1, p2, p3], WHITE, "SD_Двери")
    S.poly(sp, [hinge, p1, p2, p3], "SD_Двери", True, rgb, 25)
    a_c = math.degrees(math.atan2(cdir[1], cdir[0]))
    a_o = math.degrees(math.atan2(odir[1], odir[0]))
    s, e = (a_c, a_o) if (a_o - a_c) % 360 == 90 else (a_o, a_c)
    S.arc(sp, hinge, L, s, e, "SD_Двери", arc_rgb, 13)
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    a, b = o["c"] - o["w"] / 2.0, o["c"] + o["w"] / 2.0
    ff = o.get("frame", 40)
    for (u0, u1) in ((a, a + ff), (b - ff, b)):
        if w["dir"] == "H":
            S.rect(sp, u0, y0, u1, y1, "SD_Двери", rgb, 18)
        else:
            S.rect(sp, x0, u0, x1, u1, "SD_Двери", rgb, 18)


def draw_window(sp, P, o, k, rgb=(30, 30, 30)):
    """Window / balcony door in a wall of any orientation; sill on the room side."""
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    sgn = _inside_sign(P, o)
    a, b = o["c"] - o["w"] / 2.0, o["c"] + o["w"] / 2.0
    if w["dir"] == "H":
        mid = (y0 + y1) / 2.0
        face_in = y1 if sgn > 0 else y0
        face_out = y0 if sgn > 0 else y1
        T = lambda u, v: (u, v)  # noqa: E731
    else:
        mid = (x0 + x1) / 2.0
        face_in = x1 if sgn > 0 else x0
        face_out = x0 if sgn > 0 else x1
        T = lambda u, v: (v, u)  # noqa: E731
    s = sgn
    fr = [T(a, mid - 35), T(b, mid - 35), T(b, mid + 35), T(a, mid + 35)]
    S.fill(sp, fr, WHITE, "SD_Окна")
    S.poly(sp, fr, "SD_Окна", True, rgb, 25)
    S.line(sp, T(a, mid - 8), T(b, mid - 8), "SD_Окна", rgb, 13)
    S.line(sp, T(a, mid + 8), T(b, mid + 8), "SD_Окна", rgb, 13)
    S.line(sp, T(a, mid + s * 35), T(a, face_in), "SD_Окна", rgb, 13)
    S.line(sp, T(b, mid + s * 35), T(b, face_in), "SD_Окна", rgb, 13)
    if o["kind"] == "window":
        sill_out = face_in + s * 60
        S.fill(sp, [T(a - 40, mid + s * 35), T(b + 40, mid + s * 35), T(b + 40, sill_out), T(a - 40, sill_out)], (250, 250, 250), "SD_Окна")
        S.poly(sp, [T(a, mid + s * 35), T(a - 40, face_in), T(a - 40, sill_out), T(b + 40, sill_out), T(b + 40, face_in), T(b, mid + s * 35)],
               "SD_Окна", False, rgb, 18)
        S.line(sp, T(a, mid + s * 35), T(b, mid + s * 35), "SD_Окна", rgb, 18)
        ot = face_out - s * 30
        S.line(sp, T(a - 20, ot), T(b + 20, ot), "SD_Окна", rgb, 13)
        S.line(sp, T(a - 20, ot), T(a - 20, face_out), "SD_Окна", rgb, 13)
        S.line(sp, T(b + 20, ot), T(b + 20, face_out), "SD_Окна", rgb, 13)
    else:
        o2 = dict(o)
        o2.setdefault("frame", 60)
        draw_door(sp, P, o2, k, rgb)


def draw_openings(sp, P, k, doors=True, windows=True, door_rgb=(30, 30, 30), only_walls=None):
    for o in P.openings:
        if only_walls is not None and o["wall"] not in only_walls:
            continue
        if o["kind"] in ("window", "balcony"):
            if windows:
                draw_window(sp, P, o, k)
        elif o["kind"] == "door" and doors:
            draw_door(sp, P, o, k, door_rgb)


def draw_overhead(sp, P, k, rgb=(140, 140, 140)):
    """Overhead elements (bulkheads marked overhead) as dashed outlines on floor plans."""
    for z in P.ceilings.get("zones", []):
        if z.get("overhead"):
            dashed_poly(sp, z["poly"], 1.6 * k, 0.8 * k, rgb, 13)


def draw_axes(sp, P, k, sides=("B", "L"), off_b=1800, off_l=1450, ext=200, rgb=(70, 70, 70)):
    x0, y0, x1, y1 = P.bounds
    r = 3.5 * k
    geoms = []
    for name, x in P.grid.get("x", []):
        if "B" in sides:
            ya, yb = y0 - ext, y0 - off_b
            S.line(sp, (x, ya), (x, yb), "SD_Оси", rgb, 13)
            geoms.append(LineString([(x, ya), (x, yb)]).buffer(0.25 * k))
            c = (x, yb - r)
            S.circle(sp, c, r, "SD_Оси", rgb, 18)
            S.text(sp, name, c, 3.0 * k, "MIDDLE_CENTER", rgb=rgb)
            geoms.append(Point(c).buffer(r))
    for name, y in P.grid.get("y", []):
        if "L" in sides:
            xa, xb = x0 - ext, x0 - off_l
            S.line(sp, (xa, y), (xb, y), "SD_Оси", rgb, 13)
            geoms.append(LineString([(xa, y), (xb, y)]).buffer(0.25 * k))
            c = (xb - r, y)
            S.circle(sp, c, r, "SD_Оси", rgb, 18)
            S.text(sp, name, c, 3.0 * k, "MIDDLE_CENTER", rgb=rgb)
            geoms.append(Point(c).buffer(r))
    return geoms


# ------------------------------------------------------------------ lighting / electrics / water
def _filled_circle(sp, c, r, rgb, layer="SD_Свет"):
    S.fill(sp, Point(c).buffer(r, 24), rgb, layer)


def light_icon(sp, f, k):
    """Draws a fixture; returns its footprint (for collision registry)."""
    kind, x, y = f["kind"], f["x"], f["y"]
    if kind in ("spot", "spot_ip44"):
        col = S.C_RED if kind == "spot" else S.C_BLUE
        S.fill(sp, Point(x, y).buffer(1.25 * k, 24), WHITE, "SD_Свет")
        S.circle(sp, (x, y), 1.25 * k, "SD_Свет", col, 25)
        S.line(sp, (x - 2.1 * k, y), (x + 2.1 * k, y), "SD_Свет", col, 18)
        S.line(sp, (x, y - 2.1 * k), (x, y + 2.1 * k), "SD_Свет", col, 18)
        if kind == "spot_ip44":
            _filled_circle(sp, (x, y), 0.45 * k, col)
        return Point(x, y).buffer(2.1 * k)
    if kind in ("spot2", "spot2_ip44"):
        col = S.C_RED if kind == "spot2" else S.C_BLUE
        w, h = 2.4 * k, 1.3 * k
        S.fill(sp, [(x - w, y - h), (x + w, y - h), (x + w, y + h), (x - w, y + h)], WHITE, "SD_Свет")
        S.rect(sp, x - w, y - h, x + w, y + h, "SD_Свет", col, 25)
        for dx in (-1.1 * k, 1.1 * k):
            S.circle(sp, (x + dx, y), 0.8 * k, "SD_Свет", col, 18)
            S.line(sp, (x + dx - 0.8 * k, y), (x + dx + 0.8 * k, y), "SD_Свет", col, 13)
            S.line(sp, (x + dx, y - 0.8 * k), (x + dx, y + 0.8 * k), "SD_Свет", col, 13)
        return box(x - w, y - h, x + w, y + h)
    if kind == "surface":
        S.fill(sp, Point(x, y).buffer(1.6 * k, 24), WHITE, "SD_Свет")
        S.circle(sp, (x, y), 1.6 * k, "SD_Свет", S.C_RED, 25)
        _filled_circle(sp, (x, y), 0.95 * k, S.C_RED)
        return Point(x, y).buffer(1.7 * k)
    if kind == "chandelier":
        S.fill(sp, Point(x, y).buffer(3.4 * k, 48), WHITE, "SD_Свет")
        S.circle(sp, (x, y), 3.4 * k, "SD_Свет", S.C_AMBER, 35)
        S.circle(sp, (x, y), 1.1 * k, "SD_Свет", S.C_AMBER, 25)
        for i in range(8):
            a = math.radians(i * 45 + 22.5)
            S.line(sp, (x + 1.5 * k * math.cos(a), y + 1.5 * k * math.sin(a)),
                   (x + 2.8 * k * math.cos(a), y + 2.8 * k * math.sin(a)), "SD_Свет", S.C_AMBER, 18)
        return Point(x, y).buffer(3.5 * k)
    if kind == "pendant":
        S.fill(sp, Point(x, y).buffer(2.3 * k, 36), WHITE, "SD_Свет")
        S.circle(sp, (x, y), 2.3 * k, "SD_Свет", S.C_AMBER, 30)
        _filled_circle(sp, (x, y), 0.9 * k, S.C_AMBER)
        return Point(x, y).buffer(2.4 * k)
    if kind == "linear":
        x2, y2 = f["x2"], f["y2"]
        hw = 0.55 * k
        if abs(y2 - y) < 1:
            pts = [(x, y - hw), (x2, y - hw), (x2, y + hw), (x, y + hw)]
        else:
            pts = [(x - hw, y), (x + hw, y), (x + hw, y2), (x - hw, y2)]
        S.fill(sp, pts, (255, 236, 200), "SD_Свет")
        S.poly(sp, pts, "SD_Свет", True, S.C_AMBER, 30)
        return Polygon(pts)
    if kind == "track":
        S.line(sp, (x, y), (f["x2"], f["y2"]), "SD_Свет", (45, 45, 48), 70)
        return LineString([(x, y), (f["x2"], f["y2"])]).buffer(0.6 * k)
    if kind == "track_rect":
        pts = [(x, y), (f["x2"], y), (f["x2"], f["y2"]), (x, f["y2"])]
        S.poly(sp, pts, "SD_Свет", True, (45, 45, 48), 70)
        return Polygon(pts).exterior.buffer(0.6 * k)
    if kind == "track_spot":
        d = 1.1 * k
        S.fill(sp, [(x - d, y), (x, y - d), (x + d, y), (x, y + d)], S.C_RED, "SD_Свет")
        S.poly(sp, [(x - d, y), (x, y - d), (x + d, y), (x, y + d)], "SD_Свет", True, (120, 20, 20), 18)
        return box(x - d, y - d, x + d, y + d)
    if kind == "led":
        dashed(sp, (x, y), (f["x2"], f["y2"]), 1.2 * k, 0.6 * k, S.C_AMBER, 50, "SD_LED")
        return LineString([(x, y), (f["x2"], f["y2"])]).buffer(0.5 * k)
    # unknown -> generic spot
    S.circle(sp, (x, y), 1.4 * k, "SD_Свет", S.C_RED, 25)
    return Point(x, y).buffer(1.5 * k)


NORMALS = {"X+": (1, 0), "X-": (-1, 0), "Y+": (0, 1), "Y-": (0, -1)}


def switch_icon(sp, s, k, label=True):
    x, y = s["x"], s["y"]
    n = NORMALS[s["wall"]]
    c = (x + n[0] * 1.6 * k, y + n[1] * 1.6 * k)
    S.fill(sp, Point(c).buffer(1.1 * k, 24), WHITE, "SD_Электрика")
    S.circle(sp, c, 1.1 * k, "SD_Электрика", (30, 30, 30), 25)
    t = (-n[1], n[0])
    keys = s.get("keys", 1)
    for i in range(keys):
        off = (i - (keys - 1) / 2.0) * 0.55
        dx = n[0] + t[0] * (0.9 + off)
        dy = n[1] + t[1] * (0.9 + off)
        L = math.hypot(dx, dy)
        dx, dy = dx / L, dy / L
        p0 = (c[0] + dx * 1.1 * k, c[1] + dy * 1.1 * k)
        p1 = (c[0] + dx * 2.6 * k, c[1] + dy * 2.6 * k)
        S.line(sp, p0, p1, "SD_Электрика", (30, 30, 30), 25)
        S.line(sp, p1, (p1[0] - dy * 0.6 * k, p1[1] + dx * 0.6 * k), "SD_Электрика", (30, 30, 30), 25)
    modes = [c_.get("mode") for c_ in s.get("controls", [])]
    if s.get("pass_through") or "pass" in modes or "cross" in modes:      # multipoint: mirrored stroke (GOST 21.614)
        S.line(sp, (c[0] - t[0] * 1.1 * k, c[1] - t[1] * 1.1 * k), (c[0] - t[0] * 2.4 * k, c[1] - t[1] * 2.4 * k),
               "SD_Электрика", (30, 30, 30), 25)
    if "cross" in modes:
        S.line(sp, (c[0] + t[0] * 1.1 * k, c[1] + t[1] * 1.1 * k), (c[0] + t[0] * 2.4 * k, c[1] + t[1] * 2.4 * k),
               "SD_Электрика", (30, 30, 30), 25)
    return c, Point(c).buffer(2.9 * k)


SOCKET_RGB = {"Р": S.C_RED, "Р2": S.C_RED, "РВ": S.C_RED, "Р32": (190, 30, 30), "ТВ": S.C_GREEN, "LAN": S.C_GREEN,
              "КОНД": S.C_BLUE, "БРА": S.C_AMBER, "ВЫВ": S.C_AMBER}


def socket_icon(sp, s, k, along=0.0):
    x, y = s["x"], s["y"]
    n = NORMALS[s["wall"]]
    t = (-n[1], n[0])
    x, y = x + t[0] * along, y + t[1] * along
    kind = s["kind"]
    col = SOCKET_RGB.get(kind, S.C_RED)
    a0 = math.degrees(math.atan2(n[1], n[0]))
    if kind in ("Р", "Р2", "РВ", "Р32"):
        r = 1.6 * k
        c = (x + n[0] * 0.25 * k, y + n[1] * 0.25 * k)
        semi = Polygon([(c[0] + r * math.cos(math.radians(a0 - 90 + i * 6)), c[1] + r * math.sin(math.radians(a0 - 90 + i * 6))) for i in range(31)])
        S.fill(sp, semi, col if kind == "РВ" else WHITE, "SD_Электрика")
        S.poly(sp, list(semi.exterior.coords)[:-1], "SD_Электрика", True, col, 25)
        tip = (c[0] + n[0] * r, c[1] + n[1] * r)
        if kind == "Р2":
            for d in (-0.45, 0.45):
                b0 = (tip[0] + t[0] * d * k, tip[1] + t[1] * d * k)
                S.line(sp, b0, (b0[0] + n[0] * 0.9 * k, b0[1] + n[1] * 0.9 * k), "SD_Электрика", col, 25)
        else:
            S.line(sp, tip, (tip[0] + n[0] * 0.9 * k, tip[1] + n[1] * 0.9 * k), "SD_Электрика", col, 25)
        if kind == "Р32":
            m = (c[0] + n[0] * r * 0.45, c[1] + n[1] * r * 0.45)
            S.fill(sp, Point(m).buffer(0.45 * k, 12), col, "SD_Электрика")
        return Point(x, y).buffer(2.8 * k)
    if kind in ("ТВ", "LAN", "КОНД"):
        w, h = 1.5 * k, 1.15 * k
        c = (x + n[0] * (h + 0.1 * k), y + n[1] * (h + 0.1 * k))
        pts = [(c[0] + t[0] * w * sx + n[0] * h * sy, c[1] + t[1] * w * sx + n[1] * h * sy) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        S.fill(sp, pts, WHITE, "SD_Электрика")
        S.poly(sp, pts, "SD_Электрика", True, col, 25)
        lab = {"ТВ": "TV", "LAN": "LAN", "КОНД": "К"}[kind]
        S.text(sp, lab, c, (0.95 if kind != "LAN" else 0.75) * k, "MIDDLE_CENTER", bold=True, rgb=col)
        return Polygon(pts).buffer(0.2 * k)
    if kind == "БРА":
        c = (x + n[0] * 1.0 * k, y + n[1] * 1.0 * k)
        S.fill(sp, Point(c).buffer(0.9 * k, 16), WHITE, "SD_Электрика")
        S.circle(sp, c, 0.9 * k, "SD_Электрика", col, 25)
        S.line(sp, (c[0] - 0.64 * k, c[1] - 0.64 * k), (c[0] + 0.64 * k, c[1] + 0.64 * k), "SD_Электрика", col, 18)
        S.line(sp, (c[0] - 0.64 * k, c[1] + 0.64 * k), (c[0] + 0.64 * k, c[1] - 0.64 * k), "SD_Электрика", col, 18)
        return Point(c).buffer(1.1 * k)
    c = (x + n[0] * 0.9 * k, y + n[1] * 0.9 * k)
    d = 0.8 * k
    pts = [(c[0] - d, c[1] - d), (c[0] + d, c[1] - d), (c[0] + d, c[1] + d), (c[0] - d, c[1] + d)]
    S.fill(sp, pts, col, "SD_Электрика")
    S.poly(sp, pts, "SD_Электрика", True, col, 18)
    return Polygon(pts).buffer(0.2 * k)


WATER_RGB = {"ХВС": S.C_BLUE, "ГВС": S.C_RED, "К50": S.C_BROWN, "К110": S.C_BROWN}


def water_icon(sp, P, o, k, n=None):
    x, y = o["x"], o["y"]
    col = WATER_RGB.get(o["kind"], S.C_BLUE)
    if o["kind"].startswith("К") and o.get("h", 1) == 0:
        S.fill(sp, Point(x, y).buffer(1.3 * k, 24), WHITE, "SD_Вода")
        S.circle(sp, (x, y), 1.3 * k, "SD_Вода", col, 30)
        S.circle(sp, (x, y), 0.7 * k, "SD_Вода", col, 18)
        return (x, y), Point(x, y).buffer(1.4 * k)
    if n is None:
        n = P.inward_normal((x, y))[0] if P is not None else (0, 1)
    c = (x + n[0] * 1.1 * k, y + n[1] * 1.1 * k)
    r = 1.0 * k if o["kind"] != "К110" else 1.25 * k
    S.line(sp, (x, y), c, "SD_Вода", col, 30)
    S.fill(sp, Point(c).buffer(r, 24), col, "SD_Вода")
    S.circle(sp, c, r, "SD_Вода", (30, 30, 30), 13)
    return c, Point(c).buffer(r + 0.2 * k)


# ------------------------------------------------------------------ furniture
def furniture_detail(sp, f, k, line_rgb=(70, 70, 75), fill_rgb=WHITE, lw=18):
    shp = Polygon(f["poly"]).buffer(0)
    pts = f["poly"]
    kind = f.get("kind", "furn")
    x0, y0, x1, y1 = shp.bounds
    if kind == "rug":
        S.fill(sp, shp, (244, 239, 230), "SD_Мебель")
        dashed_poly(sp, pts, 1.0 * k, 0.6 * k, (160, 150, 135), 13, layer="SD_Мебель")
        inner = shp.buffer(-1.4 * k)
        if not inner.is_empty and inner.geom_type == "Polygon":
            dashed_poly(sp, list(inner.exterior.coords)[:-1], 0.4 * k, 0.5 * k, (190, 180, 165), 9, layer="SD_Мебель")
        return
    if kind in ("kitchen_upper", "upper"):
        dashed_poly(sp, pts, 1.2 * k, 0.7 * k, (110, 110, 115), 13, layer="SD_Мебель_скр")
        return
    S.fill(sp, shp, fill_rgb, "SD_Мебель")
    S.poly(sp, pts, "SD_Мебель", True, line_rgb, lw)
    hd = f.get("head", "W")
    if kind == "bed":
        if hd in ("W", "E"):
            hb = x0 + 160 if hd == "W" else x1 - 160
            sg = 1 if hd == "W" else -1
            S.line(sp, (hb, y0 + 60), (hb, y1 - 60), "SD_Мебель", line_rgb, 13)
            for (a, b) in ((y0 + 180, (y0 + y1) / 2 - 60), ((y0 + y1) / 2 + 60, y1 - 180)):
                xa, xb = sorted((hb + sg * 60, hb + sg * 480))
                pil = box(xa, a, xb, b).buffer(60).buffer(-30)
                S.poly(sp, list(pil.exterior.coords)[:-1], "SD_Мебель", True, line_rgb, 13)
            fold = x0 + (x1 - x0) * (0.62 if hd == "W" else 0.38)
            S.line(sp, (fold, y0 + 70), (fold, y1 - 70), "SD_Мебель", line_rgb, 13)
        else:
            hb = y0 + 160 if hd == "S" else y1 - 160
            sg = 1 if hd == "S" else -1
            S.line(sp, (x0 + 60, hb), (x1 - 60, hb), "SD_Мебель", line_rgb, 13)
            for (a, b) in ((x0 + 180, (x0 + x1) / 2 - 60), ((x0 + x1) / 2 + 60, x1 - 180)):
                ya, yb = sorted((hb + sg * 60, hb + sg * 480))
                pil = box(a, ya, b, yb).buffer(60).buffer(-30)
                S.poly(sp, list(pil.exterior.coords)[:-1], "SD_Мебель", True, line_rgb, 13)
            fold = y0 + (y1 - y0) * (0.62 if hd == "S" else 0.38)
            S.line(sp, (x0 + 70, fold), (x1 - 70, fold), "SD_Мебель", line_rgb, 13)
    elif kind == "wardrobe":
        if (x1 - x0) >= (y1 - y0):
            dashed(sp, (x0 + 60, (y0 + y1) / 2), (x1 - 60, (y0 + y1) / 2), 0.8 * k, 0.5 * k, line_rgb, 13, "SD_Мебель")
        else:
            dashed(sp, ((x0 + x1) / 2, y0 + 60), ((x0 + x1) / 2, y1 - 60), 0.8 * k, 0.5 * k, line_rgb, 13, "SD_Мебель")
        S.line(sp, (x0, y1), (x1, y0), "SD_Мебель", (170, 170, 170), 9)
    elif kind in ("cabinet", "nightstand", "tv_stand", "shoe_cabinet", "desk"):
        inner = shp.buffer(-25)
        if not inner.is_empty and inner.geom_type == "Polygon":
            S.poly(sp, list(inner.exterior.coords)[:-1], "SD_Мебель", True, (150, 150, 150), 9)
    elif kind in ("sofa", "armchair"):
        inner = shp.buffer(-170, join_style=2)
        if not inner.is_empty:
            ip = inner if inner.geom_type == "Polygon" else max(inner.geoms, key=lambda g: g.area)
            S.poly(sp, list(ip.exterior.coords)[:-1], "SD_Мебель", True, line_rgb, 13)
    elif kind == "tv":
        S.fill(sp, shp, (60, 60, 64), "SD_Мебель")
    elif kind == "sink":
        bowl = box(x0 + 60, y0 + 60, x1 - 60, y1 - 60).buffer(-40).buffer(40)
        if not bowl.is_empty:
            S.poly(sp, list(bowl.exterior.coords)[:-1], "SD_Мебель", True, line_rgb, 13)
        S.circle(sp, ((x0 + x1) / 2, (y0 + y1) / 2), 30, "SD_Мебель", line_rgb, 13)
    elif kind == "hob":
        for (cx, cy, r) in ((x0 + 130, y0 + 130, 85), (x1 - 130, y0 + 130, 70), (x0 + 130, y1 - 130, 70), (x1 - 130, y1 - 130, 95)):
            S.circle(sp, (cx, cy), r, "SD_Мебель", line_rgb, 13)
            S.circle(sp, (cx, cy), r * 0.55, "SD_Мебель", (160, 160, 160), 9)
    elif kind == "fridge":
        S.line(sp, (x0, y0), (x1, y1), "SD_Мебель", (160, 160, 160), 9)
        S.line(sp, (x0, y1), (x1, y0), "SD_Мебель", (160, 160, 160), 9)
    elif kind == "kitchen_base":
        S.line(sp, (x0 + 20, y0), (x0 + 20, y1), "SD_Мебель", (150, 150, 150), 9)
    elif kind in ("shower", "bath"):
        cx, cy = f.get("drain", ((x0 + x1) / 2, (y0 + y1) / 2))
        S.circle(sp, (cx, cy), 45, "SD_Мебель", line_rgb, 13)
        if kind == "shower":
            for (px, py) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                S.line(sp, (px + (40 if px == x0 else -40), py + (40 if py == y0 else -40)), (cx, cy), "SD_Мебель", (175, 175, 175), 9)
        inner = shp.buffer(-40 if kind == "shower" else -70, join_style=2)
        if not inner.is_empty and inner.geom_type == "Polygon":
            S.poly(sp, list(inner.exterior.coords)[:-1], "SD_Мебель", True, (150, 150, 150), 9)
    elif kind == "wc":
        inner = shp.buffer(-45)
        if not inner.is_empty and inner.geom_type == "Polygon":
            S.poly(sp, list(inner.exterior.coords)[:-1], "SD_Мебель", True, (150, 150, 150), 9)
    elif kind == "basin":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rw, rh = (x1 - x0) * 0.32, (y1 - y0) * 0.3
        S.poly(sp, [(cx + rw * math.cos(math.radians(a)), cy + rh * math.sin(math.radians(a))) for a in range(0, 360, 10)],
               "SD_Мебель", True, line_rgb, 13)
    elif kind == "washer":
        S.circle(sp, ((x0 + x1) / 2, (y0 + y1) / 2), min(x1 - x0, y1 - y0) * 0.33, "SD_Мебель", line_rgb, 13)
    elif kind == "mirror":
        S.fill(sp, shp, (200, 220, 235), "SD_Мебель")
    elif kind == "rail":
        S.fill(sp, shp, (90, 90, 95), "SD_Мебель")


def furniture_all(sp, P, k, rooms=None, line_rgb=(70, 70, 75), fill_rgb=WHITE, lw=18):
    order = {"rug": 0, "kitchen_upper": 2, "upper": 2}
    for f in sorted(P.furniture, key=lambda f: order.get(f.get("kind"), 1)):
        if rooms and f.get("room") not in rooms:
            continue
        furniture_detail(sp, f, k, line_rgb, fill_rgb, lw)


def furniture_ghost(sp, P, k, rgb=(185, 185, 190)):
    for f in P.furniture:
        if f.get("kind") == "rug":
            continue
        if f.get("kind") in ("kitchen_upper", "upper"):
            dashed_poly(sp, f["poly"], 1.0 * k, 0.6 * k, rgb, 9)
        else:
            S.poly(sp, f["poly"], "SD_Мебель_скр", True, rgb, 9)


# ------------------------------------------------------------------ floors
def plank_lines(sp, shp, plank_w=160, plank_l=1300, along="y", origin=(0, 0), rgb=PARQUET_J, stagger=(0, 433, 866)):
    if isinstance(shp, (list, tuple)):
        shp = Polygon(shp)
    minx, miny, maxx, maxy = shp.bounds
    ox, oy = origin
    segs = []
    if along == "y":
        i0, i1 = math.floor((minx - ox) / plank_w), math.ceil((maxx - ox) / plank_w)
        for i in range(i0, i1 + 1):
            x = ox + i * plank_w
            segs.append(((x, miny - 1), (x, maxy + 1)))
            off = stagger[i % len(stagger)]
            for j in range(math.floor((miny - oy - off) / plank_l), math.ceil((maxy - oy - off) / plank_l) + 1):
                y = oy + off + j * plank_l
                segs.append(((x, y), (x + plank_w, y)))
    else:
        i0, i1 = math.floor((miny - oy) / plank_w), math.ceil((maxy - oy) / plank_w)
        for i in range(i0, i1 + 1):
            y = oy + i * plank_w
            segs.append(((minx - 1, y), (maxx + 1, y)))
            off = stagger[i % len(stagger)]
            for j in range(math.floor((minx - ox - off) / plank_l), math.ceil((maxx - ox - off) / plank_l) + 1):
                x = ox + off + j * plank_l
                segs.append(((x, y), (x, y + plank_w)))
    for a, b in segs:
        g = LineString([a, b]).intersection(shp)
        for gg in (g.geoms if hasattr(g, "geoms") else [g]):
            if gg.geom_type == "LineString" and gg.length > 2:
                c = list(gg.coords)
                S.line(sp, c[0], c[-1], "SD_Тонкие", rgb, 9)


def tile_origin(P, room_name, zone):
    """Tiles: symmetric on the room axis across the entrance; full tile at the entrance side."""
    r = P.room_by_name.get(room_name)
    if r is None:
        x0, y0, x1, y1 = zone.bounds
        return ((x0 + x1) / 2 - 300, y0), None
    x0, y0, x1, y1 = r["shp"].bounds
    door = None
    for o in P.openings:
        if o["kind"] in ("door", "balcony", "passage") and P.open_shape[o["id"]].buffer(30).intersects(r["shp"]):
            door = o
            break
    if door is None:
        return ((x0 + x1) / 2 - 300, (y0 + y1) / 2 - 300), ((x0 + x1) / 2, (y0 + y1) / 2)
    dc = P.open_shape[door["id"]].centroid
    w = P.wall_by_id[door["wall"]]
    if w["dir"] == "H":
        oy = y1 if abs(dc.y - y1) < abs(dc.y - y0) else y0
        ox = (x0 + x1) / 2 - 300
        mark = ((x0 + x1) / 2, oy - 300 if oy == y1 else oy + 300)
    else:
        ox = x1 if abs(dc.x - x1) < abs(dc.x - x0) else x0
        oy = (y0 + y1) / 2 - 300
        mark = (ox - 300 if ox == x1 else ox + 300, (y0 + y1) / 2)
    return (ox, oy), mark
