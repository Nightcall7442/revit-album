# -*- coding: utf-8 -*-
"""Plans of the reference album the engine did not have: plinths, heating, cornices, furniture with dimensions and
doors, electrical outputs; the schedule of electrical fittings."""
import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from . import dims as DM
from . import gfx as S
from . import symbols as Y
from .album import Column
from .model import fmt_area
from .sheets_plans import (_lg_fill, _lg_line, _lg_socket, label_near, outer, reg_swings, reg_walls,
                           room_tags, sc, tag_near)

fmt_m = lambda v: ("%.2f" % v).replace(".", ",")
OUTPUT_KINDS = ("ВЫВ", "КОНД", "Р32", "БРА")
SOCKET_NAMES = {"Р": "Розетка 16 А с заземлением", "Р2": "Розетка двойная 16 А", "РВ": "Розетка влагозащищённая IP44",
                "Р32": "Силовой вывод / розетка 32 А", "ТВ": "Розетка TV", "LAN": "Розетка LAN (RJ-45)",
                "КОНД": "Вывод для кондиционера", "БРА": "Вывод для бра / подсветки", "ВЫВ": "Кабельный вывод"}


def has_data(A, key):
    P = A.P
    d = P.d
    return {
        "plinths": bool((d.get("plinths") or {}).get("rooms")),
        "heating": bool((d.get("heating") or {}).get("radiators") or (d.get("heating") or {}).get("floors")),
        "cornices": bool(rails(P)),
        "furniture_dims": bool(P.furniture) or any(o["kind"] in ("door", "balcony") for o in P.openings),
        "el_fittings": bool(P.sockets) or bool(P.switches),
        "el_outputs": any(s["kind"] in OUTPUT_KINDS for s in P.sockets),
    }.get(key, True)


def _base(A, sp, occ, fill=(252, 252, 252), furniture=False):
    P = A.P
    k = A.plan_k
    S.fill(sp, unary_union([r["shp"] for r in P.rooms]), fill, "SD_Штриховка")
    if furniture:
        Y.furniture_ghost(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)


def _square_mark(A, sp, occ, s, anchor, rgb=(40, 40, 40), dists=(3.0, 4.5, 6.0, 8.0)):
    """A mark in a square frame near anchor, a leader with a dot to it (К-1, Р-1, Д-1 of the reference)."""
    k = A.plan_k
    h = 1.9 * k
    w = S.tw(s, h) + 1.6 * k
    hh = h + 1.4 * k
    best = None
    for dd in dists:
        for i in range(16):
            a = 2 * math.pi * i / 16
            c = (anchor[0] + math.cos(a) * dd * k, anchor[1] + math.sin(a) * dd * k)
            g = box(c[0] - w / 2, c[1] - hh / 2, c[0] + w / 2, c[1] + hh / 2)
            sc_ = occ.overlap(g)
            if occ.bounds is not None and not occ.bounds.contains(g):
                sc_ += 1e6
            if best is None or sc_ < best[0]:
                best = (sc_, c, g)
        if best[0] < 1.0:
            break
    _, c, g = best
    q = g.exterior.interpolate(g.exterior.project(Point(anchor)))
    Y.leader(sp, (q.x, q.y), anchor, k, rgb)
    Y.tag_box(sp, s, c, k, h=1.9, txt_rgb=rgb, border=rgb)
    occ.add(g.buffer(0.3 * k), "tag")
    occ.add(LineString([(q.x, q.y), anchor]).buffer(0.2 * k), "leader")


# ------------------------------------------------------------------ plinths
def plinth_runs(P):
    """[(room, type id, [LineString])] - plinth along the room faces, door / passage gaps left out."""
    pl = P.d.get("plinths") or {}
    out = []
    gaps = unary_union([P.open_shape[o["id"]].buffer(60, join_style=2) for o in P.openings
                        if o["kind"] in ("door", "balcony", "passage")]
                       + [LineString(s).buffer(80, cap_style=2) for s in P.separations]
                       + [g.buffer(60) for g in getattr(P, "passages", [])] or [Polygon()])
    for r in P.rooms:
        t = (pl.get("rooms") or {}).get(r["name"])
        if not t:
            continue
        ring = r["shp"].exterior.difference(gaps)
        parts = [g for g in getattr(ring, "geoms", [ring]) if g.geom_type == "LineString" and g.length > 50]
        out.append((r, t, parts))
    return out


def plinths(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    _base(A, sp, occ, furniture=True)
    pl = P.d.get("plinths") or {}
    types = {t["id"]: t for t in pl.get("types", [])}
    tot = {}
    for r, t, parts in plinth_runs(P):
        rgb = tuple(types.get(t, {}).get("rgb", (150, 110, 70)))
        inner = r["shp"].buffer(-sc(A, 45), join_style=2)
        for g in parts:
            g2 = inner.exterior.intersection(g.buffer(sc(A, 60), cap_style=2)) if not inner.is_empty else g
            for ln in getattr(g2, "geoms", [g2]):
                if ln.geom_type != "LineString":
                    continue
                cs = list(ln.coords)
                for a, b in zip(cs[:-1], cs[1:]):
                    S.line(sp, a, b, "SD_Акцент", rgb, 70)
            occ.add(g.buffer(0.8 * k), "strip")
        L_ = sum(g.length for g in parts) / 1000.0
        tot[t] = tot.get(t, 0.0) + L_
        if parts:
            g = max(parts, key=lambda q: q.length)
            m = g.interpolate(0.5, normalized=True)
            _square_mark(A, sp, occ, t, (m.x, m.y))
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    rows = [[t, S.uo_line(tuple(types.get(t, {}).get("rgb", (150, 110, 70))), 70), types.get(t, {}).get("desc", ""),
             fmt_m(v), fmt_m(v * 1.1)] for t, v in sorted(tot.items())]
    col.table([11, 10, 47, 16, 16], ["Марка", "УО", "Наименование", "Длина, м.п.", "С запасом"], rows,
              title="* Ведомость плинтусов", h=1.6, aligns=["C", "C", "L", "C", "C"],
              total=["", "", "Общий итог", fmt_m(sum(tot.values())), fmt_m(sum(tot.values()) * 1.1)])
    col.legend([(_lg_line((150, 110, 70), 70), "Плинтус (марка — в прямоугольной рамке)"),
                (lambda p_, cx, cy: Y.tag_box(p_, "П-1", (cx, cy), 1.0, h=1.9), "Марка плинтуса")])
    col.notes(A.note_lines("plinths", [
        "Длина - по периметру помещений за вычетом дверных проёмов; запас на подрезку - 10 %.",
        "Плинтус монтируется после чистовой отделки стен и пола; стыки и углы - по месту, без зазоров.",
        "В мокрых зонах плинтус не предусмотрен: плитка стен заводится на пол.",
    ]))


# ------------------------------------------------------------------ heating
def heating(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    _base(A, sp, occ, furniture=True)
    H = P.d.get("heating") or {}
    for f in H.get("floors", []):
        g = Polygon(f["poly"]).buffer(0)
        S.fill(sp, g, (253, 236, 236), "SD_Штриховка")
        S.hatch(sp, g, S.C_RED, "ANSI31", scale=0.35 * k)
        Y.outline(sp, g, S.C_RED, 25, "SD_Электрика")
        occ.add(g.buffer(-0.5 * k), "zone")
        c = g.representative_point()
        tag_near(A, sp, occ, "ТП %s м², %d Вт" % (fmt_area(f["area"]), f.get("power", 0)), (c.x, c.y), h=1.7)
    by_mark = {}
    for r in H.get("radiators", []):
        g = box(*r["rect"])
        S.fill(sp, g, (255, 255, 255), "SD_Электрика")
        S.hatch(sp, g, S.C_RED, "ANSI31", scale=0.15 * k)
        Y.outline(sp, g, S.C_RED, 35, "SD_Электрика")
        occ.add(g.buffer(0.3 * k), "sym")
        by_mark.setdefault(r["mark"], []).append(r)
        c = g.centroid
        _square_mark(A, sp, occ, r["mark"], (c.x, c.y), rgb=S.C_RED)
    for t in H.get("thermostats", []):
        p = (t["x"], t["y"])
        q = box(p[0] - 0.9 * k, p[1] - 0.9 * k, p[0] + 0.9 * k, p[1] + 0.9 * k)
        S.fill(sp, q, (255, 255, 255), "SD_Электрика")
        Y.outline(sp, q, S.C_RED, 25, "SD_Электрика")
        S.text(sp, "t°", p, 1.1 * k, "MIDDLE_CENTER", "SD_Электрика", rgb=S.C_RED)
        occ.add(q.buffer(0.3 * k), "sym")
        label_near(A, sp, occ, "Н= %d мм" % t.get("h", 900), p, h=1.6, rgb=S.C_RED, dists=(2.5, 4.0, 6.0))
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    tdesc = {t["id"]: t["desc"] for t in H.get("types", [])}
    rows = [[m, S.uo_fill((255, 255, 255), "ANSI31", S.C_RED, S.C_RED), tdesc.get(m, ""), str(len(v)),
             ", ".join(sorted({r["room"] for r in v}))] for m, v in sorted(by_mark.items())]
    if rows:
        col.table([11, 10, 44, 9, 26], ["Марка", "УО", "Наименование", "Кол.", "Помещения"], rows,
                  title="* Ведомость отопительных приборов", h=1.6, aligns=["C", "C", "L", "C", "L"])
    frows = [[f["room"], fmt_area(f["area"]), "%d" % f.get("power", 0)] for f in H.get("floors", [])]
    if frows:
        col.table([50, 25, 25], ["Помещение", "Площадь, м²", "Мощность, Вт"], frows, title="* Тёплый пол (электрический)",
                  h=1.6, aligns=["L", "C", "C"])
    items = []
    if by_mark:
        items.append((_lg_fill((255, 255, 255), S.C_RED, "ANSI31", S.C_RED), "Радиатор отопления (марка — в рамке)"))
    if H.get("floors"):
        items.append((_lg_fill((253, 236, 236), S.C_RED, "ANSI31", S.C_RED), "Электрический тёплый пол (зона укладки мата)"))
    if H.get("thermostats"):
        items.append((lambda p_, cx, cy: (S.rect(p_, cx - 1.6, cy - 1.6, cx + 1.6, cy + 1.6, "SD_Таблицы", S.C_RED, 25),
                                          S.text(p_, "t°", (cx, cy), 1.6, "MIDDLE_CENTER", "SD_Таблицы", rgb=S.C_RED)),
                      "Терморегулятор тёплого пола, высота от чистого пола"))
    col.legend(items)
    col.notes(A.note_lines("heating", [
        "Радиаторы - по центру окон, низ +0,120, отступ от стены 50 мм; ширина - около 3/4 окна (СП 60.13330).",
        "Мощность радиаторов, трубы и узлы подключения - по теплотехническому расчёту и проекту ОВ.",
        "Тёплый пол - кабельный мат 150 Вт/м² под плитку, не под сантехникой и мебелью; датчик пола - в гофре.",
    ]))


# ------------------------------------------------------------------ cornices
def rails(P):
    """[(line, length mm, room name)] - curtain rails: ceiling zones «rail» and furniture «rail»."""
    out = []
    polys = [Polygon(z["poly"]) for z in (P.ceilings or {}).get("zones", []) if z.get("kind") == "rail"]
    import re
    polys += [Polygon(f["poly"]) for f in P.furniture if f.get("kind") == "rail"        # not a towel rail
              and re.search(r"карниз|штор|curtain", f.get("name") or "", re.I)]
    for g in polys:
        g = g.buffer(0)
        if g.is_empty:
            continue
        x0, y0, x1, y1 = g.bounds
        if x1 - x0 >= y1 - y0:
            ln = LineString([(x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)])
        else:
            ln = LineString([((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)])
        rm = P.room_of_point((ln.centroid.x, ln.centroid.y), 300)
        out.append((ln, ln.length, rm["name"] if rm else ""))
    return out


def cornices(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    _base(A, sp, occ, furniture=False)
    rs = rails(P)
    rgb = (150, 110, 70)
    tot = 0.0
    for ln, L_, room in rs:
        cs = list(ln.coords)
        S.line(sp, cs[0], cs[-1], "SD_Акцент", rgb, 70)
        for p in (cs[0], cs[-1]):
            S.fill(sp, Point(p).buffer(0.5 * k, 12), rgb, "SD_Акцент")
        occ.add(ln.buffer(0.8 * k), "strip")
        tot += L_
        m = ln.interpolate(0.5, normalized=True)
        _square_mark(A, sp, occ, "К-1", (m.x, m.y))
        horiz = abs(cs[0][1] - cs[-1][1]) < 1
        with DM.color(DM.BLUE):
            if horiz:
                DM.chain(sp, [cs[0][0], cs[-1][0]], cs[0][1] - sc(A, 300), cs[0][1], k, occ)
            else:
                DM.chain(sp, [cs[0][1], cs[-1][1]], cs[0][0] - sc(A, 300), cs[0][0], k, occ, vertical=True)
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    rows = [["К-1", S.uo_line(rgb, 70), "Карниз потолочный для штор, 2-рядный, скрытый монтаж (по 3D-модели)",
             str(len(rs)), fmt_m(tot / 1000.0)]]
    col.table([11, 10, 51, 10, 18], ["Марка", "УО", "Наименование", "Кол.", "Длина, м"], rows,
              title="* Ведомость карнизов", h=1.6, aligns=["C", "C", "L", "C", "C"])
    col.legend([(_lg_line(rgb, 70), "Карниз (марка — в прямоугольной рамке)"),
                (_lg_line(S.C_BLUE, 25), "Длина карниза, мм")])
    col.notes(A.note_lines("cornices", [
        "Карнизы крепятся к перекрытию; закладные - до монтажа потолка.",
        "Длина карниза уточняется по месту после чистовой отделки стен.",
    ]))


# ------------------------------------------------------------------ furniture with dimensions, doors
SKIP_DIMS = ("rug", "chair", "tv", "mirror", "rail", "hob", "sink", "lamp", "plant")


def furniture_dims(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    S.fill(sp, unary_union([r["shp"] for r in P.rooms]), (252, 252, 252), "SD_Штриховка")
    Y.furniture_all(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k)
    reg_walls(A, occ)
    reg_swings(A, occ)
    for f in P.furniture:
        g = Polygon(f["poly"]).buffer(0)
        occ.add(g, "furn")
    with DM.color(DM.BLUE):                      # overall sizes of the furniture in blue (reference album)
        for f in P.furniture:
            if f.get("kind") in SKIP_DIMS:
                continue
            g = Polygon(f["poly"]).buffer(0)
            x0, y0, x1, y1 = g.bounds
            if max(x1 - x0, y1 - y0) < 500:
                continue
            rm = P.room_of_point((g.centroid.x, g.centroid.y), 300)
            cy = rm["shp"].centroid.y if rm else (y0 + y1) / 2
            cx = rm["shp"].centroid.x if rm else (x0 + x1) / 2
            yy = y0 - sc(A, 180) if (y0 + y1) / 2 > cy else y1 + sc(A, 180)
            xx = x0 - sc(A, 180) if (x0 + x1) / 2 > cx else x1 + sc(A, 180)
            DM.chain(sp, [x0, x1], yy, y0 if yy < y0 else y1, k, occ)
            DM.chain(sp, [y0, y1], xx, x0 if xx < x0 else x1, k, occ, vertical=True)
    # door marks
    doors = {}
    for o in P.openings:
        if o["kind"] not in ("door", "balcony"):
            continue
        doors.setdefault(o.get("mark") or "Д-?", []).append(o)
        c = P.open_shape[o["id"]].centroid
        _square_mark(A, sp, occ, o.get("mark") or "Д-?", (c.x, c.y), dists=(3.5, 5.0, 7.0))
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=True)
    col = Column(A, psp)
    if doors:
        rows = []
        for m, os_ in sorted(doors.items()):
            o = os_[0]
            kind = "балконная" if o["kind"] == "balcony" else ("распашная" if not o.get("sliding") else "раздвижная")
            hands = sorted({P.door_hand(x) for x in os_ if hasattr(P, "door_hand")} - {None})
            rows.append([m, "%d×%d" % (o["w"], o["h"]), kind, ", ".join({"L": "лев.", "R": "прав."}.get(h, h) for h in hands) or "—",
                         str(len(os_))])
        col.table([12, 22, 26, 22, 10], ["Марка", "Ш×В, мм", "Тип", "Открывание", "Кол."], rows, title="Ведомость дверей",
                  h=1.6, aligns=["C", "C", "L", "C", "C"])
    col.legend([(_lg_line(S.C_BLUE, 25), "Габариты мебели и изделий, мм"),
                (lambda p_, cx, cy: Y.tag_box(p_, "Д-1", (cx, cy), 1.0, h=1.9), "Марка двери")])
    col.notes(A.note_lines("furniture_dims", [
        "Размеры мебели - габаритные, по 3D-модели; корпусная мебель - по контрольным замерам после отделки.",
        "Двери - размеры полотна; проём под коробку - по паспорту двери.",
    ]))


# ------------------------------------------------------------------ electrical outputs
def el_outputs(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    _base(A, sp, occ, furniture=True)
    outs = [s_ for s_ in P.sockets if s_["kind"] in OUTPUT_KINDS]
    bind = []
    for s_ in outs:
        occ.add(Y.socket_icon(sp, s_, k), "sym")
        if all(abs(s_["x"] - q[0]) + abs(s_["y"] - q[1]) > 60 for q in bind):
            bind.append((s_["x"], s_["y"]))
    with DM.color(DM.RED):
        DM.edge_chains(sp, P, bind, k, occ, offsets=(sc(A, 320), sc(A, 650), sc(A, 950)), exo=3.0)
    for s_ in outs:                              # «Н= 1100 мм» in a frame (reference album)
        lab = "%s Н= %d мм" % (s_["kind"], s_.get("h", 0))
        n = Y.NORMALS.get(s_.get("wall", "Y+"), (0, 1))
        p = (s_["x"] + n[0] * 3.5 * k, s_["y"] + n[1] * 3.5 * k)
        h = 1.6 * k
        w = S.tw(lab, h) + 1.4 * k
        hh = h + 1.2 * k
        best = None
        for dd in (3.5, 5.5, 8.0, 11.0):
            for i in range(12):
                a = 2 * math.pi * i / 12
                c = (s_["x"] + math.cos(a) * dd * k, s_["y"] + math.sin(a) * dd * k)
                g = box(c[0] - w / 2, c[1] - hh / 2, c[0] + w / 2, c[1] + hh / 2)
                sc_ = occ.overlap(g) + (1e6 if occ.bounds is not None and not occ.bounds.contains(g) else 0)
                if best is None or sc_ < best[0]:
                    best = (sc_, c, g)
            if best[0] < 1.0:
                break
        _, c, g = best
        S.fill(sp, g, (255, 255, 255), "SD_Электрика")
        Y.outline(sp, g, S.C_RED, 18, "SD_Электрика")
        S.text(sp, lab, c, h, "MIDDLE_CENTER", "SD_Электрика", rgb=S.C_RED)
        q = g.exterior.interpolate(g.exterior.project(Point(s_["x"], s_["y"])))
        if q.distance(Point(s_["x"], s_["y"])) > 1.5 * k:
            S.line(sp, (q.x, q.y), (s_["x"], s_["y"]), "SD_Электрика", S.C_RED, 13)
        occ.add(g.buffer(0.3 * k), "tag")
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    kinds = []
    for s_ in outs:
        if s_["kind"] not in kinds:
            kinds.append(s_["kind"])
    rows = [[kd, SOCKET_NAMES.get(kd, kd), str(sum(1 for s_ in outs if s_["kind"] == kd)),
             ", ".join(str(h) for h in sorted({s_.get("h", 0) for s_ in outs if s_["kind"] == kd}))] for kd in kinds]
    col.table([12, 52, 10, 26], ["Тип", "Наименование", "Кол.", "Н, мм"], rows, title="* Ведомость электровыводов",
              h=1.6, aligns=["C", "L", "C", "C"])
    col.legend([(_lg_socket(kd), SOCKET_NAMES.get(kd, kd)) for kd in kinds] +
               [(_lg_line(S.C_RED, 25), "Привязки выводов к стенам, мм"),
                (lambda p_, cx, cy: (S.rect(p_, cx - 6.5, cy - 1.6, cx + 6.5, cy + 1.6, "SD_Таблицы", S.C_RED, 18),
                                     S.text(p_, "Н= 1100 мм", (cx, cy), 1.5, "MIDDLE_CENTER", "SD_Таблицы", rgb=S.C_RED)),
                 "Высота вывода от чистого пола")], rh=5.2)
    col.notes(A.note_lines("el_outputs", [
        "Высоты - от чистого пола до центра вывода; выводы - с запасом кабеля 300 мм.",
        "Выводы под бра и подсветку - по развёрткам помещений; уточнить по выбранным светильникам.",
    ]))


# ------------------------------------------------------------------ schedule of electrical fittings
def el_fittings(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, None, kind="B")
    col = Column(A, psp, x=24.0, top=280.0, width=300.0, bottom=24.0, spill=[])
    rows = []
    kinds = []
    for s_ in P.sockets:
        if s_["kind"] not in kinds:
            kinds.append(s_["kind"])
    def room_of(o):
        if o.get("room"):
            return o["room"]
        r = P.room_of_point((o["x"], o["y"]), 250)
        return r["name"] if r else ""
    for kd in kinds:
        ss = [s_ for s_ in P.sockets if s_["kind"] == kd]
        rows.append([kd, SOCKET_NAMES.get(kd, kd), str(len(ss)),
                     ", ".join(str(h) for h in sorted({s_.get("h", 0) for s_ in ss})),
                     ", ".join(sorted({room_of(s_) for s_ in ss} - {""}))])
    by_keys = {}
    for w in P.switches:
        by_keys.setdefault(w.get("keys", 1), []).append(w)
    for n_, ws in sorted(by_keys.items()):
        rows.append(["В%d" % n_, "Выключатель %d-клавишный" % n_, str(len(ws)),
                     ", ".join(str(h) for h in sorted({w.get("h", 900) for w in ws})),
                     ", ".join(sorted({w.get("room") or "" for w in ws} - {""}))])
    col.table([14, 78, 12, 40, 156], ["Тип", "Наименование", "Кол.", "Н, мм", "Помещения"], rows,
              title="* Ведомость электрофурнитуры", h=1.8, aligns=["C", "L", "C", "C", "L"],
              total=["", "Общий итог", str(sum(int(r[2]) for r in rows)), "", ""])
    if P.circuits:                               # the groups of the panel (from the sockets plan)
        pn = (P.panel or {}).get("name", "ЩК")
        col.table([14, 60, 60, 166], ["Гр.", "Аппарат", "Кабель", "Потребители"], P.circuits,
                  title="Групповые линии (рекомендуемая схема %s)" % pn, h=1.8, aligns=["C", "L", "L", "L"])
    col.notes(A.note_lines("el_fittings", [
        "Серия и цвет электрофурнитуры - по выбору дизайнера, единая для всего объекта.",
        "Высоты - от чистого пола до центра изделия; в санузлах - влагозащищённое исполнение IP44.",
        "Количество - по планам розеток, выключателей и электровыводов.",
    ]))
