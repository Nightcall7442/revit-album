# -*- coding: utf-8 -*-
"""The modifier stack of a .max node as plain data (lesson L-105).

3ds Max does not save the result of a modifier stack - it rebuilds it on load from what IS saved: the base object
(primitive parameters or the Editable Poly mesh) and every modifier with its own data. This module reads exactly
that into plain Python structures, so `maxgeom` can rebuild the result the same way 3ds Max does:

    node -> {name, base: {cls, prim | verts + faces}, mods: [{cls, ctx_tm, ctx_box, ops, pb, chunks, refs}] bottom->top}

* ctx_tm (4x4, object -> mod context space) and ctx_box (min, max in mod context space) are the ModContext saved for
  every modifier instance (chunks 0x2510 / 0x2511 in the derived object).
* ops: Edit Poly operation list (op id, selection, parameters, per-vertex offsets of transforms).
* pb: ParamBlock2 values {pid: value}; chunks: the modifier's own chunks {type: bytes}; refs: referenced objects.
* gizmo: a PRS controller under the modifier evaluated at frame 0 (4x4) - the mirror of Symmetry, the lattice of FFD.
"""
import struct

import numpy as np

import maxeval as E


def _b(ch):
    d = getattr(ch, "data", None)
    return bytes(d) if isinstance(d, (bytes, bytearray, memoryview)) else None


def refs_of(M, obj):
    """References of a chunk object: 0x2034 (list) or 0x2035 (index -> object), as a list with None gaps."""
    if obj is None:
        return []
    try:
        r = obj.get_first(0x2034)
        if r is not None and isinstance(r.data, tuple):
            return [M.get_node(i) if i != 0xFFFFFFFF and i >= 0 else None for i in r.data]
        r = obj.get_first(0x2035)
        if r is not None and isinstance(r.data, tuple) and len(r.data) > 1:
            d = r.data
            out = {}
            k = 1
            while k + 1 < len(d):
                out[d[k]] = M.get_node(d[k + 1]) if d[k + 1] not in (0xFFFFFFFF, -1) else None
                k += 2
            n = max(out) + 1 if out else 0
            return [out.get(i) for i in range(n)]
    except Exception:
        return []
    return []


def param_block2(R, pb):
    """ParamBlock2 -> {pid: float | int}. 19-byte 0x100E chunks: pid u16, type u16, ..., value at byte 15."""
    out = {}
    for c in getattr(pb, "children", None) or []:
        if c.types != 0x100E:
            continue
        b = _b(c)
        if b is None or len(b) != 19:
            continue
        pid, typ = struct.unpack_from("<HH", b, 0)
        t = typ & 0xFF
        if t in (0, 5, 7):                     # float, angle, world units
            out[pid] = struct.unpack_from("<f", b, 15)[0]
        elif t in (1, 4):                      # int, BOOL
            out[pid] = struct.unpack_from("<i", b, 15)[0]
    return out


def _float_ctrl(R, c):
    """Constant value of a Bezier / linear float controller (frame 0)."""
    if c is None:
        return 0.0
    for ch in getattr(c, "children", None) or []:
        if ch.types == 0x7127:
            for k in getattr(ch, "children", None) or []:
                if k.types == 0x2501 and isinstance(k.data, tuple) and k.data:
                    return float(k.data[0])
        if ch.types == 0x2501 and isinstance(ch.data, tuple) and ch.data:
            return float(ch.data[0])
    return None


def _euler(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _quat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def prs(R, c):
    """Position/Rotation/Scale controller at frame 0 -> 4x4 (column vectors) or None when not readable."""
    M = R.M
    if c is None or R.cls_name(c) != "Position/Rotation/Scale":
        return None
    pos, rot, scl = (refs_of(M, c) + [None, None, None])[:3]
    T = np.eye(4)
    p = None
    if pos is not None:
        nm = R.cls_name(pos)
        if nm == "Position XYZ":
            v = [_float_ctrl(R, x) for x in (refs_of(M, pos) + [None] * 3)[:3]]
            p = None if any(x is None for x in v) else v
        else:
            for ch in getattr(pos, "children", None) or []:
                if ch.types in (0x2503, 0x2501) and isinstance(ch.data, tuple) and len(ch.data) >= 3:
                    p = [float(x) for x in ch.data[:3]]
    if p is None:
        return None
    Rm = np.eye(3)
    if rot is not None:
        nm = R.cls_name(rot)
        if nm == "Euler XYZ":
            v = [_float_ctrl(R, x) for x in (refs_of(M, rot) + [None] * 3)[:3]]
            if any(x is None for x in v):
                return None
            Rm = _euler(*v)
        else:
            q = None
            for ch in getattr(rot, "children", None) or []:
                if ch.types in (0x2504, 0x2501) and isinstance(ch.data, tuple) and len(ch.data) >= 4:
                    q = [float(x) for x in ch.data[:4]]
            if q is None:
                return None
            Rm = _quat(q)
    S = np.eye(3)
    if scl is not None:
        for ch in getattr(scl, "children", None) or []:
            if ch.types == 0x2505 and isinstance(ch.data, tuple) and len(ch.data) >= 7:
                s = [float(x) for x in ch.data[:3]]
                qa = _quat([float(x) for x in ch.data[3:7]])
                S = qa @ np.diag(s) @ qa.T
    T[:3, :3] = Rm @ S
    T[:3, 3] = p
    return T


def ctx_of(block):
    """ModContext of a modifier instance: (tm 4x4 object -> mod context, box (2x3) | None)."""
    tm = np.eye(4)
    box = None
    for c in getattr(block, "children", None) or []:
        if c.types == 0x2510 and isinstance(c.data, tuple) and len(c.data) >= 12:
            d = [float(x) for x in c.data[:12]]
            m = np.eye(4)
            m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = d[0:3], d[3:6], d[6:9], d[9:12]
            # 3ds Max rows are axes: p' = p.x*row0 + p.y*row1 + p.z*row2 + row3
            tm = m
        elif c.types == 0x2511 and isinstance(c.data, tuple) and len(c.data) >= 6:
            box = np.array([float(x) for x in c.data[:6]]).reshape(2, 3)
    return tm, box


def base_mesh(R, base):
    """Base object -> {cls, prim} for primitives or {cls, verts, faces, mats, edges} for Editable Poly / Mesh."""
    cls = R.cls_name(base) if base is not None else None
    out = dict(cls=cls)
    if cls in ("Box", "Plane"):
        out["prim"] = E.prim_params(base, R)
        return out
    poly = None
    try:
        poly = editable_poly(base)
    except Exception:
        poly = None
    if poly is not None:
        out.update(poly)
        return out
    try:
        v = R.poly_coords(base)
        f = R.poly_faces(base)
    except Exception:
        v, f = None, []
    if v is not None and f:
        out["verts"] = np.asarray(v, float)
        out["faces"] = [list(x[1]) for x in f]
        out["mats"] = [int(x[0]) for x in f]
    return out


MN_DEAD = 2


def editable_poly(base):
    """The MNMesh of an Editable Poly as saved: vertices 0x0100 (flags, p; a dead vertex is its flags only),
    edges 0x010A (flags, v1, v2), faces 0x011A (deg, vtx, flags, optional fields). Dead elements are dropped the
    way MNMesh::CollapseDeadStructs does, keeping the order of the living."""
    poly = base.get_first(0x08FE)
    if poly is None:
        return None
    ch = {c.types: _b(c) for c in poly.children if _b(c) is not None}
    if 0x0100 not in ch or 0x011A not in ch:
        return None
    b = ch[0x0100]
    n = struct.unpack_from("<I", b, 0)[0]
    off, pts, vdead = 4, [], []
    for i in range(n):
        fl = struct.unpack_from("<I", b, off)[0]
        off += 4
        if fl & MN_DEAD:
            pts.append((np.nan, np.nan, np.nan))
            vdead.append(True)
            continue
        pts.append(struct.unpack_from("<3f", b, off))
        off += 12
        vdead.append(False)
    if off != len(b):
        return None
    edges = None
    if 0x010A in ch:
        b = ch[0x010A]
        ne = struct.unpack_from("<I", b, 0)[0]
        off, edges = 4, []
        for i in range(ne):
            fl = struct.unpack_from("<I", b, off)[0]
            off += 4
            if fl & MN_DEAD:
                edges.append(None)
                continue
            edges.append(struct.unpack_from("<2i", b, off))
            off += 8
        if off != len(b):
            edges = None
    b = ch[0x011A]
    nf = struct.unpack_from("<I", b, 0)[0]
    off, faces, mats = 4, [], []
    for i in range(nf):
        deg = struct.unpack_from("<i", b, off)[0]
        off += 4
        vtx = list(struct.unpack_from("<%di" % deg, b, off)) if deg > 0 else []
        off += 4 * max(deg, 0)
        fl = struct.unpack_from("<H", b, off)[0]
        off += 2
        mat = 0
        if fl & 0x01:
            off += 4
        if fl & 0x08:
            mat = struct.unpack_from("<H", b, off)[0]
            off += 2
        if fl & 0x10:
            off += 4
        if fl & 0x20:
            off += 4 * 2 * (deg - 3)
        if deg > 0 and not (fl & MN_DEAD):
            faces.append(vtx)
            mats.append(mat)
    if off != len(b):
        return None
    uv = _map_channels(poly, fdead_list=None)
    alive = [i for i, d in enumerate(vdead) if not d]
    remap = {o: k for k, o in enumerate(alive)}
    verts = np.array([pts[i] for i in alive], float)
    faces = [[remap[x] for x in f] for f in faces]
    if edges is not None:
        edges = [(remap[a], remap[b_]) for e in edges if e is not None for a, b_ in [e]
                 if a in remap and b_ in remap]
    out = dict(verts=verts, faces=faces, mats=mats, edges=edges)
    if uv and len(uv.get("faces", [])) == len(faces):
        out["uv"] = uv
    return out


def _map_channels(poly, fdead_list=None):
    """Map channel 1 (texture UVW) of an Editable Poly: map vertices 0x0128 and map faces 0x012B after the
    channel number 0x0124."""
    ch, cur = {}, None
    for c in poly.children:
        b = _b(c)
        if b is None:
            continue
        if c.types == 0x0124 and len(b) >= 4:
            cur = struct.unpack_from("<i", b, 0)[0]
        elif c.types == 0x0128 and cur is not None:
            n = struct.unpack_from("<I", b, 0)[0]
            if len(b) >= 4 + 12 * n:
                ch.setdefault(cur, {})["verts"] = np.frombuffer(b, "<f4", count=3 * n, offset=4).reshape(-1, 3)
        elif c.types == 0x012B and cur is not None:
            faces, off = [], 0
            while off + 4 <= len(b):
                k = struct.unpack_from("<i", b, off)[0]
                off += 4
                faces.append(list(struct.unpack_from("<%di" % k, b, off)) if k > 0 else [])
                off += 4 * max(k, 0)
            ch.setdefault(cur, {})["faces"] = faces
    return ch.get(1)


def read(R, msh):
    """Derived-object chain of a node -> {base, mods (bottom -> top)}."""
    M = R.M
    chain = []
    cur = msh
    seen = 0
    while cur is not None and M.get_guid(cur) in (0x2032, 0x2033) and seen < 20:
        rr = refs_of(M, cur)
        mods = rr[:-1]
        blocks = [c for c in getattr(cur, "children", []) if c.types == 0x2500]
        level = list(zip(mods, blocks + [None] * (len(mods) - len(blocks))))
        chain = level[::-1] + chain
        cur = rr[-1] if rr else None
        seen += 1
    mods = []
    for mod, blk in chain:
        if mod is None:
            continue
        cls = R.cls_name(mod)
        tm, box = ctx_of(blk)
        rec = dict(cls=cls, ctx_tm=tm, ctx_box=box, ops=None, pb={}, chunks={}, gizmo=None)
        if cls == "Edit Poly" and blk is not None:
            rec["ops"] = E.edit_poly_ops(blk)
            rec["final"] = _final_counts(blk)
        for c in getattr(mod, "children", None) or []:
            b = _b(c)
            if b is not None:
                rec["chunks"][c.types] = b
        for r in refs_of(M, mod):
            if r is None:
                continue
            nm = R.cls_name(r)
            if nm == "ParamBlock2" and not rec["pb"]:
                rec["pb"] = param_block2(R, r)
            elif nm == "Position/Rotation/Scale" and rec["gizmo"] is None:
                rec["gizmo"] = prs(R, r)
                rec["gizmo_read"] = rec["gizmo"] is not None
        mods.append(rec)
    return dict(base=base_mesh(R, cur), mods=mods)


def _final_counts(blk):
    """Sizes of the saved vertex / edge / face selections of an Edit Poly = counts of its output mesh."""
    out = {}
    for c in getattr(blk, "children", None) or []:
        if c.types == 0x2512:
            for d in getattr(c, "children", None) or []:
                key = {0x0200: "v", 0x0210: "e", 0x0220: "f"}.get(d.types)
                if key:
                    out[key] = E._bits(d)[0]
    return out
