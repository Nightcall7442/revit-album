# -*- coding: utf-8 -*-
"""Dimension chains with collision-aware text placement + automatic chain builders."""
import math
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union

from . import gfx as S
from .placer import text_geom

TXT = 1.9    # paper mm, matches dimstyle dimtxt
GAP = 0.6


def style_for(k):
    return {50: "SD50", 40: "SD40", 30: "SD30", 25: "SD25", 20: "SD20", 10: "SD10", 5: "SD5", 1: "SD1"}.get(int(round(k)), "SD50")


def chain(sp, values, line_pos, ext_from, k, occ=None, vertical=False, merge=1.0, min_seg=1.0, register=True):
    """Draw a chain; every text position is chosen to avoid occ. Returns list of text geoms.

    Text rules (GOST 2.307 practice): a value that fits sits centred over its segment; a value that does not fit is
    raised one row above its own segment (staggered), and only the end segments may carry the value outside the chain.
    Values that fit are placed first so the short ones never push them aside."""
    vals = []
    for v in sorted(values):
        if not vals or v - vals[-1] > merge:
            vals.append(v)
    st = style_for(k)
    th = TXT * k
    n = len(vals) - 1
    side = 1 if line_pos >= ext_from else -1      # text placed on the far side of the dim line from the object
    lift = (GAP + TXT * 0.5) * k + 0.15 * k
    rot = 90 if vertical else 0
    segs = []
    for i in range(n):
        a, b = vals[i], vals[i + 1]
        if b - a < min_seg:
            continue
        s = "%d" % round(b - a)
        w = S.tw(s, th)
        fits = (b - a) > w + 1.2 * k
        segs.append((i, a, b, s, w, fits))
    order = [x for x in segs if x[5]] + [x for x in segs if not x[5]]
    placed = {}
    for i, a, b, s, w, fits in order:
        mid = (a + b) / 2.0
        up1 = (mid, line_pos + side * (lift + th * 1.25))
        up2 = (mid, line_pos + side * (lift + th * 2.5))
        before = (a - w / 2 - 1.2 * k, line_pos + side * lift)
        after = (b + w / 2 + 1.2 * k, line_pos + side * lift)
        cands = []
        if fits:
            cands.append((mid, line_pos + side * lift))
            if (b - a) > 2 * w + 3.0 * k:       # shifted inside the segment (clears an axis / extension line at mid)
                for f in (0.6, 1.0, 1.4):
                    dd = w / 2 + f * k
                    cands += [(mid - dd, line_pos + side * lift), (mid + dd, line_pos + side * lift)]
            cands += [up1, (mid, line_pos - side * lift), up2]
            if i == 0:
                cands.append(before)
            if i == n - 1:
                cands.append(after)
            cands += [before, after, (before[0], line_pos - side * lift), (after[0], line_pos - side * lift)]
        else:
            if i == 0:
                cands.append(before)
            if i == n - 1:
                cands.append(after)
            cands += [up1, up2, (mid, line_pos - side * lift), (mid, line_pos - side * (lift + th * 1.25))]
            if i != 0:
                cands.append(before)
            if i != n - 1:
                cands.append(after)
            cands.append((mid, line_pos + side * lift))
        best = None
        for along, across in cands:
            p = (across, along) if vertical else (along, across)
            g = text_geom(s, p, th, "MIDDLE_CENTER", rot, False, 0.2 * k)
            sc = occ.overlap(g) if occ is not None else 0.0
            sc += sum(g.intersection(pg).area for pg in placed.values())
            if sc <= 1e-6:
                best = (0, p, g)
                break
            if best is None or sc < best[0]:
                best = (sc, p, g)
        placed[i] = best[2]
        _, p, g = best
        if vertical:
            p1, p2, base_ = (ext_from, a), (ext_from, b), (line_pos, a)
        else:
            p1, p2, base_ = (a, ext_from), (b, ext_from), (a, line_pos)
        d = sp.add_linear_dim(base=base_, p1=p1, p2=p2, angle=90 if vertical else 0, dimstyle=st, location=p,
                              text="<>", dxfattribs={"layer": "SD_Размеры"})
        d.render()
    out = [placed[i] for i in sorted(placed)]
    if occ is not None and register:
        for g in out:
            occ.add(g, "dimtext")
        if n >= 1:
            # the dimension line itself is a (thin) obstacle for other texts
            if vertical:
                occ.add(LineString([(line_pos, vals[0]), (line_pos, vals[-1])]).buffer(0.15 * k), "dimline")
            else:
                occ.add(LineString([(vals[0], line_pos), (vals[-1], line_pos)]).buffer(0.15 * k), "dimline")
    return out


# ------------------------------------------------------------------ automatic builders
def outline_of(P):
    """Outer contour of the building mass without collinear / duplicate vertices."""
    m = P.mass
    if hasattr(m, "geoms"):
        g = unary_union([Polygon(g.exterior) for g in m.geoms])
    else:
        g = Polygon(m.exterior)
    return g.simplify(1.0, preserve_topology=True)


def _facing_edges(poly, side):
    """Outline edges facing outward to side B/T/L/R -> list of (fixed coord, a, b)."""
    out = []
    cs = list(poly.exterior.coords)
    for (x0, y0), (x1, y1) in zip(cs[:-1], cs[1:]):
        if abs(y0 - y1) < 1 and side in "BT":
            mx = (x0 + x1) / 2
            probe = Point(mx, y0 + (-5 if side == "B" else 5))
            if not poly.contains(probe):
                out.append((y0, min(x0, x1), max(x0, x1)))
        elif abs(x0 - x1) < 1 and side in "LR":
            my = (y0 + y1) / 2
            probe = Point(x0 + (-5 if side == "L" else 5), my)
            if not poly.contains(probe):
                out.append((x0, min(y0, y1), max(y0, y1)))
    return out


def side_rows(P, side):
    """Number of outer chain rows on side T/R (openings row + overall)."""
    poly = outline_of(P)
    x0, y0, x1, y1 = poly.bounds
    lev = {"T": y1, "R": x1, "B": y0, "L": x0}[side]
    for o in P.openings:
        r = P.opening_rect(o)
        face = {"T": r[3], "R": r[2], "B": r[1], "L": r[0]}[side]
        if abs(face - lev) < 2:
            return 2
    return 1


def outer_chains(sp, P, k, occ, sides=("B", "L"), openings=True, axes=True, first=700, step=400, first_far=None):
    """Standard outer chains: openings / axes / overall, per side; stepped outlines get a chain per level.
    B/L carry the axes row; T/R (narrow sheet margins) start at first_far and never repeat the axes row."""
    poly = outline_of(P)
    x0, y0, x1, y1 = poly.bounds
    gx = [v for _, v in P.grid.get("x", [])]
    gy = [v for _, v in P.grid.get("y", [])]
    for side in sides:
        edges = _facing_edges(poly, side)
        if not edges:
            continue
        horiz = side in "BT"
        sgn = -1 if side in "BL" else 1
        extreme = (y0 if side == "B" else y1) if horiz else (x0 if side == "L" else x1)
        levels = {}
        for c, a, b in edges:
            levels.setdefault(round(c), []).append((a, b))
        main = round(extreme)
        for lev, spans in sorted(levels.items(), key=lambda kv: abs(kv[0] - main)):
            pts = set()
            for a, b in spans:
                pts.update([a, b])
            lo, hi = min(pts), max(pts)
            if openings:
                for o in P.openings:
                    r = P.opening_rect(o)
                    face = (r[1] if side == "B" else r[3]) if horiz else (r[0] if side == "L" else r[2])
                    if abs(face - lev) < 2:
                        a_, b_ = (r[0], r[2]) if horiz else (r[1], r[3])
                        if lo - 1 <= a_ and b_ <= hi + 1:
                            pts.update([a_, b_])
            far = side in "TR"
            pos = lev + sgn * (first_far if (far and first_far) else first)
            rows = []
            if openings and len(pts) > 2:
                rows.append(sorted(pts))
            if axes and lev == main and not far:
                g = gx if horiz else gy
                if len(g) >= 2:
                    rows.append(g)
            rows.append([lo, hi])
            if lev != main and len(rows) > 1 and rows[-1] == sorted(pts):
                rows = rows[:-1]
            for vals in rows:
                chain(sp, vals, pos, lev, k, occ, vertical=not horiz)
                pos += sgn * step
    return poly


def edge_chains(sp, P, points, k, occ, offsets=(320, 650, 950), include_ends=True):
    """Bind points lying on room walls: one chain per wall face, parallel to it, inside the room."""
    by_edge = {}
    for p in points:
        r = P.room_of_point(p, 80)
        if r is None:
            continue
        n, (a, b) = P.inward_normal(p, r)
        key = (r["name"], tuple(map(round, a)), tuple(map(round, b)))
        e = by_edge.setdefault(key, dict(n=n, a=a, b=b, pts=[]))
        e["pts"].append(p)
    for key, e in by_edge.items():
        a, b, n = e["a"], e["b"], e["n"]
        horiz = abs(a[1] - b[1]) < 1
        vals = ([a[0], b[0]] if horiz else [a[1], b[1]]) if include_ends else []
        vals += [p[0] if horiz else p[1] for p in e["pts"]]
        face = a[1] if horiz else a[0]
        nn = n[1] if horiz else n[0]
        best = None
        for off in offsets:
            pos = face + nn * off
            line = LineString([(min(vals), pos), (max(vals), pos)]) if horiz else LineString([(pos, min(vals)), (pos, max(vals))])
            sc = occ.overlap(line.buffer(TXT * k * 1.2 + 0.3 * k), ignore=("wallzone",))
            if best is None or sc < best[0]:
                best = (sc, pos)
            if sc <= 1e-6:
                break
        chain(sp, vals, best[1], face, k, occ, vertical=not horiz)


def room_point_chains(sp, P, room, pts, k, occ, xs=None, ys=None, merge=40.0):
    """Bind fixtures inside a room to its walls: one horizontal + one vertical chain.
    pts: [(x, y)] or explicit xs / ys lists. Values closer than `merge` collapse into one."""
    shp = room["shp"]
    x0, y0, x1, y1 = shp.bounds
    if pts is not None:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
    xs = sorted(set(round(v) for v in (xs or [])))
    ys = sorted(set(round(v) for v in (ys or [])))
    th = TXT * k

    def best_line(horiz):
        vv = xs if horiz else ys
        cands = []
        if horiz:
            for f in (0.08, 0.92, 0.2, 0.8, 0.5, 0.35, 0.65, 0.04, 0.96, 0.14, 0.86):
                cands.append(y0 + (y1 - y0) * f)
        else:
            for f in (0.92, 0.08, 0.8, 0.2, 0.5, 0.65, 0.35, 0.96, 0.04, 0.86, 0.14):
                cands.append(x0 + (x1 - x0) * f)
        found = []
        for c in cands:
            if horiz:
                ln = LineString([(x0, c), (x1, c)]).intersection(shp)
            else:
                ln = LineString([(c, y0), (c, y1)]).intersection(shp)
            if ln.is_empty:
                continue
            if hasattr(ln, "geoms"):
                ln = max(ln.geoms, key=lambda g: g.length)
            b = ln.bounds
            lo, hi = (b[0], b[2]) if horiz else (b[1], b[3])
            if vv and (lo > min(vv) + 1 or hi < max(vv) - 1):
                continue            # the line must reach every fixture it binds
            sc = occ.overlap(ln.buffer(th * 1.3), ignore=("wallzone",))
            found.append((sc, c, ln))
        if not found:
            return None
        L = max(f[2].length for f in found)
        full = [f for f in found if f[2].length >= 0.97 * L]      # bind to the walls of the main body of the room
        return min(full, key=lambda f: f[0])

    if xs:
        bl = best_line(True)
        if bl:
            _, c, ln = bl
            b = ln.bounds
            vals = [b[0]] + [v for v in xs if b[0] + merge < v < b[2] - merge] + [b[2]]
            if len(vals) > 2:
                chain(sp, vals, c, c, k, occ, merge=merge)
    if ys:
        bl = best_line(False)
        if bl:
            _, c, ln = bl
            b = ln.bounds
            vals = [b[1]] + [v for v in ys if b[1] + merge < v < b[3] - merge] + [b[3]]
            if len(vals) > 2:
                chain(sp, vals, c, c, k, occ, vertical=True, merge=merge)
