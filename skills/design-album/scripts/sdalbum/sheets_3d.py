# -*- coding: utf-8 -*-
"""3D views of the reference album: the wall finishes (an axonometry, walls in the colour of their finish, marks on
leaders - two views from opposite corners) and the furniture (two views of the dollhouse with the real models)."""
import math
import os

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from . import gfx as S
from . import symbols as Y
from .album import Column

VIEWS = ((38.0, -58.0), (38.0, 122.0))      # (elev, azim): from the front-left corner, from the back-right corner
LOW = 350.0                                  # walls between the camera and the room are cut down to this height
SKIN = 14.0


def _finish_rgb(P):
    from .sheets_plans import FIN_RGB_DEFAULT
    F = P.finishes or {}
    types = F.get("types") or [{"id": "КР-1", "desc": "Окраска"}]
    return types, {t["id"]: tuple(t.get("rgb", FIN_RGB_DEFAULT[i % len(FIN_RGB_DEFAULT)])) for i, t in enumerate(types)}


def finish_scene(P, elev, azim):
    """Triangles, colours and the mark anchors [(type, 3D point)] of the finishes view: a skin of the room's finish
    on every wall face, full height where the face looks at the camera, cut low where the wall stands between the
    camera and the room; floors in their tint; the wall mass cut low."""
    from .iso3d import _poly_tris, _prism_tris
    from .raster3d import _basis
    from .sheets_plans import floor_tints
    v, r, u = _basis(elev, azim)
    cam = np.array([v[0], v[1]])
    cam /= (np.linalg.norm(cam) or 1.0)
    types, frgb = _finish_rgb(P)
    F = P.finishes or {}
    faces, anchors = [], []

    def add(tris, rgb):                            # flat triangles: no outline
        c = tuple(v_ / 255.0 for v_ in rgb)
        faces.extend((t, c, False) for t in tris)

    def prism(poly, z0, z1, rgb):                  # sides as outlined quads, the top as triangles
        c = tuple(v_ / 255.0 for v_ in rgb)
        add(_poly_tris(poly, z1), rgb)
        for p_ in getattr(poly, "geoms", [poly]):
            if p_.is_empty or p_.geom_type != "Polygon":
                continue
            for ring in [p_.exterior] + list(p_.interiors):
                cs = list(ring.coords)
                for a_, b_ in zip(cs[:-1], cs[1:]):
                    faces.append(([(a_[0], a_[1], z0), (b_[0], b_[1], z0), (b_[0], b_[1], z1), (a_[0], a_[1], z1)], c, True))
    tints = floor_tints(P)
    zones = P.floor_zones()
    for f, g in zones:
        add(_poly_tris(g, 0.0), tints.get(f["id"], (215, 217, 220)))
    if not zones:
        add(_poly_tris(unary_union([r_["shp"] for r_ in P.rooms]), 0.0), (214, 205, 190))
    walls = unary_union([w["shape"] for w in P.walls if w["kind"] != "box"])
    prism(walls, 0.0, LOW, (120, 120, 124))        # the walls cut down; the finish skins stand at their faces
    gaps = unary_union([P.open_shape[o["id"]].buffer(20, join_style=2) for o in P.openings
                        if o["kind"] in ("door", "balcony", "passage")] or [Polygon()])
    segs = F.get("segments", [])
    for rm in P.rooms:
        H = float(rm.get("ceiling_level") or P.ceiling)
        typ = rm.get("wall_finish") or F.get("by_class", {}).get(rm.get("cls"), types[0]["id"])
        ring = list(rm["shp"].exterior.coords)
        if Polygon(ring).exterior.is_ccw:              # inward normal = left of a->b on a ccw ring
            sgn = 1.0
        else:
            sgn = -1.0
        best = None
        for a, b in zip(ring[:-1], ring[1:]):
            ln = LineString([a, b])
            if ln.length < 200:
                continue
            ux, uy = (b[0] - a[0]) / ln.length, (b[1] - a[1]) / ln.length
            n = np.array([-uy * sgn, ux * sgn])
            facing = float(n @ cam) > 0.05             # the face looks at the camera: drawn full height
            parts = ln.difference(gaps)
            for part in getattr(parts, "geoms", [parts]):
                if part.geom_type != "LineString" or part.length < 100:
                    continue
                t_ = typ
                for sg in segs:                        # a wall of its own finish (a segment of the finishes plan)
                    if LineString([sg["a"], sg["b"]]).distance(part.centroid) < 200:
                        t_ = sg["type"]
                h = H if facing else LOW
                g0 = 3.0                               # off the wall face: no coplanar faces for the painter
                (ax_, ay_), (bx_, by_) = part.coords[0], part.coords[-1]
                skin = Polygon([(ax_ + n[0] * g0, ay_ + n[1] * g0), (bx_ + n[0] * g0, by_ + n[1] * g0),
                                (bx_ + n[0] * SKIN, by_ + n[1] * SKIN), (ax_ + n[0] * SKIN, ay_ + n[1] * SKIN)]).buffer(0)
                prism(skin, 0.0, h, frgb.get(t_, (205, 205, 210)))
                if facing:
                    m = part.interpolate(0.5, normalized=True)
                    p3 = (m.x + n[0] * SKIN, m.y + n[1] * SKIN, H * 0.62)
                    if best is None or part.length > best[0]:
                        best = (part.length, t_, p3)
                    if t_ != typ:
                        anchors.append((t_, p3, rm["name"]))
        if best is not None:
            anchors.append((best[1], best[2], rm["name"]))
    lines = []
    _elevation_reliefs(P, faces, cam, lines)
    finish_scene.lines = lines                         # outlines of the reliefs (drawn with the depth test)
    return faces, anchors


def _elevation_reliefs(P, faces, cam, lines, off=30.0):
    """The scene objects of the elevations (mouldings, panels, fronts) on the walls that look at the camera: their
    silhouettes as flat reliefs a little off the finish skin."""
    from .iso3d import _poly_tris
    from .sheets_details import Elev
    for e in P.elevations:
        rm = P.room_by_name.get(e.get("room"))
        if rm is None or not any(it.get("src") for it in e.get("items", [])):
            continue
        E = Elev(P, e)
        n = np.array([-E.ux[1], E.ux[0]])
        mid = ((E.a[0] + E.b[0]) / 2.0, (E.a[1] + E.b[1]) / 2.0)
        if not rm["shp"].contains(Point(mid[0] + n[0] * 60, mid[1] + n[1] * 60)):
            n = -n
        if float(n @ cam) <= 0.05:
            continue                                   # a wall the camera sees from behind: cut down, no relief
        for it in e.get("items", []):
            if not it.get("src") or it.get("type") != "poly":
                continue
            g = Polygon(it["pts"], it.get("holes") or []).buffer(0)
            if g.is_empty:
                continue
            c = tuple(v_ / 255.0 for v_ in it.get("rgb", (238, 236, 232)))
            d = off + min(float(it.get("depth", 0) or 0), 200.0) * 0.3
            for t in _poly_tris(g, 0.0):
                faces.append(([(E.a[0] + E.ux[0] * s_ + n[0] * d, E.a[1] + E.ux[1] * s_ + n[1] * d, z_)
                               for s_, z_, _ in t], c, False))
            for part in getattr(g, "geoms", [g]):
                if part.geom_type != "Polygon":
                    continue
                for ring in [part.exterior] + list(part.interiors):
                    cs = [(E.a[0] + E.ux[0] * s_ + n[0] * d, E.a[1] + E.ux[1] * s_ + n[1] * d, z_) for s_, z_ in ring.coords]
                    lines.extend(zip(cs[:-1], cs[1:]))


def _project(info, p3):
    v, r, u = info["basis"]
    p = np.asarray(p3, float)
    x = (p @ r - info["x0"]) * info["px_per_mm"]
    y = (info["y1"] - p @ u) * info["px_per_mm"]
    return x, y


def _place_image(A, psp, png, box_):
    """Fit the picture into box_ (x0, y0, x1, y1 on the sheet, mm); -> (insert, mm per px)."""
    from PIL import Image
    iw, ih = Image.open(png).size
    x0, y0, x1, y1 = box_
    s_ = min((x1 - x0) / iw, (y1 - y0) / ih)
    ins = (x0 + ((x1 - x0) - iw * s_) / 2.0, y0 + ((y1 - y0) - ih * s_) / 2.0)
    idef = A.image(os.path.basename(png), png)
    img = psp.add_image(idef, insert=ins, size_in_units=(iw * s_, ih * s_), dxfattribs={"layer": "SD_Мебель"})
    img.rgb = (254, 254, 254)                     # the renderer draws the image frame: make it the paper
    return ins, s_, (iw, ih)


def finishes_3d(A, no, title, scale, view):
    from . import raster3d
    P = A.P
    elev, azim = VIEWS[view]
    psp = A.make_sheet(no, title, scale, None, kind="A")
    faces, anchors = finish_scene(P, elev, azim)
    png = os.path.join(A.out_dir, "finishes_3d_%d.png" % (view + 1))
    info = {}
    raster3d.render(faces, png, elev=elev, azim=azim, width=1800, ss=2, margin=0.04, edge_rgb=(70, 70, 72),
                    info=info, crop=False, lines=getattr(finish_scene, "lines", None) or None)
    from .album import PLAN_AREA_A
    ax0, ay0, ax1, ay1 = PLAN_AREA_A
    ins, s_, (iw, ih) = _place_image(A, psp, png, (ax0, ay0 + 6.0, ax1, ay1 - 4.0))
    used = []
    seen = set()
    for typ, p3, room in anchors:                # one mark of a finish per room, on a leader out of the wall
        if (typ, room) in seen:
            continue
        seen.add((typ, room))
        px, py = _project(info, p3)
        a = (ins[0] + px * s_, ins[1] + (ih - py) * s_)
        h = 2.6
        w = S.tw(typ, h) + 3.0
        best = None
        for dd in (9.0, 13.0, 17.0, 22.0):
            for k_ in range(12):
                ang = math.radians(30 * k_ + 15)
                c = (a[0] + math.cos(ang) * dd, a[1] + math.sin(ang) * dd)
                g = Polygon([(c[0] - w / 2, c[1] - 2.3), (c[0] + w / 2, c[1] - 2.3), (c[0] + w / 2, c[1] + 2.3),
                             (c[0] - w / 2, c[1] + 2.3)])
                bad = sum(g.buffer(1.0).intersection(u_).area for u_ in used)
                if not (ax0 < g.bounds[0] and g.bounds[2] < ax1 and ay0 < g.bounds[1] and g.bounds[3] < ay1):
                    bad += 1e4
                if best is None or bad < best[0]:
                    best = (bad, c, g)
            if best[0] < 0.5:
                break
        _, c, g = best
        used.append(g)
        q = g.exterior.interpolate(g.exterior.project(Point(a)))
        Y.leader(psp, (q.x, q.y), a, 1.0, (40, 40, 40))
        Y.tag_box(psp, typ, c, 1.0, h=h, txt_rgb=(20, 20, 20), border=(40, 40, 40), rounded=True)
    types, frgb = _finish_rgb(P)
    col = Column(A, psp)
    used_t = sorted({t for t, _, _ in anchors})
    rows = [[t["id"], S.uo_fill(frgb[t["id"]]), t.get("desc", "")] for t in types if t["id"] in used_t or not used_t]
    col.table([12, 12, 76], ["Марка", "УО", "Наименование"], rows, title="Отделка стен", h=1.6, aligns=["C", "C", "L"])
    col.notes(A.note_lines("finishes_3d", [
        "Аксонометрия - для понимания отделки; размеры и площади - по плану отделки стен и развёрткам.",
        "Стены, стоящие между зрителем и помещением, срезаны (видны их нижние 350 мм).",
        "Цвета - условные, по образцам материалов дизайнера.",
    ]))


def furniture_3d(A, no, title, scale, view):
    from . import iso3d
    P = A.P
    elev, azim = VIEWS[view]
    psp = A.make_sheet(no, title, scale, None, kind="A")
    png = os.path.join(A.out_dir, "furniture_3d_%d.png" % (view + 1))
    got = iso3d.render_models(P, png, elev=elev, azim=azim, width=2000) if (P.d.get("items") or P.furniture) else None
    from .album import PLAN_AREA_A
    ax0, ay0, ax1, ay1 = PLAN_AREA_A
    if got:
        _place_image(A, psp, png, (ax0, ay0 + 6.0, ax1, ay1 - 4.0))
    col = Column(A, psp)
    from .sheets_plans import furniture_groups
    rows = [[str(g["pos"]), g["name"], str(len(g["items"]))] for g in furniture_groups(P)]
    if rows:
        col.table([12, 76, 12], ["Поз.", "Наименование", "Кол."], rows, title="Мебель", h=1.5, aligns=["C", "L", "C"])
    col.notes(A.note_lines("furniture_3d", [
        "Мебель и изделия - по 3D-модели дизайнера; стены срезаны на высоте +1,450.",
        "Позиции - см. план расстановки мебели и ведомость мебели индивидуального изготовления.",
    ]))


def sheets(A, key):
    """[(title, scale, fn, arg)] of a 3D key («finishes_3d», «furniture_3d»): two views."""
    name = {"finishes_3d": "3D-вид отделки стен", "furniture_3d": "3D-вид мебели"}[key]
    fn = finishes_3d if key == "finishes_3d" else furniture_3d
    return [("%s. Вид %d" % (name, i + 1), "б/м", fn, i) for i in range(len(VIEWS))]


def has_data(A, key):
    P = A.P
    if key == "finishes_3d":
        return bool(P.rooms) and bool((P.finishes or {}).get("types"))
    if key == "furniture_3d":
        return bool(P.d.get("items")) or len(P.furniture) >= 3
    return True
