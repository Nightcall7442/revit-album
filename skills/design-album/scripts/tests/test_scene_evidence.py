# -*- coding: utf-8 -*-
"""3D scene import reads evidence like a senior: what hangs on a gap, what is mounted in it, a door unit in a shop
front, counters built from panels, broken bounding boxes, the designer's lights and ceilings (importers/scene_draft)."""


def _obj(name, rect, z0=0, z1=3000, cls="Editable Poly", nverts=12, parent="Group001", flat=False, mods=()):
    return dict(name=name, parent=parent, cls=cls, nverts=nverts, rect=rect, z0=z0, z1=z1, flat=flat, mods=list(mods))


def _shell():
    """8 x 6 m box of walls (shell group) with an interior wall y 3000 split by a 1000 gap at x 5000..6000."""
    return [_obj("Plane1", (-200, -200, 8200, 0)), _obj("Plane2", (-200, 0, 0, 6000)), _obj("Plane3", (8000, 0, 8200, 6000)),
            _obj("Plane4", (-200, 6000, 8200, 6200)), _obj("Plane5", (0, 3000, 5000, 3200)), _obj("Plane6", (6000, 3000, 8000, 3200))]


def _build(tmp_path, extra, ceil=2900, slab=3000):
    from importers import scene_draft
    return scene_draft.build(_shell() + extra, ceil, str(tmp_path / "d.json"), slab=slab)[0]


def test_open_gap_stays_open(tmp_path):
    d = _build(tmp_path, [])
    assert not any(w["id"].startswith(("ЗС", "ПР")) for w in d["walls"])


def test_gap_with_a_menu_board_on_it_is_a_wall(tmp_path):
    board = _obj("menu board", (5100, 3195, 5900, 3207), 1400, 2100, nverts=900, parent=None)
    d = _build(tmp_path, [board])
    zs = [w for w in d["walls"] if w["id"].startswith("ЗС")]
    assert len(zs) == 1 and zs[0]["rect"] == [5000, 3000, 6000, 3200]
    assert not any(o["wall"] == zs[0]["id"] for o in d["openings"])


def test_lintel_over_a_basin_is_a_niche_not_a_door(tmp_path):
    lintel = _obj("Box11", (5000, 3000, 6000, 3200), 2100, 3000, cls="Box", nverts=None)
    basin = _obj("Console Sink", (5200, 3050, 5800, 3500), 700, 880, nverts=7000, parent="sink")
    d = _build(tmp_path, [lintel, basin])
    niche = [w for w in d["walls"] if w["id"].startswith("НШ")]
    assert len(niche) == 1 and niche[0]["kind"] == "new"
    assert niche[0]["rect"] == [5000, 2950, 6000, 3000]          # back board on the side away from the basin
    assert not any(o["kind"] == "door" for o in d["openings"])


def test_door_object_must_lie_in_the_gap_run(tmp_path):
    """A door standing across the end of a gap (another wall run) is not the door of that gap (lesson: the WC door
    became a 1200 'door' in the cubicle divider)."""
    door = _obj("Glass_Door_1", (6100, 2950, 7045, 3090), 0, 2080, nverts=17000, parent=None)
    d = _build(tmp_path, [door])
    gap_doors = [o for o in d["openings"] if o["kind"] == "door" and o["wall"].startswith("ПР")]
    assert not gap_doors
    assert [o["wall"] for o in d["openings"] if "Glass_Door_1" in o.get("note", "")] == ["W6"]


def test_entrance_door_in_a_shop_front(tmp_path):
    from importers import scene_draft
    objs = [_obj("Plane1", (-200, -200, 8200, 0)), _obj("Plane2", (-200, 0, 0, 6000)), _obj("Plane3", (8000, 0, 8200, 6000))]
    front = _obj("3 016", (-200, 6000, 8000, 6080), 0, 3000, parent=None, nverts=50000)
    panels = [_obj("pCube1", (2000, 6030, 2900, 6045), -9, 2190, nverts=488, parent="g"),
              _obj("pCube3", (3820, 6030, 4720, 6045), -9, 2190, nverts=488, parent="g"),
              _obj("pCube2", (2913, 6030, 3813, 6045), 2192, 3422, nverts=3404, parent="g")]
    leaf = _obj("Object002", (3450, 5150, 3800, 6040), -9, 2190, nverts=1946, parent="g")
    d, _ = scene_draft.build(objs + [front] + panels + [leaf], 2900, str(tmp_path / "d.json"), slab=3000)
    doors = [o for o in d["openings"] if o["kind"] == "door"]
    assert len(doors) == 1 and doors[0]["wall"] == "ВТ1" and doors[0]["w"] == 900 and doors[0].get("entrance")
    wins = [o for o in d["openings"] if o["kind"] == "window" and o["wall"] == "ВТ1"]
    assert len(wins) == 2 and all(o["sill"] == 0 for o in wins)


def test_counter_from_panels_folds_the_fridges_under_it(tmp_path):
    panels = [_obj("Box1277_FG002", (1000, 5000, 5000, 5000), 250, 1200, nverts=10, parent="g654"),
              _obj("Box1277_FG003", (5000, 3200, 5000, 5000), 250, 1200, nverts=6, parent="g654"),
              _obj("Box1277_FG001", (1000, 3200, 5000, 5000), 1200, 1200, nverts=8, parent="g654")]
    fridges = [_obj("Box%d" % i, (1100 + 700 * i, 4300, 1750 + 700 * i, 4990), 150, 850, nverts=264, parent="HICOLD %d" % i)
               for i in range(3)]
    pos = _obj("Bar_counter_POS", (3000, 4700, 3400, 4900), 1100, 1440, nverts=2796, parent="g660")
    d = _build(tmp_path, panels + fridges + [pos])
    cnt = [f for f in d["furniture"] if f["kind"] == "counter"]
    assert len(cnt) == 1 and cnt[0]["name"].startswith("Барная стойка") and "×3" in cnt[0]["name"]
    assert not any(f["kind"] == "fridge" for f in d["furniture"])
    assert len(cnt[0]["front"]) == 2


def test_broken_bounding_box_part_is_dropped_but_a_dining_group_is_kept(tmp_path):
    rack = [_obj("shelves001", (1000, 500, 2800, 950), 40, 1780, nverts=1358, parent="Metalus rack"),
            _obj("vertical base001", (1050, 520, 2700, 930), 40, 1780, nverts=1600, parent="Metalus rack"),
            _obj("screw001", (200, 700, 1900, 1000), 360, 2100, nverts=900, parent="Metalus rack")]
    group = [_obj("Table_Chairs_01", (3000, 4000, 4000, 5000), 0, 760, nverts=3000, parent="Table_Chairs set"),
             _obj("chair a", (2600, 4200, 3100, 4700), 0, 850, nverts=3000, parent="Table_Chairs set"),
             _obj("chair b", (3900, 4200, 4400, 4700), 0, 850, nverts=3000, parent="Table_Chairs set")]
    d = _build(tmp_path, rack + group)
    names = {f["name"]: f["poly"] for f in d["furniture"]}
    assert names["Стеллаж"][0][0] >= 1000                            # the screw's broken box did not stretch the rack
    assert any("Обеденная группа" in n for n in names)


def test_wall_hung_wc_and_lights_ceilings_beams_are_kept_as_evidence(tmp_path):
    wc = _obj("toilet 1", (500, 100, 850, 640), 66, 410, nverts=2700, parent="g747")
    track = _obj("Arkoslight b241", (2000, 4000, 2032, 5800), 2397, 2420, nverts=56, parent="Group688")
    spot = _obj("Arkoslight b229", (1990, 4500, 2050, 4560), 2204, 2405, nverts=15134, parent="Arkoslight b231")
    down = _obj("Arkoslight b350", (1000, 1300, 1068, 1368), 2760, 3000, nverts=15134, parent="Arkoslight b352")
    ceil = _obj("Plane11478", (0, 0, 2000, 2000), 2557, 2557, cls="Plane", nverts=None, parent=None, flat=True)
    beam = _obj("Box001", (6000, 3500, 6400, 5000), 2600, 3000, cls="Box", nverts=None, parent="Group002")
    d = _build(tmp_path, [wc, track, spot, down, ceil, beam])
    w = next(f for f in d["furniture"] if f["kind"] == "wc")
    assert w.get("hung") and "подвесной" in w["name"]
    kinds = sorted(l["kind"] for l in d["_lights"])
    assert kinds == ["line", "point", "point"]
    assert d["_ceil_planes"] == [[[0, 0, 2000, 2000], 2560]]
    assert d["_beams"] == [[[6000, 3500, 6400, 5000], 2600]]
    assert d["levels"]["slab"] == 3000 and d["levels"].get("source")


def test_columns_stubs_and_niches_are_not_passages(tmp_path):
    """Throats (passages between bearing walls) are cut out of rooms. Free-standing columns of a hall, a 100 mm WC
    divider stub and a niche closed by a back board are not passages (the hall was split into 3 rooms)."""
    from sdalbum import model
    W = lambda i, r, k="existing": dict(id=i, kind=k, rect=r)
    walls = [W("A", [-200, -200, 10200, 0]), W("B", [-200, 0, 0, 6000]), W("C", [10000, 0, 10200, 6000]),
             W("D", [-200, 6000, 10200, 6200]),
             W("col1", [4000, 3000, 4400, 3400]), W("col2", [7000, 3000, 7400, 3400]),        # 2.6 m apart
             W("stub", [2000, 0, 2100, 1500]),                                                  # divider stub
             W("n1", [6000, 0, 6220, 1000]), W("n2", [6000, 1900, 6220, 2400]), W("back", [5950, 1000, 6000, 1900], "new")]
    d = dict(walls=walls, openings=[], rooms=[dict(name="Зал", seed=[1000, 5000])])
    P = model.Project(d, str(tmp_path))
    assert P.throats() == []
    assert len(P.rooms) == 1 and P.rooms[0]["area"] > 55


def test_evidence_moves_with_the_axes(tmp_path):
    from sdalbum import autofix
    W = lambda i, r: dict(id=i, kind="existing", rect=r)
    d = dict(_todo=["x"], walls=[W("A", [1000, 1000, 7200, 1200]), W("B", [1000, 1200, 1200, 5000]),
                                 W("C", [7000, 1200, 7200, 5000]), W("D", [1000, 5000, 7200, 5200])], rooms=[], openings=[],
             _lights=[dict(kind="point", rect=[3000, 3000, 3068, 3068], z0=2760, z1=3000)],
             _objects=[["toilet", 3000, 3000]], _beams=[[[2000, 2000, 2400, 4000], 2600]])
    d2, log, rest, qs = autofix.fix(d, str(tmp_path))
    dx = d2["walls"][0]["rect"][0] - 1000
    dy = d2["walls"][0]["rect"][1] - 1000
    assert (dx, dy) != (0, 0)
    assert d2["_lights"][0]["rect"][0] == 3000 + dx and d2["_objects"][0][2] == 3000 + dy
    assert d2["_beams"][0][0][1] == 2000 + dy


def test_notes_are_one_mtext_per_item():
    import ezdxf
    from sdalbum import gfx as S
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    S.notes(msp, 0, 100, ["Выводы уточнить по паспортам выбранной сантехники до начала разводки.", "Второй пункт."], 120)
    assert len(msp.query("MTEXT")) == 2


def test_room_axonometry_uses_depth_buffer(tmp_path):
    """The WC view is drawn by the depth-buffer renderer: a near face hides a far one whatever the order."""
    import numpy as np
    from PIL import Image
    from sdalbum import raster3d
    far = (np.array([(0, 1000, 0), (1000, 1000, 0), (1000, 1000, 1000), (0, 1000, 1000)], float), (1.0, 0.0, 0.0), False)
    near = (np.array([(0, 0, 0), (1000, 0, 0), (1000, 0, 1000), (0, 0, 1000)], float), (0.0, 0.0, 1.0), False)
    p = str(tmp_path / "z.png")
    raster3d.render([near, far], p, elev=0, azim=-90, width=200)          # camera at -y: «near» is in front
    im = np.asarray(Image.open(p).convert("RGB"), float)
    c = im[im.shape[0] // 2, im.shape[1] // 2]
    assert c[2] > 100 and c[0] < 100
