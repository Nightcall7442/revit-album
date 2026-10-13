# -*- coding: utf-8 -*-
"""Geometry helpers for importers."""
from shapely.geometry import LineString, Polygon
from shapely.ops import split


def decompose(g, limit=200):
    """Polygon(s) with holes -> hole-free pieces with the same union (a wall poché around rooms is one polygon with
    holes; project.json walls are simple polygons). Cuts through every hole until none is left."""
    todo = list(g.geoms) if hasattr(g, "geoms") else [g]
    out = []
    n = 0
    while todo and n < limit:
        n += 1
        p = todo.pop()
        if p.is_empty:
            continue
        if not p.interiors:
            out.append(Polygon(p.exterior))
            continue
        h = p.interiors[0]
        hx0, hy0, hx1, hy1 = Polygon(h).bounds
        x0, y0, x1, y1 = p.bounds
        cx = (hx0 + hx1) / 2.0
        cut = LineString([(cx, y0 - 10), (cx, y1 + 10)])
        parts = split(p, cut)
        pieces = [q for q in parts.geoms if q.area > 1.0]
        if len(pieces) < 2:
            cy = (hy0 + hy1) / 2.0
            parts = split(p, LineString([(x0 - 10, cy), (x1 + 10, cy)]))
            pieces = [q for q in parts.geoms if q.area > 1.0]
        if len(pieces) < 2:
            out.append(Polygon(p.exterior).difference(Polygon(h)))
            continue
        todo.extend(pieces)
    return [q for q in out if q.area > 1.0]


def even_odd(polys):
    g = None
    for p in polys:
        p = p.buffer(0)
        if p.is_empty:
            continue
        g = p if g is None else g.symmetric_difference(p)
    return g
