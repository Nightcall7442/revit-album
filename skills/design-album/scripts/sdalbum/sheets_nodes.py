"""«Узлы и сечения» (sheet 3 of the reference album): the floor build-ups («пироги») of every floor type, the joint of
two floor finishes under a door leaf and the heights assumed in the design (rough floor, ±0,000, ceiling, slab)."""
import re

from shapely.geometry import Point

from . import gfx as S
from . import symbols as Y
from . import dims as DM

PIE_K = 5           # build-ups and the joint: 1:5
LEVELS_K = 30       # heights: 1:30
SLAB_T = 60.0       # the slab drawn under a build-up (broken off)

# kind: (keywords, default thickness mm, fill rgb, hatch pattern | None, hatch scale)
KINDS = [
    ("tile", ("керамогран", "плитк", "керамич", "камень", "мрамор"), 10, (250, 250, 250), "ANSI37", 0.4),
    ("wood", ("доск", "паркет", "ламинат", "массив", "шпон"), 15, (226, 205, 170), "ANSI31", 0.4),
    ("vinyl", ("кварцвинил", "spc", "lvt", "винил"), 5, (215, 215, 205), None, 0),
    ("carpet", ("ковролин", "ковров"), 8, (210, 200, 190), "DOTS", 0.3),
    ("glue", ("клей",), 5, (245, 245, 245), None, 0),
    ("under", ("подложк",), 3, (200, 210, 225), None, 0),
    ("membrane", ("гидроизол",), 2, (120, 140, 170), None, 0),
    ("heat", ("тёплый пол", "теплый пол", "мат ", "кабель"), 4, (235, 190, 180), None, 0),
    ("screed", ("стяжк", "цпс", "наливн", "ровнител"), 50, (236, 236, 236), "AR-CONC", 0.02),
    ("insul", ("утепл", "пенопол", "экструд", "шумоиз", "звукоиз"), 30, (240, 235, 200), "ANSI37", 0.8),
]


def _kind(name):
    s = name.lower()
    for kd, keys, t, *_ in KINDS:
        if any(k in s for k in keys):
            return kd
    return "other"


def _spec(kd):
    for k_, keys, t, rgb, pat, sc in KINDS:
        if k_ == kd:
            return t, rgb, pat, sc
    return 10, (240, 240, 240), None, 0


def parse_layers(f):
    """[(label, thickness mm, kind, measured?)] top-down from floor["layers"] («Паркетная доска 14 мм; подложка 3 мм;
    стяжка ЦПС М150 (по факту)») - or from the material when no layers are given."""
    src = f.get("layers")
    parts = [p.strip() for p in re.split(r"[;\n]", src) if p.strip()] if isinstance(src, str) else \
        [str(p).strip() for p in (src or []) if str(p).strip()]
    if not parts:
        mat = f.get("material", "Покрытие")
        kd = _kind(mat)
        parts = [mat] + (["Клей плиточный, 5-7 мм"] if kd == "tile" else ["Подложка 3 мм"] if kd == "wood" else []) + \
            ["Стяжка (толщину уточнить)"]
    out = []
    for p in parts:
        m = re.search(r"(\d+(?:[.,]\d+)?)(?:\s*[-–]\s*(\d+(?:[.,]\d+)?))?\s*мм", p)
        kd = _kind(p)
        if m:
            a = float(m.group(1).replace(",", "."))
            b = float(m.group(2).replace(",", ".")) if m.group(2) else a
            t, known = (a + b) / 2.0, True
        else:
            t, known = float(_spec(kd)[0]), False
        lab = p[0].upper() + p[1:]
        if not known and kd == "screed" and "уточн" not in lab:
            lab += " (толщину уточнить)"
        out.append((lab, t, kd, known))
    return out


def pie_thickness(f):
    return sum(t for _, t, _, _ in parse_layers(f))


def _short(f):
    mat = (f.get("material") or f.get("id", "")).split("«")[0].split(",")[0].strip()
    return mat[:1].lower() + mat[1:] if mat else "покрытием"


def _break_line(sp, x0, x1, y, k):
    """A break line (GOST) across the cut of the slab."""
    m = (x0 + x1) / 2.0
    a = 1.2 * k
    S.poly(sp, [(x0 - a, y), (m - a, y), (m - a / 2, y + a), (m + a / 2, y - a), (m + a, y), (x1 + a, y)],
           "SD_Тонкие", False, (40, 40, 40), 18)


def _layer(sp, x0, x1, y0, y1, kd, k):
    t, rgb, pat, sc = _spec(kd)
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    S.fill(sp, pts, rgb, "SD_Штриховка")
    if pat and (y1 - y0) >= 4:
        try:
            S.hatch(sp, pts, (150, 150, 150), pat, scale=sc * k)
        except Exception:
            pass
    S.poly(sp, pts, "SD_Тонкие", True, (40, 40, 40), 25)


def _slab(sp, x0, x1, y_top, k):
    pts = [(x0, y_top - SLAB_T), (x1, y_top - SLAB_T), (x1, y_top), (x0, y_top)]
    S.fill(sp, pts, (120, 120, 124), "SD_Штриховка")
    S.poly(sp, pts, "SD_Стены", True, (40, 40, 40), 35)


def _labels(sp, items, x_from, x_text, k, h=2.0):
    """Leaders from points of the layers to the labels on shelves at x_text, top-down without overlap."""
    step = h * 1.9 * k
    ys = []
    for _, (px, py) in items:
        y = py if not ys else min(py, ys[-1] - step)
        ys.append(y)
    for (lab, (px, py)), y in zip(items, ys):
        S.line(sp, (px, py), (x_text, y), "SD_Тонкие", (40, 40, 40), 13)
        S.fill(sp, Point(px, py).buffer(0.35 * k, 10), (40, 40, 40), "SD_Тонкие")
        w = S.tw(lab, h * k)
        S.line(sp, (x_text, y), (x_text + w + 0.6 * k, y), "SD_Тонкие", (40, 40, 40), 13)
        S.text(sp, lab, (x_text + 0.3 * k, y + 0.4 * k), h * k, "BOTTOM_LEFT", "SD_Текст")
    return min(ys) if ys else 0.0, max(S.tw(l, h * k) for l, _ in items) if items else 0.0


def draw_pie(sp, f, k=PIE_K, W=260.0):
    """The build-up of a floor type at 1:k, the finish at ±0; returns the model window."""
    lay = parse_layers(f)
    y = 0.0
    pts = []
    for lab, t, kd, _ in lay:
        _layer(sp, 0.0, W, y - t, y, kd, k)
        pts.append((lab, (W * 0.78, y - t / 2.0)))
        y -= t
    _slab(sp, 0.0, W, y, k)
    _break_line(sp, 0.0, W, y - SLAB_T, k)
    pts.append(("Перекрытие", (W * 0.78, y - SLAB_T / 2.0)))
    low, tw = _labels(sp, pts, W * 0.78, W + 40.0, k)
    return (-20.0, min(y - SLAB_T, low) - 30.0, W + 60.0 + tw + 40.0, 40.0)


def _shelf(sp, p, t, lab, k, side=1, h=2.0):
    """Leader from point p to a shelf at t with the label on it (side 1 - to the right of t, -1 - to the left).
    Returns the bbox of the label."""
    S.line(sp, p, t, "SD_Тонкие", (40, 40, 40), 13)
    S.fill(sp, Point(p).buffer(0.35 * k, 10), (40, 40, 40), "SD_Тонкие")
    w = S.tw(lab, h * k)
    xa = t[0] if side > 0 else t[0] - w - 0.6 * k
    S.line(sp, (xa, t[1]), (xa + w + 0.6 * k, t[1]), "SD_Тонкие", (40, 40, 40), 13)
    S.text(sp, lab, (xa + 0.3 * k, t[1] + 0.4 * k), h * k, "BOTTOM_LEFT", "SD_Текст")
    return (xa, t[1], xa + w + 0.6 * k, t[1] + (h + 0.6) * k)


def draw_joint(sp, fa, fb, k=PIE_K, W=150.0):
    """Joint of two floor finishes under a door leaf: the finishes flush at ±0, the screeds make up the difference."""
    la, lb = parse_layers(fa), parse_layers(fb)
    ta, tb = sum(t for _, t, _, _ in la), sum(t for _, t, _, _ in lb)
    base = -max(ta, tb)
    tops = []
    for x0, x1, lay in ((-W, 0.0, la), (0.0, W, lb)):
        y = 0.0
        for i, (lab, t, kd, _) in enumerate(lay):
            if i == len(lay) - 1:                          # the bottom layer takes up the difference
                t = y - base
            _layer(sp, x0, x1, y - t, y, kd, k)
            if i == 0:
                tops.append((re.sub(r"\s*[\d«(].*$", "", lab.split(",")[0]).strip() or lab, ((x0 + x1) / 2.0, y - t / 2.0)))
            y -= t
    _slab(sp, -W, W, base, k)
    _break_line(sp, -W, W, base - SLAB_T, k)
    lt, top = 40.0, 170.0
    leaf = [(-lt / 2, 10.0), (lt / 2, 10.0), (lt / 2, top), (-lt / 2, top)]
    S.fill(sp, leaf, (226, 205, 170), "SD_Штриховка")
    S.poly(sp, leaf, "SD_Тонкие", True, (40, 40, 40), 25)
    _break_line(sp, -lt / 2 - 10, lt / 2 + 10, top, k)
    Y.dashed(sp, (0.0, top + 20.0), (0.0, base - SLAB_T - 15.0), 2.0 * k, 0.8 * k, (90, 90, 90), 13)
    bbs = [_shelf(sp, tops[0][1], (-W - 10.0, 35.0), tops[0][0], k, -1),
           _shelf(sp, tops[1][1], (W + 10.0, 35.0), tops[1][0], k, 1),
           _shelf(sp, (0.0, 3.0), (-W * 0.5, 110.0), "Стык по центру полотна двери", k, -1),
           _shelf(sp, (lt / 2, 120.0), (W * 0.5, 120.0), "Дверное полотно в проёме", k, 1)]
    x0 = min([-W] + [b_[0] for b_ in bbs]) - 20.0
    x1 = max([W] + [b_[2] for b_ in bbs]) + 20.0
    return (x0, base - SLAB_T - 25.0, x1, top + 30.0)


def _lvl(v):
    return ("%+.3f" % (v / 1000.0)).replace(".", ",").replace("+0,000", "±0,000").replace("-0,000", "±0,000")


def draw_levels(sp, P, k=LEVELS_K, rough=0.0):
    """The heights assumed in the design: rough floor, ±0,000 (clean floor), clean ceiling, slab - lines across a wall
    strip with a chain of the heights and the full height rough floor - slab."""
    ceil, slab = float(P.ceiling), float(P.slab)
    x0, x1 = 0.0, 2400.0
    z_r = -rough
    lines = [(slab, "плита перекрытия"), (ceil, "потолок чистовой"), (0.0, "уровень чистого пола")]
    if rough > 0:
        lines.append((z_r, "уровень черновой (стяжку уточнить)"))
    S.fill(sp, [(1500.0, z_r), (1800.0, z_r), (1800.0, slab), (1500.0, slab)], (238, 238, 238), "SD_Штриховка")
    Y.dashed(sp, (300.0, z_r - 300.0), (300.0, slab + 300.0), 6.0 * k, 1.5 * k, (150, 150, 150), 13)
    x_end = x1
    prev = None
    for z, lab in lines:
        below = prev is not None and abs(prev - z) < 6.0 * k     # too near the level above: the mark under the line
        S.line(sp, (x0, z), (x1, z), "SD_Тонкие", (40, 40, 40), 25)
        if below:
            a, b_ = 1.2 * k, 1.6 * k
            S.poly(sp, [(x1 - a, z - b_), (x1 + a, z - b_), (x1, z)], "SD_Тонкие", True, (40, 40, 40), 18)
            S.fill(sp, [(x1, z - b_), (x1 + a, z - b_), (x1, z)], (40, 40, 40), "SD_Тонкие")
            t = "%s  %s" % (_lvl(z), lab)
            L = S.tw(t, 1.9 * k) + 1.4 * k
            S.line(sp, (x1, z - b_), (x1 + L, z - b_), "SD_Тонкие", (40, 40, 40), 13)
            S.text(sp, t, (x1 + 1.2 * k, z - b_ - 0.5 * k), 1.9 * k, "TOP_LEFT", "SD_Текст")
            x_end = max(x_end, x1 + L)
        else:
            bb = Y.level_mark(sp, (x1, z), _lvl(z), k)
            S.text(sp, lab, (bb.bounds[2] + 1.0 * k, z + 2.1 * k), 1.9 * k, "BOTTOM_LEFT", "SD_Текст")
            x_end = max(x_end, bb.bounds[2] + 1.0 * k + S.tw(lab, 1.9 * k))
        prev = z
    vals = sorted({z for z, _ in lines})
    DM.chain(sp, vals, 1100.0, 1500.0, k, vertical=True, register=False)
    DM.chain(sp, [vals[0], vals[-1]], 700.0, 1500.0, k, vertical=True, register=False)
    return (x0 - 100.0, z_r - 300.0, x_end + 100.0, slab + 400.0)


def has_data(A):
    return bool(A.P.floors)


def nodes_sections(A, no, title, scale):
    P = A.P
    psp = A.make_sheet(no, title, scale, None, header=False, kind="B")
    floors = [f for f in P.floors]
    n = 0
    x, y_top = 26.0, 272.0
    col_w = 200.0
    sub = 0

    def place(fn, args, k, caption):
        nonlocal y_top, n, sub
        blk, off = A.model_block(no, sub)
        sub += 1
        win = fn(blk, *args, k=k)
        w, h = (win[2] - win[0]) / k, (win[3] - win[1]) / k
        if w > col_w:
            win = (win[0], win[1], win[0] + col_w * k, win[3])
            w = col_w
        n += 1
        yb = S.view_title(psp, x, y_top, "Узел %d. %s" % (n, caption), "1:%d" % k)
        rr = A.vp(psp, off, win, (x, yb - 2.0 - h), k)
        y_top = rr[1] - 9.0
        return rr

    for f in floors:
        if y_top < 60.0:
            break
        place(draw_pie, (f,), PIE_K, "Пирог пола: %s" % _short(f))
    if len(floors) >= 2 and y_top >= 70.0:
        a, b = sorted(floors, key=pie_thickness)[-1], sorted(floors, key=pie_thickness)[0]
        place(draw_joint, (a, b), PIE_K, "Стык напольных покрытий под дверным полотном")
    # the heights - on the right half
    rough = max((pie_thickness(f) for f in floors), default=0.0)
    blk, off = A.model_block(no, sub)
    k = LEVELS_K
    win = draw_levels(blk, P, k, rough)
    h = (win[3] - win[1]) / k
    if h > 230.0:
        k = 50
        blk, off = A.model_block(no, sub + 1)
        win = draw_levels(blk, P, k, rough)
        h = (win[3] - win[1]) / k
    n += 1
    yb = S.view_title(psp, 240.0, 272.0, "Узел %d. Высотные данные, заложенные при проектировании" % n, "1:%d" % k)
    A.vp(psp, off, win, (240.0, yb - 2.0 - h), k)
