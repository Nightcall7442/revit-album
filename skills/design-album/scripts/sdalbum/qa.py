# -*- coding: utf-8 -*-
"""Sheet-level QA: renders every layout through a recording backend (exact paper coordinates, after
viewport transform and clipping) and checks what a reviewer would catch by eye.

Errors (block delivery):
  TEXT_OVERLAP     two texts (incl. dimension texts) overlap
  TEXT_ON_WALL     dark text sits on a dark fill (wall / partition hatch)
  TEXT_IN_STAMP    foreign text enters the title block
  TEXT_OUT_FRAME   text outside the drawing frame
  TABLE_ON_DRAWING table / legend overlaps viewport content
  VIEWPORT_OVERLAP two viewports overlap on the sheet
Warnings (review, fix when reasonable):
  TEXT_AT_VP_EDGE  text touches a viewport border (probably clipped)
  LINE_THROUGH_TEXT a dark foreign line crosses the core of a text
"""
import json
import math
from shapely.geometry import box, LineString, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from ezdxf.addons.drawing import Frontend, RenderContext, config as dcfg
from ezdxf.addons.drawing.backend import BackendInterface

STAMP = (185.0, 5.0, 415.0, 31.0)
FRAME = (20.0, 5.0, 415.0, 292.0)


def _lum(hexcolor):
    h = hexcolor.lstrip("#")[:6]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


class Recorder(BackendInterface):
    def __init__(self):
        self.texts = {}       # tid -> dict(content, boxes[], color, layer, handle, order)
        self.lines = []       # (LineString, color, layer, handle, order)
        self.fills = []       # (Polygon, color, layer, handle, order)
        self.cur = None
        self.k = 0

    def _o(self):
        self.k += 1
        return self.k

    def configure(self, config):
        pass

    def enter_entity(self, entity, properties):
        pass

    def exit_entity(self, entity):
        pass

    def set_background(self, color):
        pass

    def draw_point(self, pos, properties):
        pass

    def draw_line(self, start, end, properties):
        if self.cur:
            return
        if abs(start.x - end.x) + abs(start.y - end.y) > 1e-6:
            self.lines.append((LineString([(start.x, start.y), (end.x, end.y)]), properties.color, properties.layer, properties.handle, self._o()))

    def draw_solid_lines(self, lines, properties):
        for s, e in lines:
            self.draw_line(s, e, properties)

    def draw_path(self, path, properties):
        if self.cur:
            self._glyph(path)
            return
        pts = [(v.x, v.y) for v in path.flattening(0.05)]
        if len(pts) >= 2:
            self.lines.append((LineString(pts), properties.color, properties.layer, properties.handle, self._o()))

    def _glyph(self, path):
        try:
            (x0, y0), (x1, y1) = path.extents()
        except Exception:
            bb = path.bbox()
            x0, y0, x1, y1 = bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y
        if x1 - x0 > 1e-4 and y1 - y0 > 1e-4:
            t = self.texts[self.cur]
            t["boxes"].append(box(x0, y0, x1, y1))
            if not t.get("order"):
                t["order"] = self._o()

    def draw_filled_paths(self, paths, properties):
        if self.cur:
            t = self.texts[self.cur]
            t["color"] = properties.color
            t["layer"] = properties.layer
            for p in paths:
                self._glyph(p)
            return
        for p in paths:
            pts = [(v.x, v.y) for v in p.flattening(0.1)]
            if len(pts) >= 3:
                poly = Polygon(pts).buffer(0)
                if not poly.is_empty:
                    self.fills.append((poly, properties.color, properties.layer, properties.handle, self._o()))

    def draw_filled_polygon(self, points, properties):
        if self.cur:
            return
        pts = [(v.x, v.y) for v in points]
        if len(pts) >= 3:
            poly = Polygon(pts).buffer(0)
            if not poly.is_empty:
                self.fills.append((poly, properties.color, properties.layer, properties.handle, self._o()))

    def draw_image(self, image_data, properties):
        pass

    def clear(self):
        pass

    def finalize(self):
        pass


class QFrontend(Frontend):
    def __init__(self, ctx, rec, cfg):
        super().__init__(ctx, rec, cfg)
        self._rec = rec
        self._n = 0

    def _wrap(self, entity, fn, properties):
        self._n += 1
        tid = self._n
        try:
            content = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
        except Exception:
            content = "?"
        self._rec.texts[tid] = dict(content=str(content), boxes=[], color="#000000", layer=entity.dxf.layer,
                                    handle=getattr(entity.dxf, "handle", None))
        self._rec.cur = tid
        try:
            fn(entity, properties)
        finally:
            self._rec.cur = None

    def draw_text_entity(self, entity, properties):
        self._wrap(entity, super().draw_text_entity, properties)

    def draw_mtext_entity(self, entity, properties):
        self._wrap(entity, super().draw_mtext_entity, properties)


def record_layout(doc, layout):
    rec = Recorder()
    ctx = RenderContext(doc)
    ctx.set_current_layout(layout)
    cfg = dcfg.Configuration(background_policy=dcfg.BackgroundPolicy.WHITE)
    QFrontend(ctx, rec, cfg).draw_layout(layout, finalize=True)
    return rec


def viewports(layout):
    out = []
    for vp in layout.query("VIEWPORT"):
        if vp.dxf.id == 1:
            continue
        c, w, h = vp.dxf.center, vp.dxf.width, vp.dxf.height
        out.append(box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2))
    return out


def check_layout(doc, layout, framed=True):
    rec = record_layout(doc, layout)
    issues = []
    texts = []
    for tid, t in rec.texts.items():
        if not t["boxes"] or not t["content"].strip():
            continue
        g = unary_union(t["boxes"])
        texts.append(dict(id=tid, content=t["content"].strip().replace("\n", " "), geom=g, color=t["color"], layer=t["layer"],
                          bbox=g.bounds, order=t.get("order", 0)))
    light = [(f[0], f[4]) for f in rec.fills if _lum(f[1]) > 0.85]
    ltree_ = STRtree([f[0] for f in light]) if light else None

    def masked(geom, after, before):
        """part of geom covered by light fills drawn between orders (after, before)."""
        if ltree_ is None:
            return geom.intersection(Polygon())
        cov = [light[int(j)][0] for j in ltree_.query(geom) if after < light[int(j)][1] < before]
        return unary_union(cov) if cov else Polygon()
    # --- text / text overlaps
    geoms = [t["geom"] for t in texts]
    tree = STRtree(geoms) if geoms else None
    seen = set()
    for i, t in enumerate(texts):
        if tree is None:
            break
        for j in tree.query(t["geom"]):
            j = int(j)
            if j <= i or (i, j) in seen:
                continue
            seen.add((i, j))
            u = texts[j]
            inter = t["geom"].intersection(u["geom"]).area
            if inter > 0.04:
                issues.append(dict(code="TEXT_OVERLAP", level="error", where=_c(t["bbox"]),
                                   msg="«%s» перекрывает «%s»" % (_s(t["content"]), _s(u["content"])),
                                   bbox=[round(v, 2) for v in t["bbox"]]))
    # --- dark text on dark fills (walls)
    dark = [f for f in rec.fills if _lum(f[1]) < 0.45 and f[0].area > 0.5]
    if dark:
        dtree = STRtree([f[0] for f in dark])
        for t in texts:
            if _lum(t["color"]) > 0.7:
                continue
            a = 0.0
            for j in dtree.query(t["geom"]):
                f = dark[int(j)]
                if f[4] > t["order"]:
                    continue
                part = t["geom"].intersection(f[0])
                if part.is_empty:
                    continue
                part = part.difference(masked(part, f[4], t["order"]))
                a += part.area
            if a > 0.25 * t["geom"].area:
                issues.append(dict(code="TEXT_ON_WALL", level="error", where=_c(t["bbox"]),
                                   msg="«%s» лежит на тёмной заливке (стена)" % _s(t["content"]),
                                   bbox=[round(v, 2) for v in t["bbox"]]))
    if framed:
        st = box(*STAMP)
        fr = box(*FRAME)
        for t in texts:
            if t["layer"] in ("SD_Штамп",):
                continue
            if t["geom"].intersection(st).area > 0.05:
                issues.append(dict(code="TEXT_IN_STAMP", level="error", where=_c(t["bbox"]), msg="«%s» заходит в штамп" % _s(t["content"])))
            if not fr.buffer(0.2).contains(t["geom"]):
                issues.append(dict(code="TEXT_OUT_FRAME", level="error", where=_c(t["bbox"]), msg="«%s» за рамкой листа" % _s(t["content"])))
    # --- viewports
    vps = viewports(layout)
    for i in range(len(vps)):
        for j in range(i + 1, len(vps)):
            if vps[i].intersection(vps[j]).area > 1.0:
                issues.append(dict(code="VIEWPORT_OVERLAP", level="error", where=_c(vps[i].bounds), msg="видовые экраны перекрываются"))
    for t in texts:
        for v in vps:
            if v.buffer(0.01).contains(t["geom"]) and t["geom"].bounds and _touch(t["geom"].bounds, v.bounds, 0.25):
                issues.append(dict(code="TEXT_AT_VP_EDGE", level="warning", where=_c(t["bbox"]),
                                   msg="«%s» у границы видового экрана — возможно обрезан" % _s(t["content"])))
    # --- tables / legends over drawings
    table_layers = ("SD_Таблицы",)
    table_geo = unary_union([f[0].buffer(0.3) for f in rec.fills if f[2] in table_layers] +
                            [l[0].buffer(0.3) for l in rec.lines if l[2] in table_layers])
    model_ink = []
    for f in rec.fills:
        if f[2] not in table_layers and f[2] not in ("SD_Рамка", "SD_Штамп") and any(v.contains(f[0].representative_point()) for v in vps):
            model_ink.append(f[0])
    for l in rec.lines:
        if l[2] not in table_layers and l[2] not in ("SD_Рамка", "SD_Штамп") and any(v.contains(l[0].representative_point()) for v in vps):
            model_ink.append(l[0].buffer(0.1))
    if not table_geo.is_empty and model_ink:
        ink = unary_union(model_ink)
        for comp in (table_geo.geoms if hasattr(table_geo, "geoms") else [table_geo]):
            env = comp.envelope
            if env.area < 20:
                continue
            a = ink.intersection(env).area if not ink.is_empty else 0
            if a > 2.0:
                issues.append(dict(code="TABLE_ON_DRAWING", level="error", where=_c(env.bounds),
                                   msg="таблица/легенда перекрывает чертёж (%.0f мм²)" % a))
    # --- dark foreign lines through text cores
    dark_lines = [l for l in rec.lines if _lum(l[1]) < 0.55]
    if dark_lines:
        ltree = STRtree([l[0] for l in dark_lines])
        for t in texts:
            x0, y0, x1, y1 = t["bbox"]
            h = y1 - y0
            w = x1 - x0
            if w < 0.5 or h < 0.5:
                continue
            core = box(x0 + 0.08 * w, y0 + 0.3 * h, x1 - 0.08 * w, y1 - 0.3 * h) if w >= h else \
                box(x0 + 0.3 * w, y0 + 0.08 * h, x1 - 0.3 * w, y1 - 0.08 * h)
            n = 0
            cross = []
            zone = box(x0, y0, x1, y1).buffer(2.5)
            for j in ltree.query(core):
                ln, col, lay, hnd, od = dark_lines[int(j)]
                seg = ln.intersection(core)
                if seg.length <= 0.6:
                    continue
                if od < t["order"]:
                    m = masked(seg.buffer(0.05), od, t["order"])
                    if not m.is_empty and m.contains(seg):
                        continue
                n += 1
                near = ln.intersection(zone)
                for part in (near.geoms if hasattr(near, "geoms") else [near]):
                    if part.geom_type == "LineString" and part.length > 0:
                        cross.append([(round(x, 2), round(y, 2)) for x, y in part.coords])
            if n:
                issues.append(dict(code="LINE_THROUGH_TEXT", level="warning", where=_c(t["bbox"]),
                                   msg="через «%s» проходит линия (%d)" % (_s(t["content"]), n),
                                   bbox=[round(v, 2) for v in t["bbox"]], cross=cross))
    return issues, rec


def _touch(b, v, tol):
    return (abs(b[0] - v[0]) < tol or abs(b[2] - v[2]) < tol or abs(b[1] - v[1]) < tol or abs(b[3] - v[3]) < tol)


def _c(b):
    return [round((b[0] + b[2]) / 2, 1), round((b[1] + b[3]) / 2, 1)]


def _s(s, n=40):
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def check_doc(doc, layouts=None, unframed=("01", "02")):
    report = {}
    for name in doc.layouts.names_in_taborder():
        if name == "Model":
            continue
        if layouts and name not in layouts:
            continue
        lay = doc.layouts.get(name)
        framed = not any(name.startswith(u + " ") for u in unframed)
        issues, _ = check_layout(doc, lay, framed)
        report[name] = issues
    return report


def summary(report):
    e = sum(1 for v in report.values() for i in v if i["level"] == "error")
    w = sum(1 for v in report.values() for i in v if i["level"] == "warning")
    return e, w


def print_report(report, max_per_sheet=25):
    e, w = summary(report)
    print("QA: ошибок %d, предупреждений %d" % (e, w))
    for name, issues in report.items():
        if not issues:
            continue
        print("== %s" % name)
        for i in sorted(issues, key=lambda x: (x["level"] != "error", x["code"]))[:max_per_sheet]:
            print("  [%s] %s @%s  %s" % ("E" if i["level"] == "error" else "w", i["code"], i["where"], i["msg"]))
