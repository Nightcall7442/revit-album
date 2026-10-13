# -*- coding: utf-8 -*-
"""Sheets «Мебель индивидуального изготовления»: the schedule and one production sketch per item.

Sketch of an item (A3): three orthographic views by ГОСТ 2.305 (main view, view from the left to the right of it,
view from above under it) at one scale 1:5 / 1:10 / 1:20 / 1:25 / 1:50 with dimensions in mm (overall, shelf / seat /
top levels, vertical divisions, Ø of a round top, thickness of the top board), a shaded axonometric view with
numbered callouts of the elements, the table of materials, the data block (position, quantity, size, room) and the
production notes. Views are rendered from the item's mesh (items3d) and placed at exact scale; dimensions are
drawn in paper space with the real sizes.
"""
import os

from . import gfx as S
from . import items3d

SCALES = (5, 10, 15, 20, 25, 40, 50)          # ГОСТ 2.302
GAP = 24.0            # between views: two rows of dimensions
AREA = (26.0, 40.0, 272.0, 252.0)
DIMC = (60, 60, 60)


def item_sheets(A):
    """[(title, scale, fn, arg)] for the album registry."""
    P = A.P
    its = [it for it in P.d.get("items") or [] if it.get("pos")]
    if not its:
        return []
    out = [("Мебель индивидуального изготовления. Ведомость", "—", schedule_sheet, dict(items=its))]
    for it in sorted(its, key=_pos_key):
        if it.get("shape") in VECTOR:
            k = pick_scale(it["size"])
            out.append(("Мебель. %s — %s" % (it["pos"], it["name"]), "1:%d" % k, vector_sheet, dict(item=it, k=k)))
            continue
        m = _mesh(A, it)
        if m is None:
            continue
        k = pick_scale(m.size)
        out.append(("Мебель. %s — %s" % (it["pos"], it["name"]), "1:%d" % k, item_sheet, dict(item=it, k=k)))
    return out


def _pos_key(it):
    p = str(it.get("pos", ""))
    try:
        return int(p.split("-")[-1])
    except ValueError:
        return 999


VECTOR = ("panel", "sign")


def _mesh(A, it):
    cache = A.__dict__.setdefault("_item_meshes", {})
    key = it.get("id") or it.get("pos")
    if key not in cache:
        try:
            cache[key] = items3d.load(A.P, it)
        except Exception as ex:
            A.issues.append(dict(code="ITEM_MESH", level="warning", sheet=A.cur_title, msg="%s: %s" % (it.get("pos"), ex)))
            cache[key] = None
        m = cache[key]
        if m is not None:                     # render self-check before any view of it is drawn (lesson L-088)
            healed, rest = m.selfcheck()
            where = "Мебель. %s (самопроверка видов)" % it.get("pos")
            if healed:
                A.issues.append(dict(code="RENDER_HEALED", level="info", sheet=where,
                                     msg="%s: убраны грани невычисленной топологии сцены у %s" % (it.get("pos"), ", ".join(healed))))
            for code, msg in rest:
                A.issues.append(dict(code=code, level="error", sheet=where, msg="%s %s: %s" % (it.get("pos"), it.get("name"), msg)))
    return cache[key]


def pick_scale(size):
    """The largest standard scale at which the three views with their dimensions fit; 1:5 only for small pieces."""
    W, D, H = size
    for k in SCALES:
        w = (W + D) / k + 52.0          # dims left of the main view, the gap, dims right of the side view
        h = (H + D) / k + 62.0          # titles, two rows of dims under the main view, the gap
        if w <= AREA[2] - AREA[0] and h <= AREA[3] - AREA[1]:
            if k == 5 and (W + D) / 10.0 >= 60:
                continue
            return k
    return SCALES[-1]


def notes_height(lines, width, h=2.1):
    return 4.0 + sum(S.wrap_count("%d. %s" % (i + 1, l), width, h) for i, l in enumerate(lines)) * h * 1.667 * 1.3


def _render(A, it, m, kind, k):
    key = "%s_%s" % (it.get("id") or it["pos"], kind) + ("" if kind == "axo" else "_%d" % k)
    cache = A.__dict__.setdefault("_item_png", {})
    if key in cache:
        return cache[key]
    png = os.path.join(A.out_dir, "item_%s.png" % key)
    if kind == "axo":
        info = m.axo(png, width=1000)
    else:
        info = m.view(kind, png, px_per_mm=max(0.35, min(1.6, 9.0 / k)))
    cache[key] = (png, info)
    return png, info


def _img(A, name, png):
    defs = A.__dict__.setdefault("_item_imgdefs", {})
    if name not in defs:
        defs[name] = A.image(name, png)
    return defs[name]


def _place(A, psp, png, info, x, y, k, name):
    """Image of a view: view-plane point (info x0, y0) at paper (x, y), scale 1:k -> mapping function."""
    img = _img(A, name, png)
    w = (info["x1"] - info["x0"]) / k
    h = (info["y1"] - info["y0"]) / k
    e = psp.add_image(img, insert=(x, y), size_in_units=(w, h), dxfattribs={"layer": "SD_Мебель"})
    e.rgb = (254, 254, 254)

    def to_paper(vx, vy):
        return (x + (vx - info["x0"]) / k, y + (vy - info["y0"]) / k)
    return to_paper, (x, y, x + w, y + h)


def _hdim(psp, a, b, y_base, y_line, value, txt=None):
    S.dim(psp, (a[0], y_base), (b[0], y_base), (a[0], y_line), "SD1", text_override=txt or "%d" % round(value))


def _vdim(psp, a, b, x_base, x_line, value, txt=None):
    S.dim(psp, (x_base, a[1]), (x_base, b[1]), (x_line, a[1]), "SD1", vertical=True, text_override=txt or "%d" % round(value))


def _clean(ps, vals, min_gap=0.8):
    out = [ps[0]]
    for p in ps[1:]:
        if p - out[-1] >= min_gap:
            out.append(p)
    return out


def _chain_h(psp, xs_paper, vals, y_base, y_line, k):
    xs = _clean(sorted(xs_paper), vals)
    if len(xs) > 2:
        S.chain(psp, xs, y_line, y_base, "SD1", vertical=False, small=7.0, scale=1.0, mult=k)


def _chain_v(psp, ys_paper, vals, x_base, x_line, k):
    ys = _clean(sorted(ys_paper), vals)
    if len(ys) > 2:
        S.chain(psp, ys, x_line, x_base, "SD1", vertical=True, small=7.0, scale=1.0, mult=k)


def item_sheet(A, no, title, scale, arg):
    it, k = arg["item"], arg["k"]
    P = A.P
    m = _mesh(A, it)
    qty = int(it.get("qty", 1))
    rooms = ", ".join(it.get("rooms") or []) or "по месту"
    psp = A.make_sheet(no, title, scale, "Эскиз для изготовления: виды, размеры, материалы. Количество — %d шт. "
                       "Помещение — %s" % (qty, rooms))
    W, D, H = m.size
    fw, fh, lw, th = W / k, H / k, D / k, D / k
    x0 = AREA[0] + 14.0
    ytop = AREA[3] - 8.0
    y_front = ytop - fh
    # main view
    png, inf = _render(A, it, m, "front", k)
    to_f, rf = _place(A, psp, png, inf, x0 + (inf["x0"] + W / 2.0) / k, y_front + inf["y0"] / k, k, "item_%s_f.png" % it["pos"])
    A.title_note(psp, x0, ytop + 3.0, "Главный вид", "1:%d" % k, h=3.2, hn=2.2)
    L, R = to_f(-W / 2.0, 0)[0], to_f(W / 2.0, 0)[0]
    B, T = to_f(0, 0)[1], to_f(0, H)[1]
    cols = m.columns()
    row = 1
    if len(cols) > 2:
        xs = [to_f(c, 0)[0] for c in cols]
        _chain_h(psp, xs, [b - a for a, b in zip(cols[:-1], cols[1:])], B, B - 7.0, k)
        row = 2
    _hdim(psp, (L, 0), (R, 0), B, B - 7.0 * row, W)
    lv = m.levels()
    col_x = 1
    if len(lv) > 2:
        ys = [to_f(0, z)[1] for z in lv]
        _chain_v(psp, ys, [b - a for a, b in zip(lv[:-1], lv[1:])], L, L - 7.0, k)
        col_x = 2
    _vdim(psp, (0, B), (0, T), L, L - 7.0 * col_x, H)
    cols_ = it.get("columns") or []
    for c in cols_:                        # existing columns the piece is built around: hidden lines, hatched in plan
        x_a, x_b = to_f(c[0], 0)[0], to_f(c[2], 0)[0]
        for xx in (x_a, x_b):
            yy = B
            while yy < T:                      # hidden lines: dashes 2.5 / gaps 1.2 mm
                S.line(psp, (xx, yy), (xx, min(T, yy + 2.5)), "SD_Тонкие", (120, 60, 50), 13)
                yy += 3.7
    # view from the left (to the right of the main view)
    lx = R + GAP
    png, inf = _render(A, it, m, "left", k)
    to_l, rl = _place(A, psp, png, inf, lx + (inf["x0"] + D / 2.0) / k, y_front + inf["y0"] / k, k, "item_%s_l.png" % it["pos"])
    A.title_note(psp, lx, ytop + 3.0, "Вид слева", None, h=3.2, hn=2.2)
    Ll, Rl = to_l(-D / 2.0, 0)[0], to_l(D / 2.0, 0)[0]
    _hdim(psp, (Ll, 0), (Rl, 0), B, B - 7.0, D)
    tb = m.top_board() if it.get("kind") in ("table", "coffee_table") else None
    if tb:
        _vdim(psp, (0, to_l(0, H - tb)[1]), (0, T), Rl, Rl + 6.0, tb)
    # view from above (under the main view)
    png, inf = _render(A, it, m, "top", k)
    ty = B - 7.0 * row - GAP + 2.0 - D / k
    to_t, rt = _place(A, psp, png, inf, x0 + (inf["x0"] + W / 2.0) / k, ty + (inf["y0"] + D / 2.0) / k, k, "item_%s_t.png" % it["pos"])
    A.title_note(psp, x0, ty + D / k + 3.0, "Вид сверху", None, h=3.2, hn=2.2)
    Bt, Tt = to_t(0, -D / 2.0)[1], to_t(0, D / 2.0)[1]
    for c in cols_:
        p0, p1 = to_t(c[0], c[1]), to_t(c[2], c[3])
        from shapely.geometry import box as sbox
        S.hatch(psp, sbox(min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1])),
                (170, 80, 70), "ANSI31", 0.4)
        S.rect(psp, min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]), "SD_Мебель", (120, 60, 50), 25)
    if cols_:
        S.text(psp, "Колонны существующие: на видах — пунктиром, в плане — штриховкой", (L, Bt - 4.0), 1.9,
               "TOP_LEFT", rgb=(120, 60, 50))
    if m.round_top():
        cx, cy = to_t(0, 0)
        S.dim(psp, (L, cy), (R, cy), (L, cy), "SD1", text_override="Ø%d" % round(W))
    else:
        _vdim(psp, (0, Bt), (0, Tt), L, L - 7.0, D)
    # right column: axonometric view with callouts, materials, data
    cx0, cx1 = 280.0, 412.0
    png, inf = _render(A, it, m, "axo", k)
    from PIL import Image
    iw, ih = Image.open(png).size
    aw = 98.0
    ah = aw * ih / iw
    if ah > 92.0:
        ah, aw = 92.0, 92.0 * iw / ih
    ax, ay = cx0 + (104.0 - aw) / 2.0, 252.0 - ah
    img = _img(A, "item_%s_a.png" % it["pos"], png)
    e = psp.add_image(img, insert=(ax, ay), size_in_units=(aw, ah), dxfattribs={"layer": "SD_Мебель"})
    e.rgb = (254, 254, 254)
    A.title_note(psp, cx0, 255.0, "Общий вид", "без масштаба", h=3.2, hn=2.2)
    els = it.get("elements") or []
    sc = aw / float(iw)
    anchors = []
    for i, el in enumerate(els):
        pi = el.get("part")
        if pi is None or pi >= len(m.parts):
            continue
        px, py = m.anchor(pi, inf)
        anchors.append((i + 1, ax + px * sc, ay + ah - py * sc))
    if anchors:
        anchors.sort(key=lambda a: -a[2])
        n = len(anchors)
        ys = [min(250.0, max(ay + 3.0, a[2])) for a in anchors]
        for j in range(1, n):
            ys[j] = min(ys[j], ys[j - 1] - 7.0)
        lab_x = cx0 + 104.0 + 9.0
        for (num, px, py), ly in zip(anchors, ys):
            S.line(psp, (px, py), (lab_x - 2.6, ly), "SD_Тонкие", (80, 80, 80), 13)
            S.circle(psp, (px, py), 0.45, "SD_Тонкие", (40, 40, 40), 25)
            S.circle(psp, (lab_x, ly), 2.4, "SD_Тонкие", (40, 40, 40), 18)
            S.text(psp, str(num), (lab_x, ly), 2.2, "MIDDLE_CENTER", bold=True)
    rows = [[str(i + 1), el["name"], el["material"]] for i, el in enumerate(els)] or [["—", "—", "—"]]
    yb = S.table(psp, cx0, ay - 6.0, [8, 34, 90], ["№", "Элемент", "Материал / отделка"], rows, h=1.8,
                 aligns=["C", "L", "L"], title="Материалы", head_h=5.5)
    data = [["Позиция", it["pos"]], ["Количество", "%d шт." % qty],
            ["Габариты (Ш × Г × В)", "%d × %d × %d мм" % (round(W), round(D), round(H))],
            ["Помещение", rooms], ["Масштаб видов", "1:%d" % k]]
    yb = S.table(psp, cx0, yb - 11.0, [42, 90], ["Параметр", "Значение"], data, h=1.8, aligns=["L", "L"],
                 title="Характеристики", head_h=5.5)
    notes = A.note_lines("item_%s" % it["pos"], it.get("notes") or [])
    if notes:
        need = notes_height(notes, 131)
        if yb - 9.0 - need >= 36.0:
            S.notes(psp, cx0, yb - 9.0, notes, 131)
        else:                                  # under the views on the left (the title block is on the right)
            low = ty - (11.0 if cols_ else 8.0)
            need2 = notes_height(notes, 154)
            y_n = low if low - need2 >= 8.0 else 8.0 + need2
            S.notes(psp, 26.0, y_n, notes, 154)


def schedule_sheet(A, no, title, scale, arg):
    its = sorted(arg["items"], key=_pos_key)
    psp = A.make_sheet(no, title, scale, "Позиции, габариты, материалы и количество; эскизы — на следующих листах")
    n = len(its)
    row_h = max(7.0, min(16.0, (252.0 - 70.0) / max(1, n)))
    rows = []
    for it in its:
        W, D, H = it["size"]
        mats = "; ".join("%s — %s" % ((e["name"][:1].lower() + e["name"][1:]) if i else e["name"], e["material"])
                         for i, e in enumerate(it.get("elements") or [])) or "по визуализации"
        rows.append([it["pos"], "", it["name"], "%d × %d × %d" % (round(W), round(D), round(H)), mats,
                     str(int(it.get("qty", 1))), ", ".join(it.get("rooms") or []) or "—", _sheet_of(A, it)])
    widths = [13, 26, 62, 30, 166, 14, 48, 14]
    geo = []
    yb = S.table(psp, 24, 256, widths, ["Поз.", "Вид", "Наименование", "Ш × Г × В, мм", "Материалы", "Кол., шт.",
                                        "Помещение", "Лист"], rows, h=1.8, row_h=row_h,
                 aligns=["C", "C", "L", "C", "L", "C", "L", "C"], head_h=6.0, out_rows=geo)
    from PIL import Image
    x_img = 24 + widths[0]
    for it, (top, hh) in zip(its, geo):
        if it.get("shape") in VECTOR:
            W, D, H = it["size"]
            kk = max(W / (widths[1] - 3.0), H / (hh - 2.0))
            draw_front(psp, it, x_img + widths[1] / 2.0 - W / 2.0 / kk, top - hh / 2.0 - H / 2.0 / kk, kk, small=True)
            continue
        m = _mesh(A, it)
        if m is None:
            continue
        png, inf = _render(A, it, m, "axo", 10)
        iw, ih = Image.open(png).size
        bw, bh = widths[1] - 2.0, hh - 1.6
        w = bw
        h = w * ih / iw
        if h > bh:
            h, w = bh, bh * iw / ih
        img = _img(A, "item_%s_a.png" % it["pos"], png)
        e = psp.add_image(img, insert=(x_img + (widths[1] - w) / 2.0, top - hh + (hh - h) / 2.0), size_in_units=(w, h),
                          dxfattribs={"layer": "SD_Мебель"})
        e.rgb = (254, 254, 254)
    tot = sum(int(it.get("qty", 1)) for it in its)
    S.notes(psp, 24, min(yb - 8.0, 60.0), A.note_lines("items", [
        "Всего изделий: %d позиций, %d шт. Расстановка — см. план мебели (марки М-N у изделий)." % (len(its), tot),
        "Размеры — по 3D-модели дизайн-проекта; перед изготовлением — контрольный замер по месту.",
        "Образцы материалов (камень, шпон, ткань, металл) согласовать с дизайнером до запуска в производство.",
    ]), 250)


def _sheet_of(A, it):
    for no, key, title, *_ in A.sheets:
        if key == "items" and title.startswith("Мебель. %s " % it["pos"]):
            return "%02d" % no
    return "—"


# ------------------------------------------------------------------ parametric pieces (no mesh in the scene)
def draw_front(sp, it, x, y, k, small=False):
    """Front view of a parametric piece at paper (x, y) = its bottom-left, scale 1:k."""
    W, D, H = it["size"]
    lw = 9 if small else 25
    ink = (40, 40, 42)
    if it.get("shape") == "sign":
        S.rect(sp, x, y, x + W / k, y + H / k, "SD_Мебель", ink, lw)
        inset = 25.0 / k
        S.rect(sp, x + inset, y + inset, x + W / k - inset, y + H / k - inset, "SD_Тонкие", (150, 150, 150), 9)
        lh = it.get("letter_h", 120) / k
        if not small:
            txt = it.get("text", "")
            S.text(sp, txt, (x + W / k / 2.0, y + H / k / 2.0), lh, "MIDDLE_CENTER", "SD_Мебель", bold=True, rgb=ink)
        return
    # panel with a grid of round mirrors and a sign above it
    S.rect(sp, x, y, x + W / k, y + H / k, "SD_Мебель", ink, lw)
    g = it.get("grid") or {}
    cols, rows, cell = g.get("cols", 3), g.get("rows", 4), g.get("cell", 400)
    gl, gb, hole = g.get("left", (W - cols * cell) / 2.0), g.get("bottom", 600), g.get("hole", 260)
    gx, gy = x + gl / k, y + gb / k
    S.rect(sp, gx, gy, gx + cols * cell / k, gy + rows * cell / k, "SD_Мебель", (120, 90, 60), lw)
    for i in range(1, cols):
        S.line(sp, (gx + i * cell / k, gy), (gx + i * cell / k, gy + rows * cell / k), "SD_Тонкие", (120, 90, 60), 13)
    for j in range(1, rows):
        S.line(sp, (gx, gy + j * cell / k), (gx + cols * cell / k, gy + j * cell / k), "SD_Тонкие", (120, 90, 60), 13)
    for i in range(cols):
        for j in range(rows):
            S.circle(sp, (gx + (i + 0.5) * cell / k, gy + (j + 0.5) * cell / k), hole / 2.0 / k, "SD_Мебель", (90, 120, 140), lw)
    sg = it.get("sign")
    if sg:
        sw, sh, sb = sg.get("w", 600), sg.get("h", 280), sg.get("bottom", gb + rows * cell + 300)
        cx = x + W / k / 2.0
        S.rect(sp, cx - sw / k / 2.0, y + sb / k, cx + sw / k / 2.0, y + (sb + sh) / k, "SD_Тонкие", (190, 60, 70), 13)
        if not small:
            S.text(sp, sg.get("text", ""), (cx, y + (sb + sh / 2.0) / k), min(sh * 0.32, 90) / k, "MIDDLE_CENTER",
                   "SD_Мебель", rgb=(190, 60, 70))


def vector_sheet(A, no, title, scale, arg):
    it, k = arg["item"], arg["k"]
    W, D, H = it["size"]
    qty = int(it.get("qty", 1))
    rooms = ", ".join(it.get("rooms") or []) or "по месту"
    psp = A.make_sheet(no, title, scale, "Эскиз для изготовления: виды, размеры, материалы. Количество — %d шт. "
                       "Помещение — %s" % (qty, rooms))
    x0 = AREA[0] + 14.0
    ytop = AREA[3] - 8.0
    yb = ytop - H / k
    A.title_note(psp, x0, ytop + 3.0, "Главный вид", "1:%d" % k, h=3.2, hn=2.2)
    draw_front(psp, it, x0, yb, k)
    L, R, B, T = x0, x0 + W / k, yb, ytop
    row = 1
    if it.get("shape") == "panel":
        g = it.get("grid") or {}
        cols, cell, gl = g.get("cols", 3), g.get("cell", 400), g.get("left", (W - g.get("cols", 3) * g.get("cell", 400)) / 2.0)
        xs = [L, L + gl / k] + [L + (gl + i * cell) / k for i in range(1, cols + 1)] + [R]
        _chain_h(psp, xs, [], B, B - 7.0, k)
        row = 2
    _hdim(psp, (L, 0), (R, 0), B, B - 7.0 * row, W)
    _vdim(psp, (0, B), (0, T), L, L - 7.0, H)
    if it.get("shape") == "panel":
        g = it.get("grid") or {}
        cols, rows, cell = g.get("cols", 3), g.get("rows", 4), g.get("cell", 400)
        gl, gb = g.get("left", (W - cols * cell) / 2.0), g.get("bottom", 600)
        ys = [B, B + gb / k] + [B + (gb + j * cell) / k for j in range(1, rows + 1)]
        _chain_v(psp, ys, [gb] + [cell] * rows, R, R + 7.0, k)
        hole = g.get("hole", 260)
        cx, cy = L + (gl + 0.5 * cell) / k, B + (gb + (rows - 0.5) * cell) / k
        S.dim(psp, (cx - hole / 2.0 / k, cy), (cx + hole / 2.0 / k, cy), (cx - hole / 2.0 / k, cy), "SD1",
              text_override="Ø%d" % hole)
    else:
        lh = it.get("letter_h", 120)
        cx = L + W / k / 2.0
        _vdim(psp, (0, B + (H - lh) / 2.0 / k), (0, B + (H + lh) / 2.0 / k), R, R + 7.0, lh)
    # view from the left / from above
    if it.get("shape") == "panel":
        lx = R + GAP + 8.0
        A.title_note(psp, lx, ytop + 3.0, "Вид слева", None, h=3.2, hn=2.2)
        S.rect(psp, lx, B, lx + D / k, T, "SD_Мебель", (40, 40, 42), 25)
        inset = (it.get("grid") or {}).get("depth", 50)
        g = it.get("grid") or {}
        gb, rows, cell = g.get("bottom", 600), g.get("rows", 4), g.get("cell", 400)
        S.rect(psp, lx, B + gb / k, lx + inset / k, B + (gb + rows * cell) / k, "SD_Тонкие", (120, 90, 60), 13)
        _hdim(psp, (lx, 0), (lx + inset / k, 0), B, B - 7.0, inset)
        _hdim(psp, (lx, 0), (lx + D / k, 0), B, B - 14.0, D)
    else:
        ty = B - 7.0 - GAP - D / k
        A.title_note(psp, x0, ty + D / k + 3.0, "Вид сверху", None, h=3.2, hn=2.2)
        ret = min(it.get("return", 0), D)
        if ret:                                  # the face (bottom edge) bends back to the wall at the right end
            r = ret / k
            ink = (40, 40, 42)
            S.line(psp, (L, ty), (R - r, ty), "SD_Мебель", ink, 25)
            S.line(psp, (L, ty + D / k), (R, ty + D / k), "SD_Мебель", ink, 25)
            S.line(psp, (L, ty), (L, ty + D / k), "SD_Мебель", ink, 25)
            S.arc(psp, (R - r, ty + r), r, -90, 0, "SD_Мебель", ink, 25)
            if D / k - r > 0.05:
                S.line(psp, (R, ty + r), (R, ty + D / k), "SD_Мебель", ink, 25)
            S.text(psp, "загиб R %d" % ret, (R - r, ty - 3.5), 1.9, "MIDDLE_CENTER", rgb=(90, 90, 90))
        else:
            S.rect(psp, L, ty, R, ty + D / k, "SD_Мебель", (40, 40, 42), 25)
        _vdim(psp, (0, ty), (0, ty + D / k), L, L - 7.0, D)
    _side_column(A, psp, it, k, W, D, H, qty, rooms, B)


def _side_column(A, psp, it, k, W, D, H, qty, rooms, low):
    cx0 = 280.0
    els = it.get("elements") or []
    rows = [[str(i + 1), el["name"], el["material"]] for i, el in enumerate(els)] or [["—", "—", "—"]]
    yb = S.table(psp, cx0, 250.0, [8, 34, 90], ["№", "Элемент", "Материал / отделка"], rows, h=1.8,
                 aligns=["C", "L", "L"], title="Материалы", head_h=5.5)
    data = [["Позиция", it["pos"]], ["Количество", "%d шт." % qty],
            ["Габариты (Ш × Г × В)", "%d × %d × %d мм" % (round(W), round(D), round(H))],
            ["Помещение", rooms], ["Масштаб видов", "1:%d" % k]]
    yb = S.table(psp, cx0, yb - 11.0, [42, 90], ["Параметр", "Значение"], data, h=1.8, aligns=["L", "L"],
                 title="Характеристики", head_h=5.5)
    notes = A.note_lines("item_%s" % it["pos"], it.get("notes") or [])
    if notes:
        S.notes(psp, cx0, yb - 9.0, notes, 131)
