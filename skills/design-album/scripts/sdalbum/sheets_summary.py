# -*- coding: utf-8 -*-
"""Stage 6 of the reference album: the list of the working drawings by sections, the summary schedules (finishes,
doors, lighting and electrics, glass) at the end of the album. Every schedule of a sheet comes again here, for the
whole object."""
import math
from collections import OrderedDict

from shapely.geometry import Polygon

from . import gfx as S
from . import symbols as Y
from .album import Column
from .model import fmt_area

fmt_m = lambda v: ("%.2f" % v).replace(".", ",")
SECTIONS = OrderedDict([("album", "Альбом рабочих чертежей"), ("items", "Мебель индивидуального изготовления"),
                        ("visuals", "Визуализации"), ("summary", "Сводные ведомости")])
SUMMARY_KEYS = ("summary_finishes", "summary_doors", "summary_electric", "summary_glass")


def _section(key):
    if key == "items":
        return "items"
    if key == "visuals":
        return "visuals"
    if key in SUMMARY_KEYS:
        return "summary"
    return "album"


def sheet_rows(A):
    """[(section, «NN» or «NN–MM», name, scale)]: the elevations of a room in one line «Зал. Развёртки, виды 1–8»,
    the sketches of the furniture in one line."""
    out = []
    for n, k, t, s, fn, arg in A.sheets:
        sec = _section(k)
        if k == "elevations" and isinstance(arg, dict) and arg.get("group"):
            g = arg["group"]["name"]
            labels = [e.get("label", "") for e in arg.get("elevs", [])]
            prev = out[-1] if out else None
            if prev and prev[4] == ("elev", g):
                prev[1] = "%s–%02d" % (prev[1].split("–")[0], n)
                prev[5] += labels
                lab = prev[5]
                prev[2] = "%s. %sразвёртки, виды %s–%s" % (g, "план, " if prev[6] else "", lab[0], lab[-1]) \
                    if len(lab) > 1 else prev[2]
                if s and s not in prev[3]:
                    prev[3] = prev[3] + ", " + s
                continue
            out.append([sec, "%02d" % n, t, s or "—", ("elev", g), labels, "План" in t])
            continue
        if k == "items" and t.startswith("Мебель. "):
            prev = out[-1] if out else None
            if prev and prev[4] == ("items", None):
                prev[1] = "%s–%02d" % (prev[1].split("–")[0], n)
                prev[5].append(t.split(" — ")[0].replace("Мебель. ", ""))
                prev[2] = "Эскизы изделий %s…%s" % (prev[5][0], prev[5][-1])
                continue
            out.append([sec, "%02d" % n, t, s or "—", ("items", None), [t.split(" — ")[0].replace("Мебель. ", "")], False])
            continue
        out.append([sec, "%02d" % n, t, s or "—", None, [], False])
    return [(r[0], r[1], r[2], r[3]) for r in out]


def contents(A, no, title, scale):
    """«Ведомость рабочих чертежей» by sections, in two columns when long."""
    psp = A.make_sheet(no, title, scale, None, kind="B")
    rows = []
    by = OrderedDict((k, []) for k in SECTIONS)
    for sec, num, name, sc in sheet_rows(A):
        by[sec].append([num, name, sc])
    for sec, rs in by.items():
        if not rs:
            continue
        rows.append(dict(cells=["", SECTIONS[sec], ""], fill=(236, 236, 238)))
        rows += rs
    half = int(math.ceil(len(rows) / 2.0)) if len(rows) > 26 else len(rows)
    parts = [rows[:half], rows[half:]] if half < len(rows) else [rows]
    x = 24.0
    for i, part in enumerate(parts):
        if not part:
            continue
        S.table(psp, x, 272.0, [14, 140, 30], ["Лист", "Наименование", "Масштаб"], part, h=1.8,
                aligns=["C", "L", "C"], title="Ведомость рабочих чертежей" + (" (продолжение)" if i else ""), head_h=6.0)
        x += 196.0


# ------------------------------------------------------------------ summary schedules
def _finish_tables(A):
    """[(title, widths, header, rows, aligns, total)] of the whole object: walls by mark, floors, ceilings, plinths,
    mouldings, cornices."""
    from . import sheets_plans as SP
    from . import sheets_more as SX
    P = A.P
    out = []
    F = P.finishes or {}
    types = F.get("types") or []
    frgb = {t["id"]: tuple(t.get("rgb", SP.FIN_RGB_DEFAULT[i % len(SP.FIN_RGB_DEFAULT)])) for i, t in enumerate(types)}
    tot_w = OrderedDict()
    for rm, split in SP.room_wall_finishes(P):
        for t, v in split.items():
            tot_w[t] = tot_w.get(t, 0.0) + v
    desc = {t["id"]: t.get("desc", "") for t in types}
    rows = [[t, S.uo_line(frgb.get(t, (150, 150, 150)), 70), desc.get(t, ""), fmt_area(v)] for t, v in tot_w.items()]
    if rows:
        out.append(("* Сводная ведомость отделки стен", [12, 12, 130, 22], ["Марка", "УО", "Наименование", "Площадь, м²"],
                    rows, ["C", "C", "L", "C"], ["", "", "Общий итог", fmt_area(sum(tot_w.values()))]))
    tints = SP.floor_tints(P)
    fa = OrderedDict()
    for f, g in P.floor_zones():
        fa.setdefault(f["id"], [f, 0.0])[1] += g.area / 1e6
    rows = [[fid, S.uo_fill(tints.get(fid, (220, 220, 220))), f.get("material", ""), fmt_area(a),
             fmt_area(a * (1 + f.get("reserve", 0.1)))] for fid, (f, a) in fa.items()]
    if rows:
        out.append(("* Сводная ведомость полов", [12, 12, 108, 22, 22], ["Марка", "УО", "Наименование", "Площадь, м²",
                                                                       "С запасом, м²"], rows, ["C", "C", "L", "C", "C"],
                    ["", "", "Общий итог", fmt_area(sum(a for _, a in fa.values())),
                     fmt_area(sum(a * (1 + f.get("reserve", 0.1)) for f, a in fa.values()))]))
    ct = (P.ceilings or {}).get("types") or []
    ca = OrderedDict((t["id"], 0.0) for t in ct)
    for r in P.rooms:
        if r.get("ceiling_type") in ca:
            ca[r["ceiling_type"]] += r["area"]
    rows = [[t["id"], S.uo_fill(SP.C_T[i % len(SP.C_T)]), t.get("desc", t.get("short", "")), fmt_area(ca[t["id"]])]
            for i, t in enumerate(ct) if ca.get(t["id"], 0) > 0]
    if rows:
        out.append(("* Сводная ведомость потолков", [12, 12, 130, 22], ["Марка", "УО", "Наименование", "Площадь, м²"], rows,
                    ["C", "C", "L", "C"], ["", "", "Общий итог", fmt_area(sum(ca.values()))]))
    pl = P.d.get("plinths") or {}
    ptypes = {t["id"]: t for t in pl.get("types", [])}
    pt = OrderedDict()
    for r, t, parts in SX.plinth_runs(P):
        pt[t] = pt.get(t, 0.0) + sum(g.length for g in parts) / 1000.0
    rows = [[t, S.uo_line(tuple(ptypes.get(t, {}).get("rgb", (150, 110, 70))), 70), ptypes.get(t, {}).get("desc", ""),
             fmt_m(v), fmt_m(v * 1.1)] for t, v in pt.items()]
    if rows:
        out.append(("* Сводная ведомость плинтусов", [12, 12, 108, 22, 22], ["Марка", "УО", "Наименование", "Длина, м.п.",
                                                                            "С запасом"], rows, ["C", "C", "L", "C", "C"], None))
    ml, prof = OrderedDict(), {}
    for e in P.elevations:
        for it in e.get("items", []):
            if (it.get("mark") or "").startswith("МЛ"):
                ml[it["mark"]] = ml.get(it["mark"], 0.0) + it.get("length", 0.0)
                prof.setdefault(it["mark"], it.get("profile"))
    rows = [[m, S.uo_line((150, 120, 80), 50), "Молдинг, профиль %s мм (по 3D-модели; артикул — по каталогу)" % prof[m],
             fmt_m(v), fmt_m(v * 1.1)] for m, v in sorted(ml.items())]
    if rows:
        out.append(("* Сводная ведомость молдингов", [12, 12, 108, 22, 22], ["Марка", "УО", "Наименование", "Длина, м.п.",
                                                                            "С запасом"], rows, ["C", "C", "L", "C", "C"],
                    ["", "", "Общий итог", fmt_m(sum(ml.values())), fmt_m(sum(ml.values()) * 1.1)]))
    rs = SX.rails(P)
    if rs:
        out.append(("* Сводная ведомость карнизов", [12, 12, 108, 22, 22], ["Марка", "УО", "Наименование", "Кол.", "Длина, м"],
                    [["К-1", S.uo_line((150, 110, 70), 70), "Карниз потолочный для штор, 2-рядный, скрытый монтаж",
                      str(len(rs)), fmt_m(sum(L for _, L, _ in rs) / 1000.0)]], ["C", "C", "L", "C", "C"], None))
    return out


def _door_tables(A):
    P = A.P
    doors = OrderedDict()
    for o in P.openings:
        if o["kind"] in ("door", "balcony"):
            doors.setdefault(o.get("mark") or "Д-?", []).append(o)
    rows = []
    for m, os_ in sorted(doors.items()):
        o = os_[0]
        hands = sorted({P.door_hand(x) for x in os_} - {None})
        rooms = sorted({r["name"] for x in os_ for r in [P.room_of_point((P.open_shape[x["id"]].centroid.x,
                                                                           P.open_shape[x["id"]].centroid.y), 600)] if r})
        rows.append([m, "%d×%d" % (o["w"], o["h"]), "балконная" if o["kind"] == "balcony" else "распашная",
                     ", ".join({"L": "лев.", "R": "прав."}.get(h, h) for h in hands) or "—", ", ".join(rooms), str(len(os_))])
    if not rows:
        return []
    return [("Сводная ведомость дверей", [14, 24, 30, 22, 78, 12], ["Марка", "Ш×В, мм", "Тип", "Открывание", "Помещения", "Кол."],
             rows, ["C", "C", "L", "C", "L", "C"], ["", "", "", "", "Общий итог", str(sum(len(v) for v in doors.values()))])]


def _electric_tables(A):
    from .sheets_light import light_types, _icon
    from .sheets_more import SOCKET_NAMES
    P = A.P
    out = []
    lt = light_types(P)
    rows = [[t["mark"], _icon(t), t["desc"], str(len(t["fixtures"])),
             ", ".join(sorted({f.get("group", "") for f in t["fixtures"]} - {""}))] for t in lt]
    if rows:
        out.append(("* Сводная ведомость светильников", [14, 14, 100, 12, 40], ["Марка", "УО", "Наименование", "Кол.",
                                                                                "Помещения"], rows, ["C", "C", "L", "C", "L"],
                    ["", "", "Общий итог", str(sum(len(t["fixtures"]) for t in lt)), ""]))
    kinds = OrderedDict()
    for s_ in P.sockets:
        kinds[s_["kind"]] = kinds.get(s_["kind"], 0) + 1
    rows = [[k, SOCKET_NAMES.get(k, k), str(v)] for k, v in kinds.items()]
    by_keys = OrderedDict()
    for w in P.switches:
        by_keys[w.get("keys", 1)] = by_keys.get(w.get("keys", 1), 0) + 1
    rows += [["В%d" % n_, "Выключатель %d-клавишный" % n_, str(v)] for n_, v in sorted(by_keys.items())]
    if rows:
        out.append(("* Сводная ведомость электрофурнитуры", [14, 140, 26], ["Тип", "Наименование", "Кол."], rows,
                    ["C", "L", "C"], ["", "Общий итог", str(sum(int(r[2]) for r in rows))]))
    return out


def _glass_tables(A):
    """Glazing of the windows (area of the glass by type) and mirrors (furniture, the elevations)."""
    P = A.P
    rows = []
    by = OrderedDict()
    for o in P.openings:
        if o["kind"] == "window":
            by.setdefault(o.get("mark") or "ОК-?", []).append(o)
    for m, os_ in by.items():
        o = os_[0]
        a = max(0.0, (o["w"] - 120) * (o["h"] - 120)) / 1e6
        rows.append([m, "Стеклопакет окна (светопрозрачное заполнение)", "%d×%d" % (o["w"], o["h"]), str(len(os_)),
                     fmt_area(a * len(os_))])
    mirrors = [f for f in P.furniture if f.get("kind") == "mirror"]
    for f in mirrors:
        g = Polygon(f["poly"]).buffer(0)
        x0, y0, x1, y1 = g.bounds
        w = max(x1 - x0, y1 - y0)
        h = (f.get("z") or [1100, 1700])[1] - (f.get("z") or [1100, 1700])[0]
        rows.append(["З", "Зеркало %s" % (f.get("name") or ""), "%d×%d" % (round(w), round(h)), "1", fmt_area(w * h / 1e6)])
    for e in P.elevations:
        for it in e.get("items", []):
            if it.get("cat") == "mirror":
                g = Polygon(it["pts"]).buffer(0)
                x0, y0, x1, y1 = g.bounds
                rows.append(["З", "Зеркало (по 3D-модели), %s" % (e.get("room") or ""), "%d×%d" % (x1 - x0, y1 - y0), "1",
                             fmt_area(g.area / 1e6)])
    if not rows:
        return []
    return [("* Сводная ведомость стекла и зеркал", [14, 96, 30, 12, 26], ["Марка", "Наименование", "Размер, мм", "Кол.",
                                                                          "Площадь, м²"], rows, ["C", "L", "C", "C", "C"], None)]


TABLES = {"summary_finishes": _finish_tables, "summary_doors": _door_tables, "summary_electric": _electric_tables,
          "summary_glass": _glass_tables}
TITLES = {"summary_finishes": "Сводная ведомость отделки", "summary_doors": "Сводная ведомость дверей",
          "summary_electric": "Сводная ведомость освещения и электрики", "summary_glass": "Сводная ведомость стекла"}


def has_data(A, key):
    if key in TABLES:
        try:
            return bool(TABLES[key](A))
        except Exception:
            return False
    return True


def summary_sheet(A, no, title, scale, key):
    """A summary schedule on a stamp B sheet: the tables one under another, on to the right half when long."""
    psp = A.make_sheet(no, title, scale, None, kind="B")
    col = Column(A, psp, x=24.0, top=272.0, width=188.0, bottom=36.0, spill=[(220.0, 272.0, 190.0, 36.0)])
    for ttl, widths, header, rows, aligns, total in TABLES[key](A):
        col.table(widths, header, rows, title=ttl, h=1.7, aligns=aligns, total=total, allow_band=False)
