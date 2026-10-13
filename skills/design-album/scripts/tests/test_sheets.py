# -*- coding: utf-8 -*-
"""Semantic checks of individual sheets (what a chief architect looks at, beyond 'nothing overlaps')."""
import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from conftest import URGENCH, STUDIO


def _sheet(path, key, tmp_path):
    """Plan the full album (correct sheet numbers) but draw only sheet `key`; returns (Album, no, block)."""
    from sdalbum import album
    from sdalbum.placer import flush_all
    from sdalbum import model
    A = album.Album(model.load(path), str(tmp_path))
    for no, k, title, scale, fn, arg in A.sheets:
        if k == key:
            fn(A, no, title, scale) if arg is None else fn(A, no, title, scale, arg)
            flush_all()
            return A, no, A.doc.blocks.get("SD_%02d_0" % no)
    raise KeyError(key)


def _texts(blk):
    for e in blk:
        if e.dxftype() == "TEXT":
            yield e, e.get_placement()[1]


def _dims(blk):
    return [e for e in blk if e.dxftype() == "DIMENSION"]


@pytest.mark.parametrize("path,key", [(URGENCH, "lighting"), (URGENCH, "measured"), (URGENCH, "sockets"),
                                      (STUDIO, "lighting"), (STUDIO, "plumbing")])
def test_no_sliver_dimensions(path, key, tmp_path):
    """A 5 / 15 / 18 mm segment on a 1:50 plan is model noise (spot 18 mm off the track end) - never a binding."""
    A, no, blk = _sheet(path, key, tmp_path)
    small = [round(d.get_measurement(), 1) for d in _dims(blk) if d.get_measurement() < 25]
    assert small == []


def test_lighting_binds_track_not_spots(tmp_path):
    from sdalbum import model, sheets_plans as SP
    P = model.load(URGENCH)
    liv = P.room_by_name["Гостиная"]
    xs, ys = SP.binding_coords(P, liv)
    spots = [f for f in P.lighting if f["kind"] == "track_spot" and liv["shp"].contains(Point(f["x"], f["y"]))]
    assert spots, "fixture changed"
    for f in spots:
        assert round(f["y"]) not in [round(v) for v in ys] or round(f["y"]) in (855, 3355)


def test_socket_labels_stay_in_rooms(tmp_path):
    A, no, blk = _sheet(URGENCH, "sockets", tmp_path)
    rooms = unary_union([r["shp"] for r in A.P.rooms]).buffer(60)
    labels = [(e.dxf.text, p) for e, p in _texts(blk) if e.dxf.text.startswith("h") and "гр." in e.dxf.text]
    assert labels
    for s, p in labels:
        assert rooms.contains(Point(p[0], p[1])), "label %r outside the rooms at %s" % (s, p)


def test_furniture_marks_on_own_items(tmp_path):
    from sdalbum import sheets_plans as SP
    A, no, blk = _sheet(URGENCH, "furniture", tmp_path)
    P = A.P
    groups = {str(g["pos"]): g for g in SP.furniture_groups(P)}
    k = A.plan_k
    allp = [(f, Polygon(f["poly"]).buffer(0)) for f in P.furniture]
    marks = [(e.dxf.text, p) for e, p in _texts(blk) if e.dxf.text in groups and e.rgb == (60, 45, 20)]
    assert len(marks) == sum(len(g["items"]) for g in groups.values())
    for s, p in marks:
        own = [Polygon(f["poly"]).buffer(0) for f in groups[s]["items"]]
        pt = Point(p[0], p[1])
        assert any(o.buffer(9 * k).contains(pt) for o in own), "mark %s far from its item" % s
        for f, g in allp:
            if f in groups[s]["items"] or any(g.intersection(o).area > 0.3 * min(g.area, o.area) for o in own):
                continue
            if f.get("kind") == "rug":
                continue
            assert not g.buffer(-1.0 * k).contains(pt), "mark %s sits on «%s»" % (s, f["name"])


def test_node_callout_points_to_nodes_sheet(tmp_path):
    from sdalbum import sheets_plans as SP
    A, no, blk = _sheet(URGENCH, "ceilings", tmp_path)
    target = SP.node_sheet(A)
    assert target is not None
    assert [t for _, _, t, *_ in A.sheets][target - 1] == "Узлы"
    refs = [e.dxf.text for e, _ in _texts(blk) if e.rgb == (90, 90, 90)]
    assert refs and all(r == str(target) for r in refs)


def test_section_level_value_below_the_line():
    from sdalbum import gfx as S
    from sdalbum import symbols as Y
    S.ensure_fonts()
    doc = S.new_doc()
    msp = doc.modelspace()
    g = Y.section_level(msp, (0, 2800), "+2,800", 10)
    assert g.bounds[3] <= 2800 + 1e-6               # nothing above the underside: the value never sits in the ceiling


def test_opening_scheme_note_follows_gost(tmp_path):
    A, no, _ = _sheet(STUDIO, "openings", tmp_path)
    psp = A.layouts[no]
    txt = " ".join(e.dxf.text for e in psp if e.dxftype() == "TEXT") + " ".join(
        e.text for e in psp if e.dxftype() == "MTEXT")
    assert "основание треугольника - сторона петель" in txt
    assert "вершина треугольника - со стороны петель" not in txt


def test_cover_logo_visible(tmp_path):
    """The logo must really be on the rendered cover (RGBA images were silently dropped by the PDF renderer)."""
    import numpy as np
    from PIL import Image
    from sdalbum import album, model
    from sdalbum.placer import flush_all
    A = album.Album(model.load(URGENCH), str(tmp_path), ["cover"])
    A.build()
    A.render_pdf(str(tmp_path / "c.pdf"), str(tmp_path / "png"), dpi=60)
    im = np.array(Image.open(tmp_path / "png" / "s01.png").convert("L")).astype(float)
    k = 60 / 25.4
    crop = im[int((297 - 262) * k):int((297 - 234) * k), int(30 * k):int(146 * k)]
    assert (crop < 90).mean() > 0.08, "logo not visible on the cover"


def test_measured_binds_passage_and_interior_doors(tmp_path):
    A, no, blk = _sheet(URGENCH, "measured", tmp_path)
    m = [round(d.get_measurement()) for d in _dims(blk)]
    assert 1800 in m, "passage between the living room and the kitchen has no width"
    assert 1000 in m, "interior door Д-2 is not dimensioned"
    texts = [e.dxf.text for e, _ in _texts(blk)]
    assert any(t.startswith("проём 1800") for t in texts)


def test_no_binding_text_on_door_leaves(tmp_path):
    from sdalbum import symbols as Y
    A, no, blk = _sheet(URGENCH, "lighting", tmp_path)
    swings = [Y.door_swing_area(A.P, o).buffer(-60) for o in A.P.openings if o["kind"] in ("door", "balcony")]
    for d in _dims(blk):
        p = d.dxf.text_midpoint
        for g in swings:
            assert not g.contains(Point(p[0], p[1])), "dimension %d on a door swing" % round(d.get_measurement())


def test_socket_label_pairs_heights_with_groups():
    from sdalbum.sheets_plans import socket_label
    c = [dict(h=300, group="6"), dict(h=2150, group="5")]
    assert socket_label(c) == "h300 гр.6; h2150 гр.5"
    assert socket_label([dict(h=300, group="5"), dict(h=1100, group="5")]) == "h300/1100 · гр.5"


def test_socket_bindings_are_real_positions(tmp_path):
    A, no, blk = _sheet(URGENCH, "sockets", tmp_path)
    m = [round(d.get_measurement()) for d in _dims(blk)]
    assert 400 in m          # 1650 -> 2050 on the kitchen wall: two real sockets, not their average 1850


def test_floor_drain_bound_both_ways(tmp_path):
    A, no, blk = _sheet(URGENCH, "plumbing", tmp_path)
    P = A.P
    m = {round(d.get_measurement()) for d in _dims(blk)}
    for o in P.plumbing:
        if o.get("h", 1) == 0:
            r = P.room_of_point((o["x"], o["y"]))
            x0, y0, x1, y1 = r["shp"].bounds
            assert {round(o["x"] - x0), round(x1 - o["x"])} & m, "drain not bound along x"
            assert {round(o["y"] - y0), round(y1 - o["y"])} & m, "drain not bound along y"


def test_elevation_door_width_is_the_opening(urgench):
    from sdalbum.sheets_details import Elev
    for e in urgench.elevations:
        for op in Elev(urgench, e).openings():
            assert abs((op["s1"] - op["s0"]) - op["o"]["w"]) < 1


def test_bulkhead_shown_on_elevation(urgench):
    from sdalbum import gfx as S
    from sdalbum.sheets_details import draw_elevation
    from sdalbum.placer import flush_all
    S.ensure_fonts()
    doc = S.new_doc()
    blk = doc.blocks.new("E")
    hit = 0
    for e in urgench.elevations:
        draw_elevation(blk, urgench, e)
    flush_all()
    texts = [t.dxf.text for t in blk if t.dxftype() == "TEXT"]
    assert any(t.startswith("короб +2,49") for t in texts)


def test_no_duplicate_overall_chain(make_project):
    from sdalbum import gfx as S
    from sdalbum.sheets_details import draw_elevation
    from sdalbum.placer import flush_all
    P = make_project(lambda d: d["plumbing"].clear())
    S.ensure_fonts()
    doc = S.new_doc()
    blk = doc.blocks.new("E")
    draw_elevation(blk, P, P.elevations[0])
    flush_all()
    full = [d for d in blk if d.dxftype() == "DIMENSION" and round(d.get_measurement()) == 2000]
    assert len(full) == 1


def test_door_hands_and_schedule(tmp_path):
    from sdalbum import model
    P = model.load(URGENCH)
    h = {o["id"]: P.door_hand(o) for o in P.openings}
    assert h["Д-1.1"] == "L" and h["Д-2.1"] == "R" and h["Д-4.1"] == "R"
    A, no, _ = _sheet(URGENCH, "openings", tmp_path)
    txt = " ".join(e.dxf.text for e in A.layouts[no] if e.dxftype() == "TEXT")
    assert "Д-1 лев." in txt and "Д-2 прав." in txt


def test_finishes_equal_elevation_tables(urgench):
    from sdalbum.sheets_plans import room_wall_finishes
    from sdalbum.sheets_details import elev_material_areas, groups
    g = {x["name"]: x["elevs"] for x in groups(urgench)}
    for rm, split in room_wall_finishes(urgench):
        if rm["name"] in g and rm.get("cls") == "wet":
            assert abs(split["О2"] - elev_material_areas(urgench, g[rm["name"]])["tile"]) < 0.005


def test_waterproofing_includes_shower_zone(urgench):
    from sdalbum.sheets_details import waterproofing
    r = urgench.room_by_name["Санузел совмещённый"]
    assert waterproofing(urgench, r) > r["area_exact"] + r["perimeter"] * 0.2 + 2.5


def test_general_sheet_lists_client_questions(tmp_path):
    A, no, _ = _sheet(URGENCH, "general", tmp_path)
    txt = " ".join(e.text for e in A.layouts[no] if e.dxftype() == "MTEXT")
    assert "Д-4" in txt and "задевают друг друга" in txt and "задевает" in txt


def test_multipoint_group_wired_once(make_project):
    """Two pass-through switches of one group: the second gets one line to the nearest fixture, not a second web."""
    from sdalbum.sheets_plans import wiring_runs

    def mut(d):
        d["lighting"] += [dict(kind="spot", x=x, y=y, group="Комната") for x, y in ((3000, 600), (4000, 600), (5000, 1800))]
        d["switches"][0]["controls"][0]["mode"] = "pass"
        d["switches"].append(dict(id="В3", x=2100, y=1500, h=900, wall="X+", keys=1,
                                  controls=[{"key": "а", "group": "Комната", "mode": "pass"}]))
    P = make_project(mut)
    runs = [r for r in wiring_runs(P) if r["switch"] in ("В1", "В3")]
    assert len(runs[0]["pts"]) == 7 and len(runs[1]["pts"]) == 2
