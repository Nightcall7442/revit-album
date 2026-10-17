# -*- coding: utf-8 -*-
"""The album checked against the 3ds Max scene (1.5): modifiers evaluated or honestly reported, every element traced
to its source object, the export of 3ds Max as the truth, DWG for the draftsman. Lessons L-098 .. L-101."""
import json
import os
import struct

import numpy as np
import pytest


def _op(op, offsets=None, sel=None, **params):
    return dict(op=op, sel=sel, offsets=None if offsets is None else np.asarray(offsets, float),
                params={int(k[1:]): struct.pack("<f", v) for k, v in params.items()})


# ------------------------------------------------------------------ modifiers without 3ds Max
def test_primitive_vertices_in_max_order():
    from importers.maxeval import prim_verts
    b = prim_verts("Box", {0: 208.0, 1: 10.0, 2: 300.0, 3: 1, 4: 1, 5: 1})
    assert b.shape == (8, 3)
    assert list(b[2][:2]) == [-5.0, 104.0] and list(b[3][:2]) == [5.0, 104.0]       # 2, 3: the +y end
    assert b[6][2] == 300.0
    p = prim_verts("Plane", {0: 40.0, 1: 22.0, 2: 1, 3: 1})
    assert p.shape == (4, 3) and list(p[0][:2]) == [-11.0, -20.0]
    assert prim_verts("Box", {0: 1.0, 1: 1.0, 2: 1.0, 3: 2, 4: 1, 5: 1}) is None       # more segments: not replayed


def test_a_shortened_partition_is_replayed():
    """The WC partition of the cafe: a Box 2080 long whose +y end was pulled back 580 mm in Edit Poly (L-099)."""
    from importers.maxeval import evaluate_stack
    off = np.zeros((8, 3))
    off[[2, 3, 6, 7], 1] = -58.03
    r = evaluate_stack([("Edit Poly", [_op(53, off)]), ("UVW Map", None)], "Box",
                       {0: 208.0, 1: 10.0, 2: 300.0, 3: 1, 4: 1, 5: 1}, unit_mm=10.0)
    assert r["status"] == "replayed"
    assert round((r["verts"][:, 1].max() - r["verts"][:, 1].min()) * 10) == 1500


def test_a_whole_wall_moved_after_extrusion_is_replayed():
    from importers.maxeval import evaluate_stack
    off = np.tile([-10.0, 0, 0], (12, 1))
    stack = [("Edit Poly", [_op(41, sel=(1, {0}), p37=300.0)]),
             ("Edit Poly", [_op(21, sel=(5, {0, 1, 2, 3, 4})), _op(70, p58=1.0)]),
             ("Edit Poly", [_op(53, off), _op(53, off)])]
    r = evaluate_stack(stack, "Plane", {0: 198.0, 1: 22.0, 2: 1, 3: 1}, unit_mm=10.0)
    assert r["status"] == "bound" and r["verts"] is not None
    assert round(r["verts"][:, 0].min() * 10) == -110 - 200                     # moved 200 mm with all its faces


def test_a_partial_move_after_topology_change_is_not_guessed():
    from importers.maxeval import evaluate_stack
    off = np.zeros((16, 3))
    off[12:, 1] = -90.0
    stack = [("Edit Poly", [_op(41, sel=(1, {0}), p37=300.0), _op(43, sel=(20, {1, 3})), _op(53, off)])]
    r = evaluate_stack(stack, "Plane", {0: 40.0, 1: 22.0, 2: 1, 3: 1}, unit_mm=10.0)
    assert r["status"] == "unknown" and r["verts"] is None


def test_vertical_moves_and_neutral_modifiers_keep_the_plan():
    from importers.maxeval import evaluate_stack
    off = np.zeros((24, 3))
    off[8:12, 2] = -20.0
    stack = [("UVW Map", None), ("Edit Poly", [_op(70, p58=2.0), _op(43, sel=(20, {1})), _op(53, off)]),
             ("Unwrap UVW", None)]
    assert evaluate_stack(stack, "Plane", {0: 40.0, 1: 22.0, 2: 1, 3: 1})["status"] == "bound"
    assert evaluate_stack([("UVW Map", None)], "Editable Poly", {})["status"] == "exact"
    assert evaluate_stack([("Symmetry", None)], "Editable Poly", {})["status"] == "unknown"
    assert evaluate_stack([("FFD 2x2x2", None)], "Editable Poly", {})["status"] == "unknown"
    assert evaluate_stack([("TurboSmooth", None)], "Editable Poly", {})["status"] == "bound"


def test_small_bevel_is_bounded_big_extrude_is_not():
    from importers.maxeval import evaluate_stack
    small = evaluate_stack([("Edit Poly", [_op(32, sel=(6, {2, 3}), p38=2.0, p39=0.228, p40=-0.33)])], "Box",
                           {0: 20.0, 1: 21.0, 2: 300.0, 3: 1, 4: 1, 5: 1}, unit_mm=10.0)
    assert small["status"] == "bound"
    big = evaluate_stack([("Edit Poly", [_op(91, sel=(9, {2}))])], "Plane", {0: 1.0, 1: 1.0, 2: 1, 3: 1})
    assert big["status"] == "unknown"                                            # the height is not recorded


# ------------------------------------------------------------------ the export of 3ds Max
def test_export_files_are_read(tmp_path):
    from importers import max_export as MX
    j, b = str(tmp_path / "s.sda.json"), str(tmp_path / "s.sda.bin")
    tri = [[0, 1, 2], [0, 2, 3]]
    nodes = [dict(n="Wall", h=1, tm=[[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]], bb=[[0, 0, 0], [10, 1, 300]],
                  mods=[["Edit_Poly", "Edit Poly", True, True]], hidden=False, node_hidden=False, renderable=True),
             dict(n="Wall", h=2, tm=[[1, 0, 0], [0, 1, 0], [0, 0, 1], [500, 0, 0]], bb=[[500, 0, 0], [510, 1, 300]],
                  mods=[], hidden=False, node_hidden=False, renderable=False),
             dict(n="Old", h=3, tm=[[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]], bb=[[0, 0, 0], [1, 1, 1]], mods=[],
                  hidden=True, node_hidden=True, renderable=True)]
    meshes = {"Wall": ([[0, 0, 0], [10, 0, 0], [10, 1, 0], [0, 1, 0]], tri)}
    MX.write_fixture(j, b, nodes, meshes, mm_per_unit=10.0)
    ex = MX.Export(j, b)
    assert ex.units_mm == 10.0
    v, f = ex.mesh(ex.nodes[0])
    assert v.shape == (4, 3) and f[1][1] == [0, 2, 3]
    assert ex.match("Wall", [499, 0, 0])["h"] == 2                              # same name: the nearest pivot
    used = set()                                                                # two copies in one place (L-111)
    assert ex.match("Wall", [499, 0, 0], used)["h"] == 2 and ex.match("Wall", [499, 0, 0], used)["h"] == 1
    assert ex.skipped(ex.nodes[1]).startswith("не рендерится")
    assert ex.skipped(ex.nodes[2]) == "скрыт в сцене"
    assert ex.active_mods(ex.nodes[0]) == ["Edit_Poly"]


def test_the_max_script_exports_what_the_reader_expects():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ms = open(os.path.join(here, "max", "sda_export.ms"), encoding="utf-8").read()
    for key in ('"format\\":\\"sda-export', "snapshotAsMesh", "isNodeHidden", "renderable", "mm_per_unit",
                "WriteFloat", "WriteLong", "WriteShort", "nodeGetBoundingBox", ".sda.json", ".sda.bin", "enabled"):
        assert key in ms, key
    assert ms.count("(") == ms.count(")")


def _export(tmp_path, nodes, meshes):
    from importers import max_export as MX
    j, b = str(tmp_path / "s.sda.json"), str(tmp_path / "s.sda.bin")
    MX.write_fixture(j, b, nodes, meshes, mm_per_unit=10.0)
    return MX, j, b


def _nd(n, h, hidden=False, mods=(), cls="Editable_Poly", sup="GeometryClass"):
    return dict(n=n, h=h, cls=cls, top=cls, sup=sup, tm=[[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]],
                bb=[[0, 0, 0], [1, 1, 1]], mods=[[m, m, True, True] for m in mods], hidden=hidden, node_hidden=hidden,
                renderable=True)


def test_export_offsets_of_max_2024_are_read(tmp_path):
    """L-110: 3ds Max 2024+ gives ftell as Integer64 - the script wrote "mesh":[0L,4,2] and the JSON did not parse."""
    tri = [[0, 1, 2], [0, 2, 3]]
    MX, j, b = _export(tmp_path, [_nd("A", 1), _nd("B", 2)],
                       {"A": ([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], tri), "B": ([[0, 0, 0], [2, 0, 0], [2, 2, 0]], [[0, 1, 2]])})
    txt = open(j, encoding="utf-8").read()
    import re
    txt = re.sub(r'"mesh": \[(\d+),', r'"mesh":[\1L,', txt)
    assert '"mesh":[0L,' in txt and '"mesh":[76L,' in txt
    open(j, "w", encoding="utf-8").write(txt)
    ex = MX.Export(j, b)
    v, f = ex.mesh(ex.nodes[1])
    assert v.shape == (3, 3) and v[1][0] == 2.0


def test_export_of_a_max_without_the_plugin_is_not_the_mesh(tmp_path):
    """L-110: exported where FloorGenerator is not installed, the modifier is "Missing_OSM" and did nothing - the
    mesh is the bare outline; the object keeps the agent's own evaluation and names the missing plugin."""
    from importers import max_scene as S
    MX, j, b = _export(tmp_path, [_nd("Floor_FG001", 1, mods=["Edit_Poly", "Uvwmap", "Missing_OSM"]), _nd("Wall", 2),
                                  _nd("Corona Light001", 3, cls="Missing_Light", sup="light")],
                       {"Floor_FG001": ([[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 1, 2]]),
                        "Wall": ([[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 1, 2]])})
    ex = MX.Export(j, b)
    assert ex.missing(ex.nodes[0]) == ["Missing_OSM"] and ex.missing(ex.nodes[1]) == []
    assert ex.missing(ex.nodes[2]) == ["Missing_Light"]
    assert S._missing_mods(["Edit Poly", "UVW Map", "FloorGenerator"], ex.nodes[0]) == ["FloorGenerator"]


def test_most_of_the_scene_hidden_is_the_working_state(tmp_path):
    """L-110: Sherov was saved with 1548 of 1609 objects hidden (only cameras shown): hiding is the designer's
    working state, not "not in the project". A few hidden objects among visible ones are left out as before."""
    from importers import max_scene as S
    tri = [[0, 1, 2]]
    pts = [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    MX, j, b = _export(tmp_path, [_nd("A", 1, hidden=True), _nd("B", 2, hidden=True), _nd("C", 3),
                                  _nd("Cam", 4, cls="Missing_Camera", sup="camera")],
                       {"A": (pts, tri), "B": (pts, tri), "C": (pts, tri)})
    ex = MX.Export(j, b)
    assert ex.hidden_ignored and ex.skipped(ex.nodes[0]) is None
    MX, j, b = _export(tmp_path, [_nd("A", 1, hidden=True), _nd("B", 2), _nd("C", 3)],
                       {"A": (pts, tri), "B": (pts, tri), "C": (pts, tri)})
    ex = MX.Export(j, b)
    assert not ex.hidden_ignored and ex.skipped(ex.nodes[0]) == "скрыт в сцене"
    rows = [dict(name="A", hidden_flag=True), dict(name="B", hidden_flag=True), dict(name="C", hidden_flag=False),
            dict(name="Light")]
    hid, n, ignored = S.hidden_state(rows)
    assert ignored and n == 3 and not any(r.get("render_off") for r in rows)
    rows = [dict(name="A", hidden_flag=True), dict(name="B", hidden_flag=False), dict(name="C", hidden_flag=False)]
    hid, n, ignored = S.hidden_state(rows)
    assert not ignored and [r["name"] for r in rows if r.get("render_off")] == ["A"]


def test_the_max_script_uses_no_reserved_words():
    """L-110: "local off = ftell bs" - off is a MAXScript constant (= false): the script stopped with a syntax error
    on its first real run. Its file offset is Integer64 in 3ds Max 2024+: written without the "L"."""
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ms = open(os.path.join(here, "max", "sda_export.ms"), encoding="utf-8").read()
    code = "\n".join(ln.split("--")[0] for ln in ms.splitlines())
    reserved = {"about", "and", "animate", "as", "at", "attributes", "by", "case", "catch", "collect", "continue",
                "coordsys", "do", "else", "exit", "fn", "for", "from", "function", "global", "if", "in", "local",
                "macroscript", "mapped", "max", "not", "of", "off", "on", "or", "parameters", "persistent", "plugin",
                "private", "public", "rcmenu", "return", "rollout", "set", "struct", "then", "throw", "to", "tool",
                "try", "undo", "utility", "when", "where", "while", "with", "true", "false", "undefined", "ok"}
    names = re.findall(r"\b(?:local|global)\s+([A-Za-z_]\w*)", code)
    names += [p for m in re.finditer(r"\bfn\s+\w+\s+([\w\s]*?)=", code) for p in m.group(1).split()]
    names += re.findall(r"\bfor\s+([A-Za-z_]\w*)\s+(?:=|in)\b", code)
    assert names and not [n for n in names if n.lower() in reserved]
    assert re.search(r'trimRight \(\w+ as string\) "L"', code)


# ------------------------------------------------------------------ the check of the album against the scene
def _scene(tmp_path, nodes, export=None):
    os.makedirs(tmp_path / "import", exist_ok=True)
    json.dump(dict(nodes=nodes, unit_mm=10.0, export=export), open(tmp_path / "import" / "inventory.json", "w"))
    return str(tmp_path)


def _row(name, rect, z0=0, z1=3000, cls="Editable Poly", **kw):
    x0, y0, x1, y1 = rect
    return dict(dict(name=name, **{"class": cls}, bbox=[[x0, y0, z0], [x1, y1, z1]], mods=[]), **kw)


def _proj(walls, **kw):
    d = dict(meta=dict(scene_shift=[-1000, -1000]), levels=dict(floor=0, ceiling=3000, slab=3000), walls=walls)
    d.update(kw)
    return d


def test_a_wall_longer_than_its_source_is_an_error(tmp_path):
    from sdalbum import audit
    base = _scene(tmp_path, [_row("Plane022", [1000, 1000, 4000, 1080]), _row("Plane019", [4000, 1000, 4220, 3000])])
    d = _proj([dict(id="W11", kind="existing", rect=[0, 0, 4520, 80], source="Plane022"),
               dict(id="W10", kind="existing", rect=[3000, 0, 3220, 2000], source="Plane019")])
    iss, sm = audit.run(d, base)
    geo = [i for i in iss if i["code"] == "SCENE_GEOMETRY"]
    assert [i["obj"] for i in geo] == ["W11"] and "1520" in geo[0]["msg"]


def test_an_element_built_from_an_unevaluated_object_is_an_error(tmp_path):
    from sdalbum import audit
    base = _scene(tmp_path, [_row("Plane013", [1000, 1000, 4000, 1200], geom="unknown",
                                  geom_notes=["Edit Poly: вершины сдвинуты после изменения топологии"]),
                             _row("Plane006", [5000, 1000, 5200, 4000], geom="bound")])
    d = _proj([dict(id="W4", kind="existing", rect=[0, 0, 3000, 200], source="Plane013"),
               dict(id="W1", kind="existing", rect=[4000, 0, 4200, 3000], source="Plane006")])
    iss, sm = audit.run(d, base)
    assert [i["obj"] for i in iss if i["code"] == "SCENE_UNVERIFIED"] == ["Plane013"]
    assert "sda_export.ms" in iss[0]["msg"] and sm["unverified"] == 1


def test_scene_objects_the_album_dropped_are_errors(tmp_path):
    from sdalbum import audit
    nodes = [_row("Plane006", [1000, 1000, 1200, 9000]),
             _row("Line260_FG021", [1200, 2000, 1840, 4400]),                  # a tiled pipe box: missing
             _row("Plane024_FG002", [3000, 3000, 3408, 3408], z1=3004),        # a column cladding: in the album
             _row("Detached", [1000, 5000, 1200, 6000]),                       # faces detached from the wall
             _row("Door leaf", [2000, 6000, 2873, 6321], z1=2200),             # lower than the storey: furniture
             _row("wd_oak_pisa", [-20000, -20000, -17500, -19800], z1=2950),   # parked far from the plan
             _row("Box1292", [0, 0, 8380, 8380], z1=8380)]                     # an environment box
    base = _scene(tmp_path, nodes)
    d = _proj([dict(id="W1", kind="existing", rect=[0, 0, 200, 8000], source="Plane006")],
              claddings=[dict(src="Plane024_FG002", on="W19", host="column")])
    iss, sm = audit.run(d, base)
    miss = [i["obj"] for i in iss if i["code"] == "SCENE_MISSING"]
    assert miss == ["Line260_FG021"]
    assert sm["outside"] == 1


def test_walls_the_agent_inferred_are_listed(tmp_path):
    from sdalbum import audit
    base = _scene(tmp_path, [_row("Plane006", [1000, 1000, 1200, 9000])])
    d = _proj([dict(id="W1", kind="existing", rect=[0, 0, 200, 8000], source="Plane006"),
               dict(id="ЗС2", kind="existing", rect=[200, 0, 1500, 200], source="закрыто по оборудованию")])
    iss, _ = audit.run(d, base)
    assert [(i["code"], i["level"]) for i in iss] == [("NOT_IN_SCENE", "warning")]


def test_no_scene_no_check(tmp_path):
    from sdalbum import audit
    iss, sm = audit.run(_proj([]), str(tmp_path))
    assert iss == [] and sm == dict(scene=False)


# ------------------------------------------------------------------ evidence of the scene
def test_tile_skins_and_tiled_shafts_are_told_apart():
    from importers import scene_surfaces as SS
    walls = [dict(id="W1", rect=[0, 0, 200, 6000], source="Plane006"), dict(id="W19", rect=[3000, 3000, 3400, 3400], source="Plane002")]

    def row(n, rect, z0, z1, **kw):
        r = dict(name=n, bbox=[[rect[0], rect[1], z0], [rect[2], rect[3], z1]], materials=["Material #101"], mods=[])
        r["class"] = "Editable Poly"
        r.update(kw)
        return r
    rows = [row("Plane024_FG002", [2996, 2996, 3404, 3404], 0, 3004),                # 4 mm of tile on the column
            row("Line260_FG021", [200, 2000, 838, 4400], 0, 3001),                   # a slanted pipe box at the wall
            row("Box1277_FG002", [1000, 5000, 4772, 5000], 250, 1200, mods=["FloorGenerator"]),   # bar front
            row("Box1277_FG001", [1000, 5000, 4772, 8169], 1200, 1200, mods=["FloorGenerator"])]  # bar top
    poly = [[200, 2000], [838, 2400], [838, 4000], [200, 4400]]
    got = {b["name"]: b for b in SS.boxes(rows, walls, outlines={"Line260_FG021": poly})}
    assert got["Plane024_FG002"]["kind"] == "cladding" and got["Plane024_FG002"]["host"] == "column"
    assert got["Line260_FG021"]["kind"] == "pipe" and got["Line260_FG021"]["poly"] == poly
    assert got["Box1277_FG002"]["kind"] == "cladding" and got["Box1277_FG001"]["kind"] == "cladding"


def test_claddings_belong_to_what_they_cover():
    from sdalbum import surfaces
    d = dict(walls=[dict(id="W19", kind="existing", rect=[3000, 3000, 3400, 3400], source="Plane002"),
                    dict(id="W1", kind="existing", rect=[0, 0, 200, 6000], source="Plane006"),
                    dict(id="К-6", kind="box", box="bar", poly=[[1000, 5000], [4772, 5000], [4772, 8169], [1000, 8169]])],
             _box_src=[dict(name="Plane024_FG002", kind="cladding", host="column", inner=[3000, 3000, 3400, 3400],
                            rect=[2996, 2996, 3404, 3404], tile=[100, 100]),
                       dict(name="Box1277_FG002", kind="cladding", host=None, rect=[1000, 5000, 4772, 5000]),
                       dict(name="Tile on wall", kind="cladding", host=None, rect=[200, 1000, 205, 2000]),
                       dict(name="Lost", kind="cladding", host=None, rect=[9000, 9000, 9100, 9000])])
    log = []
    surfaces._claddings(d, ".", log)
    on = {c["src"]: (c["on"], c["host"]) for c in d["claddings"]}
    assert on["Plane024_FG002"] == ("W19", "column") and on["Box1277_FG002"] == ("К-6", "box")
    assert on["Tile on wall"] == ("W1", "wall") and on["Lost"] == (None, None)
    assert "Lost" in log[0]["msg"]


# ------------------------------------------------------------------ DWG for the draftsman
def test_layout_names_fit_dwg_r2000():
    from sdalbum.dwg import layout_name
    used = set()
    a = layout_name("26 Мебель М-3 — Стол круглый Ø700 с мраморной столешницей", used)
    assert len(a) <= 31 and "Ø" not in a and "—" not in a
    a.encode("cp1251")
    b = layout_name("26 Мебель М-3 — Стол круглый Ø700 с мраморной столешницей", used)
    assert b != a                                                                # unique
    assert layout_name("07 План полов", used) == "07 План полов"


def test_handles_shifted_above_libredwg_reserved(tmp_path):
    from sdalbum.dwg import shift_handles
    src = tmp_path / "a.dxf"
    src.write_text("0\nLINE\n5\n1F\n330\nA\n8\nSD_Стены\n10\n5.0\n0\nEOF\n", encoding="utf-8")
    shift_handles(str(src), str(tmp_path / "b.dxf"), off=0x2000)
    out = (tmp_path / "b.dxf").read_text(encoding="utf-8").split("\n")
    assert out[3] == "201F" and out[5] == "200A" and out[7] == "SD_Стены" and out[9] == "5.0"


def test_editable_dxf_explodes_sheet_blocks(tmp_path):
    import ezdxf
    from sdalbum.dwg import editable_dxf
    doc = ezdxf.new("R2018")
    blk = doc.blocks.new("SD_04_0")
    blk.add_line((0, 0), (1000, 0), dxfattribs={"layer": "SD_Стены"})
    doc.modelspace().add_blockref("SD_04_0", (5000, 0))
    lay = doc.layouts.new("04 Обмерный план")
    lay.add_viewport(center=(100, 100), size=(100, 100), view_center_point=(5500, 0), view_height=2000)
    p = str(tmp_path / "a.dxf")
    doc.saveas(p)
    ren = editable_dxf(p, str(tmp_path / "e.dxf"), dwg_names=True)
    e = ezdxf.readfile(str(tmp_path / "e.dxf"))
    ents = [x.dxftype() for x in e.modelspace()]
    assert ents == ["LINE"] and e.modelspace()[0].dxf.start.x == 5000
    assert ren == {} and "04 Обмерный план" in e.layouts.names()


def test_a_plane_lying_on_the_floor_is_a_covering_zone():
    from importers import scene_surfaces as SS
    seg = lambda a, b: dict(p=[a, b], closed=False)
    base = dict(idx=1, name="Layer:0", mods=["FloorGenerator"], materials=["CORD 120x60"], fg_tile=[600.0, 600.0],
                lines=[seg((0, 0), (9000, 0)), seg((9000, 0), (9000, 9000)), seg((9000, 9000), (0, 9000)), seg((0, 9000), (0, 0))],
                lines_z=0.0)
    base["class"] = "SplineShape"
    zone = dict(idx=2, name="Plane11477", mods=["Edit Poly", "FFD 2x2x2"], materials=["Material #2147470841"],
                footprint=[[6000, 0], [8600, 0], [8600, 8100], [6000, 8100]], z0=4, z1=4)
    zone["class"] = "Plane"
    ground = dict(idx=3, name="Ground", mods=[], materials=["Material #1"],
                  footprint=[[-50000, -50000], [50000, -50000], [50000, 50000], [-50000, 50000]], z0=0, z1=0)
    ground["class"] = "Plane"
    fl = SS.floors([base, zone, ground], {}, 1.0)
    assert [(f["name"], f["kind"]) for f in fl] == [("Layer:0", "base"), ("Plane11477", "overlay")]
    assert fl[1]["plane"] and fl[1]["tile"] is None


def test_guessed_axes_and_model_outer_faces_are_not_dimensioned():
    """L-103: axes the agent guessed from the walls of a model and the outer faces of its walls are not dimensions."""
    import ezdxf
    from sdalbum import sheets_plans as SP

    class P:
        grid = {"x": [["1", 0], ["2", 4000]], "y": [["А", 0], ["Б", 3000]], "auto": True}

    class A:
        pass
    a = A()
    a.P = P()
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    SP.outer(a, msp, None, sides=("B", "L", "T", "R"))
    assert len(msp) == 0


def test_a_plastered_solid_on_a_wall_is_a_false_wall_a_door_is_not():
    from importers import scene_surfaces as SS
    walls = [dict(id="W7", rect=[0, 0, 200, 6000], source="Box006")]

    def row(n, rect, z0, z1, mats, tex=None):
        r = dict(name=n, bbox=[[rect[0], rect[1], z0], [rect[2], rect[3], z1]], materials=mats, mods=[])
        r["class"] = "Box"
        if tex:
            r["tex"] = tex
        return r
    rows = [row("Box3137", [213, 3000, 363, 4500], -473, 2527, ["Material #6"], ["Mat_P2/Texture/Tex_Plaster2_diff.tif"]),
            row("group1_pCube1", [213, 1000, 538, 1873], 0, 2198, ["Material #3"])]
    got = {b["name"]: b["kind"] for b in SS.boxes(rows, walls)}
    assert got == {"Box3137": "lining"}


def test_a_floor_zone_without_a_format_gets_none_invented(tmp_path):
    """L-104: the model does not say the tile of a zone - the album says «уточнить», never 100×100."""
    from sdalbum import autofix, surfaces
    from test_senior import _cafe
    d, *_ = autofix.fix(_cafe(), str(tmp_path))
    d["floors"] = []
    d["_floor_src"] = [dict(name="Layer:0", material="CORD 120x60", tile=[600, 600], kind="base", area=110, z=0,
                            polys=[[[0, 0], [12000, 0], [12000, 9000], [0, 9000]]], origin=[0, 0]),
                       dict(name="Plane11477", material="Material #2147470841", tile=None, tile_name=None, kind="overlay",
                            area=4.8, z=4, polys=[[[9500, 3300], [10700, 3300], [10700, 7300], [9500, 7300]]], plane=True)]
    log = []
    surfaces._floors(d, str(tmp_path), log)
    z = next(f for f in d["floors"] if f.get("src") == "Plane11477")
    assert z["pattern"] == "model" and "tile" not in z and "уточнить" in z["material"]


def test_a_full_column_continues_beside_the_plan_not_into_the_stamp():
    import ezdxf
    from sdalbum.album import Column

    class Alb:
        issues = []
        cur_title = "07 План полов"

        def band_free(self, need):
            return False

        def spill_regions(self):
            return [(185.0, 258.0, 110.0, 36.0)]
    a = Alb()
    psp = ezdxf.new("R2018").layouts.new("07")
    col = Column(a, psp, top=60.0)                       # almost full: 24 mm left above the bottom
    col.notes(["Строка примечания номер %d, достаточно длинная, чтобы переноситься на вторую строку." % i for i in range(8)])
    assert a.issues == [] and col.x == 185.0


def test_a_long_specification_runs_on_beside_the_plan_not_into_the_stamp():
    """Sherov cafe (L-109): with every piece of the scene computed the furniture specification grew to 32 rows - one
    table taller than the column and than the free strip beside the plan, drawn into the title block. The rows now
    run on from the strip beside the plan into the column, the header repeated."""
    import ezdxf
    from sdalbum.album import Column, COL_X, COL_TOP, COL_BOTTOM

    class Alb:
        issues = []
        cur_title = "06 План расстановки мебели"

        def band_free(self, need):
            return False

        def spill_regions(self):
            return [(190.0, COL_TOP, 105.0, COL_BOTTOM)]
    a = Alb()
    doc = ezdxf.new("R2018")
    psp = doc.layouts.new("06")
    col = Column(a, psp)
    rows = [[str(i + 1), "Изделие номер %d с длинным названием на две строки" % (i + 1), "1000×600", "1", "Обеденный зал"]
            for i in range(40)]
    col.table([9, 41, 21, 8, 30], ["Поз.", "Наименование", "Габариты, мм", "Кол.", "Помещение"], rows,
              title="Спецификация мебели и оборудования", h=1.6)
    assert a.issues == []
    texts = [e for e in psp if e.dxftype() in ("TEXT", "MTEXT")]
    ys = [e.dxf.insert[1] for e in texts]
    assert min(ys) >= COL_BOTTOM - 1.0                   # nothing under the column bottom (the title block)
    xs = {round(e.dxf.insert[0]) for e in texts if "Поз." in (e.dxf.text if e.dxftype() == "TEXT" else e.text)}
    assert len(xs) == 2 and min(xs) < COL_X <= max(xs) + 5   # the header twice: beside the plan and in the column


def test_dwg_archive_carries_the_images_of_the_sheets(tmp_path):
    import zipfile
    import ezdxf
    from PIL import Image
    from sdalbum.dwg import images_of, pack
    Image.new("RGB", (8, 8), "white").save(tmp_path / "item_М-1_a.png")
    doc = ezdxf.new("R2018")
    d = doc.add_image_def(filename="item_М-1_a.png", size_in_pixel=(8, 8))
    doc.layouts.new("24 Мебель").add_image(d, insert=(0, 0), size_in_units=(10, 10))
    p = str(tmp_path / "album_edit.dxf")
    doc.saveas(p)
    assert images_of(p) == ["item_М-1_a.png"]
    z = pack(str(tmp_path), ["album_edit.dxf", "item_М-1_a.png", "missing.png"], str(tmp_path / "a.zip"))
    assert sorted(zipfile.ZipFile(z).namelist()) == ["album_edit.dxf", "item_М-1_a.png"]


def test_unverified_album_carries_a_red_line_on_every_sheet(tmp_path):
    """L-100: an album with open scene-check errors is built for review only - every sheet says so in red inside
    the frame, and the line breaks no sheet check."""
    from conftest import STUDIO
    from sdalbum import album, qa
    w = "НЕ СВЕРЕНО СО СЦЕНОЙ 3ds Max (3) - НЕ ДЛЯ ВЫДАЧИ И СТРОИТЕЛЬСТВА"
    A = album.build(STUDIO, str(tmp_path / "a"), ["cover", "measured"], warning=w)
    names = [n for n in A.doc.layouts.names_in_taborder() if n != "Model" and len(A.doc.layouts.get(n))]
    assert len(names) == 2
    for n in names:
        hits = [t for t in A.doc.layouts.get(n).query("TEXT MTEXT")
                if "НЕ СВЕРЕНО" in (t.dxf.text if t.dxftype() == "TEXT" else t.text)]
        assert len(hits) == 1, n
        x, y = hits[0].dxf.insert[0], hits[0].dxf.insert[1]
        assert 20 < x <= 415 and 5 < y <= 292, (n, x, y)
    rep = qa.check_doc(A.doc)
    assert not [i for v in rep.values() for i in v if i["level"] == "error"]
    B = album.build(STUDIO, str(tmp_path / "b"), ["measured"])
    assert not [t for n in B.doc.layouts.names_in_taborder() if n != "Model"
                for t in B.doc.layouts.get(n).query("TEXT MTEXT")
                if "НЕ СВЕРЕНО" in (t.dxf.text if t.dxftype() == "TEXT" else t.text)]


def test_dwg_has_no_empty_default_tab(tmp_path):
    """The draftsman sees only the sheets of the album: ezdxf's empty Layout1 is not carried into DWG / edit DXF."""
    import ezdxf
    from sdalbum.dwg import editable_dxf
    doc = ezdxf.new("R2018")
    doc.layouts.new("01 Обложка").add_line((0, 0), (10, 0))
    src, dst = str(tmp_path / "a.dxf"), str(tmp_path / "b.dxf")
    doc.saveas(src)
    editable_dxf(src, dst, dwg_names=True)
    assert [n for n in ezdxf.readfile(dst).layouts.names_in_taborder() if n != "Model"] == ["01 Обложка"]


def test_a_partition_through_doors_is_the_agents_not_the_door(tmp_path):
    """L-106: the WC front partition runs wall to wall through two glass doors; the door is its evidence. Taking
    the door for the partition's outline made a 1224 mm "error" once the door's FFD was computed."""
    from sdalbum import audit
    base = _scene(tmp_path, [_row("Glass_Door_21_001", [6894, -905, 7774, -785], geom="replayed")])
    d = _proj([dict(id="ПГ1", kind="new", rect=[4670, -1905, 6870, -1805],
                    source="перегородка по двери Glass_Door_21_001", evidence="Glass_Door_21_001")])
    iss, sm = audit.run(d, base)
    assert not [i for i in iss if i["code"] == "SCENE_GEOMETRY"]
    assert [i["obj"] for i in iss if i["code"] == "NOT_IN_SCENE"] == ["ПГ1"]
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "importers",
                            "scene_draft.py"), encoding="utf-8").read()
    assert 'source="перегородка по двери %s"' in src


def test_a_wall_with_piers_is_cut_into_its_rectangles():
    """L-112: Sherov's Plane021 (ProBoolean, known only from 3ds Max's export): a 130 mm wall with a passage and two
    120 mm piers. Its box (250 mm over 7 m) became one thick wall over the shelves of the toilets. The cut is split into
    rectangles; the sides of the passage, open in the mesh, are closed."""
    from importers import max_scene as S
    segs = [[9172, 193, 12802, 193], [13702, 193, 16202, 193], [9172, 193, 9172, 323], [16202, 193, 16202, 323],
            [9172, 323, 12802, 323], [13702, 323, 16202, 323], [12382, 323, 12382, 443], [12382, 443, 12802, 443],
            [13702, 443, 13902, 443], [13902, 443, 13902, 323]]          # passage sides x 12802 / 13702: open
    parts = S.plan_parts(segs)
    assert sorted(parts) == sorted([[9172, 193, 12802, 323], [13702, 193, 16202, 323], [12382, 323, 12802, 443],
                                    [13702, 323, 13902, 443]])
    door_gap = [[0, 0, 900, 0], [0, 200, 900, 200], [0, 0, 0, 200], [900, 0, 900, 200],
                [1800, 0, 4000, 0], [1800, 200, 4000, 200], [1800, 0, 1800, 200], [4000, 0, 4000, 200]]
    assert S.plan_parts(door_gap) is None                                   # one straight wall: its gap is a door
    assert S.plan_parts([[0, 0, 4000, 0], [0, 200, 4000, 200], [0, 0, 0, 200], [4000, 0, 4000, 200]]) is None


def test_a_wall_from_a_piece_of_a_cut_object_is_not_an_error(tmp_path):
    from sdalbum import audit
    row = _row("Plane021", [9172, 193, 16202, 443], plan_parts=[[9172, 193, 12802, 323], [13702, 193, 16202, 323],
                                                                [12382, 323, 12802, 443], [13702, 323, 13902, 443]])
    base = _scene(tmp_path, [row])
    d = _proj([dict(id="W2", kind="existing", rect=[8172, -807, 11802, -677], source="Plane021")])
    iss, sm = audit.run(d, base)
    assert not [i for i in iss if i["code"] == "SCENE_GEOMETRY"]


def test_calibration_compares_vertex_by_vertex_then_as_shapes():
    """L-111: sda.py calibrate - the agent's mesh against 3ds Max's: same index = exact; same points in another
    order = same_shape (an Edit Poly above would move other vertices); else different / count."""
    import numpy as np
    from importers import max_calibrate as C
    a = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], float)
    assert C.compare(a, a + 0.01, 10.0)[0] == "exact"
    assert C.compare(a, a[[1, 0, 3, 2]], 10.0)[0] == "same_shape"
    assert C.compare(a, a + [0, 0, 5], 10.0)[0] == "different"
    assert C.compare(a, a[:3], 10.0)[0] == "count"


def test_an_object_of_a_missing_plugin_asks_for_the_plugin(tmp_path):
    """L-110: the export was made in a 3ds Max without FloorGenerator - the album asks for an export where the
    plugin is installed, not for "an export" it already has."""
    from sdalbum import audit
    row = _row("Layer:0", [0, 0, 4000, 3000], z0=0, z1=10, geom="unknown", export_missing=["FloorGenerator"])
    base = _scene(tmp_path, [row], export="s.sda.json")
    d = _proj([], floors=[dict(id="П1", src="Layer:0", poly=[[0, 0], [4000, 0], [4000, 3000], [0, 3000]])])
    iss, sm = audit.run(d, base)
    un = [i for i in iss if i["code"] == "SCENE_UNVERIFIED"]
    assert un and "FloorGenerator" in un[0]["msg"] and "плагин" in un[0]["msg"]


def test_an_empty_mesh_of_3ds_max_is_no_geometry(tmp_path):
    """L-112: Edit Poly deleted every face of Sherov's Plane004 (a Plane primitive): 3ds Max exports 0 vertices.
    The row kept the primitive's footprint and became a pilaster wall over a pipe box."""
    from importers import max_scene as S
    MX, j, b = _export(tmp_path, [_nd("Plane004", 8, mods=["Edit_Poly"], cls="Plane"), _nd("Wall", 9)],
                       {"Plane004": (np.zeros((0, 3)), np.zeros((0, 3), int)),
                        "Wall": ([[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 1, 2]])})
    ex = MX.Export(j, b)
    meshes = {}
    row = dict(idx=1, name="Plane004", footprint=[[0, 0], [20, 0], [20, 40], [0, 40]])
    S.take_export(row, ex, ex.nodes[0], meshes)
    assert "footprint" not in row and row["skip"] and 1 not in meshes
    row = dict(idx=2, name="Wall", footprint=[[0, 0], [1, 0], [1, 1]])
    S.take_export(row, ex, ex.nodes[1], meshes)
    assert "footprint" not in row and not row.get("skip") and 2 in meshes and row["nverts"] == 3


def test_a_floor_base_plane_and_a_street_plane_are_not_lost_coverings(tmp_path):
    """L-112: with 3ds Max's export Sherov's Layer:004 (the CORD plane under the FloorGenerator tiles of the floors)
    and Plane11503 (2.8 × 8.2 m, half of it outside the building) became «покрытие пола не учтено» errors. The plane
    of the material of an album floor is that floor; a plane mostly outside the rooms is not the interior's."""
    from sdalbum import audit
    walls = [dict(id="W1", kind="existing", rect=[-200, -200, 6200, 0]), dict(id="W2", kind="existing", rect=[-200, 4000, 6200, 4200]),
             dict(id="W3", kind="existing", rect=[-200, 0, 0, 4000]), dict(id="W4", kind="existing", rect=[6000, 0, 6200, 4000])]
    rows = [_row("Layer:0", [1000, 1000, 7000, 5000], z0=0, z1=10, mods=["FloorGenerator"], materials=["CORD 120x60"]),
            _row("Layer:004", [1000, 1000, 7000, 5000], z0=0, z1=0.5, materials=["CORD 120x60"]),
            _row("Plane11503", [5000, -3000, 7500, 3000], z0=4, z1=6, materials=["Material #2147470841"]),
            _row("Plane77", [2000, 2000, 4000, 4000], z0=0, z1=2, materials=["Wood"])]
    for i, w in enumerate(walls):
        x0, y0, x1, y1 = w["rect"]
        rows.append(_row("Wall%d" % i, [x0 + 1000, y0 + 1000, x1 + 1000, y1 + 1000]))
        w["source"] = "Wall%d" % i
    base = _scene(tmp_path, rows)
    d = _proj(walls, rooms=[dict(name="Зал", seed=[3000, 2000])], floors=[dict(id="П1", src="Layer:0", rooms=["Зал"])])
    iss, sm = audit.run(d, base)
    miss = [i["obj"] for i in iss if i["code"] == "SCENE_MISSING"]
    assert miss == ["Plane77"]                    # a covering inside the room the album does not have: still found
