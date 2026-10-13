# -*- coding: utf-8 -*-
"""3D scene objects -> draft project.json (walls, openings, furniture, named objects for room naming).

Input: objects = [dict(name, parent, cls, nverts, rect=(x0, y0, x1, y1) mm, z0, z1, flat, mods)] in millimetres.

  walls      thin (60-700 mm) long objects standing on the floor: tall simple meshes, or flat Plane/Box primitives
             extruded by Edit Poly; the group holding most of them is the architectural shell. Curtains, doors,
             mirrors, shelves, glass, furniture are never walls (by name).
  openings   gaps between wall ends (<= 2.6 m, or any length when glazing spans it - a shop front); a door object in
             the gap -> door, glazing -> window, otherwise by position.
  furniture  objects named like toilet / washbasin / fridge / table / chair / sofa / bed ... -> kind + footprint
             (parts of one item merged).
  _objects   names + positions of everything on the floor: autofix names the rooms by what stands in them.
"""
import json
import re

from shapely.geometry import box
from shapely.ops import unary_union

NOT_WALL = re.compile(r"curtain|штор|door|двер|mirror|зеркал|shelf|полк|book|glass|стекл|window|окн|wd_|rail|pipe|"
                      r"труб|duct|воздух|light|lamp|свет|plant|palm|tree|ficus|vase|table|стол|chair|стул|sofa|диван|"
                      r"counter|стойк|cabinet|шкаф|tv|screen|frame|рамк|text|camera|cam\b|sun|sky|ground|terrain|"
                      r"environment|floor|пол\b|ceiling|потол|carpet|ковёр|ковер|rug|picture|картин|foto|photo|art",
                      re.I)
DOOR = re.compile(r"door|двер", re.I)
GLAZING = re.compile(r"glass|стекл|window|окн|витраж|glazing|pcube", re.I)

FURN = [  # (regex, kind, display name) - first match wins
    (r"toilet\s*paper|paper\s*holder|brush|ерш|seat\b|seat cover|accessor", None, None),
    (r"toilet|унитаз|\bwc\b|closet bowl|urinal|писсуар", "wc", "Унитаз"),
    (r"wash\s*basin|washbasin|basin|раковин|lavabo|vanity|console sink", "basin", "Раковина"),
    (r"shower|душ", "shower", "Душевой поддон"),
    (r"bath\s*tub|bathtub|ванн", "bath", "Ванна"),
    (r"washing machine|washer|стирал", "washer", "Стиральная машина"),
    (r"fridge|refriger|холодил|hicold|freezer|морозил", "fridge", "Холодильник"),
    (r"\bhob\b|stove|cooker|плит[аы]|oven|духов|fryer|фритюр|grill", "hob", "Плита / жарочное"),
    (r"\bsink\b|мойк", "sink", "Мойка"),
    (r"bar\s*counter|counter|стойк|reception|ресепш", "cabinet", "Барная стойка"),
    (r"wardrobe|гардероб|closet", "wardrobe", "Шкаф"),
    (r"\bbed\b|кроват", "bed", "Кровать"),
    (r"sofa|диван|banquette|банкет", "sofa", "Диван"),
    (r"armchair|кресл|swivel chair|lounge", "armchair", "Кресло"),
    (r"chair|стул|stool|табурет", "chair", "Стул"),
    (r"table|стол", "table", "Стол"),
    (r"\btv\b|телевиз", "tv", "Телевизор"),
    (r"shelf|стеллаж|rack", "cabinet", "Стеллаж"),
]
FURN = [(re.compile(rx, re.I), k, n) for rx, k, n in FURN]


def furniture_kind(name):
    for rx, kind, disp in FURN:
        if rx.search(name or ""):
            return kind, disp
    return None, None


def _shellish(o):
    return o.get("flat") and o["cls"] in ("Plane", "Box") or (o.get("nverts") or 99) <= 64


def stack_walls(objects, tmin=60, tmax=700):
    """A wall modelled in parts - below the sill, above the window head, a panel - is one wall: thin objects with the
    same orientation, overlapping along >= 70 % and touching across (<= 50 mm) are merged; a vertical gap between
    the parts (>= 100 mm) is a window band (sill, head). Returns new objects (the parts are dropped)."""
    thin = []
    for i, o in enumerate(objects):
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        if 20 <= t <= tmax and L >= 600 and _shellish(o) and not NOT_WALL.search(o["name"] or ""):
            thin.append((i, o, w >= h))
    used, out, merged_ids = set(), [], set()
    for a in range(len(thin)):
        if a in used:
            continue
        ia, oa, ha = thin[a]
        grp = [a]
        for b in range(a + 1, len(thin)):
            if b in used:
                continue
            ib, ob, hb = thin[b]
            if ha != hb:
                continue
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = oa["rect"], ob["rect"]
            if ha:
                ov = min(ax1, bx1) - max(ax0, bx0)
                gap = max(by0 - ay1, ay0 - by1)
                La, Lb = ax1 - ax0, bx1 - bx0
            else:
                ov = min(ay1, by1) - max(ay0, by0)
                gap = max(bx0 - ax1, ax0 - bx1)
                La, Lb = ay1 - ay0, by1 - by0
            if ov >= 0.7 * min(La, Lb) and gap <= 50:
                grp.append(b)
        if len(grp) < 2:
            continue
        parts = [thin[g][1] for g in grp]
        zs = sorted((p["z0"], p["z1"]) for p in parts)
        z0, z1 = zs[0][0], max(z for _, z in zs)
        if z0 > 300 or z1 - z0 < 2000:
            continue
        band, top = None, zs[0][1]
        for a0, a1 in zs[1:]:
            if a0 - top >= 100 and (band is None or a0 - top > band[1] - band[0]):
                band = (top, a0)
            top = max(top, a1)
        xs0 = min(p["rect"][0] for p in parts)
        ys0 = min(p["rect"][1] for p in parts)
        xs1 = max(p["rect"][2] for p in parts)
        ys1 = max(p["rect"][3] for p in parts)
        out.append(dict(parts[0], name="+".join(p["name"] for p in parts)[:80], rect=(xs0, ys0, xs1, ys1), z0=z0, z1=z1,
                        nverts=8, flat=False, window_band=band))
        used.update(grp)
        merged_ids.update(thin[g][0] for g in grp)
    return [o for i, o in enumerate(objects) if i not in merged_ids] + out


def wall_candidates(objects, tmin=60, tmax=700):
    objects = stack_walls(objects, tmin, tmax)
    cands = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        column = 150 <= t <= 1200 and L <= 1.6 * t and _shellish(o)      # columns / pilasters close the wall line
        if not column and (not (tmin <= t <= tmax) or L < max(3 * t, 600) or L > 60000):
            continue
        if NOT_WALL.search(o["name"] or ""):
            continue
        if o["z0"] > 300:                     # walls stand on the floor (a lintel / beam above a door is not a wall)
            continue
        tall = (o["z1"] - o["z0"]) >= 2000
        extruded = o.get("flat") and any(re.search(r"edit poly|extrude|shell", m, re.I) for m in o.get("mods", []))
        simple = (o.get("nverts") or 0) <= 64
        if not (tall or extruded or (o.get("flat") and o["cls"] in ("Plane", "Box"))):
            continue
        cands.append(dict(o, simple=simple or extruded or o["cls"] in ("Plane", "Box")))
    from collections import Counter
    groups = Counter(c.get("parent") for c in cands if c.get("parent"))
    shell = groups.most_common(1)[0][0] if groups and groups.most_common(1)[0][1] >= 3 else None
    out = []
    for c in cands:
        if c.get("parent") == shell or (c["simple"] and (c["z1"] - c["z0"]) >= 2000):
            out.append(c)
    # duplicates (a wall and its copy / finish layer): keep the bigger one
    out.sort(key=lambda c: -(c["rect"][2] - c["rect"][0]) * (c["rect"][3] - c["rect"][1]))
    keep = []
    for c in out:
        b = box(*c["rect"])
        if any(b.intersection(box(*k["rect"])).area > 0.8 * b.area for k in keep):
            continue
        keep.append(c)
    return keep, shell


def facades(objects, walls):
    """Shop fronts / curtain walls: long, tall, thin and detailed (frames, glass) objects that are not curtains or
    furniture -> a wall line with one glazing opening along it."""
    out = []
    for o in objects:
        x0, y0, x1, y1 = o["rect"]
        w, h = x1 - x0, y1 - y0
        t, L = min(w, h), max(w, h)
        if not (20 <= t <= 300) or L < 2000 or (o["z1"] - o["z0"]) < 2000 or o["z0"] > 300:
            continue
        if (o.get("nverts") or 0) <= 64 or NOT_WALL.search(o["name"] or ""):
            continue
        b = box(*o["rect"])
        if any(b.intersection(box(*c["rect"])).area > 0.5 * b.area for c in walls):
            continue
        out.append(o)
    return out


def furniture(objects, rooms_hint=None):
    items = []
    for o in objects:
        if o["z0"] > 1500 or (o["z1"] - o["z0"]) < 30:
            continue
        kind, disp = furniture_kind(o["name"])
        if not kind:
            kind, disp = furniture_kind(o.get("parent") or "")
            if not kind:
                continue
        x0, y0, x1, y1 = o["rect"]
        if (x1 - x0) < 150 or (y1 - y0) < 150 or (x1 - x0) * (y1 - y0) > 30e6:
            continue
        items.append(dict(kind=kind, name=disp, rect=[x0, y0, x1, y1], src=o["name"], group=o.get("parent")))
    # parts of one item (legs, top, base of one table; a group of meshes) -> one footprint
    merged = []
    for it in sorted(items, key=lambda i: -(i["rect"][2] - i["rect"][0]) * (i["rect"][3] - i["rect"][1])):
        b = box(*it["rect"])
        for m in merged:
            mb = box(*m["rect"])
            same_group = it["group"] and it["group"] == m["group"]
            if m["kind"] == it["kind"] and (b.intersection(mb).area > 0.3 * min(b.area, mb.area) or
                                             (same_group and b.distance(mb) < 50)):
                u = b.union(mb).bounds
                m["rect"] = list(u)
                break
        else:
            merged.append(dict(it))
    out = []
    for m in merged:
        x0, y0, x1, y1 = [int(round(v / 5.0) * 5) for v in m["rect"]]
        out.append(dict(name=m["name"], kind=m["kind"], poly=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], source=m["src"],
                        check=True))
    return out


def openings(walls_polys, objects, outline_of, max_gap=2600):
    """Gaps between wall ends -> [(gap rect, horizontal?, kind)]. Long gaps only when glazing spans them."""
    from importers.dxf_plan import close_gaps
    from shapely.geometry import Polygon
    mass = unary_union(walls_polys)
    gaps = []
    for g, horiz in close_gaps(walls_polys, max_gap=max(max_gap, 20000)):
        # a "gap" lying along a wall (a column sticking out of a wall faces the next wall) is not an opening
        x0, y0, x1, y1 = g.bounds
        if horiz:
            sides = [box(x0 + 20, y1, x1 - 20, y1 + 10), box(x0 + 20, y0 - 10, x1 - 20, y0)]
        else:
            sides = [box(x1, y0 + 20, x1 + 10, y1 - 20), box(x0 - 10, y0 + 20, x0, y1 - 20)]
        if any(s.area > 0 and s.intersection(mass).area >= 0.8 * s.area for s in sides):
            continue
        gaps.append((g, horiz))
    closed = unary_union(walls_polys + [g for g, _ in gaps])
    outline_of = unary_union([Polygon(q.exterior) for q in (closed.geoms if hasattr(closed, "geoms") else [closed])])
    doors = [box(*o["rect"]) for o in objects if DOOR.search(o["name"] or "")]
    glaz = [box(*o["rect"]).buffer(60) for o in objects if GLAZING.search(o["name"] or "") and not DOOR.search(o["name"] or "")
            and (o["z1"] - o["z0"]) >= 1200]
    glass = unary_union(glaz) if glaz else None
    out = []
    for g, horiz in gaps:
        x0, y0, x1, y1 = g.bounds
        width = (x1 - x0) if horiz else (y1 - y0)
        zone = g.buffer(150)
        has_door = any(zone.intersects(d) for d in doors)
        cover = (g.intersection(glass).area / g.area) if glass is not None and g.area > 0 else 0.0
        if width > max_gap and cover < 0.5:
            continue
        if has_door and width <= max_gap:
            kind = "door"
        elif cover >= 0.3:
            kind = "window"
        else:
            c = g.centroid
            ol = outline_of
            t = (y1 - y0) if horiz else (x1 - x0)
            n = (0, 1) if horiz else (1, 0)
            a = (c.x + n[0] * (t / 2 + 150), c.y + n[1] * (t / 2 + 150))
            b = (c.x - n[0] * (t / 2 + 150), c.y - n[1] * (t / 2 + 150))
            from shapely.geometry import Point
            outside = ol is not None and (not ol.contains(Point(a)) or not ol.contains(Point(b)))
            kind = "window" if outside and width >= 600 else ("passage" if width >= 1300 else "door")
        out.append((g, horiz, kind))
    return out


def build(objects, ceil, path, png=None):
    from shapely.geometry import Polygon
    walls, shell = wall_candidates(objects)
    ws = []
    front_ops = []
    for i, c in enumerate(walls, 1):
        x0, y0, x1, y1 = [round(v) for v in c["rect"]]
        ws.append(dict(id="W%d" % i, kind="existing", rect=[x0, y0, x1, y1], source=c["name"], check=True))
        if c.get("window_band"):                 # wall built from parts around a window: the window itself
            s0, s1 = c["window_band"]
            horiz = (x1 - x0) >= (y1 - y0)
            L = (x1 - x0) if horiz else (y1 - y0)
            front_ops.append(dict(id="ОК.W%d" % i, mark="ОК-?", kind="window", wall="W%d" % i,
                                  c=round((x0 + x1) / 2 if horiz else (y0 + y1) / 2), w=int(L - 100),
                                  h=int(round(s1 - s0)), sill=int(round(s0)), check=True))
    for j, f in enumerate(facades(objects, walls), 1):
        x0, y0, x1, y1 = [round(v) for v in f["rect"]]
        horiz = (x1 - x0) >= (y1 - y0)
        if horiz and y1 - y0 < 100:
            y0, y1 = int((y0 + y1) / 2 - 50), int((y0 + y1) / 2 + 50)
        if not horiz and x1 - x0 < 100:
            x0, x1 = int((x0 + x1) / 2 - 50), int((x0 + x1) / 2 + 50)
        wid = "ВТ%d" % j
        ws.append(dict(id=wid, kind="existing", rect=[x0, y0, x1, y1], source=f["name"], check=True, note="витраж"))
        L = (x1 - x0) if horiz else (y1 - y0)
        front_ops.append(dict(id="ОК.В%d" % j, mark="ОК-?", kind="window", wall=wid, c=round((x0 + x1) / 2 if horiz else (y0 + y1) / 2),
                              w=int(L - 200), h=int(min(ceil, 3000) - 100), sill=0, check=True, note="витраж"))
    polys = [box(*w["rect"]) for w in ws]
    mass = unary_union(polys) if polys else None
    outline = unary_union([Polygon(g.exterior) for g in (mass.geoms if hasattr(mass, "geoms") else [mass])]) if mass else None
    ops = []
    for i, (g, horiz, kind) in enumerate(openings(polys, objects, outline) if polys else [], 1):
        x0, y0, x1, y1 = g.bounds
        wid = "ПР%d" % i
        ws.append(dict(id=wid, kind="existing", rect=[round(x0), round(y0), round(x1), round(y1)], source="проём", check=True))
        c = g.centroid
        width = (x1 - x0) if horiz else (y1 - y0)
        pref = {"window": "ОК", "door": "Д", "passage": "ПР"}[kind]
        o = dict(id="%s.%d" % (pref, i), mark="%s-?" % pref, kind=kind, wall=wid, c=round(c.x if horiz else c.y),
                 w=round(width), h=1500 if kind == "window" else 2100, check=True)
        if kind == "window":
            o["sill"] = 900 if width <= 2600 else 0
            if width > 2600:
                o["h"] = int(min(ceil, 3000))
        ops.append(o)
    ops = front_ops + ops
    furn = furniture(objects)
    if mass is not None:                        # library objects parked away from the plan are not furniture
        zone = box(*unary_union(polys).bounds).buffer(500)
        furn = [f for f in furn if zone.contains(box(*[min(p[0] for p in f["poly"]), min(p[1] for p in f["poly"]),
                                                          max(p[0] for p in f["poly"]), max(p[1] for p in f["poly"])]).centroid)]
    named = [[o["name"], round((o["rect"][0] + o["rect"][2]) / 2), round((o["rect"][1] + o["rect"][3]) / 2)]
             for o in objects if o["z0"] < 2500 and o["name"]][:4000]
    d = dict(meta=dict(title="ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА", studio="Space Design Studio", stage="Дизайн-проект"),
             levels=dict(floor=0, ceiling=int(round(ceil / 10.0) * 10), slab=int(round((ceil + 400) / 10.0) * 10)),
             grid=dict(x=[], y=[]), walls=ws, openings=ops, rooms=[], furniture=furn, lighting=[], switches=[],
             sockets=[], plumbing=[], floors=[], ceilings=dict(types=[], zones=[]), elevations=[], nodes=[],
             _objects=named,
             _todo=["проверить стены, проёмы и мебель (check=true) по plan_cut.png / draft_plan.png",
                    "назвать помещения (по содержимому названы автоматически)", "оси и высоты - уточнить"])
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if png:
        _plot(d, png)
    return d, shell


def _plot(d, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, ax = plt.subplots(figsize=(14, 14))
    for w in d["walls"]:
        x0, y0, x1, y1 = w["rect"]
        col = "#d08020" if w.get("source") == "проём" else "#222"
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, color=col, alpha=0.85))
    for o in d["openings"]:
        w = next(x for x in d["walls"] if x["id"] == o["wall"])
        x0, y0, x1, y1 = w["rect"]
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, "%s %d" % (o["id"], o["w"]), fontsize=7, color="#1060c0", ha="center")
    for f in d["furniture"]:
        xs = [p[0] for p in f["poly"]]
        ys = [p[1] for p in f["poly"]]
        ax.add_patch(Rectangle((min(xs), min(ys)), max(xs) - min(xs), max(ys) - min(ys), fill=False, ec="#2a8a2a", lw=0.7))
        ax.text(sum(xs) / 4, sum(ys) / 4, f["kind"], fontsize=5, color="#2a8a2a", ha="center")
    ax.autoscale()
    ax.set_aspect("equal")
    ax.grid(True, lw=0.3, alpha=0.4)
    ax.set_title("черновик: стены (чёрн.), закрытые проёмы (оранж.), мебель (зел.)")
    fig.savefig(png, dpi=110, bbox_inches="tight")
    plt.close(fig)
