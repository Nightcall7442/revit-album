# -*- coding: utf-8 -*-
"""Senior architect's decisions: what a junior asks the client, a senior decides by norms and evidence of the source,
and writes down with the reason. The client confirms the album, not a list of questions.

    d2, log = decide(data, base_dir)

Runs after autofix (rooms exist) and before propose. Every decision is a log entry dict(code="DECISION", topic, msg,
why) - report.md «Решения агента» and the general notes of the album. Data the user gave is never overridden: only
draft / auto items (rooms with auto=true, empty sections, items from the source scene with check=true).

  zones        a counter splits an open space: the bar behind it is a room of its own (separation along the counter
               front, the staff passage closed to the nearest wall)
  purposes     rooms named by building type, contents and adjacency (cafe: dining hall / bar / WC / WC lobby /
               back room; flat: storeroom, corridor, room)
  ceilings     from the scene: sheets hanging below the slab = suspended ceiling at that level; lights on the slab, tracks
               on cables = open ceiling (painted slab, beams and services); beams shown on the ceiling plan
  lighting     the designer's fixtures of the scene: tracks, track spots, surface / recessed downlights, pendants
  entrance     public building: entrance door opens outward, clear width >= 0.8 m (<= 50 people) / 1.2 m (more)
  catering     public catering: coffee machine / POS from the scene, bar sink and hand-wash basin, water heater (no
               hot water source in the source data), staff room fittings
  overlaps     seats tucked under tables are not conflicts
"""
import copy
import math
import re

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from . import model as M
from . import topo as T

PUBLIC = re.compile(r"кафе|ресторан|\bбар|кофейн|столов|магазин|бутик|офис|салон|отел|гостиниц|клиник|банк|"
                    r"школ|детск|студи[ия] (?:йоги|танц)|фитнес|аптек", re.I)
CATERING = re.compile(r"кафе|ресторан|\bбар|кофейн|столов|фуд|пицц|пекарн|кондитер", re.I)
SEAT_KINDS = ("chair", "armchair", "sofa")


def D(log, topic, msg, why=""):
    log.append(dict(code="DECISION", topic=topic, msg=msg, why=why))


def is_public(d):
    m = d.get("meta", {})
    return bool(PUBLIC.search("%s %s" % (m.get("object", ""), m.get("title", ""))))


def is_catering(d):
    m = d.get("meta", {})
    return bool(CATERING.search("%s %s" % (m.get("object", ""), m.get("title", ""))))


def decide(data, base_dir="."):
    d = copy.deepcopy(data)
    log = []
    if not d.get("walls"):
        return d, log
    public = is_public(d)
    d.setdefault("meta", {})["building"] = "public" if public else "residential"
    if public:
        _counter_zones(d, base_dir, log)
    _purposes(d, base_dir, log, public)
    _ceilings_from_model(d, base_dir, log, public)
    _lights_from_model(d, base_dir, log)
    if public:
        _entrance(d, base_dir, log)
    _opening_types(d, base_dir, log, public)
    if is_catering(d):
        _catering(d, base_dir, log)
    _service_rooms(d, base_dir, log, public)
    if is_catering(d):
        _hot_water(d, base_dir, log)
    if d.get("items"):                       # furniture of the scene -> production sketches, the plan gets them
        from . import items as IT
        try:
            log += IT.decide(d, base_dir)
        except Exception as ex:              # the album is built without the sketches, the report says why
            log.append(dict(topic="Мебель", msg="эскизы мебели не собраны: %r" % (ex,)))
    _overlaps(d, base_dir, log)
    notes = d.setdefault("meta", {}).setdefault("decisions", [])
    for e in log:                            # the album gets the decision; the reason stays in report.md
        line = "%s: %s" % (e["topic"], e["msg"])
        if line not in notes:
            notes.append(line)
    return d, log


def _P(d, base_dir):
    return M.Project(d, base_dir)


def _poly_of(f):
    return Polygon(f["poly"]).buffer(0)


def _in_room(f, room):
    if f.get("room") == room["name"]:
        return True
    try:
        return room["shp"].buffer(30).contains(_poly_of(f).representative_point())
    except Exception:
        return False


def _rect(cx, cy, w, h):
    return [[cx - w / 2.0, cy - h / 2.0], [cx + w / 2.0, cy - h / 2.0], [cx + w / 2.0, cy + h / 2.0], [cx - w / 2.0, cy + h / 2.0]]


def _snap_poly(pts):
    return [[T.snap(x), T.snap(y)] for x, y in pts]


# ------------------------------------------------------------------ zones (bar behind a counter)
def _counter_zones(d, base_dir, log):
    """The space behind a bar counter is the bar - a room of its own (its floor, light, sockets, plumbing differ from
    the hall). The counter front is the boundary; its free end is closed by the shortest line to a wall (the staff
    passage). Only for auto rooms (the user's rooms are kept)."""
    if any(not r.get("auto") for r in d.get("rooms", [])):
        return
    P = _P(d, base_dir)
    mass = P.mass
    added = []
    for f in d.get("furniture", []):
        if f.get("kind") != "counter" or f.get("h", 1200) < 1000:
            continue
        g = _poly_of(f)
        room = P.room_of_point((g.representative_point().x, g.representative_point().y), 300)
        if room is None or room["area_exact"] < 25:
            continue
        # front = the panel faces of the counter (customer side) found by the importer; else the edges looking into
        # the open hall (an outward ray meets no wall within 2 m)
        front = [LineString(s_) for s_ in f.get("front", []) if LineString(s_).length >= 300]
        if not front:
            cs = list(g.exterior.coords)
            for a, b in zip(cs[:-1], cs[1:]):
                seg = LineString([a, b])
                if seg.length < 300:
                    continue
                mid = seg.interpolate(0.5, normalized=True)
                nx, ny = (b[1] - a[1]) / seg.length, -(b[0] - a[0]) / seg.length
                if g.contains(Point(mid.x + nx * 80, mid.y + ny * 80)):
                    nx, ny = -nx, -ny
                ray = LineString([(mid.x + nx * 20, mid.y + ny * 20), (mid.x + nx * 2000, mid.y + ny * 2000)])
                if not ray.intersects(mass) and room["shp"].buffer(5).contains(Point(mid.x + nx * 80, mid.y + ny * 80)):
                    front.append(seg)
        if not front:
            continue
        line = unary_union(front)
        from shapely.ops import linemerge
        line = linemerge(line) if line.geom_type == "MultiLineString" else line
        lines = list(line.geoms) if hasattr(line, "geoms") else [line]
        segs = []
        for ln in lines:
            pts = list(ln.coords)
            for end, nxt in ((pts[0], pts[1]), (pts[-1], pts[-2])):
                if mass.buffer(25).contains(Point(end)):
                    continue
                ux, uy = end[0] - nxt[0], end[1] - nxt[1]
                L = math.hypot(ux, uy) or 1.0
                ux, uy = ux / L, uy / L
                ray = LineString([end, (end[0] + ux * 1500, end[1] + uy * 1500)])
                hit = ray.intersection(mass)
                if hit.is_empty:
                    continue
                dist = min(Point(end).distance(h) for h in (hit.geoms if hasattr(hit, "geoms") else [hit]))
                q = (end[0] + ux * dist, end[1] + uy * dist)
                segs.append([[T.snap(end[0]), T.snap(end[1])], [T.snap(q[0]), T.snap(q[1])]])
            for a, b in zip(pts[:-1], pts[1:]):
                segs.append([[T.snap(a[0]), T.snap(a[1])], [T.snap(b[0]), T.snap(b[1])]])
        trial = copy.deepcopy(d)
        trial.setdefault("separations", [])
        trial["separations"] += segs
        trial["rooms"] = []
        from . import autofix
        lg = []
        autofix._auto_rooms(trial, base_dir, lg)
        if len(trial["rooms"]) <= len(d["rooms"]):
            continue                                        # the line does not close a zone: keep the open plan
        d["separations"] = trial["separations"]
        added.append(f.get("name", "стойка"))
    if added:
        d["rooms"] = []
        for f in d.get("furniture", []):
            if f.get("check") or f.get("proposed"):
                f.pop("room", None)
        from . import autofix
        autofix._auto_rooms(d, base_dir, [])
        D(log, "Зонирование", "зона за барной стойкой выделена в отдельное помещение «Бар» (граница - фасад стойки, проход "
                              "персонала закрыт условной линией до стены)",
          "у бара своё покрытие пола, свет, розетки оборудования и сантехника - в зале они другие")


# ------------------------------------------------------------------ purposes
def _contents(P, d, room):
    out = dict(seats=0, tables=0, wc=0, basin=0, sink=0, counter=0, fridge=0, bed=0, shower=0, bath=0, equip=0, items=0)
    shp = room["shp"].buffer(50)
    for f in d.get("furniture", []):
        try:
            g = _poly_of(f)
        except Exception:
            continue
        if not shp.contains(g.representative_point()):
            continue
        k = f.get("kind")
        out["items"] += 1
        if k in SEAT_KINDS:
            out["seats"] += 2 if k == "sofa" else 1
        elif k == "table":
            out["tables"] += 1
            if "групп" in f.get("name", "").lower():
                out["seats"] += 4
        elif k in out:
            out[k] += 1
    for e in d.get("_equipment", []):
        c = box(*e["rect"]).centroid
        if shp.contains(c) and e["kind"] in ("coffee", "pos", "grinder", "dishwasher", "ice"):
            out["equip"] += 1
    return out


def _neighbours(P, room):
    out = []
    for e in T.room_entrances(P, room):
        if e.get("other") is not None:
            out.append(e["other"]["name"])
    return out


def _purposes(d, base_dir, log, public):
    from . import editor
    P = _P(d, base_dir)
    auto = [r for r in d.get("rooms", []) if r.get("auto")]
    if not auto or not P.rooms:
        return
    info = {}
    for r in P.rooms:
        if r["name"] in [a["name"] for a in auto]:
            info[r["name"]] = (r, _contents(P, d, r))
    plan = {}                 # old name -> (new name, cls, why)
    if public:
        seats = sorted(((c["seats"] + c["tables"], n) for n, (r, c) in info.items()), reverse=True)
        hall = seats[0][1] if seats and seats[0][0] >= 4 else None
        if hall:
            r, c = info[hall]
            plan[hall] = ("Обеденный зал" if is_catering(d) else "Торговый зал" if re.search(r"магазин|бутик", d["meta"].get("object", ""), re.I)
                          else "Зал", "public", "%d посадочных мест, %d столов" % (c["seats"], c["tables"]))
        wcs = sorted([n for n, (r, c) in info.items() if c["wc"] and n not in plan], key=lambda n: (info[n][0]["shp"].centroid.x))
        for i, n in enumerate(wcs, 1):
            plan[n] = ("Санузел" if len(wcs) == 1 else "Санузел %d" % i, "wet", "унитаз")
        for n, (r, c) in info.items():
            if n in plan:
                continue
            nb = _neighbours(P, r)
            if (c["counter"] or c["equip"] or c["fridge"]) and c["seats"] == 0:
                plan[n] = ("Бар" if is_catering(d) else "Подсобное помещение", "bar" if is_catering(d) else "storage",
                           "стойка / оборудование бара за стойкой")
            elif c["basin"] and any(x in wcs for x in nb):
                plan[n] = ("Тамбур санузлов", "wet", "умывальник перед кабинами санузлов")
        for n, (r, c) in info.items():
            if n in plan:
                continue
            if c["seats"] == 0 and r["area_exact"] >= 4:
                plan[n] = ("Подсобное помещение", "storage",
                           "служебная зона без посадочных мест (склад, персонал, уборочный инвентарь)")
    else:
        for n, (r, c) in info.items():
            if not n.startswith("Помещение"):
                continue
            x0, y0, x1, y1 = r["shp"].bounds
            narrow = min(x1 - x0, y1 - y0)
            wins = T.room_openings(P, r, kinds=("window", "balcony"))
            if narrow < 1600 and max(x1 - x0, y1 - y0) >= 2.5 * narrow:
                plan[n] = ("Коридор", "circulation", "узкое проходное помещение")
            elif not wins and r["area_exact"] < 5:
                plan[n] = ("Кладовая", "storage", "без окна, %.1f м²" % r["area_exact"])
            elif wins:
                plan[n] = ("Комната", "living", "с окном, %.1f м²" % r["area_exact"])
    used = {r["name"] for r in d["rooms"] if r["name"] not in plan}
    msgs, final = [], []
    for old, (new, cls, why) in plan.items():
        name = new
        k = 2
        while name in used:
            name = "%s %d" % (new, k)
            k += 1
        used.add(name)
        tmp = "__tmp_%d" % len(msgs)
        editor.rename_room(d, old, tmp)
        final.append((tmp, name, cls, why))
        msgs.append("«%s» - %s" % (name, why))
    for tmp, name, cls, why in final:
        editor.rename_room(d, tmp, name)
        for r in d["rooms"]:
            if r["name"] == name:
                r["cls"] = cls
                r["purpose_why"] = why
    if msgs:
        D(log, "Назначение помещений", "; ".join(msgs), "по типу здания, оборудованию и смежности")


# ------------------------------------------------------------------ ceilings from the scene
def _ceilings_from_model(d, base_dir, log, public):
    if d.get("ceilings", {}).get("types"):
        return
    planes = d.get("_ceil_planes") or []
    lights = d.get("_lights") or []
    beams = d.get("_beams") or []
    if not (planes or lights or beams):
        return
    P = _P(d, base_dir)
    slab = P.slab
    per = {}
    for r in P.rooms:
        best = None
        for rect, z in planes:
            cov = box(*rect).intersection(r["shp"]).area / max(r["shp"].area, 1.0)
            if cov >= 0.6 and (best is None or cov > best[0]):
                best = (cov, z)
        if best:
            per[r["name"]] = ("susp", best[1])
            continue
        mine = [l for l in lights if r["shp"].buffer(50).contains(box(*l["rect"]).centroid)]
        on_slab = [l for l in mine if l["z1"] >= slab - 60]
        hung = [l for l in mine if l["kind"] == "line"]
        if on_slab or hung or any(r["shp"].intersects(box(*b)) for b, z in beams):
            per[r["name"]] = ("open", slab)
        else:
            per[r["name"]] = ("susp", d["levels"].get("ceiling", slab - 100))
    if not per:
        return
    lv = lambda z: ("+%.3f" % (z / 1000.0)).replace(".", ",")
    types, by = [], {}
    opens = [n for n, (k, z) in per.items() if k == "open"]
    if opens:
        types.append(dict(id="Т1", short="открытый потолок, окраска, низ плиты %s" % lv(slab), level=slab,
                          desc="Открытый потолок: ж/б плита, балки и инженерные сети окрашиваются (цвет - по дизайну, "
                               "в модели тёмный); воздуховоды и кабельные лотки - открытая прокладка", proposed=True))
        for n in opens:
            by[n] = ("Т1", slab)
    susp = sorted({z for n, (k, z) in per.items() if k == "susp"})
    for z in susp:
        names = [n for n, (k, zz) in per.items() if k == "susp" and zz == z]
        wet = all(P.room_by_name[n].get("cls") == "wet" for n in names)
        tid = "Т%d" % (len(types) + 1)
        types.append(dict(id=tid, short="подвесной потолок %s, %s" % ("ГКЛВ" if wet else "ГКЛ", lv(z)), level=z,
                          desc="%s 12,5 мм по металлокаркасу (ПП 60×27), шпатлёвка, %sокраска; люк ревизии у вентилятора" % (
                              "ГКЛВ" if wet else "ГКЛ", "влагостойкая " if wet else ""), proposed=True))
        for n in names:
            by[n] = (tid, z)
    for r in d["rooms"]:
        if r["name"] in by and not r.get("ceiling_type"):
            r["ceiling_type"], r["ceiling_level"] = by[r["name"]]
    zones = d.setdefault("ceilings", {}).setdefault("zones", [])
    nb = 0
    for rect, z in beams:
        g = box(*rect)
        for r in P.rooms:
            if by.get(r["name"], ("", 0))[0] != "Т1":
                continue
            part = g.intersection(r["shp"])
            if part.area < 0.05e6 or part.geom_type != "Polygon":
                continue
            zones.append(dict(type="Т1", kind="beam", name="Балка ж/б (по модели), низ %s" % lv(z),
                              poly=_snap_poly(list(part.simplify(2).exterior.coords)[:-1]), bottom=z, proposed=True))
            nb += 1
    d["ceilings"]["types"] = types
    main = max(P.rooms, key=lambda r: r["area_exact"])
    d["levels"]["ceiling"] = by.get(main["name"], ("", d["levels"]["ceiling"]))[1]
    parts = []
    if opens:
        parts.append("открытый (окраска плиты и сетей) в: %s" % ", ".join(opens))
    for z in susp:
        parts.append("подвесной %s в: %s" % (lv(z), ", ".join(n for n, (k, zz) in per.items() if k == "susp" and zz == z)))
    D(log, "Потолки", "; ".join(parts) + ("; балки каркаса (низ %s) показаны на плане потолка" % lv(beams[0][1]) if nb else ""),
      "по модели: светильники смонтированы на плите / подвесах, в санузлах - потолок на %s; запотолочное пространство "
      "%s мм достаточно для вытяжки" % (", ".join(lv(z) for z in susp) or "-", ", ".join(str(slab - z) for z in susp) or "-"))
    # curtains: a ceiling-mounted rail along each curtain run (open ceiling) / a niche (suspended)
    rails = 0
    for rect in d.get("_curtains") or []:
        x0, y0, x1, y1 = rect
        horiz = (x1 - x0) >= (y1 - y0)
        c = ((y0 + y1) / 2.0) if horiz else ((x0 + x1) / 2.0)
        pts = [[x0, c - 30], [x1, c - 30], [x1, c + 30], [x0, c + 30]] if horiz else [[c - 30, y0], [c + 30, y0], [c + 30, y1], [c - 30, y1]]
        r = P.room_of_point(((x0 + x1) / 2.0, (y0 + y1) / 2.0), 200)
        if r is None:
            continue
        zones.append(dict(type=by.get(r["name"], ("Т1", 0))[0], kind="rail", name="Карниз потолочный для штор",
                          poly=_snap_poly(pts), proposed=True))
        rails += 1
    if rails:
        D(log, "Шторы", "потолочные карнизы для штор: %d шт. по линиям штор модели (в т.ч. зонирующие в зале)" % rails,
          "при открытом потолке - карниз на закладных к плите, длина = длина шторы + 150 мм")


# ------------------------------------------------------------------ lighting from the scene
LIGHT_SPEC_MODEL = {
    "surface": "Светильник накладной цилиндр LED 10 Вт, 3000 K (по модели)",
    "pendant": "Светильник подвесной LED (по модели), подвес до низа по месту",
    "track": "Шинопровод однофазный, подвесной на тросах (низ по модели)",
    "track_spot": "Трековый спот LED 10-15 Вт, 3000 K, поворотный",
    "spot": "Светильник встраиваемый LED (по модели)",
    "spot_ip44": "Светильник встраиваемый LED IP44 (по модели)",
}


def _lights_from_model(d, base_dir, log):
    if d.get("lighting") or not d.get("_lights"):
        return
    P = _P(d, base_dir)
    ceil_of = {r["name"]: r.get("ceiling_level", P.ceiling) for r in d.get("rooms", [])}
    tracks, out, hidden = [], [], 0
    for l in d["_lights"]:
        if l["kind"] != "line":
            continue
        x0, y0, x1, y1 = l["rect"]
        c = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        r = P.room_of_point(c, 100)
        if r is None:
            continue
        if (x1 - x0) >= (y1 - y0):
            a, b = (T.snap(x0), T.snap(c[1])), (T.snap(x1), T.snap(c[1]))
        else:
            a, b = (T.snap(c[0]), T.snap(y0)), (T.snap(c[0]), T.snap(y1))
        if l["z0"] > ceil_of.get(r["name"], P.ceiling) + 20:
            hidden += 1
            continue
        line = LineString([a, b]).intersection(r["shp"].buffer(-150))
        if line.is_empty or line.length < 400:
            continue
        a, b = line.coords[0], line.coords[-1]
        tracks.append((LineString([a, b]), l["z0"], r["name"]))
        out.append(dict(kind="track", x=T.snap(a[0]), y=T.snap(a[1]), x2=T.snap(b[0]), y2=T.snap(b[1]), group=r["name"],
                        z=l["z0"], source="модель"))
    for l in d["_lights"]:
        if l["kind"] != "point":
            continue
        x0, y0, x1, y1 = l["rect"]
        p = Point((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        r = P.room_of_point((p.x, p.y), 100)
        if r is None:
            continue
        C = ceil_of.get(r["name"], P.ceiling)
        if l["z0"] >= C - 5:
            hidden += 1                                    # above the suspended ceiling: not seen, not built
            continue
        on = [(t, z) for t, z, rn in tracks if rn == r["name"] and t.distance(p) <= 120 and abs(l["z1"] - z) <= 260]
        if on:
            t, z = on[0]
            q = t.interpolate(t.project(p))
            kind, x, y = "track_spot", q.x, q.y
        else:
            x, y = p.x, p.y
            if l["z0"] < C - 5 and l["z1"] > C + 20:
                kind = "spot"                              # crosses the ceiling sheet: recessed
            elif C - l["z1"] <= 100 and C - l["z0"] <= 350:
                kind = "surface"                           # a short body fixed to the ceiling
            else:
                kind = "pendant"                           # hangs on a cord (the cord is not modelled)
            if kind == "spot" and r.get("cls") == "wet":
                kind = "spot_ip44"
        out.append(dict(kind=kind, x=T.snap(x), y=T.snap(y), group=r["name"], source="модель"))
    # duplicates (two parts of one lamp grouped differently): keep one
    seen, uniq = [], []
    for o in out:
        if o["kind"] not in ("track",) and any(o["kind"] == s["kind"] and math.hypot(o["x"] - s["x"], o["y"] - s["y"]) < 80 for s in seen):
            continue
        seen.append(o)
        uniq.append(o)
    # a fixture closer than 300 to a wall face (a downlight in a cubicle corner) is kept: it is the design
    for o in uniq:
        if o["kind"] != "track":
            o.pop("z", None)
    d["lighting"] = uniq
    spec = d.setdefault("lighting_spec", {})
    for o in uniq:
        if o["kind"] in LIGHT_SPEC_MODEL:
            spec.setdefault(o["kind"], LIGHT_SPEC_MODEL[o["kind"]])
    tz = sorted({t[1] for t in tracks})
    if tz:
        spec["track"] = "Шинопровод однофазный, подвесной на тросах, низ %s (по модели)" % ", ".join(
            ("+%.3f" % (z / 1000.0)).replace(".", ",") for z in tz)
    from collections import Counter
    cnt = Counter(o["kind"] for o in uniq)
    names = {"track": "шинопроводы", "track_spot": "трековые споты", "surface": "накладные", "pendant": "подвесы",
             "spot": "встраиваемые", "spot_ip44": "встраиваемые IP44"}
    D(log, "Освещение", "светильники перенесены из модели дизайнера: " + ", ".join("%s %d" % (names.get(k, k), v) for k, v in cnt.items())
      + ("; скрытые за подвесным потолком / вне плана не переносились (%d)" % hidden if hidden else ""),
      "свет - авторское решение дизайнера, норма освещённости обеспечивается количеством из модели")


# ------------------------------------------------------------------ entrance (evacuation)
def _entrance(d, base_dir, log):
    P = _P(d, base_dir)
    ents = [o for o in P.openings if o["kind"] == "door" and T.is_entrance(P, o)]
    if not ents:
        return
    seats = sum(_contents(P, d, r)["seats"] for r in P.rooms)
    staff = 3
    people = seats + staff
    need = 1200 if people > 50 else 800
    for o in ents:
        clear = o["w"] - 100
        why = "СП 1.13130: двери эвакуационных выходов открываются по направлению выхода; ширина в свету не менее %d мм " \
              "(%d мест + персонал ≈ %d чел.%s)" % (need, seats, people, ", более 50" if people > 50 else ", не более 50")
        raw = next(x for x in d["openings"] if x["id"] == o["id"])
        sides = T.opening_sides(P, o)
        out_n = next((n for r, n, fp in sides if r is None), None)
        if out_n is not None:
            raw["swing"] = [int(out_n[0]), int(out_n[1])]
        if clear >= need:
            D(log, "Вход", "входная дверь %s: проём %d мм (в свету ≈ %d), открывание наружу" % (o["id"], o["w"], clear), why)
        else:
            raw["w"] = need + 100
            D(log, "Вход", "входная дверь %s: проём увеличен до %d мм (было %d), открывание наружу" % (o["id"], need + 100, o["w"]), why)


# ------------------------------------------------------------------ windows, shop fronts, doors
GLASS_DOOR = re.compile(r"glass|стекл", re.I)


def _modules(w, max_m=1200):
    n = max(1, int(math.ceil(w / float(max_m))))
    base = int(w // n)
    mods = [base] * n
    mods[-1] += w - base * n
    return mods


def window_spec(o, room_cls, public, door_head=2200):
    """What a senior writes on the windows sheet for an opening found in the source: system, division into sashes /
    modules, opening of each sash, glazing, sill. -> dict merged into opening_types[mark]."""
    w, h, sill = o["w"], o["h"], o.get("sill", 900)
    if sill <= 50 and h >= 2000 and (w >= 1500 or "витраж" in o.get("note", "")):
        mods = _modules(w)
        tr = door_head if door_head < h - 300 else None
        return dict(system="storefront", oboz="ГОСТ 21519-2003",
                    name="Витраж из алюминиевых профилей с терморазрывом %d×%d (%d мод.%s)" % (
                        w, h, len(mods), ", ригель +%s" % ("%.3f" % (tr / 1000.0)).replace(".", ",") if tr else ""),
                    division=mods, transom=tr, sash=["fixed"] * len(mods), frame_w=60,
                    glazing="низ: стеклопакет 6 закалённое - 16 Ar - 44.2 триплекс; верх: 6 закалённое - 16 Ar - 6",
                    profile="алюминиевая стоечно-ригельная система с терморазрывом, стойки 50×120, цвет по дизайну (в модели чёрный)",
                    sill_note="низ витража на отм. ±0,000 - порог-отлив снаружи, примыкание к полу на герметике",
                    note="безопасное остекление нижнего яруса (триплекс / закалённое)")
    wet = room_cls == "wet"
    small = h <= 700 and sill >= 900
    if small:
        return dict(system="pvc", oboz="ГОСТ 30674-99", name="Блок оконный ПВХ %d×%d, створка откидная (фрамуга)" % (w, h),
                    division=[w], sash=["tilt"], frame_w=60,
                    glazing="стеклопакет однокамерный 4-16-4%s" % (", внутреннее стекло матовое (сатинат)" if wet else ""),
                    profile="ПВХ 5-камерный 70 мм, белый", sill_note="подоконник - плитка / ПВХ по месту" if wet else "подоконник ПВХ",
                    note="ручка-ограничитель откидывания" if public else "")
    n = 1 if w <= 900 else 2 if w <= 1800 else 3
    mods = _modules(w, int(math.ceil(w / float(n))) + 1)
    sash = {1: ["tilt-turn"], 2: ["fixed", "tilt-turn"], 3: ["tilt-turn", "fixed", "tilt-turn"]}[len(mods)]
    return dict(system="pvc", oboz="ГОСТ 30674-99", name="Блок оконный ПВХ %d×%d, %d-створчатый" % (w, h, len(mods)),
                division=mods, sash=sash, frame_w=60, glazing="стеклопакет двухкамерный 4-10-4-10-4И (энергосберегающее)",
                profile="ПВХ 5-камерный 70 мм, белый", sill_note="подоконник ПВХ 300 мм, отлив оцинкованный с полимерным покрытием")


def _opening_types(d, base_dir, log, public):
    types = d.get("opening_types") or {}
    if not types:
        return
    P = _P(d, base_dir)
    by_mark = {}
    for o in P.openings:
        if o.get("mark"):
            by_mark.setdefault(o["mark"], []).append(o)
    heads = [o["h"] for o in P.openings if o["kind"] == "door" and T.is_entrance(P, o)]
    done = []
    extra_types = {}
    for mark, t in list(types.items()):
        if not t.get("auto") or t.get("system") or mark not in by_mark:
            continue
        os_ = by_mark[mark]
        o = os_[0]
        if o["kind"] == "window":
            cls = None
            for r, n, fp in T.opening_sides(P, o):
                if r is not None:
                    cls = r.get("cls")
            t.update(window_spec(o, cls, public, door_head=(heads[0] if heads else 2200)))
            nm = t["name"].split(" (")[0].split(",")[0]
            done.append("%s - %s" % (mark, nm[:1].lower() + nm[1:]))
        elif o["kind"] == "door":
            raw = next(x for x in d["openings"] if x["id"] == o["id"])
            glass = bool(GLASS_DOOR.search(raw.get("note", "")))
            entr = T.is_entrance(P, o)
            if entr and public:
                t.update(oboz="ГОСТ 23747-2015", style="glass", system="alu_door",
                         name="Блок дверной алюминиевый остеклённый входной %d×%d, открывание наружу, доводчик" % (o["w"], o["h"]),
                         glazing="стеклопакет 6 закалённое - 16 - 44.2 триплекс", note="порог ≤ 14 мм (МГН), ручка-скоба")
                done.append("%s - входная алюминиевая остеклённая" % mark)
            elif glass:
                def to_wc(x):
                    return any(r is not None and r.get("cls") == "wet" and "санузел" in r["name"].lower()
                               for r, n, fp in T.opening_sides(P, x))
                wcs = [x for x in os_ if to_wc(x)]
                if wcs and len(wcs) < len(os_):          # cubicle doors are another product (indicator lock)
                    used = [int(m_.split("-")[1]) for m_ in list(types) + [x.get("mark", "") for x in d["openings"]]
                            if re.match(r"^Д-\d+$", m_ or "")]
                    new_mark = "Д-%d" % (max(used) + 1)
                    from . import autofix as AF
                    for i, x in enumerate(wcs, 1):
                        rawx = next(y for y in d["openings"] if y["id"] == x["id"])
                        old_id = rawx["id"]
                        rawx["mark"], rawx["id"] = new_mark, "%s.%d" % (new_mark, i)
                        AF._rename_refs(d, old_id, rawx["id"])
                    extra_types[new_mark] = dict(t, oboz="по каталогу производителя", style="glass", system="glass_door",
                                                 name="Дверь стеклянная распашная %d×%d, закалённое стекло 10 мм, "
                                                      "замок-индикатор «свободно/занято»" % (o["w"], o["h"]),
                                                 note="кабина санузла, по модели дизайнера")
                    done.append("%s - стеклянная кабины санузла" % new_mark)
                wc = bool(wcs) and len(wcs) == len(os_)
                t.update(oboz="по каталогу производителя", style="glass", system="glass_door",
                         name="Дверь стеклянная распашная %d×%d, закалённое стекло 10 мм%s" % (
                             o["w"], o["h"], ", замок-индикатор «свободно/занято»" if wc else ""),
                         note="по модели дизайнера")
                done.append("%s - стеклянная" % mark)
    types.update(extra_types)
    if done:
        D(log, "Окна и двери", "; ".join(done),
          "по модели и назначению: витраж - алюминий с безопасным стеклом, окна санузлов - матовые откидные")


# ------------------------------------------------------------------ catering equipment
def _catering(d, base_dir, log):
    P = _P(d, base_dir)
    furn = d.setdefault("furniture", [])
    bar = next((r for r in P.rooms if r.get("cls") == "bar"), None)
    added = []
    for e in d.get("_equipment", []):
        if e["kind"] not in ("coffee", "pos", "grinder", "dishwasher", "ice"):
            continue
        x0, y0, x1, y1 = e["rect"]
        r = P.room_of_point(((x0 + x1) / 2.0, (y0 + y1) / 2.0), 300)
        if r is None or any(f.get("source") == e["name"] and f.get("kind") == e["kind"] for f in furn):
            continue
        w, h = max(x1 - x0, 250), max(y1 - y0, 250)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        furn.append(dict(name=e["title"] + " (по модели)", kind=e["kind"], poly=_snap_poly(_rect(cx, cy, w, h)), room=r["name"],
                         source=e["name"], check=True, on_counter=e["z0"] > 600, z=[e["z0"], e["z1"]]))
        added.append(e["title"].lower())
    if added:
        D(log, "Оборудование бара", "из модели: %s - к ним выводы воды / розетки" % ", ".join(added), "")
    P = _P(d, base_dir)
    if bar is not None:
        bar = P.room_by_name.get(bar["name"])
        mine = [f for f in d["furniture"] if _in_room(f, bar)]
        near = None
        cm = [f for f in mine if f.get("kind") == "coffee"]
        if cm:
            near = _poly_of(cm[0]).centroid
        if not any(f.get("kind") in ("sink", "basin") for f in mine):
            g = place_on_wall(P, d, bar, 350, 300, prefer=near, front=600)
            if g is not None:
                d["furniture"].append(dict(name="Раковина для мытья рук персонала 350×300", kind="basin", poly=g,
                                           room=bar["name"], proposed=True, h=850))
                D(log, "Бар", "раковина для мытья рук персонала 350×300 у стены бара",
                  "СанПиН 2.3/2.4.3590-20: раковина для рук в зоне выдачи; в модели её нет, свободной стены больше нет")
            g = place_on_wall(P, d, bar, 600, 600, prefer=near)
            if g is not None:
                d["furniture"].append(dict(name="Мойка барная 1-секционная 600×600", kind="sink", poly=g, room=bar["name"],
                                           proposed=True, h=850))
                D(log, "Бар", "мойка барная 600×600 у стены бара", "мытьё посуды на месте")
            else:
                d.setdefault("meta", {})["dish_in_service"] = True
                D(log, "Бар", "мойка посуды вынесена в подсобное помещение (в баре нет стены под мойку с проходом 600 мм)",
                  "проход персонала за стойкой важнее; посуда - в моечную зону подсобки")


def _hot_water(d, base_dir, log):
    P = _P(d, base_dir)
    if any(f.get("kind") == "heater" for f in d["furniture"]):
        return
    host = next((r for r in P.rooms if r.get("cls") == "storage"), None) or next((r for r in P.rooms if r.get("cls") == "bar"), None)
    if host is None:
        return
    sinks = [_poly_of(f).centroid for f in d["furniture"] if f.get("kind") == "sink" and f.get("room") == host["name"]]
    wet = [r["shp"] for r in P.rooms if r.get("cls") == "wet"]
    target = sinks[0] if sinks else (unary_union(wet).centroid if wet else None)
    g = place_on_wall(P, d, host, 500, 500, prefer=target, wall_hung=True, front=0)
    if g is not None:
        d["furniture"].append(dict(name="Водонагреватель накопительный 80 л (низ +1,300)", kind="heater", poly=g,
                                   room=host["name"], proposed=True, z=[1300, 2100]))
        D(log, "Горячая вода", "водонагреватель накопительный 80 л в «%s» над мойкой (короткая разводка ГВС к санузлам)" % host["name"],
          "в исходных данных нет источника ГВС; для общепита горячая вода к мойкам и раковинам обязательна")


def place_on_wall(P, d, room, w, depth, prefer=None, entrance_first=False, wall_hung=False, clear_front=600, front=700):
    """Rectangle w × depth backed onto a free wall face of the room: not in a door swing / in front of a door, not on
    another item (wall-hung items may stand above low furniture), inside the room. Nearest to `prefer` (or to the
    room entrance) first. -> poly | None"""
    from .symbols import door_swing_area
    blocks = []
    for o in P.openings:
        if o["kind"] in ("door", "balcony", "passage"):
            try:
                if o.get("swing"):
                    blocks.append(door_swing_area(P, o))
            except Exception:
                pass
            blocks.append(P.open_shape[o["id"]].buffer(clear_front, cap_style=3))
    others = []
    for f in d.get("furniture", []):
        try:
            g = _poly_of(f)
        except Exception:
            continue
        if wall_hung and f.get("kind") in ("sink", "basin", "cabinet", "counter", "kitchen_base", "table"):
            continue
        others.append(g.buffer(30))
    blocked = unary_union(blocks + others) if (blocks or others) else Polygon()
    if prefer is None and entrance_first:
        ents = T.room_entrances(P, room)
        if ents:
            e = ents[0]
            prefer = Point((e["ends"][0][0] + e["ends"][1][0]) / 2.0, (e["ends"][0][1] + e["ends"][1][1]) / 2.0)
    best = None
    solid = unary_union(others) if others else Polygon()
    for seg, n in T.wall_faces(P, room, 100):
        if seg.length < w + 40:
            continue
        s = 20.0 + w / 2.0
        while s <= seg.length - 20 - w / 2.0:
            q = seg.interpolate(s)
            t = (-n[1], n[0])
            a = (q.x - t[0] * w / 2.0, q.y - t[1] * w / 2.0)
            b = (q.x + t[0] * w / 2.0, q.y + t[1] * w / 2.0)
            pts = [a, b, (b[0] + n[0] * depth, b[1] + n[1] * depth), (a[0] + n[0] * depth, a[1] + n[1] * depth)]
            g = Polygon(pts)
            fz = Polygon([pts[3], pts[2], (pts[2][0] + n[0] * front, pts[2][1] + n[1] * front),
                          (pts[3][0] + n[0] * front, pts[3][1] + n[1] * front)]) if front else None
            ok_front = fz is None or (room["shp"].buffer(5).contains(fz) and not fz.intersects(solid))
            if room["shp"].buffer(5).contains(g) and not g.intersects(blocked) and ok_front:
                sc = Point(q.x, q.y).distance(prefer) if prefer is not None else -seg.length
                if best is None or sc < best[0]:
                    best = (sc, pts)
            s += 50.0
    return _snap_poly(best[1]) if best else None


# ------------------------------------------------------------------ service rooms
def _service_rooms(d, base_dir, log, public):
    """An empty service room of a public building gets what it is for: storage racks, staff lockers, a utility sink
    near the risers (the wet rooms' wall)."""
    if not public:
        return
    P = _P(d, base_dir)
    for r in P.rooms:
        if r.get("cls") != "storage" or r["area_exact"] < 4:
            continue
        mine = [f for f in d.get("furniture", []) if _in_room(f, r) and f.get("kind") not in ("heater",)]
        if mine:
            continue
        wet = [x["shp"] for x in P.rooms if x.get("cls") == "wet"]
        target = unary_union(wet).centroid if wet else None
        put = []
        g = place_on_wall(P, d, r, 1000, 600, prefer=target)
        if g is not None:
            d["furniture"].append(dict(name="Мойка производственная 2-секционная 1000×600", kind="sink", poly=g, room=r["name"],
                                       proposed=True, h=850))
            put.append("мойка 2-секционная у стены санузлов (короткая разводка)")
        P = _P(d, base_dir)
        for i in range(2):
            g = place_on_wall(P, d, r, 1200, 500, prefer=None)
            if g is None:
                break
            d["furniture"].append(dict(name="Стеллаж складской 1200×500, h 1800", kind="cabinet", poly=g, room=r["name"],
                                       proposed=True, h=1800))
            P = _P(d, base_dir)
            put.append("стеллаж 1200×500")
        g = place_on_wall(P, d, r, 800, 500, prefer=None, entrance_first=True)
        if g is not None:
            d["furniture"].append(dict(name="Шкаф для одежды персонала 800×500", kind="wardrobe", poly=g, room=r["name"],
                                       proposed=True, h=1900))
            put.append("шкаф персонала у входа")
        if put:
            D(log, "Подсобное помещение", "«%s»: %s" % (r["name"], ", ".join(put)),
              "помещение пустое в модели; состав - минимум для работы кафе (склад, переодевание, мытьё инвентаря)")


# ------------------------------------------------------------------ overlaps
def _overlaps(d, base_dir, log):
    furn = d.get("furniture", [])
    tucked = 0
    for i, a in enumerate(furn):
        if a.get("kind") not in SEAT_KINDS:
            continue
        ga = _poly_of(a)
        for b in furn:
            if b.get("kind") != "table":
                continue
            ov = ga.intersection(_poly_of(b)).area
            if 0 < ov <= 0.6 * ga.area:
                tucked += 1
                break
    if tucked:
        D(log, "Мебель", "кресла / стулья, задвинутые под столы (%d), - не пересечение, оставлены по модели" % tucked,
          "так их ставит дизайнер; проход между группами проверен по плану мебели")
