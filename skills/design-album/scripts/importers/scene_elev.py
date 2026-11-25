# -*- coding: utf-8 -*-
"""Meshes of the objects that stand at the walls, kept for the elevations (sdalbum/elev_scene.py projects them on
every wall of every room when the album is built - the rooms are known only then).

    import/elev_meshes.npz   v<i> (float32, mm of the scene), f<i> (int32 triangles), names / cats (json)

Kept: objects whose plan footprint comes within NEAR mm of a wall face of the draft and that are not the walls,
the floor / ceiling planes, door and window blocks (the engine draws openings itself) or library objects parked far
away. A mesh denser than MAX_FACES is thinned (every n-th triangle): the projection is a 4 mm raster, the outline
does not change.
"""
import json
import os
import re

import numpy as np

NEAR = 350.0
MAX_FACES = 250000
SKIP = re.compile(r"door|двер|window|окн|wd_|camera|light(?!.*(bra|бра|sconce))|vray|corona|target|plane\d*$", re.I)

CATS = (("molding", r"molding|moulding|молдинг|багет|карниз(?!.*штор)|cornice|frame|рамк|plinth|плинтус|европласт|1\.5\d\.\d{3}"),
        ("curtain", r"curtain|штор|tulle|тюл|drape"),
        ("mirror", r"mirror|зеркал"),
        ("light", r"sconce|бра|lamp|светил|chandelier|люстр"),
        ("tv", r"\btv\b|телевиз|television"),
        ("radiator", r"radiator|радиатор|батаре"),
        ("art", r"picture|painting|картин|poster|постер|art\b"),
        ("seating", r"sofa|диван|chair|стул|кресл|armchair|bed|кроват|pouf|пуф|ottoman|table|стол(?!еш)"),
        ("furniture", r"cabinet|шкаф|wardrobe|комод|console|консол|shelf|стеллаж|полк|sideboard|буфет|tumb|тумб|fasad|фасад"))


def category(name):
    for c, rx in CATS:
        if re.search(rx, name or "", re.I):
            return c
    return "other"


def save(rows, meshes, k, d, out):
    from shapely.geometry import box
    from shapely.ops import unary_union
    walls = [w for w in d.get("walls", []) if w.get("kind") == "existing" and w.get("rect")]
    if not walls:
        return None
    mass = unary_union([box(*w["rect"]) for w in walls])
    srcs = {str(w.get("source")) for w in walls}
    hull = mass.convex_hull.buffer(500)
    arrays, names, cats = {}, [], []
    for r in rows:
        idx = r.get("idx")
        if idx not in meshes or not r.get("bbox") or r.get("skip"):
            continue
        name = r.get("name") or ""
        if name in srcs or SKIP.search(name):
            continue
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        if z1 - z0 < 15 and (x1 - x0) * (y1 - y0) > 2e6:         # floor / ceiling planes
            continue
        fp = box(x0, y0, x1, y1)
        if not hull.intersects(fp) or fp.distance(mass) > NEAR:
            continue
        if fp.area > 0.6 * hull.area:                             # the shell / a group of everything
            continue
        _, vw, faces = meshes[idx]
        v = (np.asarray(vw, float) * k).astype(np.float32)
        from importers.max_scene import _tri
        f = np.asarray(list(_tri(faces)), np.int32).reshape(-1, 3)
        if len(f) > MAX_FACES:
            f = f[:: int(np.ceil(len(f) / float(MAX_FACES)))]
        i = len(names)
        arrays["v%d" % i], arrays["f%d" % i] = v, f
        names.append(name)
        cats.append(category(name + " " + str(r.get("parent") or "")))
    if not names:
        return None
    p = os.path.join(out, "elev_meshes.npz")
    np.savez_compressed(p, names=np.array(json.dumps(names, ensure_ascii=False)),
                        cats=np.array(json.dumps(cats)), **arrays)
    print("elevations: объектов у стен %d -> %s" % (len(names), os.path.basename(p)))
    return p
