# -*- coding: utf-8 -*-
"""Geometry core: rooms, areas, existing spaces, wall gaps, floors."""
import pytest
from shapely.geometry import Point


def test_urgench_rooms_and_total(urgench):
    assert len(urgench.rooms) == 7
    assert abs(urgench.total_area() - 45.29) < 0.005
    a = {r["name"]: r["area"] for r in urgench.rooms}
    assert a["Гостиная"] == 13.98             # 3820 x 3660 in the clear, the 1800 passage is not part of the room
    assert a["Кухня-столовая"] == 6.95
    names = {r["name"] for r in urgench.rooms}
    assert {"Прихожая", "Гостиная", "Кухня-столовая", "Спальня"} <= names


def test_room_areas_are_rounded_from_exact(urgench):
    for r in urgench.rooms:
        assert abs(r["area"] - round(r["area_exact"], 2)) < 1e-9
    assert urgench.total_area() == round(sum(r["area"] for r in urgench.rooms), 2)   # the column adds up


def test_studio_rooms(make_project):
    P = make_project()
    a = {r["name"]: r["area_exact"] for r in P.rooms}
    assert abs(a["Ванная"] - 2.0 * 1.5) < 1e-6          # 2000 x 1500 inside the partitions
    assert abs(a["Комната"] - (24.0 - 2.1 * 1.6)) < 1e-6


def test_seed_in_wall_is_reported(make_project):
    def bad(d):
        d["rooms"][0]["seed"] = [-150, 1000]           # inside the exterior wall
    with pytest.raises(ValueError):
        make_project(bad)


def test_throat_between_existing_walls(urgench):
    cuts = urgench.throats()
    assert len(cuts) == 1
    x0, y0, x1, y1 = cuts[0].bounds
    assert (round(x0), round(y0), round(x1), round(y1)) == (7640, 710, 8040, 2510)


def test_existing_spaces_split_at_gaps(urgench):
    sp = urgench.existing_spaces()
    assert len(sp) == 3
    assert any(len(rooms) == 1 and rooms[0]["name"] == "Кухня-столовая" for _, rooms in sp)


def test_outline_has_no_collinear_vertices(urgench):
    from sdalbum import dims
    poly = dims.outline_of(urgench)
    cs = list(poly.exterior.coords)[:-1]
    n = len(cs)
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = cs[i - 1], cs[i], cs[(i + 1) % n]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        assert abs(cross) > 1.0, "collinear vertex %s gives a fake dimension segment" % (cs[i],)


def test_floor_zones_never_run_under_walls(urgench):
    from shapely.ops import unary_union
    windows = unary_union([urgench.open_shape[o["id"]] for o in urgench.openings if o["kind"] == "window"])
    for f, g in urgench.floor_zones():
        assert g.intersection(windows).area < 1.0, f["id"]
        assert g.intersection(urgench.shell.difference(
            unary_union(list(urgench.open_shape.values())))).area < 1.0, f["id"]


def test_room_of_point(urgench):
    r = urgench.room_of_point((1800, 1600))
    assert r["name"] == "Спальня"
    assert urgench.room_of_point((-1000, -1000)) is None
