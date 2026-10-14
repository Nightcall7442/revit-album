# -*- coding: utf-8 -*-
"""What the modifier stack of a node did to its geometry - without 3ds Max (lesson L-099).

A .max file stores base objects (Box / Plane parameters, Editable Poly meshes) and the modifiers with their own data;
the result of the stack is not stored. Taking the base object for the result is how a WC partition shortened by
580 mm in Edit Poly came out 580 mm too long in the album. Here every node gets an honest status:

    exact      the read geometry is the result: no modifiers, or only modifiers that do not move geometry
               (UVW Map, material IDs, smoothing groups, selections, FloorGenerator over its input outline)
    replayed   Edit Poly moves of vertices replayed on the primitive's own vertices (Box / Plane 1 segment):
               the vertex count stored with every move must equal the primitive's - a check of the replay itself
    bound      faces were only cut / connected / detached / deleted, or moved by at most `tol` mm (bevel 2 mm):
               nothing lies outside the read geometry, the plan outline is the read one
    unknown    vertices moved after the topology changed, Symmetry, FFD, Shell, Bend ...: the read geometry is NOT
               the scene's. The album must not be built from it - the export of 3ds Max (sda_export.ms) is needed.

Edit Poly operations are ids of epolyModButtonOp (iEPolyMod.h): 53 transform, 41 extrude face, 43 connect edge,
70 set material ... parameters are epolyModParameters ids (37 extrude height, 39 bevel height, 40 bevel outline ...).
"""
import struct

import numpy as np

OP_NAMES = {0: "null", 9: "cap", 10: "delete vertex", 11: "delete face", 12: "detach vertex", 13: "detach face",
            14: "split", 15: "break", 16: "collapse vertex", 17: "collapse edge", 18: "collapse face", 20: "slice",
            21: "slice face", 22: "weld vertex", 23: "weld edge", 25: "make planar", 26: "remove iso verts",
            27: "meshsmooth", 28: "tessellate", 29: "retriangulate", 30: "flip face", 31: "flip element", 32: "bevel",
            33: "chamfer vertex", 34: "chamfer edge", 35: "cut", 38: "inset", 39: "extrude vertex", 40: "extrude edge",
            41: "extrude face", 42: "extrude along spline", 43: "connect edge", 44: "connect vertex", 45: "hinge",
            49: "remove vertex", 50: "remove edge", 51: "outline", 53: "transform", 54: "delete edge", 56: "create",
            57: "align", 58: "attach", 59: "target weld vertex", 60: "target weld edge", 62: "create edge",
            63: "clone vertex", 64: "clone edge", 65: "clone face", 66: "insert vertex edge", 67: "insert vertex face",
            68: "autosmooth", 69: "smooth", 70: "set material", 74: "bridge border", 75: "bridge polygon",
            76: "make planar x", 77: "make planar y", 78: "make planar z", 79: "turn edge", 80: "relax",
            81: "paint deform", 82: "bridge edge", 84: "remove edge+verts", 91: "extrude face (post)",
            92: "extrude face (finalize)"}
# no geometry change at all
NEUTRAL_OPS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 24, 26, 29, 30, 31, 36, 37, 46, 47, 48, 52, 61, 68, 69, 70, 71, 72, 73, 79,
               83, 85, 86, 87, 88, 89, 90}
# the surface stays where it was (new edges / vertices on it) or loses faces: nothing outside the read geometry
INSIDE_OPS = {10, 11, 12, 13, 14, 15, 20, 21, 35, 43, 44, 50, 54, 62, 66, 67, 84}
# geometry grows by at most a parameter (mm after scale): {op: parameter ids whose |values| add up}
BOUNDED_OPS = {32: (39, 40), 38: (42,), 51: (43,), 41: (37,), 91: (37,), 92: (37,), 33: (28,), 34: (35,),
               39: (30, 29), 40: (33, 34)}
NEUTRAL_MODS = {"UVW Map", "UVW Mapping", "Unwrap UVW", "UVW Xform", "UVW Mapping Add", "UVW Mapping Clear",
                "Material", "MaterialByElement", "Smooth", "Normal", "Edit Normals", "Mesh Select", "Poly Select",
                "Vol. Select", "Optimize", "ProOptimizer", "Cap Holes", "Turn to Poly", "Turn to Mesh", "Turn to Patch",
                "CoronaDisplacementMod", "VRayDisplacementMod", "Patch Select", "Spline Select", "Mesh Cleaner"}
# the result lies inside the input (rounded corners, subdivided cage): plan outline at most the read one
INSIDE_MODS = {"TurboSmooth", "MeshSmooth", "OpenSubdiv", "Chamfer", "Relax", "Quadify Mesh", "Subdivide",
               "Tessellate", "FloorGenerator", "Slice"}


def _b(ch):
    d = getattr(ch, "data", None)
    return bytes(d) if isinstance(d, (bytes, bytearray, memoryview)) else b""


def _bits(ch):
    """BitArray chunk (0x2700 inside): count + bytes -> set of indices."""
    raw = b""
    for c in getattr(ch, "children", None) or []:
        if c.types == 0x2700:
            raw = _b(c)
    if not raw and _b(ch):
        raw = _b(ch)
    if len(raw) < 4:
        return 0, set()
    n = struct.unpack_from("<I", raw, 0)[0]
    out = set()
    for i, byte in enumerate(raw[4:]):
        for k in range(8):
            if byte >> k & 1 and i * 8 + k < n:
                out.add(i * 8 + k)
    return n, out


def edit_poly_ops(block):
    """Local data of an Edit Poly mod context (chunk 0x2512) -> [{op, sel, params, offsets}] in the order applied."""
    lmd = None
    for c in getattr(block, "children", None) or []:
        if c.types == 0x2512:
            lmd = c
    if lmd is None or not getattr(lmd, "children", None):
        return []
    ops = []
    for c in lmd.children:
        if c.types == 0x0230:
            raw = _b(c)
            ops.append(dict(op=struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else -1, sel=None, params={},
                            offsets=None, mats={}, extra={}, local={}))
        elif c.types == 0x0234 and ops:
            for d in getattr(c, "children", None) or []:
                if d.types != 0x0600:
                    if _b(d):
                        ops[-1]["extra"][d.types] = _b(d)
                    continue
                for e in getattr(d, "children", None) or []:
                    if e.types == 0x0400:
                        ops[-1]["sel"] = _bits(e)
                    elif e.types == 0x0410:
                        raw = _b(e)
                        if len(raw) >= 8:
                            pid = struct.unpack_from("<I", raw, 0)[0]
                            ops[-1]["params"][pid] = raw[4:8]
                    elif e.types in (0x0420, 0x0430):          # Matrix3 parameters (slice plane ...)
                        for g in getattr(e, "children", None) or []:
                            raw = _b(g)
                            if g.types == 0x03E8 and len(raw) == 48:
                                ops[-1]["mats"][e.types] = np.frombuffer(raw, "<f4").reshape(4, 3).astype(np.float64)
                    elif _b(e):
                        ops[-1]["extra"][e.types] = _b(e)
        elif c.types == 0x0238 and ops:
            n, data = 0, b""
            for d in getattr(c, "children", None) or []:
                if d.types == 0x12C3:
                    n = struct.unpack_from("<I", _b(d), 0)[0]
                elif d.types == 0x12C4:
                    data = _b(d)
                elif _b(d):
                    ops[-1]["local"][d.types] = _b(d)
            if n and len(data) >= n * 12:
                ops[-1]["offsets"] = np.frombuffer(data, dtype="<f4", count=n * 3).reshape(-1, 3).astype(np.float64)
    return ops


def _pf(params, pid):
    raw = params.get(pid)
    return struct.unpack("<f", raw)[0] if raw else 0.0


def prim_params(base, R):
    """ParamBlock2 of a primitive -> {pid: float | int}."""
    out = {}
    try:
        refs = R.M.get_references(base) or []
    except Exception:
        return out
    for r in refs:
        if r is None or R.cls_name(r) != "ParamBlock2":
            continue
        for c in getattr(r, "children", []):
            if c.types != 0x100E or isinstance(c.data, tuple):
                continue
            b = bytes(c.data)
            if len(b) != 19:
                continue
            pid, typ = struct.unpack_from("<HH", b, 0)
            if typ in (0, 7):
                out[pid] = struct.unpack_from("<f", b, 15)[0]
            elif typ == 1:
                out[pid] = struct.unpack_from("<i", b, 15)[0]
        break
    return out


def prim_verts(cls, prm):
    """Object-space vertices of a Box / Plane with one segment per side, in 3ds Max's own order (bottom row -y,
    left to right, then +y; Box: the same again at the top). None for other primitives / more segments."""
    if cls == "Plane" and prm.get(2, 1) == 1 and prm.get(3, 1) == 1 and 0 in prm and 1 in prm:
        L, W = prm[0], prm[1]
        return np.array([[-W / 2, -L / 2, 0], [W / 2, -L / 2, 0], [-W / 2, L / 2, 0], [W / 2, L / 2, 0]], float)
    if cls == "Box" and all(prm.get(k, 1) == 1 for k in (3, 4, 5)) and all(k in prm for k in (0, 1, 2)):
        L, W, H = prm[0], prm[1], prm[2]
        bot = [[-W / 2, -L / 2, 0], [W / 2, -L / 2, 0], [-W / 2, L / 2, 0], [W / 2, L / 2, 0]]
        return np.array(bot + [[x, y, H] for x, y, _ in bot], float)
    return None


def read_stack(msh, R):
    """Derived-object chain of a node -> ([(modifier class, [Edit Poly ops] | None)] bottom -> top, base object)."""
    M = R.M
    stack = []
    seen = 0
    cur = msh
    while cur is not None and M.get_guid(cur) in (0x2032, 0x2033) and seen < 20:
        refs = M.get_references(cur) or []
        mods = [R.cls_name(r) if r is not None else None for r in refs[:-1]]
        blocks = [c for c in getattr(cur, "children", []) if c.types == 0x2500]
        level = [(m, edit_poly_ops(b) if (m == "Edit Poly" and b is not None) else None)
                 for m, b in zip(mods, blocks + [None] * (len(mods) - len(blocks)))]
        stack = list(reversed(level)) + stack          # inner derived objects are applied first
        cur = refs[-1] if refs else None
        seen += 1
    return stack, cur


def evaluate(msh, R, base=None, cls=None, W=None, unit_mm=10.0, tol_mm=5.0):
    """-> {status, verts (object space, replayed) | None, notes [..], mods [..]}. W: world matrix (4x4) of the node
    (an offset whose plan component is 0 after W is a vertical move: harmless for the plan)."""
    stack, cur = read_stack(msh, R)
    base = base if base is not None else cur
    cls = cls or (R.cls_name(base) if base is not None else None)
    prm = prim_params(base, R) if cls in ("Box", "Plane") else {}
    return evaluate_stack(stack, cls, prm, W, unit_mm, tol_mm)


def evaluate_stack(stack, cls, prm, W=None, unit_mm=10.0, tol_mm=5.0):
    """The modifier stack (bottom -> top) of a base object of class `cls` with primitive parameters `prm`."""
    res = dict(status="exact", verts=None, notes=[], mods=[m for m, _ in stack], prim=prm)
    if not stack:
        return res
    verts = prim_verts(cls, prm) if cls in ("Box", "Plane") else None
    plane_flat = cls == "Plane"
    topo_same = verts is not None                    # vertex numbering still the primitive's
    status = "exact"
    rank = {"exact": 0, "replayed": 1, "bound": 2, "unknown": 3}

    def worse(s, note):
        nonlocal status
        if rank[s] > rank[status]:
            status = s
        if note and note not in res["notes"]:
            res["notes"].append(note)

    Wr = np.asarray(W, float)[:3, :3] if W is not None else np.eye(3)
    first_geo = True
    moved = False
    for mname, ops in stack:
        if mname in NEUTRAL_MODS or mname is None:
            continue
        if mname in INSIDE_MODS:
            worse("bound", "%s: форма внутри исходной" % mname)
            if mname != "FloorGenerator":
                topo_same = False
            continue
        if mname != "Edit Poly":
            worse("unknown", "модификатор %s не вычисляется" % mname)
            topo_same = False
            continue
        for op in ops or []:
            o = op["op"]
            nm = OP_NAMES.get(o, "op %d" % o)
            if o in NEUTRAL_OPS:
                continue
            if o == 53:                                       # transform: per-vertex offsets
                off = op.get("offsets")
                if off is None or not np.any(np.abs(off) > 1e-6):
                    continue
                off = np.asarray(off, float)
                plan = off @ Wr.T
                if np.all(np.hypot(plan[:, 0], plan[:, 1]) * unit_mm < 0.5):
                    worse("bound", "Edit Poly: перемещения только по высоте")
                    continue
                if topo_same and verts is not None and len(off) == len(verts):
                    verts = verts + off
                    moved = True
                    worse("replayed", "Edit Poly: перемещение вершин повторено")
                    continue
                if np.all(np.abs(off - off[0]) < 1e-5):          # the whole object moved: exact for any topology
                    if verts is not None:
                        verts = verts + off[0]
                        moved = True
                        worse("replayed", "Edit Poly: объект целиком сдвинут на %.0f мм" % (
                            float(np.hypot(*(off[0] @ Wr.T)[:2])) * unit_mm))
                    else:
                        worse("unknown", "Edit Poly: объект целиком сдвинут, а исходная форма не прочитана")
                    continue
                worse("unknown", "Edit Poly: вершины сдвинуты после изменения топологии")
                continue
            if o == 41 and first_geo and plane_flat and op.get("sel") and op["sel"][0] == 1:
                # the first extrusion of the whole Plane: a vertical sweep - the plan outline stays the plane's
                topo_same = False                            # the order of the new vertices is MNMesh's own
                first_geo = False
                worse("bound", "Edit Poly: выдавливание плоскости вверх")
                continue
            first_geo = False
            if o in INSIDE_OPS:
                topo_same = False
                worse("bound", "Edit Poly: %s" % nm)
                continue
            if o in BOUNDED_OPS:
                params = op.get("params") or {}
                if o == 32:                                      # bevel: faces go out by the height, the outline
                    d = (abs(_pf(params, 39)) + max(0.0, _pf(params, 40))) * unit_mm   # < 0 shrinks
                else:
                    d = sum(abs(_pf(params, p)) for p in BOUNDED_OPS[o]) * unit_mm
                topo_same = False
                if not any(p in params for p in BOUNDED_OPS[o]):
                    worse("unknown", "Edit Poly: %s - величина не записана" % nm)
                elif d <= tol_mm:
                    worse("bound", "Edit Poly: %s на %.1f мм" % (nm, d))
                else:
                    worse("unknown", "Edit Poly: %s на %.0f мм - форма меняется" % (nm, d))
                continue
            topo_same = False
            worse("unknown", "Edit Poly: %s - не вычисляется" % nm)
    res["status"] = status
    # the replayed outline stays the plan bound through later cuts / detaches (they move no vertex)
    res["verts"] = verts if moved and status != "unknown" else None
    return res
