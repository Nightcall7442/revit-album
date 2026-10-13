# -*- coding: utf-8 -*-
"""Graphic system of the Space Design Studio album (ezdxf, model mm, A3 sheets in mm)."""
import math
import os
import shutil
import ezdxf
from ezdxf import const, colors
from ezdxf.enums import TextEntityAlignment, MTextEntityAlignment
from shapely.geometry import Polygon

FONT = "Inter-Regular.otf"
FONT_B = "Inter-SemiBold.otf"
ST, STB = "SD", "SD_B"
A3 = (420.0, 297.0)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
_FONT_CACHE = {}


def ensure_fonts():
    """Install bundled Inter fonts for ezdxf (once per machine)."""
    from ezdxf.fonts import fonts
    try:
        f = fonts.make_font(FONT, cap_height=1.0)
        if "inter" in str(getattr(f, "name", "")).lower() or fonts.find_font_face(FONT) is not None:
            ok = fonts.font_manager.has_font(FONT) if hasattr(fonts.font_manager, "has_font") else True
            if ok:
                return
    except Exception:
        pass
    dst = os.path.expanduser("~/.local/share/fonts")
    os.makedirs(dst, exist_ok=True)
    for fn in (FONT, FONT_B):
        src = os.path.join(ASSETS, "fonts", fn)
        if os.path.exists(src) and not os.path.exists(os.path.join(dst, fn)):
            shutil.copy(src, os.path.join(dst, fn))
    try:
        fonts.build_system_font_cache()
    except Exception:
        pass


def tw(s, h, bold=False):
    """Exact text width (same units as h) for the album fonts."""
    from ezdxf.fonts import fonts
    key = (bold, round(h, 4))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = fonts.make_font(FONT_B if bold else FONT, cap_height=h, width_factor=1.0)
    return _FONT_CACHE[key].text_width(s)

C_WALL = (38, 38, 40)
C_PART = (120, 120, 124)
C_RED = (214, 40, 40)
C_BLUE = (25, 95, 210)
C_BROWN = (130, 80, 40)
C_AMBER = (235, 150, 0)
C_FURN = (95, 95, 100)
C_GRAY = (150, 150, 150)
C_LIGHT = (225, 225, 228)
C_DIM = (60, 60, 60)
C_GREEN = (40, 140, 80)

LAYERS = {
    "SD_Стены": 35, "SD_Перегородки": 35, "SD_Окна": 18, "SD_Двери": 18, "SD_Мебель": 18, "SD_Мебель_скр": 13,
    "SD_Размеры": 13, "SD_Текст": 18, "SD_Тонкие": 13, "SD_Акцент": 35, "SD_Свет": 25, "SD_Электрика": 25,
    "SD_Вода": 25, "SD_Проводка": 18, "SD_LED": 35, "SD_Штриховка": 9, "SD_Рамка": 50, "SD_Штамп": 25,
    "SD_Таблицы": 18, "SD_Видовые": 13, "SD_Оси": 13,
}


def new_doc():
    doc = ezdxf.new("R2018", setup=True, units=ezdxf.units.MM)
    doc.header["$LWDISPLAY"] = 1
    doc.header["$PSLTSCALE"] = 1
    for name, lw in LAYERS.items():
        doc.layers.add(name, color=7, lineweight=lw)
    doc.layers.get("SD_Видовые").off()
    doc.styles.add(ST, font=FONT).dxf.width = 1.0
    doc.styles.add(STB, font=FONT_B).dxf.width = 1.0
    for name, scale in (("SD50", 50.0), ("SD40", 40.0), ("SD30", 30.0), ("SD25", 25.0), ("SD20", 20.0), ("SD10", 10.0), ("SD5", 5.0), ("SD1", 1.0)):
        ds = doc.dimstyles.new(name)
        ds.dxf.dimtxsty = ST
        ds.dxf.dimscale = scale
        ds.dxf.dimtxt = 1.9
        ds.dxf.dimtsz = 0.9
        ds.dxf.dimexe = 1.2
        ds.dxf.dimexo = 0.8
        ds.dxf.dimdle = 1.2
        ds.dxf.dimgap = 0.6
        ds.dxf.dimtad = 1
        ds.dxf.dimtih = 0
        ds.dxf.dimtoh = 0
        ds.dxf.dimdec = 0
        ds.dxf.dimzin = 8
        ds.dxf.dimclrd = 8
        ds.dxf.dimclre = 8
        ds.dxf.dimclrt = 250
        ds.dxf.dimlwd = 13
        ds.dxf.dimlwe = 13
        ds.dxf.dimtmove = 2
    return doc


def tc(e, rgb):
    if rgb is not None:
        e.rgb = rgb
    return e


def text(sp, s, p, h, align="MIDDLE_CENTER", layer="SD_Текст", rot=0.0, bold=False, rgb=None, width=None):
    t = sp.add_text(s, height=h, rotation=rot, dxfattribs={"style": STB if bold else ST, "layer": layer})
    if width:
        t.dxf.width = width
    t.set_placement(p, align=getattr(TextEntityAlignment, align))
    return tc(t, rgb)


def mtext(sp, s, p, h, width, layer="SD_Текст", attach="TOP_LEFT", spacing=1.25, bold=False, rgb=None):
    m = sp.add_mtext(s, dxfattribs={"style": STB if bold else ST, "layer": layer, "char_height": h, "width": width})
    m.dxf.line_spacing_factor = spacing
    m.set_location(p, attachment_point=getattr(MTextEntityAlignment, attach))
    return tc(m, rgb)


def line(sp, a, b, layer="SD_Тонкие", rgb=None, lw=None, lt=None):
    e = sp.add_line(a, b, dxfattribs={"layer": layer})
    if lw is not None:
        e.dxf.lineweight = lw
    if lt:
        e.dxf.linetype = lt
    return tc(e, rgb)


def poly(sp, pts, layer="SD_Тонкие", closed=True, rgb=None, lw=None, lt=None):
    e = sp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
    if lw is not None:
        e.dxf.lineweight = lw
    if lt:
        e.dxf.linetype = lt
    return tc(e, rgb)


def rect(sp, x0, y0, x1, y1, layer="SD_Тонкие", rgb=None, lw=None, lt=None):
    return poly(sp, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, True, rgb, lw, lt)


def circle(sp, c, r, layer="SD_Тонкие", rgb=None, lw=None):
    e = sp.add_circle(c, r, dxfattribs={"layer": layer})
    if lw is not None:
        e.dxf.lineweight = lw
    return tc(e, rgb)


def arc(sp, c, r, a0, a1, layer="SD_Тонкие", rgb=None, lw=None, lt=None):
    e = sp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})
    if lw is not None:
        e.dxf.lineweight = lw
    if lt:
        e.dxf.linetype = lt
    return tc(e, rgb)


def _paths(h, shp):
    polys = list(shp.geoms) if hasattr(shp, "geoms") else [shp]
    n = 0
    for p in polys:
        if p.is_empty or p.area < 1e-6:
            continue
        h.paths.add_polyline_path(list(p.exterior.coords)[:-1], is_closed=True, flags=const.BOUNDARY_PATH_EXTERNAL)
        for ring in p.interiors:
            h.paths.add_polyline_path(list(ring.coords)[:-1], is_closed=True, flags=const.BOUNDARY_PATH_DEFAULT)
        n += 1
    return n


def fill(sp, shp, rgb, layer="SD_Штриховка"):
    if isinstance(shp, (list, tuple)):
        shp = Polygon(shp)
    h = sp.add_hatch(dxfattribs={"layer": layer})
    h.set_solid_fill(color=7, rgb=rgb)
    _paths(h, shp)
    return h


def hatch(sp, shp, rgb, pattern="ANSI31", scale=1.0, angle=0.0, layer="SD_Штриховка"):
    if isinstance(shp, (list, tuple)):
        shp = Polygon(shp)
    h = sp.add_hatch(dxfattribs={"layer": layer})
    h.set_pattern_fill(pattern, scale=scale, angle=angle)
    h.rgb = rgb
    _paths(h, shp)
    return h


def grid_lines(sp, shp, step_x, step_y, origin=(0.0, 0.0), rgb=C_GRAY, layer="SD_Тонкие", angle=0.0):
    """Exact tile / plank joints clipped to a polygon (vector lines, not a hatch)."""
    from shapely.geometry import LineString
    from shapely import affinity
    if isinstance(shp, (list, tuple)):
        shp = Polygon(shp)
    minx, miny, maxx, maxy = shp.bounds
    ox, oy = origin
    lines = []
    if step_x:
        k0 = math.floor((minx - ox) / step_x)
        k1 = math.ceil((maxx - ox) / step_x)
        for k in range(k0, k1 + 1):
            x = ox + k * step_x
            lines.append(LineString([(x, miny - 1), (x, maxy + 1)]))
    if step_y:
        k0 = math.floor((miny - oy) / step_y)
        k1 = math.ceil((maxy - oy) / step_y)
        for k in range(k0, k1 + 1):
            y = oy + k * step_y
            lines.append(LineString([(minx - 1, y), (maxx + 1, y)]))
    for ln in lines:
        seg = ln.intersection(shp)
        for g in (seg.geoms if hasattr(seg, "geoms") else [seg]):
            if g.geom_type == "LineString" and g.length > 1:
                c = list(g.coords)
                line(sp, c[0], c[-1], layer, rgb)


def dim(sp, p1, p2, base, style, vertical=False, location=None, text_override=None):
    d = sp.add_linear_dim(base=base, p1=p1, p2=p2, angle=90 if vertical else 0, dimstyle=style, location=location,
                          text=text_override if text_override else "<>", dxfattribs={"layer": "SD_Размеры"})
    d.render()
    return d


def chain(sp, values, line_pos, ext_from, style="SD50", vertical=False, small=None, custom=None, scale=50.0):
    vals = sorted(set(round(v, 2) for v in values))
    n = len(vals) - 1
    th = 1.9 * scale
    small = small if small is not None else 7.5 * scale
    custom = custom or {}
    prev_mode = None
    for i in range(n):
        a, b = vals[i], vals[i + 1]
        if vertical:
            p1, p2, base = (ext_from, a), (ext_from, b), (line_pos, a)
        else:
            p1, p2, base = (a, ext_from), (b, ext_from), (a, line_pos)
        loc = None
        tw = len("%d" % round(b - a)) * th * 0.62
        lift = 0.6 * scale + th / 2.0
        mode = custom.get(i)
        if mode is None and b - a < small:
            mode = "before" if (i == 0 and n > 1) else ("after" if i == n - 1 else "up")
            if mode == "up" and prev_mode == "up":
                mode = "other"
        prev_mode = mode if b - a < small else None
        if mode is not None:
            if isinstance(mode, tuple):
                along, across = mode
                loc = (across, along) if vertical else (along, across)
            else:
                if mode == "before":
                    along = a - tw / 2.0 - 0.8 * scale
                elif mode == "after":
                    along = b + tw / 2.0 + 0.8 * scale
                else:
                    along = (a + b) / 2.0
                l2 = lift + (th * 1.1 if mode == "up" else 0.0)
                if mode == "other":
                    l2 = -lift
                loc = (line_pos - l2, along) if vertical else (along, line_pos + l2)
        dim(sp, p1, p2, base, style, vertical=vertical, location=loc)


# ---------------------------------------------------------------- sheet furniture
def frame(psp):
    W, H = A3
    rect(psp, 0, 0, W, H, "SD_Тонкие", rgb=(180, 180, 180))
    rect(psp, 20, 5, W - 5, H - 5, "SD_Рамка")


def stamp(psp, logo_def, sheet_no, sheets_total, title, scale_txt, info):
    W, H = A3
    x1, y0 = W - 5, 5
    x0, y1 = x1 - 230, y0 + 26
    rect(psp, x0, y0, x1, y1, "SD_Штамп")
    xa, xb = x0 + 52, x1 - 42
    line(psp, (xa, y0), (xa, y1), "SD_Штамп")
    line(psp, (xb, y0), (xb, y1), "SD_Штамп")
    line(psp, (xa, y0 + 9), (xb, y0 + 9), "SD_Тонкие")
    line(psp, (xa, y0 + 17.5), (xb, y0 + 17.5), "SD_Тонкие")
    line(psp, (xb, y0 + 13), (x1, y0 + 13), "SD_Тонкие")
    line(psp, (xb + 21, y0), (xb + 21, y0 + 13), "SD_Тонкие")
    if logo_def is not None:
        iw, ih = logo_def.dxf.image_size.x, logo_def.dxf.image_size.y
        wl = 44.0
        hl = wl * ih / iw
        img = psp.add_image(logo_def, insert=(x0 + 4, y0 + (26 - hl) / 2.0), size_in_units=(wl, hl), dxfattribs={"layer": "SD_Штамп"})
        img.rgb = (254, 254, 254)
    text(psp, info["object"], (xa + 2.5, y1 - 4.3), 2.4, "MIDDLE_LEFT", "SD_Штамп")
    text(psp, info["place"], (xa + 2.5, y0 + 13.2), 2.4, "MIDDLE_LEFT", "SD_Штамп")
    text(psp, title, (xa + 2.5, y0 + 4.5), 3.2, "MIDDLE_LEFT", "SD_Штамп", bold=True)
    text(psp, "Стадия", (xb + 2, y1 - 3.0), 1.7, "MIDDLE_LEFT", "SD_Штамп", rgb=(110, 110, 110))
    text(psp, info.get("stage", "Рабочий проект"), (xb + 2, y1 - 8.5), 2.3, "MIDDLE_LEFT", "SD_Штамп")
    text(psp, "Масштаб", (xb + 2, y0 + 10.5), 1.7, "MIDDLE_LEFT", "SD_Штамп", rgb=(110, 110, 110))
    text(psp, scale_txt or "-", (xb + 2, y0 + 4.5), 2.4, "MIDDLE_LEFT", "SD_Штамп")
    text(psp, "Лист", (xb + 31.5, y0 + 10.5), 1.7, "MIDDLE_CENTER", "SD_Штамп", rgb=(110, 110, 110))
    text(psp, "%s / %s" % (sheet_no, sheets_total), (xb + 31.5, y0 + 4.5), 2.8, "MIDDLE_CENTER", "SD_Штамп", bold=True)
    text(psp, info.get("date", ""), (xb + 2, y1 + 2.2), 1.7, "MIDDLE_LEFT", "SD_Тонкие", rgb=(130, 130, 130))


def view_title(psp, x, y, title, scale_txt=None, h=4.0):
    text(psp, title, (x, y), h, "BOTTOM_LEFT", "SD_Текст", bold=True)
    wlen = len(title) * h * 0.58
    if scale_txt:
        text(psp, scale_txt, (x + wlen + 3, y), h * 0.7, "BOTTOM_LEFT", "SD_Текст", rgb=(110, 110, 110))
    line(psp, (x, y - 1.5), (x + wlen + (h * 0.7 * len(scale_txt) * 0.6 + 3 if scale_txt else 0), y - 1.5), "SD_Тонкие")


def viewport(psp, cx_mm, cy_mm, w_mm, h_mm, model_center, scale):
    return psp.add_viewport(center=(cx_mm, cy_mm), size=(w_mm, h_mm), view_center_point=model_center,
                            view_height=h_mm * scale, dxfattribs={"layer": "SD_Видовые"})


def wrap_count(s, width, h, bold=False):
    """Number of lines MTEXT will use (greedy word wrap with real glyph widths)."""
    n = 0
    for part in str(s).split("\\P"):
        words = part.split(" ")
        cur = ""
        k = 1
        for w in words:
            t = (cur + " " + w) if cur else w
            if tw(t, h, bold) > width * 0.97 and cur:
                k += 1
                cur = w
            else:
                cur = t
        n += k
    return max(1, n)


def row_height(h, n):
    return h * 1.35 + 2.6 if n == 1 else h * 1.85 * n + 1.6


def table_height(widths, header, rows, h=2.0, head_h=7.0, title=None, pad=1.2, total=None, row_h=None):
    tot = head_h + (5.0 if title else 0.0)
    for ri, r in enumerate(list(rows) + ([total] if total else [])):
        cells = r["cells"] if isinstance(r, dict) else r
        n = max([wrap_count("" if c is None else str(c), widths[i] - 2 * pad, h) for i, c in enumerate(cells)] + [1])
        tot += row_h or row_height(h, n)
    return tot


def table(psp, x, y, widths, header, rows, h=2.0, row_h=None, head_h=7.0, aligns=None, title=None, pad=1.2,
          total=None, zebra=False):
    """Top-left at (x, y). rows: list of lists (strings) or dict(cells=..., bold=..., fill=rgb). Auto row height."""
    tw = sum(widths)
    xs = [x]
    for w in widths:
        xs.append(xs[-1] + w)
    if title:
        text(psp, title, (x, y + 2.5), 3.0, "BOTTOM_LEFT", "SD_Таблицы", bold=True)
    fill(psp, [(x, y), (x + tw, y), (x + tw, y - head_h), (x, y - head_h)], (236, 236, 238), "SD_Таблицы")
    for i, hd in enumerate(header):
        mtext(psp, hd, ((xs[i] + xs[i + 1]) / 2.0, y - head_h / 2.0), h * 0.9, widths[i] - 2 * pad, "SD_Таблицы",
              "MIDDLE_CENTER", 1.0, bold=True)
    cy = y - head_h
    aligns = aligns or ["L"] * len(widths)
    all_rows = list(rows) + ([total] if total else [])
    for ri, r in enumerate(all_rows):
        cells = r["cells"] if isinstance(r, dict) else r
        bold = (isinstance(r, dict) and r.get("bold")) or (total is not None and ri == len(all_rows) - 1)
        lines_needed = 1
        for i, c in enumerate(cells):
            c = "" if c is None else str(c)
            lines_needed = max(lines_needed, wrap_count(c, widths[i] - 2 * pad, h, bold))
        rh = row_h or row_height(h, lines_needed)
        if isinstance(r, dict) and r.get("fill"):
            fill(psp, [(x, cy), (x + tw, cy), (x + tw, cy - rh), (x, cy - rh)], r["fill"], "SD_Таблицы")
        elif zebra and ri % 2 == 1:
            fill(psp, [(x, cy), (x + tw, cy), (x + tw, cy - rh), (x, cy - rh)], (247, 247, 248), "SD_Таблицы")
        for i, c in enumerate(cells):
            c = "" if c is None else str(c)
            if not c:
                continue
            if aligns[i] == "C":
                mtext(psp, c, ((xs[i] + xs[i + 1]) / 2.0, cy - rh / 2.0), h, widths[i] - 2 * pad, "SD_Таблицы",
                      "MIDDLE_CENTER", 1.1, bold=bold)
            elif aligns[i] == "R":
                mtext(psp, c, (xs[i + 1] - pad, cy - rh / 2.0), h, widths[i] - 2 * pad, "SD_Таблицы",
                      "MIDDLE_RIGHT", 1.1, bold=bold)
            else:
                mtext(psp, c, (xs[i] + pad, cy - rh / 2.0), h, widths[i] - 2 * pad, "SD_Таблицы", "MIDDLE_LEFT", 1.1, bold=bold)
        line(psp, (x, cy - rh), (x + tw, cy - rh), "SD_Таблицы", rgb=(170, 170, 170))
        cy -= rh
    rect(psp, x, y, x + tw, cy, "SD_Таблицы")
    for xx in xs[1:-1]:
        line(psp, (xx, y), (xx, cy), "SD_Таблицы", rgb=(170, 170, 170))
    line(psp, (x, y - head_h), (x + tw, y - head_h), "SD_Таблицы")
    return cy


def legend(psp, x, y, items, title="Условные обозначения", w1=20.0, w2=72.0, rh=6.5):
    """items: list of (draw_fn(psp, cx, cy) | None, label). Returns bottom y."""
    rows = []
    cy = table(psp, x, y, [w1, w2], ["Эскиз", "Наименование"], [["", lab] for _, lab in items], h=1.9,
               row_h=rh, head_h=6.0, title=title)
    yy = y - 6.0
    for fn, lab in items:
        if fn is not None:
            fn(psp, x + w1 / 2.0, yy - rh / 2.0)
        yy -= rh
    return cy


def notes(psp, x, y, lines_, width=110.0, title="Примечания:"):
    text(psp, title, (x, y), 2.5, "BOTTOM_LEFT", "SD_Текст", bold=True)
    s = "\\P".join("%d. %s" % (i + 1, l) for i, l in enumerate(lines_))
    return mtext(psp, s, (x, y - 2.0), 2.1, width, "SD_Текст", "TOP_LEFT", 1.3)
