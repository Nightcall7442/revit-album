# -*- coding: utf-8 -*-
"""Floor coverings and boxes of a 3D scene -> evidence for the senior decisions (all in mm, scene coordinates).

    floors(rows, meshes, k)          -> [{name, material, tile [long, short] | None, tile_name, z, area, polys, origin}]
    boxes(rows, walls_rects)         -> [{kind: column | pipe | low, name, rect, z0, z1, material, inner?}]

A floor covering is a tiled object lying on the floor: a FloorGenerator object (its tile size is read from the
modifier) or an object whose material names a format ("CORD 120x60"). Splines (an outline the covering is generated
on) are polygonized; flat meshes give their horizontal faces; Plane primitives their footprint. The biggest covering
is the base, the others lie over it (a strip of other tiles, a zone at the bar).

Boxes are solids standing on the floor that are not walls: a cladding around a free-standing column, a narrow
full-height shaft at a wall (pipes), a low solid against a wall (installation box, seating base). What each is for
is decided by the senior from the room and the fixtures around it.
"""
import math
import re

import numpy as np

TILE_RX = re.compile(r"(?<![\d.])(\d{2,4})\s*[xх×*]\s*(\d{2,4})(?![\d.])", re.I)
GENERIC_MAT = re.compile(r"(?i)^\s*(material\s*#?\s*-?\d*|\d+\s*-\s*default|default|standard|mat\s*\d*|\d+)\s*$")
NOT_FLOOR = re.compile(r"(?i)carpet|rug|ковер|ковёр|doormat|plinth|плинтус|skirting|step|ступен|stair|лестн")
NOT_BOX = re.compile(
    r"(?i)light|lamp|spot|track|plant|pot\b|vase|decor|door|curtain|blind|fridge|hicold|cabinet|wardrobe|shelf|rack|"
    r"sofa|chair|table|stool|bench|desk|counter|bar|mirror|tv|console|radiator|heater|boiler|conditioner|"
    r"шкаф|стелл|диван|стул|стол|кресл|зеркал")


def tile_from_name(name):
    """'CORD 120x60' -> [1200, 600]; sizes <= 200 are centimetres (60x120, 30x60, 10x10), larger are millimetres."""
    m = TILE_RX.search(name or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if max(a, b) <= 200:
        a, b = a * 10, b * 10
    if min(a, b) < 20 or max(a, b) > 3200:
        return None
    return [max(a, b), min(a, b)]


def generic_material(name):
    return not name or bool(GENERIC_MAT.match(name))


TEX_TILE_RX = re.compile(r"(?<!\d)(\d{2,3})\s*[-xх×_ ]\s*(\d{2,3})(?!\d)")
GENERIC_DIR = re.compile(r"(?i)^(tex+|textures?|maps?|map|materials?|images?|bitmaps?|\d+)$")
COLORS = ("burgundy", "bordeaux", "white", "black", "beige", "grey", "gray", "green", "blue", "red", "terracotta", "brown",
          "cream", "ivory", "sand", "graphite", "anthracite", "olive", "pink", "ochre", "taupe")
KIND_RX = [("brick", re.compile(r"(?i)brick|кирпич")),
           ("loft", re.compile(r"(?i)loft")),
           ("plaster", re.compile(r"(?i)plaster|stucco|штукат|microcem|микроцем|betonka|tadelakt|venet")),
           ("concrete", re.compile(r"(?i)concrete|бетон")),
           ("wood", re.compile(r"(?i)\boak|wood|veneer|дуб|шпон")),
           ("tile", re.compile(r"(?i)tile|плитк|ceramic|керам|porcelain|mosaic|мозаик|artisan|cord|60x120|120x60"))]


def tex_info(r):
    """What the textures of an object's material say: {kind, label, tile}. Files like
    '22.EQUIPE ARTISAN/full_artisan-burgundy-24457-132-132.jpeg' -> tile 132×132 'Equipe Artisan Burgundy'."""
    tex = r.get("tex") or []
    if not tex:
        return {}
    names = [t.split("/")[-1] for t in tex]
    dirs = [x for t in tex for x in t.split("/")[:-1]]
    main = [n for n in names if not re.search(r"(?i)bump|normal|nrm|gloss|refl|spec|rough|disp|height|mask|opac|ao\b|ambient|fresnel|ior", n)]
    pool = main or names
    tiles = []
    for n in pool:
        m = TEX_TILE_RX.search(re.sub(r"\(\d+\)", "", n))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            k = 10 if (a % 5 == 0 and b % 5 == 0 and max(a, b) <= 200) else 1      # 120x60 cm / 132-132 mm
            tiles.append((max(a, b) * k, min(a, b) * k))
    tile = list(max(set(tiles), key=tiles.count)) if tiles else None
    kind = "tile" if tile else None          # a format in the texture's name: a tile whatever else is mixed in
    blob = " ".join(names + dirs)
    for kd, rx in KIND_RX:
        if kind is None and rx.search(blob):
            kind = kd
    mix = kind == "brick" and bool(dict(KIND_RX)["plaster"].search(blob))
    if mix:                                  # a multi-material plaster / brick: plaster with brick parts
        kind = "plaster"
    brand = ""
    low = " ".join(names).lower().replace("_", " ").replace("-", " ")
    for dname in dirs:                       # a folder naming the product: one of its words is in the file names too
        dn = re.sub(r"^[\d.\s_-]+", "", dname).strip()
        if dn and not GENERIC_DIR.match(dn) and any(len(w) >= 4 and w.lower() in low for w in re.findall(r"\w+", dn)):
            brand = dn.title()
            break
    color = next((c for c in COLORS if re.search(r"(?i)\b%s\b" % c, " ".join(pool).replace("_", " ").replace("-", " "))), "")
    label = " ".join(x for x in (brand, color.title()) if x)
    return dict(kind=kind, label=label, tile=list(tile) if tile else None, brick_mix=mix)


def _mats(r):
    return list(r.get("materials") or ([r["material"]] if r.get("material") else []))


def _faces_of_lines(lines):
    """Spline segments -> polygons of the faces they close (columns inside give holes of their own faces)."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union
    segs = []
    for ln in lines:
        p = [tuple(q) for q in ln["p"]]
        if ln.get("closed") and len(p) > 2:
            p = p + [p[0]]
        if len(p) >= 2:
            segs.append(LineString(p))
    if not segs:
        return []
    faces = [g for g in polygonize(unary_union(segs)) if g.area > 0.5e6]
    if not faces:                                   # endpoints not quite joined: faces of the 5 mm thickened lines
        thick = unary_union([s.buffer(5, cap_style=2) for s in segs])
        for g in (thick.geoms if hasattr(thick, "geoms") else [thick]):
            for ring in getattr(g, "interiors", []):
                f = Polygon(ring).buffer(5, join_style=2)
                if f.area > 0.5e6:
                    faces.append(f)
    return faces


def _horizontal_faces(v, faces):
    """Faces of a mesh looking up or down, projected to the plan."""
    from shapely.geometry import Polygon
    out = []
    for f in faces:
        idx = f[1] if isinstance(f, tuple) else f
        if len(idx) < 3 or max(idx) >= len(v):
            continue
        p = v[idx]
        if np.ptp(p[:, 2]) > 5:
            continue
        g = Polygon(p[:, :2]).buffer(0)
        if g.area > 1:
            out.append(g)
    return out


def floors(rows, meshes, k):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for r in rows:
        nm = r.get("name") or ""
        if NOT_FLOOR.search(nm):
            continue
        mats = _mats(r)
        fg = "FloorGenerator" in (r.get("mods") or [])
        named = next((t for t in (tile_from_name(m) for m in mats) if t), None)
        if not (fg or named):
            continue
        z, geoms = None, []
        if r.get("lines"):
            z = r.get("lines_z", 0.0)
            geoms = _faces_of_lines(r["lines"])
        elif r.get("bbox") and r.get("idx") in meshes:
            (x0, y0, z0), (x1, y1, z1) = r["bbox"]
            if z1 - z0 > 40:
                continue
            z = (z0 + z1) / 2.0
            _, vw, faces = meshes[r["idx"]]
            geoms = _horizontal_faces(np.asarray(vw, float) * k, faces)
        elif r.get("footprint") and r.get("class") == "Plane" and abs((r.get("z1") or 0) - (r.get("z0") or 0)) < 1:
            z = r.get("z0") or 0.0
            geoms = [Polygon(r["footprint"]).buffer(0)]
        if z is None or abs(z) > 100 or not geoms:
            continue
        g = unary_union(geoms)
        if g.area < 0.3e6:
            continue
        tile = sorted(r["fg_tile"], reverse=True) if r.get("fg_tile") else named
        polys = [[[round(x), round(y)] for x, y in list(p.exterior.coords)[:-1]]
                 for p in (g.geoms if hasattr(g, "geoms") else [g]) if p.area > 0.1e6]
        x0, y0, _, _ = g.bounds
        ti = tex_info(r)
        out.append(dict(name=nm, material=next((m for m in mats if not generic_material(m)), mats[0] if mats else ""),
                        tile=[round(t) for t in tile] if tile else None, tile_name=named or ti.get("tile"), z=round(z, 1),
                        area=round(g.area / 1e6, 2), polys=polys, origin=[round(x0), round(y0)],
                        fg=fg, label=ti.get("label", ""), tex_kind=ti.get("kind")))
    # one covering modelled twice (a spline and its copy on another layer): keep the first
    keep = []
    for f in sorted(out, key=lambda f: -f["area"]):
        g = unary_union([Polygon(p).buffer(0) for p in f["polys"]])
        dup = False
        for o in keep:
            go = unary_union([Polygon(p).buffer(0) for p in o["polys"]])
            if o["material"] == f["material"] and g.symmetric_difference(go).area < 0.05 * max(g.area, go.area):
                dup = True
                break
        if not dup:
            keep.append(f)
    for i, f in enumerate(keep):
        f["kind"] = "base" if i == 0 else "overlay"
    return keep


def _rect_of(r):
    if r.get("bbox"):
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        return [x0, y0, x1, y1], z0, z1
    if r.get("footprint") and r.get("z0") is not None:
        xs = [p[0] for p in r["footprint"]]
        ys = [p[1] for p in r["footprint"]]
        return [min(xs), min(ys), max(xs), max(ys)], r["z0"], r["z1"]
    return None


def _gap(a, b):
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def boxes(rows, walls, ledges=(), skip_names=()):
    """walls: draft walls (rect, source); ledges: wall parts standing proud under a window (the wall is the part
    above). Boxes are evidence only: the senior keeps those it can explain."""
    narrow = {lg["wall"]: lg["wall_rect"] for lg in ledges or []}
    wrects = [narrow.get(w.get("id"), w["rect"]) for w in walls if w.get("rect")]
    sources = set()
    for w in walls:
        sources.update(str(w.get("source") or "").split("+"))
    cols = [r for r in wrects if (r[2] - r[0]) <= 800 and (r[3] - r[1]) <= 800]
    out = []
    for r in rows:
        nm = r.get("name") or ""
        if r.get("class") in ("SplineShape", "Line", "Text") or nm in sources or nm in skip_names:
            continue
        got = _rect_of(r)
        if got is None:
            continue
        rect, z0, z1 = got
        if z0 > 60 or z0 < -400:
            continue
        z0 = max(0.0, z0)
        h = z1 - z0
        w, d = rect[2] - rect[0], rect[3] - rect[1]
        t, L = min(w, d), max(w, d)
        mats = _mats(r)
        ti = tex_info(r)
        base = dict(name=nm, rect=[round(v) for v in rect], z0=round(z0), z1=round(z1),
                    material=next((m for m in mats if not generic_material(m)), ""), label=ti.get("label", ""),
                    tex_kind=ti.get("kind"), tile=ti.get("tile"), parent=r.get("parent"),
                    clad=bool("FloorGenerator" in (r.get("mods") or []) or re.search(r"_FG\d", nm) or ti.get("kind") == "tile"))
        # a cladding around a free-standing column
        inner = None
        for c in cols:
            m = (c[0] - rect[0], c[1] - rect[1], rect[2] - c[2], rect[3] - c[3])
            grow = (w - (c[2] - c[0]), d - (c[3] - c[1]))
            if all(x >= -5 for x in m) and all(40 <= g_ <= 600 for g_ in grow):
                inner = c
                break
        if inner is not None and h >= 2000:
            out.append(dict(base, kind="column", inner=[round(v) for v in inner]))
            continue
        if NOT_BOX.search(nm) or t < 60:
            continue
        area = max(1.0, w * d)
        if any(_inter(rect, wr) >= 0.6 * area for wr in wrects):
            continue                         # the wall itself, a cladding / tile layer on it
        if any(_inter(rect, c) > 0 for c in cols):
            continue                         # a finish around a column (thicker claddings are taken above)
        touch = sum(1 for wr in wrects if _gap(rect, wr) <= 30)
        near = sum(1 for wr in wrects if _gap(rect, wr) <= 300)
        if h >= 2000 and 100 <= t and L <= 450 and touch >= 1:
            out.append(dict(base, kind="pipe"))
        elif 300 <= h <= 1500 and t <= 400 and L >= 300 and touch >= 1:
            out.append(dict(base, kind="low"))
        elif 300 <= h <= 650 and t <= 800 and L >= 1000 and near >= 1:
            out.append(dict(base, kind="low"))      # a seating base along a wall (the back cushion between)
    return out


def wall_materials(rows, walls):
    """What each wall of the draft is finished with in the model: {wall id: {kind, label, material}} from the
    materials / textures of the objects it was built from (a plaster wall, a brick wall)."""
    by = {}
    for r in rows:
        if r.get("name"):
            by.setdefault(r["name"], r)
    out = {}
    for w in walls:
        names = [n for n in str(w.get("source") or "").split("+") if n in by]
        if not names:
            continue
        kinds, labels, mats, mixes = [], [], [], []
        for n in names:
            r = by[n]
            ti = tex_info(r)
            ms = _mats(r)
            kd = ti.get("kind")
            if kd is None and any(re.search(r"(?i)plaster|штукат", m) for m in ms):
                kd = "plaster"
            if kd is None and any(re.search(r"(?i)brick|кирпич|loft", m) for m in ms):
                kd = "brick"
            kinds.append(kd)
            if ti.get("brick_mix"):
                mixes.append(n)
            labels.append(ti.get("label") or "")
            mats.append(next((m for m in ms if not generic_material(m)), ""))
        kd = max(set(kinds), key=kinds.count)
        out[w["id"]] = dict(kind=kd, label=next((x for x in labels if x), ""), material=next((x for x in mats if x), ""),
                            brick_mix=bool(mixes))
    return out
