# -*- coding: utf-8 -*-
"""Automatic safe corrections (sdalbum/autofix.py): every fix must remove its validation finding and never touch
design decisions (those become questions)."""
import copy
import json
import os

from conftest import STUDIO


def _fix(d):
    from sdalbum import autofix
    return autofix.fix(d, os.path.dirname(STUDIO))


def _codes(rest):
    return {i["code"] for i in rest}


def test_socket_off_the_wall_is_projected(studio_data):
    d = copy.deepcopy(studio_data)
    d["sockets"][0]["x"] = 140          # 140 mm inside the room instead of on the wall face x=0
    d2, log, rest, _ = _fix(d)
    assert "SOCKET_NOT_ON_WALL" not in _codes(rest)
    assert d2["sockets"][0]["x"] == 0 and d2["sockets"][0]["wall"] == "X+"
    assert any(e["code"] == "ON_WALL" for e in log)


def test_wall_side_taken_from_the_face(studio_data):
    d = copy.deepcopy(studio_data)
    d["switches"][0]["wall"] = "X+"     # В1 hangs on the right wall x=6000 -> faces X-
    d2, log, rest, _ = _fix(d)
    assert d2["switches"][0]["wall"] == "X-"
    assert "SWITCH_WALL_SIDE" not in _codes(rest)


def test_hot_water_swapped_to_the_left(studio_data):
    d = copy.deepcopy(studio_data)
    for o in d["plumbing"]:
        if o["fixture"] == "Раковина" and o["kind"] in ("ГВС", "ХВС"):
            o["x"] = {1550: 1650, 1650: 1550}[o["x"]]
    from sdalbum import model, validate
    assert "WATER_HOT_LEFT" in _codes(validate.run(model.Project(d, os.path.dirname(STUDIO))))
    d2, log, rest, _ = _fix(d)
    assert "WATER_HOT_LEFT" not in _codes(rest)
    hot = next(o for o in d2["plumbing"] if o["fixture"] == "Раковина" and o["kind"] == "ГВС")
    assert hot["x"] == 1550


def test_model_noise_snapped_but_face_coordinate_kept(studio_data):
    d = copy.deepcopy(studio_data)
    d["switches"][0]["y"] = 2553.7
    d["lighting"][1]["x"] = 1002.4
    d["furniture"][0]["poly"][0] = [3601.2, 2000]
    d2, log, rest, _ = _fix(d)
    assert d2["switches"][0]["y"] == 2555 and d2["switches"][0]["x"] == 6000
    assert d2["lighting"][1]["x"] == 1000
    assert "POINT_NOT_SNAPPED" not in _codes(rest)


def test_face_coordinate_off_module_is_not_noise(studio_data):
    """Walls from a survey are not on a 5-mm grid: a socket on the face x=3 must not be called model noise."""
    from sdalbum import model, validate
    d = copy.deepcopy(studio_data)
    for w in d["walls"]:
        if w["id"] == "С3":
            w["rect"] = [-300, 0, 3, 4000]
    d["sockets"][0]["x"] = 3
    P = model.Project(d, os.path.dirname(STUDIO))
    assert "POINT_NOT_SNAPPED" not in _codes(validate.run(P))


def test_multipoint_modes_assigned(studio_data):
    d = copy.deepcopy(studio_data)
    d["switches"].append(dict(id="В3", x=2100, y=1500, h=900, wall="X+", keys=1, room="Комната",
                              controls=[{"key": "а", "group": "Комната", "desc": "свет комнаты"}]))
    from sdalbum import model, validate
    assert "SWITCH_MULTIPOINT" in _codes(validate.run(model.Project(d, os.path.dirname(STUDIO))))
    d2, log, rest, _ = _fix(d)
    assert "SWITCH_MULTIPOINT" not in _codes(rest)
    modes = sorted(c["mode"] for s in d2["switches"] for c in s["controls"] if c["group"] == "Комната")
    assert modes == ["pass", "pass"]


def test_three_places_get_a_cross_switch(studio_data):
    d = copy.deepcopy(studio_data)
    for sid, x, y, wall in (("В3", 2100, 1500, "X+"), ("В4", 3000, 0, "Y+")):
        d["switches"].append(dict(id=sid, x=x, y=y, h=900, wall=wall, keys=1, room="Комната",
                                  controls=[{"key": "а", "group": "Комната", "desc": "свет комнаты"}]))
    d2, log, rest, _ = _fix(d)
    modes = sorted(c["mode"] for s in d2["switches"] for c in s["controls"] if c["group"] == "Комната")
    assert modes == ["cross", "pass", "pass"]
    assert "SWITCH_MULTIPOINT" not in _codes(rest)


def test_ordinary_socket_in_bathroom_becomes_ip44(studio_data):
    d = copy.deepcopy(studio_data)
    d["sockets"][2]["kind"] = "Р2"
    d2, log, rest, _ = _fix(d)
    assert d2["sockets"][2]["kind"] == "РВ"
    assert "SOCKET_WET" not in _codes(rest)


def test_design_conflicts_are_questions_not_fixes(studio_data):
    d = copy.deepcopy(studio_data)
    d["furniture"].append(dict(name="Комод", kind="cabinet", room="Комната", poly=[[5300, 2900], [5990, 2900], [5990, 3500], [5300, 3500]]))
    d2, log, rest, qs = _fix(d)
    assert "DOOR_HITS_FURNITURE" in _codes(rest)
    assert any("задевает" in q for q in qs)
    assert d2["openings"][1]["swing"] == d["openings"][1]["swing"]       # an existing swing is never changed


def test_fix_is_idempotent(studio_data):
    d2, log, _, _ = _fix(copy.deepcopy(studio_data))
    d3, log2, _, _ = _fix(d2)
    assert log2 == [] and d3 == d2


def _draft(tmp_path):
    from importers import dxf_plan
    from test_importers import _plan_dxf
    src = str(tmp_path / "plan.dxf")
    _plan_dxf(src)
    dxf_plan.main(src, str(tmp_path / "imp"))
    return json.load(open(tmp_path / "imp" / "draft_project.json", encoding="utf-8"))


def test_dxf_draft_becomes_buildable(tmp_path):
    from sdalbum import autofix, model, validate
    d = _draft(tmp_path)
    d2, log, rest, qs = autofix.fix(d, str(tmp_path))
    marks = sorted(o["mark"] for o in d2["openings"])
    assert all("?" not in m for m in marks)
    assert set(d2["opening_types"]) == set(marks)
    for o in d2["openings"]:
        if o["kind"] in ("door", "balcony"):
            assert o.get("swing") and o.get("hinge") in ("min", "max")
    P = model.Project(d2, str(tmp_path))
    assert not [i for i in validate.run(P) if i["level"] == "error"]
    assert any("автоматически" in q for q in qs)


def test_rooms_found_when_draft_has_none(tmp_path):
    from sdalbum import autofix, model
    d = _draft(tmp_path)
    d["rooms"] = []
    d2, log, rest, qs = autofix.fix(d, str(tmp_path))
    assert len(d2["rooms"]) == 1 and d2["rooms"][0]["name"] == "Помещение 1"
    assert abs(model.Project(d2, str(tmp_path)).rooms[0]["area"] - 24.0) < 0.05


def test_room_class_from_name():
    from sdalbum.topo import room_class
    assert room_class("Кухня-гостиная") == "kitchen"
    assert room_class("Санузел совмещённый") == "wet"
    assert room_class("Ванная комната") == "wet"
    assert room_class("Прихожая") == "circulation"
    assert room_class("Спальня") == "living"


def test_bathroom_door_opens_outward(studio_data):
    from sdalbum import autofix
    d = copy.deepcopy(studio_data)
    for o in d["openings"]:
        if o["id"] == "Д-2.1":
            o.pop("swing")
            o.pop("hinge")
    d2, log, rest, _ = autofix.fix(d, os.path.dirname(STUDIO))
    o = next(o for o in d2["openings"] if o["id"] == "Д-2.1")
    assert o["swing"] == [0, -1]                    # the bathroom is above the partition П1 -> opens down, outward


def test_material_thickness_is_not_noise(urgench):
    """Shelf 22 mm, side panel 18 mm, hob 12 mm are real sizes: the snap must leave them alone (lesson L-050)."""
    from sdalbum import autofix
    from conftest import URGENCH
    d = json.load(open(URGENCH, encoding="utf-8"))
    d2, log, rest, _ = autofix.fix(d, os.path.dirname(URGENCH))
    assert d2["elevations"] == d["elevations"]
    assert log == []
