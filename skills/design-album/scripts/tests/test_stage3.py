# -*- coding: utf-8 -*-
"""Plans of stage 3 of the reference album: plinths, heating, cornices, furniture with dimensions and doors,
electrical outputs, the schedule of electrical fittings."""
import json
import os

import pytest
from shapely.geometry import Point, box

from conftest import URGENCH


@pytest.fixture(scope="module")
def urgench_proposed():
    from sdalbum import propose
    d = json.load(open(URGENCH, encoding="utf-8"))
    d2, log = propose.propose(d, os.path.dirname(URGENCH), sections=("plinths", "heating"))
    return d2


def test_radiators_under_the_windows_and_floor_heating_in_wet_rooms(urgench_proposed):
    from sdalbum import model
    H = urgench_proposed["heating"]
    P = model.Project(urgench_proposed, os.path.dirname(URGENCH))
    wins = [P.open_shape[o["id"]] for o in P.openings if o["kind"] == "window"]
    assert len(H["radiators"]) == len(wins) == 2
    for r in H["radiators"]:
        g = box(*r["rect"])
        assert min(g.distance(w) for w in wins) < 120               # under a window, 50 mm off the wall face
        assert r["w"] == 1100 and r["mark"] == "Р-1"                  # 3/4 of a 1500 window
    assert {f["room"] for f in H["floors"]} == {r["name"] for r in P.rooms if r.get("cls") == "wet"}
    for t in H["thermostats"]:                                        # outside the wet room, in the room it opens to
        rm = P.room_of_point((t["x"] + t["n"][0] * 80, t["y"] + t["n"][1] * 80), 50)
        assert rm is not None and rm.get("cls") != "wet"


def test_plinth_in_dry_rooms_only(urgench_proposed):
    from sdalbum import model
    P = model.Project(urgench_proposed, os.path.dirname(URGENCH))
    rooms = urgench_proposed["plinths"]["rooms"]
    assert rooms and all(P.room_by_name[n].get("cls") != "wet" for n in rooms)


def test_stage3_sheets_build_clean(urgench_proposed, tmp_path):
    from sdalbum import album, model, qa
    p = tmp_path / "project.json"
    p.write_text(json.dumps(urgench_proposed, ensure_ascii=False), encoding="utf-8")
    P = model.load(str(p))
    keys = ["plinths", "heating", "cornices", "furniture_dims", "sockets", "el_fittings", "el_outputs"]
    A = album.Album(P, str(tmp_path / "out"), keys)
    titles = [t for _, _, t, *_ in A.sheets]
    assert "План карнизов" not in titles                              # a towel rail is not a curtain rail
    assert "План розеток" in titles and "План электровыводов" in titles
    A.build()
    rep = qa.check_doc(A.doc)
    errs = [i for v in rep.values() for i in v if i["level"] == "error"]
    assert errs == [], errs[:5]
    out = " ".join(e.dxf.text for no in A.layouts for e in A.layouts[no] if e.dxftype() == "TEXT")
    assert "* Ведомость плинтусов" in out and "* Ведомость отопительных приборов" in out
    assert "Ведомость дверей" in out and "* Ведомость электрофурнитуры" in out
