# -*- coding: utf-8 -*-
"""Colour axonometric 'dollhouse' of the project (walls cut at +1.45 m, floors, furniture blocks)."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

CUT = 1450
LIGHT = np.array([-0.45, -0.75, 0.85])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
FURN_H = {"bed": (0, 520, (245, 245, 243)), "nightstand": (0, 450, (196, 160, 118)), "wardrobe": (0, 2400, (238, 236, 232)),
          "cabinet": (0, 450, (196, 160, 118)), "tv_stand": (0, 450, (196, 160, 118)), "sofa": (0, 750, (170, 170, 175)),
          "armchair": (0, 750, (170, 170, 175)), "tv": (900, 1700, (40, 40, 42)), "kitchen_base": (0, 900, (240, 240, 238)),
          "fridge": (0, 2400, (240, 240, 238)), "table": (0, 750, (196, 160, 118)), "chair": (0, 460, (150, 150, 155)),
          "shoe_cabinet": (0, 900, (196, 160, 118)), "shower": (0, 40, (250, 250, 250)), "bath": (0, 550, (250, 250, 250)),
          "wc": (0, 450, (252, 252, 252)), "basin": (700, 850, (250, 250, 250)), "washer": (0, 850, (250, 250, 250)),
          "desk": (0, 750, (196, 160, 118)), "counter": (0, 1150, (120, 112, 104)), "heater": (1300, 2100, (250, 250, 250)),
          "sink": (0, 850, (240, 240, 238)), "coffee": (1100, 1550, (60, 60, 62)), "pos": (1100, 1400, (40, 40, 42))}
SKIP = ("kitchen_upper", "upper", "hob", "mirror", "rail", "rug")


def _rgb(c):
    return tuple(v / 255.0 for v in c)


def render(P, out_png, elev=48, azim=-58, dpi=260):
    faces = []

    def add(pts, col, edge=True):
        faces.append((np.array(pts, dtype=float), col, edge))

    def prism(poly, z0, z1, col):
        for p in (poly.geoms if hasattr(poly, "geoms") else [poly]):
            if p.is_empty or p.area < 10 or p.geom_type != "Polygon":
                continue
            p = p.simplify(2)
            ring = list(p.exterior.coords)[:-1]
            add([(x, y, z1) for x, y in ring], col)
            for a, b in zip(ring, ring[1:] + ring[:1]):
                add([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], col)
            for hole in p.interiors:
                hr = list(hole.coords)[:-1]
                for a, b in zip(hr, hr[1:] + hr[:1]):
                    add([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], col)

    def floor(g, col, step=350.0):
        for p in (g.geoms if hasattr(g, "geoms") else [g]):
            if p.is_empty:
                continue
            x0, y0, x1, y1 = p.bounds
            for xa in np.arange(x0, x1, step):
                for ya in np.arange(y0, y1, step):
                    c = p.intersection(box(xa, ya, xa + step, ya + step))
                    for q in (c.geoms if hasattr(c, "geoms") else [c]):
                        if q.geom_type == "Polygon" and q.area > 1:
                            add([(x, y, 0) for x, y in list(q.exterior.coords)[:-1]], col, False)

    zones = P.floor_zones()
    if zones:
        for f, g in zones:
            floor(g, _rgb((215, 217, 220)) if f.get("pattern") == "tile" else _rgb((214, 186, 146)))
    else:
        floor(unary_union([r["shp"] for r in P.rooms]), _rgb((214, 186, 146)))
    walls = unary_union([w["shape"] for w in P.walls if w["kind"] != "box"])
    doors = unary_union([P.open_shape[o["id"]] for o in P.openings if o["kind"] in ("door", "balcony", "passage")] or [Polygon()])
    wins = unary_union([P.open_shape[o["id"]] for o in P.openings if o["kind"] == "window"] or [Polygon()])
    wc = _rgb((236, 234, 230))
    prism(walls.difference(doors).difference(wins), 0, CUT, wc)
    prism(wins, 0, 900, wc)
    for f in P.furniture:
        kd = f.get("kind", "furn")
        if kd in SKIP:
            continue
        z0, z1, col = FURN_H.get(kd, (0, 400, (220, 220, 220)))
        if "z" in f:
            z0, z1 = f["z"]
        prism(Polygon(f["poly"]).buffer(0), z0, min(z1, CUT), _rgb(col))
    if not faces:
        return None
    fig = plt.figure(figsize=(9, 6.2))
    ax = fig.add_axes([0, 0, 1, 1], projection="3d")
    ax.set_proj_type("ortho")
    cols = []
    for pts, col, _ in faces:
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        nn = np.linalg.norm(n)
        kk = 1.0
        if nn > 1e-9:
            n = n / nn
            kk = 1.0 if abs(n[2]) > 0.9 else 0.62 + 0.38 * abs(float(n @ LIGHT))
        cols.append(tuple(min(1, c * kk) for c in col))
    edges = [(0.35, 0.35, 0.36, 0.55) if f[2] else c for f, c in zip(faces, cols)]
    ax.add_collection3d(Poly3DCollection([f[0] for f in faces], facecolors=cols, edgecolors=edges, linewidths=0.25))
    x0, y0, x1, y1 = P.bounds
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_zlim(0, 3200)
    ax.set_box_aspect((x1 - x0, y1 - y0, 3200))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.savefig(out_png, dpi=dpi, facecolor="white", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    from PIL import Image, ImageOps
    im = Image.open(out_png).convert("RGB")
    bb = ImageOps.invert(im).getbbox()
    if bb:
        im.crop((max(0, bb[0] - 10), max(0, bb[1] - 10), min(im.size[0], bb[2] + 10), min(im.size[1], bb[3] + 10))).save(out_png)
    return out_png


TILE_W, TILE_H = 600, 1200


def _fixture_dir(P, rooms, names):
    """Average inward normal of the walls the sanitary ware stands against: the camera looks at those walls."""
    from . import topo as T
    acc = np.zeros(2)
    for f in P.furniture:
        if f.get("room") not in names or f.get("kind") not in ("wc", "basin", "sink", "shower", "bath", "washer", "heater"):
            continue
        r = P.room_by_name.get(f["room"])
        back = T.back_side(P, Polygon(f["poly"]).buffer(0), r) if r else None
        if back is not None:
            acc += np.array(back[1], float)
    return acc / np.linalg.norm(acc) if np.linalg.norm(acc) > 1e-6 else None


def views_for(P, names):
    """Two azimuths looking at the walls with the fixtures from the two diagonals (default: -58 / 122)."""
    n = _fixture_dir(P, [P.room_by_name[x] for x in names if x in P.room_by_name], names)
    if n is None:
        return [-58.0, 122.0]
    a = float(np.degrees(np.arctan2(n[1], n[0])))
    return [a - 40.0, a + 40.0]


def render_rooms(P, names, out_png, elev=35, azim=-58, low=300):
    """Axonometric view of a few rooms (a WC block, a bathroom) on the depth-buffer renderer (raster3d): walls at
    full height with the 600×1200 tile layout on their inner faces, the walls between the viewer and the rooms cut
    at `low`, open glass door leaves, windows with glass, sanitary ware by its shape (wall-hung WC with a flush plate,
    console basin with a mirror). -> png path or None"""
    from shapely.geometry import LineString as _LS, Point as _Pt
    from . import raster3d, symbols as Y
    rooms = [P.room_by_name[n] for n in names if n in P.room_by_name]
    if not rooms:
        return None
    region = unary_union([r["shp"] for r in rooms])
    H = max(int(r.get("ceiling_level") or P.ceiling) for r in rooms)
    zone = region.buffer(320, join_style=2)
    cam = np.array([np.cos(np.radians(azim)), np.sin(np.radians(azim))])
    gc = np.array([region.centroid.x, region.centroid.y])
    faces = []

    def add(pts, col, edge=True):
        faces.append((np.array(pts, dtype=float), col, edge))

    tiled = []                                        # inner faces that get tiles: the wall face there is not drawn
    for r in rooms:
        cs = list(r["shp"].exterior.coords)
        for a, b in zip(cs[:-1], cs[1:]):
            mid = np.array([(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0])
            if float(np.hypot(b[0] - a[0], b[1] - a[1])) >= 50 and float((mid - gc) @ cam) <= 0:
                tiled.append((_LS([a, b]), r))

    def prism(poly, z0, z1, col, skip_tiled=False, edge=True):
        for p in (poly.geoms if hasattr(poly, "geoms") else [poly]):
            if p.is_empty or p.area < 10 or p.geom_type != "Polygon" or z1 <= z0:
                continue
            p = p.simplify(1)
            ring = list(p.exterior.coords)[:-1]
            add([(x, y, z1) for x, y in ring], col, edge)
            for a, b in zip(ring, ring[1:] + ring[:1]):
                if skip_tiled:
                    m = _Pt((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                    if any(t.distance(m) < 3 for t, _ in tiled):
                        continue
                add([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], col, edge)
    # floor tiles 600×600
    fl = _rgb((208, 210, 215))
    for r in rooms:
        x0, y0, x1, y1 = r["shp"].bounds
        for xa in np.arange(x0, x1, 600):
            for ya in np.arange(y0, y1, 600):
                c = r["shp"].intersection(box(xa, ya, xa + 600, ya + 600))
                for q in (c.geoms if hasattr(c, "geoms") else [c]):
                    if q.geom_type == "Polygon" and q.area > 1:
                        add([(x, y, 0) for x, y in list(q.exterior.coords)[:-1]], fl, True)
    wall_col, part_col = _rgb((232, 232, 235)), _rgb((246, 246, 248))
    ops = [(o, P.open_shape[o["id"]]) for o in P.openings]
    for w in P.walls:
        if w["kind"] == "box":
            continue
        g = w["shape"].intersection(zone)
        if g.is_empty or g.area < 100:
            continue
        c = np.array([g.centroid.x, g.centroid.y])
        front = float((c - gc) @ cam) > 0 and not region.buffer(-5).intersects(g)
        top = low if front else H
        col = part_col if w["kind"] == "new" else wall_col
        solid = g
        for o, sh in ops:
            if not sh.intersects(g):
                continue
            part = sh.intersection(g)
            solid = solid.difference(sh)
            if o["kind"] == "window":
                s0, s1 = o.get("sill", 900), o.get("sill", 900) + o["h"]
                prism(part, 0, min(s0, top), col, True)
                if s1 < top:
                    prism(part, s1, top, col, True)
            elif o["kind"] in ("door", "balcony") and o["h"] < top:
                prism(part, o["h"], top, col, True)
        prism(solid, 0, top, col, not front)
    # wall tiles on the inner faces kept at full height (1.5 mm off the face), none in the openings
    tile = _rgb((244, 242, 238))
    for seg, r in tiled:
        (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
        L = seg.length
        u = ((bx - ax) / L, (by - ay) / L)
        nrm = (-u[1], u[0])
        mid = ((ax + bx) / 2.0, (ay + by) / 2.0)
        if not r["shp"].contains(_Pt(mid[0] + nrm[0] * 20, mid[1] + nrm[1] * 20)):
            nrm = (u[1], -u[0])
        off = (nrm[0] * 1.5, nrm[1] * 1.5)
        holes = []                                    # openings in this face, in (s, z) of the face
        for o, sh in ops:
            if sh.buffer(30).intersection(seg).length < 20:
                continue
            ss_ = sorted(((x - ax) * u[0] + (y - ay) * u[1]) for x, y in list(sh.exterior.coords)[:-1])
            lo = o.get("sill", 0) if o["kind"] == "window" else 0
            holes.append(box(max(0.0, ss_[0]), lo, min(L, ss_[-1]), lo + o["h"]))
        hole_u = unary_union(holes) if holes else None
        for s0 in np.arange(0, L, TILE_W):
            s1 = min(L, s0 + TILE_W)
            for z0 in np.arange(0, H, TILE_H):
                z1 = min(H, z0 + TILE_H)
                q = box(s0, z0, s1, z1)
                if hole_u is not None:
                    q = q.difference(hole_u)
                for piece in (q.geoms if hasattr(q, "geoms") else [q]):
                    if piece.is_empty or piece.geom_type != "Polygon" or piece.area < 1:
                        continue
                    add([(ax + u[0] * sv + off[0], ay + u[1] * sv + off[1], zv)
                         for sv, zv in list(piece.exterior.coords)[:-1]], tile, True)
    glass = _rgb((176, 204, 226))
    for o, sh in ops:
        if not sh.intersects(zone.buffer(-200)):
            continue
        x0, y0, x1, y1 = sh.bounds
        if o["kind"] == "window":
            z0, z1 = o.get("sill", 900), o.get("sill", 900) + o["h"]
            if (x1 - x0) >= (y1 - y0):
                yc = (y0 + y1) / 2.0
                add([(x0, yc, z0), (x1, yc, z0), (x1, yc, z1), (x0, yc, z1)], glass, True)
            else:
                xc = (x0 + x1) / 2.0
                add([(xc, y0, z0), (xc, y1, z0), (xc, y1, z1), (xc, y0, z1)], glass, True)
        elif o["kind"] == "door" and o.get("swing"):
            try:
                hinge, cdir, odir, Lf, fr = Y.door_geom(P, o)
            except Exception:
                continue
            hx, hy = hinge
            ex, ey = hx + odir[0] * Lf, hy + odir[1] * Lf
            t = (cdir[0] * 20, cdir[1] * 20)
            leaf = Polygon([(hx, hy), (ex, ey), (ex + t[0], ey + t[1]), (hx + t[0], hy + t[1])])
            if leaf.intersects(region.buffer(-20)):
                prism(leaf, 0, o["h"] - 30, glass)
    from . import topo as T
    white = _rgb((252, 252, 252))
    for f in P.furniture:
        if f.get("room") not in names or f.get("kind") in SKIP:
            continue
        kd = f.get("kind", "furn")
        g = Polygon(f["poly"]).buffer(0)
        r = P.room_by_name.get(f["room"])
        back = T.back_side(P, g, r) if r is not None and kd in ("wc", "basin") else None
        if kd == "wc" and back is not None:
            seg, n, q = back
            x0, y0, x1, y1 = g.bounds
            w_ = (x1 - x0) if abs(n[1]) > 0.5 else (y1 - y0)
            d_ = (y1 - y0) if abs(n[1]) > 0.5 else (x1 - x0)
            t = (-n[1], n[0])
            pts = [(q[0] + t[0] * w_ / 2, q[1] + t[1] * w_ / 2)]
            for k_ in range(0, 13):                     # rounded front of the bowl
                ang = np.pi * k_ / 12.0
                pts.append((q[0] + t[0] * np.cos(ang) * w_ / 2 + n[0] * (d_ * 0.35 + np.sin(ang) * d_ * 0.65),
                            q[1] + t[1] * np.cos(ang) * w_ / 2 + n[1] * (d_ * 0.35 + np.sin(ang) * d_ * 0.65)))
            pts.append((q[0] - t[0] * w_ / 2, q[1] - t[1] * w_ / 2))
            bowl = Polygon(pts).buffer(0)
            z0 = 230 if f.get("hung") else 0
            prism(bowl, z0, 410, white, edge=False)
            prism(bowl, 410, 430, white)
            if f.get("hung"):
                pc = (q[0] + n[0] * 2, q[1] + n[1] * 2)
                add([(pc[0] - t[0] * 120, pc[1] - t[1] * 120, 780), (pc[0] + t[0] * 120, pc[1] + t[1] * 120, 780),
                     (pc[0] + t[0] * 120, pc[1] + t[1] * 120, 930), (pc[0] - t[0] * 120, pc[1] - t[1] * 120, 930)],
                    _rgb((70, 70, 74)), True)
            continue
        if kd == "basin" and back is not None:
            seg, n, q = back
            prism(g, 820, 860, white)
            prism(g.buffer(-max(20.0, min(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) * 0.2)), 650, 820, white, edge=False)
            x0, y0, x1, y1 = g.bounds
            w_ = (x1 - x0) if abs(n[1]) > 0.5 else (y1 - y0)
            t = (-n[1], n[0])
            pc = (q[0] + n[0] * 3, q[1] + n[1] * 3)
            add([(pc[0] - t[0] * w_ / 2, pc[1] - t[1] * w_ / 2, 1100), (pc[0] + t[0] * w_ / 2, pc[1] + t[1] * w_ / 2, 1100),
                 (pc[0] + t[0] * w_ / 2, pc[1] + t[1] * w_ / 2, 1700), (pc[0] - t[0] * w_ / 2, pc[1] - t[1] * w_ / 2, 1700)],
                glass, True)
            continue
        z0, z1, col = FURN_H.get(kd, (0, int(f.get("h") or 400), (220, 220, 220)))
        if "z" in f:
            z0, z1 = f["z"]
        prism(g, z0, min(z1, H), _rgb(col))
    if not faces:
        return None
    return raster3d.render(faces, out_png, elev=elev, azim=azim, width=1500)


# ------------------------------------------------------------------ 3D view with the models of the scene
def _poly_tris(poly, z):
    """Shapely polygon (holes allowed) -> triangles at height z (constrained Delaunay, inside only)."""
    from shapely.geometry import Polygon as _Pg
    out = []
    for p in (poly.geoms if hasattr(poly, "geoms") else [poly]):
        if p.is_empty or p.geom_type != "Polygon" or p.area < 10:
            continue
        try:
            from shapely import constrained_delaunay_triangles
            tri = constrained_delaunay_triangles(p)
            ts = list(tri.geoms)
        except Exception:
            from shapely.ops import triangulate
            ts = [t for t in triangulate(p) if p.contains(t.representative_point())]
        for t in ts:
            cs = list(t.exterior.coords)[:3]
            out.append([(x, y, z) for x, y in cs])
    return out


def _prism_tris(poly, z0, z1):
    T = _poly_tris(poly, z1)
    for p in (poly.geoms if hasattr(poly, "geoms") else [poly]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        for ring in [p.exterior] + list(p.interiors):
            cs = list(ring.coords)
            for a, b in zip(cs[:-1], cs[1:]):
                T.append([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)])
                T.append([(a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)])
    return T


def render_models(P, out_png, d=None, elev=40.0, azim=-58.0, width=1900, cut=CUT):
    """The dollhouse with the real furniture of the scene: the item meshes (also of the bought pieces that have no
    sketch) at their places, the rest as blocks; floors coloured by zone, boxes, walls cut at +1.45."""
    from . import items3d, raster3d
    from shapely import affinity
    T, C = [], []

    def add(tris, rgb):
        if not len(tris):
            return
        T.extend(tris)
        C.extend([tuple(c / 255.0 for c in rgb)] * len(tris))
    try:
        from .sheets_plans import floor_tints
        tints = floor_tints(P)
    except Exception:
        tints = {}
    zones = P.floor_zones()
    for f, g in zones:
        add(_poly_tris(g, 0.0), tints.get(f["id"], (215, 217, 220)))
    if not zones:
        add(_poly_tris(unary_union([r["shp"] for r in P.rooms]), 0.0), (214, 186, 146))
    walls = unary_union([w["shape"] for w in P.walls if w["kind"] != "box"])
    doors = unary_union([P.open_shape[o["id"]] for o in P.openings if o["kind"] in ("door", "balcony", "passage")] or [Polygon()])
    wins = unary_union([P.open_shape[o["id"]] for o in P.openings if o["kind"] == "window"] or [Polygon()])
    add(_prism_tris(walls.difference(doors).difference(wins), 0.0, cut), (236, 234, 230))
    add(_prism_tris(wins, 0.0, 900.0), (236, 234, 230))
    for b in P.boxes:
        shp = b["shape"].difference(P.mass)
        rgb = (150, 52, 58) if b.get("box") in ("seat", "column", "pipe", "install") else (120, 112, 104)
        add(_prism_tris(shp, 0.0, min(cut, b.get("h", 1200))), rgb)
    covered = []
    items = list((d or {}).get("items") or P.d.get("items") or []) + list((d or {}).get("_items_bought") or P.d.get("_items_bought") or [])
    for it in items:
        if it.get("kind") in ("chandelier", "sconce") or (it.get("z0") or 0) > cut:
            continue
        try:
            m = items3d.load(P, it)
        except Exception:
            m = None
        if m is None or not it.get("places"):
            continue
        tr, cols, _ = m.tris(props=True, colour=True)
        if not len(tr):
            continue
        if len(tr) > 60000:                     # thin dense meshes for the overview
            sel = np.linspace(0, len(tr) - 1, 60000).astype(int)
            tr, cols = tr[sel], cols[sel]
        for pl in it["places"]:
            x, y = pl[0], pl[1]
            a = np.radians(pl[2] if len(pl) > 2 else 0.0)
            R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            t2 = tr.copy()
            t2[:, :, :2] = t2[:, :, :2] @ R.T + np.array([x, y])
            t2[:, :, 2] += (it.get("z0") or 0)
            keep = t2[:, :, 2].min(1) <= cut
            T.extend(t2[keep])
            C.extend([tuple(c) for c in cols[keep]])
            try:
                covered.append(affinity.translate(affinity.rotate(Polygon(it.get("foot") or [(-it["size"][0] / 2, -it["size"][1] / 2),
                    (it["size"][0] / 2, -it["size"][1] / 2), (it["size"][0] / 2, it["size"][1] / 2), (-it["size"][0] / 2, it["size"][1] / 2)]),
                    np.degrees(a), origin=(0, 0)), x, y).buffer(0))
            except Exception:
                pass
    cov = unary_union(covered) if covered else Polygon()
    for f in P.furniture:                        # what the models do not cover: blocks
        kd = f.get("kind", "furn")
        if kd in SKIP:
            continue
        g = Polygon(f["poly"]).buffer(0)
        if not cov.is_empty and g.intersection(cov).area > 0.5 * g.area:
            continue
        if kd == "counter" and any(b.get("box") == "bar" for b in P.boxes):
            continue
        z0, z1, col = FURN_H.get(kd, (0, 400, (220, 220, 220)))
        if "z" in f:
            z0, z1 = f["z"]
        add(_prism_tris(g, z0, min(z1, cut)), col)
    if not T:
        return None
    raster3d.render_painter(np.asarray(T, float), np.asarray(C, float), out_png, elev=elev, azim=azim, width=width, ss=2,
                            margin=0.02, edge_rgb=(90, 90, 92), crop=True)
    return out_png
