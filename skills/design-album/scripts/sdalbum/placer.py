# -*- coding: utf-8 -*-
"""Collision-aware placement of texts and symbols (model units of one drawing block).

Every sheet block owns an Occ registry. Everything that must not be covered by text (walls,
symbols, already placed texts, dimension texts) is registered; labels try candidate positions
in order and take the first free one. QA (qa.py) verifies the final result independently.
"""
import math
from shapely.geometry import box, Point, Polygon
from shapely import affinity
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import gfx as S

ALIGN = {
    "LEFT": 0.0, "CENTER": 0.5, "RIGHT": 1.0, "MIDDLE": 0.5,
}


def text_geom(s, p, h, align="MIDDLE_CENTER", rot=0.0, bold=False, pad=0.0):
    """Rectangle covered by a single-line text (cap height h), incl. descenders; optional padding."""
    w = S.tw(s, h, bold)
    v, hz = align.split("_") if "_" in align else ("MIDDLE", align)
    fx = {"LEFT": 0.0, "CENTER": 0.5, "MIDDLE": 0.5, "RIGHT": 1.0}[hz]
    if v == "BOTTOM":
        y0, y1 = -0.28 * h, 1.3 * h
    elif v == "TOP":
        y0, y1 = -1.3 * h, 0.0
    else:
        y0, y1 = -0.76 * h, 0.62 * h
    x0 = -fx * w
    g = box(x0 - pad, y0 - pad, x0 + w + pad, y1 + pad)
    if rot:
        g = affinity.rotate(g, rot, origin=(0, 0))
    return affinity.translate(g, p[0], p[1])


_PENDING = []
HINTS = {}          # block offset -> [geometry]: obstacles learnt from the sheet QA of a previous build (self-healing)
CUR_BLOCK = None    # offset of the block being drawn (set by Album.model_block)


def flush_all():
    """Draw deferred (masked) labels of every registry created since the last flush. Masked labels go on top of
    everything else in their block, so lines drawn after placement (extension lines, wiring) never cross them."""
    while _PENDING:
        o = _PENDING.pop(0)
        o.flush()


class Occ:
    def __init__(self):
        self.geoms = []
        self.kinds = []
        self._tree = None
        self.late = []
        _PENDING.append(self)
        self.block = CUR_BLOCK
        self.bounds = None          # model window shown in the viewport: nothing may be placed outside it
        for g in HINTS.get(CUR_BLOCK, []):
            self.add(g, "hint")

    def defer(self, fn):
        self.late.append(fn)

    def flush(self):
        for fn in self.late:
            fn()
        self.late = []

    def add(self, g, kind="x"):
        if g is None or g.is_empty:
            return
        self.geoms.append(g)
        self.kinds.append(kind)
        self._tree = None

    def tree(self):
        if self._tree is None and self.geoms:
            self._tree = STRtree(self.geoms)
        return self._tree

    def overlap(self, g, ignore=()):
        a = 0.0
        if self.bounds is not None and not self.bounds.contains(g):
            a += 1e4 + 1e3 * g.difference(self.bounds).area     # would be clipped by the viewport (CONTENT_CLIPPED)
        t = self.tree()
        if t is None:
            return a
        for j in t.query(g):
            j = int(j)
            if self.kinds[j] in ignore:
                continue
            gg = self.geoms[j]
            if gg.intersects(g):
                a += g.intersection(gg).area
        return a

    def free(self, g, ignore=(), tol=1.0):
        return self.overlap(g, ignore) <= tol


def place_text(sp, occ, s, candidates, h, align="MIDDLE_CENTER", rot=0.0, bold=False, rgb=None, layer="SD_Текст",
               pad=None, within=None, mask=False, kind="text", ignore=(), force=True):
    """Try candidate insertion points; draw at the first free one (or the least bad if force).
    candidates: list of (x, y) or (x, y, rot, align). Returns (point, geom) or None."""
    pad = 0.18 * h if pad is None else pad
    best = None
    for c in candidates:
        p = (c[0], c[1])
        r = c[2] if len(c) > 2 and c[2] is not None else rot
        al = c[3] if len(c) > 3 and c[3] else align
        g = text_geom(s, p, h, al, r, bold, pad)
        if within is not None and not within.contains(g):
            score = 1e9 + g.difference(within).area
        else:
            score = occ.overlap(g, ignore)
        if score <= 1e-6:
            best = (0, p, r, al, g)
            break
        if best is None or score < best[0]:
            best = (score, p, r, al, g)
    if best is None or (best[0] > 0 and not force):
        return None
    _, p, r, al, g = best
    if mask:
        def draw(sp=sp, g=g, s=s, p=p, h=h, al=al, layer=layer, r=r, bold=bold, rgb=rgb):
            S.fill(sp, g, (255, 255, 255), layer)
            S.text(sp, s, p, h, al, layer, rot=r, bold=bold, rgb=rgb)
        occ.defer(draw)
    else:
        S.text(sp, s, p, h, al, layer, rot=r, bold=bold, rgb=rgb)
    occ.add(g, kind)
    return p, g, best[0]


def ring_candidates(p, dists, n=16, start=0.0):
    out = []
    for d in dists:
        for i in range(n):
            a = start + 2 * math.pi * i / n
            out.append((p[0] + d * math.cos(a), p[1] + d * math.sin(a)))
    return out


def grid_candidates(poly, step, center=None):
    x0, y0, x1, y1 = poly.bounds
    pts = []
    yy = y0 + step / 2
    while yy < y1:
        xx = x0 + step / 2
        while xx < x1:
            if poly.contains(Point(xx, yy)):
                pts.append((xx, yy))
            xx += step
        yy += step
    if center is None:
        try:
            from shapely.ops import polylabel
            c = polylabel(poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area), 5)
            center = (c.x, c.y)
        except Exception:
            c = poly.representative_point()
            center = (c.x, c.y)
    pts.sort(key=lambda q: (q[0] - center[0]) ** 2 + (q[1] - center[1]) ** 2)
    return [center] + pts


def free_area(region, occ, kinds=None, buffer_=0.0):
    obs = [g for g, k in zip(occ.geoms, occ.kinds) if kinds is None or k in kinds]
    if not obs:
        return region
    return region.difference(unary_union(obs).buffer(buffer_))
