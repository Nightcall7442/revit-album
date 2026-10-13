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
