# -*- coding: utf-8 -*-
"""Plain edits of project.json with selectors, a journal and undo; human-readable diff between versions.

Selector:  section[cond,cond,...]  or  section#N (1-based)  or  section
  cond:    key=value (exact), key~text (contains, any case), key>v, key<v,
           room=Name   (for points without a 'room' field the room is found by position),
           near=x:y    (the nearest item, within 600 mm)
Sections:  walls openings rooms furniture lighting switches sockets plumbing floors elevations nodes
           zones (ceilings.zones) ctypes (ceilings.types) ftypes (finishes.types) segments (finishes.segments)
           otypes (opening_types: key = mark) panel meta levels
Operations (one per argument):
  set SEL key=value [key=value ...]   value is JSON when it parses (600, [1,2], true), else text
  move SEL dx dy                      shift by dx, dy mm (points, contours, walls, seeds; openings along their wall)
  del SEL
  add SECTION {json}
  rename-room OLD NEW                 the name changes everywhere it is referenced
"""
import copy
import json
import math
import re

from . import model as M

SECTION_PATH = {
    "zones": ("ceilings", "zones"), "ctypes": ("ceilings", "types"), "ftypes": ("finishes", "types"),
    "segments": ("finishes", "segments"),
}
NAMES = {
    "walls": "Стены", "openings": "Проёмы", "rooms": "Помещения", "furniture": "Мебель", "lighting": "Светильники",
    "switches": "Выключатели", "sockets": "Розетки", "plumbing": "Сантехника", "floors": "Полы", "elevations": "Развёртки",
    "nodes": "Узлы", "zones": "Потолок: зоны", "ctypes": "Потолок: типы", "ftypes": "Отделка: типы",
    "segments": "Отделка: участки", "otypes": "Типы проёмов", "panel": "Щит", "meta": "Реквизиты", "levels": "Высоты",
    "circuits": "Группы щита", "separations": "Границы помещений",
}
SHEETS = {
    "walls": "все планы", "openings": "планы, развёртки, ведомость проёмов", "rooms": "общие данные, все планы",
    "furniture": "мебель (и подложка других планов)", "lighting": "освещение", "switches": "освещение",
    "sockets": "розетки", "panel": "розетки", "circuits": "розетки", "plumbing": "сантехника, санузлы",
    "floors": "полы", "zones": "потолки, узлы", "ctypes": "потолки", "ftypes": "отделка, развёртки",
    "segments": "отделка", "elevations": "развёртки", "nodes": "узлы", "otypes": "ведомость проёмов",
    "meta": "обложка, обращение, общие данные, штампы", "levels": "все планы, развёртки", "separations": "все планы",
}


class EditError(Exception):
    pass


# ------------------------------------------------------------------ selectors
def _container(d, section, create=False):
    if section in SECTION_PATH:
        a, b = SECTION_PATH[section]
        if create:
            d.setdefault(a, {}).setdefault(b, [])
        return d.get(a, {}).get(b, [])
    if section == "otypes":
        return d.setdefault("opening_types", {}) if create else d.get("opening_types", {})
    if create and section not in d:
        d[section] = {} if section in ("meta", "levels") else []
    return d.get(section)


def parse_selector(s):
    m = re.match(r"^([a-z_]+)(?:#(\d+))?(?:\[(.*)\])?$", s.strip())
    if not m:
        raise EditError("не понял выбор «%s» (пример: sockets[room=Спальня,kind=Р2])" % s)
    sec, idx, conds = m.group(1), m.group(2), m.group(3)
    out = []
    if conds:
        for c in _split(conds):
            mm = re.match(r"^\s*([\w.]+)\s*(=|~|>|<)\s*(.*?)\s*$", c)
            if not mm:
                raise EditError("условие «%s» не распознано" % c)
            out.append((mm.group(1), mm.group(2), mm.group(3)))
    return sec, (int(idx) if idx else None), out


def _split(s):
    parts, cur, depth = [], "", 0
    for ch in s:
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += ch in "([{"
        depth -= ch in ")]}"
        cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _room_of_item(P, sec, it):
    if isinstance(it, dict) and it.get("room"):
        return it["room"]
    if P is None or not isinstance(it, dict):
        return None
    if "x" in it and "y" in it:
        r = P.room_of_point((it["x"], it["y"]), 80)
        return r["name"] if r else None
    if "poly" in it and it["poly"]:
        from shapely.geometry import Polygon
        c = Polygon(it["poly"]).representative_point()
        r = P.room_of_point((c.x, c.y), 80)
        return r["name"] if r else None
    if sec == "rooms":
        return it.get("name")
    return None


def _anchor(it):
    if not isinstance(it, dict):
        return None
    if "x" in it and "y" in it:
        return it["x"], it["y"]
    if it.get("poly"):
        xs = [p[0] for p in it["poly"]]
        ys = [p[1] for p in it["poly"]]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if it.get("rect"):
        x0, y0, x1, y1 = it["rect"]
        return (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if it.get("seed"):
        return tuple(it["seed"])
    if it.get("a") and it.get("b"):
        return (it["a"][0] + it["b"][0]) / 2.0, (it["a"][1] + it["b"][1]) / 2.0
    return None


def select(d, sel, P=None):
    """-> (section, [(key or index, item)])"""
    sec, idx, conds = parse_selector(sel)
    cont = _container(d, sec)
    if cont is None:
        raise EditError("раздел «%s» пуст или не существует" % sec)
    if isinstance(cont, dict):
        if sec in ("meta", "levels", "panel"):
            return sec, [(None, cont)]
        items = list(cont.items())
    else:
        items = list(enumerate(cont))
    if idx is not None:
        if not 1 <= idx <= len(items):
            raise EditError("%s#%d: всего элементов %d" % (sec, idx, len(items)))
        items = [items[idx - 1]]
    near = None
    for key, op, val in conds:
        if key == "near":
            xy = [float(v) for v in re.split(r"[:;/ ]", val) if v]
            near = (xy[0], xy[1])
            continue
        res = []
        for k, it in items:
            if key == "room":
                v = _room_of_item(P, sec, it)
            elif key in ("key", "mark") and sec == "otypes":
                v = k
            else:
                v = it.get(key) if isinstance(it, dict) else None
            if _match(v, op, val):
                res.append((k, it))
        items = res
    if near is not None:
        items = [(k, it) for k, it in items if _anchor(it) is not None]
        items.sort(key=lambda kv: math.hypot(_anchor(kv[1])[0] - near[0], _anchor(kv[1])[1] - near[1]))
        items = [kv for kv in items[:1] if math.hypot(_anchor(kv[1])[0] - near[0], _anchor(kv[1])[1] - near[1]) <= 600]
    return sec, items


def _word_in(w, text):
    """'кровать' finds 'у кровати', 'розетки' finds 'розетка': Russian endings are ignored for longer words."""
    if w in text:
        return True
    if len(w) > 5 and w[:-2] in text:
        return True
    return len(w) > 4 and w[:-1] in text


def _match(v, op, val):
    if v is None:
        return False
    if op == "~":
        text = (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)).lower()
        return all(_word_in(w, text) for w in val.lower().split())
    if op in (">", "<"):
        a, b = _num(v), _num(val)
        return a is not None and b is not None and (a > b if op == ">" else a < b)
    a, b = _num(v), _num(val)
    if a is not None and b is not None and not isinstance(v, str):
        return abs(a - b) < 1e-6
    return str(v) == val


# ------------------------------------------------------------------ descriptions
def describe(sec, it, P=None):
    if not isinstance(it, dict):
        return json.dumps(it, ensure_ascii=False)
    room = _room_of_item(P, sec, it)
    at = ""
    if "x" in it and "y" in it:
        at = " (%s; %s)" % (_f(it["x"]), _f(it["y"]))
    rm = (", " + room) if room and sec not in ("rooms",) else ""
    if sec == "sockets":
        return "%s h%s%s%s%s" % (it.get("kind"), _f(it.get("h", "")), (" «%s»" % it["note"]) if it.get("note") else "",
                                 rm, at) + (" гр.%s" % it["group"] if it.get("group") else "")
    if sec == "switches":
        ctl = ", ".join("%s-%s" % (c.get("key", ""), c.get("group", "")) for c in it.get("controls", []))
        return "%s h%s [%s]%s%s" % (it.get("id"), _f(it.get("h", 900)), ctl, rm, at)
    if sec == "lighting":
        return "%s, группа «%s»%s" % (it.get("kind"), it.get("group", ""), at)
    if sec == "plumbing":
        return "%s %s h%s%s%s" % (it.get("kind"), it.get("fixture", ""), _f(it.get("h", 0)), rm, at)
    if sec == "furniture":
        x0 = _anchor(it)
        return "%s (%s)%s%s" % (it.get("name"), it.get("kind"), rm, (" центр %d; %d" % (round(x0[0]), round(x0[1]))) if x0 else "")
    if sec == "openings":
        return "%s %s w%s h%s в стене %s%s" % (it.get("id"), it.get("kind"), _f(it.get("w")), _f(it.get("h", "")), it.get("wall"),
                                               (", " + it["room"]) if it.get("room") else "")
    if sec == "walls":
        return "%s %s %s" % (it.get("id"), it.get("kind", "existing"), it.get("rect") or it.get("poly") or [it.get("a"), it.get("b")])
    if sec == "rooms":
        return "%s %s (%s)" % (it.get("num", ""), it.get("name"), it.get("cls", "living"))
    if sec == "elevations":
        return "%s %s" % (it.get("group"), it.get("label"))
    if "id" in it:
        return "%s %s" % (it["id"], it.get("material") or it.get("desc") or it.get("name") or it.get("short") or "")
    return json.dumps(it, ensure_ascii=False)[:120]


def _f(v):
    if isinstance(v, float) and abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return str(v)


# ------------------------------------------------------------------ operations
def _tokens(op):
    """Split on spaces outside quotes / brackets; quotes are kept (key="two words" stays one token)."""
    out, cur, q, depth = [], "", None, 0
    for ch in op:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            cur += ch
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def _unq(a):
    if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'":
        return a[1:-1]
    return a


def _value(s):
    try:
        return json.loads(s)
    except Exception:
        return s


def _shift(it, dx, dy, P=None):
    for kx, ky in (("x", "y"), ("x2", "y2")):
        if kx in it and ky in it:
            it[kx] = _rnd(it[kx] + dx)
            it[ky] = _rnd(it[ky] + dy)
    for k in ("poly",):
        if it.get(k):
            it[k] = [[_rnd(p[0] + dx), _rnd(p[1] + dy)] + list(p[2:]) for p in it[k]]
    if it.get("front"):                                       # counter fronts: [[a, b], ...]
        it["front"] = [[[_rnd(a[0] + dx), _rnd(a[1] + dy)], [_rnd(b[0] + dx), _rnd(b[1] + dy)]] for a, b in it["front"]]
    if it.get("rect"):
        x0, y0, x1, y1 = it["rect"]
        it["rect"] = [_rnd(x0 + dx), _rnd(y0 + dy), _rnd(x1 + dx), _rnd(y1 + dy)]
    for k in ("a", "b", "seed", "at"):
        if isinstance(it.get(k), list) and len(it[k]) >= 2 and all(isinstance(v, (int, float)) for v in it[k][:2]):
            it[k] = [_rnd(it[k][0] + dx), _rnd(it[k][1] + dy)] + list(it[k][2:])
    if "c" in it and "wall" in it and P is not None:          # an opening slides along its wall
        w = P.wall_by_id.get(it["wall"])
        if w is not None:
            it["c"] = _rnd(it["c"] + (dx if w["dir"] == "H" else dy))
            if "hinge_at" in it:
                it["hinge_at"] = _rnd(it["hinge_at"] + (dx if w["dir"] == "H" else dy))


def _rnd(v):
    v = round(v, 1)
    return int(v) if abs(v - round(v)) < 1e-6 else v


def rename_room(d, old, new):
    n = 0
    for r in d.get("rooms", []):
        if r.get("name") == old:
            r["name"] = new
            n += 1
    if not n:
        raise EditError("помещение «%s» не найдено" % old)
    for sec in ("furniture", "openings", "switches", "lighting", "elevations"):
        for it in d.get(sec, []):
            for k in ("room", "group"):
                if it.get(k) == old:
                    it[k] = new
                    n += 1
            for c in it.get("controls", []) if isinstance(it, dict) else []:
                if c.get("group") == old:
                    c["group"] = new
                    n += 1
    for f in d.get("floors", []):
        if old in f.get("rooms", []):
            f["rooms"] = [new if x == old else x for x in f["rooms"]]
            n += 1
    ov = d.get("overrides", {})
    for k in ("tag_pos",):
        if old in ov.get(k, {}):
            ov[k][new] = ov[k].pop(old)
            n += 1
    return n


def apply(d, ops, base_dir="."):
    """Apply a list of operation strings to a copy of d. -> (new data, [messages])"""
    d = copy.deepcopy(d)
    msgs = []
    for op in ops:
        P = _project(d, base_dir)
        m_add = re.match(r"^\s*add\s+(\S+)\s+(.*)$", op, re.S)
        if m_add:                                   # JSON is taken verbatim (quotes intact)
            args = ["add", m_add.group(1), m_add.group(2)]
        else:
            args = [_unq(a) if i < 2 or "=" not in a else a for i, a in enumerate(_tokens(op))]
        if not args:
            continue
        verb = args[0].lower()
        if verb == "rename-room":
            if len(args) != 3:
                raise EditError("rename-room СТАРОЕ НОВОЕ (имя с пробелами - в кавычках)")
            args = [_unq(a) for a in args]
            n = rename_room(d, args[1], args[2])
            msgs.append("помещение «%s» -> «%s» (ссылок обновлено: %d)" % (args[1], args[2], n))
            continue
        if verb == "add":
            if len(args) < 3:
                raise EditError("add РАЗДЕЛ {json}")
            sec = args[1]
            item = _value(args[2])
            if not isinstance(item, dict):
                raise EditError("add %s: нужен объект JSON {...}, получено «%s»" % (sec, args[2][:60]))
            cont = _container(d, sec, create=True)
            if isinstance(cont, dict):
                if not isinstance(item, dict):
                    raise EditError("для %s нужен объект {...}" % sec)
                cont.update(item)
            else:
                cont.append(item)
            msgs.append("%s: добавлено %s" % (NAMES.get(sec, sec), describe(sec, item, P)))
            continue
        if len(args) < 2:
            raise EditError("«%s»: не указан выбор элементов" % op)
        sec, items = select(d, args[1], P)
        if not items:
            raise EditError("«%s»: ничего не найдено (посмотреть: sda.py find project.json '%s')" % (args[1], args[1].split("[")[0]))
        if verb == "set":
            pairs = []
            for kv in args[2:]:
                if "=" not in kv:
                    raise EditError("set: ожидалось key=value, получено «%s»" % kv)
                k, v = kv.split("=", 1)
                pairs.append((k, _value(v) if not (v[:1] == "'" and v[-1:] == "'") else v[1:-1]))
            for key, it in items:
                if sec in ("meta", "levels", "panel"):
                    for k, v in pairs:
                        msgs.append("%s: %s: %s -> %s" % (NAMES.get(sec, sec), k, _short(it.get(k)), _short(v)))
                        it[k] = v
                    continue
                before = describe(sec, it, P)
                for k, v in pairs:
                    if sec == "otypes" and k == "mark":
                        continue
                    if "." in k:                    # nested: controls.0.mode=pass
                        _set_path(it, k, v)
                    else:
                        it[k] = v
                msgs.append("%s: %s -> %s" % (NAMES.get(sec, sec), before, ", ".join("%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in pairs)))
        elif verb == "move":
            if len(args) != 4:
                raise EditError("move ВЫБОР dx dy")
            dx, dy = float(args[2]), float(args[3])
            for key, it in items:
                before = describe(sec, it, P)
                _shift(it, dx, dy, P)
                msgs.append("%s: %s сдвинут на (%s; %s)" % (NAMES.get(sec, sec), before, _f(dx), _f(dy)))
        elif verb in ("del", "delete", "rm"):
            cont = _container(d, sec)
            for key, it in sorted(items, key=lambda kv: kv[0] if kv[0] is not None else 0, reverse=True):
                msgs.append("%s: удалено %s" % (NAMES.get(sec, sec), describe(sec, it, P)))
                if isinstance(cont, dict):
                    cont.pop(key)
                else:
                    cont.pop(key)
        else:
            raise EditError("неизвестная операция «%s» (set, move, del, add, rename-room)" % verb)
    return d, msgs


def _set_path(it, path, v):
    parts = path.split(".")
    cur = it
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur.setdefault(p, {})
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = v
    else:
        cur[last] = v


def _project(d, base_dir):
    try:
        return M.Project(d, base_dir)
    except Exception:
        return None


# ------------------------------------------------------------------ diff
KEYS = {"walls": "id", "openings": "id", "switches": "id", "rooms": "name", "floors": "id", "ctypes": "id",
        "ftypes": "id", "nodes": "num"}
UNKEYED = {"furniture": lambda it: (it.get("name"), it.get("kind")), "lighting": lambda it: (it.get("kind"), it.get("group")),
           "sockets": lambda it: (it.get("kind"),), "plumbing": lambda it: (it.get("kind"), it.get("fixture")),
           "zones": lambda it: (it.get("type"), it.get("name")), "segments": lambda it: (it.get("type"),)}
SKIP = ("proposed",)


def diff(a, b, base_dir="."):
    """Human-readable changes a -> b: [(section, text)] and the sheets they touch. A renamed room is reported once
    (not as every reference that changed with it)."""
    out = []
    ra = {r.get("name"): r for r in a.get("rooms", [])}
    rb = {r.get("name"): r for r in b.get("rooms", [])}
    gone = [n for n in ra if n not in rb]
    new = [n for n in rb if n not in ra]
    ren = {}
    for n in gone:
        for m in new:
            if m not in ren.values() and (ra[n].get("seed") == rb[m].get("seed") and ra[n].get("seed") is not None
                                          or ra[n].get("poly") == rb[m].get("poly") and ra[n].get("poly")):
                ren[n] = m
    if ren:
        a = copy.deepcopy(a)
        for n, m in ren.items():
            rename_room(a, n, m)
            out.append(("rooms", "переименовано: «%s» -> «%s» (все ссылки)" % (n, m)))
    Pa, Pb = _project(a, base_dir), _project(b, base_dir)
    for sec in ("meta", "levels", "walls", "openings", "otypes", "rooms", "separations", "furniture", "lighting", "switches",
                "sockets", "panel", "circuits", "plumbing", "floors", "ctypes", "zones", "ftypes", "segments", "elevations", "nodes"):
        ca, cb = _container(a, sec), _container(b, sec)
        if ca == cb:
            continue
        if sec in ("meta", "levels", "panel") or sec == "otypes":
            ca, cb = ca or {}, cb or {}
            for k in sorted(set(ca) | set(cb)):
                if ca.get(k) != cb.get(k) and k not in SKIP:
                    out.append((sec, "%s: %s -> %s" % (k, _short(ca.get(k)), _short(cb.get(k)))))
            continue
        if sec in ("circuits", "separations"):
            out.append((sec, "изменено (было %d, стало %d)" % (len(ca or []), len(cb or []))))
            continue
        ca, cb = ca or [], cb or []
        if sec in KEYS or sec == "elevations":
            kf = (lambda it: (it.get("group"), it.get("label"))) if sec == "elevations" else (lambda it, k=KEYS[sec]: it.get(k))
            ma = {kf(it): it for it in ca}
            mb = {kf(it): it for it in cb}
            for k in mb:
                if k not in ma:
                    out.append((sec, "добавлено: " + describe(sec, mb[k], Pb)))
            for k in ma:
                if k not in mb:
                    out.append((sec, "удалено: " + describe(sec, ma[k], Pa)))
            for k in ma:
                if k in mb and ma[k] != mb[k]:
                    out.append((sec, "%s: %s" % (describe(sec, mb[k], Pb), _fields(ma[k], mb[k]))))
            continue
        kf = UNKEYED.get(sec, lambda it: ())
        rest_b = list(cb)
        for it in ca:
            if it in rest_b:
                rest_b.remove(it)
                continue
            cand = [x for x in rest_b if kf(x) == kf(it)]
            pa = _anchor(it)
            if cand and pa is not None:
                best = min(cand, key=lambda x: math.hypot(_anchor(x)[0] - pa[0], _anchor(x)[1] - pa[1]) if _anchor(x) else 1e9)
                pb = _anchor(best)
                if pb is not None and math.hypot(pb[0] - pa[0], pb[1] - pa[1]) <= 1500:
                    rest_b.remove(best)
                    out.append((sec, "%s: %s" % (describe(sec, it, Pa), _fields(it, best))))
                    continue
            out.append((sec, "удалено: " + describe(sec, it, Pa)))
        for it in rest_b:
            out.append((sec, "добавлено: " + describe(sec, it, Pb)))
    sheets = sorted(set(SHEETS.get(s, s) for s, _ in out))
    return out, sheets


def _fields(x, y):
    parts = []
    for k in sorted(set(x) | set(y)):
        if k in SKIP or x.get(k) == y.get(k):
            continue
        if k in ("x", "y") and "x" in x and "x" in y:
            if k == "y" and x.get("x") != y.get("x"):
                continue
            parts.append("положение (%s; %s) -> (%s; %s)" % (_f(x["x"]), _f(x["y"]), _f(y["x"]), _f(y["y"])))
            continue
        parts.append("%s %s -> %s" % (k, _short(x.get(k)), _short(y.get(k))))
    return "; ".join(parts) or "изменено"


def _short(v, n=60):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n - 1] + "…"


def print_diff(changes, sheets):
    if not changes:
        print("изменений нет")
        return
    cur = None
    for sec, txt in changes:
        if sec != cur:
            print("%s:" % NAMES.get(sec, sec))
            cur = sec
        print("  - " + txt)
    print("Затронутые листы: " + "; ".join(sheets))
