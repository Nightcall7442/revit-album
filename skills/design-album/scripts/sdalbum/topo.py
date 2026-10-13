# -*- coding: utf-8 -*-
"""Plan topology helpers shared by autofix / propose / editor: which rooms an opening connects, free wall faces
of a room (no openings, no open edges), projecting a point onto a wall face, axis normals <-> 'X+'/'Y-' codes."""
import math
import re

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

CODES = {(1, 0): "X+", (-1, 0): "X-", (0, 1): "Y+", (0, -1): "Y-"}
NORM = {v: k for k, v in CODES.items()}

ROOM_CLASS = [
    (r"кухн|столов", "kitchen"),
    (r"сан\.?\s*уз|санузел|с/у|ванн|туалет|уборн|душев|wc|bath", "wet"),
    (r"прихож|коридор|холл|тамбур|хол\b|проход", "circulation"),
    (r"гардероб|кладов|постироч|техн", "storage"),
]


def room_class(name):
    s = (name or "").lower()
    for rx, cls in ROOM_CLASS:
        if re.search(rx, s):
            return cls
    return "living"


def normal_code(n):
    k = (int(round(n[0])), int(round(n[1])))
    return CODES.get(k)


def snap(v, step=5):
    return int(step * round(float(v) / step))


def opening_sides(P, o, probe=120):
    """[(room | None, normal pointing from the wall into that side)] for both faces of an opening."""
    w = P.wall_by_id[o["wall"]]
    x0, y0, x1, y1 = w["shape"].bounds
    out = []
    if w["dir"] == "H":
        for sgn, face in ((1, y1), (-1, y0)):
            p = (o["c"], face + sgn * probe)
            out.append((P.room_of_point(p, probe), (0, sgn), (o["c"], face)))
    else:
        for sgn, face in ((1, x1), (-1, x0)):
            p = (face + sgn * probe, o["c"])
            out.append((P.room_of_point(p, probe), (sgn, 0), (face, o["c"])))
    return out


def room_openings(P, room, kinds=("door", "balcony", "passage")):
    """Openings of the given kinds that lead into the room: [(opening, normal into the room, face point)]."""
    out = []
    for o in P.openings:
        if o["kind"] not in kinds:
            continue
        for r, n, fp in opening_sides(P, o):
            if r is not None and r["name"] == room["name"]:
                out.append((o, n, fp))
    return out


def _boundary_segments(poly):
    out = []
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        cs = list(ring.coords)
        for a, b in zip(cs[:-1], cs[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1:
                out.append(LineString([a, b]))
    return out


def inward(room, seg):
    (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
    L = math.hypot(bx - ax, by - ay) or 1.0
    n = (-(by - ay) / L, (bx - ax) / L)
    m = ((ax + bx) / 2.0, (ay + by) / 2.0)
    if not room["shp"].contains(Point(m[0] + n[0] * 20, m[1] + n[1] * 20)):
        n = (-n[0], -n[1])
    return n


def wall_faces(P, room, clear=0.0, kinds=("window", "door", "balcony", "passage")):
    """Free wall faces of a room: boundary minus open edges (separations, passages) and minus openings widened by
    `clear`. Returns [(LineString, inward normal)] with axis-aligned normals snapped."""
    holes = [P.open_shape[o["id"]].buffer(clear + 1, cap_style=3) for o in P.openings if o["kind"] in kinds]
    holes += [e.buffer(3) for e in P.open_edges()]
    cut = unary_union(holes) if holes else None
    out = []
    for seg in _boundary_segments(room["shp"]):
        n = inward(room, seg)
        parts = seg.difference(cut) if cut is not None else seg
        for g in (parts.geoms if hasattr(parts, "geoms") else [parts]):
            if g.is_empty or g.length < 1:
                continue
            if g.geom_type != "LineString":
                continue
            out.append((g, n))
    return out


def project_to_face(P, p, room=None, max_d=300.0, clear=0.0):
    """Nearest point on a free wall face of the room containing / nearest to p. -> (q, normal, room) or None."""
    room = room or P.room_of_point(p, max_d)
    if room is None:
        return None
    best = None
    pt = Point(p)
    for seg, n in wall_faces(P, room, clear):
        d = seg.distance(pt)
        if d <= max_d and (best is None or d < best[0]):
            q = seg.interpolate(seg.project(pt))
            best = (d, (q.x, q.y), n)
    if best is None:
        return None
    return best[1], best[2], room


def building_outline(P):
    return P.outline()


def is_entrance(P, o):
    """Door whose one side is outside the apartment (no room there and outside the outline)."""
    if o["kind"] not in ("door",):
        return False
    sides = opening_sides(P, o, probe=400)
    return any(r is None and not P.outline().buffer(-5).contains(Point(fp[0] + n[0] * 400, fp[1] + n[1] * 400))
               for r, n, fp in sides)


def furniture_shapes(P, kinds=None):
    from shapely.geometry import Polygon
    out = []
    for f in P.furniture:
        if kinds and f.get("kind") not in kinds:
            continue
        try:
            out.append((f, Polygon(f["poly"]).buffer(0)))
        except Exception:
            continue
    return out


def back_side(P, g, room):
    """Wall face a fixture stands against: (segment, inward normal, point on face opposite the fixture centre)."""
    best = None
    c = g.centroid
    for seg, n in wall_faces(P, room, 0.0, kinds=()):
        d = seg.distance(g)
        if d > 150:
            continue
        # overlap of the fixture projection with the segment
        x0, y0, x1, y1 = g.bounds
        if abs(n[0]) > 0.5:
            lo, hi = y0, y1
            s0, s1 = sorted((seg.coords[0][1], seg.coords[-1][1]))
        else:
            lo, hi = x0, x1
            s0, s1 = sorted((seg.coords[0][0], seg.coords[-1][0]))
        ov = min(hi, s1) - max(lo, s0)
        if ov <= 0:
            continue
        score = d - 0.01 * ov
        if best is None or score < best[0]:
            q = seg.interpolate(seg.project(c))
            best = (score, seg, n, (q.x, q.y))
    if best is None:
        return None
    return best[1], best[2], best[3]


def _line_parts(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if hasattr(g, "geoms"):
        out = []
        for x in g.geoms:
            out += _line_parts(x)
        return out
    return []


def room_entrances(P, room):
    """Ways into a room: doors / passages (openings), open edges (separations) and throats between bearing walls.
    -> [dict(kind, opening, ends=[point, point], n=normal into the room or None, other=room on the other side)]"""
    out = []
    for o, n, fp in room_openings(P, room, kinds=("door", "passage", "balcony")):
        w = P.wall_by_id[o["wall"]]
        a, b = o["c"] - o["w"] / 2.0, o["c"] + o["w"] / 2.0
        ends = [(a, fp[1]), (b, fp[1])] if w["dir"] == "H" else [(fp[0], a), (fp[0], b)]
        other = [r for r, nn, _ in opening_sides(P, o) if r is not None and r["name"] != room["name"]]
        out.append(dict(kind=o["kind"], opening=o, ends=ends, n=n, other=other[0] if other else None))
    shp = room["shp"].buffer(2)
    edges = [("open", LineString(s)) for s in P.separations] + [("throat", g.exterior) for g in getattr(P, "passages", [])]
    for kind, e in edges:
        for part in _line_parts(e.intersection(shp)):
            if part.length < 300:
                continue
            cs = list(part.coords)
            ends = [cs[0], cs[-1]]
            mid = part.interpolate(0.5, normalized=True)
            other = None
            for r in P.rooms:
                if r["name"] != room["name"] and r["shp"].buffer(2).intersection(part).length > 0.5 * part.length:
                    other = r
            if other is None and kind == "throat":
                for r in P.rooms:
                    if r["name"] != room["name"] and r["shp"].distance(mid) < 1200 and r["shp"].distance(part) < 600:
                        other = r
            out.append(dict(kind=kind, opening=None, ends=ends, n=None, other=other))
    return out


def beside_points(P, room, E, step=150.0, clear=30.0, min_free=110.0, reach=250.0):
    """Points on free wall faces of the room next to a corner / jamb E, `step` away from it (clamped to stay 75 mm
    off the far end of the face). Faces within `reach` count (the return wall at a jamb).
    -> [(point, inward normal, distance from E to the face)]"""
    out = []
    pE = Point(E)
    for seg, n in wall_faces(P, room, clear):
        if seg.distance(pE) > reach:
            continue
        L = seg.length
        s0 = seg.project(pE)
        if s0 < L / 2.0:
            avail = L - s0
            s = s0 + min(step, avail - 75.0)
        else:
            avail = s0
            s = s0 - min(step, avail - 75.0)
        if avail < min_free:
            continue
        q = seg.interpolate(s)
        out.append(((q.x, q.y), n, seg.distance(pE)))
    return out
