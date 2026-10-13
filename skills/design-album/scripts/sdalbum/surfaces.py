# -*- coding: utf-8 -*-
"""Senior decisions on floor coverings and boxes (короба) from the 3D-scene evidence and the norms.

Floors. The scene's base covering (the FloorGenerator floor of the whole plan) gives the material and the tile format
of every room it covers; the room's use adds what the norms need on top of the look: slip resistance R10 / R11 in
public rooms (R11 behind a bar, where water is spilt), waterproofing in wet rooms. Coverings lying over the base (a
strip of small tiles) are zones of their own with their outline, tile and layout origin. The tile format is taken
from the geometry (what the renders show); a different format in the material's name is reported for confirmation.

Boxes. What a solid standing at a wall is for is decided by where it stands and what is in front of it:
  * behind a wall-hung WC - the installation box; its top goes under the window sill when a window is behind it
    (a box over the sill would block the window), the cabin keeps its clear depth;
  * around a free-standing column - the column cladding;
  * a narrow full-height shaft at a wall - the box for risers / hidden pipes;
  * a bar counter - the counter frame built by the contractor (its cladding is on the counter's sheets).
Every wall-hung WC gets an installation box even when the model has none (depth 200, h 1100 or under the sill).
"""
import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from . import model as M
from . import topo as T

BOX_NAME = {"install": "Короб для инсталляции подвесного унитаза",
            "pipe": "Короб для стояков и скрытых труб",
            "column": "Облицовка колонны",
            "bar": "Каркас барной стойки",
            "seat": "Короб-основание дивана",
            "low": "Короб ГКЛВ"}
BOX_SHORT = {"install": "Короб инсталляции", "pipe": "Короб для труб", "column": "Облицовка колонны",
             "bar": "Каркас стойки бара", "seat": "Основание дивана", "low": "Короб"}
BOX_MAT = {"install": "ГКЛВ 2×12,5 по м/к ПН/ПС 50 (под плитку); рама инсталляции - к стене и полу",
           "pipe": "ГКЛВ 2×12,5 по м/к ПН/ПС 50; ревизионные люки 300×300 у ревизий и кранов",
           "column": "ГКЛ 2×12,5 по м/к ПН/ПС 50, углы - перфоуголок; отделка по развёртке",
           "bar": "Каркас - стальная труба 40×40, обшивка ЦСП 12 мм под облицовку плиткой (по эскизу стойки)",
           "seat": "Каркас - стальная профильная труба 40×40 и 40×20 (сварной, грунт-эмаль), обшивка ЦСП 12 мм; облицовка плиткой%s по фасаду и верху, торцы - плитка с запилом 45°",
           "low": "ГКЛВ 2×12,5 по м/к ПН/ПС 50"}
INSTALL_DEPTH = 200
INSTALL_H = 1100
INSTALL_MIN = 150                      # frame 120 + GKLV 2×12,5 + tile
CABIN_MIN = 1200                       # СП 44.13330: WC cabin 0,85 × 1,2 m (door opening outwards)


def D(log, topic, msg, why=""):
    log.append(dict(code="DECISION", topic=topic, msg=msg, why=why))


def decide(d, base_dir="."):
    log = []
    _boxes(d, base_dir, log)
    _floors(d, base_dir, log)
    _finishes(d, base_dir, log)
    return log


# ------------------------------------------------------------------ boxes
def _boxes(d, base_dir, log):
    d["walls"] = [w for w in d.get("walls", []) if not (w.get("kind") == "box" and w.get("source") in ("model", "proposed"))]
    for w in d["walls"]:                       # a wall narrowed by an earlier run keeps its source rect in "_rect0"
        if w.get("_rect0"):
            w["rect"] = w.pop("_rect0")
    P = M.Project(d, base_dir)
    if not P.rooms:
        return
    src = d.get("_box_src") or []
    ledges = d.get("_ledges") or []
    out = []
    used = set()
    # 1. installation boxes behind wall-hung WCs
    for f, g in T.furniture_shapes(P, ("wc",)):
        if not (f.get("hung") or "подвес" in (f.get("name") or "").lower()):
            continue
        room = next((r for r in P.rooms if r["shp"].buffer(30).contains(g.representative_point())), None)
        if room is None:
            continue
        back = T.back_side(P, g, room)
        if back is None:
            continue
        seg, n, q = back
        res = _install(d, P, f, g, room, seg, n, q, src, ledges, used)
        if res:
            out.append(res[0])
            D(log, "Короба", res[1], res[2])
            P = M.Project(dict(d, walls=d["walls"] + out), base_dir)
    # 2. column claddings, pipe shafts of the scene
    walls = {w["id"]: w for w in d["walls"]}
    for i, b in enumerate(src):
        if i in used or b.get("kind") not in ("column", "pipe"):
            continue
        rect = b["rect"]
        h = int(min(b["z1"] - b.get("z0", 0), P.ceiling if P.ceiling else b["z1"]))
        if b["kind"] == "column":
            col = next((w for w in walls.values() if w.get("rect") and _same(w["rect"], b["inner"], 30)), None)
            if col is None:
                continue
            a_, c_ = rect[2] - rect[0], rect[3] - rect[1]
            out.append(dict(id="", kind="box", box="column", rect=rect, h=h, z0=0, source="model", check=True,
                            name="%s %d×%d" % (BOX_NAME["column"], round(a_), round(c_)), material=BOX_MAT["column"],
                            inner=col["id"], note="колонна %s" % col["id"]))
        else:
            out.append(dict(id="", kind="box", box="pipe", rect=rect, h=h, z0=0, source="model", check=True,
                            name=BOX_NAME["pipe"], material=BOX_MAT["pipe"], note="по модели"))
        used.add(i)
    # 3. seating bases: a low tiled solid along a wall under a bench / sofa - a metal frame box built on site
    items = d.get("items") or []
    moved_items = []
    for i, b in enumerate(src):
        if i in used or b.get("kind") != "low":
            continue
        x0, y0, x1, y1 = b["rect"]
        hh = b["z1"] - b.get("z0", 0)
        if not (300 <= hh <= 650 and max(x1 - x0, y1 - y0) >= 1000):
            continue
        it = next((it for it in items if b["name"] in str(it.get("src") or "").split(" + ")
                   or b["name"] in (it.get("parts") or [])), None)
        if it is None and not b.get("clad"):
            continue
        lb = b.get("label") or next((x.get("label") for x in src if x.get("clad") and x.get("label")), "")
        tt = b.get("tile") or next((x.get("tile") for x in src if x.get("clad") and x.get("tile")), None)
        tl = lb or ""                               # the tile of the other claddings of the model (one tile family)
        if tt:
            tl = (tl + " " if tl else "") + "%d×%d" % tuple(tt)
        mark = (it or {}).get("pos")
        out.append(dict(id="", kind="box", box="seat", rect=b["rect"], h=int(round(hh / 10.0) * 10), z0=0, source="model",
                        check=True, name=BOX_NAME["seat"] + (" %s" % mark if mark else ""),
                        material=BOX_MAT["seat"] % ((" " + tl) if tl else ""),
                        note=("подушки - эскиз %s" % mark) if mark else "по модели",
                        item=mark))
        used.add(i)
        if it is not None:
            it["base_box"] = True
            if len(it.get("places") or []) == 1:      # the base is the anchor: the bench stands along its box
                x, y = it["places"][0][0], it["places"][0][1]
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                if (y1 - y0) >= (x1 - x0):
                    y = cy
                else:
                    x = cx
                if abs(x - it["places"][0][0]) + abs(y - it["places"][0][1]) > 20:
                    it["places"][0] = [round(x), round(y)] + list(it["places"][0][2:])
                    moved_items.append(it)
    # 4. bar counter frames
    for f in d.get("furniture", []):
        if f.get("kind") != "counter" or f.get("h", 1200) < 900 or not f.get("poly"):
            continue
        out.append(dict(id="", kind="box", box="bar", poly=[[round(x), round(y)] for x, y in f["poly"]], h=int(f.get("h", 1100)),
                        z0=0, source="model", check=True, name=BOX_NAME["bar"], material=BOX_MAT["bar"],
                        note="облицовка - по эскизу стойки"))
    if moved_items:                             # the plan of furniture follows
        from . import items as IT
        IT._to_plan(d, M.Project(d, base_dir))
    if not out:
        return
    order = {"install": 0, "pipe": 1, "column": 2, "seat": 3, "bar": 4, "low": 5}

    def key(b):
        c = (Polygon(b["poly"]) if b.get("poly") else box(*b["rect"])).centroid
        return order.get(b["box"], 9), -round(c.y / 500.0), c.x
    out.sort(key=key)
    for i, b in enumerate(out, 1):
        b["id"] = "К-%d" % i
    d["walls"] += out
    import re
    for b in out:                              # the sketch of the bench names its base: the box of the partitions plan
        if b.get("box") != "seat" or not b.get("item"):
            continue
        it = next((x for x in d.get("items", []) if x.get("pos") == b["item"]), None)
        for e in (it or {}).get("elements", []):
            if isinstance(e, dict) and re.search(r"(?i)основан|цокол|base|короб", e.get("name", "")):
                e["material"] = "короб %s по плану перегородок: %s" % (b["id"], b["material"][0].lower() + b["material"][1:])
                break
    kinds = {}
    for b in out:
        kinds[BOX_SHORT[b["box"]]] = kinds.get(BOX_SHORT[b["box"]], 0) + 1
    D(log, "Короба", "на плане перегородок %d шт.: %s" % (len(out), ", ".join("%s - %d" % kv for kv in kinds.items())),
      "из 3D-модели и по нормам для подвесных унитазов")


def _same(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _install(d, P, f, g, room, seg, n, q, src, ledges, used):
    """-> (box dict, decision msg, why) or None"""
    qx, qy = q
    near_pt = Point(qx, qy)
    span = _span(P, room, seg, n, g)            # along-wall extent of the box
    ev_top, rect, how = None, None, ""
    lg = next((x for x in ledges if box(*x["rect"]).distance(near_pt) < 250), None)
    lows = [(i, b) for i, b in enumerate(src) if b.get("kind") == "low" and box(*b["rect"]).distance(near_pt) < 250]
    if lg is not None:
        w = next((x for x in d["walls"] if x["id"] == lg["wall"]), None)
        rect = list(lg["rect"])
        if w is not None and w.get("rect") and not w.get("_rect0"):
            w["_rect0"] = list(w["rect"])          # the wall is the part above the window; the ledge is the box
            r0 = list(w["rect"])
            ax = 1 if (r0[2] - r0[0]) >= (r0[3] - r0[1]) else 0      # across the wall: y for a horizontal wall
            nr = list(r0)
            nr[ax], nr[ax + 2] = lg["wall_rect"][ax], lg["wall_rect"][ax + 2]
            w["rect"] = nr                         # along the wall it keeps its (snapped) ends: no gap at the corners
            rect[1 - ax], rect[3 - ax] = r0[1 - ax], r0[3 - ax]
            rect[ax] = max(rect[ax], min(nr[ax + 2], rect[ax + 2]))
        ev_top = lg["z1"]
        how = "по модели (выступ под окном %s)" % lg["name"]
    if lows:
        tops = [b["z1"] for _, b in lows]
        ev_top = max([ev_top or 0] + tops)
        if rect is None:
            rr = [b["rect"] for _, b in lows]
            rect = [min(r[0] for r in rr), min(r[1] for r in rr), max(r[2] for r in rr), max(r[3] for r in rr)]
            how = "по модели (%s)" % ", ".join(b["name"] for _, b in lows[:2])
        for i, _ in lows:
            used.add(i)
    moved = False
    if rect is None:                            # not in the model: the norm box in front of the wall, the WC moves out
        dep = INSTALL_DEPTH
        a, b = span
        if abs(n[0]) > 0.5:
            x = seg.coords[0][0]
            rect = [min(x, x + n[0] * dep), a, max(x, x + n[0] * dep), b]
        else:
            y = seg.coords[0][1]
            rect = [a, min(y, y + n[1] * dep), b, max(y, y + n[1] * dep)]
        if box(*rect).intersection(g).area > 1:
            f["poly"] = [[round(x + n[0] * dep), round(y + n[1] * dep)] for x, y in f["poly"]]
            moved = True
        ev_top = INSTALL_H
        how = "по нормам (в модели короба нет)"
    rect = [round(v) for v in rect]
    h = int(ev_top or INSTALL_H)
    # a window behind the box: the box top goes under the sill
    face = LineString(seg.coords).buffer(400)
    sills = [o.get("sill", 0) for o in P.openings if o["kind"] == "window" and P.open_shape[o["id"]].intersects(face)
             and P.open_shape[o["id"]].intersects(box(*rect).buffer(300)) and o.get("sill", 0) > 300]
    why = []
    if sills:
        s = min(sills)
        if h > s - 5:
            why.append("верх короба опущен до низа окна (+%s): в модели %d мм - перекрывал окно" % (_lv(s), h)
                       if h > s + 30 else "верх короба - по низу окна (+%s)" % _lv(s))
            h = int(math.floor(s / 10.0) * 10)
        if h < 850:
            why.append("под окном меньше 850 мм - инсталляция не встаёт: окно заложить или унитаз напольный")
    dep = min(rect[2] - rect[0], rect[3] - rect[1])
    short = []
    if dep < INSTALL_MIN:                       # a frame needs ~120 + 2 GKLV + tile: the box grows into the room
        add = INSTALL_MIN - dep
        if abs(n[0]) > 0.5:
            rect = [rect[0], rect[1] + 0, rect[2] + add, rect[3]] if n[0] > 0 else [rect[0] - add, rect[1], rect[2], rect[3]]
        else:
            rect = [rect[0], rect[1], rect[2], rect[3] + add] if n[1] > 0 else [rect[0], rect[1] - add, rect[2], rect[3]]
        why.append("глубина короба увеличена до %d мм (в модели %d - рама инсталляции не помещается)" % (INSTALL_MIN, dep))
        if box(*rect).intersection(g).area > 1:
            f["poly"] = [[round(x + n[0] * add), round(y + n[1] * add)] for x, y in f["poly"]]
            why.append("унитаз смещён на %d мм" % add)
        dep = INSTALL_MIN
    clear = _clear_depth(room, rect, n)
    if clear is not None and clear < CABIN_MIN:
        why.append("свободная глубина кабины %d мм < %d (СП 44.13330) - проверить" % (clear, CABIN_MIN))
    if moved:
        why.append("унитаз отодвинут от стены на глубину короба")
    if sills and h <= min(sills):
        short.append("верх - по низу окна")
    short.append("рама h 820" if h < 1050 else "рама h 1120")
    b = dict(id="", kind="box", box="install", rect=rect, h=h, z0=0, source="model" if how.startswith("по модели") else "proposed",
             check=True, name=BOX_NAME["install"], material=BOX_MAT["install"], note=", ".join(short))
    msg = "короб инсталляции в «%s»: h=%d, глубина %d %s" % (room["name"], h, dep, how)
    return b, msg, "; ".join(why)


def _lv(z):
    return ("%.3f" % (z / 1000.0)).replace(".", ",")


def _span(P, room, seg, n, g):
    """Along-wall range of an installation box: the whole cabin wall if the cabin is narrow (<= 1300), else 800
    centred on the WC."""
    (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
    horiz = abs(n[1]) > 0.5
    lo, hi = (min(ax, bx), max(ax, bx)) if horiz else (min(ay, by), max(ay, by))
    x0, y0, x1, y1 = g.bounds
    c = (x0 + x1) / 2.0 if horiz else (y0 + y1) / 2.0
    if hi - lo <= 1300:
        return lo, hi
    return max(lo, c - 400), min(hi, c + 400)


def _clear_depth(room, rect, n):
    """Free depth of the room in front of the box (along n)."""
    c = box(*rect).centroid
    x0, y0, x1, y1 = rect
    sx = (x1 if n[0] > 0 else x0) if abs(n[0]) > 0.5 else c.x
    sy = (y1 if n[1] > 0 else y0) if abs(n[1]) > 0.5 else c.y
    ray = LineString([(sx + n[0] * 2, sy + n[1] * 2), (sx + n[0] * 8000, sy + n[1] * 8000)])
    inter = ray.intersection(room["shp"])
    if inter.is_empty:
        return None
    parts = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
    first = min(parts, key=lambda p: Point(sx, sy).distance(p))
    return int(round(first.length + 2))


# ------------------------------------------------------------------ floors
def _floors(d, base_dir, log):
    src = d.get("_floor_src") or []
    fl = d.get("floors") or []
    if not src or (fl and not all(f.get("proposed") or f.get("source") == "model" for f in fl)):
        return                                   # the user's floors stay as they are
    base = next((f for f in src if f.get("kind") == "base"), None)
    if base is None:
        return
    P = M.Project(dict(d, floors=[]), base_dir)
    if not P.rooms:
        return
    gb = unary_union([Polygon(p).buffer(0) for p in base["polys"]])
    public = d.get("meta", {}).get("building") == "public"
    groups = {}                                   # key -> rooms
    other = []
    for r in P.rooms:
        a = r["shp"].area
        if a <= 0:
            continue
        cls = r.get("cls", "living")
        if gb.intersection(r["shp"]).area >= 0.5 * a:
            key = "wet" if cls == "wet" else "bar" if cls == "bar" else "service" if cls in ("storage", "kitchen") else "main"
            groups.setdefault(key, []).append(r)
        else:
            other.append(r)
    mat = _mat_label(base)
    tile = _orient_tile(base.get("tile") or base.get("tile_name") or [600, 600], groups)
    out = []
    spec = [("main", "R10, матовый" if public else "", "Керамогранит 10 мм; плиточный клей; стяжка"),
            ("bar", "R11, противоскользящий" if public else "", "Керамогранит 10 мм; плиточный клей; обмазочная гидроизоляция; стяжка"),
            ("service", "R10" if public else "", "Керамогранит 10 мм; плиточный клей; стяжка"),
            ("wet", "R10" if public else "", "Керамогранит 10 мм; плиточный клей; обмазочная гидроизоляция с заведением на стены 200 мм; стяжка")]
    for key, cls_txt, layers in spec:
        rooms = groups.get(key)
        if not rooms:
            continue
        out.append(dict(id="П%d" % (len(out) + 1), material="%s %s%s" % (mat, "×".join(map(str, tile)), (", " + cls_txt) if cls_txt else ""),
                        pattern="tile", tile=tile, rooms=[r["name"] for r in rooms], layers=layers, reserve=0.1,
                        proposed=True, source="model"))
    for r in other:                               # not under the model's floor: by its use
        wet = r.get("cls") == "wet"
        out.append(dict(id="П%d" % (len(out) + 1), material="Керамогранит 600×600%s" % (", R10" if public else ""), pattern="tile",
                        tile=[600, 600], rooms=[r["name"]], reserve=0.1, proposed=True,
                        layers="Керамогранит 10 мм; плиточный клей; %sстяжка" % ("обмазочная гидроизоляция с заведением на стены 200 мм; " if wet else "")))
    zones = []
    for z in src:
        if z is base or z.get("kind") != "overlay":
            continue
        g = unary_union([Polygon(p).buffer(0) for p in z["polys"]])
        host = max(P.rooms, key=lambda r: r["shp"].intersection(g).area)
        if host["shp"].intersection(g).area < 0.2e6:
            continue
        wet = host.get("cls") in ("wet", "bar")
        t = z.get("tile") or z.get("tile_name") or [100, 100]
        out.append(dict(id="П%d" % (len(out) + 1), material=_mat_label(z, small=True) + " " + "×".join(map(str, t)), pattern="tile",
                        tile=t, polys=z["polys"], origin=z.get("origin"), reserve=0.15, proposed=True, source="model",
                        layers="Плитка 8-10 мм; плиточный клей; %sстяжка (уровень - заподлицо с основным покрытием)" % (
                            "обмазочная гидроизоляция; " if wet else ""),
                        zone="полоса / зона по модели в «%s»" % host["name"]))
        zones.append("%s - %s (%s м²)" % (out[-1]["id"], out[-1]["material"], ("%.1f" % z["area"]).replace(".", ",")))
    d["floors"] = out
    notes = d.setdefault("notes", {})
    fn = notes.get("floors")
    if isinstance(fn, dict):                    # the norm proposal's note does not describe the model's floors
        fn["add"] = [x for x in fn.get("add", []) if "проектное предложение" not in x]
    else:
        fn = {"add": []}
    txt = "Покрытия, форматы и зоны - по 3D-модели дизайн-проекта; класс скольжения и гидроизоляция - по назначению помещений."
    if txt not in fn["add"]:
        fn["add"].insert(0, txt)
    notes["floors"] = fn
    D(log, "Полы", "покрытия по 3D-модели: %s %s%s" % (mat, "×".join(map(str, tile)), ("; зоны: " + "; ".join(zones)) if zones else ""),
      "материал и формат - из модели (FloorGenerator); класс скольжения и гидроизоляция - по назначению помещений")
    tn = base.get("tile_name")
    if tn and base.get("tile") and sorted(tn) != sorted(base["tile"]):
        D(log, "Полы", "формат плитки: раскладка модели %s, в названии материала «%s» - %s; принят формат модели (так на визуализациях)" % (
            "×".join(map(str, base["tile"])), base.get("material"), "×".join(map(str, tn))), "подтвердить формат при заказе")
        for f in out:
            if f.get("source") == "model" and not f.get("polys"):
                f["note"] = "формат по раскладке модели; в названии материала %s - подтвердить при заказе" % "×".join(map(str, tn))


def _mat_label(z, small=False):
    from importers.scene_surfaces import generic_material
    t = z.get("tile") or z.get("tile_name") or [600, 600]
    kind = "Мозаика" if min(t) <= 50 else "Плитка керамическая" if min(t) <= 150 else "Керамогранит"
    name = z.get("material") or ""
    nm = name.split("_")[0].strip()
    import re
    nm = re.sub(r"\s*\d{2,4}\s*[xх×*]\s*\d{2,4}\s*", " ", nm).strip()
    if generic_material(name) or not nm:
        return kind
    return "%s «%s»" % (kind, nm)


def _orient_tile(t, groups):
    """Long side of a rectangular tile along the long side of the biggest room it covers: [step x, step y]."""
    a, b = max(t), min(t)
    if a == b:
        return [a, b]
    rooms = [r for rs in groups.values() for r in rs]
    if not rooms:
        return [a, b]
    r = max(rooms, key=lambda r: r["shp"].area)
    x0, y0, x1, y1 = r["shp"].bounds
    return [a, b] if (x1 - x0) >= (y1 - y0) else [b, a]


# ------------------------------------------------------------------ wall finishes
WALL_LABEL = {"plaster": "Декоративная штукатурка по модели (фактура «%s»)",
              "brick": "Кирпич «лофт» по модели (облицовочный кирпич / плитка под кирпич%s)",
              "concrete": "Бетон / микроцемент по модели%s",
              "wood": "Деревянные панели по модели%s",
              "tile": "Плитка по модели%s",
              "loft": "Фактурная отделка «лофт» по модели (материал - по образцу дизайнера%s)"}
WALL_RGB = {"plaster": [214, 196, 172], "brick": [176, 92, 70], "concrete": [170, 170, 170], "wood": [190, 150, 105],
            "tile": [150, 40, 50], "paint": [205, 205, 210], "loft": [120, 110, 100]}


import re


def _finishes(d, base_dir, log):
    """Wall finishes as the model has them (no tiled walls the designer did not draw): the material of the walls is
    the base finish, other materials of single walls (a brick wall) are their segments, the tile of the boxes and
    claddings is the tile type. Wet rooms keep the base finish with a moisture-proof coat unless the model tiles them."""
    wm = d.get("_wall_mats") or {}
    fin = d.get("finishes") or {}
    if not wm or (fin.get("types") and not all(t.get("proposed") or t.get("source") == "model" for t in fin["types"])):
        return
    P = M.Project(d, base_dir)
    if not P.rooms:
        return
    length = {}
    for w in P.walls:
        if w["kind"] != "existing" or w["id"] not in wm:
            continue
        x0, y0, x1, y1 = w["shape"].bounds
        kd = wm[w["id"]].get("kind") or "paint"
        length[kd] = length.get(kd, 0.0) + max(x1 - x0, y1 - y0)
    if not length:
        return
    base = max(length, key=length.get)
    if base == "paint":
        return                                         # nothing the model says: the norms (propose) decide
    mat = next((v.get("material") for v in wm.values() if v.get("kind") == base and v.get("material")
                and not re.match(r"(?i)material\s*#", v.get("material"))), "")
    if base == "plaster":
        desc = "Декоративная штукатурка по модели" + (" (фактура «%s»)" % mat if mat else "")
        if any(v.get("brick_mix") for v in wm.values()):
            desc += "; на части стен - кирпичная кладка «лофт» по визуализации"
    else:
        desc = WALL_LABEL.get(base, "%s") % ""
    types = [dict(id="О1", desc=desc, rgb=WALL_RGB.get(base, [205, 205, 210]), source="model", kind=base)]
    segs = []
    other = {}
    for w in P.walls:
        v = wm.get(w["id"])
        if w["kind"] != "existing" or not v or not v.get("kind") or v["kind"] in (base, "paint"):
            continue
        other.setdefault(v["kind"], []).append(w)
    for kd, ws in other.items():
        tid = "О%d" % (len(types) + 1)
        types.append(dict(id=tid, desc=WALL_LABEL.get(kd, "%s") % "", rgb=WALL_RGB.get(kd, [150, 150, 150]), source="model", kind=kd))
        for w in ws:
            for rm in P.rooms:
                ln = rm["shp"].boundary.intersection(w["shape"].buffer(5))
                for g in (ln.geoms if hasattr(ln, "geoms") else [ln]):
                    if g.geom_type == "LineString" and g.length >= 300:
                        cs = list(g.coords)
                        segs.append(dict(type=tid, a=[round(cs[0][0]), round(cs[0][1])], b=[round(cs[-1][0]), round(cs[-1][1])],
                                         source="model", h=int(rm.get("ceiling_level") or P.ceiling)))
    # the tile of the boxes / claddings of the model (bench base, columns, pipe boxes) - the installation boxes get it too
    clad = [b for b in d.get("_box_src") or [] if b.get("clad") or b.get("tile")]
    lbl = next((b.get("label") for b in clad if b.get("label")), "")
    tl = next((b.get("tile") for b in clad if b.get("tile")), None)
    tile_label = None
    if clad or any(w.get("box") == "install" for w in d.get("walls", [])):
        tile_label = "Плитка%s%s" % ((" " + lbl) if lbl else "", (" %d×%d" % tuple(tl)) if tl else "")
        types.append(dict(id="О%d" % (len(types) + 1), desc="%s - короба, облицовки колонн, основание дивана, стена инсталляции"
                          % tile_label, rgb=WALL_RGB["tile"], source="model", kind="tile", tile=tl or [100, 100]))
    base_label = types[0]["desc"].split(" по модели")[0].split(";")[0]
    d["finishes"] = dict(types=types, by_class={}, segments=segs, source="model", base_label=base_label,
                         tile_label=tile_label, tile=tl)
    notes = d.setdefault("notes", {})
    fn = notes.get("finishes")
    add = ["Отделка стен - по 3D-модели дизайн-проекта: %s%s." % (
        types[0]["desc"][0].lower() + types[0]["desc"][1:],
        "; " + "; ".join(t["desc"][0].lower() + t["desc"][1:] for t in types[1:]) if len(types) > 1 else "")]
    if any(r.get("cls") == "wet" for r in P.rooms):
        add.append("В санузлах та же отделка в влагостойком исполнении с защитным лаком (влажная уборка и дезинфекция); "
                   "плитка - на коробе инсталляции.")
    notes["finishes"] = {"add": add} if not isinstance(fn, list) else fn
    D(log, "Отделка стен", "по модели: %s" % "; ".join("%s - %s" % (t["id"], t["desc"]) for t in types),
      "плитку на стенах санузлов агент больше не назначает сам: в модели стены - %s" % base_label.lower())
