# -*- coding: utf-8 -*-
"""Data rules: every wrong-but-clean-looking drawing seen so far is a rule here."""
from sdalbum import validate


def codes(P, level=None):
    return [i["code"] for i in validate.run(P) if level is None or i["level"] == level]


def test_reference_projects_are_clean(urgench, make_project):
    assert codes(urgench, "error") == []
    assert codes(make_project()) == []


def test_opening_outside_wall(make_project):
    def m(d):
        d["openings"][0]["c"] = 6500
    assert "OPENING_OUT_OF_WALL" in codes(make_project(m))


def test_furniture_outside_room(make_project):
    def m(d):
        d["furniture"][0]["poly"] = [[6500, 100], [7000, 100], [7000, 600], [6500, 600]]
    c = codes(make_project(m))
    assert "FURN_OUTSIDE_ROOM" in c or "FURN_NO_ROOM" in c or "FURN_IN_WALL" in c


def test_socket_height_and_wet_zone(make_project):
    def m(d):
        d["sockets"][0]["h"] = 5000
        d["sockets"].append({"kind": "Р2", "x": 2000, "y": 3300, "h": 1000, "wall": "X-", "group": "2"})
    c = codes(make_project(m))
    assert "SOCKET_HEIGHT" in c
    assert "SOCKET_WET" in c


def test_socket_wrong_wall_side(make_project):
    def m(d):
        d["sockets"][0]["wall"] = "X-"
    assert "SOCKET_WALL_SIDE" in codes(make_project(m))


def test_switch_not_on_wall(make_project):
    def m(d):
        d["switches"][0]["x"] = 5000
    assert "SWITCH_NOT_ON_WALL" in codes(make_project(m))


def test_mirrored_elevation(make_project):
    def m(d):
        e = d["elevations"][0]
        e["a"], e["b"] = e["b"], e["a"]
    assert "ELEV_MIRRORED" in codes(make_project(m))


def test_model_slivers_are_flagged(make_project):
    def m(d):
        e = d["elevations"][0]
        e["heights"] = [0, 100, 860, 900, 2200, 2687, 2700]
        e["items"] = [dict(type="base", s0=0, s1=526, z0=100, z1=860), dict(type="base", s0=530, s1=1051, z0=100, z1=860)]
        e["module_chain"] = [0, 526.5, 1051]
    c = codes(make_project(m))
    assert "ELEV_SMALL_GAP" in c
    assert "MODULES_NEAR_EQUAL" in c
    assert "NOT_SNAPPED" in c


def test_door_hits_furniture(make_project):
    def m(d):
        d["furniture"].append({"name": "Тумба", "kind": "cabinet", "room": "Ванная",
                               "poly": [[700, 2500], [1300, 2500], [1300, 2900], [700, 2900]]})
    assert "DOOR_HITS_FURNITURE" in codes(make_project(m))


def test_bulkhead_below_ceiling(make_project):
    def m(d):
        d["ceilings"]["types"].append({"id": "Т2", "kind": "bulkhead"})
        d["ceilings"]["zones"].append({"type": "Т2", "kind": "bulkhead", "name": "Короб",
                                       "poly": [[3000, 200], [3400, 200], [3400, 1000], [3000, 1000]], "bottom": 2800})
    assert "BULKHEAD_LEVEL" in codes(make_project(m))


def test_floor_overlap(make_project):
    def m(d):
        d["floors"][1]["rooms"] = ["Ванная", "Комната"]
    assert "FLOOR_OVERLAP" in codes(make_project(m))


def test_multipoint_switching(make_project):
    def m(d):
        for i in range(3):
            d["switches"].append({"id": "Х%d" % i, "x": 6000, "y": 1000 + 300 * i, "h": 900, "wall": "X-", "keys": 1,
                                  "controls": [{"key": "а", "group": "Комната", "kinds": ["chandelier"], "mode": "pass"}]})
    assert "SWITCH_MULTIPOINT" in codes(make_project(m))


def test_hot_water_left(make_project):
    def m(d):
        for o in d["plumbing"]:
            if o["fixture"] == "Раковина" and o["kind"] in ("ХВС", "ГВС"):
                o["kind"] = "ХВС" if o["kind"] == "ГВС" else "ГВС"
    assert "WATER_HOT_LEFT" in codes(make_project(m))


def test_model_noise_positions(make_project):
    def m(d):
        d["lighting"][1]["x"] = 1003
    assert "POINT_NOT_SNAPPED" in codes(make_project(m))


def test_overlapping_wardrobes(make_project):
    def m(d):
        d["furniture"].append({"name": "Шкаф", "kind": "wardrobe", "room": "Комната",
                               "poly": [[3250, 3400], [3800, 3400], [3800, 3900], [3250, 3900]]})
    assert "FURN_OVERLAP" in codes(make_project(m))


def test_boundary_point_belongs_to_facing_room(urgench):
    assert urgench.room_of_point((700, 3880))["name"] == "Санузел совмещённый"


def test_a_rack_built_around_a_column_is_not_in_the_wall(make_project):
    """L-112: Sherov's "rack around columns" (1800×600, h 2600) wraps a free-standing column - its outline takes the
    column in; that is how it is built, not a collision. A piece that only overlaps a column still is."""
    def around(d):
        d["walls"].append(dict(id="К1", kind="existing", rect=[4200, 800, 4600, 1200]))
        d["furniture"].append(dict(name="Стеллаж вокруг колонны", kind="shelving", room="Комната",
                                   poly=[[4000, 700], [4800, 700], [4800, 1300], [4000, 1300]]))
    assert "FURN_IN_WALL" not in codes(make_project(around))

    def overlap(d):
        d["walls"].append(dict(id="К1", kind="existing", rect=[4200, 800, 4600, 1200]))
        d["furniture"].append(dict(name="Тумба", kind="cabinet", room="Комната",
                                   poly=[[4400, 700], [5000, 700], [5000, 1300], [4400, 1300]]))
    assert "FURN_IN_WALL" in codes(make_project(overlap))
