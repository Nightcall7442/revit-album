# -*- coding: utf-8 -*-
"""Strict check of the project against the 3ds Max scene it was built from (lesson L-100).

    run(d, base_dir) -> (issues, summary)

Every element of the album that came from the scene names its source object (walls: `source`, boxes / floors: `src`,
furniture items: `parts` / `src`, lights: `_lights`, signs: `_texts`). The check:

1. SCENE_UNVERIFIED (error) - an element is built from an object whose geometry could not be evaluated without 3ds Max
   (vertices moved after the topology changed, Symmetry, FFD ...): its size / position in the album is a guess.
   Fix: run scripts/max/sda_export.ms in 3ds Max and rebuild (the export is the truth, nothing is guessed).
2. SCENE_GEOMETRY (error) - a wall's outline in the album differs from its source object by more than 6 mm
   (the 5-mm module snap is allowed).
3. SCENE_MISSING (error) - an architectural object of the scene (a full-height solid on the floor, a tiled cladding,
   a floor covering) is not in the album and not part of a furniture item.
4. NOT_IN_SCENE (warning) - a wall the agent added from indirect evidence (a niche, a wall behind equipment, an
   opening between wall ends): listed for the designer to confirm.
"""
import json
import os
import re

TOL = 6.0
DECOR = re.compile(
    r"(?i)plant|leaf|leaves|palm|ficus|licuala|chamaerops|flower|pot\b|vase|book|cup|mug|plate|dish|bottle|glass_?(?!door)"
    r"|candle|pillow|cushion|decor|sweet|coffee_shop|coffee pack|paper|toilet paper|brush|soap|towel|bin|frame|poster|"
    r"vinyl|record|cable|wire|chain|bulb|handle|knob|hook|screw|bolt|label|logo|sign|text|curtain|blind|cord|rope|"
    r"ivy|planter|grass|tree|"
    r"цвет|растен|книг|чашк|ваз|подушк|декор")
SKIP_CLASSES = ("CoronaLight", "CoronaCam", "CoronaSun", "Target", "Dummy", "VRayLight", "VRayPhysicalCamera",
                "Free Camera", "Target Camera", "Omni", "Point", "Physical", "Sunlight", "ParticleView", None)


def _load_inventory(base_dir):
    p = os.path.join(base_dir, "import", "inventory.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _rect(r):
    if r.get("bbox"):
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        return [x0, y0, x1, y1], z0, z1
    if r.get("footprint"):
        xs = [p[0] for p in r["footprint"]]
        ys = [p[1] for p in r["footprint"]]
        return [min(xs), min(ys), max(xs), max(ys)], r.get("z0", 0.0), r.get("z1", 0.0)
    return None


def _split(s):
    return [x.strip() for x in re.split(r"\s*\+\s*|/", str(s or "")) if x.strip()]


def _uses(d):
    """{scene object name: [what in the album uses it]}"""
    used = {}

    def add(name, what):
        for nm in _split(name):
            used.setdefault(nm, []).append(what)
    for w in d.get("walls", []):
        if w.get("kind") == "box":
            add(w.get("src"), "короб %s" % w.get("id"))
        else:
            add(w.get("source"), "стена %s" % w.get("id"))
    for f in d.get("floors", []):
        add(f.get("src"), "пол %s" % f.get("id"))
    for it in d.get("items", []):
        for p in it.get("parts") or []:
            add(p, "изделие %s" % (it.get("pos") or it.get("id")))
        add(it.get("src"), "изделие %s" % (it.get("pos") or it.get("id")))
    for c in d.get("claddings", []):
        if c.get("on"):
            add(c.get("src"), "облицовка %s" % c["on"])
    for it in d.get("_items_bought", []):
        add(it.get("src"), "покупное изделие")
    for f in d.get("furniture", []):
        add(f.get("source"), "мебель «%s»" % f.get("name"))
    for lt in d.get("_lights", []):
        add(lt.get("name"), "светильник")
        for p in lt.get("parts") if isinstance(lt.get("parts"), list) else []:
            add(p, "светильник")
    for e in d.get("_equipment", []):
        add(e.get("name"), "оборудование")
        for p in e.get("parts") if isinstance(e.get("parts"), list) else []:
            add(p, "оборудование")
    for t in d.get("_texts", []):
        add(t.get("name"), "вывеска «%s»" % t.get("text"))
    for o in d.get("openings", []):
        ev = o.get("evidence")
        for x in (ev if isinstance(ev, list) else [ev]):
            if isinstance(x, str):
                add(x, "проём %s" % o.get("id"))
    for ov in d.get("item_overrides") or []:     # objects the designer chose to leave out (bought chairs ...)
        if ov.get("skip") and ov.get("match"):
            used.setdefault("__skip__", []).append(ov["match"])
    return used


def _skipped_by_designer(used, name):
    for pat in used.get("__skip__", []):
        try:
            if re.search(pat, name or ""):
                return True
        except re.error:
            if pat in (name or ""):
                return True
    return False


def _shift(d, rows_by_name):
    sh = (d.get("meta") or {}).get("scene_shift")
    if sh:
        return float(sh[0]), float(sh[1])
    dx, dy = [], []                              # older projects: from the walls and their sources
    for w in d.get("walls", []):
        if w.get("kind") == "box" or not w.get("rect"):
            continue
        rs = rows_by_name.get(str(w.get("source") or ""))
        if not rs or len(rs) != 1:
            continue
        got = _rect(rs[0])
        if got is None:
            continue
        r = w.get("_rect0") or w["rect"]
        dx.append(r[0] - got[0][0])
        dy.append(r[1] - got[0][1])
    if not dx:
        return 0.0, 0.0
    dx.sort()
    dy.sort()
    return dx[len(dx) // 2], dy[len(dy) // 2]


def _significant(r, storey):
    """An architectural object: a solid from the floor to the slab / ceiling, a tiled cladding, a floor covering.
    Doors, wardrobes, shelves (lower than 85 % of the storey) are furniture, not architecture."""
    got = _rect(r)
    if got is None:
        return None
    (x0, y0, x1, y1), z0, z1 = got
    w, d_, h = x1 - x0, y1 - y0, z1 - z0
    if h > 1.5 * storey or max(w, d_) > 30000:
        return None                              # an environment box / a ground plane, not part of the storey
    mods = r.get("mods") or []
    nm = r.get("name") or ""
    if z0 > storey - 50:
        return None                              # above the slab: parked, not in the room
    if "FloorGenerator" in mods and max(w, d_, h) >= 300:
        return "облицовка / покрытие с раскладкой плитки (FloorGenerator)"
    mats = [m for m in (r.get("materials") or []) if m]
    if h < 40 and -60 < z0 < 60 and w * d_ >= 1.0e6 and mats and not re.search(r"(?i)carpet|rug|ковер|ковёр|mat\b", nm) \
            and not any(m in mods for m in ("Shell", "Extrude", "Sweep", "Lathe")):
        return "покрытие пола (плоскость на полу)"
    if re.search(r"_FG\d", nm) and max(w, d_, h) >= 300:
        return "облицовка плиткой"
    if z0 < 100 and h >= 0.85 * storey and max(w, d_) >= 150:
        return "объект от пола до плиты (стена / колонна / короб)"
    return None


def run(d, base_dir):
    inv = _load_inventory(base_dir)
    if inv is None:
        return [], dict(scene=False)
    rows = [r for r in inv["nodes"] if r.get("class") not in SKIP_CLASSES]
    by_name = {}
    for r in rows:
        by_name.setdefault(r.get("name") or "", []).append(r)
    parent = {r.get("name"): r.get("parent") for r in inv["nodes"]}
    used = _uses(d)
    sx, sy = _shift(d, by_name)
    issues = []
    export = bool(inv.get("export"))

    def ancestors(name):
        seen = set()
        while name and name not in seen:
            seen.add(name)
            yield name
            name = parent.get(name)

    # 1. used objects must be verified
    unver = {}
    for nm, whats in used.items():
        for r in by_name.get(nm, []):
            if r.get("skip"):
                continue
            if r.get("geom") == "unknown" and whats and not all(w.startswith("вывеска") for w in whats):
                unver.setdefault(nm, (r, whats))     # (a sign gives its words and its pivot - both exact)
    for nm, (r, whats) in sorted(unver.items()):
        issues.append(dict(code="SCENE_UNVERIFIED", level="error", obj=nm,
                           msg="%s: объект сцены «%s» - %s; размеры в альбоме не проверены, нужна выгрузка 3ds Max "
                               "(scripts/max/sda_export.ms)" % (", ".join(sorted(set(whats))[:3]), nm,
                                                                "; ".join((r.get("geom_notes") or [])[-2:]) or "модификаторы")))
    # 2. wall outlines against their sources
    for w in d.get("walls", []):
        if w.get("kind") == "box" or not w.get("rect"):
            continue
        names = _split(w.get("source"))
        rs = [r for n in names for r in by_name.get(n, []) if not r.get("skip")]
        if not names or not rs:
            if w.get("source") and not any(n in by_name for n in names):
                issues.append(dict(code="NOT_IN_SCENE", level="warning", obj=w["id"],
                                   msg="стена %s («%s») - вывод агента, отдельного объекта в сцене нет: подтвердить" % (
                                       w["id"], w.get("source"))))
            continue
        if any(r.get("geom") == "unknown" for r in rs):
            continue                             # reported above
        mine = w.get("_rect0") or w["rect"]
        best = None
        for r in rs:                             # the same name twice in a scene: the closest one
            got = _rect(r)
            if got is None:
                continue
            g = got[0]
            sc = [g[0] + sx, g[1] + sy, g[2] + sx, g[3] + sy]
            dev = max(abs(a - b) for a, b in zip(sc, mine))
            if best is None or dev < best[0]:
                best = (dev, sc, r)
        if best is None or len(names) > 1:
            if len(names) > 1 and rs:            # a wall built from several objects: their union
                gs = [_rect(r)[0] for r in rs if _rect(r)]
                if gs:
                    sc = [min(g[0] for g in gs) + sx, min(g[1] for g in gs) + sy, max(g[2] for g in gs) + sx, max(g[3] for g in gs) + sy]
                    best = (max(abs(a - b) for a, b in zip(sc, mine)), sc, rs[0])
            if best is None:
                continue
        if best is not None and "витраж" in str(w.get("note") or ""):
            # a storefront is drawn with its profile depth: only its ends along the facade are checked
            ax = 0 if (mine[2] - mine[0]) >= (mine[3] - mine[1]) else 1
            best = (max(abs(best[1][ax] - mine[ax]), abs(best[1][ax + 2] - mine[ax + 2])), best[1], best[2])
        if best[0] > TOL:
            issues.append(dict(code="SCENE_GEOMETRY", level="error", obj=w["id"],
                               msg="стена %s: в альбоме x %d–%d, y %d–%d; в сцене («%s») x %d–%d, y %d–%d (расхождение %d мм)" % (
                                   w["id"], mine[0], mine[2], mine[1], mine[3], w.get("source"), best[1][0], best[1][2],
                                   best[1][1], best[1][3], best[0])))
    # 3. architectural objects of the scene that the album does not have
    storey = float((d.get("levels") or {}).get("slab") or (d.get("levels") or {}).get("ceiling") or 3000)
    wrects = [w.get("_rect0") or w["rect"] for w in d.get("walls", []) if w.get("rect") and w.get("kind") != "box"]
    brects = []                                  # boxes of the album: what stands inside one is part of it
    for w in d.get("walls", []):
        if w.get("kind") == "box":
            if w.get("rect"):
                brects.append(w["rect"])
            elif w.get("poly"):
                xs = [p[0] for p in w["poly"]]
                ys = [p[1] for p in w["poly"]]
                brects.append([min(xs), min(ys), max(xs), max(ys)])
    if wrects:
        ext = (min(r[0] for r in wrects) - 1500, min(r[1] for r in wrects) - 1500,
               max(r[2] for r in wrects) + 1500, max(r[3] for r in wrects) + 1500)
    else:
        ext = None
    miss = []
    outside = 0
    for r in rows:
        nm = r.get("name") or ""
        if r.get("skip") or not nm:
            continue
        if any(a in used for a in ancestors(nm)):
            continue
        what = _significant(r, storey)
        if what is None:
            continue
        if DECOR.search(nm) and "_FG" not in nm:
            continue
        (x0, y0, x1, y1), z0, z1 = _rect(r)
        pr = [x0 + sx, y0 + sy, x1 + sx, y1 + sy]
        if ext and not (ext[0] <= (pr[0] + pr[2]) / 2 <= ext[2] and ext[1] <= (pr[1] + pr[3]) / 2 <= ext[3]):
            outside += 1                         # library objects parked away from the plan
            continue
        if any(pr[0] >= q[0] - 20 and pr[1] >= q[1] - 20 and pr[2] <= q[2] + 20 and pr[3] <= q[3] + 20 for q in wrects + brects):
            continue                             # faces detached from a wall / the inside of a box: that element
        if _skipped_by_designer(used, nm) or any(_skipped_by_designer(used, a) for a in ancestors(nm)):
            continue
        miss.append((nm, what, r))
    # 4. other objects of the plan the album does not show (built-ins, equipment, ducts): for the designer to check
    groups = {}
    missed = {m[0] for m in miss}
    for r in rows:
        nm = r.get("name") or ""
        if r.get("skip") or not nm or nm in missed or any(a in used for a in ancestors(nm)):
            continue
        got = _rect(r)
        if got is None:
            continue
        (x0, y0, x1, y1), z0, z1 = got
        if z1 - z0 > 1.5 * storey or z0 > storey - 50:
            continue
        pr = [x0 + sx, y0 + sy, x1 + sx, y1 + sy]
        if ext and not (ext[0] + 1000 <= (pr[0] + pr[2]) / 2 <= ext[2] - 1000 and ext[1] + 1000 <= (pr[1] + pr[3]) / 2 <= ext[3] - 1000):
            continue
        if any(pr[0] >= q[0] - 30 and pr[1] >= q[1] - 30 and pr[2] <= q[2] + 30 and pr[3] <= q[3] + 30 for q in wrects + brects):
            continue
        if r.get("render_off") or _skipped_by_designer(used, nm) or any(_skipped_by_designer(used, a) for a in ancestors(nm)):
            continue
        top = list(ancestors(nm))[-1]
        if DECOR.search(top) or DECOR.search(nm):
            continue
        g = groups.setdefault(top, [pr[0], pr[1], z0, pr[2], pr[3], z1])
        g[:] = [min(g[0], pr[0]), min(g[1], pr[1]), min(g[2], z0), max(g[3], pr[2]), max(g[4], pr[3]), max(g[5], z1)]
    for top, g in sorted(groups.items()):
        size = (g[3] - g[0], g[4] - g[1], g[5] - g[2])
        if max(size) < 400:
            continue
        issues.append(dict(code="SCENE_UNUSED", level="warning", obj=top,
                           msg="в сцене «%s» (%d×%d×%d мм, x %d, y %d, низ %+d) - в альбоме не показан: проверить" % (
                               top, size[0], size[1], size[2], (g[0] + g[3]) / 2, (g[1] + g[4]) / 2, g[2])))
    for nm, what, r in miss:
        got = _rect(r)
        (x0, y0, x1, y1), z0, z1 = got
        off = bool(r.get("render_off"))          # the "rendered" flag of the node is off: most likely not in renders
        issues.append(dict(code="SCENE_MISSING", level="warning" if off else "error", obj=nm,
                           msg="в сцене есть «%s» (%s, %d×%d×%d мм, x %d, y %d) - в альбоме не учтён%s" % (
                               nm, what, x1 - x0, y1 - y0, z1 - z0, (x0 + x1) / 2 + sx, (y0 + y1) / 2 + sy,
                               " (у объекта снят флаг рендера - вероятно, не на визуализациях; проверить)" if off else "")))
    geo = [r for r in rows if _rect(r) is not None and not r.get("skip")]
    summary = dict(scene=True, export=export, objects=len(geo),
                   used=sum(1 for r in geo if r.get("name") in used),
                   unverified=len(unver), missing=sum(1 for m in miss if not m[2].get("render_off")), outside=outside,
                   geometry=sum(1 for i in issues if i["code"] == "SCENE_GEOMETRY"),
                   statuses={k: sum(1 for r in geo if (r.get("geom") or "exact") == k)
                             for k in ("export", "exact", "replayed", "bound", "unknown")})
    return issues, summary


def print_report(issues, summary):
    if not summary.get("scene"):
        return
    print("Сверка со сценой 3ds Max: объектов %d, использовано %d, не проверено %d, не учтено %d, расхождений геометрии %d%s" % (
        summary["objects"], summary["used"], summary["unverified"], summary["missing"], summary["geometry"],
        " (по выгрузке 3ds Max)" if summary.get("export") else ""))
    for i in issues:
        print("  [%s] %s" % (i["code"], i["msg"]))
