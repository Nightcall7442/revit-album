# -*- coding: utf-8 -*-
"""Lighting of the reference album in four sheets: marking (СВ / ТР / П marks without frames), the schedule of the
fixtures with their pictures, bindings of every fixture (sheets_plans.lighting_bind) and the switches with their
groups (sheets_plans.lighting_switch)."""
import os

from shapely.ops import unary_union

from . import gfx as S
from . import symbols as Y
from .album import Column
from .sheets_plans import LIGHT_SPEC, label_near, outer, reg_swings, reg_walls, room_tags

PREFIX = {"track": "ТР", "track_rect": "ТР", "led": "П", "linear": "П"}
KIND_RU = {"spot": "встраиваемый", "spot_ip44": "встраиваемый IP44", "spot2": "встраиваемый двойной",
           "spot2_ip44": "встраиваемый двойной IP44", "surface": "накладной", "chandelier": "люстра", "pendant": "подвес",
           "wall": "бра", "track": "шинопровод", "track_rect": "шинопровод (контур)", "track_spot": "трековый спот",
           "linear": "линейный", "led": "светодиодная лента в профиле"}


def light_types(P):
    """[dict(mark, kind, heads, model, desc, fixtures)] - one type per kind / number of heads / model; marks СВ-n,
    ТР-n (tracks), П-n (profiles, LED) numbered within the prefix."""
    spec = P.d.get("lighting_spec", {})
    types, n = [], {}
    for f in P.lighting:
        key = (f["kind"], f.get("heads", 1), f.get("model") or "")
        t = next((x for x in types if x["key"] == key), None)
        if t is None:
            pre = PREFIX.get(f["kind"], "СВ")
            n[pre] = n.get(pre, 0) + 1
            desc = spec.get(f["kind"], LIGHT_SPEC.get(f["kind"], KIND_RU.get(f["kind"], f["kind"])))
            if f.get("heads", 1) > 1:
                desc = "Светильник %s, модуль %d головки (по модели)" % (KIND_RU.get(f["kind"], ""), f["heads"])
            if f.get("model") and f["kind"] in ("chandelier", "pendant", "wall"):
                desc = f["model"]
            t = dict(key=key, mark="%s-%d" % (pre, n[pre]), kind=f["kind"], heads=f.get("heads", 1),
                     model=f.get("model") or "", desc=desc, fixtures=[], item=f.get("item"))
            types.append(t)
        t["fixtures"].append(f)
    return types


def mark_of(P):
    out = {}
    for t in light_types(P):
        for f in t["fixtures"]:
            out[id(f)] = t["mark"]
    return out


def _icon(t):
    def fn(psp, cx, cy, w=14.0, h=6.0):
        f = dict(kind=t["kind"], x=cx, y=cy, heads=t["heads"])
        if t["heads"] > 1:
            f["ends"] = [[cx - 2, cy], [cx + 2, cy]]
        if t["kind"] in ("track", "linear", "led"):
            f.update(x=cx - 6, x2=cx + 6, y2=cy)
        if t["kind"] == "track_rect":
            f.update(x=cx - 6, y=cy - 1.8, x2=cx + 6, y2=cy + 1.8)
        if t["kind"] == "wall":
            f.update(y=cy - 1.5, nx=0.0, ny=1.0)
        if t["kind"] == "chandelier":
            f.pop("d", None)
        Y.light_icon(psp, f, 0.7)
    return fn


def lighting_marks(A, no, title, scale):
    P = A.P
    k = A.plan_k
    psp, sp, occ = A.plan_sheet(no, title, scale, None)
    S.fill(sp, unary_union([r["shp"] for r in P.rooms]), (252, 252, 252), "SD_Штриховка")
    Y.furniture_ghost(sp, P, k)
    Y.draw_walls(sp, P, k)
    Y.draw_openings(sp, P, k, door_rgb=(150, 150, 150))
    reg_walls(A, occ)
    reg_swings(A, occ)
    types = light_types(P)
    for f in P.lighting:
        occ.add(Y.light_icon(sp, f, k), "sym")
    for t in types:                               # marks without frames, as on the reference album
        for f in t["fixtures"]:
            if f["kind"] in ("track", "linear", "led"):
                p = ((f["x"] + f["x2"]) / 2.0, (f["y"] + f["y2"]) / 2.0)
            else:
                p = (f["x"], f["y"])
            label_near(A, sp, occ, t["mark"], p, h=1.9, dists=(2.6, 3.6, 5.0, 7.0), rgb=(20, 20, 20))
    room_tags(A, sp, occ)
    outer(A, sp, occ, sides=("B", "L"), openings=False)
    col = Column(A, psp)
    rows = [[t["mark"], _icon(t), t["desc"], str(len(t["fixtures"]))] for t in types]
    col.table([12, 14, 62, 10], ["Марка", "УО", "Наименование", "Кол."], rows, title="Светильники", h=1.6,
              aligns=["C", "C", "L", "C"], total=["", "", "Общий итог", str(sum(len(t["fixtures"]) for t in types))])
    col.notes(A.note_lines("lighting_marks", [
        "Марки светильников - см. «Ведомость светильников»; привязки - лист «План освещения. Привязки».",
        "Светильники - по 3D-модели дизайнера; модели и цветовую температуру согласовать до закупки.",
    ]))


def _mount(t):
    f = t["fixtures"][0]
    if t["kind"] == "chandelier":
        zs = sorted({x.get("z") for x in t["fixtures"] if x.get("z")})
        return "подвес, низ " + ", ".join(("+%.3f" % (z / 1000.0)).replace(".", ",") for z in zs) if zs else "подвес"
    if t["kind"] == "wall":
        hs = sorted({x.get("h") for x in t["fixtures"] if x.get("h")})
        return "на стене, Н= " + ", ".join("%d мм" % h for h in hs)
    if t["kind"] in ("spot", "spot_ip44", "spot2", "spot2_ip44"):
        return "встраиваемый в потолок"
    if t["kind"] == "pendant":
        return "подвес над столом / зоной, высота - по месту"
    if t["kind"] in ("track", "track_rect", "track_spot"):
        return "на шинопроводе / подвес"
    return "на потолке"


def _picture(A, t):
    """The 3D picture of the fixture (its sketch sheet made it) or its plan symbol."""
    pic = None
    if t.get("item"):
        it = next((i for i in A.P.d.get("items") or [] if i.get("pos") == t["item"]), None)
        if it is not None:
            for nm in ("item_%s_axo.png" % it["id"], "item_%s_a.png" % t["item"]):
                pth = os.path.join(A.out_dir, nm)
                if os.path.isfile(pth):
                    pic = pth
                    break
    if pic is None:
        return _icon(t)

    def fn(psp, cx, cy, w, h):
        from PIL import Image
        idef = A.image(os.path.basename(pic), pic)
        iw, ih = Image.open(pic).size
        s_ = min((w - 2.0) / iw, (h - 2.0) / ih)
        psp.add_image(idef, insert=(cx - iw * s_ / 2.0, cy - ih * s_ / 2.0), size_in_units=(iw * s_, ih * s_),
                      dxfattribs={"layer": "SD_Таблицы"})
    return fn


def lighting_schedule(A, no, title, scale):
    """«* Ведомость светильников»: mark, picture, name, quantity, rooms, mounting (stamp B, the whole width)."""
    P = A.P
    psp = A.make_sheet(no, title, scale, None, kind="B")
    types = light_types(P)
    rows = []
    for t in types:
        rooms = ", ".join(sorted({f.get("group", "") for f in t["fixtures"]} - {""}))
        rows.append([t["mark"], _picture(A, t), t["desc"], str(len(t["fixtures"])), rooms, _mount(t)])
    rh = max(9.0, min(22.0, (272.0 - 40.0 - 6.0 - 6.0 - 4.5) / (len(rows) + 1)))   # down to the stamp B strip
    S.table(psp, 24.0, 272.0, [16, 34, 150, 14, 70, 74], ["Марка", "Изображение", "Наименование", "Кол.", "Помещения",
                                                         "Монтаж"], rows, h=1.9, row_h=rh, head_h=6.0,
            aligns=["C", "C", "L", "C", "L", "L"], title="* Ведомость светильников",
            total=["", "", "Общий итог", str(sum(len(t["fixtures"]) for t in types)), "", ""])
