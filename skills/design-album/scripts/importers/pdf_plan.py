# -*- coding: utf-8 -*-
"""Vector PDF plan -> DXF (walls, texts) for the DXF importer.

    python3 sda.py import-pdf plan.pdf OUT [--page 1] [--scale 50]

Walls of a vector plan are dark filled areas (poché). They are written as closed polylines on layer A-WALL, texts
as TEXT; the drawing scale is found from dimension numbers next to dimension lines (value / paper length) and
snapped to a standard scale, or given with --scale. A raster PDF (scan / photo) has no vectors: its pages are
saved as PNG for digitising by eye (references/import-pdf-photo.md).
"""
import math
import os
import re
from collections import Counter

PT = 25.4 / 72.0                     # PDF point -> paper mm
STD_SCALES = (10, 20, 25, 50, 75, 100, 125, 150, 200)


def _lum(c):
    if c is None:
        return 1.0
    r, g, b = (list(c) + [0, 0, 0])[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _paths(dr):
    """Drawing items -> list of point loops (paper mm, y up later)."""
    loops, cur = [], []
    for it in dr["items"]:
        op = it[0]
        if op == "re":
            r = it[1]
            loops.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)])
            continue
        if op == "qu":
            q = it[1]
            loops.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)])
            continue
        if op == "l":
            a, b = it[1], it[2]
            if cur and abs(cur[-1][0] - a.x) + abs(cur[-1][1] - a.y) < 1e-3:
                cur.append((b.x, b.y))
            else:
                if len(cur) >= 3:
                    loops.append(cur)
                cur = [(a.x, a.y), (b.x, b.y)]
        elif op == "c":
            pts = [it[1], it[2], it[3], it[4]]
            seq = []
            for i in range(1, 9):
                t = i / 8.0
                x = sum(c * p.x for c, p in zip(_bern(t), pts))
                y = sum(c * p.y for c, p in zip(_bern(t), pts))
                seq.append((x, y))
            if cur and abs(cur[-1][0] - pts[0].x) + abs(cur[-1][1] - pts[0].y) < 1e-3:
                cur += seq
            else:
                if len(cur) >= 3:
                    loops.append(cur)
                cur = [(pts[0].x, pts[0].y)] + seq
    if len(cur) >= 3:
        loops.append(cur)
    return loops


def _bern(t):
    u = 1 - t
    return (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)


def analyse(pdf, page=0):
    import pymupdf
    doc = pymupdf.open(pdf)
    pg = doc[page]
    H = pg.rect.height
    drs = pg.get_drawings()
    from shapely.geometry import Polygon
    fills, lines, curves = [], [], []
    for dr in drs:
        if dr.get("fill") is not None and _lum(dr.get("fill")) < 0.45:
            # one path = outer contour + holes (rooms inside a wall poché): even-odd -> symmetric difference
            g = None
            for lp in _paths(dr):
                if len(lp) < 3:
                    continue
                p = Polygon([(x * PT, (H - y) * PT) for x, y in lp]).buffer(0)
                if p.is_empty:
                    continue
                g = p if g is None else g.symmetric_difference(p)
            if g is not None and not g.is_empty:
                fills.append(g)
        if dr.get("color") is not None and (dr.get("fill") is None or _lum(dr.get("fill")) > 0.45):
            for it in dr["items"]:
                if it[0] == "l":
                    a, b = it[1], it[2]
                    lines.append(((a.x * PT, (H - a.y) * PT), (b.x * PT, (H - b.y) * PT)))
                elif it[0] == "re":
                    r = it[1]
                    cs = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
                    for (ax, ay), (bx, by) in zip(cs[:-1], cs[1:]):
                        lines.append(((ax * PT, (H - ay) * PT), (bx * PT, (H - by) * PT)))
                elif it[0] == "c":
                    pts = [it[1], it[2], it[3], it[4]]
                    seq = []
                    for i in range(0, 9):
                        t = i / 8.0
                        seq.append((sum(c * p.x for c, p in zip(_bern(t), pts)) * PT,
                                    (H - sum(c * p.y for c, p in zip(_bern(t), pts))) * PT))
                    curves.append(seq)
    texts = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                s = sp["text"].strip()
                if not s:
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                d = ln.get("dir", (1, 0))
                texts.append(dict(text=s, x=(x0 + x1) / 2 * PT, y=(H - (y0 + y1) / 2) * PT, w=(x1 - x0) * PT, h=(y1 - y0) * PT,
                                  vertical=abs(d[1]) > abs(d[0])))
    raster = len(pg.get_images()) > 0 and len(drs) < 20
    return dict(fills=fills, lines=lines, curves=curves, texts=texts, raster=raster, n_drawings=len(drs), page_mm=(pg.rect.width * PT, H * PT))


def detect_scale(a):
    """Dimension numbers vs. the paper length of the dimension line under them -> standard scale (or None)."""
    votes = Counter()
    for t in a["texts"]:
        if not re.fullmatch(r"\d{2,5}", t["text"]):
            continue
        v = float(t["text"])
        if not 50 <= v <= 30000:
            continue
        best = None
        for (p, q) in a["lines"]:
            horiz = abs(q[1] - p[1]) < 0.05 * max(abs(q[0] - p[0]), 1e-6)
            vert = abs(q[0] - p[0]) < 0.05 * max(abs(q[1] - p[1]), 1e-6)
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            if L < 2:
                continue
            if t["vertical"] and vert:
                if abs((p[0] + q[0]) / 2 - t["x"]) > 3 * t["w"] + 2 or not min(p[1], q[1]) - 1 <= t["y"] <= max(p[1], q[1]) + 1:
                    continue
            elif not t["vertical"] and horiz:
                if abs((p[1] + q[1]) / 2 - t["y"]) > 3 * t["h"] + 2 or not min(p[0], q[0]) - 1 <= t["x"] <= max(p[0], q[0]) + 1:
                    continue
            else:
                continue
            d = abs((p[1] + q[1]) / 2 - t["y"]) if not t["vertical"] else abs((p[0] + q[0]) / 2 - t["x"])
            if best is None or d < best[0]:
                best = (d, L)
        if best is None:
            continue
        ratio = v / best[1]
        for s in STD_SCALES:
            if abs(ratio - s) <= 0.03 * s:
                votes[s] += 1
    if not votes:
        return None, votes
    s, n = votes.most_common(1)[0]
    return (s if n >= 2 else None), votes


def to_dxf(pdf, dst, page=0, scale=None):
    """-> dict(status, scale, walls, texts, dxf) ; status: ok | raster | no_scale | no_walls"""
    import ezdxf
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    a = analyse(pdf, page)
    if a["raster"] or (a["n_drawings"] < 20 and not a["fills"]):
        return dict(status="raster", n=a["n_drawings"])
    auto = None
    if scale is None:
        scale, votes = detect_scale(a)
        auto = dict(votes)
        if scale is None:
            return dict(status="no_scale", votes=auto, texts=len(a["texts"]))
    k = float(scale)
    from shapely import affinity
    polys = []
    for g0 in a["fills"]:
        g0 = affinity.scale(g0, k, k, origin=(0, 0))
        for p in (g0.geoms if hasattr(g0, "geoms") else [g0]):
            if p.is_empty or p.area < 0.01e6:
                continue
            thick = 2.0 * p.area / max(p.exterior.length, 1.0)   # ~ wall thickness for long thin shapes
            if thick < 45:
                continue
            polys.append(p)
    if not polys:
        return dict(status="no_walls", scale=k)
    # the plan is the biggest connected group of fills (title block, logo and lettering are separate groups);
    # 1300 mm joins wall runs across door / window gaps up to 2600
    u = unary_union([p.buffer(1300) for p in polys])
    comps = list(u.geoms) if hasattr(u, "geoms") else [u]
    comp = max(comps, key=lambda c: sum(p.area for p in polys if c.contains(p.representative_point())))
    mine = [p for p in polys if comp.contains(p.representative_point())]
    big = [p for p in mine if max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) >= 500]
    core = unary_union(big) if big else None
    # lettering (bold titles, sheet numbers) is small and stands alone; a short pier touching a wall stays
    walls = unary_union([p for p in mine if p in big or (core is not None and p.buffer(5).intersects(core))])
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("A-WALL")
    doc.layers.add("Помещения")
    doc.layers.add("Размеры")
    n = 0
    from importers.geomutil import decompose
    for g in decompose(walls.simplify(2.0)):
        cs = [(round(x), round(y)) for x, y in g.exterior.coords]
        msp.add_lwpolyline(cs, close=True, dxfattribs={"layer": "A-WALL"})
        n += 1
    doc.layers.add("Линии")
    zone = comp.buffer(500)
    from shapely.geometry import LineString, Point as _Pt
    for (p, q) in a["lines"]:
        P1, P2 = (p[0] * k, p[1] * k), (q[0] * k, q[1] * k)
        if zone.contains(_Pt(P1)) or zone.contains(_Pt(P2)):
            msp.add_line(P1, P2, dxfattribs={"layer": "Линии"})
    for seq in a["curves"]:
        pts = [(x * k, y * k) for x, y in seq]
        if zone.contains(_Pt(pts[0])):
            msp.add_lwpolyline(pts, dxfattribs={"layer": "Линии"})
    nt = 0
    for t in a["texts"]:
        layer = "Размеры" if re.fullmatch(r"\d{2,5}", t["text"]) else "Помещения"
        msp.add_text(t["text"], dxfattribs={"layer": layer, "height": max(t["h"] * k * 0.7, 50), "insert": (t["x"] * k, t["y"] * k)})
        nt += 1
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    doc.saveas(dst)
    return dict(status="ok", scale=k, auto_votes=auto, walls=n, texts=nt, dxf=dst)


def pages_to_png(pdf, out, dpi=150):
    import pymupdf
    os.makedirs(out, exist_ok=True)
    doc = pymupdf.open(pdf)
    paths = []
    for i, pg in enumerate(doc):
        p = os.path.join(out, "page-%d.png" % (i + 1))
        pg.get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    return paths


def main(pdf, out, page=1, scale=None):
    from importers import dxf_plan
    os.makedirs(out, exist_ok=True)
    res = to_dxf(pdf, os.path.join(out, "plan_from_pdf.dxf"), page - 1, scale)
    if res["status"] == "ok":
        dxf_plan.main(res["dxf"], out)
        print("PDF: масштаб 1:%g%s, стен %d, текстов %d" % (res["scale"], " (определён по размерам)" if res.get("auto_votes") else "",
                                                           res["walls"], res["texts"]))
    else:
        pngs = pages_to_png(pdf, out)
        msg = {"raster": "растровый PDF (скан/фото) - оцифровка по images (import-pdf-photo.md)",
               "no_scale": "масштаб не определён - укажите --scale (например 50)",
               "no_walls": "залитых стен не найдено - оцифровка по images"}[res["status"]]
        print("PDF:", msg, "; страницы:", ", ".join(os.path.basename(p) for p in pngs))
    return res
