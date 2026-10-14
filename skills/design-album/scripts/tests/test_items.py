# -*- coding: utf-8 -*-
"""Furniture of the scene -> production sketches: units from groups / touching free objects, identical pieces as one
item with a quantity, things that are not furniture dropped, the meshes drawn at scale, the designer's data on top
(importers/scene_items, sdalbum/items3d, sdalbum/items, sdalbum/sheets_items)."""
import json
import os
import pickle

import numpy as np
import pytest


def _box(x0, y0, z0, x1, y1, z1):
    v = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                  (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], float)
    f = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return v, f


def _cyl(cx, cy, r, z0, z1, n=24):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    bot = np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.full(n, z0)], 1)
    top = np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.full(n, z1)], 1)
    v = np.vstack([bot, top])
    f = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    return v, f


class Scene:
    """Inventory rows (mm) + meshes (scene units = mm, k = 1) the way max_scene.main hands them over."""

    def __init__(self):
        self.rows, self.meshes, self.i = [], {}, 0

    def group(self, name, parent=None):
        self.rows.append(dict(idx=None, name=name, cls="Dummy", **{"class": "Dummy"}, parent=parent, mods=[]))
        return name

    def mesh(self, name, vf, parent=None, mats=(), mods=()):
        self.i += 1
        v, f = vf
        v = np.asarray(v, float)
        r = dict(idx=self.i, name=name, parent=parent, mods=list(mods), material=(mats[0] if mats else None),
                 materials=list(mats), bbox=[v.min(0).tolist(), v.max(0).tolist()], nverts=len(v))
        r["class"] = "Editable Poly"
        r["cls"] = "Editable Poly"
        self.rows.append(r)
        self.meshes[self.i] = (name, v, [(0, list(x)) for x in f])


def _shell(sc):
    sc.group("Shell")
    for i, r in enumerate(((-200, -200, 10200, 0), (-200, 0, 0, 8000), (10000, 0, 10200, 8000), (-200, 8000, 10200, 8200))):
        sc.mesh("Wall%d" % i, _box(r[0], r[1], 0, r[2], r[3], 3000), parent="Shell")
    return [dict(id="W%d" % i, kind="existing", rect=list(r)) for i, r in
            enumerate(((-200, -200, 10200, 0), (-200, 0, 0, 8000), (10000, 0, 10200, 8000), (-200, 8000, 10200, 8200)))]


def _table(sc, name, cx, cy):
    g = sc.group(name)
    sc.mesh(name + "_top", _cyl(cx, cy, 350, 730, 750), parent=g, mats=["marble_white"])
    sc.mesh(name + "_leg", _cyl(cx, cy, 30, 0, 730, 12), parent=g, mats=["black metal"])


@pytest.fixture(scope="module")
def collected(tmp_path_factory):
    from importers import scene_items
    sc = Scene()
    walls = _shell(sc)
    for i, (x, y) in enumerate(((2000, 2000), (4000, 2000), (6000, 2000))):
        _table(sc, "Round_Table_%03d" % i, x, y)
    # a group of a table with its chairs: two pieces of different make
    g = sc.group("Dining set")
    sc.mesh("Set_table", _box(2000, 5000, 0, 3200, 5800, 750), parent=g, mats=["oak veneer"])
    sc.mesh("Set_chair_1", _box(2100, 4400, 0, 2600, 4900, 850), parent=g, mats=["chair fabric"])
    sc.mesh("Set_chair_2", _box(2700, 4400, 0, 3200, 4900, 850), parent=g, mats=["chair fabric"])
    # a built-in bench: a base and cushions as free objects resting on it, a back cushion against the wall
    sc.mesh("Object100", _box(9400, 3000, 0, 10000, 6000, 400), mats=["brick tile"])
    sc.mesh("Object101", _box(9400, 3000, 400, 10000, 4500, 550), mats=["Sofa_001"])
    sc.mesh("Object102", _box(9400, 4500, 400, 10000, 6000, 550), mats=["Sofa_002"])
    sc.mesh("Object103", _box(9900, 3000, 600, 10000, 6000, 900), mats=["zebra fabric"])
    # not furniture: a light, a plant, a column, decor on a table, a curtain rail
    sc.mesh("Arkoslight b101", _cyl(5000, 5000, 40, 2700, 3000), mats=["chrome"])
    sc.mesh("Ficus lyrata", _cyl(8000, 7000, 300, 0, 1800), mats=["leaf"])
    sc.mesh("Column", _box(5000, 4000, 0, 5400, 4400, 3000))
    sc.mesh("Vase decor", _cyl(4000, 2000, 60, 750, 1000), mats=["glass"])
    sc.mesh("Rail", _box(1000, 7900, 2500, 4500, 7940, 2540))
    # a shelf with an unevaluated Shell modifier: planes are boards
    g = sc.group("Shelf unit")
    for z in (0, 400, 800, 1200):
        sc.mesh("Board%d" % z, (np.array([(6000, 7600, z), (7200, 7600, z), (7200, 8000, z), (6000, 8000, z)], float),
                                [[0, 1, 2, 3]]), parent=g, mods=["Shell"], mats=["walnut wood"])
    sc.mesh("Side_L", (np.array([(6000, 7600, 0), (6000, 8000, 0), (6000, 8000, 1220), (6000, 7600, 1220)], float),
                       [[0, 1, 2, 3]]), parent=g, mods=["Shell"], mats=["walnut wood"])
    d = dict(walls=walls, furniture=[])
    out = str(tmp_path_factory.mktemp("imp"))
    items, signs = scene_items.collect(sc.rows, sc.meshes, 1.0, d, out)
    return dict(items=items, out=out)


def test_identical_tables_are_one_item_with_a_quantity(collected):
    tabs = [it for it in collected["items"] if "Round_Table" in it["src"]]
    assert len(tabs) == 1 and tabs[0]["qty"] == 3 and len(tabs[0]["places"]) == 3
    W, D, H = tabs[0]["size"]
    assert abs(W - 700) < 5 and abs(H - 750) < 5


def test_a_table_and_its_chairs_are_separate_items(collected):
    srcs = [it["src"] for it in collected["items"] if it["src"].startswith("Dining set")]
    assert len(srcs) == 2
    chairs = next(it for it in collected["items"] if "chair" in " ".join(it["mats"]))
    assert chairs["qty"] == 2


def test_bench_base_with_cushions_is_one_piece(collected):
    b = [it for it in collected["items"] if "Object100" in it["src"]]
    assert len(b) == 1 and all(n in b[0]["src"] for n in ("Object101", "Object102", "Object103"))
    assert b[0]["size"][2] == 900


def test_not_furniture_is_dropped(collected):
    txt = " ".join(it["src"] for it in collected["items"])
    for n in ("Arkoslight", "Ficus", "Column", "Vase", "Rail", "Wall"):
        assert n not in txt, n


def test_shell_planes_are_boards(collected):
    sh = [it for it in collected["items"] if it["src"] == "Shelf unit"]
    assert sh and sh[0]["size"][2] >= 1220
    m = pickle.load(open(os.path.join(collected["out"], "items", sh[0]["id"] + ".pkl"), "rb"))
    assert all(np.ptp(np.asarray(p["v"])[:, :3], axis=0).min() >= 19 for p in m["parts"])


def test_mesh_views_levels_and_round_top(collected, tmp_path):
    from sdalbum import items3d
    sh = next(it for it in collected["items"] if it["src"] == "Shelf unit")
    m = items3d.ItemMesh(pickle.load(open(os.path.join(collected["out"], "items", sh["id"] + ".pkl"), "rb")))
    lv = m.levels()
    assert [round(z) for z in lv[1:-1]] == [420, 820]           # shelf tops between the bottom and the top board
    tab = next(it for it in collected["items"] if "Round_Table" in it["src"])
    mt = items3d.ItemMesh(pickle.load(open(os.path.join(collected["out"], "items", tab["id"] + ".pkl"), "rb")))
    assert mt.round_top() and mt.top_board() == 20
    info = mt.view("front", str(tmp_path / "f.png"), px_per_mm=0.5)
    assert info["x0"] <= -350 and info["x1"] >= 350 and info["y0"] <= 0 and info["y1"] >= 750
    assert os.path.isfile(str(tmp_path / "f.png"))


def test_catmull_clark_smooths_a_cage():
    from sdalbum import items3d
    v, f = _box(0, 0, 0, 100, 100, 100)
    v2, f2 = items3d.subdivide(v, f)
    assert len(f2) == 24
    assert (v2[:8] > 0).all() and (v2[:8] < 100).all()                # the corners are rounded inside the cage
    edges = {}
    for fc in f2:
        for a, b in zip(fc, fc[1:] + fc[:1]):
            edges[(min(a, b), max(a, b))] = edges.get((min(a, b), max(a, b)), 0) + 1
    assert set(edges.values()) == {2}                                   # still closed


def test_classify_by_geometry_and_names():
    from sdalbum import items as IT
    from sdalbum import items3d

    def mesh(parts):
        return items3d.ItemMesh(dict(parts=[dict(name=n, mats=m, v=v.astype(np.float32), f=f) for n, m, (v, f) in parts]))
    bench = mesh([("Object1", ["Material #12"], _box(0, 0, 0, 3000, 600, 400)),
                  ("Object2", ["Sofa_001"], _box(0, 0, 400, 3000, 600, 550))])
    assert IT.classify(dict(src="Object1 + Object2", parts=[], mats=[]), bench) == "bench"
    table = mesh([("t", [], _cyl(0, 0, 400, 730, 750)), ("l", [], _cyl(0, 0, 30, 0, 730))])
    assert IT.classify(dict(src="Group1/Table_Chairs_010", parts=["Table_Chairs_010"], mats=[]), table) == "table"
    sofa = mesh([("Mesh_0", ["21 - Default65"], _box(0, 0, 0, 2600, 850, 800))])
    assert IT.classify(dict(src="Mesh_0", parts=[], mats=[]), sofa) == "sofa"


def _project(tmp_path):
    from importers import scene_items
    sc = Scene()
    walls = _shell(sc)
    _table(sc, "Round_Table_001", 3000, 3000)
    _table(sc, "Round_Table_002", 5000, 3000)
    items, _ = scene_items.collect(sc.rows, sc.meshes, 1.0, dict(walls=walls), str(tmp_path / "import"))
    rect = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    d = dict(meta=dict(object="Дизайн-проект интерьера кафе «Тест»"), levels=dict(floor=0, ceiling=2900, slab=3000),
             walls=walls, openings=[dict(id="Д1", kind="door", wall="W0", c=5000, w=900, h=2100)],
             rooms=[dict(name="Обеденный зал", seed=[5000, 4000])], furniture=[], lighting=[], switches=[], sockets=[],
             plumbing=[], floors=[], ceilings=dict(types=[], zones=[]), elevations=[], nodes=[], items=items)
    return d


def test_items_sheets_and_designer_data(tmp_path):
    from sdalbum import album, autofix, items as IT, model as M
    d = _project(tmp_path)
    d["item_overrides"] = [
        {"match": "Round_Table", "set": {"name": "Стол круглый Ø700 с мраморной столешницей", "size": [700, 700, 760],
                                          "elements": [["Столешница", "натуральный мрамор, 20 мм"], ["Опора", "сталь, чёрный мат"]]}},
        {"add": True, "id": "s1", "set": {"name": "Вывеска световая «RESTROOM»", "kind": "sign", "shape": "sign",
                                          "size": [1850, 150, 350], "text": "RESTROOM", "letter_h": 120, "return": 150,
                                          "elements": [["Короб", "алюминий"]]}}]
    base = str(tmp_path)
    d, flog, rest, qs = autofix.fix(d, base)
    log = IT.decide(d, base)
    assert log and log[0]["topic"] == "Мебель"
    tab = next(it for it in d["items"] if it.get("mesh"))
    assert tab["pos"] == "М-1" and tab["qty"] == 2 and tab["rooms"] == ["Обеденный зал"]
    assert tab["size"] == [700, 700, 760] and tab["elements"][0]["material"].startswith("натуральный мрамор")
    assert any(f.get("item") == "М-1" for f in d["furniture"])           # the plan of furniture got the tables
    P = M.Project(d, base)
    A = album.Album(P, str(tmp_path / "out"), sheets=["items"])
    titles = [s[2] for s in A.sheets]
    assert titles[0].endswith("Ведомость") and any("М-1" in t for t in titles) and any("RESTROOM" in t for t in titles)
    A.build(heal=False)
    errs = [i for i in A.issues if i.get("level") == "error"]
    assert not errs, errs
    from sdalbum import qa
    for no in A.layouts:
        issues, _ = qa.check_layout(A.doc, A.layouts[no], True)
        bad = [i for i in issues if i["level"] == "error" or i["code"].startswith("TYPO")]
        assert not bad, bad


def test_profile_piece_from_the_designer():
    """A straight sofa of two rolls described by its section (the model's cage was not the made piece)."""
    from sdalbum import items3d
    it = dict(size=[4300, 900, 700], profile=dict(length=4300, blocks=[
        dict(name="Сиденье", mat="velvet fabric", y0=0, y1=600, z0=40, z1=450, r=170),
        dict(name="Спинка", mat="velvet fabric", y0=600, y1=900, z0=40, z1=700, r=150)]))
    m = items3d.load(None, it)
    assert [round(x) for x in m.size] == [4300, 900, 700]
    assert 450 in [round(z) for z in m.levels()]


def test_big_ngon_is_triangulated_fast():
    """The cap of a free-form table top: one polygon of 1200 vertices (ear clipping took 100 s) - lesson L-084."""
    import time
    from sdalbum import raster3d
    n = 1200
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = 500 + 120 * np.sin(7 * a)                                  # a wavy, non-convex outline
    pts = np.stack([r * np.cos(a), r * np.sin(a), np.full(n, 750.0)], 1)
    t = time.time()
    tris = raster3d._triangles(pts)
    assert time.time() - t < 2.0
    assert len(tris) == n - 2


def test_faces_of_an_unevaluated_topology_do_not_cut_across_the_piece():
    """Metal rack (lesson L-087): the base object of a part edited by modifiers that are not evaluated has faces
    pointing at vertices that do not exist and big oblique faces from one shelf to another - drawn as triangles
    across the whole rack. A part with such faces drops its large oblique faces; a sound mesh keeps a sloped back."""
    from sdalbum import items3d
    v, f = _box(0, 0, 0, 1800, 450, 5)                      # a shelf plate
    v2, f2 = _box(0, 0, 600, 1800, 450, 605)                # the next shelf
    v = np.vstack([v, v2])
    f = f + [[i + 8 for i in x] for x in f2]
    f.append([0, 1, 14, 15])                                # oblique quad: front of one shelf to the back of the next
    f.append([3, 2, 16, 17])                                # a face of the stream pointing past the vertex list
    f.append([0, 6, 2])                                     # a sliver across the plate from corner to corner
    bad = items3d.Part(dict(name="shelves001", v=v, f=f))
    assert len(bad.f) == 12 and [0, 1, 14, 15] not in bad.f and [0, 6, 2] not in bad.f
    m = items3d.ItemMesh(dict(parts=[dict(name="shelves001", v=v, f=f + [[0, 5, 6, 3]])]))   # a plate face with a diagonal side
    L = m.edges(np.array([0.0, 0.0, 1.0]))
    long_oblique = [e for e in L if np.sort(np.abs(e[0] - e[1]))[1] > 150 and np.linalg.norm(e[0] - e[1]) > 300]
    assert not long_oblique
    back = np.array([(0, 0, 450), (500, 0, 450), (500, 120, 900), (0, 120, 900)], float)   # a sloped chair back
    ok = items3d.Part(dict(name="chair", v=back, f=[[0, 1, 2, 3]]))
    assert len(ok.f) == 1


def test_a_smooth_round_base_keeps_its_outline(tmp_path):
    """The cone of a table base is many nearly coplanar faces: its silhouette is drawn (the flipped-winding rule of
    L-087 must not erase it)."""
    from sdalbum import items3d
    v, f = _cyl(0, 0, 250, 0, 700, n=96)
    m = items3d.ItemMesh(dict(parts=[dict(name="base", v=v, f=f)]))
    L = m.edges(np.array([0.0, -1.0, 0.0]))
    vertical = [e for e in L if abs(e[0][2] - e[1][2]) > 600]
    assert len(vertical) >= 2                                      # the left and right outline of the cylinder


def _rack_with_garbage():
    """Two shelf plates and one big oblique face from the front of the lower shelf to the back of the upper one (a
    stream of an unevaluated topology), every index valid: nothing marks the part as unsound in advance."""
    v, f = _box(-900, -220, 0, 900, 220, 5)
    v2, f2 = _box(-900, -220, 600, 900, 220, 605)
    v = np.vstack([v, v2])
    f = f + [[i + 8 for i in x] for x in f2]
    f.append([0, 1, 14, 15])
    posts = []
    for x in (-880, 860):
        pv, pf = _box(x, -220, 0, x + 20, -200, 605)
        posts.append(dict(name="post", v=pv, f=pf))
    return dict(parts=[dict(name="shelves001", v=v, f=f)] + posts)


def test_render_self_check_heals_a_face_across_the_piece(tmp_path):
    """Lesson L-088: the views are checked before they go on the sheet; a big oblique face across the piece marks
    its part as unsound, the part is cleaned and the view drawn again."""
    from sdalbum import items3d
    m = items3d.ItemMesh(_rack_with_garbage())
    info = m.view("front", str(tmp_path / "f.png"), px_per_mm=0.3)
    assert info["healed"] == ["shelves001"] and not info["issues"]
    assert [0, 1, 14, 15] not in m.parts[0].f
    assert len(m.parts[1].f) == 6                                   # the posts are untouched


def test_render_self_check_leaves_sound_pieces_alone(tmp_path):
    from sdalbum import items3d
    back = (np.array([(-250, 0, 450), (250, 0, 450), (250, 120, 900), (-250, 120, 900)], float), [[0, 1, 2, 3]])
    seat = _box(-250, -250, 400, 250, 250, 450)
    cone = _cyl(0, 0, 200, 0, 400, n=48)
    m = items3d.ItemMesh(dict(parts=[dict(name=n, v=vf[0], f=vf[1]) for n, vf in
                                     (("back", back), ("seat", seat), ("base", cone))]))
    for kind in ("front", "left", "top"):
        info = m.view(kind, str(tmp_path / ("%s.png" % kind)), px_per_mm=0.4)
        assert not info["healed"] and not info["issues"], (kind, info["issues"])


def test_render_self_check_reports_an_empty_view(tmp_path):
    from sdalbum import items3d
    v = np.array([(0, 0, 0), (1000, 0, 0), (1000, 400, 700), (0, 400, 700)], float)       # one face, all garbage
    m = items3d.ItemMesh(dict(parts=[dict(name="x", v=v, f=[[0, 1, 2, 3]], unsound=True)]))
    info = m.view("front", str(tmp_path / "f.png"), px_per_mm=0.3)
    assert any(code == "RENDER_EMPTY" for code, msg in info["issues"])


def test_sheet_build_records_the_self_check(tmp_path):
    """The self-check runs once per item before its thumbnail and views; a cleaned part is recorded in the build."""
    from sdalbum import items3d, sheets_items

    class A_:
        issues = []
        cur_title = "x"

        class P:
            base_dir = str(tmp_path)
    data = _rack_with_garbage()
    fn = tmp_path / "rack.pkl"
    pickle.dump(data, open(fn, "wb"))
    A = A_()
    m = sheets_items._mesh(A, dict(id="r", pos="М-1", name="Стеллаж", mesh=str(fn)))
    assert m is not None and m.checked[0] == ["shelves001"]
    assert [i["code"] for i in A.issues] == ["RENDER_HEALED"]


def test_furniture_stands_parallel_to_the_wall_and_against_it(tmp_path):
    """Lesson L-089: the roll sofa of the cafe stood at 13° on the plan - its sections are bent by FFD modifiers
    that are not evaluated, the angle came from the bent cage. A piece within 15° of a wall direction is turned
    parallel to it; a sofa / bench / shelving is moved back to the wall it stands at."""
    from sdalbum import items as IT, model as M
    d = _project(tmp_path)
    P = M.Project(d, str(tmp_path))
    it = dict(kind="sofa", size=[3000, 900, 700], places=[[5000, 7400, 13]])
    IT._settle(it, P)
    x, y, ang = it["places"][0]
    assert ang == 0
    assert abs((y + 450) - 8000) <= 10                       # back face on the wall face y = 8000
    turned = dict(kind="armchair", size=[650, 650, 750], places=[[3000, 3000, 37]])
    IT._settle(turned, P)
    assert turned["places"][0][2] == 37                      # a chair turned on purpose keeps its angle


def test_a_shelving_around_a_column_is_not_moved_off_it(tmp_path):
    from sdalbum import items as IT, model as M
    d = _project(tmp_path)
    d["walls"].append(dict(id="C1", kind="existing", rect=[2800, 2800, 3200, 3200]))
    P = M.Project(d, str(tmp_path))
    it = dict(kind="shelving", size=[1800, 600, 2600], places=[[3000, 3000, 0]], columns=[[-200, -200, 200, 200]])
    IT._settle(it, P)
    assert it["places"][0][:2] == [3000, 3000]


def test_a_computed_shelf_plate_is_drawn():
    """Metal rack of the Sherov cafe (L-107): the shelves come out of the computed modifier stack - 1.8 m plates with
    rounded rims of many small faces. The broken-stream filter (L-087) took the plates for faces across the piece and
    the sketch showed posts without shelves. A part computed from the scene (sound) keeps every face."""
    from sdalbum import items3d
    v, f = _box(-892, -223, 0, 892, 223, 5)
    rim = []
    for i in range(600):                                   # the rounded rim: many short faces
        x = -892 + i * 1784.0 / 600
        rim.append(np.array([(x, -223, 0), (x + 2.9, -223, 0), (x + 2.9, -224, 2.5), (x, -224, 2.5)], float))
    v = np.vstack([v] + rim)
    f = f + [[8 + 4 * i, 9 + 4 * i, 10 + 4 * i, 11 + 4 * i] for i in range(600)]
    old = items3d.Part(dict(name="shelves001", v=v, f=f))
    assert len(old.f) < len(f)                             # the old filter drops the plate faces
    new = items3d.Part(dict(name="shelves001", v=v, f=f, sound=True))
    assert len(new.f) == len(f)
    m = items3d.ItemMesh(dict(parts=[dict(name="shelves001", v=v, f=f, sound=True)]))
    healed, rest = m.selfcheck()
    assert not healed and len(m.parts[0].f) == len(f)


def test_a_plank_on_the_wall_and_a_low_box_are_not_coffee_tables():
    """Sherov cafe (L-107): once the modifier stacks were computed, a 1049 x 229 x 31 ledge at +1013 and a bare box
    644 x 448 x 101 on the floor showed up as «Стол журнальный». Sitting furniture stands on the floor and a coffee
    table is at least 300 high: the plank is a wall shelf, the low box a podium."""
    from sdalbum import items as IT
    from sdalbum import items3d

    def one(vf):
        return items3d.ItemMesh(dict(parts=[dict(name="Box", mats=[], v=vf[0].astype(np.float32), f=vf[1])]))
    ledge = one(_box(0, 0, 0, 1049, 229, 31))            # item meshes are local: z from the piece's bottom
    it = dict(src="Box2131637797", parts=["Box"], mats=["Material #2147470827"], z0=1013)
    assert IT.classify(it, ledge) == "wall_shelf"
    assert IT.name_of("wall_shelf", dict(it, size=[1049, 229, 31]), ledge) == "Полка настенная 1050×230"
    low = one(_box(0, 0, 0, 644, 448, 101))
    assert IT.classify(dict(src="Box2131637803", parts=["Box"], mats=[], z0=0), low) == "podium"
    tbl = one(_box(0, 0, 0, 1000, 600, 450))
    assert IT.classify(dict(src="Box1", parts=["Box"], mats=[], z0=0), tbl) == "coffee_table"


def test_a_designer_entry_matching_two_different_pieces_does_not_double_them():
    """Seven bar tables in the designer's data («qty 7, h 750»); the computed model has 4 at 781 and 3 at 558. Both
    items matched the entry and each got qty 7 - 14 tables. Now each keeps the model's count and height, the
    names differ by the height and the disagreement goes to the report."""
    from sdalbum import items as IT
    made = [dict(id="u1", src="Group645", parts=["Modern_Black_Round_Bar_Table"], mats=[], size=[717, 717, 781], qty=4,
                 name="Стол", kind="table", notes=[]),
            dict(id="u2", src="Group746", parts=["Modern_Black_Round_Bar_Table"], mats=[], size=[717, 717, 558], qty=3,
                 name="Стол", kind="coffee_table", notes=[])]
    d = dict(item_overrides=[{"match": "Modern_Black_Round_Bar_Table", "set": {
        "name": "Стол круглый Ø700 с мраморной столешницей", "kind": "table", "size": [700, 700, 750], "qty": 7,
        "elements": [["Столешница", "мрамор"]], "notes": {"add": ["Высота стола 750 мм."]}}}])
    out = IT.apply_overrides(d, made, None)
    assert sorted(it["qty"] for it in out) == [3, 4]
    assert sorted(it["size"][2] for it in out) == [558, 781]
    assert len({it["name"] for it in out}) == 2 and all(it["name"].startswith("Стол круглый Ø700") for it in out)
    assert all("Высота стола 750 мм." in it["notes"] for it in out)              # the notes reach both pieces
    assert all(any(n.startswith("Размеры — по 3D-модели") for n in it["notes"][:2]) for it in out)   # the sheet asks
    assert all(("qty", 7, it["qty"]) in it["designer_vs_model"] for it in out)


def test_a_group_with_an_uncomputed_part_is_not_split(tmp_path):
    """Sherov sofa (L-107): the rolls of a sofa are stretched by FFD after an Edit Poly that could not be computed -
    their cages lie a metre away from the seat. The group was split into «Диван-валик 4300, h 640» and «…, h 90»;
    a group with such a part stays one piece (it is the designer's unit)."""
    from importers import scene_items
    sc = Scene()
    walls = _shell(sc)
    g = sc.group("Group690")
    sc.mesh("Object105", _box(3000, 3000, 0, 4000, 4000, 640), parent=g, mats=["Ma33"])
    sc.mesh("Cylinder1770", _box(6000, 6000, 0, 6784, 6100, 100), parent=g, mats=["Mat44"])
    sc.rows[-1]["geom"] = "unknown"
    items, _ = scene_items.collect(sc.rows, sc.meshes, 1.0, dict(walls=walls, furniture=[]), str(tmp_path / "imp"))
    assert [it["src"] for it in items] == ["Group690"]
    sc.rows[-1]["geom"] = "replayed"                          # computed: far apart, other material - two pieces
    items, _ = scene_items.collect(sc.rows, sc.meshes, 1.0, dict(walls=walls, furniture=[]), str(tmp_path / "imp2"))
    assert len([it for it in items if it["src"].startswith("Group690")]) == 2


def test_a_shelf_on_the_wall_keeps_its_outline_on_the_plan(tmp_path):
    """The shelf on top of a WC installation box (+1,013): on the plan it was cut by the box under it and by the WC to
    350 × 110 while its sketch says 1050 × 230. A piece hanging on the wall keeps its own outline."""
    from importers import scene_items
    from sdalbum import items as IT
    from shapely.geometry import Polygon
    sc = Scene()
    walls = _shell(sc)
    sc.mesh("Box2131637797", _box(2000, 0, 1013, 3049, 229, 1044), mats=["Material #2147470827"])
    items, _ = scene_items.collect(sc.rows, sc.meshes, 1.0, dict(walls=walls, furniture=[]), str(tmp_path / "import"))
    walls = walls + [dict(id="W9", kind="new", rect=[1950, 0, 3100, 113])]             # the installation box
    d = dict(meta=dict(object="т"), levels=dict(floor=0, ceiling=2900, slab=3000), walls=walls, openings=[],
             rooms=[dict(name="Санузел", seed=[5000, 4000])], lighting=[], switches=[], sockets=[], plumbing=[],
             floors=[], ceilings=dict(types=[], zones=[]), elevations=[], nodes=[], items=items,
             furniture=[dict(name="Унитаз подвесной", kind="wc", poly=[[2300, 113], [2650, 113], [2650, 650], [2300, 650]],
                             room="Санузел")])
    IT.decide(d, str(tmp_path))
    it = next(x for x in d["items"] if x["src"] == "Box2131637797")
    assert it["kind"] == "wall_shelf"
    f = next(x for x in d["furniture"] if x.get("item") == it["pos"])
    x0, y0, x1, y1 = Polygon(f["poly"]).bounds
    assert x1 - x0 > 1000 and y1 - y0 > 200 and f["z"][0] > 1000


def test_a_media_console_is_a_console():
    """«RH ST. JAMES PANEL 65" MEDIA CONSOLE» (778 × 311 × 553 under the WC lobby basin) came out as «Стол журнальный»."""
    from sdalbum import items as IT
    it = dict(src='RH ST. JAMES PANEL 65" MEDIA CONSOLE Antiqued Coffee001', parts=[], mats=[], size=[778, 311, 553], z0=0)
    assert IT.classify(it, None) == "console"
    assert IT.name_of("console", it, None) == "Консоль 780×310"


def test_a_piece_known_only_by_its_lattice_says_so_on_its_sketch(tmp_path):
    """The media console of the WC lobby is a Boolean under an FFD: only the lattice box is known. Its sketch shows
    that box - and says that the shape is not computed (L-107)."""
    from importers import scene_items
    from sdalbum import items as IT
    sc = Scene()
    walls = _shell(sc)
    sc.mesh('RH ST. JAMES PANEL 65" MEDIA CONSOLE Antiqued Coffee001', _box(3000, 0, 0, 3778, 311, 553), mats=["Antiqued Nickel"])
    sc.rows[-1]["geom"] = "unknown"
    sc.rows[-1]["geom_notes"] = ["габарит - по решётке последнего FFD (сетка внутри не вычислена)"]
    items, _ = scene_items.collect(sc.rows, sc.meshes, 1.0, dict(walls=walls, furniture=[]), str(tmp_path / "import"))
    assert items[0]["outline_only"]
    d = dict(meta=dict(object="т"), levels=dict(floor=0, ceiling=2900, slab=3000), walls=walls, openings=[],
             rooms=[dict(name="Тамбур", seed=[5000, 4000])], lighting=[], switches=[], sockets=[], plumbing=[],
             floors=[], ceilings=dict(types=[], zones=[]), elevations=[], nodes=[], items=items, furniture=[])
    IT.decide(d, str(tmp_path))
    it = d["items"][0]
    assert it["kind"] == "console" and any("не вычислена" in n for n in it["notes"])
