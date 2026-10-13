# -*- coding: utf-8 -*-
"""Importers: unit guess for 3ds Max scenes, wall / opening / room extraction from a DXF plan."""
import json

from shapely.geometry import box


def test_max_units_guess():
    from importers.max_scene import guess_units
    rows = [dict(cls="Editable Poly", **{"class": "Editable Poly"}, bbox=[[0, 0, 0], [400, 40, 280]])] * 10
    assert guess_units(rows)[0] == "cm"
    rows = [dict(**{"class": "Editable Poly"}, bbox=[[0, 0, 0], [4000, 400, 2800]])] * 10
    assert guess_units(rows)[0] == "mm"


def test_section_of_a_box():
    import numpy as np
    from importers.max_scene import section
    v = np.array([[0, 0, 0], [1000, 0, 0], [1000, 200, 0], [0, 200, 0],
                  [0, 0, 2800], [1000, 0, 2800], [1000, 200, 2800], [0, 200, 2800]], float)
    faces = [(0, [0, 1, 5, 4]), (0, [1, 2, 6, 5]), (0, [2, 3, 7, 6]), (0, [3, 0, 4, 7])]
    segs = section(v, faces, 1100)
    length = sum(((s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2) ** 0.5 for s in segs)
    assert abs(length - 2400) < 1e-6           # perimeter of the 1000 x 200 cut


def test_gaps_become_openings():
    from importers.dxf_plan import close_gaps
    # two wall runs with a 900 door gap, and a short stub that must NOT create a gap across the room
    walls = [box(0, 0, 3000, 120), box(3900, 0, 6000, 120), box(0, 3000, 120, 3150)]
    gaps = close_gaps(walls)
    assert len(gaps) == 1
    g, horiz = gaps[0]
    assert tuple(round(v) for v in g.bounds) == (3000, 0, 3900, 120)


def _plan_dxf(path):
    import ezdxf
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("A-WALL")
    doc.layers.add("Помещения")
    # 6000 x 4000 flat, 300 walls, one 900 door gap in the bottom wall, one 1500 window gap in the top wall
    rects = [(-300, -300, 2000, 0), (2900, -300, 6300, 0), (-300, 4000, 1500, 4300), (3000, 4000, 6300, 4300),
             (-300, 0, 0, 4000), (6000, 0, 6300, 4000)]
    for x0, y0, x1, y1 in rects:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "A-WALL"})
    msp.add_text("Гостиная", dxfattribs={"layer": "Помещения", "height": 250, "insert": (2500, 2000)})
    doc.saveas(path)


def test_dxf_import_draft_builds_rooms(tmp_path):
    from importers import dxf_plan
    from sdalbum import model
    src = str(tmp_path / "plan.dxf")
    _plan_dxf(src)
    dxf_plan.main(src, str(tmp_path / "out"))
    d = json.load(open(tmp_path / "out" / "draft_project.json", encoding="utf-8"))
    kinds = sorted(o["kind"] for o in d["openings"])
    assert kinds == ["window", "window"] or kinds == ["door", "window"]
    widths = sorted(o["w"] for o in d["openings"])
    assert widths == [900, 1500]
    P = model.Project(d, str(tmp_path))
    assert len(P.rooms) == 1 and abs(P.rooms[0]["area_exact"] - 24.0) < 0.01
    assert (tmp_path / "out" / "plan.png").exists()


def _plan_pdf(path, with_dims=True):
    """A vector PDF like an architect's export: walls as dark fills at 1:50 on A3, dimension lines with numbers."""
    import pymupdf
    pt = 72.0 / 25.4
    doc = pymupdf.open()
    pg = doc.new_page(width=420 * pt, height=297 * pt)
    H = 297 * pt

    def R(x0, y0, x1, y1):                 # model mm -> paper rect (1:50, origin at 100/80 mm, y up)
        return pymupdf.Rect((100 + x0 / 50.0) * pt, H - (80 + y1 / 50.0) * pt, (100 + x1 / 50.0) * pt, H - (80 + y0 / 50.0) * pt)
    for r in [(-300, -300, 2000, 0), (2900, -300, 6300, 0), (-300, 4000, 1500, 4300), (3000, 4000, 6300, 4300),
              (-300, 0, 0, 4000), (6000, 0, 6300, 4000)]:
        pg.draw_rect(R(*r), color=None, fill=(0.15, 0.15, 0.16))
    if with_dims:
        y = H - (80 - 1000 / 50.0) * pt
        pg.draw_line(((100 - 300 / 50.0) * pt, y), ((100 + 6300 / 50.0) * pt, y), color=(0, 0, 0), width=0.3)
        pg.insert_text(((100 + 2900 / 50.0) * pt, y - 1.0 * pt), "6600", fontsize=6)
        x = (100 - 1100 / 50.0) * pt
        pg.draw_line((x, H - (80 - 300 / 50.0) * pt), (x, H - (80 + 4300 / 50.0) * pt), color=(0, 0, 0), width=0.3)
        pg.insert_text((x - 1.0 * pt, H - (80 + 1800 / 50.0) * pt), "4600", fontsize=6, rotate=90)
        y2 = H - (80 - 600 / 50.0) * pt
        pg.draw_line(((100 + 0) * pt, y2), ((100 + 2000 / 50.0) * pt, y2), color=(0, 0, 0), width=0.3)
        pg.insert_text(((100 + 800 / 50.0) * pt, y2 - 1.0 * pt), "2000", fontsize=6)
    pg.insert_text(((100 + 2500 / 50.0) * pt, H - (80 + 2000 / 50.0) * pt), "Гостиная", fontsize=8,
                   fontname="helv")
    doc.save(path)


def test_vector_pdf_scale_found_and_walls_imported(tmp_path):
    from importers import pdf_plan
    from sdalbum import autofix, model
    src = str(tmp_path / "plan.pdf")
    _plan_pdf(src)
    a = pdf_plan.analyse(src)
    scale, votes = pdf_plan.detect_scale(a)
    assert scale == 50, votes
    res = pdf_plan.main(src, str(tmp_path / "imp"))
    assert res["status"] == "ok" and res["scale"] == 50
    d = json.load(open(tmp_path / "imp" / "draft_project.json", encoding="utf-8"))
    d2, log, rest, qs = autofix.fix(d, str(tmp_path))
    P = model.Project(d2, str(tmp_path))
    assert len(P.rooms) == 1 and abs(P.rooms[0]["area"] - 24.0) < 0.1
    assert sorted(o["w"] for o in d2["openings"]) == [900, 1500]


def test_pdf_without_dimensions_asks_for_scale(tmp_path):
    from importers import pdf_plan
    src = str(tmp_path / "plan.pdf")
    _plan_pdf(src, with_dims=False)
    res = pdf_plan.main(src, str(tmp_path / "imp"))
    assert res["status"] == "no_scale"
    assert (tmp_path / "imp" / "page-1.png").exists()


def test_hatch_with_holes_is_not_a_solid_block(tmp_path):
    """A wall hatch drawn around the rooms (outer contour + room holes) must not turn the flat into one wall."""
    import ezdxf
    from importers import dxf_plan
    from sdalbum import autofix, model
    doc = ezdxf.new(setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    doc.layers.add("A-WALL")
    h = msp.add_hatch(dxfattribs={"layer": "A-WALL"})
    h.paths.add_polyline_path([(-300, -300), (6300, -300), (6300, 4300), (-300, 4300)], is_closed=True)
    h.paths.add_polyline_path([(0, 0), (6000, 0), (6000, 4000), (0, 4000)], is_closed=True)
    src = str(tmp_path / "h.dxf")
    doc.saveas(src)
    dxf_plan.main(src, str(tmp_path / "imp"))
    d = json.load(open(tmp_path / "imp" / "draft_project.json", encoding="utf-8"))
    d2, log, rest, qs = autofix.fix(d, str(tmp_path))
    P = model.Project(d2, str(tmp_path))
    assert len(P.rooms) == 1 and abs(P.rooms[0]["area"] - 24.0) < 0.05


def test_gap_kind_by_what_is_drawn():
    """Window = frame lines across the gap; door = swing arc ending on the opening; glazing + arc in the facade =
    balcony door; nothing drawn: facade -> window, wide interior gap -> passage (lesson L-054)."""
    from shapely.geometry import LineString, Point, box
    from importers.dxf_plan import _gap_kind
    g = box(1000, 0, 2000, 300)                       # gap 1000 in a horizontal wall, measured along x
    frames = [(LineString([(1000, 140), (2000, 140)]), False), (LineString([(1000, 160), (2000, 160)]), False)]
    arc = [(Point(1000, 300).buffer(900).exterior.intersection(box(1000, 300, 1900, 1200)), True)]
    assert _gap_kind(g, True, frames, True, 1000) == "window"
    assert _gap_kind(g, True, arc, True, 1000) == "door"
    assert _gap_kind(g, True, frames + arc, True, 1000) == "balcony"
    assert _gap_kind(g, True, [], True, 1000) == "window"
    assert _gap_kind(box(0, 0, 1800, 300), True, [], False, 1800) == "passage"
    assert _gap_kind(g, True, [], False, 1000) == "door"
