# -*- coding: utf-8 -*-
"""Senior decisions on the furniture items of the scene (sheets «Мебель индивидуального изготовления»).

    log = decide(d, base_dir)

For every item (importers/scene_items) the agent decides like a senior designer handing furniture to a workshop:
  what it is        by object / material names, else by its geometry (a fabric piece 1.5 m+ long with a seat is a
                    sofa, a low base with soft parts on it is a built-in bench, a 1 m+ tall shallow piece is a shelving,
                    a flat top at 650-800 is a table, below 550 a coffee table, many square sleeves - vinyl records);
  materials         by element (table top / base, upholstery / frame, carcass / shelves / backlight / back panel,
                    base / cushions) from the material names of the scene, else «по образцу, согласовать с дизайнером»;
  where it stands   room of every place, a shelving built around a column says so;
  notes             production notes by type (ГОСТ 16371-2014, ГОСТ 19917-2014, upholstery for a public interior,
                    stone sealing, LED backlight, fixing to the wall, measure on site for built-in pieces);
  position          М-1, М-2 ... by room and type; the plan of furniture gets the pieces it did not have.
Fields the user set (item["auto"] is False) are kept as they are.
"""
import math
import re

import numpy as np

from . import items3d

KIND_ORDER = ["table", "coffee_table", "chair", "armchair", "sofa", "bench", "shelving", "bookshelf", "records",
              "chandelier", "sconce", "decor", "sign", "item"]
LIGHT_KINDS = ("chandelier", "sconce")
RX = [
    ("bookshelf", r"(?i)bookshel|книжн"),
    ("records", r"(?i)vinyl|record|пластин"),
    ("shelving", r"(?i)\brack|стеллаж|shelving|metalus"),
    ("shelving", r"(?i)shelf|shelves|полк"),
    ("sofa", r"(?i)sofa|диван|couch|settee"),
    ("bench", r"(?i)bench|скамь|banquet"),
    ("armchair", r"(?i)armchair|кресл|swivel|lounge"),
    ("chair", r"(?i)chair|стул|stool|alcor_brown"),
    ("coffee_table", r"(?i)cocktail|coffee.?table|журнальн"),
    ("table", r"(?i)table|стол|desk"),
]
NAME = {"table": "Стол", "coffee_table": "Стол журнальный", "chair": "Стул", "armchair": "Кресло", "sofa": "Диван",
        "bench": "Скамья встроенная с мягкими элементами", "shelving": "Стеллаж", "bookshelf": "Полка книжная настенная",
        "records": "Полка для виниловых пластинок", "decor": "Декоративный элемент", "sign": "Вывеска световая",
        "chandelier": "Люстра подвесная", "sconce": "Бра настенное", "item": "Изделие"}
PLAN_KIND = {"table": "table", "coffee_table": "table", "chair": "chair", "armchair": "armchair", "sofa": "sofa",
             "bench": "sofa", "shelving": "cabinet", "bookshelf": "cabinet", "records": "cabinet", "decor": "cabinet",
             "item": "cabinet"}
MAT = {
    "marble": "натуральный мрамор (образец плиты — по согласованию), защитная пропитка от пятен",
    "stone": "натуральный камень по образцу, защитная пропитка",
    "wood": "МДФ / фанера в натуральном шпоне, покрытие — масло-воск",
    "metal": "металл, порошковая окраска, цвет — по визуализации",
    "fabric": "мебельная ткань по образцу дизайнера, наполнитель — ППУ",
    "leather": "натуральная / экокожа по образцу",
    "glass": "закалённое стекло",
    "mirror": "зеркало 4 мм на основании",
    "led": "светодиодная лента 24 В, 3000 K, в алюминиевом профиле с рассеивателем",
    "brick": "облицовка — плитка (клинкер) по образцу",
    "plastic": "пластик / композит по образцу",
    None: "по визуализации — образец согласовать с дизайнером",
}


def _txt(it):
    return " ".join([it.get("src", "")] + list(it.get("parts", [])) + list(it.get("mats", [])))


def classify(it, m):
    """-> kind"""
    if it.get("kind_hint"):
        return it["kind_hint"]
    t = _txt(it)
    W, D, H = (m.size if m is not None else it.get("size", [0, 0, 0]))
    if m is not None:
        fams = [p.fam for p in m.parts if not p.prop]
        soft = [p for p in m.parts if not p.prop and p.fam in ("fabric", "leather")]
        hard_low = [p for p in m.parts if not p.prop and p.fam not in ("fabric", "leather")
                    and float(p.v[:, 2].max()) <= 470 and float(p.v[:, 0].max() - p.v[:, 0].min()) >= 0.6 * W]
        if soft and hard_low and W >= 1200:
            return "bench"
        sq = []
        for p in m.parts:                     # vinyl sleeves: thin squares ~310 mm standing on the shelves
            if p.prop:
                continue
            dx, dy, dz = (float(np.ptp(p.v[:, i])) for i in range(3))
            if min(dx, dy) <= 110 and abs(max(dx, dy) - 315) < 45 and abs(dz - 315) < 45:
                sq.append(p)
        if len(sq) >= 6 and H >= 900:
            return "records"
    hits = [kind for kind, rx in RX if re.search(rx, t)]
    if "table" in hits and "chair" in hits and m is not None:     # «Table_Chairs_010»: the geometry decides
        top = sum(a for z, a in m._faces_dir(2, 1) if z > 0.9 * H)
        hits = ["table"] if top > 0.35 * W * D else ["chair"]
    for kind in hits:
        if kind == "table" and H < 560:
            return "coffee_table"
        return kind
    if W >= 1500 and 550 <= H <= 1000 and D >= 550:
        return "sofa"
    if H >= 1000 and D <= 700:
        return "shelving"
    if 650 <= H <= 820 and W >= 500:
        return "table"
    if H < 560 and W >= 500:
        return "coffee_table"
    if 650 <= H <= 1000 and W < 700:
        return "chair"
    return "item"


def _round(it, m):
    try:
        return m is not None and m.round_top()
    except Exception:
        return False


def _brand(it):
    """'Eichholtz_Chandelier-Tissot_S_' -> 'Eichholtz Tissot S' (the catalogue piece the designer put in the model)"""
    s = re.sub(r"[_\-]+", " ", str(it.get("src") or ""))
    s = re.sub(r"(?i)\b(chandelier|sconce|lamp|light|pendant|group|object|mesh)\b", " ", s)
    s = re.sub(r"\s*\d+\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return "" if len(s) < 3 or re.fullmatch(r"[\d\s]+", s) else s


def name_of(kind, it, m, P=None):
    W, D, H = [round(x) for x in (m.size if m is not None else it["size"])]
    if kind in LIGHT_KINDS:
        b = _brand(it)
        return "%s%s Ø%d" % (NAME[kind], (" " + b) if b else "", round(max(W, D) / 10.0) * 10) if kind == "chandelier" else \
            "%s%s" % (NAME[kind], (" " + b) if b else "")
    if kind in ("table", "coffee_table"):
        base = NAME[kind]
        if _round(it, m):
            return "%s круглый Ø%d" % (base, round(W / 10.0) * 10)
        return "%s %d×%d" % (base, round(W / 10.0) * 10, round(D / 10.0) * 10)
    if kind == "shelving":
        metal = m is not None and any(p.fam == "metal" for p in m.parts if not p.prop) and not any(
            p.fam == "wood" for p in m.parts if not p.prop)
        return "Стеллаж металлический" if metal else "Стеллаж"
    if kind == "bookshelf" and m is not None and any("led" == items3d.family(x) for p in m.parts for x in p.mats):
        return "Полка книжная настенная с подсветкой"
    if kind == "sofa":
        return "Диван %d×%d" % (round(W / 10.0) * 10, round(D / 10.0) * 10)
    return NAME.get(kind, "Изделие")


def elements(kind, m):
    """[(element, family, part index)] - what the workshop makes it from."""
    out = []
    if m is None:
        return out
    body = [(i, p) for i, p in enumerate(m.parts) if not p.prop]
    if not body:
        return out
    H = m.size[2]
    if kind in LIGHT_KINDS:
        main = max(body, key=lambda ip: len(ip[1].f))
        out.append(("Корпус / обод и бахрома" if kind == "chandelier" else "Корпус и плафон", "metal", main[0]))
        out.append(("Источник света", "led", main[0]))
        if kind == "chandelier":
            out.append(("Подвес к потолку (штанга / цепь, чашка)", "metal", main[0]))
        return out
    if kind in ("table", "coffee_table"):
        top = max(body, key=lambda ip: (float(ip[1].v[:, 2].max()), float(np.ptp(ip[1].v[:, 0]) * np.ptp(ip[1].v[:, 1]))))
        thin = float(np.ptp(top[1].v[:, 2])) < 0.35 * H
        if thin and len(body) > 1:
            out.append(("Столешница", top[1].fam, top[0]))
            rest = [ip for ip in body if ip[0] != top[0]]
            out.append(("Опора (подстолье)", rest[0][1].fam, rest[0][0]))
        else:
            out.append(("Столешница и опора", top[1].fam, top[0]))
    elif kind in ("chair", "armchair", "sofa"):
        fams = {}
        for i, p in body:
            fams.setdefault(p.fam, []).append(i)
        for fam, idx in fams.items():
            if fam in ("fabric", "leather"):
                out.append(("Обивка", fam, idx[0]))
            elif fam == "metal":
                out.append(("Каркас / опоры", fam, idx[0]))
            elif fam == "wood":
                out.append(("Каркас / ножки", fam, idx[0]))
            elif fam is None:
                big = max(idx, key=lambda i: len(m.parts[i].f))
                out.append(("Обивка" if not out else "Опоры", "fabric" if not out else None, big))
            else:
                out.append(("Отделка", fam, idx[0]))
    elif kind == "bench":
        low = [ip for ip in body if ip[1].fam not in ("fabric", "leather") and float(ip[1].v[:, 2].max()) <= 470]
        soft = [ip for ip in body if ip[1].fam in ("fabric", "leather")]
        other = [ip for ip in body if ip not in low and ip not in soft]
        if low:
            out.append(("Основание", low[0][1].fam or "brick", low[0][0]))
        if soft:
            out.append(("Матрасы сиденья", soft[0][1].fam, soft[0][0]))
        if other:
            out.append(("Подушка спинки", other[0][1].fam or "fabric", other[0][0]))
    else:
        main = max(body, key=lambda ip: float(np.ptp(ip[1].v[:, 0]) * np.ptp(ip[1].v[:, 2])))
        fam = main[1].fam
        out.append(("Каркас и полки" if fam == "metal" else "Корпус и полки", fam if fam else "wood", main[0]))
        seen = {fam}
        for i, p in body:
            for x in p.mats + [p.name]:
                f2 = items3d.family(x)
                if f2 in ("led", "fabric", "mirror", "glass", "metal") and f2 not in seen:
                    seen.add(f2)
                    out.append(({"led": "Подсветка полок", "fabric": "Задняя стенка", "mirror": "Зеркало",
                                 "glass": "Стекло", "metal": "Металлические элементы"}[f2], f2, i))
    return out


def notes_for(kind, it, extra=()):
    n = []
    if kind in ("chair", "armchair", "sofa", "bench"):
        n.append("Мебель для сидения — по ГОСТ 19917-2014; ткань для общественного интерьера: износостойкость не менее "
                 "40 000 циклов по Мартиндейлу, пропитка от пятен, чехлы / матрасы — съёмные.")
    if kind in ("table", "coffee_table"):
        n.append("Столешница — с защитной пропиткой от пятен (кофе, масло), кромка скруглена r = 2–3 мм; опора — с "
                 "регулируемыми подпятниками, устойчивость проверить при нагрузке на край.")
    if kind in ("shelving", "bookshelf", "records"):
        n.append("Крепление к стене — скрытое, анкерами по материалу стены (уточнить по месту); полки рассчитать на "
                 "нагрузку от книг / пластинок без прогиба.")
    if kind == "bench":
        n.append("Основание — встроенное, по месту; облицовка — по образцу; матрасы — секциями, стыки над швами основания.")
    if kind == "chandelier":
        z = it.get("z0")
        n.append("Низ люстры — на отметке %s от чистого пола (по модели); длина подвеса регулируется по месту." % (
            ("+%.3f" % (z / 1000.0)).replace(".", ",") if z else "по модели"))
        n.append("Крепление — к закладной / анкеру в плите перекрытия, рассчитанному не менее чем на 5-кратную массу "
                 "светильника; распределительная коробка — над чашкой подвеса.")
        n.append("Питание — линия освещения зала по плану; лампы LED 2700-3000 K, тип цоколя и мощность — по паспорту изделия.")
    if kind == "sconce":
        n.append("Высота установки и привязки — по развёртке стены и плану освещения; вывод кабеля в стене до чистовой отделки.")
    if kind in LIGHT_KINDS and _brand(it):
        n.append("Изделие серийное (%s) — заказ по артикулу производителя; аналог — того же размера и высоты подвеса." % _brand(it))
    n += list(extra)
    n.append("Размеры — по 3D-модели дизайн-проекта; для встроенных изделий — контрольный замер по месту до изготовления.")
    n.append("Материалы, цвет и фактура — по образцам, согласованным с дизайнером; деталировочные чертежи выполняет "
             "изготовитель (ГОСТ 16371-2014) и согласует с дизайнером до запуска в производство.")
    return n


def _columns_inside(P, it):
    """Square bearing columns standing inside the footprint of the item (a shelving built around them) ->
    [[x0, y0, x1, y1]] in the item's own axes (front view: x right, y away from the viewer)."""
    from shapely.geometry import box as sbox
    out = []
    W, D = it["size"][0], it["size"][1]
    for x, y, ang in it.get("places", [])[:1]:
        a = math.radians(ang)
        hw = abs(W / 2 * math.cos(a)) + abs(D / 2 * math.sin(a))
        hd = abs(W / 2 * math.sin(a)) + abs(D / 2 * math.cos(a))
        b = sbox(x - hw, y - hd, x + hw, y + hd)
        for w in P.walls:
            r = w.get("rect")
            if not r:
                continue
            cw, ch = r[2] - r[0], r[3] - r[1]
            if 200 <= cw <= 700 and 200 <= ch <= 700 and abs(cw - ch) < 120 and b.intersection(sbox(*r)).area > 0.5 * cw * ch:
                pts = []
                for px, py in ((r[0], r[1]), (r[2], r[3])):
                    dx, dy = px - x, py - y
                    pts.append((dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)))
                out.append([round(min(p[0] for p in pts)), round(min(p[1] for p in pts)),
                            round(max(p[0] for p in pts)), round(max(p[1] for p in pts))])
    return out


def local_footprint(m, px=15.0):
    """Plan outline of the item in its own axes: the silhouette of the mesh seen from above (rasterised at 15 mm,
    traced) - an L-shaped sofa stays an L, a round top stays round, the concave side of a curved banquette is free."""
    from PIL import Image, ImageDraw
    from shapely.geometry import Polygon
    W, D = m.size[0], m.size[1]
    T, _, _ = m.tris(props=False, colour=False)
    if not len(T):
        return None
    nx, ny = int(W / px) + 6, int(D / px) + 6
    im = Image.new("L", (nx, ny), 0)
    dr = ImageDraw.Draw(im)
    X = (T[:, :, 0] + W / 2.0) / px + 3
    Y = (T[:, :, 1] + D / 2.0) / px + 3
    for xs, ys in zip(X, Y):
        dr.polygon([(xs[0], ys[0]), (xs[1], ys[1]), (xs[2], ys[2])], fill=255)
    a = np.asarray(im) > 0
    try:
        import contourpy
        lines = contourpy.contour_generator(z=a.astype(float)).lines(0.5)
    except Exception:
        lines = []
    polys = []
    for ln in lines:
        if len(ln) >= 4:
            g = Polygon([((x - 3) * px - W / 2.0, (y - 3) * px - D / 2.0) for x, y in ln]).buffer(0)
            if not g.is_empty:
                polys.append(g)
    if not polys:
        return None
    g = max(polys, key=lambda q: q.area)
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda q: q.area)
    g = g.simplify(12)
    return [[round(x), round(y)] for x, y in list(g.exterior.coords)[:-1]]


def footprint(it, place, m=None):
    from shapely.geometry import Point, Polygon
    from shapely import affinity
    W, D = it["size"][0], it["size"][1]
    x, y, ang = place
    if it.get("foot") and len(it["foot"]) >= 3:
        g = affinity.rotate(Polygon(it["foot"]), ang, origin=(0, 0))
        return affinity.translate(g, x, y).buffer(0)
    if m is not None and _round(it, m):
        return Point(x, y).buffer(W / 2.0, 16)
    g = Polygon([(-W / 2, -D / 2), (W / 2, -D / 2), (W / 2, D / 2), (-W / 2, D / 2)])
    g = affinity.rotate(g, ang, origin=(0, 0))
    return affinity.translate(g, x, y)


WALL_BACKED = ("sofa", "bench", "shelving", "bookshelf", "records")


def _settle(it, P):
    """Where a piece really stands (lesson L-089): within 15° of a wall direction it is parallel to the walls (the
    angle of a cage bent by unevaluated modifiers is noise, designers do not put a sofa at 13°); a sofa, bench or
    shelving stands with its back against the wall it is at (gap or overlap up to 800 / 300 mm closed)."""
    from shapely.geometry import Polygon
    from shapely import affinity
    W, D = it["size"][0], it["size"][1]
    out = []
    for place in it.get("places", []):
        x, y, ang = place[0], place[1], (place[2] if len(place) > 2 else 0)
        near = round(ang / 90.0) * 90.0
        dev = (ang - near + 180.0) % 360.0 - 180.0
        if 0 < abs(dev) <= 15.0 and it.get("kind") not in ("chair", "armchair"):
            ang = int(near) % 360
        if it.get("kind") in WALL_BACKED and P.mass is not None and not P.mass.is_empty:
            a = math.radians(ang)
            bx, by = -math.sin(a), math.cos(a)                       # local +y (the back) in the world
            base = Polygon(it["foot"]) if it.get("foot") and len(it["foot"]) >= 3 else \
                Polygon([(-W / 2, -D / 2), (W / 2, -D / 2), (W / 2, D / 2), (-W / 2, D / 2)])
            g0 = affinity.translate(affinity.rotate(base, ang, origin=(0, 0)), x, y)

            def free(s):
                return affinity.translate(g0, bx * s, by * s).intersection(P.mass).area < 2000.0
            if it.get("columns") or g0.intersection(P.mass).area > 0.03 * g0.area:
                out.append([round(x), round(y), ang] + list(place[3:]))
                continue                              # built around a column / into the wall: it stays where it is
            best = None
            for s_ in range(-300, 805, 5):
                if free(s_) and not free(s_ + 5):
                    if best is None or abs(s_) < abs(best):
                        best = s_
            if best is not None and best != 0 and free(best):
                x, y = x + bx * best, y + by * best
        out.append([round(x), round(y), ang] + list(place[3:]))
    it["places"] = out
    return it


def _simple(g):
    """A polygon with holes (a shelving around a column) -> one simple ring cut by a thin slot to the outside."""
    from shapely.geometry import LineString, Polygon, box
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda q: q.area)
    for hole in list(g.interiors):
        h = Polygon(hole)
        c = h.centroid
        ext = g.exterior
        p = ext.interpolate(ext.project(c))
        slot = LineString([(c.x, c.y), (p.x, p.y)]).buffer(3, cap_style=2)
        g = g.difference(slot)
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda q: q.area)
    return g


def decide(d, base):
    from . import model as M
    log = []
    items = d.get("items") or []
    if not items:
        return log
    P = M.Project(d, base)
    order = {r["name"]: (int(r["num"]) if str(r.get("num", "")).isdigit() else 99) for r in P.rooms}
    made = []
    for it in items:
        auto = it.get("auto", True)
        m = None
        try:
            m = items3d.load(P, it)
        except Exception:
            m = None
        if m is not None and not it.get("size_user"):
            it["size"] = [round(x) for x in m.size]
        if m is not None:
            it["foot"] = local_footprint(m)
        rooms = []
        for x, y, *_ in it.get("places", []):
            r = P.room_of_point((x, y), 300)
            if r and r["name"] not in rooms:
                rooms.append(r["name"])
        it["rooms"] = rooms
        if not auto:
            made.append(it)
            continue
        kind = it.get("kind") if it.get("kind_user") else classify(it, m)
        it["kind"] = kind
        it["name"] = name_of(kind, it, m, P)
        els = elements(kind, m)
        it["elements"] = [dict(name=e, material=MAT.get(f, MAT[None]), fam=f, part=pi) for e, f, pi in els]
        if kind in LIGHT_KINDS:                   # a catalogue fixture: its finishes from the model's material names
            fin = [x for x in it.get("mats", []) if re.search(r"(?i)gold|brass|bronze|chrom|nickel|black|white|copper|латун|хром", x)]
            mt = {"gold": "латунь / золото", "brass": "латунь", "bronze": "бронза", "chrom": "хром", "nickel": "никель",
                  "black": "чёрный металл", "white": "белый", "copper": "медь"}
            words = []
            for x in fin:
                for key_, ru in mt.items():
                    if key_ in x.lower() and ru not in words:
                        words.append(ru)
            fin_txt = ", ".join(words) or "по каталогу производителя"
            for e in it["elements"]:
                if e["name"].startswith("Корпус"):
                    e["material"] = "металл, отделка: %s (по модели и каталогу)" % fin_txt
                elif e["name"].startswith("Источник"):
                    e["material"] = "лампы LED 2700-3000 K, цоколь и мощность — по паспорту изделия"
                    e["fam"] = None
                elif e["name"].startswith("Подвес"):
                    e["material"] = "цепь / штанга и потолочная чашка, отделка: %s" % (words[-1] if words else "по каталогу")
        extra = []
        if kind not in LIGHT_KINDS and (kind == "bookshelf" or any(e["fam"] == "led" for e in it["elements"])):
            extra.append("Подсветка — включается с общей группой зала; блок питания — в доступном месте (за "
                         "съёмной панелью), выводы кабеля — по плану розеток.")
        cols_ = _columns_inside(P, it) if kind in ("shelving", "bookshelf", "item") else []
        ncol = len(cols_)
        it["columns"] = cols_
        if ncol:
            it["name"] = "Стеллаж вокруг колонны" if ncol == 1 else "Стеллаж вокруг колонн"
            extra.append("Стеллаж собирается вокруг существующей колонны (облицовка колонны сохраняется), зазор до "
                         "колонны 10 мм, крепление — к колонне и к полу, без нагрузки на облицовку.")
        it["notes"] = notes_for(kind, it, extra)
        made.append(it)
    made = apply_overrides(d, made, P)
    for it in made:                        # the designer's size / section: the plan outline follows it
        if it.get("profile") or it.get("size_user"):
            try:
                mm = items3d.load(P, it)
            except Exception:
                mm = None
            if mm is not None:
                it["foot"] = local_footprint(mm)
    for it in made:
        if it.get("places") and it.get("kind") not in LIGHT_KINDS:
            _settle(it, P)
    # positions: by room, then by type
    made.sort(key=lambda it: (min([order.get(r, 99) for r in it.get("rooms") or []] or [99]),
                              KIND_ORDER.index(it.get("kind")) if it.get("kind") in KIND_ORDER else 99,
                              -it["size"][0]))
    for i, it in enumerate(made):
        it["pos"] = "М-%d" % (i + 1)         # marks follow the order (room, type) every run
    d["items"] = made
    _to_plan(d, P)
    n = sum(it.get("qty", 1) for it in made)
    log.append(dict(topic="Мебель", msg="изделия индивидуального изготовления: %d позиций, %d шт. — эскизы с видами, "
                    "размерами и материалами по 3D-модели" % (len(made), n),
                    why="мебель для кафе изготавливается по эскизам дизайнера; позиции сверены с планом мебели"))
    return log


def apply_overrides(d, made, P):
    """The designer's data (d["item_overrides"]) wins over the agent's guesses: [{"match": regex on the scene names
    of the item | "add": true, "set": {name, kind, qty, size, elements [[element, material]], notes, shape...},
    "skip": true (a bought piece: no sketch)}]. A size given by the designer stretches the model to it."""
    ovs = d.get("item_overrides") or []
    out = list(made)
    for ov in ovs:
        st = dict(ov.get("set") or {})
        if "elements" in st:
            els = []
            for e in st["elements"]:
                if isinstance(e, dict):
                    els.append(e)
                else:
                    els.append(dict(name=e[0], material=e[1], fam=items3d.family(e[1]), part=e[2] if len(e) > 2 else None))
            st["elements"] = els
        if ov.get("add"):
            iid = ov.get("id") or "a_" + re.sub(r"\W+", "_", st.get("name", ""))[:30]
            old = [x for x in out if x.get("id") == iid]
            for x in old:                          # added by an earlier run: made again from the designer's data
                out.remove(x)
            it = dict(id=iid, qty=1, places=[], rooms=[], auto=False, src="дизайнер")
            if old and old[0].get("pos"):
                it["pos"] = old[0]["pos"]
            it.update(st)
            if it.get("room") and not it.get("rooms"):
                it["rooms"] = [it["room"]]
            it.setdefault("notes", notes_for(it.get("kind", "item"), it))
            out.append(it)
            continue
        rx = re.compile(ov.get("match", "^$"))
        for it in out:
            if not rx.search(_txt(it)):
                continue
            if ov.get("skip"):
                it["skip"] = True
                continue
            if "size" in st:
                it["size_user"] = True
            if "elements" in st:
                old = it.get("elements") or []
                for i, e in enumerate(st["elements"]):     # the callout keeps pointing at the part of the model
                    if e.get("part") is None and i < len(old):
                        e["part"] = old[i].get("part")
            if "notes" in st and isinstance(st["notes"], dict):
                add = st.pop("notes").get("add", [])
                it["notes"] = list(add) + [n for n in it.get("notes", []) if n not in add]
            it.update(st)
            it["auto_fields"] = sorted(st)
    # bought pieces (no sketch) keep their models for the 3D view of the album
    bought = {it["id"]: {k: v for k, v in it.items() if k in ("id", "src", "size", "z0", "places", "mesh", "foot")}
              for it in out if it.get("skip") and it.get("mesh")}
    for it in d.get("_items_bought") or []:        # a re-run on the working copy: the skipped pieces are gone from
        bought.setdefault(it["id"], it)            # the items, their models stay for the 3D view
    d["_items_bought"] = list(bought.values())
    return [it for it in out if not it.get("skip")]


def _to_plan(d, P):
    """Pieces the plan of furniture does not show yet are added there with their position mark (the pieces added by
    an earlier run are made again: positions and names may have changed)."""
    from shapely.geometry import Polygon
    furn = [f for f in d.get("furniture", []) if f.get("source") != "items"]
    for f in furn:
        f.pop("item", None)
    d["furniture"] = furn
    polys = []
    for f in furn:
        try:
            polys.append(Polygon(f["poly"]).buffer(0))
        except Exception:
            polys.append(None)
    for it in d.get("items", []):
        if it.get("kind") in LIGHT_KINDS:
            continue                                     # hangs from the ceiling / on a wall: the lighting plan has it
        m = None
        for place in it.get("places", []):
            try:
                g = footprint(it, place, m if m is not None else _mesh_for_round(P, it))
            except Exception:
                continue
            hit = None
            for f, pg in zip(furn, polys):              # the same piece: they cover each other and are alike in size
                if pg is None or f.get("source") == "items" and f.get("item") != it.get("pos"):
                    continue
                ov = pg.intersection(g).area
                if (ov > 0.5 * min(pg.area, g.area) and min(pg.area, g.area) > 0.33 * max(pg.area, g.area)) \
                        or ov > 0.8 * g.area:          # or the plan shows it inside a group (table + chairs)
                    hit = f
                    break
            if hit is not None:
                hit["item"] = it["pos"]
                if re.match(r"^(Стол|Стул|Кресло|Диван|Стеллаж|Тумба|Полка)\b(?!.*груп)", hit.get("name", "")) \
                        or hit.get("source") == "items":
                    hit["name"] = it["name"]          # the sketch names it better than the plan import
                continue
            r = P.room_of_point((place[0], place[1]), 300)
            if r is None:
                continue
            gg = g.intersection(r["shp"]).difference(P.mass).buffer(0)
            for pg in polys:                         # a thin strip over a neighbour is a modelling tolerance
                if pg is None:
                    continue
                ov = gg.intersection(pg)
                if 0 < ov.area < 0.25e6 and _thin(ov) <= 150:
                    gg = gg.difference(pg.buffer(1)).buffer(0)
            if gg.is_empty or gg.area < 0.04e6:
                continue
            gg = _simple(gg.simplify(5))
            pts = [[5 * round(x / 5.0), 5 * round(y / 5.0)] for x, y in list(gg.exterior.coords)[:-1]]
            if len(pts) < 3:
                continue
            f = dict(name=it["name"], kind=PLAN_KIND.get(it.get("kind"), "cabinet"), poly=pts, h=it["size"][2],
                     room=r["name"], source="items", item=it["pos"], check=True)
            if it.get("z0", 0) > 150:                  # wall-mounted: hangs above the floor
                f["z"] = [it["z0"], it["z0"] + it["size"][2]]
            furn.append(f)
            polys.append(Polygon(pts).buffer(0))


def _thin(g):
    """Width of a strip: the short side of its minimum rectangle."""
    r = g.minimum_rotated_rectangle
    cs = list(r.exterior.coords) if r.geom_type == "Polygon" else []
    if len(cs) < 4:
        return 0.0
    a = math.hypot(cs[1][0] - cs[0][0], cs[1][1] - cs[0][1])
    b = math.hypot(cs[2][0] - cs[1][0], cs[2][1] - cs[1][1])
    return min(a, b)


_ROUND = {}


def _mesh_for_round(P, it):
    key = it.get("mesh")
    if key not in _ROUND:
        try:
            _ROUND[key] = items3d.load(P, it)
        except Exception:
            _ROUND[key] = None
    return _ROUND[key]
