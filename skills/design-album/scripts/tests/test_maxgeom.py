# -*- coding: utf-8 -*-
"""L-105: the agent rebuilds a 3ds Max modifier stack itself - no 3ds Max. Real stacks of the Sherov cafe scene
(tests/data/stacks_sherov.json, read from the .max by maxstack) must replay with every count 3ds Max saved, and
the result must be the geometry the designer built (door 891 x 2100 in wall W4, the tile strip of floor P6 ...)."""
import json
import os
import struct
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "importers"))

import maxgeom as G  # noqa: E402

DATA = os.path.join(HERE, "data", "stacks_sherov.json")


def _load(name):
    raw = json.load(open(DATA, encoding="utf-8"))[name]
    b = dict(raw["base"])
    if "prim" in b:
        b["prim"] = {int(k): v for k, v in b["prim"].items()}
    if "verts" in b:
        b["verts"] = np.array(b["verts"], float)
        if b.get("edges"):
            b["edges"] = [tuple(e) for e in b["edges"]]
    mods = []
    for m in raw["mods"]:
        r = dict(cls=m["cls"], ctx_tm=np.array(m["ctx_tm"]), ctx_box=None if m["ctx_box"] is None else np.array(m["ctx_box"]),
                 pb={int(k): v for k, v in m["pb"].items()}, final=m.get("final"),
                 gizmo=None if m.get("gizmo") is None else np.array(m["gizmo"]),
                 chunks={int(k): bytes.fromhex(v) for k, v in m["chunks"].items()})
        if m["ops"] is None:
            r["ops"] = None
        else:
            r["ops"] = [dict(op=o["op"], sel=None if o["sel"] is None else (o["sel"][0], set(o["sel"][1])),
                             params={int(k): bytes.fromhex(v) for k, v in o["params"].items()},
                             offsets=None if o["offsets"] is None else np.array(o["offsets"], float),
                             mats={int(k): np.array(v) for k, v in o["mats"].items()})
                        for o in m["ops"]]
        mods.append(r)
    return dict(base=b, mods=mods)


def test_plane_and_box_are_numbered_as_mnmesh():
    """A Plane is the quad [2, 0, 1, 3] with edges in triangle order (the long edges of a wall are 1 and 3 -
    as the connects of wall W4 select them); a Box keeps the bottom face first, the top second."""
    p = G.plane({0: 20.0, 1: 322.0})
    assert p.f == [[2, 0, 1, 3]]
    assert [e[:2] for e in p.e] == [[2, 0], [3, 2], [1, 3], [0, 1]]
    b = G.box({0: 1.0, 1: 1.0, 2: 1.0})
    assert b.counts() == (8, 12, 6)
    assert b.normal(0)[2] < 0 and b.normal(1)[2] > 0


def test_wall_w4_with_door_is_rebuilt_exactly():
    """Plane013 (wall W4): extrude 300, slice, two connects, a smart extrude through the wall (the door), the head
    lowered to 2100 - every saved count agrees and the door is 891 x 2100 at x -146.7 .. -57.6."""
    m, log = G.evaluate(_load("Plane013"))
    assert m.counts() == (24, 46, 21)
    assert getattr(m, "inferred", False)              # the renumbered stitch: found by geometry, the only way
    v = m.v
    assert np.isclose(v[:, 0].min(), -159.0) and np.isclose(v[:, 0].max(), 271.0)
    assert np.isclose(v[:, 2].max(), 300.0)
    slice_z = sorted(set(np.round(v[:, 2], 2)))
    assert slice_z == [0.0, 210.0, 300.0]             # 229.98 lowered by 19.98: the door head is 2100
    door_x = sorted(set(np.round(v[(np.isclose(v[:, 2], 210.0)), 0], 2)))
    assert -146.72 in door_x and -57.59 in door_x


def test_floor_strip_p6_outline_is_the_designers():
    """Plane025 (floor P6): connect, clone edge (deleted again), clone edge, transforms -> a strip 402 x 8250 mm;
    FloorGenerator lays its tiles inside it."""
    m, log = G.evaluate(_load("Plane025"))
    assert getattr(m, "fg_outline", False)
    assert np.isclose(m.v[:, 0].min(), 1.7, atol=0.01) and np.isclose(m.v[:, 0].max(), 41.95, atol=0.01)
    assert np.isclose(m.v[:, 1].min(), -244.0, atol=0.01) and np.isclose(m.v[:, 1].max(), 580.95, atol=0.01)
    assert m.floor["length"] == 10.0 and m.floor["width"] == 10.0


def test_box_k1_becomes_a_ledge_stretched_by_the_designer():
    """Box2131637795: the box faces were deleted, a cloned and extruded lid stays (L profile after a smart extrude
    stitched onto its walls), Chamfer 4 segments, then the back moved 109 mm: a 1049 x 229 x 31 mm ledge."""
    m, log = G.evaluate(_load("Box2131637795"))
    assert [c for c, _ in log] == ["Edit Poly", "Chamfer", "Edit Poly"]
    assert log[0][1] == (12, 18, 8) and log[1][1] == (228, 450, 224)
    size = m.v.max(0) - m.v.min(0)
    assert np.allclose(size, [104.92, 22.94, 3.06], atol=0.01)


def test_light_moves_replay_on_the_editable_poly():
    m, log = G.evaluate(_load("Arkoslight b189"))
    assert m.counts() == (56, 102, 48)


def test_turbosmooth_numbers_vertices_as_3ds_max():
    """A bar table leg: TurboSmooth 1 step, then the upper rings moved up 180 mm and down 223 mm. 3ds Max numbers
    the smoothed vertices cage - face centres - edge points: the moved set is then exactly the upper band, and both
    moves replay directly (no guessing, the earlier 'two variants' stop is gone)."""
    st = _load("Modern_Black_Round_Bar_Table_032")
    m = G.from_base(st["base"])
    G.mod_turbosmooth(m, st["mods"][0])
    assert m.counts() == (468, 900, 432)
    off = st["mods"][1]["ops"][0]["offsets"]
    moved = np.abs(off).max(1) > 1e-9
    assert m.v[moved, 2].min() > m.v[~moved, 2].max() + 5     # a band, not a scatter
    m, log = G.evaluate(st)
    assert not getattr(m, "inferred", False)
    assert np.isclose(np.ptp(m.v[:, 2]), 18.79, atol=0.01)


def test_ffd_lattice_is_the_mod_context_box():
    """FFD 2x2x2 / 4x4x4: control points (lattice space) over the box of the modifier's context; the input bounding
    box equals that box - the base mesh and the context transform are read right."""
    st = _load("Object2089580086")
    m = G.from_base(st["base"])
    mod = st["mods"][0]
    C = mod["ctx_tm"]
    q = (C[:3, :3] @ m.v.T).T + C[:3, 3]
    lo, hi = mod["ctx_box"]
    assert np.all(q.min(0) >= lo - 1e-3) and np.all(q.max(0) <= hi + 1e-3)
    G.mod_ffd(m, mod, 2)
    q2 = (C[:3, :3] @ m.v.T).T + C[:3, 3]
    assert q2[:, 1].min() < q[:, 1].min() - 5            # the lattice moved: the shape changed


def test_ffd_with_untouched_lattice_changes_nothing():
    m = G.box({0: 10.0, 1: 20.0, 2: 30.0})
    v0 = m.v.copy()
    pts = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], float)
    mod = dict(chunks={0x0200: pts.astype("<f4").tobytes()}, ctx_tm=np.eye(4),
               ctx_box=np.array([v0.min(0), v0.max(0)]), gizmo=np.eye(4), pb={})
    G.mod_ffd(m, mod, 2)
    assert np.allclose(m.v, v0)


def test_symmetry_keeps_the_positive_side_and_mirrors_it():
    """Symmetry X: the half x < 0 is cut away, the half x >= 0 mirrored and welded on the seam."""
    m = G.box({0: 10.0, 1: 20.0, 2: 10.0})
    m.v[:, 0] += 4.0                                      # x from -6 to 14
    mod = dict(pb={0: 0, 1: 1, 2: 1, 3: 0.01, 6: 1, 7: 0, 8: 0, 9: 0}, gizmo=np.eye(4), ctx_tm=np.eye(4))
    G.mod_symmetry(m, mod)
    assert np.isclose(m.v[:, 0].min(), -14.0) and np.isclose(m.v[:, 0].max(), 14.0)


def test_unknown_operation_is_not_guessed():
    m = G.plane({0: 10.0, 1: 10.0})
    with pytest.raises(G.ReplayError):
        G.replay_edit_poly(m, [dict(op=45, sel=(1, {0}), params={}, offsets=None, mats={})])


def test_a_transform_count_that_disagrees_stops_the_replay():
    m = G.plane({0: 10.0, 1: 10.0})
    with pytest.raises(G.ReplayError):
        G.replay_edit_poly(m, [dict(op=53, sel=(0, set()), params={}, offsets=np.zeros((5, 3)), mats={})])


def test_face_list_iterates_like_the_importer_lists():
    fl = G.FaceList([[0, 1, 2], [2, 3, 4, 5]], [1, 7])
    assert len(fl) == 2 and list(fl) == [(1, [0, 1, 2]), (7, [2, 3, 4, 5])] and fl[1] == (7, [2, 3, 4, 5])


def test_editable_poly_dead_vertices_are_dropped():
    """MNMesh saves a dead vertex as its flags only: the reader keeps the order of the living ones."""
    import maxstack as S

    class C:
        def __init__(self, t, data):
            self.types, self.data, self.children = t, data, []

    class P:
        def __init__(self, ch):
            self.children = ch

        def get_first(self, t):
            return self if t == 0x08FE else None
    verts = struct.pack("<I", 4) + struct.pack("<I3f", 0, 0, 0, 0) + struct.pack("<I", 2) + \
        struct.pack("<I3f", 0, 1, 0, 0) + struct.pack("<I3f", 0, 1, 1, 0)
    face = struct.pack("<I", 1) + struct.pack("<i", 3) + struct.pack("<3i", 0, 2, 3) + struct.pack("<H", 0)
    poly = P([C(0x0100, verts), C(0x011A, face)])
    got = S.editable_poly(poly)
    assert got["verts"].tolist() == [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    assert got["faces"] == [[0, 1, 2]]


def _sym_away():
    C = np.eye(4)
    C[0, 3] = 20.0                                        # the box lies at x 15..25 of the mirror space
    return dict(cls="Symmetry", pb={0: 0, 1: 1, 2: 1, 3: 0.01, 6: 1, 7: 0, 8: 0, 9: 1}, gizmo=np.eye(4), ctx_tm=C,
                ctx_box=None, ops=None, chunks={}, final=None)


def test_an_empty_result_needs_the_scene_to_say_so():
    """Sofa of the Sherov cafe (L-107): a Symmetry that cuts the whole piece away is accepted only when the next
    Edit Poly saved a face selection of 0 faces (3ds Max gave it nothing); otherwise it is our reading of the gizmo
    and the piece must not silently vanish from the album."""
    base = dict(cls="Box", prim={0: 10.0, 1: 10.0, 2: 10.0})
    with pytest.raises(G.ReplayError):
        G.evaluate(dict(base=base, mods=[_sym_away()]))
    ep = dict(cls="Edit Poly", ops=[dict(op=11, sel=(0, set()), params={}, offsets=None, mats={})],
              final={"v": 0, "e": 0, "f": 0}, pb={}, chunks={}, ctx_tm=np.eye(4), ctx_box=None, gizmo=None)
    m, log = G.evaluate(dict(base=base, mods=[_sym_away(), ep]))
    assert m.counts() == (0, 0, 0)
    seen = dict(ep, ops=[dict(op=11, sel=(6, set()), params={}, offsets=None, mats={})], final={"v": 8, "e": 12, "f": 6})
    with pytest.raises(G.ReplayError):                     # the Edit Poly got 6 faces: the empty cut is wrong
        G.evaluate(dict(base=base, mods=[_sym_away(), seen]))


def test_an_uncomputed_stack_ending_with_ffd_takes_the_lattice_as_its_outline(monkeypatch):
    """Sofa of the Sherov cafe (L-107): the rolls go through an Edit Poly that cannot be computed and then an FFD
    that stretches them 3.4 times to 4.3 m along the wall. Their cages lay a metre away at 45 degrees and the sofa
    stood across the hall on the plan; the deformed lattice of the last FFD is where 3ds Max shows the piece."""
    import max_scene as MSC
    import maxstack as MS
    pts = np.array([[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], float)
    pts[:, 1] = np.where(pts[:, 1] == 0, -1.267, 2.169)              # the lattice stretched along y
    ffd = dict(cls="FFD 2x2x2", ctx_tm=np.eye(4), ctx_box=np.array([[-44.2, -62.5, 0.0], [44.2, 62.5, 66.6]]),
               chunks={0x0200: pts.astype("<f4").tobytes()}, pb={}, ops=None, gizmo=np.eye(4), final=None)
    st = dict(base=dict(cls="Box", prim={0: 10.0, 1: 10.0, 2: 10.0}),
              mods=[dict(cls="Edit Poly", ops=[], final=None), ffd])
    monkeypatch.setattr(MS, "read", lambda R, msh: st)
    W = np.eye(4)
    W[:3, 3] = [100.0, 200.0, 0.0]
    row, meshes = dict(idx=7, name="Object2089580105"), {}
    assert MSC._lattice_proxy(None, None, W, row, meshes)
    lo, hi = np.array(row["bbox"])
    assert np.allclose(hi - lo, [88.4, 125.0 * 3.436, 66.6], atol=0.05)
    assert np.allclose(lo[:2], [100.0 - 44.2, 200.0 - 62.5 - 1.267 * 125.0], atol=0.05)
    assert len(meshes[7][1]) == 8 and "не вычислена" in row["geom_notes"][-1]


def test_bezier_float_value_without_wrapper_is_read(monkeypatch):
    """L-111: Bezier Float keeps its value in 0x7127/0x2501, but objects merged from libraries hold 0x2501 directly:
    the parser read 0 and put 293 Sherov objects (plants, pots, a lamp) at the origin with no rotation - 3ds Max's
    export showed them 9-18 m away."""
    import maxread as R

    class Ch:
        def __init__(self, typ, data=None, kids=(), guid=None):
            self.types, self.data, self.children, self.guid = typ, data, list(kids), guid

        def get_first(self, t):
            return next((c for c in self.children if c.types == t), None)

    monkeypatch.setattr(R.M, "get_guid", lambda c: c.guid if c.guid is not None else c.types)
    wrapped = Ch(0, kids=[Ch(0x7127, kids=[Ch(0x2501, (12.5,))])], guid=0x2007)
    direct = Ch(0, kids=[Ch(0x2035, (2,)), Ch(0x2501, (1845.4215,))], guid=0x2007)
    empty = Ch(0, kids=[Ch(0x2035, (2,))], guid=0x2007)
    assert R.M.get_point is R.get_point
    assert R.get_point(wrapped) == 12.5
    assert abs(R.get_point(direct) - 1845.4215) < 1e-6
    assert R.get_point(empty, 7.0) == 7.0


def test_symmetry_numbers_the_mirror_as_3ds_max():
    """L-111: 3ds Max numbers the mirrored vertices as it meets them going over the faces (each loop as stored) and
    a mirrored face keeps its first vertex: [a b c d] -> [a' d' c' b']. The agent numbered them by vertex index -
    the same shape, but an Edit Poly above moved other vertices (Sherov pCube1: 1461 mm off)."""
    m = G.Mesh([[1, 0, 0], [2, 0, 0], [3, 0, 0], [1, 1, 0], [2, 1, 0], [3, 1, 0]], [[0, 1, 4, 3], [1, 2, 5, 4]])
    mod = dict(pb={0: 0, 1: 1, 2: 1, 3: 0.01, 6: 1, 7: 0, 8: 0, 9: 0}, gizmo=np.eye(4), ctx_tm=np.eye(4))
    G.mod_symmetry(m, mod)
    src = [0, 1, 4, 3, 2, 5]                                  # met over face 0, then face 1
    assert np.allclose(m.v[6:], m.v[src] * [-1, 1, 1])
    assert m.f[2] == [6, 9, 8, 7] and m.f[3] == [7, 8, 11, 10]


def test_cloned_faces_number_vertices_as_met():
    """L-111: Edit Poly "clone face" numbers the new vertices as it meets them over the selected faces."""
    m = G.plane({0: 10.0, 1: 20.0, 2: 1, 3: 2})              # 2 quads, 6 vertices
    loop = list(m.f[1])
    G.op_clone_faces(m, {1})
    assert len(m.v) == 10 and np.allclose(m.v[6:], m.v[loop]) and m.f[-1] == [6, 7, 8, 9]


def test_pcube1_is_rebuilt_vertex_by_vertex_as_3ds_max():
    """L-111: Symmetry, then Edit Poly (delete, clone face, 4 vertex moves by index) - every vertex where 3ds Max
    2027 has it (its export of Sherov), not only the same shape."""
    truth = json.load(open(os.path.join(HERE, "data", "max_truth_sherov.json"), encoding="utf-8"))["pCube1"]
    m, log = G.evaluate(_load("pCube1"))
    assert len(m.v) == truth["n"] == 1464
    idx = np.array([int(i) for i in truth["verts"]])
    want = np.array(list(truth["verts"].values()))
    assert np.abs(m.v[idx] - want).max() < 0.01
