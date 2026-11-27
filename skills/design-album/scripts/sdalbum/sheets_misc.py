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
ZONE_RGB = {"living": (236, 224, 202), "kitchen": (220, 233, 214), "wet": (214, 228, 242), "circulation": (232, 232, 234),
            "public": (240, 226, 204), "bar": (226, 236, 210), "storage": (228, 226, 232)}
ZONE_NAME = {"living": "жилые помещения", "kitchen": "кухня", "wet": "санузлы", "circulation": "прихожая, коридор",
             "public": "зал для посетителей", "bar": "бар (зона персонала)", "storage": "служебные помещения"}


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
    """The title sheet. By default as on the reference album (an axonometry of the flat, the project fields, the city
    and the year); meta.cover_style = "studio" - the studio cover with the hexagon band."""
    if (A.P.meta.get("cover_style") or "reference") != "studio":
        return cover_reference(A, no, title, scale)
    return cover_studio(A, no, title, scale)


COVER_FIELDS = (("Проект", "object"), ("Адрес", "place"), ("Заказчик", "client"), ("Дизайнер", "designer"),
                ("Проектировщик", "engineer"))


def cover_reference(A, no, title, scale):
    """Title of the reference album: no frame; the axonometry of the flat on the left; on the right a vertical line and
    the fields - «Проект» (large) and «Адрес» at the top, «Заказчик» in the middle, «Дизайнер» and «Проектировщик»
    lower, the city and the year at the foot (empty fields left out)."""
    from . import iso3d
    P = A.P
    m = P.meta
    psp = A.make_sheet(no, title, scale, header=False, stamp=False)
    png = os.path.join(A.out_dir, "cover_3d.png")
    got = None
    try:
        got = iso3d.render_models(P, png, elev=38.0, azim=-58.0, width=2400) if (P.d.get("items") or P.furniture) \
            else iso3d.render(P, png)
    except Exception:
        got = None
    if got and os.path.isfile(png):
        iw, ih = Image.open(png).size
        bx0, by0, bx1, by1 = 6.0, 10.0, 300.0, 285.0
        s_ = min((bx1 - bx0) / iw, (by1 - by0) / ih)
        ins = (bx0 + ((bx1 - bx0) - iw * s_) / 2.0, by0 + ((by1 - by0) - ih * s_) / 2.0)
        img = psp.add_image(A.image("cover_3d.png", png), insert=ins, size_in_units=(iw * s_, ih * s_),
                            dxfattribs={"layer": "SD_Мебель"})
        img.rgb = (254, 254, 254)
    xl = 315.0
    S.line(psp, (xl, 12.0), (xl, 284.0), "SD_Тонкие", (150, 150, 150), 13)

    def field(lab, val, y, hl=3.0, hv=3.0):
        """Draw a field; return the y just under its (possibly wrapped) value."""
        if not val:
            return y
        S.text(psp, lab, (xl - 4.0, y), hl, "TOP_RIGHT", "SD_Текст", rgb=(60, 60, 60))
        S.mtext(psp, val, (xl + 4.0, y), hv, 92.0, "SD_Текст", "TOP_LEFT", 1.2)
        return y - S.wrap_count(val, 92.0, hv) * hv * 1.2 * 1.4
    y_addr = min(247.0, field("Проект", (m.get("project") or m.get("object") or "").strip(), 258.0, 4.2, 4.2) - 3.0)
    field("Адрес", (m.get("place") or "").strip(), y_addr)
    field("Заказчик", (m.get("client") or "").strip(), 105.0)
    field("Дизайнер", (m.get("designer") or "").strip(), 58.0)
    field("Проектировщик", (m.get("engineer") or m.get("designer_contact") or "").strip(), 46.0)
    city = (m.get("city") or "").strip()
    year = str(m.get("year") or "").strip()
    if city:
        S.text(psp, city, (xl + 4.0, 22.0), 3.0, "TOP_LEFT", "SD_Текст")
    if year:
        S.text(psp, year, (xl + 4.0, 16.0), 3.0, "TOP_LEFT", "SD_Текст")


def cover_studio(A, no, title, scale):
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


def _merged_title(grp, titles):
    """'Санузлы. План, развёртки А, Б' + 'Санузлы. Развёртки В, Г' + 'Санузлы. Аксонометрия' ->
    'Санузлы. План, развёртки А–Г, аксонометрия'"""
    import re
    plan = any("План" in t for t in titles)
    iso = any("Аксонометрия" in t for t in titles)
    letters = []
    for t in titles:
        m = re.search(r"[Рр]азвёртк[аи] ([А-ЯЁ](?:, [А-ЯЁ])*)", t)
        if m:
            letters += [x.strip() for x in m.group(1).split(",")]
    parts = []
    if plan:
        parts.append("план")
    if letters:
        parts.append(("развёртки %s–%s" % (letters[0], letters[-1])) if len(letters) > 2 else
                     ("развёртки " + ", ".join(letters)) if len(letters) > 1 else "развёртка " + letters[0])
    if iso:
        parts.append("аксонометрия")
    txt = ", ".join(parts)
    return "%s. %s" % (grp, txt[:1].upper() + txt[1:])


def explanatory_items(A):
    """Paragraphs of the explanatory note of the reference album: the existing premises, the project, the content of
    the album, the style (only what the data says)."""
    P = A.P
    m = P.meta
    out = []
    n_r = len(P.rooms)
    out.append(("Существующее помещение", "Помещение общей площадью %s м², %d %s; высота от чистого пола до плиты "
                "перекрытия — %d мм. Размеры — по %s." % (
                    fmt_area(P.total_area()), n_r, "помещение" if n_r == 1 else ("помещения" if n_r < 5 else "помещений"),
                    P.slab, "3D-модели и обмеру заказчика" if m.get("scene_shift") is not None else "исходным данным")))
    proj = []
    if P.parts:
        proj.append("возводятся перегородки (%d шт., см. план монтажа)" % len(P.parts))
    else:
        proj.append("перепланировка не предусмотрена")
    ct = (P.ceilings or {}).get("types") or []
    if ct:
        proj.append("потолки: " + "; ".join("%s — %s" % (t["id"], t.get("short") or t.get("desc", "")) for t in ct))
    fl = P.floors
    if fl:
        proj.append("полы: " + "; ".join("%s — %s" % (f["id"], f.get("material", "")) for f in fl))
    out.append(("Проект", ("; ".join(proj) + ".")[:1].upper() + ("; ".join(proj) + ".")[1:]))
    secs = sorted({t.split(".")[0] for _, k, t, *_ in A.sheets if k not in ("cover", "contents", "letter", "general")},
                  key=lambda x: x)
    out.append(("Состав проекта", "Альбом рабочих чертежей — %d листов (см. «Ведомость рабочих чертежей»): планы, "
                "развёртки стен, 3D-виды, ведомости и сводные ведомости%s." % (
                    A.count, ", мебель индивидуального изготовления" if A.sheet_no("items") else "")))
    if m.get("style"):
        out.append(("Стиль", m["style"]))
    return out


def explanatory_note(A, psp, x, y, width):
    """«Пояснительная записка» under the top y; returns the bottom y."""
    yy = S.heading(psp, x - 5.0, y, "Пояснительная записка")
    for head, txt in explanatory_items(A):
        S.text(psp, head + ":", (x, yy), 2.5, "TOP_LEFT", "SD_Текст")
        yy -= 4.0
        S.mtext(psp, txt, (x, yy), 2.2, width, "SD_Текст", "TOP_LEFT", 1.3)
        yy -= S.wrap_count(txt, width, 2.2) * 2.2 * 1.667 * 1.3 + 3.0
    return yy


def explanatory_sheet(A, no, title, scale):
    """«Пояснительная записка» as on the reference album (stamp B): the text on the left in large lettering, on the
    right the explication of the rooms by the survey and by the project and a picture (a render of meta.renders or the
    axonometry); the questions to the client under the text."""
    P = A.P
    psp = A.make_sheet(no, title, scale, None, header=False, kind="B")
    y = 268.0
    S.text(psp, "Пояснительная записка.", (46.0, y), 3.0, "TOP_LEFT", "SD_Текст")
    y -= 10.0
    for head, txt in explanatory_items(A):
        body = "%s: %s" % (head, txt)
        S.mtext(psp, body, (46.0, y), 3.0, 190.0, "SD_Текст", "TOP_LEFT", 1.3)
        y -= S.wrap_count(body, 190.0, 3.0) * 3.0 * 1.667 * 1.3 + 6.0
    qs = client_questions(A)
    if qs and y > 60:
        S.notes(psp, 41.0, y, qs[:8], 196.0, title="Вопросы к заказчику (до начала работ):")
    tot = P.total_area()
    parts = sum(g.area for g in P.parts.values()) / 1e6 if P.parts else 0.0
    yb = S.table(psp, 250.0, 268.0, [12, 50, 16], ["№", "Наименование", "S, м²"], [["0.1", "Помещение", fmt_area(tot + parts)]],
                 h=2.2, aligns=["C", "L", "R"], title="Экспликация помещений (обмер)", head_h=5.0,
                 total=["", "Общая площадь", fmt_area(tot + parts)])
    rr = [[r["num"], r["name"], fmt_area(r["area"])] for r in P.rooms]
    yb = S.table(psp, 250.0, yb - 10.0, [12, 50, 16], ["№", "Наименование", "S, м²"], rr, h=2.2, aligns=["C", "L", "R"],
                 title="Экспликация помещений", head_h=5.0, total=["", "Общая площадь", fmt_area(tot)])
    pic = None
    rnd = (P.meta.get("renders") or [None])[0]
    if isinstance(rnd, dict):
        rnd = rnd.get("file")
    if rnd:
        pic = rnd if os.path.isabs(rnd) else os.path.join(P.base_dir, rnd)
        if not os.path.isfile(pic):
            pic = None
    if pic is None:
        from . import iso3d
        png = os.path.join(A.out_dir, "iso.png")
        try:
            pic = png if (iso3d.render_models(P, png) if P.d.get("items") else iso3d.render(P, png)) else None
        except Exception:
            pic = None
    if pic:
        iw, ih = Image.open(pic).size
        bw, bh = 80.0, max(30.0, yb - 10.0 - 26.0)
        s_ = min(bw / iw, bh / ih)
        img = psp.add_image(A.image(os.path.basename(pic), pic), insert=(250.0 + (bw - iw * s_) / 2.0, yb - 10.0 - ih * s_),
                            size_in_units=(iw * s_, ih * s_), dxfattribs={"layer": "SD_Мебель"})
        img.rgb = (254, 254, 254)


def general(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, "Пояснительная записка, общие указания, экспликация помещений"
                       if A.sheet_no("contents") is not None else "Состав альбома, общие указания, экспликация помещений")
    rows = []
    sk = [x for x in A.sheets if x[1] == "items" and x[2].startswith("Мебель. ")]
    for n, k, t, s, fn, arg in A.sheets:
        if sk and (n, k, t) == sk[0][:3]:          # the sketches of furniture: one line for all of them
            ks = sorted({int(x[3].split(":")[1]) for x in sk if ":" in str(x[3])})
            sc = ("1:%d" % ks[0]) if len(ks) == 1 else ("1:%d–1:%d" % (ks[0], ks[-1]) if ks else "-")
            first, last = sk[0][2].split(" — ")[0].replace("Мебель. ", ""), sk[-1][2].split(" — ")[0].replace("Мебель. ", "")
            rows.append(["%02d–%02d" % (sk[0][0], sk[-1][0]) if len(sk) > 1 else "%02d" % n,
                         "Мебель. Эскизы изделий %s…%s" % (first, last) if len(sk) > 1 else t, sc, None, t])
            continue
        if sk and any(n == x[0] for x in sk):
            continue
        grp = t.split(". ")[0] if k == "elevations" and ". " in t else None
        if grp and rows and rows[-1][3] == grp:      # the elevations of one room: one line «Зал. Развёртки А–Д»
            prev = rows[-1]
            prev[0] = "%s–%02d" % (prev[0].split("–")[0], n)
            prev[4].append(t)
            prev[1] = _merged_title(grp, prev[4])
            if s and s not in prev[2]:
                prev[2] = prev[2] + ", " + s
            continue
        rows.append(["%02d" % n, t, s or "-", grp, [t]])
    rows = [r[:3] for r in rows]
    if A.sheet_no("contents") is not None:        # the list of sheets has its own sheet: the explanatory note here
        yb = explanatory_note(A, psp, 24, 256, 176)
    else:
        yb = S.table(psp, 24, 256, [14, 118, 40], ["Лист", "Наименование", "Масштаб"], rows, h=1.8, aligns=["C", "L", "C"],
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
    notes_bottom = yb - 9 - 2.0 - sum(S.wrap_count("%d. %s" % (i + 1, l), 176, 2.1) for i, l in enumerate(notes)) * 2.1 * 1.667 * 1.3
    rr, tot = [], 0.0
    for r in P.rooms:
        fl = P.floor_of_room(r["name"])
        rr.append([r["num"], r["name"], fmt_area(r["area"]), ("%.2f" % r["perimeter"]).replace(".", ","),
                   (fl or {}).get("id", "-"), r.get("ceiling_type", "ПО-1")])
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
        S.notes(psp, 214, 46 + hq, qs, wq, title="Вопросы к заказчику (до начала работ):")
        q_top = 46 + hq + 8
    else:                                    # a senior album: the decisions taken instead of open questions
        dec = [x if len(x) <= 150 else x[:147].rsplit(" ", 1)[0] + "..." for x in P.meta.get("decisions", [])][:6]
        if dec:
            wq = 196.0
            n = sum(S.wrap_count("%d. %s" % (i + 1, q), wq, 2.1) for i, q in enumerate(dec))
            hq = 2.0 + n * 2.1 * 1.667 * 1.3
            S.notes(psp, 214, 46 + hq, dec, wq, title="Принятые проектные решения:")
            q_top = 46 + hq + 8
    try:
        from . import iso3d
        png = os.path.join(A.out_dir, "iso.png")
        try:                                  # the furniture models of the scene; blocks when there are none
            got = iso3d.render_models(P, png) if P.d.get("items") else None
        except Exception as ex:
            A.issues.append(dict(code="ISO_MODELS", level="warning", sheet=A.cur_title, msg=repr(ex)))
            got = None
        models = bool(got)
        if got or iso3d.render(P, png):
            iso = A.image("iso.png", png)
            from PIL import Image
            iw, ih = Image.open(png).size
            avail_h = yb2 - 20 - q_top
            hh = min(avail_h, 192.0 * ih / iw)
            ww = hh * iw / ih
            psp.add_image(iso, insert=(214 + (198 - ww) / 2, q_top), size_in_units=(ww, hh),
                          dxfattribs={"layer": "SD_Рамка"}).rgb = (254, 254, 254)
            A.title_note(psp, 214, yb2 - 12, "Аксонометрия", "разрез на отм. +1,450, мебель - %s" % (
                "модели из 3D-сцены" if models else "условно"))
    except Exception as ex:   # 3D view is decorative: never block the album
        A.issues.append(dict(code="ISO_FAILED", level="warning", sheet=A.cur_title, msg=str(ex)))
    # zone scheme
    x0, y0, x1, y1 = P.bounds
    if notes_bottom - 12.0 - 36.0 < 24.0:      # a long list of sheets: no room under the notes - the 3D view and the
        return                                 # explication show the rooms; a scheme on the notes is worse than none
    blk, off = A.model_block(no, 0)
    avail = max(24.0, min(58.0, notes_bottom - 12.0 - 36.0))   # the scheme sits under the notes, never on them
    kk = max(100.0, (x1 - x0 + 600) / 95.0, (y1 - y0 + 600) / avail)
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
