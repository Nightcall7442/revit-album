# -*- coding: utf-8 -*-
"""Objects of the 3D scene on the elevations: the meshes kept at import (import/elev_meshes.npz, see
importers/scene_elev.py) projected on the plane of a wall, seen from the room.

A triangle of an object is taken when the object stands at the wall (its nearest point within DEPTH of the wall face,
in front of it) - mouldings, panels, cabinets, curtains, wall lights, radiators; free-standing furniture in the room
is not. Its triangles are rasterised on a PX mm grid in (s along the wall, z up) and the filled area is traced into
polygons with holes (a moulding frame stays a frame), simplified to 3 mm.
"""
import json
import math
import os

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

DEPTH = 300.0          # an object is «at the wall» when it comes this close to the face (curtains hang 100-250 off)
BEHIND = 60.0          # tolerance behind the face (model noise, objects let into the wall)
PX = 4.0               # raster step, mm
_CACHE = {}

STYLE = {               # fill, outline (rgb) of a category on the elevation
    "molding": ((250, 250, 248), (60, 60, 60)), "curtain": ((236, 232, 224), (120, 112, 100)),
    "mirror": ((214, 226, 236), (70, 90, 110)), "light": ((255, 246, 214), (150, 110, 40)),
    "tv": ((60, 60, 64), (30, 30, 30)), "radiator": ((245, 245, 245), (150, 40, 40)),
    "art": ((236, 230, 220), (90, 80, 70)), "furniture": ((232, 226, 216), (70, 66, 62)),
    "seating": ((232, 226, 216), (70, 66, 62)),
    "other": ((238, 236, 232), (80, 80, 84)),
}


def load(P):
    """[(name, cat, V (n, 3) plan mm, F (m, 3))] of the project's scene meshes, [] when there are none."""
    rel = (P.meta or {}).get("elev_meshes")
    if not rel:
        return []
    path = rel if os.path.isabs(rel) else os.path.join(P.base_dir or ".", rel)
    if not os.path.isfile(path):
        return []
    sh = (P.meta or {}).get("scene_shift") or [0, 0]
    key = (os.path.abspath(path), tuple(sh))
    if key not in _CACHE:
        z = np.load(path)
        names = json.loads(str(z["names"]))
        cats = json.loads(str(z["cats"]))
        out = []
        for i, (n, c) in enumerate(zip(names, cats)):
            v = z["v%d" % i].astype(float)
            v[:, 0] += sh[0]
            v[:, 1] += sh[1]
            out.append((n, c, v, z["f%d" % i]))
        _CACHE.clear()
        _CACHE[key] = out
    return _CACHE[key]


def _raster_polys(tri_sz, s_lim, z_lim):
    """Triangles in (s, z) -> polygons with holes of their union (PX raster, traced)."""
    from PIL import Image, ImageDraw
    import contourpy
    s0 = max(s_lim[0], float(tri_sz[:, :, 0].min())) - 2 * PX
    s1 = min(s_lim[1], float(tri_sz[:, :, 0].max())) + 2 * PX
    z0 = max(z_lim[0], float(tri_sz[:, :, 1].min())) - 2 * PX
    z1 = min(z_lim[1], float(tri_sz[:, :, 1].max())) + 2 * PX
    if s1 - s0 < 2 * PX or z1 - z0 < 2 * PX:
        return []
    w, h = int(math.ceil((s1 - s0) / PX)) + 1, int(math.ceil((z1 - z0) / PX)) + 1
    if w * h > 6e6:                                   # a huge object: coarser grid, same outline
        f = math.sqrt(w * h / 6e6)
        return _raster_scaled(tri_sz, s0, z0, s1, z1, PX * f)
    return _trace(tri_sz, s0, z0, w, h, PX)


def _raster_scaled(tri_sz, s0, z0, s1, z1, px):
    w, h = int(math.ceil((s1 - s0) / px)) + 1, int(math.ceil((z1 - z0) / px)) + 1
    return _trace(tri_sz, s0, z0, w, h, px)


def _trace(tri_sz, s0, z0, w, h, px):
    from PIL import Image, ImageDraw
    import contourpy
    img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(img)
    pts = (tri_sz - np.array([s0, z0])) / px
    for t in pts:
        dr.polygon([(float(t[0][0]), float(t[0][1])), (float(t[1][0]), float(t[1][1])), (float(t[2][0]), float(t[2][1]))],
                   fill=255, outline=255)
    a = np.asarray(img, dtype=float)
    if a.max() <= 0:
        return []
    a = np.pad(a, 1)
    gen = contourpy.contour_generator(z=a, fill_type=contourpy.FillType.OuterOffset)
    polys = []
    filled, offsets = gen.filled(127.5, 1e9)
    for pts_, offs in zip(filled, offsets):
        rings = [pts_[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
        if not rings or len(rings[0]) < 4:
            continue
        conv = [[(s0 + (x - 1) * px, z0 + (y - 1) * px) for x, y in r] for r in rings]
        g = Polygon(conv[0], [r for r in conv[1:] if len(r) >= 4]).buffer(0)
        if not g.is_empty:
            polys.append(g)
    return polys


def project(P, E, room_shp, H, depth=DEPTH):
    """Scene objects at the wall of elevation E (room on its right): [dict(name, cat, depth, geom (s, z polygon))],
    far ones first (nearer objects are drawn over them)."""
    meshes = load(P)
    if not meshes:
        return []
    ux = E.ux
    n = (-ux[1], ux[0])
    mid = ((E.a[0] + E.b[0]) / 2.0, (E.a[1] + E.b[1]) / 2.0)
    from shapely.geometry import Point
    if not room_shp.contains(Point(mid[0] + n[0] * 50, mid[1] + n[1] * 50)):
        n = (-n[0], -n[1])
    out = []
    room_area = room_shp.area
    import re as _re
    seat = _re.compile(r"sofa|диван|chair|стул|кресл|armchair|bed|кроват|pouf|пуф|ottoman", _re.I)
    for name, cat, V, F in meshes:
        if cat == "seating" or seat.search(name):     # loose furniture is not on the elevations of the walls
            continue
        zx = float(V[:, 2].max() - V[:, 2].min())
        fx = (V[:, 0].max() - V[:, 0].min()) * (V[:, 1].max() - V[:, 1].min())
        if zx < 300 and fx > 0.3 * room_area:            # a floor build-up / rug under the room: not on the wall
            continue
        s = (V[:, 0] - E.a[0]) * ux[0] + (V[:, 1] - E.a[1]) * ux[1]
        d = (V[:, 0] - E.a[0]) * n[0] + (V[:, 1] - E.a[1]) * n[1]
        if s.max() < 0 or s.min() > E.L:
            continue
        front = d >= -BEHIND
        if not front.any():
            continue
        dmin = float(d[front].min())
        if dmin > depth:
            continue
        # inside the room: the object's plan points in front of this wall lie in the room (not behind a corner)
        inside = [room_shp.buffer(250).contains(Point(float(x), float(y))) for x, y in V[front][:: max(1, int(front.sum() // 40)), :2]]
        if sum(inside) < 0.5 * len(inside):
            continue
        ss_ = np.clip(s, 0, E.L)
        if len(F) <= 48 and ss_.max() - ss_.min() >= 0.8 * E.L and zx >= 0.7 * H:
            continue                                     # a plain box over the whole wall is a wall, not a thing on it
        tri = F[np.all(front[F], axis=1)]
        if not len(tri):
            continue
        sz = np.stack([s, V[:, 2]], axis=1)[tri]
        polys = _raster_polys(sz, (-50.0, E.L + 50.0), (-10.0, H + 10.0))
        g = unary_union(polys).simplify(3.0, preserve_topology=True) if polys else None
        if g is None or g.is_empty or g.area < 900.0:
            continue
        out.append(dict(name=name, cat=cat, depth=round(dmin), geom=g))
    out.sort(key=lambda x: -x["depth"])
    return out


def items(P, E, room_shp, H, depth=DEPTH):
    """Elevation items («poly» with holes) of the scene objects at the wall, for project.json."""
    out = []
    for o in project(P, E, room_shp, H, depth):
        fill, edge = STYLE.get(o["cat"], STYLE["other"])
        for part in getattr(o["geom"], "geoms", [o["geom"]]):
            if part.geom_type != "Polygon" or part.area < 900.0:
                continue
            out.append(dict(type="poly", src=o["name"], cat=o["cat"], depth=o["depth"],
                            pts=[[round(x), round(y)] for x, y in list(part.exterior.coords)[:-1]],
                            holes=[[[round(x), round(y)] for x, y in list(r.coords)[:-1]] for r in part.interiors
                                   if Polygon(r).area >= 400.0],
                            rgb=list(fill), edge=list(edge)))
    return out


def dims_of(items_, L, H, max_n=24):
    """Extra dimension points of the scene items on an elevation: the outer edges of every frame / front / mirror
    (a cladding over most of the wall is not dimensioned along that direction). Too many (a dense pattern) - none:
    the frames are dimensioned on a fragment."""
    ss, zs = set(), set()
    shapes = []
    for it in items_:
        if not it.get("src") or it.get("cat") not in ("molding", "furniture", "mirror", "art", "other", "radiator"):
            continue
        g = Polygon(it["pts"]).buffer(0)
        x0, y0, x1, y1 = g.bounds
        if (x1 - x0) >= 0.85 * L and (y1 - y0) >= 0.85 * H:      # a cladding over the wall: its edges are the wall's
            continue
        shapes.append(g)
    # nested profiles of one frame, a front and its handle: one group, dimensioned by its outer edges
    groups = unary_union([g.buffer(15) for g in shapes]) if shapes else Polygon()
    for g in getattr(groups, "geoms", [groups]):
        if g.is_empty:
            continue
        x0, y0, x1, y1 = g.buffer(-15).bounds if not g.buffer(-15).is_empty else g.bounds
        w, h = x1 - x0, y1 - y0
        if w < 150 and h < 150:
            continue
        if w < 0.85 * L:
            ss.update(int(round(v / 5.0) * 5) for v in (x0, x1) if 20 < v < L - 20)
        if h < 0.85 * H:
            zs.update(int(round(v / 5.0) * 5) for v in (y0, y1) if 20 < v < H - 20)

    def thin(vals, step=30):
        out = []
        for v in sorted(vals):
            if not out or v - out[-1] >= step:
                out.append(v)
        return out
    ss, zs = thin(ss), thin(zs)
    return (ss if len(ss) <= max_n else []), (zs if len(zs) <= max_n else [])
