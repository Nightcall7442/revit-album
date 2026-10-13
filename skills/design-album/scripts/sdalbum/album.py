# -*- coding: utf-8 -*-
"""Album builder: sheet registry, scaffolding (frame, header, stamp), viewports, layout, rendering, export."""
import math
import os
import shutil

from PIL import Image

from . import gfx as S
from . import model as M
from .placer import Occ

BRONZE = (168, 132, 82)
COL_X = 303.0
COL_TOP = 258.0
COL_BOTTOM = 36.0
PLAN_AREA = (22.0, 40.0, 300.0, 262.0)      # x0, y0, x1, y1 on the sheet for plan viewports
SCALES = (50, 75, 100)

SHEET_TITLES = {
    "cover": "Обложка", "letter": "Обращение к заказчику", "general": "Общие данные", "measured": "Обмерный план",
    "partitions": "План монтажа перегородок", "furniture": "План расстановки мебели", "floors": "План полов",
    "ceilings": "План потолков", "lighting": "План освещения", "sockets": "План розеток и электровыводов",
    "plumbing": "План сантехники", "finishes": "План отделки стен", "openings": "Ведомость заполнения проёмов",
}
DEFAULT_ORDER = ["cover", "letter", "general", "measured", "partitions", "furniture", "floors", "ceilings", "lighting",
                 "sockets", "plumbing", "finishes", "elevations", "openings"]


class Column:
    """Right-hand column of a plan sheet: stacks legend / tables / notes top-down and reports overflow."""

    def __init__(self, album, psp, x=COL_X, top=COL_TOP, bottom=COL_BOTTOM, width=109.0):
        self.a, self.psp, self.x, self.y, self.bottom, self.w = album, psp, x, top, bottom, width

    def legend(self, items, title="Условные обозначения", rh=6.0):
        w1 = 18.0
        self.y = S.legend(self.psp, self.x, self.y, items, title=title, w1=w1, w2=self.w - w1, rh=rh) - 9.0
        self._check()

    def legend_table(self, items, header, widths, title="Условные обозначения и спецификация", rh=5.2, h=1.45, aligns=None):
        """Legend + specification in one table: items = [(draw_fn | None, [cells...])]."""
        sc = self.w / float(sum(widths))
        wc = [w * sc for w in widths]
        rows = [[""] + list(cells) for fn, cells in items]
        geo = []
        bottom = S.table(self.psp, self.x, self.y, wc, header, rows, h=h, row_h=rh, head_h=5.5, aligns=aligns, title=title,
                         out_rows=geo)
        for (fn, _), (top, hh) in zip(items, geo):
            if fn is not None:
                fn(self.psp, self.x + wc[0] / 2.0, top - hh / 2.0)
        self.y = bottom - 9.0
        self._check()

    def table(self, widths, header, rows, title=None, h=1.6, aligns=None, total=None, head_h=5.5, zebra=False,
              allow_band=True):
        sc = self.w / float(sum(widths))
        widths_c = [w * sc for w in widths]
        need = S.table_height(widths_c, header, rows, h, head_h, title, total=total)
        if self.y - need < self.bottom and allow_band and self.a.band_free(need):
            bx, by, bw = self.a.take_band(need)
            sc2 = bw / float(sum(widths))
            S.table(self.psp, bx, by, [w * sc2 for w in widths], header, rows, h=h, aligns=aligns, title=title,
                    total=total, head_h=head_h, zebra=zebra)
            return
        self.y = S.table(self.psp, self.x, self.y, widths_c, header, rows, h=h, aligns=aligns, title=title, total=total,
                         head_h=head_h, zebra=zebra) - 9.0
        self._check()

    def notes(self, lines):
        if not lines:
            return
        m = S.notes(self.psp, self.x, self.y, lines, self.w - 1)
        n = sum(max(1, math.ceil(S.tw(l, 2.1) / (self.w - 1))) for l in lines)
        self.y -= 4.0 + n * 2.1 * 1.667 * 1.3
        self._check()

    def _check(self):
        if self.y < self.bottom:
            self.a.issues.append(dict(code="COLUMN_OVERFLOW", level="error", sheet=self.a.cur_title,
                                      msg="правая колонка не помещается (низ %.0f мм)" % self.y))


class Album:
    def __init__(self, P, out_dir, sheets=None):
        self.P = P
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        S.ensure_fonts()
        self.doc = S.new_doc()
        self.msp = self.doc.modelspace()
        self.doc.filename = os.path.join(out_dir, "album.dxf")
        self.issues = []
        self.layouts = {}
        self.cur_title = ""
        meta = P.meta
        self.info = dict(object=meta.get("object", "Дизайн-проект интерьера"), place=meta.get("place", ""),
                         stage=meta.get("stage", "Дизайн-проект"), date="")
        logo = meta.get("logo") or os.path.join(S.ASSETS, "logo_w.png")
        if not os.path.isabs(logo):
            logo = os.path.join(P.base_dir, logo)
        self.logo_def = self._image("logo.png", logo)
        self.sheet_keys = sheets or P.d.get("sheets") or DEFAULT_ORDER
        self.plan_k, self.plan_win, self.plan_xy = self._plan_layout()
        self.sheets = []        # (no, key, title, scale, builder, arg)
        self._blocks = {}       # offset -> (block, sheet title)
        self._vps = []          # (offset, model window, sheet title)
        self._plan_sheets()

    # ------------------------------------------------------------------ assets
    def _image(self, name, src):
        dst = os.path.join(self.out_dir, name)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy(src, dst)
        sz = Image.open(dst).size
        return self.doc.add_image_def(filename=name, size_in_pixel=sz)

    def image(self, name, src):
        return self._image(name, src)

    # ------------------------------------------------------------------ layout
    def _plan_layout(self):
        x0, y0, x1, y1 = self.P.bounds
        has_axes = bool(self.P.grid.get("x"))
        ml = 1900 if has_axes else 1300
        mb = 2250 if has_axes else 1700
        mr, mt = 720, 880
        if "measured" in self.sheet_keys:          # the measured plan is dimensioned on all four sides
            from . import dims as DM
            mr = max(mr, 450 + (DM.side_rows(self.P, "R") - 1) * 400 + 270)
            mt = max(mt, 450 + (DM.side_rows(self.P, "T") - 1) * 400 + 270)
        ax0, ay0, ax1, ay1 = PLAN_AREA
        for k in SCALES:
            w = (x1 - x0) / k + (ml + mr) / 50.0
            h = (y1 - y0) / k + (mb + mt) / 50.0
            if w <= ax1 - ax0 and h <= ay1 - ay0:
                break
        win = (x0 - ml * k / 50.0, y0 - mb * k / 50.0, x1 + mr * k / 50.0, y1 + mt * k / 50.0)
        w = (win[2] - win[0]) / k
        h = (win[3] - win[1]) / k
        xy = (ax0, ay0 + max(0.0, (ay1 - ay0 - h) / 2.0) + 6.0)
        if xy[1] + h > ay1:
            xy = (ax0, ay1 - h)
        return k, win, xy

    def _plan_sheets(self):
        P = self.P
        from . import sheets_plans as SP
        from . import sheets_misc as SM
        from . import sheets_details as SD
        reg = {
            "cover": (SM.cover, None), "letter": (SM.letter, None), "general": (SM.general, None),
            "measured": (SP.measured, "1:%d" % self.plan_k), "partitions": (SP.partitions, "1:%d" % self.plan_k),
            "furniture": (SP.furniture, "1:%d" % self.plan_k), "floors": (SP.floors, "1:%d" % self.plan_k),
            "ceilings": (SP.ceilings, "1:%d" % self.plan_k), "lighting": (SP.lighting, "1:%d" % self.plan_k),
            "sockets": (SP.sockets, "1:%d" % self.plan_k), "plumbing": (SP.plumbing, "1:%d" % self.plan_k),
            "finishes": (SP.finishes, "1:%d" % self.plan_k),
            "openings": (SD.openings_schedule, "1:%d" % SD.openings_k(P)),
        }
        n = 0
        for key in self.sheet_keys:
            if key == "elevations":
                for title, scale, fn, arg in SD.elevation_sheets(self):
                    n += 1
                    self.sheets.append((n, key, title, scale, fn, arg))
                continue
            if key not in reg:
                continue
            if not SP.has_data(self, key) or not SM.has_data(self, key):
                continue
            fn, scale = reg[key]
            n += 1
            self.sheets.append((n, key, SHEET_TITLES[key], scale, fn, None))
        self.total = n

    def sheet_no(self, key):
        for no, k, *_ in self.sheets:
            if k == key:
                return no
        return None

    # ------------------------------------------------------------------ scaffolding
    def make_sheet(self, no, title, scale, subtitle=None, header=True, stamp=True):
        self.cur_title = "%02d %s" % (no, title)
        name = self.cur_title.replace(".", "").replace(":", "")[:60]
        psp = self.doc.layouts.new(name)
        psp.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")
        if stamp:
            S.frame(psp)
            S.stamp(psp, self.logo_def, no, self.total, title, scale, self.info)
        if header:
            S.text(psp, "%02d" % no, (26, 268.5), 10.0, "BOTTOM_LEFT", "SD_Текст", bold=True, rgb=BRONZE)
            ttl = title
            h = 5.6
            while S.tw(ttl, h, True) > 360 and h > 4.0:
                h -= 0.2
            S.text(psp, ttl, (47, 274.0), h, "BOTTOM_LEFT", "SD_Текст", bold=True)
            if subtitle:
                hs = 2.5
                while S.tw(subtitle, hs) > 362 and hs > 1.8:
                    hs -= 0.1
                S.text(psp, subtitle, (47, 268.6), hs, "BOTTOM_LEFT", "SD_Текст", rgb=(115, 115, 115))
            S.line(psp, (26, 265), (412, 265), "SD_Тонкие", (200, 200, 200), 13)
            S.line(psp, (26, 265), (44, 265), "SD_Тонкие", BRONZE, 50)
        self.layouts[no] = psp
        return psp

    def model_block(self, no, sub=0):
        name = "SD_%02d_%d" % (no, sub)
        blk = self.doc.blocks.new(name)
        off = (no * 60000.0 + sub * 18000.0, 0.0 if sub == 0 else -40000.0)
        self.msp.add_blockref(name, off)
        self._blocks[off] = (blk, self.cur_title)
        from . import placer
        placer.CUR_BLOCK = off
        return blk, off

    def vp(self, psp, off, window, xy, k):
        x0, y0, x1, y1 = window
        w, h = (x1 - x0) / k, (y1 - y0) / k
        rect = (xy[0], xy[1], xy[0] + w, xy[1] + h)
        self._vps.append((off, window, self.cur_title, rect, k))
        S.viewport(psp, xy[0] + w / 2.0, xy[1] + h / 2.0, w, h, (off[0] + (x0 + x1) / 2.0, off[1] + (y0 + y1) / 2.0), k)
        return rect

    def band_free(self, need):
        """Free band under the plan viewport, left of the title block."""
        top = self.plan_xy[1] - 3.0 - self._band_used
        return top - need >= 36.0 and self._band_used == 0.0

    def take_band(self, need):
        top = self.plan_xy[1] - 3.0
        self._band_used = need
        return 24.0, top - (5.0 if True else 0.0), 158.0

    def plan_sheet(self, no, title, scale, subtitle):
        self._band_used = 0.0
        psp = self.make_sheet(no, title, scale, subtitle)
        blk, off = self.model_block(no)
        self.vp(psp, off, self.plan_win, self.plan_xy, self.plan_k)
        occ = Occ()
        from shapely.geometry import box as _box
        occ.bounds = _box(*self.plan_win).buffer(-0.6 * self.plan_k)
        return psp, blk, occ

    def title_note(self, psp, x, y, title, note, h=3.4, hn=2.4):
        S.text(psp, title, (x, y), h, "BOTTOM_LEFT", bold=True)
        if note:
            S.text(psp, note, (x + S.tw(title, h, True) + 3.0, y), hn, "BOTTOM_LEFT", rgb=(120, 120, 120))

    def note_lines(self, key, default):
        o = self.P.notes.get(key)
        if o is None:
            return default
        if isinstance(o, dict):
            return list(default) + list(o.get("add", []))
        return list(o)

    # ------------------------------------------------------------------ build / output
    def build(self, heal=True):
        """Draw every sheet. heal: a sheet whose QA finds a line through a text is drawn again with those lines as
        obstacles for the labels (learnt from its own check, up to 2 rounds; the better version is kept)."""
        self.healed = {}
        for sheet in self.sheets:
            self._draw(sheet)
            if heal and sheet[1] not in ("cover", "letter"):
                self._heal(sheet)
        return self

    def _draw(self, sheet, hints=None):
        from . import placer
        no, key, title, scale, fn, arg = sheet
        placer.HINTS = hints or {}
        try:
            if arg is None:
                fn(self, no, title, scale)
            else:
                fn(self, no, title, scale, arg)
            placer.flush_all()
        finally:
            placer.HINTS = {}
            placer.CUR_BLOCK = None

    def _sheet_qa(self, no):
        from . import qa
        lay = self.layouts[no]
        issues, _ = qa.check_layout(self.doc, lay, True)
        title = self._title_of(no)
        issues += [i for i in self.check_clipping() if i.get("sheet") == title]
        return issues

    @staticmethod
    def _score(issues):
        return sum(1000 if i["level"] == "error" else 1 for i in issues)

    def _heal(self, sheet, rounds=2):
        no = sheet[0]
        issues = self._sheet_qa(no)
        if not any(i["code"] == "LINE_THROUGH_TEXT" for i in issues):
            return
        best = (self._score(issues), {}, issues)
        hints = {}
        for _ in range(rounds):
            new = self._hints(no, issues)
            if not new:
                break
            for off, gs in new.items():
                hints.setdefault(off, []).extend(gs)
            self._drop_sheet(no)
            self._draw(sheet, {k_: list(v) for k_, v in hints.items()})
            issues = self._sheet_qa(no)
            sc = self._score(issues)
            if sc < best[0]:
                best = (sc, {k_: list(v) for k_, v in hints.items()}, issues)
            if not any(i["code"] == "LINE_THROUGH_TEXT" for i in issues):
                break
        if self._score(issues) != best[0]:          # the last round was not the best one: draw the best again
            self._drop_sheet(no)
            self._draw(sheet, best[1])
        self.healed[no] = dict(score=best[0], hints=sum(len(v) for v in best[1].values()))

    def _hints(self, no, issues):
        """Lines crossing texts (paper mm) -> obstacles in the coordinates of the block shown in that viewport."""
        from shapely.geometry import LineString, Point
        title = self._title_of(no)
        vps = [v for v in self._vps if v[2] == title]
        out = {}
        for i in issues:
            if i["code"] != "LINE_THROUGH_TEXT":
                continue
            for cs in i.get("cross", []):
                ln = LineString(cs)
                m = ln.interpolate(0.5, normalized=True)
                for off, win, t, rect, k in vps:
                    if rect[0] <= m.x <= rect[2] and rect[1] <= m.y <= rect[3]:
                        loc = LineString([(win[0] + (x - rect[0]) * k, win[1] + (y - rect[1]) * k) for x, y in cs])
                        out.setdefault(off, []).append(loc.buffer(0.3 * k))
                        break
        return out

    def _title_of(self, no):
        for n, key, title, scale, fn, arg in self.sheets:
            if n == no:
                return "%02d %s" % (no, title)
        return None

    def _drop_sheet(self, no):
        """Remove a drawn sheet (layout, its model blocks, viewport records, build issues) to draw it again."""
        title = self._title_of(no)
        psp = self.layouts.pop(no)
        self.doc.layouts.delete(psp.name)
        for off, (blk, t) in list(self._blocks.items()):
            if t != title:
                continue
            for e in list(self.msp.query("INSERT")):
                if e.dxf.name == blk.name:
                    self.msp.delete_entity(e)
            self.doc.blocks.delete_block(blk.name, safe=False)
            del self._blocks[off]
        self._vps = [v for v in self._vps if v[2] != title]
        self.issues = [i for i in self.issues if i.get("sheet") != title]

    def check_clipping(self, tol=2.0):
        """Every entity of a sheet block must lie completely inside one of the viewports showing that block:
        a dimension, label or symbol cut by the viewport edge is an error (CONTENT_CLIPPED)."""
        from ezdxf import bbox
        wins = {}
        for off, w, t, *_ in self._vps:
            wins.setdefault(off, []).append(w)
        out = []
        for off, (blk, title) in self._blocks.items():
            ws = wins.get(off, [])
            bad = []
            for e in blk:
                if e.dxftype() not in ("TEXT", "MTEXT", "DIMENSION") and e.dxf.layer not in ("SD_Текст", "SD_Размеры"):
                    continue            # drawing geometry may be cropped by the view on purpose (enlarged plans)
                try:
                    bb = bbox.extents([e], fast=False)
                except Exception:
                    continue
                if not bb.has_data:
                    continue
                (ax, ay, _), (bx, by, _) = bb.extmin, bb.extmax
                if not any(ax >= w[0] - tol and ay >= w[1] - tol and bx <= w[2] + tol and by <= w[3] + tol for w in ws):
                    bad.append((e.dxftype(), (ax + bx) / 2.0, (ay + by) / 2.0))
            if bad:
                kinds = {}
                for t, x, y in bad:
                    kinds[t] = kinds.get(t, 0) + 1
                x, y = bad[0][1], bad[0][2]
                out.append(dict(code="CONTENT_CLIPPED", level="error", sheet=title,
                                msg="%s: %d надписей/размеров выходят за видовой экран (%s), напр. у точки (%.0f, %.0f)" % (
                                    title, len(bad), ", ".join("%s×%d" % kv for kv in kinds.items()), x, y)))
        return out

    def save_dxf(self, path):
        self.doc.saveas(path)

    def render_pdf(self, pdf_path, png_dir=None, dpi=110, nos=None):
        import pymupdf
        from ezdxf.addons.drawing import Frontend, RenderContext, layout, config
        from ezdxf.addons.drawing import pymupdf as pmb
        from ezdxf.math import BoundingBox2d
        cfg = config.Configuration(lineweight_policy=config.LineweightPolicy.ABSOLUTE,
                                   background_policy=config.BackgroundPolicy.WHITE,
                                   image_policy=config.ImagePolicy.DISPLAY)
        out = pymupdf.open()
        BB = BoundingBox2d([(0, 0), (420, 297)])
        page = layout.Page(420, 297, layout.Units.mm, margins=layout.Margins.all(0))
        for no in sorted(self.layouts):
            if nos and no not in nos:
                continue
            psp = self.layouts[no]
            ctx = RenderContext(self.doc)
            ctx.set_current_layout(psp)
            be = pmb.PyMuPdfBackend()
            Frontend(ctx, be, config=cfg).draw_layout(psp, finalize=True)
            b = be.get_pdf_bytes(page, settings=layout.Settings(fit_page=True, output_layers=False), render_box=BB)
            src = pymupdf.open("pdf", b)
            out.insert_pdf(src)
            if png_dir:
                os.makedirs(png_dir, exist_ok=True)
                src[0].get_pixmap(dpi=dpi).save(os.path.join(png_dir, "s%02d.png" % no))
        out.save(pdf_path, garbage=3, deflate=True)
        return pdf_path


def build(project_path, out_dir, sheets=None):
    P = M.load(project_path)
    A = Album(P, out_dir, sheets)
    A.build()
    return A
