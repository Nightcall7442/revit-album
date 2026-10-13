# -*- coding: utf-8 -*-
"""Cover, letter to the client, general data sheet."""
import math
import os
import re
from PIL import Image
from shapely.geometry import Polygon, Point, box

from . import gfx as S
from . import symbols as Y
from .album import BRONZE, Column
from .model import fmt_area

DEFAULT_LETTER = [
    "Благодарим Вас за выбор нашей студии и оказанное доверие!",
    "Надеемся, что Вы довольны проделанной работой над дизайн-проектом. Нам было очень приятно работать над Вашим интерьером.",
    "Хотим пожелать Вам лёгкого ремонта и успешной реализации всех наших с Вами идей.",
    "В этом альбоме собраны рабочие чертежи и ведомости материалов, которые понадобятся строителям для ремонтных работ. "
    "Визуализации интерьера собраны в отдельном альбоме.",
    "Мы всегда будем ждать Вас в нашей студии за новыми проектами!",
]
ZONE_RGB = {"living": (236, 224, 202), "kitchen": (220, 233, 214), "wet": (214, 228, 242), "circulation": (232, 232, 234)}
ZONE_NAME = {"living": "жилые помещения", "kitchen": "кухня", "wet": "санузлы", "circulation": "прихожая, коридор"}


def has_data(A, key):
    return True


def _hex(cx, cy, R):
    return [(cx + R * math.cos(math.radians(60 * i)), cy + R * math.sin(math.radians(60 * i))) for i in range(6)]


def _band_grey(y_mm):
    i = min(59, max(0, int(y_mm / (297.0 / 60))))
    g = int(196 + 44 * i / 59.0)
    return (g, g, g + 1)


def _logo_on_gradient(src, dst, insert, w_mm):
    """PDF renderers drop the alpha of RGBA images (the logo vanished, lesson L-030): compose the logo onto the
    exact cover gradient bands it sits on and save an opaque RGB image."""
    im = Image.open(src).convert("RGBA")
    W, H = im.size
    h_mm = w_mm * H / float(W)
    bg = Image.new("RGBA", (W, H))
    px = bg.load()
    for r in range(H):
        y = insert[1] + h_mm - (r + 0.5) * h_mm / H
        c = _band_grey(y) + (255,)
        for x in range(W):
            px[x, r] = c
    out = Image.alpha_composite(bg, im).convert("RGB")
    out.save(dst)
    return dst


def cover(A, no, title, scale):
    m = A.P.meta
    psp = A.make_sheet(no, title, scale, header=False, stamp=False)
    lw_mm = 120.0
    li = Image.open(os.path.join(S.ASSETS, "logo.png") if not m.get("logo_transparent") else
                    (m["logo_transparent"] if os.path.isabs(m["logo_transparent"])
                     else os.path.join(A.P.base_dir, m["logo_transparent"])))
    hole = box(28, 232, 28 + lw_mm, 232 + lw_mm * li.size[1] / float(li.size[0]))
    for i in range(60):
        y0 = 297.0 * i / 60
        band_ = box(0, y0, 420, y0 + 297.0 / 60 + 0.2).difference(hole)   # the PDF renderer puts images UNDER
        if not band_.is_empty:                                               # vector fills: leave a hole for the logo
            S.fill(psp, band_, _band_grey(y0 + 0.01), "SD_Рамка")
    band = Polygon([(0, 205), (0, 120), (120, 55), (230, 0), (420, 0), (420, 30), (300, 85), (170, 150), (60, 205)])
    R = 13.0
    dx = R * 1.5
    dy = R * math.sqrt(3)
    for i in range(-1, 32):
        for j in range(-1, 20):
            cx = i * dx + 4
            cy = j * dy + (dy / 2 if i % 2 else 0)
            if band.contains(Point(cx, cy)):
                S.fill(psp, _hex(cx, cy, R - 1.4), (255, 255, 255), "SD_Рамка")
    for (cx, cy) in ((372, 120), (395, 60)):
        S.fill(psp, _hex(cx, cy, R - 1.4), (255, 255, 255), "SD_Рамка")
    iw, ih = A.logo_def.dxf.image_size.x, A.logo_def.dxf.image_size.y
    src = m.get("logo_transparent") or os.path.join(S.ASSETS, "logo.png")
    if not os.path.isabs(src):
        src = os.path.join(A.P.base_dir, src)
    w = 120.0
    flat = _logo_on_gradient(src, os.path.join(A.out_dir, "logo_cover.png"), (28, 232), w)
    logo = A.image("logo_cover.png", flat)
    lw, lh = Image.open(flat).size
    img = psp.add_image(logo, insert=(28, 232), size_in_units=(w, w * lh / lw), dxfattribs={"layer": "SD_Штамп"})
    img.rgb = _band_grey(232 + w * lh / lw / 2.0)       # the renderer always draws the image frame: make it the paper
    if m.get("tagline"):
        S.text(psp, m["tagline"], (110, 222), 2.6, "MIDDLE_LEFT", rgb=(70, 70, 70))
    lines = m.get("title", "ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА").split("|")
    for i, t in enumerate(lines):
        S.text(psp, t, (270, 190 - i * 11), 7.2, "MIDDLE_CENTER", bold=True, rgb=(25, 25, 25))
    S.text(psp, m.get("album", "АЛЬБОМ 1  ·  РАБОЧИЕ ЧЕРТЕЖИ"), (270, 190 - len(lines) * 11 - 3), 3.4, "MIDDLE_CENTER", rgb=(70, 70, 70))
    S.line(psp, (250, 190 - len(lines) * 11 - 8.5), (290, 190 - len(lines) * 11 - 8.5), "SD_Тонкие", BRONZE, 50)
    S.text(psp, m.get("cover_footer", "%s %s" % (m.get("country", ""), m.get("year", ""))).strip(), (395, 22), 4.0,
           "MIDDLE_RIGHT", rgb=(40, 40, 40))


def letter(A, no, title, scale):
    m = A.P.meta
    psp = A.make_sheet(no, title, scale, header=False, stamp=False)
    S.rect(psp, 0, 0, 420, 297, "SD_Тонкие", (215, 215, 215))
    S.fill(psp, [(0, 0), (8, 0), (8, 297), (0, 297)], (40, 40, 42), "SD_Рамка")
    iw, ih = A.logo_def.dxf.image_size.x, A.logo_def.dxf.image_size.y
    w = 92.0
    img = psp.add_image(A.logo_def, insert=(164, 232), size_in_units=(w, w * ih / iw), dxfattribs={"layer": "SD_Штамп"})
    img.rgb = (254, 254, 254)
    S.line(psp, (190, 222), (230, 222), "SD_Тонкие", BRONZE, 50)
    S.text(psp, m.get("letter_title", "Уважаемый заказчик!"), (210, 206), 7.0, "MIDDLE_CENTER", bold=True)
    paras = m.get("letter") or DEFAULT_LETTER
    S.mtext(psp, "\\P\\P".join(paras), (95, 192), 3.6, 230, attach="TOP_LEFT", spacing=1.45)
    S.text(psp, m.get("signature", "С наилучшими пожеланиями, команда %s!" % m.get("studio", "студии")), (325, 70), 3.6,
           "MIDDLE_RIGHT", bold=True)
    S.text(psp, ("%s %s" % (m.get("place", ""), m.get("year", ""))).strip(), (325, 63), 3.0, "MIDDLE_RIGHT", rgb=(120, 120, 120))


QUESTION_CODES = {
    "DOORS_CLASH": "сменить сторону открывания одной из дверей или поставить ограничитель",
    "DOOR_HITS_FURNITURE": "сменить сторону / руку двери или сдвинуть мебель",
    "LEAF_WIDER_THAN_OPENING": "подтвердить размер проёма или полотна",
}


def client_questions(A):
    """Decisions that belong to the client / designer, not to the draughtsman: listed on the general data sheet."""
    from . import validate
    out = list(A.P.meta.get("questions", []))
    fsh = A.sheet_no("furniture")
    for i in validate.run(A.P):
        if i["code"] in QUESTION_CODES:
            ref = " (лист %02d)" % fsh if fsh else ""
            out.append("%s%s - %s." % (i["msg"][0].upper() + i["msg"][1:], ref, QUESTION_CODES[i["code"]]))
    return out


def general(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, "Состав альбома, общие указания, экспликация помещений")
    rows = [["%02d" % n, t, s or "-"] for n, k, t, s, fn, arg in A.sheets]
    yb = S.table(psp, 24, 256, [12, 120, 40], ["Лист", "Наименование", "Масштаб"], rows, h=1.8, aligns=["C", "L", "C"],
                 title="Ведомость листов", head_h=6.0, zebra=True)
    notes = A.note_lines("general", [
        "Дизайн-проект разработан по исходным данным заказчика (3D-модель / чертежи / обмер).",
        "Все размеры - в миллиметрах, отметки - в метрах от уровня чистого пола (±0,000).",
        "До начала работ подрядчик выполняет контрольный обмер и сообщает о расхождениях.",
        "Позиции электроустановочных изделий, светильников и выводов, не заданные в исходных данных, являются "
        "проектным предложением и согласуются с заказчиком.",
        "Электромонтаж - по ПУЭ и местным нормам; схема щита - рекомендуемая, окончательно - по электропроекту.",
        "Материалы, сантехника, светильники и мебель согласуются с дизайнером до закупки.",
        "Скрытые работы - фотофиксация до закрытия. Изменения - только по согласованию со студией.",
    ])
    S.notes(psp, 24, yb - 9, notes, 176)
    rr, tot = [], 0.0
    for r in P.rooms:
        fl = P.floor_of_room(r["name"])
        rr.append([r["num"], r["name"], fmt_area(r["area"]), ("%.2f" % r["perimeter"]).replace(".", ","),
                   (fl or {}).get("id", "-"), r.get("ceiling_type", "Т1")])
        tot += r["area"]                     # the column must add up (lesson L-025)
    yb2 = S.table(psp, 214, 256, [10, 70, 26, 26, 30, 36], ["№", "Наименование", "Площадь, м²", "Периметр, м", "Тип пола", "Тип потолка"],
                  rr, h=1.8, aligns=["C", "L", "C", "C", "C", "C"], title="Экспликация помещений", head_h=6.5,
                  total=["", "Общая площадь", fmt_area(tot), "", "", ""])
    # questions to the client: design conflicts found by the data checks + meta.questions (lesson L-048)
    qs = client_questions(A)
    q_top = 44.0
    if qs:
        wq = 196.0
        n = sum(max(1, math.ceil(S.tw("%d. %s" % (i + 1, q), 2.1) / (wq - 2))) for i, q in enumerate(qs))
        hq = 4.0 + n * 2.1 * 1.3 * 1.25
        S.notes(psp, 214, 38 + hq, qs, wq, title="Вопросы к заказчику (до начала работ):")
        q_top = 38 + hq + 8
    try:
        from . import iso3d
        png = os.path.join(A.out_dir, "iso.png")
        if iso3d.render(P, png):
            iso = A.image("iso.png", png)
            from PIL import Image
            iw, ih = Image.open(png).size
            avail_h = yb2 - 20 - q_top
            hh = min(avail_h, 192.0 * ih / iw)
            ww = hh * iw / ih
            psp.add_image(iso, insert=(214 + (198 - ww) / 2, q_top), size_in_units=(ww, hh),
                          dxfattribs={"layer": "SD_Рамка"}).rgb = (254, 254, 254)
            A.title_note(psp, 214, yb2 - 12, "Аксонометрия", "разрез на отм. +1,450, мебель условно")
    except Exception as ex:   # 3D view is decorative: never block the album
        A.issues.append(dict(code="ISO_FAILED", level="warning", sheet=A.cur_title, msg=str(ex)))
    # zone scheme
    blk, off = A.model_block(no, 0)
    x0, y0, x1, y1 = P.bounds
    kk = max(100.0, (x1 - x0 + 600) / 95.0, (y1 - y0 + 600) / 58.0)
    for r in P.rooms:
        S.fill(blk, r["shp"], ZONE_RGB.get(r.get("cls", "living"), (236, 224, 202)), "SD_Штриховка")
    Y.draw_walls(blk, P, kk)
    Y.draw_openings(blk, P, kk)
    from shapely.ops import polylabel
    for r in P.rooms:
        c = polylabel(r["shp"], 10)
        Y.mark_circle(blk, r["num"], (c.x, c.y), kk, r=2.0, h=2.0)
    pr = A.vp(psp, off, (x0 - 300, y0 - 300, x1 + 300, y1 + 300), (24, 36), kk)
    if pr[3] + 8 > yb - 9 - 2.1 * 1.667 * 1.3 * 12:
        pass
    A.title_note(psp, pr[0], pr[3] + 3, "Схема помещений", "без масштаба", h=3.2)
    used = []
    for r in P.rooms:
        c = r.get("cls", "living")
        if c not in used:
            used.append(c)
    for i, c in enumerate(used):
        xx, yy = pr[2] + 8, pr[3] - 6 - i * 7
        S.fill(psp, [(xx, yy - 1.8), (xx + 6, yy - 1.8), (xx + 6, yy + 1.8), (xx, yy + 1.8)], ZONE_RGB.get(c, (230, 230, 230)), "SD_Таблицы")
        S.rect(psp, xx, yy - 1.8, xx + 6, yy + 1.8, "SD_Таблицы", (120, 120, 120), 9)
        zn = ZONE_NAME.get(c, c)
        if c == "living" and not re.search(r"квартир|дом", P.meta.get("object", "квартиры"), re.I):
            zn = "залы, основные помещения"           # a cafe hall is not a «жилое помещение»
        S.text(psp, zn, (xx + 8, yy), 2.2, "MIDDLE_LEFT", rgb=(80, 80, 80))
