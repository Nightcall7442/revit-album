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
          "wc": (0, 450, (252, 252, 252)), "basin": (300, 850, (250, 250, 250)), "washer": (0, 850, (250, 250, 250)),
          "desk": (0, 750, (196, 160, 118))}
SKIP = ("kitchen_upper", "upper", "sink", "hob", "mirror", "rail", "rug")


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
