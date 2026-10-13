# -*- coding: utf-8 -*-
"""DWG / DXF plan -> survey pack + draft project.json.

    python3 sda.py import-dxf plan.dxf OUT [--window x0,y0,x1,y1] [--units mm|cm|m]

Writes to OUT:
  layers.md          layers with entity counts, guessed role (walls / partitions / doors / windows / text / dims)
  clusters.json      separate drawings found in model space (bounds, number of wall polygons) - the largest is used
  plan.png           the chosen drawing rendered with a 1 m grid and coordinates (mm)
  texts.json         every text in the drawing window (room names, areas, marks) with positions in mm
  inserts.json       block references (doors, windows, furniture, sanitary) with position / rotation / extents
  draft_project.json walls from closed polylines / hatches on wall layers (existing / new by layer name),
                     rooms with seeds at room-name texts; openings are left to the agent (see plan.png)

DWG: converted with the ODA File Converter (ezdxf odafc add-on) or LibreDWG `dwg2dxf` when installed; otherwise ask
for "Сохранить как -> DXF" from AutoCAD / nanoCAD.
"""
import json
import os
import re
import shutil
import subprocess
import sys

UNITS = {0: None, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}
ROLE_PATTERNS = [
    ("partition", r"перегород|partit|возвод|new|нов|a-wall-prtn|кладк"),
    ("wall", r"стен|wall|несущ|a-wall|конструкц|bearing|colum|колон"),
    ("door", r"двер|door"),
    ("window", r"окн|window|glaz|витраж"),
    ("dims", r"размер|dim"),
    ("axes", r"ос[иь]|axis|grid"),
    ("text", r"текст|text|марк|помещ|room|anno"),
    ("hatch", r"штрих|hatch"),
    ("furniture", r"мебел|furn|equip|оборуд|сантех|plumb"),
]
ROOM_WORDS = r"(прихож|коридор|холл|кухн|столов|гостин|спальн|детск|кабинет|санузел|ванн|туалет|с/у|гардероб|кладов|балкон|лоджи|тамбур|постир|зал|комнат)"


def role_of(layer):
    n = layer.lower()
    for role, pat in ROLE_PATTERNS:
        if re.search(pat, n):
            return role
    return ""


def to_dxf(path, out):
    if path.lower().endswith(".dxf"):
        return path
    dst = os.path.join(out, os.path.splitext(os.path.basename(path))[0] + ".dxf")
    try:
        from ezdxf.addons import odafc
        if odafc.is_installed():
            odafc.convert(path, dst, version="R2018")
            return dst
    except Exception:
        pass
    if shutil.which("dwg2dxf"):
        subprocess.call(["dwg2dxf", "-o", dst, path])
        if os.path.exists(dst):
            return dst
    raise SystemExit("DWG не конвертируется в этой среде: нет ODA File Converter / LibreDWG. "
                     "Попросите файл в формате DXF (AutoCAD: Сохранить как -> DXF 2013).")


def _polys(e, k):
    """Closed polygons (mm) from a wall entity."""
    from shapely.geometry import Polygon
    out = []
    t = e.dxftype()
    try:
        if t == "LWPOLYLINE" and (e.closed or len(e) > 3):
            pts = [(p[0] * k, p[1] * k) for p in e.get_points("xy")]
            if len(pts) >= 3:
                out.append(Polygon(pts))
        elif t == "POLYLINE" and e.is_closed:
            out.append(Polygon([(v.dxf.location.x * k, v.dxf.location.y * k) for v in e.vertices]))
        elif t == "HATCH":
            for bp in e.paths:
                if hasattr(bp, "vertices") and bp.vertices:
                    out.append(Polygon([(v[0] * k, v[1] * k) for v in bp.vertices]))
                elif hasattr(bp, "edges"):
                    pts = []
                    for ed in bp.edges:
                        if hasattr(ed, "start"):
                            pts.append((ed.start[0] * k, ed.start[1] * k))
                    if len(pts) >= 3:
                        out.append(Polygon(pts))
        elif t == "SOLID":
            pts = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
            out.append(Polygon([(p[0] * k, p[1] * k) for p in pts]))
    except Exception:
        return []
    return [p.buffer(0) for p in out if p.is_valid or p.buffer(0).area > 0]


def main(path, out, window=None, units=None):
    import ezdxf
    from shapely.geometry import box, Point
    from shapely.ops import unary_union
    os.makedirs(out, exist_ok=True)
    src = to_dxf(path, out)
    doc = ezdxf.readfile(src)
    msp = doc.modelspace()
    k = {"mm": 1.0, "cm": 10.0, "m": 1000.0}.get(units) if units else UNITS.get(doc.header.get("$INSUNITS", 4)) or 1.0
    # layers
    from collections import Counter, defaultdict
    cnt = defaultdict(Counter)
    for e in msp:
        cnt[e.dxf.layer][e.dxftype()] += 1
    roles = {ly: role_of(ly) for ly in cnt}
    md = ["# Слои %s" % os.path.basename(path), "", "Единицы чертежа: x%.1f -> мм ($INSUNITS=%s)" % (k, doc.header.get("$INSUNITS")), "",
          "| Слой | Роль (догадка) | Объекты |", "|---|---|---|"]
    for ly in sorted(cnt):
        md.append("| %s | %s | %s |" % (ly, roles[ly] or "-", ", ".join("%s×%d" % kv for kv in cnt[ly].most_common())))
    # wall polygons
    def collect(accept):
        out_ = []
        for e in msp:
            r = roles.get(e.dxf.layer)
            if r in accept and e.dxftype() in ("LWPOLYLINE", "POLYLINE", "HATCH", "SOLID"):
                for p in _polys(e, k):
                    if 0.01e6 < p.area < 50e6:
                        out_.append((p, "new" if r == "partition" else "existing", e.dxf.layer))
        return out_
    walls = collect(("wall", "partition"))
    if not walls:                    # no named wall layers: fall back to hatches (often the poché of walls)
        walls = collect(("hatch",))
    # duplicates (outline polyline + its hatch, overlapping copies): keep the first of near-identical shapes
    uniq = []
    for w in walls:
        if any(w[0].intersection(u[0]).area > 0.9 * min(w[0].area, u[0].area) for u in uniq):
            continue
        uniq.append(w)
    walls = uniq
    # clusters of drawings in model space
    clusters = []
    if walls:
        u = unary_union([p.buffer(800) for p, _, _ in walls])
        comps = list(u.geoms) if hasattr(u, "geoms") else [u]
        for c in comps:
            members = [w for w in walls if c.contains(w[0].representative_point())]
            clusters.append(dict(bounds=[round(v) for v in c.buffer(-800).bounds], walls=len(members),
                                 area_m2=round(sum(w[0].area for w in members) / 1e6, 2)))
        clusters.sort(key=lambda c: -c["walls"])
    json.dump(clusters, open(os.path.join(out, "clusters.json"), "w"), indent=1)
    if window:
        win = box(*window)
    elif clusters:
        b = clusters[0]["bounds"]
        win = box(b[0] - 1500, b[1] - 1500, b[2] + 1500, b[3] + 1500)
    else:
        ext = msp_extents(msp, k)
        win = box(*ext)
    # texts / inserts in the window
    texts, inserts = [], []
    for e in msp:
        t = e.dxftype()
        try:
            if t in ("TEXT", "MTEXT"):
                p = e.dxf.insert
                s = e.dxf.text if t == "TEXT" else e.plain_text()
                q = (p[0] * k, p[1] * k)
                if t == "TEXT" and e.dxf.halign + e.dxf.valign > 0 and e.dxf.hasattr("align_point"):
                    p = e.dxf.align_point
                    q = (p[0] * k, p[1] * k)
                h = e.dxf.height if t == "TEXT" else e.dxf.char_height
                if win.contains(Point(q)) and s.strip():
                    texts.append(dict(text=s.strip(), x=round(q[0]), y=round(q[1]), layer=e.dxf.layer, h=round(h * k)))
            elif t == "INSERT":
                p = e.dxf.insert
                q = (p[0] * k, p[1] * k)
                if win.contains(Point(q)):
                    inserts.append(dict(block=e.dxf.name, x=round(q[0]), y=round(q[1]), rot=round(e.dxf.rotation, 1),
                                        sx=e.dxf.xscale, sy=e.dxf.yscale, layer=e.dxf.layer, role=role_of(e.dxf.layer) or role_of(e.dxf.name)))
        except Exception:
            continue
    json.dump(texts, open(os.path.join(out, "texts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(inserts, open(os.path.join(out, "inserts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md += ["", "## Чертежи в пространстве модели", ""]
    for i, c in enumerate(clusters[:10]):
        md.append("- #%d: границы %s мм, стен/полигонов %d%s" % (i + 1, c["bounds"], c["walls"], "  <- взят" if i == 0 and not window else ""))
    md += ["", "Текстов в окне: %d, блоков: %d. Названия помещений: %s" % (
        len(texts), len(inserts), ", ".join(sorted({t["text"] for t in texts if re.search(ROOM_WORDS, t["text"].lower())})[:20]) or "-")]
    open(os.path.join(out, "layers.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    _render(doc, src, win, k, os.path.join(out, "plan.png"))
    _draft(walls, texts, win, os.path.join(out, "draft_project.json"))
    print("walls:", len([w for w in walls if win.contains(w[0].representative_point())]), " texts:", len(texts),
          " inserts:", len(inserts), " ->", out)


def msp_extents(msp, k):
    from ezdxf import bbox
    b = bbox.extents(msp, fast=True)
    return (b.extmin[0] * k, b.extmin[1] * k, b.extmax[0] * k, b.extmax[1] * k)


def _render(doc, src, win, k, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    x0, y0, x1, y1 = win.bounds
    fig = plt.figure(figsize=(16, max(4.0, 16 * (y1 - y0) / max(1.0, x1 - x0))))
    ax = fig.add_axes([0.04, 0.04, 0.94, 0.92])
    from ezdxf.addons.drawing import config
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=False)
    ax.set_xlim(x0 / k, x1 / k)
    ax.set_ylim(y0 / k, y1 / k)
    ax.set_aspect("equal")
    import numpy as np
    step = 1000 / k
    ax.set_xticks(np.arange(round(x0 / k / step) * step, x1 / k, step))
    ax.set_yticks(np.arange(round(y0 / k / step) * step, y1 / k, step))
    ax.tick_params(labelsize=6)
    ax.grid(True, lw=0.3, alpha=0.4)
    ax.set_title("план (сетка 1 м; координаты в единицах чертежа x%.0f = мм)" % k, fontsize=9)
    fig.savefig(png, dpi=140)
    plt.close(fig)


def _run_behind(mass, face, sgn, horiz_face, maxd=6000):
    """Depth of construction behind a face (opposite to the extrusion direction)."""
    from shapely.geometry import box
    (lo, hi, c) = face
    if horiz_face:
        r = box(lo + 1, min(c, c - sgn * maxd), hi - 1, max(c, c - sgn * maxd))
    else:
        r = box(min(c, c - sgn * maxd), lo + 1, max(c, c - sgn * maxd), hi - 1)
    g = r.intersection(mass)
    if g.is_empty:
        return 0.0
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    best = 0.0
    for q in parts:
        b = q.bounds
        if horiz_face:
            near = abs((b[3] if sgn > 0 else b[1]) - c) < 2
            dep = b[3] - b[1]
        else:
            near = abs((b[2] if sgn > 0 else b[0]) - c) < 2
            dep = b[2] - b[0]
        if near:
            best = max(best, dep)
    return best


def close_gaps(polys, max_gap=2600, min_t=60, max_t=700, min_w=450):
    """Wall ends facing each other across a gap (door / window / passage) -> [(gap rectangle, horizontal?)].
    Works on orthogonal outlines: every short edge (wall end) is extruded outward until it meets another wall."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    if not polys:
        return []
    mass = unary_union(polys)
    out = []
    for poly in (mass.geoms if hasattr(mass, "geoms") else [mass]):
        cs = list(poly.exterior.coords)
        for (ax, ay), (bx, by) in zip(cs[:-1], cs[1:]):
            L = abs(ax - bx) + abs(ay - by)
            if not (min_t <= L <= max_t) or (abs(ax - bx) > 1 and abs(ay - by) > 1):
                continue
            if abs(ay - by) < 1:                         # horizontal end face -> extrude along y
                lo, hi = sorted((ax, bx))
                for sgn in (1, -1):
                    probe = box(lo + 1, ay + sgn * 2 if sgn > 0 else ay - 3, hi - 1, ay + 3 if sgn > 0 else ay - 2)
                    if mass.intersection(probe).area > 0.5:
                        continue                         # wall continues on this side
                    if _run_behind(mass, (lo, hi, ay), sgn, True) < 1.2 * (hi - lo):
                        continue                         # a side of a short stub, not the end of a wall run
                    ray = box(lo + 1, min(ay, ay + sgn * max_gap), hi - 1, max(ay, ay + sgn * max_gap))
                    hit = ray.intersection(mass.difference(box(lo - 1, ay - 2, hi + 1, ay + 2)))
                    if hit.is_empty or hit.area < 1:
                        continue
                    hb = hit.bounds
                    d = (hb[1] - ay) if sgn > 0 else (ay - hb[3])
                    if d < min_w:
                        continue
                    g = box(lo, min(ay, ay + sgn * d), hi, max(ay, ay + sgn * d))
                    if not any(g.buffer(1).contains(q) or q.buffer(1).contains(g) for q, _ in out):
                        out.append((g, False))           # vertical wall run -> opening measured along y
            else:                                        # vertical end face -> extrude along x
                lo, hi = sorted((ay, by))
                for sgn in (1, -1):
                    probe = box(ax + 2 if sgn > 0 else ax - 3, lo + 1, ax + 3 if sgn > 0 else ax - 2, hi - 1)
                    if mass.intersection(probe).area > 0.5:
                        continue
                    if _run_behind(mass, (lo, hi, ax), sgn, False) < 1.2 * (hi - lo):
                        continue
                    ray = box(min(ax, ax + sgn * max_gap), lo + 1, max(ax, ax + sgn * max_gap), hi - 1)
                    hit = ray.intersection(mass.difference(box(ax - 2, lo - 1, ax + 2, hi + 1)))
                    if hit.is_empty or hit.area < 1:
                        continue
                    hb = hit.bounds
                    d = (hb[0] - ax) if sgn > 0 else (ax - hb[2])
                    if d < min_w:
                        continue
                    g = box(min(ax, ax + sgn * d), lo, max(ax, ax + sgn * d), hi)
                    if not any(g.buffer(1).contains(q) or q.buffer(1).contains(g) for q, _ in out):
                        out.append((g, True))
    return out


def _draft(walls, texts, win, path):
    from shapely.geometry import Point
    from shapely.ops import unary_union
    ws, n = [], 0
    inwin = [w for w in walls if win.contains(w[0].representative_point())]
    for p, kind, layer in inwin:
        n += 1
        x0, y0, x1, y1 = p.bounds
        rect = abs(p.area - (x1 - x0) * (y1 - y0)) < 0.02 * p.area
        w = dict(id=("С%d" if kind == "existing" else "П%d") % n, kind=kind, source=layer)
        if rect:
            w["rect"] = [round(x0), round(y0), round(x1), round(y1)]
        else:
            w["poly"] = [[round(x), round(y)] for x, y in list(p.exterior.coords)[:-1]]
        ws.append(w)
    # openings: gaps between wall ends become a small wall piece carrying the opening (rooms close, openings exist)
    gaps = close_gaps([w[0] for w in inwin])
    mass0 = unary_union([w[0] for w in inwin] + [g for g, _ in gaps]) if inwin else None
    outline = None
    if mass0 is not None:
        from shapely.geometry import Polygon
        outline = unary_union([Polygon(g.exterior) for g in (mass0.geoms if hasattr(mass0, "geoms") else [mass0])])
    openings = []
    for i, (g, horiz) in enumerate(gaps, 1):
        x0, y0, x1, y1 = g.bounds
        wid = "ПР%d" % i
        ws.append(dict(id=wid, kind="existing", rect=[round(x0), round(y0), round(x1), round(y1)], source="проём", check=True))
        c = g.centroid
        width = (x1 - x0) if horiz else (y1 - y0)
        t = (y1 - y0) if horiz else (x1 - x0)
        n = (0, 1) if horiz else (1, 0)
        a = Point(c.x + n[0] * (t / 2 + 150), c.y + n[1] * (t / 2 + 150))
        b = Point(c.x - n[0] * (t / 2 + 150), c.y - n[1] * (t / 2 + 150))
        outside = outline is not None and (not outline.contains(a) or not outline.contains(b))
        kind = "window" if outside and width >= 600 else "door"
        o = dict(id="%s.%d" % ("ОК" if kind == "window" else "Д", i), mark="ОК-?" if kind == "window" else "Д-?",
                 kind=kind, wall=wid, c=round(c.x if horiz else c.y), w=round(width),
                 h=1500 if kind == "window" else 2100, check=True)
        if kind == "window":
            o["sill"] = 900
        openings.append(o)
    mass = mass0
    rooms = []
    for t in texts:
        if re.search(ROOM_WORDS, t["text"].lower()) and mass is not None and not mass.contains(Point(t["x"], t["y"])):
            rooms.append(dict(num=str(len(rooms) + 1), name=t["text"].split("\n")[0][:40], seed=[t["x"], t["y"]],
                              cls="wet" if re.search(r"санузел|ванн|туалет|с/у", t["text"].lower()) else "living"))
    d = dict(meta=dict(title="ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА", studio="Space Design Studio", stage="Дизайн-проект"),
             levels=dict(floor=0, ceiling=2700, slab=3000), grid=dict(x=[], y=[]), walls=ws, openings=openings, rooms=rooms,
             separations=[], furniture=[], lighting=[], switches=[], sockets=[], plumbing=[], floors=[],
             ceilings=dict(types=[], zones=[]), elevations=[], nodes=[],
             _todo=["сдвинуть начало координат в пересечение осей 1/А (внутренний угол)", "проверить kind стен",
                    "проёмы: стена + центр + ширина по plan.png / inserts.json", "высоты: потолок / плита - уточнить",
                    "sda.py validate"])
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    a = sys.argv[1:]
    w = [float(v) for v in a[a.index("--window") + 1].split(",")] if "--window" in a else None
    main(a[0], a[1], w, a[a.index("--units") + 1] if "--units" in a else None)
