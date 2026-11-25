# -*- coding: utf-8 -*-
"""Elevations of every wall with the objects of the scene projected on them (stage 2 of the reference album)."""
import json

import numpy as np
import pytest


def _box_mesh(x0, y0, z0, x1, y1, z1):
    v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], np.float32)
    q = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
    f = [(a, b, c) for a, b, c, d in q] + [(a, c, d) for a, b, c, d in q]
    return v, np.array(f, np.int32)


def _frame(x0, x1, y, z0, z1, t=60, d=30):
    """A moulding frame on the wall y=y (4 bars) -> one mesh."""
    parts = [_box_mesh(x0, y, z0, x1, y + d, z0 + t), _box_mesh(x0, y, z1 - t, x1, y + d, z1),
             _box_mesh(x0, y, z0, x0 + t, y + d, z1), _box_mesh(x1 - t, y, z0, x1, y + d, z1)]
    vs, fs, n = [], [], 0
    for v, f in parts:
        vs.append(v)
        fs.append(f + n)
        n += len(v)
    return np.vstack(vs), np.vstack(fs)


@pytest.fixture
def room_project(tmp_path):
    """A 4 x 3 m room (inside 0..4000 x 0..3000), a frame on the wall y=3000, a chair at it, a box over the wall."""
    v1, f1 = _frame(1000, 2200, 2970, 900, 2100)
    v2, f2 = _box_mesh(2600, 2500, 0, 3200, 2990, 900)
    v3, f3 = _box_mesh(0, 2980, 0, 4000, 2995, 2800)
    np.savez_compressed(str(tmp_path / "m.npz"), names=np.array(json.dumps(["Frame01", "Armchair 01", "Box77"])),
                        cats=np.array(json.dumps(["molding", "seating", "other"])),
                        v0=v1, f0=f1, v1=v2, f1=f2, v2=v3, f2=f3)
    d = dict(meta=dict(elev_meshes="m.npz"), levels=dict(floor=0, ceiling=2800, slab=3000),
             walls=[dict(id="W1", kind="existing", rect=[-200, -200, 4200, 0]),
                    dict(id="W2", kind="existing", rect=[-200, 3000, 4200, 3200]),
                    dict(id="W3", kind="existing", rect=[-200, 0, 0, 3000]),
                    dict(id="W4", kind="existing", rect=[4000, 0, 4200, 3000])],
             rooms=[dict(num="1", name="Гостиная", seed=[2000, 1500], cls="living")], openings=[])
    p = tmp_path / "project.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return str(p), str(tmp_path)


def test_frame_projects_as_a_frame_chair_and_wall_box_do_not(room_project):
    from sdalbum import elev_scene as ES, model
    from sdalbum.sheets_details import Elev
    P = model.load(room_project[0])
    rm = P.rooms[0]
    e = dict(a=[4000, 3000], b=[0, 3000], room=rm["name"], height=2800)
    its = ES.items(P, Elev(P, e), rm["shp"], 2800)
    assert [i["src"] for i in its] == ["Frame01"]
    fr = its[0]
    assert len(fr["holes"]) == 1                                 # a frame, not a solid plate
    xs = [p[0] for p in fr["pts"]]
    ys = [p[1] for p in fr["pts"]]
    assert abs(min(xs) - 1800) <= 8 and abs(max(xs) - 3000) <= 8   # s runs from b=(4000) side: 4000-2200 .. 4000-1000
    assert abs(min(ys) - 900) <= 8 and abs(max(ys) - 2100) <= 8


def test_every_wall_gets_an_elevation_numbered_through(room_project):
    from sdalbum import propose
    d = json.load(open(room_project[0], encoding="utf-8"))
    d2, log = propose.propose(d, room_project[1], sections=("elevations",))
    els = d2["elevations"]
    assert len(els) == 4 and [e["label"] for e in els] == ["1", "2", "3", "4"]
    framed = [e for e in els if any(it.get("src") == "Frame01" for it in e["items"])]
    assert len(framed) == 1
    assert {1000, 2200} <= set(framed[0].get("extra_s", []))      # seen from the room: x grows to the right
    assert {900, 2100} <= set(framed[0].get("extra_heights", []))


def test_frame_is_a_moulding_with_its_profile_and_mark(room_project):
    from sdalbum import propose
    d = json.load(open(room_project[0], encoding="utf-8"))
    d2, log = propose.propose(d, room_project[1], sections=("elevations",))
    fr = [it for e in d2["elevations"] for it in e["items"] if it.get("src") == "Frame01"][0]
    assert fr["cat"] == "molding" and fr["profile"] == 60 and fr["mark"] == "МЛ-1"
    assert abs(fr["length"] - (2 * (1200 + 1200) + 2 * (1080 + 1080)) / 2000.0) < 0.1


def test_layout_start_is_a_red_pair_of_arrows():
    import ezdxf
    from sdalbum import gfx as S, symbols as Y
    d = ezdxf.new()
    sp = d.modelspace()
    g = Y.start_mark(sp, (0, 0), 1.0)
    lines = [e for e in sp if e.dxftype() == "LINE"]
    assert len(lines) == 2 and all(e.rgb == S.C_RED for e in lines)
    assert g.bounds[2] > 3.5 and g.bounds[3] > 3.5
