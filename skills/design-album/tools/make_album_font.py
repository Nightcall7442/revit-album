# -*- coding: utf-8 -*-
"""Build assets/fonts/osifont-gost.ttf - the lettering of the album (upright narrow, as GOSTCommon of the reference album).

    python3 make_album_font.py <osifont-lgpl3fe.ttf> <out.ttf>

Source: https://github.com/hikikomori82/osifont (LGPL-3 with the font exception). Steps:
  1. glyphs that are placeholder rectangles in the source are rebuilt: Ё / ё from Latin Ë / ë, Э - Є mirrored;
  2. every glyph is narrowed to 0.87 (slant SLANT, 0 - upright), side bearings recomputed;
  3. overlapping contours merged (Ø, ø: a ring crossed by a stroke rendered as a solid blot) - needs skia-pathops;
  4. family renamed «osifont GOST».
"""
import math
import sys

from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

SLANT, NARROW = 0.0, 0.87         # upright and narrow, as GOSTCommon of the reference album (measured on its text)


def is_placeholder(gs, name):
    p = RecordingPen()
    gs[name].draw(p)
    v = p.value
    if len(v) < 5 or v[0][0] != "moveTo" or [x[0] for x in v[1:5]] != ["lineTo", "lineTo", "lineTo", "closePath"]:
        return False
    pts = [v[0][1][0]] + [x[1][0] for x in v[1:4]]
    return max(y for _, y in pts) - min(y for _, y in pts) > 1000


def _slashed(f, name, base):
    """Glyph `name` = glyph `base` with a diagonal stroke through it, as one clean outline."""
    import pathops
    gs = f.getGlyphSet()
    glyf, hmtx = f["glyf"], f["hmtx"]
    ring = pathops.Path()
    gs[base].draw(ring.getPen())
    xmin, ymin, xmax, ymax = ring.bounds
    t = 0.09 * (ymax - ymin)                           # stroke width as of the letters
    ext = 0.12 * (ymax - ymin)
    a, b = (xmin - ext * 0.6, ymin - ext), (xmax + ext * 0.6, ymax + ext)
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / L * t / 2.0, dx / L * t / 2.0
    stroke = pathops.Path()
    pen = stroke.getPen()
    pen.moveTo((a[0] + nx, a[1] + ny))
    pen.lineTo((a[0] - nx, a[1] - ny))
    pen.lineTo((b[0] - nx, b[1] - ny))
    pen.lineTo((b[0] + nx, b[1] + ny))
    pen.closePath()
    # no overlapping contours (renderers that nest contours by containment fill a crossed ring solid):
    # the ring of the base letter as it is + the stroke inside the counter (an island) + the stroke ends outside
    from fontTools.pens.recordingPen import RecordingPen
    rec = RecordingPen()
    gs[base].draw(rec)
    contours, cur = [], []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(cur)
            cur = []

    def path_of(c):
        p = pathops.Path()
        pen_ = p.getPen()
        for op, args in c:
            getattr(pen_, op)(*args)
        return p
    paths = sorted((path_of(c) for c in contours), key=lambda p: -(p.bounds[2] - p.bounds[0]))
    outer, counter = paths[0], paths[1]
    inside = pathops.op(stroke, counter, pathops.PathOp.INTERSECTION)
    ends = pathops.op(stroke, outer, pathops.PathOp.DIFFERENCE)
    tt = TTGlyphPen(None)
    for c in contours:
        for op, args in c:
            getattr(tt, op)(*args)
    from fontTools.pens.reverseContourPen import ReverseContourPen
    ref = path_of(contours[0])
    for part in (inside, ends):
        part.draw(ReverseContourPen(tt) if ref.clockwise != part.clockwise else tt)
    glyf[name] = tt.glyph()
    hmtx[name] = (hmtx[base][0], 0)


def _ellipsis(f):
    from fontTools.pens.transformPen import TransformPen as _TP
    gs = f.getGlyphSet()
    cm = f.getBestCmap()
    per = cm[ord(".")]
    w = f["hmtx"][per][0]
    pen = TTGlyphPen(gs)
    for i in range(3):
        gs[per].draw(_TP(pen, (1, 0, 0, 1, i * w, 0)))
    name = "ellipsis"
    f["glyf"][name] = pen.glyph()
    f["hmtx"][name] = (3 * w, 0)
    order = f.getGlyphOrder()
    if name not in order:
        f.setGlyphOrder(order + [name])
    for t in f["cmap"].tables:
        if t.isUnicode():
            t.cmap[0x2026] = name
    f["maxp"].numGlyphs = len(f.getGlyphOrder())


def main(src, dst):
    f = TTFont(src)
    gs = f.getGlyphSet()
    glyf, hmtx, cm = f["glyf"], f["hmtx"], f.getBestCmap()
    fixes = {"Ё": ("Ë", None), "ё": ("ë", None), "Э": ("Є", "mirror")}
    new = {}
    for ch, (from_ch, how) in fixes.items():
        name, base = cm[ord(ch)], cm[ord(from_ch)]
        if not is_placeholder(gs, name):
            continue
        pen = TTGlyphPen(gs)
        w = hmtx[base][0]
        m = (-1, 0, 0, 1, w, 0) if how == "mirror" else (1, 0, 0, 1, 0, 0)
        gs[base].draw(TransformPen(pen, m))
        g = pen.glyph()
        if how == "mirror":                          # a mirrored outline runs the other way round
            from fontTools.pens.reverseContourPen import ReverseContourPen
            pen2 = TTGlyphPen(gs)
            gs[base].draw(TransformPen(ReverseContourPen(pen2), m))
            g = pen2.glyph()
        new[name] = (g, w)
    for name, (g, w) in new.items():
        glyf[name] = g
        hmtx[name] = (w, 0)
    for ch, base in (("Ø", "O"), ("ø", "o")):      # source: the ring and the stroke wound so that the ring fills
        _slashed(f, cm[ord(ch)], cm[ord(base)])
    if 0x2026 not in cm:                           # «…» (the typography of the album writes it): three periods
        _ellipsis(f)
    gs = f.getGlyphSet()
    sk = math.tan(math.radians(SLANT))
    out = {}
    for name in f.getGlyphOrder():
        pen = TTGlyphPen(gs)
        gs[name].draw(TransformPen(pen, (NARROW, 0, sk, 1, 0, 0)))
        out[name] = pen.glyph()
    for name, g in out.items():
        glyf[name] = g
        g.recalcBounds(glyf)
        w, _ = hmtx[name]
        hmtx[name] = (round(w * NARROW), g.xMin if g.numberOfContours else 0)
    from fontTools.ttLib.removeOverlaps import removeOverlaps
    removeOverlaps(f)
    for name in f.getGlyphOrder():
        g = glyf[name]
        g.recalcBounds(glyf)
        hmtx[name] = (hmtx[name][0], g.xMin if g.numberOfContours else 0)
    for rec in f["name"].names:
        s = rec.toUnicode()
        if rec.nameID in (1, 3, 4, 16):
            rec.string = s.replace("osifont", "osifont GOST")
        if rec.nameID == 6:
            rec.string = s.replace("osifont", "osifontGOST")
    f["post"].italicAngle = -SLANT
    if SLANT:
        f["OS/2"].fsSelection = (f["OS/2"].fsSelection | 1) & ~(1 << 6)
        f["head"].macStyle |= 2
    f["hhea"].advanceWidthMax = max(w for w, _ in hmtx.metrics.values())
    f.save(dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
