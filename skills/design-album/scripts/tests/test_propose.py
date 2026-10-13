# -*- coding: utf-8 -*-
"""Design proposal by norms (sdalbum/propose.py): a bare plan becomes a complete, valid project; a designer's data
is never overwritten; the result follows the conventions a designer uses (checked against the Urgench album)."""
import copy
import json
import math
import os

import pytest

from conftest import STUDIO, URGENCH

STRIP = ("lighting", "switches", "sockets", "plumbing", "circuits", "floors")


def _strip(d):
    d = copy.deepcopy(d)
    for k in STRIP:
        d[k] = []
    d["panel"] = None
    d["finishes"] = {}
    d["ceilings"] = {"types": [], "zones": d.get("ceilings", {}).get("zones", [])}
    for r in d["rooms"]:
        for k in ("ceiling_type", "wall_finish", "wall_split"):
            r.pop(k, None)
    d.pop("lighting_spec", None)
    return d


def _run(d, base):
    from sdalbum import autofix, propose
    d2, log = propose.propose(d, base)
    d3, flog, rest, qs = autofix.fix(d2, base)
    return d3, log, rest


def _load(p):
    return json.load(open(p, encoding="utf-8"))


@pytest.fixture(scope="module")
def urgench_proposed():
    d = _strip(_load(URGENCH))
    return _run(d, os.path.dirname(URGENCH))


def test_bare_plan_becomes_valid_project(studio_data):
    d3, log, rest = _run(_strip(studio_data), os.path.dirname(STUDIO))
    assert not [i for i in rest if i["level"] == "error"], rest
    codes = {i["code"] for i in rest}
    assert "LIGHT_GROUP_NO_SWITCH" not in codes and "SOCKET_NO_GROUP" not in codes
    for k in STRIP:
        assert d3[k], k
    assert d3["panel"] and d3["floors"] and d3["ceilings"]["types"] and d3["finishes"]["types"]
    assert all(o.get("proposed") for o in d3["lighting"] + d3["sockets"] + d3["switches"] + d3["plumbing"])
    assert any("проектное предложение" in q for q in d3["notes"]["general"]["add"])     # a statement, not a question


def test_designer_data_is_never_overwritten(studio_data):
    from sdalbum import propose
    d2, log = propose.propose(copy.deepcopy(studio_data), os.path.dirname(STUDIO))
    for k in STRIP + ("panel",):
        assert d2[k] == studio_data[k], k
    assert not [e for e in log if e["section"] in ("освещение", "розетки", "выключатели", "сантехника")]


def test_socket_count_meets_norm(urgench_proposed):
    from sdalbum import model
    d3, log, rest = urgench_proposed
    P = model.Project(d3, os.path.dirname(URGENCH))
    for r in P.rooms:
        pts = [s for s in P.sockets if s["kind"] in ("Р", "Р2", "РВ") and P.room_of_point((s["x"], s["y"]), 60) is r]
        if r["cls"] == "living":
            assert len(pts) >= math.ceil(r["perimeter"] / 4.0 - 1e-9), r["name"]
        if r["cls"] == "kitchen":
            assert len(pts) >= 4


def test_switches_where_the_designer_put_them(urgench_proposed):
    """The Urgench designer's main switches (В1-В7) - the proposal lands within 150 mm of each of them."""
    d3, log, rest = urgench_proposed
    ref = [s for s in _load(URGENCH)["switches"] if s["h"] == 900]
    got = [(s["x"], s["y"]) for s in d3["switches"]]
    for s in ref:
        dmin = min(math.hypot(s["x"] - x, s["y"] - y) for x, y in got)
        assert dmin <= 150, (s["id"], s["x"], s["y"], dmin)


def test_wet_room_switch_is_outside(urgench_proposed):
    from sdalbum import model
    d3, log, rest = urgench_proposed
    P = model.Project(d3, os.path.dirname(URGENCH))
    for s in P.switches:
        for c in s["controls"]:
            r = P.room_by_name.get(c["group"])
            if r is not None and r["cls"] == "wet":
                assert P.room_of_point((s["x"], s["y"]), 40)["cls"] != "wet"


def test_bedroom_gets_pass_switch_at_the_bed(urgench_proposed):
    d3, log, rest = urgench_proposed
    bed = [s for s in d3["switches"] if s["h"] == 700]
    assert bed and all(c.get("mode") == "pass" for s in bed for c in s["controls"])
    assert "SWITCH_MULTIPOINT" not in {i["code"] for i in rest}


def test_plumbing_hot_left_and_on_walls(urgench_proposed):
    d3, log, rest = urgench_proposed
    codes = {i["code"] for i in rest}
    assert not codes & {"WATER_HOT_LEFT", "WATER_NOT_ON_WALL", "DRAIN_OUTSIDE"}
    fixtures = {o["fixture"] for o in d3["plumbing"]}
    assert {"Раковина", "Мойка", "Унитаз", "Стиральная машина", "Трап душевой"} <= fixtures


def test_kitchen_worktop_sockets_clear_of_sink_and_hob(urgench_proposed):
    from shapely.geometry import Polygon
    d3, log, rest = urgench_proposed
    sink = Polygon(next(f["poly"] for f in d3["furniture"] if f["kind"] == "sink")).centroid
    hob = Polygon(next(f["poly"] for f in d3["furniture"] if f["kind"] == "hob")).centroid
    top = [s for s in d3["sockets"] if s["h"] == 1100 and s.get("note") == "над столешницей"]
    assert len(top) == 2
    for s in top:
        assert abs(s["y"] - sink.y) >= 300 and abs(s["y"] - hob.y) >= 350


def test_no_spots_above_wardrobes_and_pendant_over_table(urgench_proposed):
    from shapely.geometry import Point, Polygon
    d3, log, rest = urgench_proposed
    wards = [Polygon(f["poly"]) for f in d3["furniture"] if f["kind"] in ("wardrobe", "kitchen_upper", "fridge")]
    for f in d3["lighting"]:
        if f["kind"].startswith("spot"):
            assert not any(w.contains(Point(f["x"], f["y"])) for w in wards)
    table = Polygon(next(f["poly"] for f in d3["furniture"] if f["kind"] == "table")).centroid
    pend = [f for f in d3["lighting"] if f["kind"] == "pendant"]
    assert pend and math.hypot(pend[0]["x"] - table.x, pend[0]["y"] - table.y) < 10


def test_air_conditioner_not_above_bed(urgench_proposed):
    from shapely.geometry import Point, Polygon
    d3, log, rest = urgench_proposed
    beds = [Polygon(f["poly"]).buffer(700) for f in d3["furniture"] if f["kind"] == "bed"]
    for s in d3["sockets"]:
        if s["kind"] == "КОНД":
            assert not any(b.contains(Point(s["x"], s["y"])) for b in beds)


def test_planks_along_the_light(urgench_proposed):
    d3, log, rest = urgench_proposed
    plank = next(f for f in d3["floors"] if f["pattern"] == "plank")
    assert plank["along"] == "y"            # windows in the bottom wall -> light along y


@pytest.mark.slow
def test_proposed_sheets_pass_qa(tmp_path, studio_data):
    from sdalbum import album, qa
    d3, log, rest = _run(_strip(studio_data), os.path.dirname(STUDIO))
    p = tmp_path / "project.json"
    json.dump(d3, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    A = album.build(str(p), str(tmp_path / "out"), ["lighting", "sockets", "plumbing", "floors", "ceilings", "finishes"])
    rep = qa.check_doc(A.doc)
    errs = [i for v in rep.values() for i in v if i["level"] == "error"] + [i for i in A.check_clipping() if i["level"] == "error"]
    assert not errs, errs
