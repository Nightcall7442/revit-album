# -*- coding: utf-8 -*-
"""Plan sheets (1:50 / 1:75 / 1:100): measured, partitions, furniture, floors, ceilings, lighting,
sockets, plumbing, wall finishes. Every label goes through the collision registry."""
import math
from shapely.geometry import Polygon, box, LineString, Point, MultiPoint
from shapely.ops import unary_union

from . import gfx as S
from . import symbols as Y
from . import dims as DM
from .album import Column, BRONZE
from .placer import Occ, place_text, text_geom, grid_candidates, ring_candidates
from .model import fmt_area

TILE_KINDS = ("tile",)


def node_sheet(A):
    """Sheet number of the ceiling nodes sheet (callouts must point to it, not to the first elevation)."""
    for no, key, title, scale, fn, arg in A.sheets:
        if getattr(fn, "__name__", "") == "nodes_sheet":
            return no
    return None


def has_data(A, key):
    P = A.P
    return {
        "partitions": bool(P.parts) or bool(P.boxes),
        "furniture": bool(P.furniture),
        "floors": bool(P.floors),
        "ceilings": bool(P.rooms),
        "lighting": bool(P.lighting),
        "sockets": bool(P.sockets),
        "plumbing": bool(P.plumbing),
        "finishes": bool(P.rooms),
        "windows": any(t.get("division") for t in P.opening_types.values()),
    }.get(key, True)


def sc(A, v):
    """Distance given for 1:50 scaled to the current plan scale (keeps paper spacing constant)."""
    return v * A.plan_k / 50.0


def reg_walls(A, occ, parts=True):
    occ.add(A.P.shell_cut, "wall")
    for o in A.P.openings:                      # window / door openings carry no text either
        occ.add(A.P.open_shape[o["id"]], "opening")
    if parts:
        for g in A.P.parts.values():
            occ.add(g, "wall")


def reg_swings(A, occ):
    for o in A.P.openings:
        if o["kind"] in ("door", "balcony"):
            try:
                occ.add(Y.door_swing_area(A.P, o), "swing")
            except Exception:
                pass


def outer(A, sp, occ, sides=("B", "L"), openings=True):
    if A.P.grid.get("auto"):
        # axes guessed by the agent and the outer faces of a model's walls are not dimensions anyone can build by:
        # the plan is dimensioned in clear from the room faces (measured plan), lesson L-103
        return
    k = A.plan_k
    axes = bool(A.P.grid.get("x"))
    if axes:
        for g in Y.draw_axes(sp, A.P, k, sides=tuple(s for s in sides if s in "BL"), off_b=sc(A, 1800), off_l=sc(A, 1450)):
            occ.add(g, "axis")
    DM.outer_chains(sp, A.P, k, occ, sides=sides, openings=openings, axes=axes, first=sc(A, 700), step=sc(A, 400),
                    first_far=sc(A, 450))


# ------------------------------------------------------------------ room tags
def _split_name(name, maxw, h):
    if "|" in name:
        return name.split("|")
    if S.tw(name, h, True) <= maxw or " " not in name and "-" not in name:
        return [name]
    if " " in name:
        a, b = name.split(" ", 1)
        return [a, b]
    a, b = name.split("-", 1)
    return [a + "-", b]


def room_tags(A, sp, occ, style="compact", extra=None):
    P, k = A.P, A.plan_k
    ov = P.overrides.get("tag_pos", {})
    h1, h2, r, gap = 2.0 * k, 1.75 * k, 1.7 * k, 0.9 * k
    ww_of, hh_of = {}, {}
    for rm in P.rooms:
        rx0, ry0, rx1, ry1 = rm["shp"].bounds
        lines = _split_name(rm.get("label", rm["name"]), (rx1 - rx0) * 0.55, h1)
        area_s = fmt_area(rm["area"]) + " м²"
        ex = extra(rm) if extra else None
        tw_ = max([S.tw(t, h1, True) for t in lines] + [S.tw(area_s, h2)] + ([S.tw(ex, h2)] if ex else []))
        n = len(lines)
        hh = n * h1 * 1.3 + h2 * 1.75 + (h2 * 1.45 if ex else 0)
        ww = 2 * r + gap + tw_ + 0.4 * k
        region = rm["shp"].buffer(-0.8 * k)
        if region.is_empty:
            continue
        if rm["name"] in ov:
            cands = [tuple(ov[rm["name"]])]
        else:
            cands = grid_candidates(region, max(150.0, 0.18 * min(rx1 - rx0, ry1 - ry0)))[:400]
        best = None
        for c in cands:
            g = box(c[0] - ww / 2, c[1] - hh / 2, c[0] + ww / 2, c[1] + hh / 2)
            pen = 0.0 if region.contains(g) else g.difference(region).area * 4
            score = pen + occ.overlap(g, ignore=("rug",))
            if score <= 1e-6:
                best = (0, c, g)
                break
            if best is None or score < best[0]:
                best = (score, c, g)
        _, c, g = best
        if g.difference(region).area > 0.15 * g.area:   # a WC cubicle at 1:100: only the number (name, area -
            cs_ = grid_candidates(region, 60.0)[:400] or [(region.representative_point().x, region.representative_point().y)]
            bc = None                                     # in the explication / tables)
            for c2 in cs_:
                g2 = Point(c2).buffer(r * 1.15)
                sc2 = occ.overlap(g2, ignore=("rug",)) + g2.difference(rm["shp"]).area * 4
                if bc is None or sc2 < bc[0]:
                    bc = (sc2, c2, g2)
                if sc2 <= 1e-6:
                    break
            _, c2, g2 = bc

            def draw_small(c2=c2, rm=rm):
                S.fill(sp, Point(c2).buffer(r * 1.1), (255, 255, 255), "SD_Текст")
                Y.mark_circle(sp, rm["num"], c2, k, r=1.7, h=1.8)
            occ.defer(draw_small)
            occ.add(g2, "tag")
            continue

        def draw(c=c, g=g, lines=lines, n=n, area_s=area_s, ex=ex, rm=rm):
            left = c[0] - ww_of[id(rm)] / 2
            top = c[1] + hh_of[id(rm)] / 2
            S.fill(sp, g.buffer(0.3 * k, join_style=2), (255, 255, 255), "SD_Текст")
            Y.mark_circle(sp, rm["num"], (left + r, c[1]), k, r=1.7, h=1.8)
            for i, t in enumerate(lines):
                S.text(sp, t, (left + 2 * r + gap, top - (i + 0.55) * h1 * 1.3), h1, "MIDDLE_LEFT", bold=True)
            S.text(sp, area_s, (left + 2 * r + gap, top - n * h1 * 1.3 - h2 * 1.0), h2, "MIDDLE_LEFT", rgb=(95, 95, 95))
            if ex:
                S.text(sp, ex, (left + 2 * r + gap, top - n * h1 * 1.3 - h2 * 2.45), h2, "MIDDLE_LEFT", rgb=(120, 120, 120))
        ww_of[id(rm)], hh_of[id(rm)] = ww, hh
        occ.defer(draw)
        occ.add(g.buffer(0.3 * k), "tag")


def tag_near(A, sp, occ, s, p, h=1.9, dists=(0.0, 4.0, 7.0, 10.0, 14.0), bold=False, n=16, kind="tag"):
    """Boxed label (white box + thin border) at the first free position around p."""
    k = A.plan_k
    w = S.tw(s, h * k, bold) + 1.6 * k
    hh = h * k + 1.4 * k
    best = None
    for d in dists:
        for c in ([p] if d == 0 else ring_candidates(p, [d * k], n)):
            g = box(c[0] - w / 2, c[1] - hh / 2, c[0] + w / 2, c[1] + hh / 2)
            sc_ = occ.overlap(g.buffer(0.3 * k))
            if best is None or sc_ < best[0]:
                best = (sc_, c)
            if sc_ <= 1e-6:
                break
        if best[0] <= 1e-6:
            break
    c = best[1]
    g = box(c[0] - w / 2, c[1] - hh / 2, c[0] + w / 2, c[1] + hh / 2)
    occ.defer(lambda: Y.tag_box(sp, s, c, k, h=h, bold=bold))
    occ.add(g.buffer(0.4 * k), kind)
    return g


def label_near(A, sp, occ, s, p, h=1.9, dists=(2.5, 4.0, 6.0, 8.5), rot=0.0, bold=False, rgb=None, mask=True, n=16):
    """Label next to a point; when every near place is taken (a crowded corner of a 1:100 plan) the label goes
    further out with a thin leader instead of lying on a wall or another text (lesson L-066)."""
    k = A.plan_k
    c = [(p[0], p[1])] + ring_candidates(p, [d * k for d in dists], n)
    res = place_text(sp, occ, s, c, h * k, "MIDDLE_CENTER", rot, bold, rgb, mask=mask, force=False)
    if res is not None:
        return res
    far = ring_candidates(p, [d * k for d in (max(dists) + 3.5, max(dists) + 7.0, max(dists) + 11.0, max(dists) + 16.0)], 24)
    res = place_text(sp, occ, s, c + far, h * k, "MIDDLE_CENTER", rot, bold, rgb, mask=mask)
    if res and math.hypot(res[0][0] - p[0], res[0][1] - p[1]) > (max(dists) + 1.0) * k:
        q = res[1].exterior.interpolate(res[1].exterior.project(Point(p)))
        S.line(sp, (q.x, q.y), p, "SD_Тонкие", (90, 90, 90), 9)
        occ.add(LineString([(q.x, q.y), p]).buffer(0.2 * k), "leader")
    return res


# ------------------------------------------------------------------ 04 measured plan
def measured(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Существующее положение. Размеры в мм по чистовым поверхностям несущих стен")
    S.fill(sp, P.shell_cut, S.C_WALL, "SD_Стены")
    Y.outline(sp, P.shell_cut, (20, 20, 20), 35)
    for g in P.parts.values():
        Y.dashed_shape(sp, g, 1.2 * k, 0.7 * k, (150, 150, 155), 13)
    reg_walls(A, occ, parts=False)
    ex_walls = {w["id"] for w in P.walls if w["kind"] == "existing"}
    for o in P.openings:
        if o["wall"] not in ex_walls:
            continue
        if o["kind"] in ("window", "balcony"):
            Y.draw_window(sp, P, o, k)
            if o["kind"] == "balcony":
                occ.add(Y.door_swing_area(P, o), "swing")
        elif o["kind"] == "door" and o.get("existing_leaf"):
            Y.draw_door(sp, P, o, k)
            occ.add(Y.door_swing_area(P, o), "swing")
    Y.draw_overhead(sp, P, k)
    outer(A, sp, occ, sides=("B", "L", "T", "R"))
    # clear dimensions of the existing spaces (split at wall gaps), one width/length per future room
    outline = DM.outline_of(P)
    rows = []
    from shapely.ops import polylabel
    for i, (g, rms) in enumerate(P.existing_spaces()):
        space_tag = ("пом. " + ", ".join(r["num"] for r in rms)) if rms else "пространство %d" % (i + 1)
        seeds = [(polylabel(r["shp"], 10), "%s «%s»" % (r["num"], r["name"])) for r in rms] or [(polylabel(g, 10), space_tag)]
        done = {"h": [], "v": []}
        for c, tag in seeds:
            for horiz in (True, False):
                key = "h" if horiz else "v"
                best = None
                for d in (0, 350, -350, 700, -700, 1050, -1050, 1400, -1400):
                    if horiz:
                        yy = c.y + d
                        ln = LineString([(g.bounds[0] - 1, yy), (g.bounds[2] + 1, yy)]).intersection(g)
                    else:
                        xx = c.x + d
                        ln = LineString([(xx, g.bounds[1] - 1), (xx, g.bounds[3] + 1)]).intersection(g)
                    segs = [s_ for s_ in (ln.geoms if hasattr(ln, "geoms") else [ln]) if s_.length > 10]
                    if not segs:
                        continue
                    seg = min(segs, key=lambda s_: s_.distance(c))
                    if best is None:
                        ref = seg.length
                    elif abs(seg.length - ref) > 5:
                        continue
                    sc_ = occ.overlap(seg.buffer(DM.TXT * k * 1.4), ignore=("wallzone",))
                    if best is None or sc_ < best[0] - 1e-6:
                        best = (sc_, d, seg)
                    if sc_ <= 1e-6:
                        break
                if not best:
                    continue
                _, d, seg = best
                b_ = seg.bounds
                ext = (b_[0], b_[2]) if horiz else (b_[1], b_[3])
                if any(abs(ext[0] - e0) < 30 and abs(ext[1] - e1) < 30 for e0, e1 in done[key]):
                    continue
                done[key].append(ext)
                pos = b_[1] if horiz else b_[0]
                DM.chain(sp, list(ext), pos, pos, k, occ, vertical=not horiz)
                rows.append(["%d" % (len(rows) + 1), "%s в чистоте, %s" % ("Ширина" if horiz else "Длина", tag),
                             "%d" % round(ext[1] - ext[0])])
        pl = polylabel(g, 10)
        tag_near(A, sp, occ, "Н = %d" % P.slab, (pl.x, pl.y), h=2.0, bold=True)
    # interior openings and passages: width + binding to the walls of the space (lesson L-032)
    spaces = [g for g, _ in P.existing_spaces()]
    out_ext = outline.exterior
    items = [(P.open_shape[o["id"]], o) for o in P.openings
             if o["wall"] in ex_walls and (P.grid.get("auto") or P.open_shape[o["id"]].distance(out_ext) > 5)]
    items += [(g, None) for g in getattr(P, "passages", [])]
    faces_ = {}
    for rect, o in items:
        x0, y0, x1, y1 = rect.bounds
        vert = (x1 - x0) < (y1 - y0)                    # opening in a vertical wall: width along y
        best = None
        for face, sg in (((x0, -1), (x1, 1)) if vert else ((y0, -1), (y1, 1))):
            probe = LineString([(face + sg * 2, y0 - 1e5), (face + sg * 2, y1 + 1e5)]) if vert else \
                LineString([(x0 - 1e5, face + sg * 2), (x1 + 1e5, face + sg * 2)])
            for g in spaces:
                ln = probe.intersection(g)
                for seg in (ln.geoms if hasattr(ln, "geoms") else [ln]):
                    if seg.is_empty or seg.length < 10:
                        continue
                    b_ = seg.bounds
                    lo, hi = (b_[1], b_[3]) if vert else (b_[0], b_[2])
                    a_, b2 = (y0, y1) if vert else (x0, x1)
                    if lo - 5 <= a_ and b2 <= hi + 5 or (lo <= a_ <= hi or lo <= b2 <= hi):
                        if best is None or seg.length > best[0]:
                            best = (seg.length, face, sg, lo, hi)
        if best is None:
            continue
        _, face, sg, lo, hi = best
        a_, b2 = (y0, y1) if vert else (x0, x1)
        key = (vert, round(face), sg, round(lo), round(hi))   # every opening of one wall face: ONE chain
        grp = faces_.setdefault(key, set([round(lo), round(hi)]))
        grp.update([round(a_), round(b2)])
        if o is None:
            bh = [z.get("bottom") for z in P.ceilings.get("zones", []) if z.get("bottom")
                  and Polygon(z["poly"]).buffer(5).contains(rect.centroid)]
            s_ = "проём %d" % round(b2 - a_) + (", низ короба %+.3f" % (bh[0] / 1000.0) if bh else "")
            c = rect.centroid
            label_near(A, sp, occ, s_.replace(".", ","), (c.x, c.y), h=1.8, dists=(4.0, 6.0, 8.0, 11.0),
                       rot=90 if vert else 0, bold=True)
    for (vert, face, sg, lo, hi), vals in faces_.items():
        DM.chain(sp, sorted(vals), face + sg * sc(A, 420), face, k, occ, vertical=vert, merge=20)
    # thickness of interior bearing walls
    for w in P.walls:
        if w["kind"] != "existing":
            continue
        if P.grid.get("auto") and w["shape"].exterior.distance(outline.exterior) < 1:
            continue                     # a model's outer wall / pilaster: its thickness is the modeller's, not a size
        g = w["shape"]
        x0, y0, x1, y1 = g.bounds
        if not outline.buffer(-5).contains(g.centroid) or g.buffer(5).difference(P.shell).area < 1:
            pass
        if g.exterior.distance(outline.exterior) < 1 and g.length > 0:
            touch = g.intersection(outline.exterior.buffer(2)).length
            if touch > 0.6 * max(x1 - x0, y1 - y0):
                continue
        if w["dir"] == "V":
            yy = (y0 + y1) / 2
            DM.chain(sp, [x0, x1], yy, yy, k, occ)
        else:
            xx = (x0 + x1) / 2
            DM.chain(sp, [y0, y1], xx, xx, k, occ, vertical=True)
    # opening tags
    for o in P.openings:
        if o["wall"] not in ex_walls:
            continue
        r = P.open_shape[o["id"]]
        c = r.centroid
        if o["kind"] == "window":
            s = "%s %d×%d, низ %+.3f" % (o.get("mark", ""), o["w"], o["h"], o["sill"] / 1000.0)
        else:
            s = "%s %d×%d" % (o.get("mark", "проём"), o["w"], o["h"])
        s = s.replace(".", ",").strip()
        w = P.wall_by_id[o["wall"]]
        rot = 0 if w["dir"] == "H" else 90
        label_near(A, sp, occ, s, (c.x, c.y), h=1.8, dists=(4.0, 6.0, 8.0, 11.0), rot=rot, bold=True)
    for rm in P.rooms[:0]:
        pass
    col = Column(A, psp)
    col.legend([
        (_lg_fill(S.C_WALL, (20, 20, 20)), "Существующие несущие стены"),
        (_lg_line((150, 150, 155), 18, True), "Проектные перегородки (для ориентации)"),
        (_lg_window, "Оконный / балконный блок"),
        (_lg_line((140, 140, 140), 13, True), "Конструкции над плоскостью разреза"),
    ])
    rows.append(["%d" % (len(rows) + 1), "Высота от пола до плиты", "%d" % P.slab])
    col.table([10, 62, 37], ["№", "Контрольный размер", "Значение, мм"], rows, title="Контрольные размеры", h=1.8,
              aligns=["C", "L", "C"])
    col.notes(A.note_lines("measured", [
        "План выполнен по исходным данным заказчика (3D-модель / обмер). Привязка - пересечение осей.",
        "До начала работ выполнить контрольный обмер; при расхождении более 20 мм сообщить дизайнеру.",
        "Размеры - в миллиметрах, отметки - от уровня чистого пола.",
        "Перегородки показаны пунктиром только для ориентации.",
    ]))


def _lg_fill(rgb, outline=(40, 40, 40), hatch=None, hatch_rgb=None, w=12, h=3.6):
    def fn(psp, cx, cy):
        pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
        S.fill(psp, pts, rgb, "SD_Таблицы")
        if hatch:
            S.hatch(psp, pts, hatch_rgb or outline, hatch, scale=0.35, layer="SD_Таблицы")
        S.poly(psp, pts, "SD_Таблицы", True, outline, 18)
    return fn


def _lg_line(rgb, lw=35, dashed=False):
    def fn(psp, cx, cy):
        if dashed:
            Y.dashed(psp, (cx - 7, cy), (cx + 7, cy), 1.4, 0.8, rgb, lw, "SD_Таблицы")
        else:
            S.line(psp, (cx - 7, cy), (cx + 7, cy), "SD_Таблицы", rgb, lw)
    return fn


def _lg_window(psp, cx, cy):
    S.rect(psp, cx - 7, cy - 1.2, cx + 7, cy + 1.2, "SD_Таблицы", (30, 30, 30), 18)
    S.line(psp, (cx - 7, cy), (cx + 7, cy), "SD_Таблицы", (30, 30, 30), 9)


def _lg_sym(fn_):
    def fn(psp, cx, cy):
        fn_(psp, cx, cy)
    return fn


# ------------------------------------------------------------------ 05 partitions
def _interior_wo_parts(P):
    return DM.outline_of(P).difference(P.shell)


def partitions(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Возводимые перегородки и короба. Размеры - по черновым поверхностям")
    S.fill(sp, P.shell_cut, (110, 110, 114), "SD_Стены")
    Y.outline(sp, P.shell_cut, (40, 40, 40), 25)
    Y.draw_walls(sp, P, k, shell_rgb=(110, 110, 114), part_mode="new", show_boxes=True)
    reg_walls(A, occ)
    for b in P.boxes:
        occ.add(b["shape"], "wall")
    for o in P.openings:
        if o["kind"] == "window" or o["kind"] == "balcony":
            Y.draw_window(sp, P, o, k)
        elif o["kind"] == "door":
            r = P.opening_rect(o)
            S.line(sp, (r[0], r[1]), (r[2], r[3]), "SD_Тонкие", (150, 150, 150), 9)
            S.line(sp, (r[0], r[3]), (r[2], r[1]), "SD_Тонкие", (150, 150, 150), 9)
            occ.add(box(*r), "wall")
    Y.draw_overhead(sp, P, k)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    region = _interior_wo_parts(P)
    new_ids = list(P.parts.keys())
    for wid in new_ids:
        w = P.wall_by_id[wid]
        x0, y0, x1, y1 = w["shape"].bounds
        ops = [o for o in P.openings if o["wall"] == wid]
        # position along the wall free of openings for the across-chain
        if w["dir"] == "V":
            span = [y0, y1]
            free_pts = [y0 + (y1 - y0) * f for f in (0.3, 0.7, 0.5, 0.15, 0.85)]
            free_pts = [y for y in free_pts if not any(o["c"] - o["w"] / 2 - 50 < y < o["c"] + o["w"] / 2 + 50 for o in ops)] or [(y0 + y1) / 2]
            yy = free_pts[0]
            ln = LineString([(-1e6, yy), (1e6, yy)]).intersection(region)
            seg = _seg_containing(ln, ((x0 + x1) / 2, yy))
            if seg is not None:
                b = seg.bounds
                DM.chain(sp, [b[0], x0, x1, b[2]], yy, yy, k, occ)
            # along-chain
            ax = LineString([((x0 + x1) / 2, -1e6), ((x0 + x1) / 2, 1e6)]).intersection(region.union(w["shape"]))
            sg = _seg_containing(ax, ((x0 + x1) / 2, (y0 + y1) / 2))
            vals = [y0, y1] + [v for o in ops for v in (o["c"] - o["w"] / 2, o["c"] + o["w"] / 2)]
            if sg is not None:
                vals += [sg.bounds[1], sg.bounds[3]]
            side = _free_side(occ, w["shape"], "V", k)
            pos = (x1 + sc(A, 450)) if side > 0 else (x0 - sc(A, 450))
            DM.chain(sp, vals, pos, x1 if side > 0 else x0, k, occ, vertical=True)
        else:
            xs = [x0 + (x1 - x0) * f for f in (0.3, 0.7, 0.5, 0.15, 0.85)]
            xs = [x for x in xs if not any(o["c"] - o["w"] / 2 - 50 < x < o["c"] + o["w"] / 2 + 50 for o in ops)] or [(x0 + x1) / 2]
            xx = xs[0]
            ln = LineString([(xx, -1e6), (xx, 1e6)]).intersection(region)
            seg = _seg_containing(ln, (xx, (y0 + y1) / 2))
            if seg is not None:
                b = seg.bounds
                DM.chain(sp, [b[1], y0, y1, b[3]], xx, xx, k, occ, vertical=True)
            ax = LineString([(-1e6, (y0 + y1) / 2), (1e6, (y0 + y1) / 2)]).intersection(region.union(w["shape"]))
            sg = _seg_containing(ax, ((x0 + x1) / 2, (y0 + y1) / 2))
            vals = [x0, x1] + [v for o in ops for v in (o["c"] - o["w"] / 2, o["c"] + o["w"] / 2)]
            if sg is not None:
                vals += [sg.bounds[0], sg.bounds[2]]
            side = _free_side(occ, w["shape"], "H", k)
            pos = (y1 + sc(A, 450)) if side > 0 else (y0 - sc(A, 450))
            DM.chain(sp, vals, pos, y1 if side > 0 else y0, k, occ)
    for b in P.boxes:
        x0, y0, x1, y1 = b["shape"].bounds
        kind = b.get("box")
        if kind == "column":
            continue                              # the size is in the callout: a 400 chain at a column is noise
        if kind == "bar" or (x1 - x0) >= (y1 - y0):
            side = _free_side(occ, b["shape"], "H", k)
            DM.chain(sp, [x0, x1], (y1 + sc(A, 350)) if side > 0 else (y0 - sc(A, 350)), y1 if side > 0 else y0, k, occ)
        if kind == "bar" or (x1 - x0) < (y1 - y0):
            side = _free_side(occ, b["shape"], "V", k)
            DM.chain(sp, [y0, y1], (x1 + sc(A, 350)) if side > 0 else (x0 - sc(A, 350)), x1 if side > 0 else x0, k, occ,
                     vertical=True)
    # marks and opening sizes
    for wid in new_ids:
        w = P.wall_by_id[wid]
        c = w["shape"].centroid
        _mark_box(A, sp, occ, wid, (c.x, c.y), S.C_RED)
    for b in sorted(P.boxes, key=lambda b: b["shape"].area):       # small ones first: they have fewer places
        _box_callout(A, sp, occ, b)
    for o in P.openings:
        if o["kind"] != "door" or o["wall"] not in P.parts:
            continue
        r = P.open_shape[o["id"]].centroid
        w = P.wall_by_id[o["wall"]]
        label_near(A, sp, occ, "%d×%d" % (o["w"], o["h"]), (r.x, r.y), h=1.9, rot=0 if w["dir"] == "H" else 90, bold=True,
                   dists=(3.0, 4.5, 6.5))
    col = Column(A, psp)
    lg = [(_lg_fill((110, 110, 114), (40, 40, 40)), "Существующие несущие стены")]
    if new_ids:
        lg.append((_lg_fill((253, 232, 232), S.C_RED, "ANSI31", S.C_RED), "Возводимые перегородки"))
    if any(b.get("box") != "bar" for b in P.boxes):
        lg.append((_lg_fill((226, 238, 252), S.C_BLUE, "ANSI37", S.C_BLUE), "Короба, облицовки ГКЛВ по металлокаркасу"))
    if any(b.get("box") == "bar" for b in P.boxes):
        lg.append((_lg_fill((238, 244, 252), S.C_BLUE, "ANSI31", S.C_BLUE), "Каркас барной стойки (возводится до чистовой отделки)"))
    lg.append((_lg_door_cross, "Дверной проём (ширина × высота)"))
    col.legend(lg)
    rows, tot = [], 0.0
    for wid in new_ids:
        w = P.wall_by_id[wid]
        x0, y0, x1, y1 = w["shape"].bounds
        L = max(x1 - x0, y1 - y0)
        hgt = w.get("h", P.slab)
        ops = [o for o in P.openings if o["wall"] == wid]
        a = round(L * hgt / 1e6 - sum(o["w"] * o["h"] for o in ops) / 1e6, 2)
        tot += a
        rows.append([wid, w.get("material", "Перегородка %d мм" % w["t"]), "%d" % L, "%d" % hgt, fmt_area(a),
                     ", ".join("%s %d×%d" % (o.get("mark", ""), o["w"], o["h"]) for o in ops) or "-"])
    if rows:
        col.table([9, 39, 12, 11, 13, 25], ["Марка", "Конструкция", "Длина", "Высота", "Площадь, м²", "Проёмы"], rows,
                  title="Ведомость перегородок", h=1.6, aligns=["C", "L", "C", "C", "C", "L"],
                  total=["", "Итого перегородок (%s)" % ", ".join(new_ids), "", "", fmt_area(tot), ""])
    brows, btot = [], 0.0
    for b in P.boxes:
        x0, y0, x1, y1 = b["shape"].bounds
        a = round(box_sheathing(P, b), 2)
        btot += a
        txt = b.get("name") or BOX_SHORT.get(b.get("box"), "Короб")
        if b.get("material"):
            txt += ". " + b["material"]
        if b.get("note"):
            txt += " (%s)" % b["note"]
        brows.append([b["id"], txt, "%d×%d" % (round(x1 - x0), round(y1 - y0)), "%d" % b.get("h", 1200), fmt_area(a)])
    if brows:
        col.table([10, 63, 14, 10, 12], ["Марка", "Короб, конструкция", "В плане, мм", "Высота", "Обшивка, м²"],
                  brows, title="Ведомость коробов и облицовок", h=1.45, aligns=["C", "L", "C", "C", "C"],
                  total=["", "Итого обшивки", "", "", fmt_area(btot)])
    t_mm = max([P.wall_by_id[w]["t"] for w in new_ids] or [100]) - 20
    notes = []
    if new_ids:
        notes += ["Кладка на клей для ячеистого бетона, армирование через 2 ряда; примыкания - гибкие связи через 2 ряда.",
                  "Зазор у перекрытия 20 мм - монтажная пена и демпферная лента.",
                  "Перемычки над проёмами - армированные U-блоки или уголок, опирание не менее 250 мм.",
                  "Объём кладки с запасом 5 %%: %s м³ (толщина блока %d мм)." % (fmt_area(tot * t_mm / 1000.0 * 1.05), t_mm)]
    if P.boxes:
        notes += ["Короба - после разводки сетей и опрессовки; каркасы инсталляций, стойки бара и оснований диванов "
                  "крепятся к основанию пола до стяжки. Под плитку - ГКЛВ / ЦСП в два слоя."]
    col.notes(A.note_lines("partitions", notes))


def _lg_door_cross(psp, cx, cy):
    S.rect(psp, cx - 6, cy - 2, cx + 6, cy + 2, "SD_Таблицы", (120, 120, 120), 13)
    S.line(psp, (cx - 6, cy - 2), (cx + 6, cy + 2), "SD_Таблицы", (120, 120, 120), 9)
    S.line(psp, (cx - 6, cy + 2), (cx + 6, cy - 2), "SD_Таблицы", (120, 120, 120), 9)


def _seg_containing(ln, p, tol=200):
    if ln.is_empty:
        return None
    segs = [s for s in (ln.geoms if hasattr(ln, "geoms") else [ln]) if s.geom_type == "LineString"]
    best = None
    for s in segs:
        d = s.distance(Point(p))
        if best is None or d < best[0]:
            best = (d, s)
    return best[1] if best and best[0] < tol else None


def _free_side(occ, g, d, k):
    x0, y0, x1, y1 = g.bounds
    if d == "V":
        a = occ.overlap(box(x1, y0, x1 + 25 * k, y1))
        b = occ.overlap(box(x0 - 25 * k, y0, x0, y1))
    else:
        a = occ.overlap(box(x0, y1, x1, y1 + 25 * k))
        b = occ.overlap(box(x0, y0 - 25 * k, x1, y0))
    return 1 if a <= b else -1


BOX_SHORT = {"install": "Короб инсталляции", "pipe": "Короб для труб", "column": "Облицовка колонны",
             "bar": "Каркас барной стойки", "seat": "Короб-основание дивана (м/к, плитка)", "low": "Короб ГКЛВ",
             "lining": "Фальш-стена (короб)"}


def box_label(b):
    """'К-1 Короб инсталляции, h=1000' / 'К-3 Облицовка колонны 410×410, h=3000'"""
    kind = b.get("box", "low")
    s = "%s %s" % (b["id"], BOX_SHORT.get(kind, "Короб"))
    if kind == "column":
        x0, y0, x1, y1 = b["shape"].bounds
        s += " %d×%d" % (round(x1 - x0), round(y1 - y0))
    return s + ", h=%d" % b.get("h", 1200)


def _box_callout(A, sp, occ, b):
    """Callout of a box like the studio draws it: a dot on the box, a leader to a shelf, the text on the shelf - placed
    where it covers nothing (outside the plan when the inside is busy)."""
    k = A.plan_k
    h = 1.8 * k
    s = box_label(b)
    shp = b["shape"].difference(A.P.mass)
    if shp.is_empty:
        shp = b["shape"]
    a = shp.representative_point()
    ax, ay = a.x, a.y
    w = S.tw(s, h) + 0.8 * k
    best = None
    for dd in (6, 9, 13, 18, 24, 32, 42, 55):
        for i in range(16):
            ang = 2 * math.pi * i / 16
            cx, cy = ax + dd * k * math.cos(ang), ay + dd * k * math.sin(ang)
            right = math.cos(ang) >= -1e-6
            x0 = cx if right else cx - w
            tg = box(x0, cy, x0 + w, cy + 1.6 * h)
            ld = LineString([(ax, ay), (cx, cy)])
            sc_ = occ.overlap(tg.buffer(0.3 * k)) + 0.3 * occ.overlap(ld.buffer(0.15 * k), ignore=("wall", "dim"))
            if best is None or sc_ < best[0] - 1e-6:
                best = (sc_, cx, cy, right, tg, ld)
            if sc_ <= 1e-6:
                break
        if best[0] <= 1e-6:
            break
    _, cx, cy, right, tg, ld = best
    x0 = cx if right else cx - w

    def draw(sp=sp, s=s, ax=ax, ay=ay, cx=cx, cy=cy, x0=x0, w=w, h=h):
        S.fill(sp, Point(ax, ay).buffer(0.45 * k), S.C_BLUE, "SD_Тонкие")
        S.line(sp, (ax, ay), (cx, cy), "SD_Тонкие", S.C_BLUE, 13)
        S.line(sp, (x0, cy), (x0 + w, cy), "SD_Тонкие", S.C_BLUE, 13)
        S.text(sp, s, (x0 + 0.4 * k, cy + 0.45 * k), h, "BOTTOM_LEFT", rgb=(25, 70, 140))
    occ.defer(draw)
    occ.add(tg.buffer(0.2 * k), "tag")
    occ.add(ld.buffer(0.15 * k), "leader")


def box_sheathing(P, b):
    """Area of the box faces to sheathe: sides not against a wall × height + the top of a low box, m²."""
    shp = b["shape"].difference(P.mass)
    if shp.is_empty:
        return 0.0
    walls = P.mass.buffer(3)
    free = shp.boundary.difference(walls)
    a = free.length * b.get("h", 1200)
    if b.get("h", 1200) < P.ceiling - 50 and b.get("box") != "bar":
        a += shp.area
    return a / 1e6


def _mark_box(A, sp, occ, s, p, rgb):
    k = A.plan_k
    h = 2.0 * k
    w = S.tw(s, h, True) + 1.6 * k
    hh = h + 1.4 * k
    cands = [p] + ring_candidates(p, [d * k for d in (4, 6, 9, 13)], 16)
    for c in cands:
        g = box(c[0] - w / 2, c[1] - hh / 2, c[0] + w / 2, c[1] + hh / 2)
        if occ.free(g, ignore=("wall",)) and occ.overlap(g) < 0.35 * g.area:
            break
    occ.defer(lambda: Y.tag_box(sp, s, c, k, h=2.0, txt_rgb=rgb, border=rgb, bold=True))
    occ.add(g.buffer(0.3 * k), "tag")


# ------------------------------------------------------------------ 06 furniture
def furniture_groups(P):
    groups = []
    for f in P.furniture:
        shp = Polygon(f["poly"]).buffer(0)
        x0, y0, x1, y1 = shp.bounds
        w, d = sorted([round((x1 - x0) / 10) * 10, round((y1 - y0) / 10) * 10], reverse=True)
        key = (f["name"], f.get("room"), w, d)
        for g in groups:
            if g["key"] == key:
                g["items"].append(f)
                break
        else:
            groups.append(dict(key=key, name=f["name"], room=f.get("room", ""), size="%d×%d" % (w, d), items=[f]))
    order = {r["name"]: int(r["num"]) if str(r["num"]).isdigit() else 99 for r in P.rooms}
    groups.sort(key=lambda g: (order.get(g["room"], 99), g["name"]))
    for i, g in enumerate(groups):
        g["pos"] = i + 1
    return groups


FLOOR_TINTS = [(234, 232, 226), (222, 233, 243), (241, 232, 214), (226, 238, 226), (233, 228, 241), (240, 236, 222)]
FLOOR_ZONE_TINT = (243, 214, 206)              # a zone of other tiles over the base (a strip, a bar zone)


def floor_tints(P):
    """Floor type id -> fill colour on the floor plan (a zone with its own outline gets the accent)."""
    out, i = {}, 0
    for f in P.floors:
        if f.get("polys"):
            out[f["id"]] = FLOOR_ZONE_TINT
        else:
            out[f["id"]] = FLOOR_TINTS[i % len(FLOOR_TINTS)]
            i += 1
    return out


def _darker(rgb, k=0.78):
    return tuple(int(c * k) for c in rgb)


def draw_floor_fill(A, sp, joints=True, tint=False):
    P = A.P
    tints = floor_tints(P) if tint else {}
    for f, g in P.floor_zones():
        if f["id"] in tints:
            S.fill(sp, g, tints[f["id"]], "SD_Штриховка")
        elif f.get("pattern") == "tile":
            S.fill(sp, g, Y.TILE, "SD_Штриховка")
        else:
            S.fill(sp, g, Y.PARQUET, "SD_Штриховка")
    if not joints:
        return
    for f, g in P.floor_zones():
        if f.get("pattern") == "tile":
            tw_, th_ = f.get("tile", [600, 600])
            jrgb = _darker(tints[f["id"]]) if f["id"] in tints else Y.TILE_J
            step = max(1, int(math.ceil(0.7 * A.plan_k / max(1.0, min(tw_, th_)))))   # joints closer than 0.7 mm: every n-th
            if f.get("origin"):                    # a zone of the model: tiles from its own corner
                S.grid_lines(sp, g, tw_ * step, th_ * step, origin=tuple(f["origin"]), rgb=jrgb)
                continue
            for rm in P.rooms:
                part = g.intersection(rm["shp"].buffer(250, join_style=2))
                others = unary_union([r2["shp"] for r2 in P.rooms if r2 is not rm])
                part = part.difference(others)
                if part.is_empty or part.area < 1e5:
                    continue
                org, _ = Y.tile_origin(P, rm["name"], part)
                S.grid_lines(sp, part, tw_ * step, th_ * step, origin=org, rgb=jrgb)
        elif f.get("pattern") == "model":
            continue                       # a covering of the model whose format is not known: no invented joints
        else:
            pl = f.get("plank", [1300, 160])
            Y.plank_lines(sp, g, plank_w=pl[1], plank_l=pl[0], along=f.get("along", "y"),
                          origin=tuple(f.get("origin", [P.bounds[0], P.bounds[1]])))


def furniture(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Расстановка мебели и оборудования. Позиции - см. спецификацию")
    draw_floor_fill(A, sp)
    Y.furniture_all(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k)
    Y.draw_overhead(sp, P, k)
    reg_walls(A, occ)
    reg_swings(A, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=True)
    groups = furniture_groups(P)
    ov = P.overrides.get("furn_mark", {})
    items = [f for g in groups for f in g["items"]]
    shapes = [Polygon(f["poly"]).buffer(0) for f in items]
    for i, (f, shp) in enumerate(zip(items, shapes)):
        if f.get("kind") != "rug":
            occ.add(shp, "furn#%d" % i)
    idx = {id(f): i for i, f in enumerate(items)}
    for g in groups:
        for f in g["items"]:
            i = idx[id(f)]
            shp = shapes[i]
            # a mark may sit on its own item and on items stacked with it (sink in a worktop, upper over base)
            own = ["furn#%d" % i, "rug"] + ["furn#%d" % j for j, o in enumerate(shapes)
                                            if j != i and o.intersection(shp).area > 0.3 * min(o.area, shp.area)]
            r = 1.55 * k
            key = "%s@%d,%d" % (f["name"], round(shp.centroid.x), round(shp.centroid.y))
            if key in ov:
                cands = [tuple(ov[key])]
            else:
                inner = shp.buffer(-r * 1.15)
                cands = grid_candidates(inner, max(60.0, r)) if not inner.is_empty else []
                c0 = shp.centroid
                cands += ring_candidates((c0.x, c0.y), [d * k for d in (3, 4.5, 6, 8)], 16)
            best = None
            for c in cands:
                gg = Point(c).buffer(r + 0.3 * k)
                sc_ = occ.overlap(gg, ignore=tuple(own))
                if f.get("kind") != "rug":
                    sc_ += gg.difference(shp).area * (0.0 if shp.buffer(-r * 1.15).contains(Point(c)) else 0.2)
                if best is None or sc_ < best[0]:
                    best = (sc_, c, gg)
                if sc_ <= 1e-6:
                    break
            _, c, gg = best
            if not shp.contains(Point(c)) and f.get("kind") != "rug":
                q = shp.exterior.interpolate(shp.exterior.project(Point(c)))
                S.line(sp, (q.x, q.y), c, "SD_Тонкие", BRONZE, 13)
            Y.mark_circle(sp, str(g["pos"]), c, k, r=1.55, h=1.7, rgb=BRONZE, txt_rgb=(60, 45, 20))
            occ.add(gg, "mark")
    room_tags(A, sp, occ)
    col = Column(A, psp)
    rows = [[str(g["pos"]), g["name"] + ("" if not any(f.get("item") for f in g["items"]) else
                                         " (эскиз %s)" % next(f["item"] for f in g["items"] if f.get("item"))),
             g["size"], str(len(g["items"])), g["room"]] for g in groups]
    col.table([9, 41, 21, 8, 30], ["Поз.", "Наименование", "Габариты, мм", "Кол.", "Помещение"], rows,
              title="Спецификация мебели и оборудования", h=1.6, aligns=["C", "L", "C", "C", "L"], zebra=True, head_h=6.0)
    col.notes(A.note_lines("furniture", [
        "Габариты - по исходной модели; модели мебели и оборудования уточнить при заказе.",
        "Корпусную мебель изготавливать по контрольным замерам после чистовой отделки.",
    ]))


# ------------------------------------------------------------------ 07 floors
def floors(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Покрытия пола, зоны и форматы плитки, раскладка, стыки. Отметки чистого пола")
    draw_floor_fill(A, sp, tint=True)
    tints = floor_tints(P)
    zones = P.floor_zones()
    # joints between different coverings
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            jl = zones[i][1].boundary.intersection(zones[j][1].buffer(8))
            for gg in (jl.geoms if hasattr(jl, "geoms") else [jl]):
                if gg.geom_type == "LineString" and gg.length > 50:
                    S.poly(sp, list(gg.coords), "SD_Акцент", False, BRONZE, 70)    # an L-shaped joint stays an L
    Y.draw_walls(sp, P, k, show_boxes=True)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)
    for b in P.boxes:
        occ.add(b["shape"], "wall")
    for rm in P.wet_rooms():
        shp = rm["shp"].buffer(-sc(A, 60), join_style=2)
        Y.dashed_shape(sp, shp, 1.4 * k, 0.6 * k, S.C_BLUE, 18)
    for f, g in zones:
        if f.get("pattern") != "tile":
            continue
        if f.get("origin"):                       # a zone of the model: tiles start at its corner
            tw_, th_ = f.get("tile", [600, 600])
            ox, oy = f["origin"]
            m = (ox + min(tw_, 300) / 2.0, oy + min(th_, 300) / 2.0)
            if g.buffer(5).contains(Point(m)):
                occ.add(Y.start_mark(sp, m, k), "sym")
            continue
        for rm in P.rooms:
            part = g.intersection(rm["shp"])
            if part.area < 0.5e6:
                continue
            _, mark = Y.tile_origin(P, rm["name"], part)
            if mark and part.buffer(5).contains(Point(mark)):
                occ.add(Y.start_mark(sp, mark, k), "sym")
    for f, g in zones:
        if f.get("pattern") in ("tile", "model"):
            continue                              # (a covering without a known format has no laying direction)
        for gg in (g.geoms if hasattr(g, "geoms") else [g]):
            if gg.area < 4e6:
                continue
            for rm in P.rooms:
                part = gg.intersection(rm["shp"])
                if part.area < 6e6:
                    continue
                c = part.representative_point()
                L = sc(A, 1400)
                if f.get("along", "y") == "y":
                    a, b = (c.x, c.y - L / 2), (c.x, c.y + L / 2)
                else:
                    a, b = (c.x - L / 2, c.y), (c.x + L / 2, c.y)
                if occ.free(LineString([a, b]).buffer(1.5 * k)):
                    occ.add(Y.arrow(sp, a, b, k), "sym")
    room_tags(A, sp, occ, extra=lambda rm: "пол %s, ±0,000" % ((P.floor_of_room(rm["name"]) or {}).get("id", "-")))
    for f, g in zones:                            # zones with their own outline get their tag on them
        if not f.get("polys") or g.is_empty:
            continue
        big = max((g.geoms if hasattr(g, "geoms") else [g]), key=lambda q: q.area)
        c = big.representative_point()
        if f.get("tile"):
            tw_, th_ = f["tile"]
            tag_near(A, sp, occ, "%s  %d×%d" % (f["id"], tw_, th_), (c.x, c.y), h=1.7, bold=True)
        else:                                     # no format in the model: none is invented (L-104)
            tag_near(A, sp, occ, "%s  формат - уточнить" % f["id"], (c.x, c.y), h=1.7, bold=True)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)

    def sw_floor(f):
        rgb = tints.get(f["id"], Y.TILE if f.get("pattern") == "tile" else Y.PARQUET)

        def fn(psp_, cx, cy):
            pts = [(cx - 7, cy - 2.2), (cx + 7, cy - 2.2), (cx + 7, cy + 2.2), (cx - 7, cy + 2.2)]
            S.fill(psp_, pts, rgb, "SD_Таблицы")
            n_ = 7 if f.get("pattern") == "tile" and min(f.get("tile", [600])) <= 150 else 0 if f.get("pattern") == "model" else 4
            for i in range(1, n_):
                S.line(psp_, (cx - 7 + i * 14.0 / n_, cy - 2.2), (cx - 7 + i * 14.0 / n_, cy + 2.2), "SD_Таблицы", _darker(rgb), 9)
            if n_ == 7:
                S.line(psp_, (cx - 7, cy), (cx + 7, cy), "SD_Таблицы", _darker(rgb), 9)
            S.poly(psp_, pts, "SD_Таблицы", True, (90, 90, 90), 13)
        return fn
    areas = {f["id"]: g.area / 1e6 for f, g in zones}
    items = [(sw_floor(f), "%s - %s, %s м²" % (f["id"], f.get("material", ""), fmt_area(round(areas.get(f["id"], 0), 2))))
             for f in P.floors]
    items += [(_lg_line(BRONZE, 70), "Стык покрытий: профиль-порог в створе двери / разделительный профиль зоны")]
    if any(f.get("pattern") == "tile" for f in P.floors):
        items.append((_lg_sym(lambda p, cx, cy: Y.start_mark(p, (cx, cy), 1.0)), "Начало раскладки плитки"))
    if any(f.get("pattern") not in ("tile", "model") for f in P.floors):
        items.append((_lg_sym(lambda p, cx, cy: Y.arrow(p, (cx - 6, cy), (cx + 6, cy), 1.0)), "Направление укладки доски"))
    if P.wet_rooms():
        items.append((_lg_line(S.C_BLUE, 18, True), "Граница гидроизоляции"))
    if P.boxes:
        items.append((_lg_fill((226, 238, 252), S.C_BLUE, "ANSI37", S.C_BLUE), "Короба и каркасы на полу (покрытие до них)"))
    col.legend(items)
    rows = []
    tot = tot_r = 0.0
    n_tot = 0
    for f, g in zones:
        a = round(g.area / 1e6, 2)
        ar = round(a * (1 + f.get("reserve", 0.1)), 2)
        tot += a
        tot_r += ar
        fmt = "-"
        cnt = "-"
        if f.get("pattern") == "tile":
            tw_, th_ = f.get("tile", [600, 600])
            fmt = "%d×%d" % (max(tw_, th_), min(tw_, th_))
            n = int(math.ceil(ar * 1e6 / float(tw_ * th_)))
            n_tot += n
            cnt = "%d" % n
        elif f.get("pattern") == "model":
            fmt = "уточнить"
        elif f.get("plank"):
            fmt = "%d×%d" % tuple(f["plank"])
        where = ", ".join(f.get("rooms", [])) or f.get("zone") or "-"
        txt = f.get("material", "")
        if f.get("layers"):
            txt += ". " + f["layers"]
        rows.append([f["id"], txt, fmt, where, fmt_area(a), fmt_area(ar), cnt])
    tot = round(tot, 2)
    col.table([8, 40, 12, 19, 10, 11, 9], ["Тип", "Покрытие и состав пола", "Формат, мм", "Помещения / зона", "Площадь, м²",
                                          "С запасом, м²", "Плиток, шт."], rows,
              title="Экспликация полов", h=1.45, aligns=["C", "L", "C", "L", "C", "C", "C"], head_h=6.5,
              total=["", "Итого", "", "", fmt_area(tot), fmt_area(tot_r), "%d" % n_tot if n_tot else ""])
    extra = []
    rooms_tot = P.total_area()
    on_floor = sum(b["shape"].intersection(unary_union([r["shp"] for r in P.rooms])).area for b in P.boxes
                   if b.get("z0", 0) <= 0) / 1e6
    if abs(tot - rooms_tot) >= 0.05:
        why = []
        if tot > rooms_tot:
            why.append("учтены полы в дверных проёмах и нишах")
        if on_floor >= 0.05:
            why.append("без площади под коробами и каркасом стойки (%s м²)" % fmt_area(round(on_floor, 2)))
        if tot < rooms_tot - on_floor - 0.05:
            why.append("часть пола не покрыта - уточнить")
        extra.append("Площадь покрытий (%s м²) %s площади помещений (%s м²) на %s м²: %s." % (
            fmt_area(tot), "больше" if tot > rooms_tot else "меньше", fmt_area(rooms_tot), fmt_area(abs(tot - rooms_tot)),
            "; ".join(why) or "уточнить"))
    base = ["Запас материала учтён в таблице (подрезка, бой); количество плиток - с запасом, округлено вверх.",
            "Неровность основания - не более 2 мм на 2 м."]
    if any(f.get("pattern") == "tile" for f in P.floors):
        base.append("Плитка раскладывается от знака начала раскладки, подрезка - у дальних стен; зоны модели - от своего угла.")
    if any(f.get("polys") for f in P.floors):
        base.append("Плитка зон укладывается заподлицо с основным покрытием (толщину выровнять клеем), стык - "
                    "разделительный профиль из нержавеющей стали.")
    if any(f.get("pattern") not in ("tile", "model") for f in P.floors):
        base += ["Влажность стяжки под доску - не более 2 %.", "Демпферный шов 10 мм по периметру доски закрывается плинтусом."]
    if any(f.get("pattern") == "model" for f in P.floors):
        base.append("Покрытие зоны без формата - по 3D-модели и образцу дизайнера: материал, формат и раскладку уточнить "
                    "до заказа (в модели не задан).")
    col.notes(A.note_lines("floors", extra + base))


# ------------------------------------------------------------------ 08 ceilings
C_T = [(250, 250, 250), (222, 230, 240), (240, 228, 210), (60, 60, 60), (232, 240, 228)]


def ceilings(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Подвесные потолки, короба, ниши. Отметки - от чистого пола до низа потолка")
    C = P.ceilings
    types = C.get("types", [{"id": "Т1", "desc": "Потолок ГКЛ, окраска", "level": P.ceiling}])
    tcol = {t["id"]: C_T[i % len(C_T)] for i, t in enumerate(types)}
    zones = C.get("zones", [])
    OVER = ("cove", "beam", "rail")            # drawn over the ceiling, not a ceiling surface of their own
    rooms_u = unary_union([r["shp"] for r in P.rooms])
    zu = unary_union([Polygon(z["poly"]) for z in zones if z.get("kind") not in OVER] or [Polygon()])
    t1 = rooms_u.difference(zu)
    by_type = {}
    for rm in P.rooms:                         # every room in its own ceiling type (open slab / suspended)
        tid = rm.get("ceiling_type", types[0]["id"])
        part = rm["shp"].difference(zu)
        by_type[tid] = by_type.get(tid, Polygon()).union(part)
        S.fill(sp, part, tcol.get(tid, tcol[types[0]["id"]]), "SD_Штриховка")
    for z in zones:
        if z.get("kind") in OVER:
            continue
        rgb = tcol.get(z["type"], (230, 230, 230))
        S.fill(sp, z["poly"], rgb, "SD_Штриховка")
        if z.get("kind") == "bulkhead":
            S.hatch(sp, z["poly"], (120, 140, 170), "ANSI31", scale=0.24 * k, layer="SD_Штриховка")
        S.poly(sp, z["poly"], "SD_Тонкие", True, (90, 90, 90), 25)
    for z in zones:
        if z.get("kind") == "cove":
            S.fill(sp, z["poly"], (60, 60, 60), "SD_Тонкие")
        elif z.get("kind") == "beam":           # a down-stand beam of the frame: hatched, dashed (above the cut)
            S.hatch(sp, z["poly"], (150, 150, 155), "ANSI31", scale=0.35 * k, layer="SD_Штриховка")
            Y.dashed_poly(sp, z["poly"], 0.8 * k, 0.4 * k, (70, 70, 75), 25)
        elif z.get("kind") == "rail":           # a ceiling curtain rail: a dash-dot line along its axis
            g = Polygon(z["poly"])
            x0, y0, x1, y1 = g.bounds
            a, b = (((x0, (y0 + y1) / 2.0), (x1, (y0 + y1) / 2.0)) if (x1 - x0) >= (y1 - y0)
                    else (((x0 + x1) / 2.0, y0), ((x0 + x1) / 2.0, y1)))
            Y.dashed(sp, a, b, 2.0 * k, 0.5 * k, BRONZE, 50, "SD_Тонкие")
            occ.add(LineString([a, b]).buffer(0.6 * k), "sym")
    for f in P.lighting:
        if f["kind"] == "led":
            Y.dashed(sp, (f["x"], f["y"]), (f["x2"], f["y2"]), 1.2 * k, 0.6 * k, S.C_AMBER, 35, "SD_LED")
        elif f["kind"] in ("track", "track_rect"):
            occ.add(Y.light_icon(sp, f, k), "sym")
        elif f["kind"] != "linear":
            S.circle(sp, (f["x"], f["y"]), 0.9 * k, "SD_Свет", (150, 150, 150), 13)
            occ.add(Point(f["x"], f["y"]).buffer(1.0 * k), "sym")
    Y.draw_walls(sp, P, k)
    reg_walls(A, occ)
    for o in P.openings:
        if o["kind"] in ("window", "balcony"):
            r = P.opening_rect(o)
            S.rect(sp, r[0], r[1], r[2], r[3], "SD_Окна", (60, 60, 60), 13)
    for n in P.nodes:                   # node callouts sit where the designer put them: register before any text
        if n.get("at"):
            occ.add(Y.callout(sp, tuple(n["at"]), n["num"], node_sheet(A) or "", k), "sym")
    # dims of zones: each chain on the side of the zone that is free and inside the rooms (a 130 niche at a wall
    # was dimensioned on top of the wall - lesson L-059)
    inside = unary_union([r["shp"] for r in P.rooms]).buffer(-0.3 * k)

    def zone_chain(vals, horiz, cands, ext_of):
        best = None
        for pos in cands:
            band = (LineString([(vals[0] - 2 * k, pos), (vals[1] + 2 * k, pos)]) if horiz else
                    LineString([(pos, vals[0] - 2 * k), (pos, vals[1] + 2 * k)])).buffer(2.2 * k)
            sc_ = occ.overlap(band) + 50.0 * band.difference(inside).area
            if best is None or sc_ < best[0]:
                best = (sc_, pos)
        DM.chain(sp, vals, best[1], ext_of(best[1]), k, occ, vertical=not horiz)
    for z in zones:
        if z.get("kind") in ("beam", "rail"):
            continue
        g = Polygon(z["poly"])
        x0, y0, x1, y1 = g.bounds
        d = sc(A, 300)
        wide = [y1 + d, y0 - d, (y0 + y1) / 2.0]
        tall = [x1 + d, x0 - d, (x0 + x1) / 2.0]
        ext_y = lambda pos, y0=y0, y1=y1: y1 if pos >= y1 else y0 if pos <= y0 else pos
        ext_x = lambda pos, x0=x0, x1=x1: x1 if pos >= x1 else x0 if pos <= x0 else pos
        if (x1 - x0) < (y1 - y0):
            zone_chain([x0, x1], True, wide, ext_y)
            if z.get("kind") != "niche":
                zone_chain([y0, y1], False, tall, ext_x)
        else:
            zone_chain([y0, y1], False, tall, ext_x)
            if z.get("kind") != "niche":
                zone_chain([x0, x1], True, wide, ext_y)
    # level marks per room and zone tags
    for rm in P.rooms:
        lvl = rm.get("ceiling_level", types[0].get("level", P.ceiling))
        s = "%+.3f" % (lvl / 1000.0)
        s = s.replace(".", ",")
        region = rm["shp"].buffer(-1.5 * k).difference(zu)
        if region.is_empty:
            continue
        L = S.tw(s, 1.9 * k) + 2.8 * k
        best = None
        for c in grid_candidates(region, max(150.0, 6 * k))[:300]:
            g = box(c[0] - 1.3 * k, c[1] - 1.7 * k - 3.0 * k, c[0] + L, c[1] + 3.2 * k)
            sc_ = occ.overlap(g) + (0 if region.contains(g) else g.difference(region).area)
            if best is None or sc_ < best[0]:
                best = (sc_, c, g)
            if sc_ <= 1e-6:
                break
        _, c, g = best
        S.fill(sp, g, (255, 255, 255), "SD_Текст")
        Y.ceiling_mark(sp, c, s, k)
        S.text(sp, rm.get("ceiling_type", types[0]["id"]), (c[0], c[1] - 3.0 * k), 1.8 * k, "MIDDLE_LEFT", bold=True, rgb=(60, 60, 60))
        occ.add(g, "tag")
    for z in zones:
        if z.get("kind") == "rail":
            continue
        g = Polygon(z["poly"])
        c = g.representative_point()
        s = "Б" if z.get("kind") == "beam" else z["type"]
        if z.get("bottom"):
            s += "  %+.3f" % (z["bottom"] / 1000.0)
        s = s.replace(".", ",")
        rot = 90 if (g.bounds[2] - g.bounds[0]) < (g.bounds[3] - g.bounds[1]) and (g.bounds[2] - g.bounds[0]) < 4 * k else 0
        label_near(A, sp, occ, s, (c.x, c.y), h=1.8, rot=rot, bold=True, dists=(3.0, 5.0, 7.0, 9.0))
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    items = []
    for t in types:
        rgb = tcol[t["id"]]
        items.append((_lg_fill(rgb, (90, 90, 90), "ANSI31" if t.get("kind") == "bulkhead" else None, (120, 140, 170)),
                      "%s - %s" % (t["id"], t.get("short", t.get("desc", "")))))
    items.append((_lg_sym(lambda p, cx, cy: Y.ceiling_mark(p, (cx - 4.5, cy - 0.9), "+2,800", 0.8)), "Отметка низа потолка"))
    if any(z.get("kind") == "beam" for z in zones):
        items.append((_lg_fill((240, 240, 240), (70, 70, 75), "ANSI31", (150, 150, 155)), "Б - балка каркаса (низ - отметка)"))
    if any(z.get("kind") == "rail" for z in zones):
        items.append((_lg_line(BRONZE, 50, True), "Карниз потолочный для штор"))
    if any(f["kind"] == "led" for f in P.lighting):
        items.append((_lg_led, "Светодиодная лента"))
    col.legend(items)
    rows = []
    tot = 0.0
    for t in types:
        a = by_type.get(t["id"], Polygon()).area / 1e6
        a += sum(Polygon(z["poly"]).area for z in zones if z["type"] == t["id"] and z.get("kind") not in OVER) / 1e6
        a = round(a, 2)
        tot += a
        lv = t.get("level_text") or ("%+.3f" % (t.get("level", P.ceiling) / 1000.0)).replace(".", ",")
        rows.append([t["id"], t.get("desc", ""), lv, fmt_area(a) if a > 0 else t.get("qty", "-")])
    col.table([9, 60, 20, 20], ["Тип", "Конструкция и отделка", "Отметка", "Площадь, м²"], rows, title="Ведомость потолков",
              h=1.55, aligns=["C", "L", "C", "C"], total=["", "Итого", "", fmt_area(tot)])
    open_ceiling = any("открыт" in t.get("short", "") for t in types)
    col.notes(A.note_lines("ceilings", [
        "Высота от чистого пола до плиты - %d мм." % P.slab,
        "Открытый потолок: плита, балки, воздуховоды и лотки окрашиваются в один цвет; крепления подвесов шинопроводов, "
        "светильников и карнизов - анкерами в плиту до окраски." if open_ceiling else
        "Закладные под подвесные светильники и треки - до монтажа ГКЛ.",
        "В санузлах - ГКЛВ; ревизионные люки к узлам вентиляции - по месту.",
    ]))


def _lg_led(psp, cx, cy):
    Y.dashed(psp, (cx - 7, cy), (cx + 7, cy), 1.2, 0.6, S.C_AMBER, 50, "SD_Таблицы")


# ------------------------------------------------------------------ 09 lighting
LIGHT_SPEC = {
    "spot": "Светильник встраиваемый точечный",
    "spot_ip44": "Светильник встраиваемый влагозащищённый IP44",
    "spot2": "Светильник встраиваемый двойной",
    "spot2_ip44": "Светильник встраиваемый двойной IP44",
    "surface": "Светильник накладной",
    "track": "Магнитный шинопровод",
    "track_rect": "Магнитный шинопровод, замкнутый контур",
    "track_spot": "Трековый спот",
    "linear": "Линейный модуль",
    "chandelier": "Люстра",
    "wall": "Бра настенное",
    "pendant": "Подвесной светильник",
    "led": "Светодиодная лента в профиле",
}


def _mst(pts):
    """Edges of the minimum spanning tree of points (Prim): fixtures linked to their neighbours, no long jumps
    across the room that a nearest-next chain makes when it runs out of near fixtures."""
    if len(pts) < 2:
        return []
    inside, rest, edges = [pts[0]], list(pts[1:]), []
    while rest:
        best = None
        for a in inside:
            for b in rest:
                d2 = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                if best is None or d2 < best[0]:
                    best = (d2, a, b)
        _, a, b = best
        edges.append((a, b))
        inside.append(b)
        rest.remove(b)
    return edges


def wiring_runs(P):
    """Control lines: the fixtures of a group linked to their neighbours (spanning tree), the switch to the nearest
    fixture of the group. A group switched from several places is linked once; every further switch gets one line to
    its nearest fixture (no second web over the room)."""
    runs = []
    done = set()
    for s in P.switches:
        for ctl in s.get("controls", []):
            fx = [f for f in P.lighting if f.get("group") == ctl.get("group") and
                  (not ctl.get("kinds") or f["kind"] in ctl["kinds"])]
            if any(f["kind"] in ("track", "track_rect") for f in fx):
                fx = [f for f in fx if f["kind"] in ("track", "track_rect", "led", "linear") or f["kind"] not in ("track_spot",)]
            pts = []
            for f in fx:
                if f["kind"] in ("led", "track", "linear"):
                    pts.append(((f["x"] + f["x2"]) / 2.0, (f["y"] + f["y2"]) / 2.0) if f["kind"] != "led" else (f["x"], f["y"]))
                elif f["kind"] == "track_rect":
                    pts.append((f["x"], f["y2"]))
                else:
                    pts.append((f["x"], f["y"]))
            pts = list(dict.fromkeys(pts))
            if not pts:
                continue
            key = (ctl.get("group"), tuple(sorted(ctl.get("kinds") or ())))
            near = min(pts, key=lambda p: (p[0] - s["x"]) ** 2 + (p[1] - s["y"]) ** 2)
            first = [((s["x"], s["y"]), near)]
            if key in done:
                runs.append(dict(switch=s["id"], key=ctl.get("key", ""), segs=first, pts=[first[0][0], near]))
                continue
            done.add(key)
            runs.append(dict(switch=s["id"], key=ctl.get("key", ""), segs=first + _mst(pts), pts=[first[0][0], near]))
    return runs


POINT_LIGHTS = ("spot", "spot_ip44", "spot2", "spot2_ip44", "surface", "chandelier", "pendant", "wall", "sconce")


def binding_coords(P, rm):
    """Coordinates to dimension in a room: x values for the horizontal chain, y values for the vertical one."""
    xs, ys = [], []
    shp = rm["shp"]
    for f in P.lighting:
        kd = f["kind"]
        if kd in ("led", "track_spot", "linear"):
            continue
        if kd in ("track", "track_rect"):
            if not (shp.contains(Point(f["x"], f["y"])) or shp.contains(Point(f["x2"], f["y2"]))):
                continue
            if kd == "track_rect" or abs(f["y2"] - f["y"]) > 1 and abs(f["x2"] - f["x"]) > 1:
                xs += [f["x"], f["x2"]]
                ys += [f["y"], f["y2"]]
            elif abs(f["y2"] - f["y"]) < 1:          # horizontal track: its axis -> vertical chain, ends -> horizontal
                xs += [f["x"], f["x2"]]
                ys.append(f["y"])
            else:
                ys += [f["y"], f["y2"]]
                xs.append(f["x"])
            continue
        if shp.contains(Point(f["x"], f["y"])):
            xs.append(f["x"])
            ys.append(f["y"])
    return xs, ys


def _ray(P, p, d, maxd=9000):
    """Distance from p along d (unit axis vector) to the first wall / column face, or None."""
    ln = LineString([(p[0] + d[0] * 5, p[1] + d[1] * 5), (p[0] + d[0] * maxd, p[1] + d[1] * maxd)])
    hit = ln.intersection(P.mass)
    if hit.is_empty:
        return None
    return min(Point(p).distance(g) for g in (hit.geoms if hasattr(hit, "geoms") else [hit]))


def light_bindings(P, rm, tol=30.0, gap=4200.0):
    """Binding dimensions of the fixed fixtures of a room the way the studio draws them: fixtures standing in a row
    get one chain through their centres from the nearest wall / column; the row gets one cross dimension to a wall;
    a single fixture gets its two dimensions to the nearest walls. -> [(values, line_pos, vertical)]"""
    xs, ys = binding_coords(P, rm)
    pts = []
    for x, y in zip(*_pairs(P, rm)):
        if not any(abs(x - a) < 20 and abs(y - b) < 20 for a, b in pts):
            pts.append((x, y))
    if not pts:
        return []

    def rows(axis):
        o = 1 - axis                            # rows along x share y (axis=0), along y share x (axis=1)
        out = []
        for p in sorted(pts, key=lambda q: (q[o], q[axis])):
            for r in out:
                if abs(r[0][o] - p[o]) <= tol and abs(p[axis] - r[-1][axis]) <= gap:
                    r.append(p)
                    break
            else:
                out.append([p])
        return [sorted(r, key=lambda q: q[axis]) for r in out if len(r) >= 2]
    rh, rv = rows(0), rows(1)
    in_h = {p for r in rh for p in r}
    in_v = {p for r in rv for p in r}
    out = []

    def along(r, axis):                         # chain from the nearest wall at one end through the row
        o = 1 - axis
        line = sum(q[o] for q in r) / len(r)
        a, b = r[0], r[-1]
        da = _ray(P, a, (-1, 0) if axis == 0 else (0, -1))
        db = _ray(P, b, (1, 0) if axis == 0 else (0, 1))
        vals = [q[axis] for q in r]
        if da is not None and (db is None or da <= db):
            vals.insert(0, a[axis] - da)
        elif db is not None:
            vals.append(b[axis] + db)
        out.append((vals, line, axis == 1))

    def cross(p, axis):                         # one dimension of the coordinate `axis` to the nearer wall
        d1 = _ray(P, p, (-1, 0) if axis == 0 else (0, -1))
        d2 = _ray(P, p, (1, 0) if axis == 0 else (0, 1))
        if d1 is None and d2 is None:
            return
        v = p[axis] - d1 if (d2 is None or (d1 is not None and d1 <= d2)) else p[axis] + d2
        out.append(([p[axis], v], p[1 - axis], axis == 1))
    for r in rh:
        along(r, 0)
        if not any(q in in_v for q in r):
            cross(r[0], 1)
    for r in rv:
        along(r, 1)
        if not any(q in in_h for q in r):
            cross(r[0], 0)
    for p in pts:
        if p in in_h or p in in_v:
            continue
        cross(p, 0)
        cross(p, 1)
    return out


def _pairs(P, rm):
    """Fixed fixture points of a room (centres of point lights, ends of tracks)."""
    xs, ys = [], []
    shp = rm["shp"]
    for f in P.lighting:
        kd = f["kind"]
        if kd in ("led", "track_spot", "linear"):
            continue
        if kd in ("track", "track_rect"):
            for x, y in ((f["x"], f["y"]), (f["x2"], f["y2"])):
                if shp.buffer(30).contains(Point(x, y)):
                    xs.append(x)
                    ys.append(y)
            continue
        if shp.contains(Point(f["x"], f["y"])):
            xs.append(f["x"])
            ys.append(f["y"])
    return xs, ys


def lighting(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Светильники, выключатели, группы управления. Привязки - по центрам светильников")
    Y.furniture_ghost(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)                 # no binding text on a door leaf / arc (lesson L-035)
    for z in P.ceilings.get("zones", []):
        if z.get("kind") in ("bulkhead",):
            Y.dashed_poly(sp, z["poly"], 1.0 * k, 0.6 * k, (120, 120, 120), 13)
    for r_ in wiring_runs(P):
        for a, b in r_["segs"]:
            Y.dashed(sp, a, b, 1.0 * k, 0.5 * k, (214, 90, 90), 13, "SD_Проводка")
            occ.add(LineString([a, b]).buffer(0.6 * k), "wire")      # binding texts keep off the control lines
    order = {"led": 0, "track": 1, "track_rect": 1, "linear": 2}
    for f in sorted(P.lighting, key=lambda f: order.get(f["kind"], 5)):
        occ.add(Y.light_icon(sp, f, k), "sym")
    sw_c = {}
    for s in P.switches:
        c, g = Y.switch_icon(sp, s, k)
        sw_c[s["id"]] = c
        occ.add(g, "sym")
    # key letters near the first segment of each run
    for r_ in wiring_runs(P):
        if not r_["key"] or len(r_["pts"]) < 2:
            continue
        a, b = r_["pts"][0], r_["pts"][1]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        cands = []
        for t in (0.3, 0.45, 0.6, 0.2, 0.75):
            m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            cands += [(m[0] + nx * 1.4 * k, m[1] + ny * 1.4 * k), (m[0] - nx * 1.4 * k, m[1] - ny * 1.4 * k)]
        place_text(sp, occ, r_["key"], cands, 1.8 * k, bold=True, rgb=(190, 40, 40), mask=True)
    for s in P.switches:
        label_near(A, sp, occ, s["id"], sw_c[s["id"]], h=1.9, bold=True, dists=(3.2, 4.5, 6.0, 8.0))
    # LED lengths
    for f in P.lighting:
        if f["kind"] != "led":
            continue
        ln = math.hypot(f["x2"] - f["x"], f["y2"] - f["y"]) / 1000.0
        t = ("LED %.2f м" % ln).replace(".", ",")
        m = ((f["x"] + f["x2"]) / 2.0, (f["y"] + f["y2"]) / 2.0)
        horiz = abs(f["y2"] - f["y"]) < 1
        cands = []
        for d in (2.0, -2.0, 3.5, -3.5):
            for sh in (0.0, 0.25, -0.25):
                if horiz:
                    cands.append((m[0] + sh * (f["x2"] - f["x"]), m[1] + d * k, 0))
                else:
                    cands.append((m[0] + d * k, m[1] + sh * (f["y2"] - f["y"]), 90))
        place_text(sp, occ, t, cands, 1.6 * k, rgb=(185, 110, 0), mask=True)
    # binding chains per room: fixed fixtures only. Track spots / linear modules ride on the track and are
    # movable -> bound through the track itself; LED strips carry their own length label.
    for rm in P.rooms:
        for vals, pos, vert in light_bindings(P, rm):
            DM.chain(sp, vals, pos, pos, k, occ, vertical=vert, merge=20.0)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    kinds = []
    for f in P.lighting:
        if f["kind"] not in kinds:
            kinds.append(f["kind"])
    spec = P.d.get("lighting_spec", {})
    items = []
    for kd in kinds:
        fx = [f for f in P.lighting if f["kind"] == kd]
        if kd == "led":
            qty = ("%.1f м" % (sum(math.hypot(f["x2"] - f["x"], f["y2"] - f["y"]) for f in fx) / 1000.0)).replace(".", ",")
        else:
            qty = str(len(fx))
        groups = sorted(set(f.get("group", "") for f in fx))
        items.append((_lg_light(kd), [spec.get(kd, LIGHT_SPEC.get(kd, kd)), qty, ", ".join(groups)]))
    items.append((_lg_sym(lambda p, cx, cy: Y.switch_icon(p, dict(id="", x=cx - 1.0, y=cy - 1.3, wall="Y+", keys=2), 1.0)),
                  ["Выключатель (штрихи = клавиши)", str(len(P.switches)), "см. таблицу"]))
    items.append((_lg_wire, ["Линия управления; а, б, в - клавиши", "-", ""]))
    col.legend_table(items, ["Эскиз", "Наименование", "Кол.", "Группа"], [15, 54, 10, 30], aligns=["C", "L", "C", "L"])
    sw_rows = []
    MODE = {"pass": " (проходной)", "cross": " (перекрёстный)"}
    for s in P.switches:
        ctrl = "; ".join("%s - %s%s" % (c.get("key", ""), c.get("desc", c.get("group", "")), MODE.get(c.get("mode"), ""))
                         for c in s.get("controls", []))
        if s.get("pass_through") and not any(c.get("mode") for c in s.get("controls", [])):
            ctrl = (ctrl + " (проходной)") if ctrl else s.get("note", "проходной")
        sw_rows.append([s["id"], str(s.get("keys", 1)), str(s.get("h", 900)), ctrl])
    col.table([10, 10, 10, 79], ["Марка", "Клав.", "h, мм", "Управление"], sw_rows, title="Выключатели", h=1.5,
              aligns=["C", "C", "C", "L"], head_h=5.0)
    col.notes(A.note_lines("lighting", [
        "Высота выключателей - 900 мм, у кровати - 700 мм от чистого пола (если не указано иное).",
        "Блоки питания LED / треков - в доступных местах с ревизией.",
        "Споты и линейные модули на шинопроводе перемещаемые: положение показано условно, привязан шинопровод.",
    ]))


def _lg_light(kind):
    def fn(psp, cx, cy):
        f = dict(kind=kind, x=cx, y=cy)
        if kind in ("track", "linear", "led"):
            f.update(x=cx - 6, x2=cx + 6, y2=cy)
        if kind == "track_rect":
            f.update(x=cx - 6, y=cy - 1.8, x2=cx + 6, y2=cy + 1.8)
        Y.light_icon(psp, f, 1.0)
    return fn


def _lg_wire(psp, cx, cy):
    Y.dashed(psp, (cx - 7, cy), (cx + 7, cy), 1.0, 0.5, (214, 90, 90), 13, "SD_Таблицы")


# ------------------------------------------------------------------ 10 sockets
def socket_clusters(P):
    S_ = [dict(s) for s in P.sockets]
    used = [False] * len(S_)
    out = []
    for i, s in enumerate(S_):
        if used[i]:
            continue
        c = [s]
        used[i] = True
        for j in range(i + 1, len(S_)):
            t = S_[j]
            if not used[j] and t["wall"] == s["wall"] and abs(t["x"] - s["x"]) + abs(t["y"] - s["y"]) < 420:
                c.append(t)
                used[j] = True
        out.append(c)
    return out


def socket_label(c):
    """Height and group of every point of a cluster, as pairs: 'h300 · гр.6, h2150 · гр.5' (never 'h300/2150 · гр.5,6',
    which loses which height belongs to which group - lesson L-036). One group for all -> 'h300/1100 · гр.5'."""
    by = {}
    for s_ in sorted(c, key=lambda q: q["h"]):
        g = str(s_.get("group", "") or "")
        hs = by.setdefault(g, [])
        if s_["h"] not in hs:
            hs.append(s_["h"])

    def gname(g):
        return "" if not g else ("сл." if g.startswith("сл") else "гр.%s" % g)
    if len(by) == 1:
        g, hs = next(iter(by.items()))
        return "h%s" % "/".join(str(h) for h in hs) + (" · %s" % gname(g) if g else "")
    return "; ".join(("h%s %s" % ("/".join(str(h) for h in hs), gname(g))).strip() for g, hs in by.items())


def sockets(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Розетки, силовые выводы, слаботочные точки. Высоты - от чистого пола до центра")
    Y.furniture_ghost(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)
    clusters = socket_clusters(P)
    centers, bind = [], []
    for c in clusters:
        for s_ in c:
            occ.add(Y.socket_icon(sp, s_, k), "sym")
        m = len(c)
        centers.append((round(sum(s_["x"] for s_ in c) / m), round(sum(s_["y"] for s_ in c) / m)))
        for s_ in c:                           # bind every real socket position, never an average of a cluster
            if all(abs(s_["x"] - q[0]) + abs(s_["y"] - q[1]) > 60 for q in bind):
                bind.append((s_["x"], s_["y"]))
    if P.panel:
        p = P.panel
        n = Y.NORMALS[p.get("wall", "X+")]
        w = p.get("w", 300)
        x, y = p["x"], p["y"]
        t = (-n[1], n[0])
        pts = [(x + t[0] * w / 2, y + t[1] * w / 2), (x - t[0] * w / 2, y - t[1] * w / 2),
               (x - t[0] * w / 2 + n[0] * 100, y - t[1] * w / 2 + n[1] * 100), (x + t[0] * w / 2 + n[0] * 100, y + t[1] * w / 2 + n[1] * 100)]
        S.fill(sp, pts, (40, 40, 40), "SD_Электрика")
        occ.add(Polygon(pts).buffer(0.5 * k), "sym")
        label_near(A, sp, occ, ("%s, низ %+.3f" % (p.get("name", "ЩК"), p.get("bottom", 1500) / 1000.0)).replace(".", ","), (x, y), h=1.8,
                   bold=True, dists=(4, 6, 8, 11))
    # bindings first (they must sit at their wall), then labels, which have room to move and take leaders
    DM.edge_chains(sp, P, bind, k, occ, offsets=(sc(A, 320), sc(A, 650), sc(A, 950)), exo=3.0)
    for c, cen in zip(clusters, centers):
        lab = socket_label(c)
        n = Y.NORMALS[c[0]["wall"]]
        t = (-n[1], n[0])
        rot = 90 if n[0] != 0 else 0
        cands = []
        L = S.tw(lab, 1.5 * k) / 2 + 3.2 * k
        for off in (1.6, 3.4, 5.2):           # along the wall first (reads with the wall), stepping into the room
            for sgn in (1, -1):
                cands.append((cen[0] + t[0] * sgn * L + n[0] * off * k, cen[1] + t[1] * sgn * L + n[1] * off * k))
        for sgn in (1, -1):
            for ex in (1.0, 2.0):
                LL = L + ex * S.tw(lab, 1.5 * k) * 0.5
                cands.append((cen[0] + t[0] * sgn * LL + n[0] * 1.6 * k, cen[1] + t[1] * sgn * LL + n[1] * 1.6 * k))
        far = []                               # crowded wall: further into the room, with a leader
        for off in (7.0, 9.5, 12.0, 15.0, 18.0, 22.0, 26.0, 30.0):
            for sh in (0.0, 1.0, -1.0, 2.0, -2.0, 3.0, -3.0):
                far.append((cen[0] + t[0] * sh * L + n[0] * off * k, cen[1] + t[1] * sh * L + n[1] * off * k, 0 if rot else 90))
        rm = P.room_of_point(cen, 200)
        within = rm["shp"].buffer(-0.3 * k) if rm else None
        res = place_text(sp, occ, lab, [(c_[0], c_[1], rot) for c_ in cands] + far, 1.5 * k, rgb=(40, 40, 40), mask=True,
                         within=within)
        if res and math.hypot(res[0][0] - cen[0], res[0][1] - cen[1]) > 6.0 * k:
            q = res[1].exterior.interpolate(res[1].exterior.project(Point(cen)))
            S.line(sp, (q.x, q.y), (cen[0] + n[0] * 0.8 * k, cen[1] + n[1] * 0.8 * k), "SD_Тонкие", (90, 90, 90), 9)
            occ.add(LineString([(q.x, q.y), cen]).buffer(0.2 * k), "leader")
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    kinds = []
    for s_ in P.sockets:
        if s_["kind"] not in kinds:
            kinds.append(s_["kind"])
    names = {"Р": "Розетка 16 А с заземлением", "Р2": "Розетка двойная 16 А", "РВ": "Розетка влагозащищённая IP44",
             "Р32": "Силовой вывод / розетка 32 А", "ТВ": "Розетка TV", "LAN": "Розетка LAN (RJ-45)", "КОНД": "Вывод для кондиционера",
             "БРА": "Вывод для бра / подсветки", "ВЫВ": "Кабельный вывод"}
    items = [(_lg_socket(kd), names.get(kd, kd)) for kd in kinds]
    if P.panel:
        items.append((_lg_fill((40, 40, 40), (40, 40, 40), w=4, h=4),
                      {"ЩК": "Щит квартирный", "ЩР": "Щит распределительный", "ЩО": "Щит освещения"}.get(
                          P.panel.get("name", "ЩК"), "Щит %s" % P.panel.get("name", ""))))
    col.legend(items, rh=5.2)
    if P.circuits:
        pn = (P.panel or {}).get("name", "ЩК")
        col.table([9, 27, 27, 46], ["Гр.", "Аппарат", "Кабель", "Потребители"], P.circuits,
                  title="Групповые линии (рекомендуемая схема %s)" % pn, h=1.5, aligns=["C", "L", "L", "L"], head_h=5.0)
    col.notes(A.note_lines("sockets", [
        "Схема %s - рекомендуемая; окончательно - по электропроекту с учётом выделенной мощности." % (P.panel or {}).get("name", "ЩК"),
        "Прокладка - в гофре, по стенам строго вертикально / горизонтально; в санузлах - вне зон 0-1.",
    ]))


def _lg_socket(kind):
    def fn(psp, cx, cy):
        Y.socket_icon(psp, dict(kind=kind, x=cx, y=cy - 1.6, wall="Y+"), 1.0)
    return fn


# ------------------------------------------------------------------ 11 plumbing
def plumbing(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Выводы водоснабжения и канализации. Высоты - от чистого пола до оси вывода")
    Y.furniture_ghost(sp, P, k, rgb=(170, 170, 176))
    Y.draw_walls(sp, P, k, show_boxes=True)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)
    fixtures = []
    for o in P.plumbing:
        key = o.get("fixture", "вывод") + "|" + (P.room_of_point((o["x"], o["y"]), 120) or {"name": ""})["name"]
        for fx in fixtures:
            if fx["key"] == key:
                fx["items"].append(o)
                break
        else:
            fixtures.append(dict(key=key, name=o.get("fixture", "вывод"), room=key.split("|")[1], items=[o]))
    for o in P.plumbing:
        c, g = Y.water_icon(sp, P, o, k)
        occ.add(g, "sym")
    for i, fx in enumerate(fixtures):
        fx["num"] = i + 1
        cx = sum(o["x"] for o in fx["items"]) / len(fx["items"])
        cy = sum(o["y"] for o in fx["items"]) / len(fx["items"])
        r = 1.7 * k
        best = None
        for c in ring_candidates((cx, cy), [d * k for d in (5, 7, 9.5, 12)], 16):
            g = Point(c).buffer(r + 0.3 * k)
            s_ = occ.overlap(g)
            rm = P.room_of_point((cx, cy), 120)
            if rm is not None and not rm["shp"].buffer(-r).contains(Point(c)):
                s_ += 5 * g.area
            if best is None or s_ < best[0]:
                best = (s_, c, g)
            if s_ <= 1e-6:
                break
        _, c, g = best
        S.line(sp, (cx, cy), c, "SD_Тонкие", (110, 110, 110), 9)
        Y.mark_circle(sp, str(fx["num"]), c, k, r=1.7, h=1.8, rgb=S.C_BLUE, txt_rgb=S.C_BLUE)
        occ.add(g, "mark")
    pts = []
    for fx in fixtures:
        wall_items = [o for o in fx["items"] if o.get("h", 1) > 0]
        if wall_items:
            pts.append((round(sum(o["x"] for o in wall_items) / len(wall_items)), round(sum(o["y"] for o in wall_items) / len(wall_items))))
    DM.edge_chains(sp, P, pts, k, occ, offsets=(sc(A, 450), sc(A, 750), sc(A, 1050)), exo=2.6)
    # floor outlets (drains) are bound in both directions to the walls of their room (lesson L-037)
    for rm in P.rooms:
        fl = [(o["x"], o["y"]) for o in P.plumbing if o.get("h", 1) == 0 and rm["shp"].buffer(10).contains(Point(o["x"], o["y"]))]
        if fl:
            DM.room_point_chains(sp, P, rm, fl, k, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    col.legend([
        (_lg_water("ХВС"), "Вывод холодной воды (ХВС)"), (_lg_water("ГВС"), "Вывод горячей воды (ГВС)"),
        (_lg_water("К50"), "Канализация Ø50"), (_lg_water("К110"), "Канализация Ø110"),
        (_lg_sym(lambda p, cx, cy: Y.water_icon(p, None, dict(kind="К50", x=cx, y=cy, h=0), 1.0)), "Трап"),
    ], rh=5.6)
    rows = []
    for fx in fixtures:
        hx = sorted(set(o["h"] if o["h"] else "в полу" for o in fx["items"] if o["kind"] == "ХВС"), key=str)
        hg = sorted(set(o["h"] if o["h"] else "в полу" for o in fx["items"] if o["kind"] == "ГВС"), key=str)
        kk = ["%s, h %d" % (o["kind"].replace("К", "Ø"), o["h"]) if o.get("h", 0) > 0 else "%s, в полу" % o["kind"].replace("К", "Ø")
              for o in fx["items"] if o["kind"].startswith("К")]
        rows.append([str(fx["num"]), fx["name"], fx["room"], "/".join(map(str, hx)) or "-", "/".join(map(str, hg)) or "-",
                     "; ".join(sorted(set(kk))) or "-"])
    col.table([7, 34, 19, 11, 11, 27], ["№", "Прибор", "Помещение", "ХВС, h", "ГВС, h", "Канализация"], rows,
              title="Ведомость выводов", h=1.55, aligns=["C", "L", "L", "C", "C", "L"])
    col.notes(A.note_lines("plumbing", [
        "Водопровод - PP-R PN20 Ø20; канализация - ПП Ø50/Ø110, уклон 0,02-0,03 к стояку.",
        "Место стояков, узла учёта и коллектора - по месту, доступ через ревизионные люки.",
        "Гидроизоляция санузлов - с заведением на стены 200 мм, в душевой зоне - 2000 мм.",
        "Выводы уточнить по паспортам выбранной сантехники до начала разводки.",
    ]))


def _lg_water(kind):
    def fn(psp, cx, cy):
        Y.water_icon(psp, None, dict(kind=kind, x=cx, y=cy - 1.1, h=1), 1.0, n=(0, 1))
    return fn


# ------------------------------------------------------------------ 12 finishes
FIN_RGB_DEFAULT = [(205, 205, 210), (60, 130, 200), (190, 120, 60), (120, 160, 90), (150, 110, 170)]


def finishes(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, "Отделка стен по типам. Ведомость отделки помещений")
    S.fill(sp, unary_union([r["shp"] for r in P.rooms]), (252, 252, 252), "SD_Штриховка")
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)
    F = P.finishes
    types = F.get("types", [{"id": "О1", "desc": "Окраска"}])
    frgb = {t["id"]: tuple(t.get("rgb", FIN_RGB_DEFAULT[i % len(FIN_RGB_DEFAULT)])) for i, t in enumerate(types)}
    mask = unary_union([LineString(sl).buffer(sc(A, 160), cap_style=2) for sl in P.separations]
                       + [g.buffer(sc(A, 110), join_style=2) for g in getattr(P, "passages", [])]
                       + [P.open_shape[o["id"]].buffer(sc(A, 110), join_style=2) for o in P.openings] or [Polygon()])
    for rm in P.rooms:
        typ = rm.get("wall_finish") or F.get("by_class", {}).get(rm.get("cls"), types[0]["id"])
        inner = rm["shp"].buffer(-sc(A, 70), join_style=2)
        if inner.is_empty:
            continue
        rest = inner.exterior.difference(mask)
        for g in (rest.geoms if hasattr(rest, "geoms") else [rest]):
            cs = list(g.coords)
            for a, b in zip(cs[:-1], cs[1:]):
                S.line(sp, a, b, "SD_Акцент", frgb.get(typ, (150, 150, 150)), 70)
        occ.add(inner.exterior.buffer(0.9 * k), "strip")
    for seg in F.get("segments", []):
        S.line(sp, seg["a"], seg["b"], "SD_Акцент", frgb.get(seg["type"], (150, 150, 150)), 100)
        occ.add(LineString([seg["a"], seg["b"]]).buffer(1.0 * k), "strip")
        m = ((seg["a"][0] + seg["b"][0]) / 2, (seg["a"][1] + seg["b"][1]) / 2)
        _mark_box(A, sp, occ, seg["type"], m, frgb.get(seg["type"], (90, 90, 90)))
    # tile claddings of the model on columns / boxes / walls: the outline of what they cover in the tile type (L-102)
    tile_t = next((t["id"] for t in types if t.get("kind") == "tile"), None)
    if tile_t:
        done = set()
        for c in P.d.get("claddings") or []:
            on = c.get("on")
            if not on or on in done:
                continue
            w = P.wall_by_id.get(on) or next((b for b in P.boxes if b.get("id") == on), None)
            if w is None or w.get("shape") is None:
                continue
            done.add(on)
            g = w["shape"].buffer(sc(A, 40), join_style=2)
            ring = g.exterior if c.get("host") != "wall" else g.exterior.intersection(
                unary_union([r["shp"] for r in P.rooms]).buffer(sc(A, 60)))
            for gg in (ring.geoms if hasattr(ring, "geoms") else [ring]):
                if gg.is_empty or not hasattr(gg, "coords"):
                    continue
                cs = list(gg.coords)
                for a, b in zip(cs[:-1], cs[1:]):
                    S.line(sp, a, b, "SD_Акцент", frgb.get(tile_t, (150, 40, 50)), 70)
            occ.add(g.exterior.buffer(0.9 * k), "strip")
            cc = w["shape"].centroid
            _mark_box(A, sp, occ, tile_t, (cc.x, cc.y), frgb.get(tile_t, (150, 40, 50)))
    room_tags(A, sp, occ, extra=lambda rm: "стены %s" % (rm.get("wall_finish") or F.get("by_class", {}).get(rm.get("cls"), types[0]["id"])))
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    col.legend([(_lg_line(frgb[t["id"]], 70), "%s - %s" % (t["id"], t.get("desc", ""))) for t in types])
    rows = []
    tot_c = tot_f = 0.0
    tot_w = {}
    for rm, split in room_wall_finishes(P):
        ws = " / ".join("%s %s" % (t, fmt_area(v)) for t, v in split.items())
        for t, v in split.items():
            tot_w[t] = tot_w.get(t, 0.0) + round(v, 2)
        fl = P.floor_of_room(rm["name"])
        rows.append([rm["num"], rm["name"], "%s %s" % (rm.get("ceiling_type", "Т1"), fmt_area(rm["area"])), ws,
                     "%s %s" % ((fl or {}).get("id", "-"), fmt_area(rm["area"]))])
        tot_c += rm["area"]
        tot_f += rm["area"]
    col.table([7, 26, 20, 32, 24], ["№", "Помещение", "Потолок, м²", "Стены, м²", "Пол, м²"], rows,
              title="Ведомость отделки помещений", h=1.55, aligns=["C", "L", "L", "L", "L"],
              total=["", "Итого", fmt_area(tot_c), " / ".join("%s %s" % (t, fmt_area(v)) for t, v in tot_w.items()), fmt_area(tot_f)])
    col.notes(A.note_lines("finishes", [
        "Площади стен - за вычетом проёмов, высота отделки - до потолка; откосы - дополнительно.",
        "Подготовка под окраску: штукатурка, шпаклёвка Q3-Q4, грунт; цвет - по палитре дизайнера.",
    ]))


def room_wall_finishes(P):
    """[(room, {finish type: m2})] - one calculation for the finishes sheet and the elevation sheets:
    rooms fully covered by elevations take tile / paint areas from them; apron segments (О3) take their height from
    the kitchen elevation zones (default 650) and are subtracted from the base finish."""
    from .sheets_details import elev_material_areas, groups
    F = P.finishes
    types = F.get("types", [{"id": "О1", "desc": "Окраска"}])
    paint_t = types[0]["id"]
    by_room = {}
    for g in groups(P):
        by_room.setdefault(g["name"], []).extend(g["elevs"])
    out = []
    for rm, area_w in wall_areas(P):
        typ = rm.get("wall_finish") or F.get("by_class", {}).get(rm.get("cls"), paint_t)
        el = by_room.get(rm["name"], [])
        split = None
        if el:
            mats = elev_material_areas(P, el)
            wall_len = sum(math.hypot(e["b"][0] - e["a"][0], e["b"][1] - e["a"][1]) for e in el) / 1000.0
            per = rm["shp"].length / 1000.0 - sum(rm["shp"].boundary.intersection(sl.buffer(3)).length
                                                 for sl in P.open_edges()) / 1000.0
            if wall_len >= 0.9 * per:
                split = {}
                if mats["tile"] > 0:
                    split[typ if typ != paint_t else "О2"] = mats["tile"]
                if mats["paint"] > 0:
                    split[paint_t] = split.get(paint_t, 0.0) + mats["paint"]
        if split is None:
            split = {typ: area_w}
            for seg in F.get("segments", []):
                ln = LineString([seg["a"], seg["b"]])
                if rm["shp"].buffer(80).contains(ln.centroid):
                    h = seg.get("h") or (elev_material_areas(P, el)["apron_h"] if el else 0) or 650
                    a = ln.length * h / 1e6
                    split[seg["type"]] = split.get(seg["type"], 0.0) + a
                    split[typ] -= a
        out.append((rm, split))
    return out


def wall_areas(P):
    seps = P.open_edges()
    out = []
    for rm in P.rooms:
        shp = rm["shp"]
        per = shp.length / 1000.0
        for sl in seps:
            per -= shp.boundary.intersection(sl.buffer(3)).length / 1000.0
        h = rm.get("ceiling_level", P.ceiling) / 1000.0
        a = per * h
        for o in P.openings:
            r = P.open_shape[o["id"]].buffer(5)
            if r.intersects(shp.boundary) and r.intersection(shp).area > 100:
                a -= o["w"] / 1000.0 * min(o["h"], P.ceiling) / 1000.0
        out.append((rm, a))
    return out
