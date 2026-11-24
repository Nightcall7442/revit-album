# -*- coding: utf-8 -*-
"""Graphic system of the album (ezdxf, model mm, A3 sheets in mm).

One lettering for every text: sloped narrow technical font of GOST 2.304 / ISO 3098 (ISOCPEUR style) -
assets/fonts/osifont-italic.ttf. «bold» keeps the same face (drawings have no bold lettering)."""
import math
import os
import shutil
import ezdxf
from ezdxf import const, colors
from ezdxf.enums import TextEntityAlignment, MTextEntityAlignment
from shapely.geometry import Polygon

FONT = "osifont-italic.ttf"
FONT_B = "osifont-italic.ttf"
ST, STB = "SD", "SD_B"
A3 = (420.0, 297.0)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
_FONT_CACHE = {}


def ensure_fonts():
    """Install the bundled album font for ezdxf (once per machine)."""
    from ezdxf.fonts import fonts
    dst = os.path.expanduser("~/.local/share/fonts")
    if all(os.path.exists(os.path.join(dst, fn)) for fn in {FONT, FONT_B}):
        try:
            if fonts.find_font_face(FONT) is not None and "osifont" in str(fonts.find_font_face(FONT).family).lower():
                return
        except Exception:
            pass
    os.makedirs(dst, exist_ok=True)
    for fn in {FONT, FONT_B}:
        src = os.path.join(ASSETS, "fonts", fn)
        if os.path.exists(src) and not os.path.exists(os.path.join(dst, fn)):
            shutil.copy(src, os.path.join(dst, fn))
    try:
        fonts.build_system_font_cache()
    except Exception:
        pass


def tw(s, h, bold=False):
    """Exact text width (same units as h) for the album fonts - of the text as it will be drawn (typography fixed)."""
    from ezdxf.fonts import fonts
    from . import typo
    key = (bold, round(h, 4))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = fonts.make_font(FONT_B if bold else FONT, cap_height=h, width_factor=1.0)
    return _FONT_CACHE[key].text_width(typo.fix(s).replace(typo.NBSP, " ") if isinstance(s, str) else s)

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
        ds.dxf.dimclrd = 7                    # geometry and overall sizes - black (meaning colours: dims.color)
        ds.dxf.dimclre = 7
        ds.dxf.dimclrt = 7
        ds.dxf.dimlwd = 13
        ds.dxf.dimlwe = 13
        ds.dxf.dimtmove = 2
    return doc


def tc(e, rgb):
    if rgb is not None:
        e.rgb = rgb
    return e


def text(sp, s, p, h, align="MIDDLE_CENTER", layer="SD_Текст", rot=0.0, bold=False, rgb=None, width=None):
    from . import typo
    s = typo.fix(s)
    if isinstance(s, str):
        s = s.replace(typo.NBSP, " ")            # one line: nothing to break
    t = sp.add_text(s, height=h, rotation=rot, dxfattribs={"style": STB if bold else ST, "layer": layer})
    if width:
        t.dxf.width = width
    t.set_placement(p, align=getattr(TextEntityAlignment, align))
    return tc(t, rgb)


def prewrap(s, width, h, bold=False):
    """Line breaks made here (greedy, glyph widths, non-breaking spaces respected) - the renderer breaks at a
    non-breaking space and drops text after MTEXT's own \\~ code, so the lines are given explicitly."""
    from . import typo
    lines = []
    for part in str(s).split("\\P"):
        cur = ""
        for w in part.split(" "):
            t = (cur + " " + w) if cur else w
            if tw(t, h, bold) > width * 0.97 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
    return "\\P".join(l.replace(typo.NBSP, " ") for l in lines)


def mtext(sp, s, p, h, width, layer="SD_Текст", attach="TOP_LEFT", spacing=1.25, bold=False, rgb=None):
    from . import typo
    s = typo.fix(s)
    if width and isinstance(s, str):
        s = prewrap(s, width, h, bold)
        width = width * 1.03                     # the renderer must not break a line we made again
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
    h.dxf.hatch_style = 0                        # normal (odd parity): islands stay empty in every renderer
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
    """A linear dimension; text_override replaces the measured text (paper-space views: the real size)."""
    d = sp.add_linear_dim(base=base, p1=p1, p2=p2, angle=90 if vertical else 0, dimstyle=style, location=location,
                          text=text_override if text_override else "<>", dxfattribs={"layer": "SD_Размеры"})
    d.render()
    return d


def chain(sp, values, line_pos, ext_from, style="SD50", vertical=False, small=None, custom=None, scale=50.0, mult=None):
    """A chain of dimensions; small segments get their text moved aside. mult: paper-space chain of a view at 1:mult -
    the texts are the real sizes (paper length × mult)."""
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
        txt = "%d" % round((b - a) * mult) if mult else None
        tw = len(txt or "%d" % round(b - a)) * th * 0.62
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
        dim(sp, p1, p2, base, style, vertical=vertical, location=loc, text_override=txt)


# ---------------------------------------------------------------- sheet furniture
STAMP_A_W = 90.0          # stamp A: the right column of the sheet (tables, legend, notes, title block)
STAMP_A_H = 46.0
STAMP_B_H = 26.0          # stamp B: a strip along the bottom
C_LABEL = (110, 110, 110)


def scale_label(scale_txt):
    """«1:25» -> «1 : 25» (several scales «1:25, 1:10» keep their order)."""
    import re
    return re.sub(r"1\s*:\s*(\d+)", lambda m: "1 : " + m.group(1), scale_txt or "")


def frame(psp, info=None):
    """A3 landscape: 20 mm binding margin, 5 mm elsewhere; under the frame the print time (left) and the format."""
    W, H = A3
    rect(psp, 0, 0, W, H, "SD_Тонкие", rgb=(180, 180, 180))
    rect(psp, 20, 5, W - 5, H - 5, "SD_Рамка")
    info = info or {}
    if info.get("printed"):
        text(psp, info["printed"], (20.0, 2.5), 1.8, "MIDDLE_LEFT", "SD_Штамп", rgb=C_LABEL)
    text(psp, "Формат: А3А", (W - 5.0, 2.5), 1.8, "MIDDLE_RIGHT", "SD_Штамп", rgb=C_LABEL)


def _fit_text(s, h, width, hmin=1.8):
    while tw(s, h) > width and h > hmin:
        h -= 0.1
    if tw(s, h) > width:
        while s and tw(s + "…", h) > width:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s, h


def _label_value(psp, x, y_top, y_bot, label, value, w, hv=2.5, align="L"):
    xs = x + 1.5 if align == "L" else x + w / 2.0
    al = "MIDDLE_LEFT" if align == "L" else "MIDDLE_CENTER"
    text(psp, label, (xs, y_top - 2.2), 1.6, al, "SD_Штамп", rgb=C_LABEL)
    v, h = _fit_text(str(value or ""), hv, w - 3.0)
    text(psp, v, (xs, (y_top - 3.6 + y_bot) / 2.0), h, al, "SD_Штамп")


def stamp_a(psp, logo_def, sheet_no, sheets_total, title, scale_txt, info):
    """Title block at the foot of the right column (stamp A): logo, project, address, sheet title,
    stage / scale / sheet / sheets."""
    W, H = A3
    x1, y0 = W - 5, 5.0
    x0 = x1 - STAMP_A_W
    y1 = y0 + STAMP_A_H
    line(psp, (x0, y0), (x0, H - 5), "SD_Рамка")                # the column
    rect(psp, x0, y0, x1, y1, "SD_Штамп")
    rows = [y1, y1 - 11.0, y1 - 20.0, y1 - 27.0, y1 - 37.0, y0]
    for yy in rows[1:-1]:
        line(psp, (x0, yy), (x1, yy), "SD_Штамп" if yy in (rows[1], rows[4]) else "SD_Тонкие")
    if logo_def is not None:                                     # logo row
        iw, ih = logo_def.dxf.image_size.x, logo_def.dxf.image_size.y
        hl = 7.0
        wl = min(40.0, hl * iw / ih)
        hl = wl * ih / iw
        img = psp.add_image(logo_def, insert=(x0 + 2.0, rows[1] + (11.0 - hl) / 2.0), size_in_units=(wl, hl),
                            dxfattribs={"layer": "SD_Штамп"})
        img.rgb = (254, 254, 254)
    if info.get("studio") and logo_def is None:
        s, h = _fit_text(info["studio"], 2.2, STAMP_A_W - 4.0)
        text(psp, s, (x1 - 2.0, rows[1] + 5.5), h, "MIDDLE_RIGHT", "SD_Штамп")
    _label_value(psp, x0, rows[1], rows[2], "Проект", info.get("object"), STAMP_A_W)
    _label_value(psp, x0, rows[2], rows[3], "Адрес", info.get("place"), STAMP_A_W, hv=2.2)
    t, ht = _fit_text(title, 3.5, STAMP_A_W - 4.0, 2.2)
    text(psp, "Наименование листа", (x0 + 1.5, rows[3] - 2.2), 1.6, "MIDDLE_LEFT", "SD_Штамп", rgb=C_LABEL)
    text(psp, t, (x0 + 1.5, (rows[3] - 3.6 + rows[4]) / 2.0), ht, "MIDDLE_LEFT", "SD_Штамп")
    cw = [30.0, 22.0, 19.0, 19.0]
    xx = x0
    for (lab, val), w in zip((("Стадия", info.get("stage", "")), ("Масштаб", scale_label(scale_txt) or "—"),
                              ("Лист", sheet_no), ("Листов", sheets_total)), cw):
        if xx > x0:
            line(psp, (xx, rows[4]), (xx, y0), "SD_Тонкие")
        _label_value(psp, xx, rows[4], y0, lab, val, w, hv=2.5, align="C")
        xx += w


def stamp_b(psp, logo_def, sheet_no, sheets_total, title, scale_txt, info):
    """Title block as a strip along the bottom of the sheet (stamp B): sheets with full-width drawings."""
    W, H = A3
    x1, y0 = W - 5, 5.0
    x0, y1 = x1 - 230.0, y0 + STAMP_B_H
    rect(psp, x0, y0, x1, y1, "SD_Штамп")
    xa, xb = x0 + 48.0, x1 - 70.0
    line(psp, (xa, y0), (xa, y1), "SD_Штамп")
    line(psp, (xb, y0), (xb, y1), "SD_Штамп")
    line(psp, (xa, y0 + 9.0), (xb, y0 + 9.0), "SD_Тонкие")
    line(psp, (xa, y0 + 17.5), (xb, y0 + 17.5), "SD_Тонкие")
    line(psp, (xb, y0 + 13.0), (x1, y0 + 13.0), "SD_Тонкие")
    if logo_def is not None:
        iw, ih = logo_def.dxf.image_size.x, logo_def.dxf.image_size.y
        wl = 40.0
        hl = min(18.0, wl * ih / iw)
        wl = hl * iw / ih
        img = psp.add_image(logo_def, insert=(x0 + (48.0 - wl) / 2.0, y0 + (STAMP_B_H - hl) / 2.0),
                            size_in_units=(wl, hl), dxfattribs={"layer": "SD_Штамп"})
        img.rgb = (254, 254, 254)
    _label_value(psp, xa, y1, y0 + 17.5, "Проект", info.get("object"), xb - xa)
    _label_value(psp, xa, y0 + 17.5, y0 + 9.0, "Адрес", info.get("place"), xb - xa, hv=2.2)
    t, ht = _fit_text(title, 3.5, xb - xa - 4.0, 2.2)
    text(psp, t, (xa + 1.5, y0 + 4.5), ht, "MIDDLE_LEFT", "SD_Штамп")
    cw = [28.0, 21.0, 21.0]
    _label_value(psp, xb, y1, y0 + 13.0, "Стадия", info.get("stage", ""), 70.0, align="C")
    xx = xb
    for (lab, val), w in zip((("Масштаб", scale_label(scale_txt) or "—"), ("Лист", sheet_no),
                              ("Листов", sheets_total)), cw):
        if xx > xb:
            line(psp, (xx, y0 + 13.0), (xx, y0), "SD_Тонкие")
        _label_value(psp, xx, y0 + 13.0, y0, lab, val, w, align="C")
        xx += w


def stamp(psp, logo_def, sheet_no, sheets_total, title, scale_txt, info):
    stamp_b(psp, logo_def, sheet_no, sheets_total, title, scale_txt, info)


def view_title(psp, x, y, title, scale_txt=None, h=3.5, align="L"):
    """Caption of a view: the name underlined, the scale «1 : 25» under it. (x, y) - baseline of the name;
    align «L» - from x, «C» - centred on x. Returns the bottom y of the caption."""
    w = tw(title, h)
    xa = x if align == "L" else x - w / 2.0
    text(psp, title, (xa, y), h, "BOTTOM_LEFT", "SD_Текст")
    line(psp, (xa, y - 1.0), (xa + w, y - 1.0), "SD_Текст", lw=25)
    if scale_txt:
        text(psp, scale_label(scale_txt), (xa + w / 2.0, y - 2.2), 2.5, "TOP_CENTER", "SD_Текст")
        return y - 5.2
    return y - 1.5


def viewport(psp, cx_mm, cy_mm, w_mm, h_mm, model_center, scale):
    return psp.add_viewport(center=(cx_mm, cy_mm), size=(w_mm, h_mm), view_center_point=model_center,
                            view_height=h_mm * scale, dxfattribs={"layer": "SD_Видовые"})


def wrap_count(s, width, h, bold=False):
    """Number of lines MTEXT will use (greedy word wrap with real glyph widths) - the same breaks as prewrap."""
    from . import typo
    s = typo.fix(s) if isinstance(s, str) else s
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


def fixed_row_height(row_h, h, n):
    """A fixed row height (legends) still grows when a cell wraps: wrapped lines never spill into the next row
    (lesson L-051)."""
    return max(row_h, (n - 1) * h * 1.85 + h * 1.35 + 1.2) if n > 1 else row_h


TABLE_MIN_H = 2.0          # lettering of tables is never smaller than this (the drawings' 2.5 mm reads at 2.0 in a cell)
TITLE_ROW_H = 6.0          # the name of a table is its first row, above the header (as on the reference album)
STAR_NOTE = "* Ведомость для оценки объёма работ; количество уточняется по месту."
STAR_H = 4.5               # a table named «* ...» has the footnote above under it
HEAD_H = 3.5               # «Условные обозначения:», «Примечание:» - 3.5 mm, underlined


def heading(psp, x, y, s, h=HEAD_H):
    """A block heading under the top y: the text and a line under it. Returns the y under the heading."""
    text(psp, s, (x, y), h, "TOP_LEFT", "SD_Текст")
    line(psp, (x, y - h - 1.0), (x + tw(s, h), y - h - 1.0), "SD_Текст", lw=18)
    return y - h - 3.0


def _cell_text(c):
    return "" if c is None or callable(c) else str(c)


def uo_line(rgb, lw=50):
    """«УО» of a linear item (plinth, cornice, wall finish): a coloured stroke across the cell."""
    def fn(psp, cx, cy, w, h):
        line(psp, (cx - w * 0.38, cy), (cx + w * 0.38, cy), "SD_Таблицы", rgb, lw)
    return fn


def uo_fill(rgb, hatch_=None, hatch_rgb=None, outline=(60, 60, 60)):
    """«УО» of an area item (floor, ceiling): a rectangle with the fill / hatch of the plan."""
    def fn(psp, cx, cy, w, h):
        ww, hh = w * 0.38, min(h * 0.32, 2.4)
        pts = [(cx - ww, cy - hh), (cx + ww, cy - hh), (cx + ww, cy + hh), (cx - ww, cy + hh)]
        fill(psp, pts, rgb, "SD_Таблицы")
        if hatch_:
            hatch(psp, pts, hatch_rgb or outline, hatch_, scale=0.3, layer="SD_Таблицы")
        poly(psp, pts, "SD_Таблицы", True, outline, 13)
    return fn


def table_height(widths, header, rows, h=2.0, head_h=7.0, title=None, pad=1.2, total=None, row_h=None):
    h = max(h, TABLE_MIN_H)
    head_h = max(head_h, h * 2.6)
    tot = head_h + (TITLE_ROW_H if title else 0.0) + (STAR_H if title and title.startswith("*") else 0.0)
    for ri, r in enumerate(list(rows) + ([total] if total else [])):
        cells = r["cells"] if isinstance(r, dict) else r
        n = max([wrap_count(_cell_text(c), widths[i] - 2 * pad, h) for i, c in enumerate(cells)] + [1])
        tot += fixed_row_height(row_h, h, n) if row_h else row_height(h, n)
    return tot


def table(psp, x, y, widths, header, rows, h=2.0, row_h=None, head_h=7.0, aligns=None, title=None, pad=1.2,
          total=None, zebra=False, out_rows=None):
    """Top-left at (x, y). rows: list of lists (strings) or dict(cells=..., bold=..., fill=rgb). Auto row height.
    out_rows: list to receive (top y, height) of every row (to centre legend symbols)."""
    h = max(h, TABLE_MIN_H)
    head_h = max(head_h, h * 2.6)
    tw = sum(widths)
    xs = [x]
    for w in widths:
        xs.append(xs[-1] + w)
    y_top = y
    if title:                                   # the name of the table: its first row
        t, ht = _fit_text(title, 2.5, tw - 2 * pad, 1.8)
        text(psp, t, (x + tw / 2.0, y - TITLE_ROW_H / 2.0), ht, "MIDDLE_CENTER", "SD_Таблицы")
        line(psp, (x, y - TITLE_ROW_H), (x + tw, y - TITLE_ROW_H), "SD_Таблицы")
        y -= TITLE_ROW_H
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
            lines_needed = max(lines_needed, wrap_count(_cell_text(c), widths[i] - 2 * pad, h, bold))
        rh = fixed_row_height(row_h, h, lines_needed) if row_h else row_height(h, lines_needed)
        if out_rows is not None:
            out_rows.append((cy, rh))
        if isinstance(r, dict) and r.get("fill"):
            fill(psp, [(x, cy), (x + tw, cy), (x + tw, cy - rh), (x, cy - rh)], r["fill"], "SD_Таблицы")
        elif zebra and ri % 2 == 1:
            fill(psp, [(x, cy), (x + tw, cy), (x + tw, cy - rh), (x, cy - rh)], (247, 247, 248), "SD_Таблицы")
        for i, c in enumerate(cells):
            if callable(c):                     # a symbol in the cell («УО», sketch)
                c(psp, (xs[i] + xs[i + 1]) / 2.0, cy - rh / 2.0, widths[i], rh)
                continue
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
    rect(psp, x, y_top, x + tw, cy, "SD_Таблицы")
    for xx in xs[1:-1]:
        line(psp, (xx, y), (xx, cy), "SD_Таблицы", rgb=(170, 170, 170))
    line(psp, (x, y - head_h), (x + tw, y - head_h), "SD_Таблицы")
    if title and title.startswith("*"):         # a schedule to estimate the works: the footnote under it
        n, hn = _fit_text(STAR_NOTE, 1.8, tw, 1.5)
        text(psp, n, (x, cy - 1.2), hn, "TOP_LEFT", "SD_Таблицы")
        cy -= STAR_H
    return cy


def legend(psp, x, y, items, title="Условные обозначения:", w1=20.0, w2=72.0, rh=6.5):
    """items: list of (draw_fn(psp, cx, cy) | None, label). Heading «Условные обозначения:» and a two-column table
    (symbol, meaning) without a header row. Returns bottom y."""
    rows = []
    if title:
        y = heading(psp, x, y, title if title.endswith(":") else title + ":")
    cy = table(psp, x, y, [w1, w2], ["Обозначение", "Наименование"], [["", lab] for _, lab in items], h=2.0,
               row_h=rh, head_h=5.5, out_rows=rows)
    for (fn, lab), (top, hh) in zip(items, rows):
        if fn is not None:
            fn(psp, x + w1 / 2.0, top - hh / 2.0)
    return cy


NOTE_H = 2.2


def notes_height(lines_, width):
    return HEAD_H + 3.0 + sum(wrap_count("%d. %s" % (i + 1, l), width, NOTE_H) for i, l in enumerate(lines_)) * NOTE_H * 1.667 * 1.3


def notes(psp, x, y, lines_, width=110.0, title="Примечание:"):
    """Heading «Примечание:» and numbered notes under the top y, one MTEXT per item (a paragraph break that falls
    on the wrap edge was lost by the renderer: «...разводки.5. Выводы» ran into one line)."""
    yy = heading(psp, x, y, title)
    m = None
    for i, l in enumerate(lines_):
        s = "%d. %s" % (i + 1, l)
        m = mtext(psp, s, (x, yy), NOTE_H, width, "SD_Текст", "TOP_LEFT", 1.3)
        yy -= wrap_count(s, width, NOTE_H) * NOTE_H * 1.667 * 1.3
    return m
