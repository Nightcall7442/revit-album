"""«Сводная ведомость. Молдинги» (reference album): mark | the profile drawn | description | length.
The profile is the real cross-section of the moulding's mesh in the scene: the mesh is cut by a plane across the top
strip of the frame (perpendicular to the wall), the cut gives the outline in (off the wall, height)."""
from collections import OrderedDict

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from . import gfx as S


def _cut(V, F, ux, nrm, a, s_cut, z_lo, z_hi):
    """Segments (d, z) where the plane s = s_cut cuts the triangles, kept inside the height band."""
    s = (V[:, 0] - a[0]) * ux[0] + (V[:, 1] - a[1]) * ux[1] - s_cut
    d = (V[:, 0] - a[0]) * nrm[0] + (V[:, 1] - a[1]) * nrm[1]
    z = V[:, 2]
    segs = []
    sf = s[F]
    cross = (sf.min(axis=1) < 0) & (sf.max(axis=1) > 0)
    for tri in F[cross]:
        pts = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            si, sj = s[tri[i]], s[tri[j]]
            if (si < 0) != (sj < 0):
                t = si / (si - sj)
                pts.append((d[tri[i]] + t * (d[tri[j]] - d[tri[i]]), z[tri[i]] + t * (z[tri[j]] - z[tri[i]])))
        if len(pts) == 2 and all(z_lo <= p[1] <= z_hi for p in pts):
            segs.append(pts)
    return segs


def profile_section(P, e, it):
    """Outline of the moulding's section: [(d, z)] polygons in mm, d - off the wall face, z - up from the strip's
    lower edge; None when the scene mesh is not at hand."""
    from . import elev_scene as ES
    from .sheets_details import Elev
    meshes = {n: (V, F) for n, c, V, F in ES.load(P)}
    if it.get("src") not in meshes:
        return None
    V, F = meshes[it["src"]]
    E = Elev(P, e)
    ux = E.ux
    nrm = (-ux[1], ux[0])
    from shapely.geometry import Point
    room = P.room_by_name.get(e.get("room")) if hasattr(P, "room_by_name") else None
    mid = ((E.a[0] + E.b[0]) / 2.0, (E.a[1] + E.b[1]) / 2.0)
    if room is not None and not room["shp"].contains(Point(mid[0] + nrm[0] * 50, mid[1] + nrm[1] * 50)):
        nrm = (-nrm[0], -nrm[1])
    poly = Polygon(it["pts"])
    s0, z0, s1, z1 = poly.bounds
    w = float(it.get("profile") or 60)
    segs = _cut(V, F, ux, nrm, E.a, (s0 + s1) / 2.0 + 0.37, z1 - w - 25.0, z1 + 25.0)
    if len(segs) < 3:
        return None
    lines = [LineString(sg) for sg in segs if LineString(sg).length > 0.01]
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        g = unary_union([ln.buffer(0.6) for ln in lines])
        polys = list(getattr(g, "geoms", [g]))
    g = unary_union(polys)
    if g.is_empty:
        return None
    gx0, gz0, _, _ = g.bounds
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.geom_type == "Polygon" and p.area > 2.0:
            out.append([(x - gx0, y - gz0) for x, y in p.exterior.coords])
    return out or None


def collect(P):
    """OrderedDict mark -> dict(length m, profile mm, elev, item) over the elevations."""
    out = OrderedDict()
    for e in P.elevations:
        for it in e.get("items", []):
            m = it.get("mark") or ""
            if m.startswith("МЛ"):
                r = out.setdefault(m, dict(length=0.0, profile=it.get("profile"), elev=e, item=it))
                r["length"] += it.get("length", 0.0)
    return OrderedDict(sorted(out.items(), key=lambda kv: int("".join(ch for ch in kv[0] if ch.isdigit()) or 0)))


def has_data(A):
    return bool(collect(A.P))


def _draw_profile(psp, polys, cx, cy, wmax, hmax, fallback_wh):
    """The section fitted into a cell, with its overall sizes."""
    if not polys:                      # no mesh: no invented outline
        S.text(psp, "по каталогу", (cx, cy), 1.8, "MIDDLE_CENTER", "SD_Таблицы", rgb=(120, 120, 120))
        return
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    W, H = max(xs), max(ys)
    sc = min(wmax / max(W, 1.0), hmax / max(H, 1.0), 1.0)
    x0, y0 = cx - W * sc / 2.0, cy - H * sc / 2.0
    for p in polys:
        pts = [(x0 + x * sc, y0 + y * sc) for x, y in p]
        S.fill(psp, pts, (30, 30, 30), "SD_Таблицы")
    S.text(psp, "%d" % round(H), (x0 - 1.0, cy), 1.6, "MIDDLE_RIGHT", "SD_Таблицы")
    S.text(psp, "%d" % round(W), (cx, y0 + H * sc + 0.8), 1.6, "BOTTOM_CENTER", "SD_Таблицы")


def summary_sheet(A, no, title, scale, key=None):
    P = A.P
    psp = A.make_sheet(no, title, scale, None, kind="B")
    data = collect(P)
    widths = [16, 30, 70, 20]
    header = ["Марка", "Изображение профиля", "Описание", "Длина, м.п."]
    fmt = lambda v: ("%.2f" % v).replace(".", ",")
    rows, profs = [], []
    for m, r in data.items():
        sec = None
        try:
            sec = profile_section(P, r["elev"], r["item"])
        except Exception:
            sec = None
        profs.append(sec)
        dep = ""
        if sec:
            dep = ", вынос %d мм" % round(max(x for p in sec for x, _ in p))
        rows.append([m, "", "Молдинг, профиль %s мм%s (по 3D-модели; артикул - по каталогу)" % (r["profile"], dep),
                     fmt(r["length"])])
    total = ["", "", "Общий итог (с запасом 10%% - %s)" % fmt(sum(r["length"] for r in data.values()) * 1.1),
             fmt(sum(r["length"] for r in data.values()))]
    row_h = 24.0
    per = int((280.0 - 30.0 - 12.0) // row_h)
    x = 24.0
    i = 0
    while i < len(rows):
        part = rows[i:i + per]
        geo = []
        last = i + per >= len(rows)
        S.table(psp, x, 280.0, widths, header, part, h=2.0, row_h=row_h, head_h=6.0, aligns=["C", "C", "L", "C"],
                title="Спецификация молдингов" if i == 0 else "Спецификация молдингов (продолжение)",
                total=total if last else None, out_rows=geo)
        for j, (top, hh) in enumerate(geo[:len(part)]):
            r = list(data.values())[i + j]
            w = float(r["profile"] or 50)
            _draw_profile(psp, profs[i + j], x + widths[0] + widths[1] / 2.0 + 1.0, top - hh / 2.0 - 1.0,
                          widths[1] - 10.0, hh - 8.0, (w * 0.4, w))
        i += per
        x += sum(widths) + 12.0
        if x + sum(widths) > 412.0:
            break
