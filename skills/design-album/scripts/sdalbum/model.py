# -*- coding: utf-8 -*-
"""Project model: loads project.json (single source of truth) and derives the geometry every sheet needs.

Units: millimetres. Plan: x to the right, y up. Heights from finished floor (±0.000).
See references/project-schema.md for the full format.
"""
import json
import math
import os
from shapely.geometry import Polygon, box, LineString, Point, MultiPolygon
from shapely.ops import unary_union

WET = ("wet",)


def _poly(p):
    return Polygon(p).buffer(0)


def fmt_area(a, nd=2):
    return ("%.*f" % (nd, a)).replace(".", ",")


def fmt_len(v):
    return "%d" % round(v)


class Project:
    def __init__(self, data, base_dir="."):
        self.d = data
        self.base_dir = base_dir
        self.meta = data.get("meta", {})
        lv = data.get("levels", {})
        self.slab = lv.get("slab", 3000)
        self.ceiling = lv.get("ceiling", 2700)
        self.walls = [self._norm_wall(w) for w in data.get("walls", [])]
        self.wall_by_id = {w["id"]: w for w in self.walls}
        self.openings = [self._norm_opening(o) for o in data.get("openings", [])]
        self.opening_types = data.get("opening_types", {})
        self.separations = [tuple(map(tuple, s)) for s in data.get("separations", [])]
        self.grid = data.get("grid", {"x": [], "y": []})
        self.furniture = data.get("furniture", [])
        self.lighting = data.get("lighting", [])
        self.switches = data.get("switches", [])
        self.sockets = data.get("sockets", [])
        self.panel = data.get("panel")
        self.circuits = data.get("circuits", [])
        self.plumbing = data.get("plumbing", [])
        self.floors = data.get("floors", [])
        self.ceilings = data.get("ceilings", {})
        self.finishes = data.get("finishes", {})
        self.elevations = data.get("elevations", [])
        self.nodes = data.get("nodes", [])
        self.overrides = data.get("overrides", {})
        self.notes = data.get("notes", {})
        self._derive()

    # ------------------------------------------------------------------ normalisation
    def _norm_wall(self, w):
        w = dict(w)
        w.setdefault("kind", "existing")          # existing | new | box
        if "rect" in w and w["rect"]:
            x0, y0, x1, y1 = w["rect"]
            w["shape"] = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        elif "poly" in w:
            w["shape"] = _poly(w["poly"])
        elif "a" in w and "b" in w and "t" in w:
            ln = LineString([w["a"], w["b"]])
            w["shape"] = ln.buffer(w["t"] / 2.0, cap_style=2, join_style=2)
        else:
            raise ValueError("wall %s: need rect | poly | a,b,t" % w.get("id"))
        x0, y0, x1, y1 = w["shape"].bounds
        w["dir"] = "H" if (x1 - x0) >= (y1 - y0) else "V"
        w.setdefault("t", round(min(x1 - x0, y1 - y0)))
        if "a" not in w or "b" not in w:
            if w["dir"] == "H":
                cy = (y0 + y1) / 2.0
                w["a"], w["b"] = [x0, cy], [x1, cy]
            else:
                cx = (x0 + x1) / 2.0
                w["a"], w["b"] = [cx, y0], [cx, y1]
        w.setdefault("h", self.slab if w["kind"] != "box" else 1200)
        return w

    def _norm_opening(self, o):
        o = dict(o)
        o.setdefault("kind", "door")              # window | door | balcony | passage
        o.setdefault("h", 2100 if o["kind"] != "window" else 1500)
        o.setdefault("sill", 0 if o["kind"] != "window" else 900)
        return o

    def opening_rect(self, o):
        w = self.wall_by_id[o["wall"]]
        x0, y0, x1, y1 = w["shape"].bounds
        if w["dir"] == "H":
            return (o["c"] - o["w"] / 2.0, y0, o["c"] + o["w"] / 2.0, y1)
        return (x0, o["c"] - o["w"] / 2.0, x1, o["c"] + o["w"] / 2.0)

    # ------------------------------------------------------------------ derived geometry
    def _derive(self):
        self.open_shape = {o["id"]: box(*self.opening_rect(o)) for o in self.openings}
        struct = [w for w in self.walls if w["kind"] == "existing"]
        newp = [w for w in self.walls if w["kind"] == "new"]
        self.boxes = [w for w in self.walls if w["kind"] == "box"]
        cut_ex = unary_union([self.open_shape[o["id"]] for o in self.openings if self.wall_by_id[o["wall"]]["kind"] == "existing"] or [Polygon()])
        self.shell = unary_union([w["shape"] for w in struct]) if struct else Polygon()
        self.shell_cut = self.shell.difference(cut_ex)
        self.parts = {}
        for w in newp:
            cut = unary_union([self.open_shape[o["id"]] for o in self.openings if o["wall"] == w["id"]] or [Polygon()])
            self.parts[w["id"]] = w["shape"].difference(cut)
        self.mass = unary_union([w["shape"] for w in self.walls if w["kind"] != "box"])
        self.bounds = self.mass.bounds
        self.rooms = self._rooms()
        self.room_by_name = {r["name"]: r for r in self.rooms}

    def _rooms(self):
        spec = self.d.get("rooms", [])
        if not spec:
            return []
        mass = self.mass
        if hasattr(mass, "geoms"):
            outer = unary_union([Polygon(g.exterior) for g in mass.geoms])
        else:
            outer = Polygon(mass.exterior)
        interior = outer.difference(mass)
        # a gap between two bearing walls (passage without a door) belongs to no room: room areas are measured in
        # the clear between finished wall faces (lesson L-031); separations still split open-plan spaces
        self.passages = self.throats() if any(w["kind"] == "existing" for w in self.walls) else []
        if self.passages:
            interior = interior.difference(unary_union(self.passages))
        pieces = list(interior.geoms) if hasattr(interior, "geoms") else [interior]
        for (a, b) in self.separations:
            new = []
            for p in pieces:
                parts = p.difference(LineString([a, b]).buffer(0.5, cap_style=2))
                new.extend(list(parts.geoms) if hasattr(parts, "geoms") else [parts])
            pieces = new
        pieces = [p for p in pieces if p.area > 2e5]
        out = []
        for i, r in enumerate(spec):
            r = dict(r)
            r.setdefault("num", str(i + 1))
            if r.get("poly"):
                poly = _poly(r["poly"])
            else:
                hit = [p for p in pieces if p.contains(Point(r["seed"]))]
                if len(hit) != 1:
                    raise ValueError("room %s: seed %s hits %d regions (check walls/separations)" % (r["name"], r["seed"], len(hit)))
                poly = hit[0]
                coords = [(round(x), round(y)) for x, y in poly.exterior.coords]
                poly = Polygon(coords).buffer(0)
            r["shp"] = poly
            r["area"] = round(poly.area / 1e6, 2)
            r["area_exact"] = poly.area / 1e6
            r["perimeter"] = poly.length / 1000.0
            r.setdefault("cls", "living")
            out.append(r)
        return out

    # ------------------------------------------------------------------ helpers
    def room_of_point(self, p, tol=60):
        """Room containing p, or the nearest one within tol (a point on a wall face belongs to the room it faces;
        the old version returned the first room in the list for boundary points - lesson L-034)."""
        pt = Point(p)
        best = None
        for r in self.rooms:
            d = r["shp"].distance(pt)
            if d <= tol and (best is None or d < best[0]):
                best = (d, r)
        return best[1] if best else None

    def inward_normal(self, p, room=None):
        r = room or self.room_of_point(p)
        if r is None:
            return (0, 1), (p, p)
        cs = list(r["shp"].exterior.coords)
        best = None
        for i in range(len(cs) - 1):
            d = LineString([cs[i], cs[i + 1]]).distance(Point(p))
            if best is None or d < best[0]:
                best = (d, cs[i], cs[i + 1])
        _, a, b = best
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        n1 = (-dy / L, dx / L)
        if not r["shp"].contains(Point(p[0] + n1[0] * 50, p[1] + n1[1] * 50)):
            n1 = (-n1[0], -n1[1])
        return n1, (a, b)

    def outline(self):
        m = self.mass
        g = unary_union([Polygon(x.exterior) for x in m.geoms]) if hasattr(m, "geoms") else Polygon(m.exterior)
        return g.simplify(1.0, preserve_topology=True)

    def throats(self, max_gap=2600):
        """Gaps between existing walls (passages without a wall): a free wall end that faces another
        existing wall within max_gap. Returns rectangles spanning the gap."""
        cuts = []
        outline = self.outline()

        exist = [w for w in self.walls if w["kind"] == "existing"]

        def column(w):                               # a free-standing column: no passage "between" columns
            x0, y0, x1, y1 = w["shape"].bounds
            if max(x1 - x0, y1 - y0) > 1.6 * min(x1 - x0, y1 - y0):
                return False
            near = w["shape"].buffer(5)
            return not any(v is not w and near.intersects(v["shape"]) for v in exist)
        runs = unary_union([w["shape"] for w in self.walls if w["kind"] == "existing" and not column(w)] or [Polygon()])
        for w in self.walls:
            if w["kind"] != "existing" or column(w):
                continue
            g = w["shape"]
            gx0, gy0, gx1, gy1 = g.bounds
            if min(gx1 - gx0, gy1 - gy0) < 150:
                continue                              # a partition stub (WC cubicle divider) ends in a room, not a passage
            x0, y0, x1, y1 = g.bounds
            ends = [((x0, x1), y1, 1), ((x0, x1), y0, -1)] if w["dir"] == "V" else [((y0, y1), x1, 1), ((y0, y1), x0, -1)]
            for (a, b), c, sgn in ends:
                if w["dir"] == "V":
                    probe = Point((a + b) / 2.0, c + sgn * 5)
                    ray = box(a + 1, min(c, c + sgn * max_gap), b - 1, max(c, c + sgn * max_gap))
                else:
                    probe = Point(c + sgn * 5, (a + b) / 2.0)
                    ray = box(min(c, c + sgn * max_gap), a + 1, max(c, c + sgn * max_gap), b - 1)
                if self.shell.contains(probe):
                    continue
                hit = ray.intersection(self.shell.difference(g.buffer(0.5)))
                hit_run = ray.intersection(runs.difference(g.buffer(0.5)))
                if hit.is_empty or hit.area < 1 or hit_run.is_empty or hit_run.area < 1:
                    continue
                pc = Point(probe.x - sgn * 5, probe.y) if w["dir"] != "V" else Point(probe.x, probe.y - sgn * 5)
                if hit.distance(pc) < hit_run.distance(pc) - 1:
                    continue                          # a column stands first: the space between is a hall, not a passage
                hb = hit.bounds
                if w["dir"] == "V":
                    d = (hb[1] - c) if sgn > 0 else (c - hb[3])
                    cut = box(a, min(c, c + sgn * d), b, max(c, c + sgn * d))
                else:
                    d = (hb[0] - c) if sgn > 0 else (c - hb[2])
                    cut = box(min(c, c + sgn * d), a, max(c, c + sgn * d), b)
                if d < 50 or cut.difference(outline).area > 0.05 * cut.area:
                    continue
                cx0, cy0, cx1, cy1 = cut.bounds          # a passage has room on both sides; a niche has a back wall
                mid = ((cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0)
                sides = [Point(cx0 - 30, mid[1]), Point(cx1 + 30, mid[1])] if w["dir"] == "V" else \
                    [Point(mid[0], cy0 - 30), Point(mid[0], cy1 + 30)]
                if any(self.mass.contains(q) for q in sides):
                    continue
                if any(cut.buffer(1).contains(q) or q.buffer(1).contains(cut) for q in cuts):
                    continue
                cuts.append(cut)
        return cuts

    def existing_spaces(self, min_area=1.0e6):
        """Spaces of the existing shell (inside the outline, between bearing walls), split at wall gaps.
        Returns [(polygon, [rooms inside])]."""
        sp = self.outline().difference(self.shell)
        cuts = self.throats()
        if cuts:
            sp = sp.difference(unary_union(cuts).buffer(0.5))
        pieces = [g for g in (sp.geoms if hasattr(sp, "geoms") else [sp]) if g.area >= min_area]
        out = []
        from shapely.ops import polylabel
        for g in sorted(pieces, key=lambda q: (round(q.bounds[0] / 100), q.bounds[1])):
            rooms = []
            for r in self.rooms:
                c = polylabel(r["shp"], 10)
                if g.contains(c):
                    rooms.append(r)
            out.append((g, rooms))
        return out

    def door_hand(self, o):
        """'L' / 'R' per GOST 475: hinges on the left / right when viewed from the side the leaf opens to.
        None for windows / passages or when swing is not given."""
        if o["kind"] not in ("door", "balcony") or not o.get("swing"):
            return None
        w = self.wall_by_id[o["wall"]]
        sw = o["swing"]
        u = (1.0, 0.0) if w["dir"] == "H" else (0.0, 1.0)
        hd = (-u[0], -u[1]) if o.get("hinge", "min") == "min" else u
        left = (sw[1], -sw[0])                     # viewer stands on the swing side looking at the door
        return "L" if hd[0] * left[0] + hd[1] * left[1] > 0 else "R"

    def wet_rooms(self):
        return [r for r in self.rooms if r.get("cls") == "wet"]

    def total_area(self):
        """Total as printed: the sum of the rounded room areas (a column must add up, lesson L-025)."""
        return round(sum(r["area"] for r in self.rooms), 2)

    def open_edges(self):
        """Lines where a room has no wall: separations + faces of passages (for wall areas, finish strips)."""
        out = [LineString(s) for s in self.separations]
        for g in getattr(self, "passages", []):
            out.append(g.exterior)
        return out

    def floor_zones(self):
        """[(floor_type dict, shapely geometry)] — explicit polys or union of the rooms listed.
        Explicit polys (often taken from 3D-model floor slabs) are clipped to rooms + door thresholds: a floor
        never runs under walls or into window reveals."""
        if getattr(self, "_fz", None) is not None:
            return self._fz
        out = []
        lim = unary_union([r["shp"] for r in self.rooms] + list(getattr(self, "passages", [])) +
                          [self.open_shape[o["id"]] for o in self.openings if o["kind"] in ("door", "balcony", "passage")])
        for f in self.floors:
            if f.get("polys"):
                g = unary_union([_poly(p) for p in f["polys"]])
                if self.rooms:
                    g = g.intersection(lim)
            else:
                g = unary_union([self.room_by_name[n]["shp"] for n in f.get("rooms", []) if n in self.room_by_name])
            out.append((f, g))
        # a zone with its own outline (a strip of other tiles) lies over the zones taken by rooms; a later outline over
        # an earlier one; boxes and counter frames standing on the floor are not covered
        res = []
        for i, (f, g) in enumerate(out):
            over = [g2 for j, (f2, g2) in enumerate(out) if j != i and f2.get("polys") and (not f.get("polys") or j > i)]
            if over:
                g = g.difference(unary_union(over))
            res.append((f, g))
        stand = [b["shape"] for b in self.boxes if b.get("z0", 0) <= 0]
        if stand:
            cut = unary_union(stand)
            res = [(f, g.difference(cut)) for f, g in res]
        self._fz = res
        return res

    def floor_of_room(self, name):
        for f in self.floors:
            if name in f.get("rooms", []):
                return f
        best = None
        for f, g in self.floor_zones():
            a = g.intersection(self.room_by_name[name]["shp"]).area
            if best is None or a > best[0]:
                best = (a, f)
        return best[1] if best and best[0] > 0 else None


def load(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return Project(data, os.path.dirname(os.path.abspath(path)))
