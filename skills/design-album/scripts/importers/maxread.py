# -*- coding: utf-8 -*-
"""Low-level .max reader (no 3ds Max needed).

Uses the GPL-2.0+ Blender importer `max_lib/import_max.py` (io_scene_max) as a parsing library with bpy stubbed
out, plus corrected transform controllers. Limits: modifiers are NOT evaluated (an Editable Poly base gives its
own mesh; a Plane/Box with Edit Poly / Extrude modifiers gives only its primitive parameters).
"""
import os
import sys, types, json, struct, re, pickle
import numpy as np
import mathutils

# ---- stub blender modules ------------------------------------------------
bpy = types.ModuleType("bpy")
bpy_extras = types.ModuleType("bpy_extras")
nsu = types.ModuleType("bpy_extras.node_shader_utils")
nsu.PrincipledBSDFWrapper = object
bpy_extras.node_shader_utils = nsu
sys.modules.update({"bpy": bpy, "bpy_extras": bpy_extras, "bpy_extras.node_shader_utils": nsu})
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "max_lib"))
import import_max as M  # noqa: E402

M.print = lambda *a, **k: None  # silence


# ---- memory-friendly chunk reading (memoryview instead of copies) --------
def get_next_chunk(self, data, offset, level, number, conReader, primReader):
    header = 6
    typ, siz = struct.unpack_from("<Hi", data, offset)
    chunksize = siz & M.UNKNOWN_SIZE
    if siz == 0:
        siz, = struct.unpack_from("<q", data, offset + header)
        header += 8
        chunksize = siz & M.MAXFILE_SIZE
    if siz < 0:
        chunk = conReader(typ, chunksize, level, number, primReader)
    else:
        chunk = primReader(typ, chunksize, level, number)
    chunk.set_data(data[offset + header:offset + chunksize])
    return offset + chunksize, chunk


def get_chunks(self, data, level, conReader, primReader):
    chunks = []
    offset = 0
    if level == 0:
        if not isinstance(data, bytes):
            data = bytes(data)
        short, step = M.get_short(data, 0)
        if short == 0x8B1F:
            import zlib
            data = zlib.decompress(data, zlib.MAX_WBITS | 32)
        data = memoryview(data)
    while offset < len(data):
        offset, chunk = self.get_next_chunk(data, offset, level, len(chunks), conReader, primReader)
        chunks.append(chunk)
    return chunks


M.ChunkReader.get_next_chunk = get_next_chunk
M.ChunkReader.get_chunks = get_chunks
_orig_set_string = M.ByteArrayChunk.set_string


def set_string(self, data):
    try:
        self.data = bytes(data).decode("UTF-16LE")
    except Exception:
        self.data = bytes(data)


M.ByteArrayChunk.set_string = set_string


def bset(self, data, fmt, start, end):
    try:
        self.data = struct.unpack(fmt, data[start:end])
    except Exception:
        self.data = data


M.ByteArrayChunk.set = bset


# ---- correct transform controllers -------------------------------------------
def max_quat(q):
    """3ds Max stores quats as (x, y, z, w) with left-handed sense -> conjugate."""
    return mathutils.Quaternion((q[3], q[0], q[1], q[2])).conjugated()


def get_rotation(pos):
    mtx = mathutils.Matrix.Identity(4)
    if pos is None:
        return mtx
    uid = M.get_guid(pos)
    if uid == 0x2012:  # Euler XYZ (angles in radians, applied X then Y then Z)
        rot = M.get_point_3d(pos)
        if len(rot) == 3:
            mtx = mathutils.Euler((rot[0], rot[1], rot[2]), 'XYZ').to_matrix().to_4x4()
    elif uid in (0x442313, 0x2009):  # TCB Rotation / Bezier? (quaternion keys)
        c = pos.get_first(0x2504)
        if c is not None:
            mtx = max_quat(c.data[:4]).to_matrix().to_4x4()
    elif uid == 0x4B4B1003:  # Rotation List -> first sub controller
        r = M.get_references(pos)
        if r:
            return get_rotation(r[0])
    elif uid == M.MATRIX_ROT:
        return get_rotation(M.get_references(pos)[0])
    return mtx


def get_scale(pos):
    mtx = mathutils.Matrix.Identity(4)
    if pos is None:
        return mtx
    uid = M.get_guid(pos)
    vals = None
    if uid in (0x2010, 0x442315):
        c = pos.get_first(0x2501) or pos.get_first(0x2505)
        vals = c.data if c is not None else None
    elif uid == M.MATRIX_SCL:
        vals = M.get_point_3d(pos, 1.0)
    if vals:
        mtx = mathutils.Matrix.Diagonal(vals[:3]).to_4x4()
        if len(vals) >= 7:
            q = max_quat(vals[3:7]).to_matrix().to_4x4()
            mtx = q @ mtx @ q.inverted()
    return mtx


def create_matrix(prc):
    uid = M.get_guid(prc)
    if uid == 0x2005:  # Position/Rotation/Scale
        r = M.get_references(prc)
        T = M.get_position(r[0])
        R = get_rotation(r[1])
        S = get_scale(r[2])
        return T @ R @ S
    return mathutils.Matrix.Identity(4)


M.get_rotation = get_rotation
M.get_scale = get_scale
M.create_matrix = create_matrix


# ---- helpers ---------------------------------------------------------------
def load(path):
    mf = M.ImportMaxFile(path)
    M.read_class_data(mf, path)
    M.read_config(mf, path)
    M.read_directory(mf, path)
    M.read_class_directory(mf, path)
    M.SCENE_LIST = M.read_chunks(mf, "Scene", path, conReader=M.SceneChunk)
    return mf


def cls_name(chunk):
    c = M.get_class(chunk)
    if c is None:
        return "?%04X" % chunk.types
    n = c.get_first(0x2042)
    return n.data if n is not None and isinstance(n.data, str) else "?"


def node_name(node):
    n = node.get_first(M.TYP_NAME)
    return n.data if n is not None and isinstance(n.data, str) else ""


def is_node(chunk):
    return isinstance(chunk, M.SceneChunk) and M.get_guid(chunk) == 0x01 and M.get_super_id(chunk) == 0x01


def local_matrix(node):
    try:
        prs, msh, mat, lyr = M.get_matrix_mesh_material(node)
        return M.create_matrix(prs), msh, mat, lyr
    except Exception:
        return mathutils.Matrix.Identity(4), None, None, None


def offset_matrix(node):
    """Object-offset (pivot) TM stored in the node: chunk 0x096A pos, 0x096B rot quat, 0x096C scale."""
    m = mathutils.Matrix.Identity(4)
    try:
        p = node.get_first(0x096A)
        r = node.get_first(0x096B)
        s = node.get_first(0x096C)
        T = mathutils.Matrix.Identity(4)
        R = mathutils.Matrix.Identity(4)
        S = mathutils.Matrix.Identity(4)
        if p is not None:
            v = struct.unpack_from("<3f", bytes(p.data) if not isinstance(p.data, tuple) else struct.pack("<3f", *p.data[:3]))
            T = mathutils.Matrix.Translation(v)
        if r is not None:
            q = struct.unpack_from("<4f", bytes(r.data) if not isinstance(r.data, tuple) else struct.pack("<4f", *r.data[:4]))
            R = max_quat(q).to_matrix().to_4x4()
        if s is not None:
            sv = struct.unpack_from("<7f", bytes(s.data) if not isinstance(s.data, tuple) else struct.pack("<7f", *s.data[:7]))
            S = mathutils.Matrix.Diagonal(sv[:3]).to_4x4()
            qa = max_quat(sv[3:7]).to_matrix().to_4x4()
            S = qa @ S @ qa.inverted()
        m = T @ R @ S
    except Exception:
        pass
    return m


def world_matrix(node, cache):
    key = id(node)
    if key in cache:
        return cache[key]
    loc, *_ = local_matrix(node)
    parent = M.get_node_parent(node)
    if parent is not None and is_node(parent) and parent is not node:
        w = world_matrix(parent, cache) @ loc
    else:
        w = loc
    cache[key] = w
    return w


def base_object(msh):
    """Follow Derived Object chain to the base object."""
    seen = 0
    while msh is not None and M.get_guid(msh) in (0x2032, 0x2033) and seen < 20:
        refs = M.get_references(msh)
        msh = refs[-1] if refs else None
        seen += 1
    return msh


def modifiers(msh):
    mods = []
    seen = 0
    while msh is not None and M.get_guid(msh) in (0x2032, 0x2033) and seen < 20:
        refs = M.get_references(msh)
        for r in refs[:-1]:
            if r is not None:
                mods.append(cls_name(r))
        msh = refs[-1] if refs else None
        seen += 1
    return mods


def poly_coords(obj):
    """Return Nx3 float32 vertex array for Editable Poly / Editable Mesh base object."""
    g = M.get_guid(obj)
    poly = obj.get_first(0x08FE)
    if poly is None:
        return None
    if g == M.EDIT_POLY:
        for c in poly.children:
            if c.types == 0x0100:
                buf = bytes(c.data) if not isinstance(c.data, tuple) else None
                if buf is None:
                    return None
                n = struct.unpack_from("<I", buf, 0)[0]
                arr = np.frombuffer(buf, dtype=np.uint8, offset=4)
                arr = arr[: (len(arr) // 16) * 16].view(np.dtype([("f", "<u4"), ("p", "<f4", 3)]))
                return arr["p"].astype(np.float64)
    elif g == M.EDIT_MESH:
        vc = poly.get_first(0x0914)
        if vc is None:
            return None
        buf = bytes(vc.data)
        n = struct.unpack_from("<I", buf, 0)[0]
        return np.frombuffer(buf, dtype="<f4", count=n * 3, offset=4).reshape(-1, 3).astype(np.float64)
    return None


def poly_faces(obj):
    """Return list of (matid, [vertex indices]) for Editable Poly / Mesh."""
    g = M.get_guid(obj)
    poly = obj.get_first(0x08FE)
    out = []
    if g == M.EDIT_POLY:
        p4 = p6 = pN = None
        for c in poly.children:
            if c.types == 0x0108:
                p6 = c.data
            elif c.types == 0x011A:
                p4 = M.calc_point_3d(c)
            elif c.types == 0x0310:
                pN = c.data
        if p4 is not None:
            for pt in p4:
                out.append((pt.fH, list(pt.points)))
        elif p6 is not None:
            for f in M.get_poly_6p(bytes(p6)):
                out.append((0, list(f)))
        elif pN is not None:
            for f in M.get_poly_5p(bytes(pN)):
                out.append((0, list(f)))
    elif g == M.EDIT_MESH:
        cc = poly.get_first(0x0912)
        for f in M.get_poly_5p(bytes(cc.data)):
            out.append((0, list(f)))
    return out


def iter_nodes():
    for ch in M.SCENE_LIST[0].children:
        if is_node(ch):
            yield ch


def _chunk_name(ch, depth=0):
    """Material / map name: chunk 0x4001 (directly or nested up to 3 levels)."""
    try:
        n = ch.get_first(0x4001)
        if n is not None and isinstance(n.data, str) and n.data:
            return n.data
    except Exception:
        pass
    if depth < 3:
        for c in getattr(ch, "children", None) or []:
            r = _chunk_name(c, depth + 1)
            if r:
                return r
    return None


def mat_name(mat):
    if mat is None:
        return None
    return (_chunk_name(mat) or cls_name(mat) or "").strip() or None


def mat_names(mat):
    """[material name, sub-material names...] (Multi/Sub-Object), class name of a light material kept as a hint."""
    if mat is None:
        return []
    out = []
    n = mat_name(mat)
    if n:
        out.append(n)
    if "Light" in (cls_name(mat) or ""):
        out.append("LightMtl")
    try:
        refs = M.get_references(mat) or []
    except Exception:
        refs = []
    for r in refs[:40]:
        if r is None:
            continue
        c = cls_name(r) or ""
        if not re.search(r"Mtl|Material|Multi", c):
            continue
        s = _chunk_name(r)
        if s and s not in out:
            out.append(s)
        if "Light" in c and "LightMtl" not in out:
            out.append("LightMtl")
    return out


def layer_name(lyr):
    if lyr is None:
        return None
    try:
        for c in lyr.children:
            if isinstance(c.data, str) and c.data:
                return c.data
    except Exception:
        pass
    return None


def scan(path, out_json):
    load(path)
    cache = {}
    rows = []
    for node in iter_nodes():
        name = node_name(node)
        loc, msh, mat, lyr = local_matrix(node)
        base = base_object(msh) if msh is not None else None
        row = {
            "idx": node.number,
            "name": name,
            "class": cls_name(base) if base is not None else None,
            "mods": modifiers(msh) if msh is not None else [],
            "parent": node_name(M.get_node_parent(node)) if M.get_node_parent(node) is not None and is_node(M.get_node_parent(node)) else None,
            "material": mat_name(mat),
            "layer": layer_name(lyr),
            "node_chunks": sorted({"%04X" % c.types for c in node.children}),
        }
        try:
            W = world_matrix(node, cache) @ offset_matrix(node)
            row["world"] = [list(r) for r in W]
            if base is not None:
                v = poly_coords(base)
                if v is not None and len(v):
                    Wn = np.array(W)
                    vw = v @ Wn[:3, :3].T + Wn[:3, 3]
                    row["nverts"] = int(len(v))
                    row["bbox"] = [vw.min(0).tolist(), vw.max(0).tolist()]
        except Exception as e:
            row["err"] = repr(e)
        rows.append(row)
    json.dump(rows, open(out_json, "w"), ensure_ascii=False, indent=1)
    return rows


def extract(path, names, out_npz):
    load(path)
    cache = {}
    want = set(names)
    data = {}
    for node in iter_nodes():
        name = node_name(node)
        if name not in want:
            continue
        loc, msh, mat, lyr = local_matrix(node)
        base = base_object(msh)
        v = poly_coords(base)
        f = poly_faces(base)
        W = np.array(world_matrix(node, cache) @ offset_matrix(node))
        vw = v @ W[:3, :3].T + W[:3, 3]
        data[name + "#%d" % node.number] = {"v": vw, "faces": f}
    pickle.dump(data, open(out_npz, "wb"))
    return data


