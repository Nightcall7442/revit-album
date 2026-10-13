# -*- coding: utf-8 -*-
"""Boxes, floor zones, wall finishes, decorative lights and feature walls taken from the 3D scene (1.4):
lessons L-090 .. L-096."""
import copy

import pytest

from test_senior import _cafe


def _cafe_scene():
    d = _cafe()
    d["walls"].append(dict(id="W8", kind="existing", rect=[8000, 7500, 8400, 7900]))            # a free column
    # the base floor of the whole plan (FloorGenerator 600×600, «CORD 120x60») and a strip of 100×100 in the hall
    d["_floor_src"] = [
        dict(name="Layer:0", material="CORD 120x60", tile=[600, 600], tile_name=[1200, 600], z=0, area=110,
             polys=[[[0, 0], [12000, 0], [12000, 9000], [0, 9000]]], origin=[0, 0], fg=True, kind="base"),
        dict(name="Plane025", material="Material #101", tile=[100, 100], tile_name=None, z=2.5, area=4.8,
             polys=[[[9500, 3300], [10700, 3300], [10700, 7300], [9500, 7300]]], origin=[9500, 3300], fg=True,
             kind="overlay")]
    d["_box_src"] = [
        dict(name="cladding", rect=[7980, 7480, 8420, 7920], z0=0, z1=3000, kind="column", inner=[8000, 7500, 8400, 7900],
             clad=True, label="Equipe Artisan Burgundy", tile=[132, 132]),
        dict(name="riser", rect=[11600, 300, 12000, 700], z0=0, z1=3000, kind="pipe", clad=True)]
    d["_wall_mats"] = {w: dict(kind="plaster", label="", material="Plaster 37") for w in ("W1", "W2", "W3", "W4", "W5")}
    d["_lights"] += [dict(kind="point", name="Eichholtz_Chandelier-Tissot_S_", rect=[9500, 7000, 10600, 8100], z0=1530, z1=3000),
                     dict(kind="point", name="Baba_Sconce1", rect=[20, 7000, 170, 7300], z0=1450, z1=1740, low=True)]
    d["_texts"] = [dict(name="Text142", text="COFFEE", pos=[0, 6000, 2100], light=True)]
    return d


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    from sdalbum import autofix, propose, senior
    base = str(tmp_path_factory.mktemp("cafe2"))
    d, flog, rest, qs = autofix.fix(_cafe_scene(), base)
    d, slog = senior.decide(d, base)
    d, flog2, rest, qs = autofix.fix(d, base)
    d, plog = propose.propose(d, base)
    d, flog3, rest, qs = autofix.fix(d, base)
    return dict(d=d, slog=slog, plog=plog, rest=rest, qs=qs, base=base)


def _P(made):
    from sdalbum import model
    return model.Project(made["d"], made["base"])


# ------------------------------------------------------------------ importer evidence
def test_texture_names_say_what_the_material_is():
    from importers.scene_surfaces import tex_info, tile_from_name
    t = tex_info({"tex": ["22.EQUIPE ARTISAN/TEXX/betonka.jpg", "22.EQUIPE ARTISAN/TEXX/full_artisan-burgundy-24457-132-132.jpeg"]})
    assert t["kind"] == "tile" and t["tile"] == [132, 132] and t["label"] == "Equipe Artisan Burgundy"
    assert tex_info({"tex": ["x/maps/CORD 120x60 (3).jpg", "x/maps/CORD 120x60 (2).jpg"]})["tile"] == [1200, 600]
    mix = tex_info({"tex": ["a/b/brick_type_3_pattern_13_normal.jpg", "a/b/Plaster 37.png"]})
    assert mix["kind"] == "plaster" and mix["brick_mix"]
    assert tile_from_name("CORD 120x60") == [1200, 600] and tile_from_name("Material #101") is None


def test_a_spline_floor_outline_and_a_strip_over_it():
    from importers import scene_surfaces as SS
    seg = lambda a, b: dict(p=[a, b], closed=False)
    outline = [seg((0, 0), (6000, 0)), seg((6000, 0), (6000, 4000)), seg((6000, 4000), (0, 4000)), seg((0, 4000), (0, 0))]
    rows = [dict(idx=1, name="Layer:0", **{"class": "SplineShape"}, mods=["Edit Poly", "FloorGenerator"], materials=["CORD 120x60"],
                 lines=outline, lines_z=0.0, fg_tile=[600.0, 600.0]),
            dict(idx=2, name="Plane025", **{"class": "Plane"}, mods=["FloorGenerator"], materials=["Material #101"],
                 footprint=[[1000, 1000], [2200, 1000], [2200, 3000], [1000, 3000]], z0=2.5, z1=2.5, fg_tile=[100.0, 100.0]),
            dict(idx=3, name="carpet", **{"class": "Plane"}, mods=[], materials=["carpet 120x60"],
                 footprint=[[0, 0], [1000, 0], [1000, 1000], [0, 1000]], z0=5, z1=5)]
    fl = SS.floors(rows, {}, 1.0)
    assert [f["kind"] for f in fl] == ["base", "overlay"]
    assert fl[0]["tile"] == [600, 600] and fl[0]["tile_name"] == [1200, 600] and abs(fl[0]["area"] - 24.0) < 0.1
    assert fl[1]["tile"] == [100, 100] and fl[1]["origin"] == [1000, 1000]


def test_boxes_of_the_scene_are_told_apart():
    from importers import scene_surfaces as SS
    walls = [dict(id="W1", rect=[0, 0, 200, 6000], source="wall"), dict(id="C1", rect=[3000, 3000, 3400, 3400], source="col")]
    def row(n, fp, z1, **kw):
        r = dict(name=n, footprint=fp, z0=0, z1=z1, materials=[], mods=[])
        r["class"] = "Box"
        r.update(kw)
        return r
    rows = [row("cladding", [[2980, 2980], [3420, 2980], [3420, 3420], [2980, 3420]], 3000),
            row("riser", [[200, 5500], [600, 5500], [600, 5900], [200, 5900]], 3000),
            row("Plane024_FG007", [[406, 1000], [814, 1000], [814, 4000], [406, 4000]], 410, mods=["FloorGenerator"]),
            row("tile on the wall", [[200, 0], [210, 0], [210, 3000], [200, 3000]], 3000)]
    got = {b["name"]: b for b in SS.boxes(rows, walls)}
    assert got["cladding"]["kind"] == "column" and got["riser"]["kind"] == "pipe"
    assert got["Plane024_FG007"]["kind"] == "low" and got["Plane024_FG007"]["clad"]          # 206 mm off the wall: a seating base
    assert "tile on the wall" not in got                                              # a finish, not a box


# ------------------------------------------------------------------ senior
def test_installation_box_behind_a_hung_wc(made):
    P = _P(made)
    ib = [b for b in P.boxes if b.get("box") == "install"]
    assert len(ib) == 1
    b = ib[0]
    x0, y0, x1, y1 = b["shape"].bounds
    assert round(y1 - y0) == 200 and b["h"] == 1100                  # by the norms: 200 deep, h 1100 (sill 1200)
    wc = next(f for f in made["d"]["furniture"] if f["kind"] == "wc")
    assert min(p[1] for p in wc["poly"]) >= y1 - 1                    # the WC hangs on the box, not inside it
    assert any(o["fixture"].startswith("Унитаз") for o in made["d"]["plumbing"])


def test_column_cladding_and_riser_box(made):
    P = _P(made)
    kinds = sorted(b.get("box") for b in P.boxes)
    assert "column" in kinds and "pipe" in kinds and "bar" in kinds
    assert [b["id"] for b in P.boxes] == ["К-%d" % i for i in range(1, len(P.boxes) + 1)]


def test_floor_zones_from_the_model(made):
    P = _P(made)
    fl = made["d"]["floors"]
    assert all(f.get("source") == "model" or f.get("polys") is None for f in fl)
    assert any("CORD" in f["material"] and f["tile"] in ([600, 600],) for f in fl)
    strip = next(f for f in fl if f.get("polys"))
    assert strip["tile"] == [100, 100] and strip.get("origin")
    zones = P.floor_zones()
    for i in range(len(zones)):
        for j in range(i + 1, len(zones)):
            assert zones[i][1].intersection(zones[j][1]).area < 1e4          # the strip is cut out of the hall's floor
    assert not [i for i in made["rest"] if i["code"] in ("FLOOR_OVERLAP", "FLOOR_UNCOVERED")]
    assert any("формат" in e["msg"] and "1200×600" in e["msg"] for e in made["slog"])     # name vs model: confirm


def test_wall_finishes_from_the_model_no_invented_tile(made):
    F = made["d"]["finishes"]
    assert F["source"] == "model" and not F.get("by_class")
    assert "штукатурка" in F["types"][0]["desc"].lower()
    wc = [e for e in made["d"]["elevations"] if e["room"] == "Санузел"]
    assert wc and all(e["base"] == "paint" for e in wc)
    tiled = [z for e in wc for z in e.get("zones", []) if z["mat"] == "tile"]
    assert tiled and all(z["z1"] <= 1100 for z in tiled)                   # tile only on the installation box


def test_chandelier_and_wall_light_from_the_model(made):
    by = {}
    for f in made["d"]["lighting"]:
        by.setdefault(f["kind"], []).append(f)
    ch = by["chandelier"][0]
    assert ch["d"] >= 1000 and ch["z"] == 1530 and "Eichholtz" in ch.get("model", "")
    w = by["wall"][0]
    assert (w["nx"], w["ny"]) == (1, 0) or abs(w["nx"] - 1) < 1e-6
    spec = made["d"]["lighting_spec"]
    assert "Люстра" in spec["chandelier"] and "+1,530" in spec["chandelier"]


def test_feature_wall_gets_an_elevation_with_its_sign(made):
    el = [e for e in made["d"]["elevations"] if e.get("feature")]
    signs = [it for e in el for it in e.get("items", []) if it.get("type") == "sign"]
    assert signs and signs[0]["text"] == "COFFEE" and signs[0]["z"] == 2100
    assert any(it.get("type") == "wall_light" for e in el for it in e.get("items", []))


def test_decisions_are_replaced_not_piled_up(made):
    from sdalbum import senior
    d, _ = senior.decide(copy.deepcopy(made["d"]), made["base"])
    d, _ = senior.decide(d, made["base"])
    topics = [s.split(":", 1)[0] for s in d["meta"]["decisions"]]
    assert topics.count("Назначение помещений") == 1


# ------------------------------------------------------------------ lighting plan
def test_control_lines_are_a_spanning_tree():
    from sdalbum.sheets_plans import _mst
    pts = [(0, 0), (1000, 0), (2000, 0), (8000, 0), (9000, 0)]
    e = _mst(pts)
    assert len(e) == 4 and sum(abs(a[0] - b[0]) for a, b in e) == 9000      # neighbours, one link between the groups


def test_fixtures_in_a_row_get_one_chain(made):
    from sdalbum import model
    from sdalbum.sheets_plans import light_bindings
    d = copy.deepcopy(made["d"])
    d["lighting"] = [dict(kind="pendant", x=x, y=6500, group="Обеденный зал") for x in (7000, 8500, 10000)]
    P = model.Project(d, made["base"])
    room = P.room_by_name["Обеденный зал"]
    ch = light_bindings(P, room)
    rows = [c for c in ch if len(c[0]) >= 4]
    assert rows and not rows[0][2] and rows[0][1] == 6500                # along the row, through the fixtures
    assert len(ch) == 2                                                  # + one cross dimension of the row
