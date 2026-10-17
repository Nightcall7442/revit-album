# -*- coding: utf-8 -*-
"""The result of a 3ds Max modifier stack, rebuilt without 3ds Max (lesson L-105).

`maxstack.read` gives the base object and the modifiers as data; here they are applied the way 3ds Max applies them:
a polygon mesh with the conventions of MNMesh (vertex / edge / face numbering, edge f1 = the face that runs v1 -> v2)
goes through the Edit Poly operation list and the deforming modifiers (FFD, Symmetry ...).

Every step is checked against what 3ds Max itself saved with the operation: the size of the selection of an op is
the number of vertices / edges / faces the mesh had at that moment, a transform stores one offset per vertex, an Edit
Poly stores the selection sizes of its output. A replay that disagrees with any of them stops with status "unknown" -
the album is not built from a guess.
"""
import numpy as np

# selection level of an Edit Poly op: which counter its saved selection size must equal
SEL_V = {10, 12, 16, 22, 26, 33, 39, 44, 49, 59, 63}
SEL_E = {9, 17, 23, 34, 40, 43, 50, 54, 60, 62, 64, 66, 74, 82, 84}
SEL_F = {11, 13, 18, 21, 27, 28, 30, 31, 32, 38, 41, 51, 65, 67, 68, 69, 70, 75, 91, 92}
NEUTRAL = {0, 1, 2, 3, 4, 5, 6, 7, 8, 24, 30, 31, 36, 37, 46, 47, 48, 52, 61, 68, 69, 70, 71, 72, 73, 79, 83, 85, 86,
           87, 88, 89, 90}


class ReplayError(Exception):
    pass


class Mesh:
    """Polygon mesh with MNMesh numbering. faces: vertex loops; edges: [v1, v2, f1, f2] (f2 = -1 on a border)."""

    def __init__(self, verts, faces, mats=None, edges=None):
        self.v = np.asarray(verts, float).reshape(-1, 3).copy()
        self.f = [list(map(int, x)) for x in faces]
        self.mat = list(mats) if mats is not None else [0] * len(self.f)
        self.e = []
        if edges is not None:
            self._edges_from_pairs(edges)
        else:
            self.fill_edges()

    # ---- topology -----------------------------------------------------------------------------------------------
    def fill_edges(self):
        """MNMesh::FillInMesh: edges in the order the faces meet them; f1 runs v1 -> v2."""
        self.e = []
        index = {}
        for fi, loop in enumerate(self.f):
            d = len(loop)
            for j in range(d):
                a, b = loop[j], loop[(j + 1) % d]
                k = index.get((b, a))
                if k is not None and self.e[k][3] < 0:
                    self.e[k][3] = fi
                    del index[(b, a)]
                else:
                    index[(a, b)] = len(self.e)
                    self.e.append([a, b, fi, -1])

    def _edges_from_pairs(self, pairs):
        """Edges saved with an Editable Poly: (v1, v2) in their order; faces attached by direction."""
        self.e = [[int(a), int(b), -1, -1] for a, b in pairs]
        pos = {}
        for k, (a, b, _, _) in enumerate(self.e):
            pos[(a, b)] = k
            pos.setdefault((b, a), k)
        for fi, loop in enumerate(self.f):
            d = len(loop)
            for j in range(d):
                a, b = loop[j], loop[(j + 1) % d]
                k = pos.get((a, b))
                if k is None:
                    raise ReplayError("ребро грани %d не найдено среди сохранённых" % fi)
                ed = self.e[k]
                if ed[0] == a and ed[1] == b and ed[2] < 0:
                    ed[2] = fi
                else:
                    ed[3] = fi

    def counts(self):
        return len(self.v), len(self.e), len(self.f)

    def edge_index(self):
        idx = {}
        for k, (a, b, _, _) in enumerate(self.e):
            idx[(a, b)] = k
            idx[(b, a)] = k
        return idx

    def face_edges(self, fi, idx=None):
        idx = idx or self.edge_index()
        loop = self.f[fi]
        return [idx[(loop[j], loop[(j + 1) % len(loop)])] for j in range(len(loop))]

    def normal(self, fi):
        p = self.v[self.f[fi]]
        n = np.zeros(3)
        for j in range(len(p)):                         # Newell
            a, b = p[j], p[(j + 1) % len(p)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
        L = np.linalg.norm(n)
        return n / L if L > 0 else n

    def collapse(self, vdead, edead, fdead):
        """MNMesh::CollapseDeadStructs: drop dead elements, keep the order of the living."""
        vmap = -np.ones(len(self.v), int)
        alive = [i for i in range(len(self.v)) if i not in vdead]
        vmap[alive] = np.arange(len(alive))
        fmap = {}
        nf, nm = [], []
        for i, loop in enumerate(self.f):
            if i in fdead:
                continue
            fmap[i] = len(nf)
            nf.append([int(vmap[x]) for x in loop])
            nm.append(self.mat[i])
        ne = []
        for k, (a, b, f1, f2) in enumerate(self.e):
            if k in edead:
                continue
            ne.append([int(vmap[a]), int(vmap[b]), fmap.get(f1, -1), fmap.get(f2, -1)])
        self.v = self.v[alive]
        self.f, self.mat, self.e = nf, nm, ne
        for ed in self.e:
            if ed[2] < 0 and ed[3] >= 0:                # the remaining face runs the other way: flip the edge
                ed[0], ed[1], ed[2], ed[3] = ed[1], ed[0], ed[3], -1


# ---- base objects ---------------------------------------------------------------------------------------------------
def from_tris(verts, tris):
    """A primitive's triangle mesh -> MNMesh the way 3ds Max converts it: edges in the order the triangles meet them
    (SetFromTri + FillInMesh), then every pair of triangles (2k, 2k+1) merged across their shared diagonal into one
    quad (MakePolyMesh): the first triangle's loop takes the second one's far vertex, the diagonal is removed."""
    edges, index, diag = [], {}, set()
    for t in tris:
        for j in range(3):
            a, b = t[j], t[(j + 1) % 3]
            if (b, a) in index:
                continue
            if (a, b) not in index:
                index[(a, b)] = len(edges)
                edges.append((a, b))
    faces = []
    for k in range(0, len(tris), 2):
        t0, t1 = tris[k], tris[k + 1]
        shared = [(t0[j], t0[(j + 1) % 3]) for j in range(3) if t0[(j + 1) % 3] in t1 and t0[j] in t1]
        a, b = shared[0]                                  # t0 runs a -> b along the diagonal
        far = [x for x in t1 if x not in (a, b)][0]
        loop = list(t0)
        loop.insert(loop.index(a) + 1, far)
        faces.append(loop)
        diag.add(frozenset((a, b)))
    pairs = [e for e in edges if frozenset(e) not in diag]
    return Mesh(verts, faces, None, pairs)


def plane(prm):
    L, W = prm[0], prm[1]
    ls, ws = int(prm.get(3, 1) or 1), int(prm.get(2, 1) or 1)
    v = [[-W / 2 + W * i / ws, -L / 2 + L * j / ls, 0.0] for j in range(ls + 1) for i in range(ws + 1)]
    tris = []
    for j in range(ls):
        for i in range(ws):
            bl = j * (ws + 1) + i
            br, tl, tr = bl + 1, bl + ws + 1, bl + ws + 2
            tris += [(tl, bl, tr), (br, tr, bl)]
    return from_tris(v, tris)


def box(prm):
    L, W, H = prm[0], prm[1], prm[2]
    if any(int(prm.get(k, 1) or 1) != 1 for k in (3, 4, 5)):
        raise ReplayError("Box с сегментами")
    bot = [[-W / 2, -L / 2, 0], [W / 2, -L / 2, 0], [-W / 2, L / 2, 0], [W / 2, L / 2, 0]]
    v = bot + [[x, y, H] for x, y, _ in bot]
    tris = [(0, 2, 3), (3, 1, 0), (4, 5, 7), (7, 6, 4), (0, 1, 5), (5, 4, 0), (1, 3, 7), (7, 5, 1), (3, 2, 6),
            (6, 7, 3), (2, 0, 4), (4, 6, 2)]
    return from_tris(v, tris)


def from_base(base):
    cls = base.get("cls")
    if cls == "Plane":
        return plane(base["prim"])
    if cls == "Box":
        return box(base["prim"])
    if "verts" in base:
        m = Mesh(base["verts"], base["faces"], base.get("mats"), base.get("edges"))
        m.guessed_edges = not base.get("edges")              # edge order built here, not read from the file
        return m
    raise ReplayError("основа %s не читается" % cls)


# ---- Edit Poly operations -------------------------------------------------------------------------------------------
def _sel(op):
    s = op.get("sel")
    return (s[0], sorted(s[1])) if s else (0, [])


def _pf(op, pid, default=0.0):
    import struct
    raw = (op.get("params") or {}).get(pid)
    return struct.unpack("<f", raw)[0] if raw else default


def _pi(op, pid, default=0):
    import struct
    raw = (op.get("params") or {}).get(pid)
    return struct.unpack("<i", raw)[0] if raw else default


def op_transform(m, op):
    off = op.get("offsets")
    if off is None:
        return
    if len(off) != len(m.v):
        raise ReplayError("перемещение: вершин %d, в сцене %d" % (len(m.v), len(off)))
    lo = getattr(m, "uncertain_from", None)
    moved = np.where(np.abs(off).max(1) > 1e-9)[0]
    if lo is not None and (moved >= lo).any():
        _transform_inferred(m, off, lo)
        return
    m.v = m.v + off


def _transform_inferred(m, off, lo):
    """A transform right after a stitch that 3ds Max renumbers: every moved vertex has the same offset, so the
    moved vertices of the renumbered part are found as the only set of that size that keeps every rectangle a
    rectangle and every planar face planar. No such set, or more than one - unknown."""
    import itertools
    moved = np.where(np.abs(off).max(1) > 1e-9)[0]
    t = off[moved[0]]
    if not np.allclose(off[moved], t, atol=1e-6):
        raise ReplayError("перемещение после сшивки: разные смещения, нумерация 3ds Max неизвестна")
    fixed = [i for i in moved if i < lo]
    k = int((moved >= lo).sum())
    pool = list(range(lo, len(m.v)))
    base_ok = _shape_signature(m)
    cands = []
    if len(pool) <= 24:
        cands = itertools.combinations(pool, k)
    else:                                                    # bands of levels along the move and the axes
        P = m.v[pool]
        seen = set()
        dirs = [t / np.linalg.norm(t), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])]
        for dvec in dirs:
            proj = np.round(P @ dvec, 6)
            levels = np.unique(proj)
            groups = [np.where(proj == lv)[0] for lv in levels]
            sizes = [len(g) for g in groups]
            for i in range(len(groups)):
                tot = 0
                for j in range(i, len(groups)):
                    tot += sizes[j]
                    if tot == k:
                        S = tuple(sorted(pool[x] for g in groups[i:j + 1] for x in g))
                        if S not in seen:
                            seen.add(S)
                            cands.append(S)
                    if tot >= k:
                        break
    good = []
    for S in cands:
        v = m.v.copy()
        idx = list(fixed) + list(S)
        v[idx] += t
        if _shape_ok(m, v, base_ok):
            good.append(S)
            if len(good) > 1:
                break
    if len(good) != 1:
        raise ReplayError("перемещение после сшивки: вариантов %d, нужен один" % len(good))
    m.v[list(fixed) + list(good[0])] += t
    m.inferred = True


def _shape_signature(m):
    sig = []
    for loop in m.f:
        P = m.v[loop]
        sig.append((_max_cos(P) < 1e-4, _planar_dev(P) < 1e-6, _loop_normal(P)))
    return sig


def _shape_ok(m, v, sig):
    """The moved mesh keeps every rectangle a rectangle, every planar face planar and no face turns over."""
    for (rect, planar, n0), loop in zip(sig, m.f):
        P = v[loop]
        if rect and _max_cos(P) > 1e-4:
            return False
        if planar and _planar_dev(P) > 1e-6:
            return False
        n1 = _loop_normal(P)
        if np.linalg.norm(n1) < 1e-12 or float(n0 @ n1) <= 0:
            return False
    return True


def _max_cos(P):
    mx = 0.0
    for j in range(len(P)):
        a, b, c = P[j - 1], P[j], P[(j + 1) % len(P)]
        u, w = a - b, c - b
        nu, nw = np.linalg.norm(u), np.linalg.norm(w)
        if nu < 1e-12 or nw < 1e-12:
            return 9.0
        mx = max(mx, abs(float(u @ w)) / nu / nw)
    return mx


def _planar_dev(P):
    if len(P) < 4:
        return 0.0
    c = P.mean(0)
    s = np.linalg.svd(P - c, compute_uv=False)
    return float(s[-1] / max(s[0], 1e-12))


def op_delete_faces(m, faces, iso=True):
    fdead = set(faces)
    if not fdead:
        return
    edead = set()
    for k, (a, b, f1, f2) in enumerate(m.e):
        d1, d2 = f1 in fdead or f1 < 0, f2 in fdead or f2 < 0
        if d1 and d2:
            edead.add(k)
    vdead = set()
    if iso:
        used = set()
        for i, loop in enumerate(m.f):
            if i not in fdead:
                used.update(loop)
        vdead = set(range(len(m.v))) - used
    m.collapse(vdead, edead, fdead)


def op_delete_verts(m, verts, iso=True):
    vs = set(verts)
    faces = [i for i, loop in enumerate(m.f) if vs & set(loop)]
    fdead = set(faces)
    edead = set(k for k, (a, b, f1, f2) in enumerate(m.e) if a in vs or b in vs or
                ((f1 in fdead or f1 < 0) and (f2 in fdead or f2 < 0)))
    vdead = set(vs)
    if iso:
        used = set()
        for i, loop in enumerate(m.f):
            if i not in fdead:
                used.update(loop)
        vdead |= set(range(len(m.v))) - used
    m.collapse(vdead, edead, fdead)


def op_clone_faces(m, faces):
    """Clone selected faces to a new element: new vertices as they are met going over the faces in order (each loop
    as stored - checked against 3ds Max's export, Sherov pCube1, L-111), new faces in face order."""
    fs = sorted(faces)
    vs = []
    vmap = {}
    for fi in fs:
        for x in m.f[fi]:
            if x not in vmap:
                vmap[x] = len(m.v) + len(vs)
                vs.append(x)
    m.v = np.vstack([m.v, m.v[vs]]) if vs else m.v
    first = len(m.f)
    for fi in fs:
        m.f.append([vmap[x] for x in m.f[fi]])
        m.mat.append(m.mat[fi])
    _append_face_edges(m, range(first, len(m.f)))


def _append_face_edges(m, faces):
    idx = {}
    for k, (a, b, f1, f2) in enumerate(m.e):
        if f2 < 0:
            idx[(b, a)] = k                       # an open edge can take a face running b -> a
    for fi in faces:
        loop = m.f[fi]
        d = len(loop)
        for j in range(d):
            a, b = loop[j], loop[(j + 1) % d]
            k = idx.pop((a, b), None)
            if k is not None and m.e[k][3] < 0:
                m.e[k][3] = fi
            else:
                idx[(b, a)] = len(m.e)
                m.e.append([a, b, fi, -1])


OPS = {}


def replay_edit_poly(m, ops, check=True, log=None):
    """Apply an Edit Poly op list to mesh m (in place). Raises ReplayError on an op it cannot do exactly or on
    a count that disagrees with what 3ds Max saved."""
    for k, op in enumerate(ops):
        o = op["op"]
        n, sel = _sel(op)
        whole = (o in SEL_E and len(sel) == len(m.e)) or (o in SEL_F and len(sel) == len(m.f))
        if getattr(m, "uncertain_topo", False) and (o in SEL_E or o in SEL_F) and o not in (70,) and sel and not whole:
            raise ReplayError("op %d после сшивки: нумерация граней/рёбер 3ds Max неизвестна" % o)
        if n == 0:
            pass
        elif check and o in SEL_V and n != len(m.v):
            raise ReplayError("op %d (%d): вершин %d, сохранено %d" % (k, o, len(m.v), n))
        elif check and o in SEL_E and n != len(m.e):
            raise ReplayError("op %d (%d): рёбер %d, сохранено %d" % (k, o, len(m.e), n))
        elif check and o in SEL_F and n != len(m.f) and o != 92:
            raise ReplayError("op %d (%d): граней %d, сохранено %d" % (k, o, len(m.f), n))
        if o == 53:
            op_transform(m, op)
        elif o == 70:
            mid = _pi(op, 58)
            for fi in sel:
                m.mat[fi] = mid
        elif o in NEUTRAL:
            continue
        elif o == 11:
            op_delete_faces(m, sel, _pi(op, 26, 1) == 1)
        elif o == 10:
            op_delete_verts(m, sel, _pi(op, 26, 1) == 1)
        elif o == 13:
            continue                                  # detach to another object: this mesh keeps the faces
        elif o == 65:
            op_clone_faces(m, sel)
        elif o in OPS:
            OPS[o](m, op, sel)
        else:
            raise ReplayError("операция Edit Poly %d не повторяется" % o)
        if log is not None:
            log.append((k, o, m.counts()))
    return m


# ---- extrude ---------------------------------------------------------------------------------------------------------
def _clusters(m, faces):
    fs = set(faces)
    idx = m.edge_index()
    adj = {f: set() for f in fs}
    for (a, b, f1, f2) in m.e:
        if f1 in fs and f2 in fs:
            adj[f1].add(f2)
            adj[f2].add(f1)
    out, seen = [], set()
    for f in sorted(fs):
        if f in seen:
            continue
        comp, stack = [], [f]
        seen.add(f)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        out.append(sorted(comp))
    return out


def extrude_region(m, cluster):
    """MNMesh extrusion of one face cluster with zero height. Returns (clone map {orig: new}, side faces)."""
    cs = set(cluster)
    idx = m.edge_index()
    bverts, bedges = [], []
    for fi in cluster:
        loop = m.f[fi]
        d = len(loop)
        for j in range(d):
            a, b = loop[j], loop[(j + 1) % d]
            k = idx[(a, b)]
            ed = m.e[k]
            other = ed[3] if ed[2] == fi else ed[2]
            if other in cs:
                continue
            bedges.append((fi, a, b, k))
            for x in (a, b):
                if x not in bverts:
                    bverts.append(x)
    vmap = {}
    for x in bverts:
        vmap[x] = len(m.v) + len(vmap)
    m.v = np.vstack([m.v, m.v[bverts]])
    for fi in cluster:
        m.f[fi] = [vmap.get(x, x) for x in m.f[fi]]
    # inner edges of the cluster follow their faces' new vertices
    for ed in m.e:
        if ed[2] in cs and (ed[3] in cs):
            ed[0], ed[1] = vmap.get(ed[0], ed[0]), vmap.get(ed[1], ed[1])
    top = {}
    for fi, a, b, k in bedges:                               # the cluster's border, cloned
        top[(a, b)] = len(m.e)
        m.e.append([vmap[a], vmap[b], fi, -1])
    vert = {}
    for x in bverts:                                         # one edge orig -> clone per border vertex
        vert[x] = len(m.e)
        m.e.append([x, vmap[x], -1, -1])
    side = []
    for fi, a, b, k in bedges:
        sf = len(m.f)
        m.f.append([a, b, vmap[b], vmap[a]])
        m.mat.append(m.mat[fi])
        side.append(sf)
        ed = m.e[k]
        if ed[2] == fi:
            ed[2] = sf
        else:
            ed[3] = sf
        m.e[top[(a, b)]][3] = sf
        vb = m.e[vert[b]]                                    # side face runs b -> b'
        if vb[2] < 0:
            vb[2] = sf
        else:
            vb[3] = sf
        va = m.e[vert[a]]                                    # and a' -> a
        if va[3] < 0 and va[2] >= 0:
            va[3] = sf
        elif va[2] < 0:
            va[2], va[3] = -1, sf
    for ed in m.e:                                           # keep f1 running v1 -> v2
        if ed[2] < 0 and ed[3] >= 0:
            ed[0], ed[1], ed[2], ed[3] = ed[1], ed[0], ed[3], -1
    return vmap, side


def _cluster_normal(m, cluster):
    n = np.zeros(3)
    for fi in cluster:
        p = m.v[m.f[fi]]
        for j in range(len(p)):
            a, b = p[j], p[(j + 1) % len(p)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
    L = np.linalg.norm(n)
    return n / L if L > 0 else n


def op_extrude(m, op, sel):
    h = _pf(op, 37)
    typ = _pi(op, 36)
    clusters = [[f] for f in sorted(sel)] if typ == 2 else _clusters(m, sel)
    if typ == 1 and any(len(c) > 1 for c in clusters):
        raise ReplayError("выдавливание по локальным нормалям")
    for cl in clusters:
        nrm = _cluster_normal(m, cl)
        vmap, side = extrude_region(m, cl)
        moved = sorted(set(x for fi in cl for x in m.f[fi]))
        m.v[moved] += h * nrm


OPS[41] = lambda m, op, sel: op_extrude(m, op, sel)


# ---- slice -------------------------------------------------------------------------------------------------------
def _split_edge(m, k, pos):
    """Put a new vertex on edge k; the edge keeps v1 -> new, a new edge new -> v2 is appended."""
    a, b, f1, f2 = m.e[k]
    s = len(m.v)
    m.v = np.vstack([m.v, pos])
    m.e[k] = [a, s, f1, f2]
    m.e.append([s, b, f1, f2])
    for fi in (f1, f2):
        if fi < 0:
            continue
        loop = m.f[fi]
        d = len(loop)
        for j in range(d):
            x, y = loop[j], loop[(j + 1) % d]
            if (x, y) in ((a, b), (b, a)):
                loop.insert(j + 1, s)
                break
    return s


def _split_face(m, fi, s1, s2):
    """Cut face fi between its vertices s1, s2: the face keeps the part with its first vertex, the other part is
    appended; the new edge is appended."""
    loop = m.f[fi]
    i, j = loop.index(s1), loop.index(s2)
    if i > j:
        i, j = j, i
        s1, s2 = s2, s1
    A = loop[:i + 1] + loop[j:]
    B = loop[i:j + 1]
    nb = len(m.f)
    m.f[fi] = A
    m.f.append(B)
    m.mat.append(m.mat[fi])
    bset = set()
    d = len(B)
    for t in range(d - 1):
        bset.add((B[t], B[t + 1]))
    for ed in m.e:
        if (ed[0], ed[1]) in bset and ed[2] == fi:
            ed[2] = nb
        elif (ed[1], ed[0]) in bset and ed[3] == fi:
            ed[3] = nb
    m.e.append([s1, s2, fi, nb])                             # A runs s1 -> s2
    return nb


def op_slice(m, op, sel):
    M1, M2 = op["mats"].get(0x0420), op["mats"].get(0x0430)
    if M1 is None or M2 is None:
        raise ReplayError("плоскость разреза не прочитана")
    T1, T2 = np.eye(4), np.eye(4)
    T1[:3, :3], T1[3, :3] = M1[:3], M1[3]
    T2[:3, :3], T2[3, :3] = M2[:3], M2[3]
    T = T1 @ T2                                              # row vectors: p * M420 * M430
    nrm = T[2, :3] / np.linalg.norm(T[2, :3])
    org = T[3, :3]
    fs = set(sel)
    dist = (m.v - org) @ nrm
    eps = 1e-5
    cut_on = {}
    for k in range(len(m.e)):
        a, b, f1, f2 = m.e[k]
        if f1 not in fs and f2 not in fs:
            continue
        da, db = dist[a], dist[b]
        if (da > eps and db < -eps) or (da < -eps and db > eps):
            t = da / (da - db)
            s = _split_edge(m, k, m.v[a] + t * (m.v[b] - m.v[a]))
            dist = np.append(dist, 0.0)
    for fi in sorted(fs):
        on = [x for x in m.f[fi] if abs(dist[x]) <= eps]
        if len(on) != 2:
            if len(on) > 2:
                raise ReplayError("разрез: грань %d касается плоскости в %d точках" % (fi, len(on)))
            continue
        loop = m.f[fi]
        i, j = loop.index(on[0]), loop.index(on[1])
        if abs(i - j) in (1, len(loop) - 1):                 # the plane runs along an edge
            continue
        _split_face(m, fi, on[0], on[1])


OPS[21] = lambda m, op, sel: op_slice(m, op, sel)


# ---- connect edges --------------------------------------------------------------------------------------------------
def op_connect(m, op, sel):
    segs = max(1, _pi(op, 31, 1))
    pinch, slide = _pf(op, 91), _pf(op, 92)
    if abs(pinch) > 1e-9 or abs(slide) > 1e-9:
        raise ReplayError("соединение рёбер со сдвигом / сжатием")
    news = {}
    for k in sorted(sel):
        a, b = m.e[k][0], m.e[k][1]
        pa, pb = m.v[a].copy(), m.v[b].copy()
        chain = []
        cur = k
        for i in range(segs):
            t = (i + 1) / (segs + 1)
            s = _split_edge(m, cur, pa + t * (pb - pa))
            chain.append(s)
            cur = len(m.e) - 1                               # continue on the piece s -> b
        news[k] = (a, b, chain)
    for fi in range(len(m.f)):
        loop = m.f[fi]
        hits = [news[k] for k in news if _face_has_pair(loop, news[k])]
        if len(hits) < 2:
            continue
        if len(hits) > 2:
            raise ReplayError("соединение: в грани больше двух выбранных рёбер")
        if any(x in (hits[1][0], hits[1][1]) for x in (hits[0][0], hits[0][1])):
            raise ReplayError("соединение: выбранные рёбра грани смежные - нумерация не та")
        (a1, b1, c1), (a2, b2, c2) = hits
        # pair the segment vertices so that the connections do not cross
        o1 = _order_in_loop(loop, a1, b1, c1)
        o2 = _order_in_loop(loop, a2, b2, c2)
        pairs = list(zip(o1, reversed(o2)))
        cur = fi
        for s1, s2 in pairs:
            nf = _split_face_containing(m, fi, s1, s2)
    return m


def _face_has_pair(loop, rec):
    a, b, chain = rec
    return chain[0] in loop


def _order_in_loop(loop, a, b, chain):
    """The new vertices of one edge in the order the face loop meets them."""
    i0 = loop.index(chain[0])
    i1 = loop.index(chain[-1])
    pos = sorted(chain, key=lambda x: loop.index(x))
    return pos


def _split_face_containing(m, fi, s1, s2):
    for f in [fi] + list(range(len(m.f))):
        if s1 in m.f[f] and s2 in m.f[f]:
            return _split_face(m, f, s1, s2)
    raise ReplayError("соединение: нет общей грани")


OPS[43] = lambda m, op, sel: op_connect(m, op, sel)


# ---- smart extrude (3ds Max 2021+: Shift-drag faces) ---------------------------------------------------------------
def op_smart_start(m, op, sel):
    clusters = _clusters(m, sel)
    m.smart = []
    for cl in clusters:
        vmap, side = extrude_region(m, cl)
        m.smart.append(dict(cluster=cl, vmap=vmap, side=side, normal=_cluster_normal(m, cl)))


OPS[91] = op_smart_start


# ---- deforming modifiers -------------------------------------------------------------------------------------------
def _bern(n, u):
    """Bernstein basis of degree n-1 at u (array) -> (len(u), n)."""
    from math import comb
    u = np.asarray(u, float)
    return np.stack([comb(n - 1, i) * u ** i * (1 - u) ** (n - 1 - i) for i in range(n)], axis=1)


def _ffd_points(mod, n):
    raw = mod["chunks"].get(0x0200)
    if raw is None or len(raw) < 12 * n ** 3:
        raise ReplayError("FFD: точки решётки не прочитаны")
    pts = np.frombuffer(raw, "<f4", count=3 * n ** 3).reshape(n, n, n, 3).astype(float)
    off = mod["chunks"].get(0x0400)
    if off is not None and len(off) >= 12 * n ** 3:
        pts = pts + np.frombuffer(off, "<f4", count=3 * n ** 3).reshape(n, n, n, 3)
    return pts


def mod_ffd(m, mod, n):
    """FFD NxNxN: lattice over the mod context box (moved by the lattice gizmo), Bernstein-weighted control points;
    only the vertices inside the lattice volume move (3ds Max default "Only In Volume")."""
    box = mod.get("ctx_box")
    if box is None:
        raise ReplayError("FFD: нет коробки контекста")
    pts = _ffd_points(mod, n)
    C = mod["ctx_tm"]
    G_ = mod.get("gizmo")
    if G_ is None:
        if mod.get("gizmo_read") is False:
            raise ReplayError("FFD: решётка повернута контроллером, который не читается")
        G_ = np.eye(4)
    L = C.copy()
    L = np.linalg.inv(G_) @ L                                # object -> lattice gizmo space
    lo, hi = box[0], box[1]
    size = np.where(np.abs(hi - lo) < 1e-12, 1.0, hi - lo)
    P = (L[:3, :3] @ m.v.T).T + L[:3, 3]
    u = (P - lo) / size
    deform_all = int(mod["pb"].get(0, 0) or 0) == 1 and False
    eps = 1e-3
    inside = np.all((u >= -eps) & (u <= 1 + eps), axis=1) | deform_all
    if not inside.any():
        return
    ui = u[inside]
    Bx, By, Bz = _bern(n, ui[:, 0]), _bern(n, ui[:, 1]), _bern(n, ui[:, 2])
    q = np.einsum("pi,pj,pk,ijkc->pc", Bx, By, Bz, pts)
    Pn = P.copy()
    Pn[inside] = q * size + lo
    Li = np.linalg.inv(L)
    m.v = (Li[:3, :3] @ Pn.T).T + Li[:3, 3]


def mod_symmetry(m, mod, keep_negative=False):
    """Symmetry (planar, one axis): slice along the mirror, keep one half, append its mirror, weld the seam."""
    pb = mod["pb"]
    axes = [a for a, pid in enumerate((6, 7, 8)) if int(pb.get(pid, 0) or 0)]
    if int(pb.get(0, 0) or 0) != 0:
        raise ReplayError("Symmetry: радиальная")
    G_ = mod.get("gizmo")
    if G_ is None:
        raise ReplayError("Symmetry: зеркало не прочитано")
    C = mod["ctx_tm"]
    T = np.linalg.inv(G_) @ C                                # object -> mirror space
    Ti = np.linalg.inv(T)
    thr = float(pb.get(3, 0.01) or 0.01)
    slice_on, weld_on = int(pb.get(1, 1) or 0), int(pb.get(2, 1) or 0)
    for a in axes:
        flip = int(pb.get(9 + a, 0) or 0)
        q = (T[:3, :3] @ m.v.T).T + T[:3, 3]
        sgn = -1.0 if (keep_negative != bool(flip)) else 1.0  # side that stays
        if slice_on:
            _slice_all(m, q, a, sgn)
            q = (T[:3, :3] @ m.v.T).T + T[:3, 3]
        _mirror_append(m, q, a, T, Ti, thr if weld_on else None)


def _slice_all(m, q, a, sgn):
    """Cut every face by the plane q[a] = 0 and delete the faces on the far side (sgn * q[a] < 0)."""
    eps = 1e-5
    dist = sgn * q[:, a]
    for k in range(len(m.e)):
        x, y = m.e[k][0], m.e[k][1]
        dx, dy = dist[x], dist[y]
        if (dx > eps and dy < -eps) or (dx < -eps and dy > eps):
            t = dx / (dx - dy)
            _split_edge(m, k, m.v[x] + t * (m.v[y] - m.v[x]))
            dist = np.append(dist, 0.0)
    for fi in range(len(m.f)):
        loop = m.f[fi]
        on = [x for x in loop if abs(dist[x]) <= eps]
        pos = [x for x in loop if dist[x] > eps]
        neg = [x for x in loop if dist[x] < -eps]
        if pos and neg and len(on) == 2:
            i, j = loop.index(on[0]), loop.index(on[1])
            if abs(i - j) not in (1, len(loop) - 1):
                _split_face(m, fi, on[0], on[1])
    dist = dist[:len(m.v)]
    dead = set()
    for fi, loop in enumerate(m.f):
        if any(dist[x] < -eps for x in loop):
            dead.add(fi)
    op_delete_faces(m, dead, True)


def _mirror_append(m, q, a, T, Ti, thr):
    nv = len(m.v)
    qm = q.copy()
    qm[:, a] = -qm[:, a]
    pm = (Ti[:3, :3] @ qm.T).T + Ti[:3, 3]
    seam = set(np.where(np.abs(q[:, a]) <= (thr if thr is not None else -1))[0]) if thr is not None else set()
    # 3ds Max numbers the mirrored vertices as it meets them going over the faces in order (each face's loop as
    # stored), and each mirrored face keeps its first vertex and runs the other way: [a b c d] -> [a' d' c' b'].
    # Checked vertex by vertex against 3ds Max's export (Sherov pCube9, 4544 vertices; L-111).
    vmap = {i: i for i in seam}
    order = []
    for loop in m.f:
        for x in loop:
            if x not in vmap:
                vmap[x] = nv + len(order)
                order.append(x)
    for i in range(nv):                                       # vertices of no face: after the others
        if i not in vmap:
            vmap[i] = nv + len(order)
            order.append(i)
    if order:
        m.v = np.vstack([m.v, pm[np.array(order)]])
    nf = len(m.f)
    for fi in range(nf):
        loop = [vmap[x] for x in m.f[fi]]
        m.f.append([loop[0]] + loop[1:][::-1])
        m.mat.append(m.mat[fi])
    for i in seam:
        m.v[i, :] = (Ti[:3, :3] @ np.where(np.arange(3) == a, 0.0, q[i]) + Ti[:3, 3])
    _append_face_edges(m, range(nf, len(m.f)))


MAX_FACES = 400000                                           # memory guard of the importer (Railway: one process)

NEUTRAL_MODS = {"UVW Map", "UVW Mapping", "Unwrap UVW", "UVW Xform", "UVW Mapping Add", "UVW Mapping Clear", "Material",
                "MaterialByElement", "Smooth", "Normal", "Edit Normals", "Mesh Select", "Poly Select", "Vol. Select",
                "CoronaDisplacementMod", "VRayDisplacementMod"}


def evaluate(stack, upto=None):
    """Rebuild the mesh of a node: stack = maxstack.read(...). Returns (Mesh, log). Raises ReplayError."""
    m = from_base(stack["base"])
    log = []
    mods = stack["mods"] if upto is None else stack["mods"][:upto]
    for i, mod in enumerate(mods):
        c = mod["cls"]
        if c in NEUTRAL_MODS:
            continue
        had = len(m.v) > 0
        if c == "Edit Poly":
            if getattr(m, "fg_outline", False):
                geo = [op for op in (mod["ops"] or []) if op["op"] not in NEUTRAL and op["op"] != 70 and not
                       (op["op"] == 53 and (op.get("offsets") is None or not np.any(np.abs(op["offsets"]) > 1e-9)))]
                if geo:
                    raise ReplayError("Edit Poly правит плитки FloorGenerator по номерам")
                log.append((c, m.counts()))
                continue
            replay_edit_poly(m, mod["ops"] or [])
            fin = mod.get("final") or {}
            if fin and fin.get("v") and (fin.get("v"), fin.get("e"), fin.get("f")) != m.counts():
                raise ReplayError("Edit Poly #%d: итог %s, в сцене %s" % (i, m.counts(), (fin.get("v"), fin.get("e"), fin.get("f"))))
        elif c in ("FFD 2x2x2", "FFD 3x3x3", "FFD 4x4x4"):
            mod_ffd(m, mod, int(c[4]))
        elif c == "Symmetry":
            mod_symmetry(m, mod)
        elif c == "TurboSmooth":
            mod_turbosmooth(m, mod)
        elif c == "Chamfer":
            mod_chamfer(m, mod)
        elif c == "FloorGenerator":
            mod_floorgen(m, mod)
        else:
            raise ReplayError("модификатор %s не вычисляется" % c)
        log.append((c, m.counts()))
        if had and not len(m.v) and not (c == "Edit Poly" and _deletes_all(mod)) and not _next_ep_empty(mods[i + 1:]):
            # nothing left: true only when the scene says so - an Edit Poly deleted the whole selection, or the next
            # Edit Poly saved a face selection of 0 faces (its input was empty); else it is our reading of a gizmo
            raise ReplayError("%s: геометрии не осталось - не подтверждено сценой" % c)
    return m, log


def _deletes_all(mod):
    for op in mod.get("ops") or []:
        n, sel = _sel(op)
        if op["op"] in (10, 11) and n and len(sel) == n:
            return True
    return False


def _next_ep_empty(rest):
    """The next Edit Poly up the stack saved the size of its face selection as 0: it got no faces."""
    for mod in rest:
        if mod["cls"] == "Edit Poly":
            for op in mod.get("ops") or []:
                if op["op"] in SEL_F and op.get("sel") is not None:
                    return op["sel"][0] == 0 and not (mod.get("final") or {}).get("f")
            return False                       # (a modifier between makes nothing out of nothing)
    return False


def _seg_hits_vertex(m, o, c, skip, eps=1e-3):
    """Vertices (not in skip) lying strictly inside segment o -> c."""
    p, q = m.v[o], m.v[c]
    d = q - p
    L2 = float(d @ d)
    if L2 < 1e-18:
        return []
    t = ((m.v - p) @ d) / L2
    proj = p + np.outer(t, d)
    dist = np.linalg.norm(m.v - proj, axis=1)
    cand = np.where((dist < eps) & (t > 1e-6) & (t < 1 - 1e-6))[0]
    return [int(i) for i in cand if int(i) not in skip]


def _seg_crosses_faces(m, o, c, skip_faces):
    """Faces (not skipped) whose plane the segment o -> c crosses inside the face polygon."""
    p, q = m.v[o], m.v[c]
    out = []
    for fi, loop in enumerate(m.f):
        if fi in skip_faces or o in loop:
            continue
        n = m.normal(fi)
        if not n.any():
            continue
        a = m.v[loop[0]]
        dp, dq = (p - a) @ n, (q - a) @ n
        if dp * dq >= 0:
            continue
        x = p + (q - p) * (dp / (dp - dq))
        P = m.v[loop]
        # point in polygon (projected to the dominant plane)
        ax = int(np.argmax(np.abs(n)))
        k = [i for i in range(3) if i != ax]
        inside = False
        for j in range(len(P)):
            u, w = P[j][k], P[(j + 1) % len(P)][k]
            if (u[1] > x[k][1]) != (w[1] > x[k][1]):
                xi = u[0] + (x[k][1] - u[1]) * (w[0] - u[0]) / (w[1] - u[1])
                if xi > x[k][0]:
                    inside = not inside
        if inside:
            out.append(fi)
    return out


def op_smart_finalize(m, op, sel):
    recs = getattr(m, "smart", None) or []
    m.smart = []
    for rec in recs:
        cl, vmap, side = rec["cluster"], rec["vmap"], rec["side"]
        skipf = set(cl) | set(side)
        skipv = set(vmap) | set(vmap.values())
        hits = {}
        crossing = False
        for o, c in vmap.items():
            w = _seg_hits_vertex(m, o, c, skipv)
            if w:
                hits[c] = w
            if _seg_crosses_faces(m, o, c, skipf):
                crossing = True
        if not hits and not crossing:
            if _stitch_coplanar(m, rec):                     # side faces lying on the walls: rebuilt
                m.uncertain_from = min(vmap)
                m.uncertain_topo = True
            continue                                         # outward / pocket: a plain extrusion
        if len(hits) != len(vmap) or any(len(w) != 1 for w in hits.values()):
            raise ReplayError("умное выдавливание: частичное пересечение не повторяется")
        target = {c: w[0] for c, w in hits.items()}
        tset = set(target.values())
        opp = [fi for fi, loop in enumerate(m.f) if fi not in skipf and set(loop) == tset]
        if len(opp) != len(cl):
            raise ReplayError("умное выдавливание: противоположная грань не совпадает с выдавленной")
        # weld the far end of the tube to the opposite face, drop the cap and the opposite face
        dead_f = set(cl) | set(opp)
        for fi in side:
            m.f[fi] = [target.get(x, x) for x in m.f[fi]]
        clones = set(vmap.values())
        for ed in m.e:
            ed[0], ed[1] = target.get(ed[0], ed[0]), target.get(ed[1], ed[1])
        dead_e = set()
        seen = {}
        for k, ed in enumerate(m.e):
            key = frozenset(ed[:2])
            if ed[2] in dead_f:
                ed[2] = -1
            if ed[3] in dead_f:
                ed[3] = -1
            if key in seen:                                  # cap edge now doubles an opposite-face edge
                j = seen[key]
                keep, drop = (j, k)
                for f in (ed[2], ed[3]):
                    if f >= 0:
                        if m.e[keep][2] < 0:
                            m.e[keep][2] = f
                        elif m.e[keep][3] < 0:
                            m.e[keep][3] = f
                dead_e.add(drop)
            else:
                seen[key] = k
        for k, ed in enumerate(m.e):
            if ed[2] < 0 and ed[3] < 0:
                dead_e.add(k)
        m.collapse(clones, dead_e, dead_f)
        _fix_edge_dirs(m)
        lo = min(min(tset), min(vmap))
        m.uncertain_from = lo                                # 3ds Max renumbers the stitched part
        m.uncertain_topo = True


def _fix_edge_dirs(m):
    """f1 must run v1 -> v2: swap faces / ends where the stored order disagrees with the loops."""
    runs = {}
    for fi, loop in enumerate(m.f):
        d = len(loop)
        for j in range(d):
            runs[(loop[j], loop[(j + 1) % d])] = fi
    for ed in m.e:
        a, b = ed[0], ed[1]
        fab, fba = runs.get((a, b), -1), runs.get((b, a), -1)
        if fab >= 0:
            ed[2], ed[3] = fab, fba
        else:
            ed[0], ed[1], ed[2], ed[3] = b, a, fba, -1


def _plane_basis(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _stitch_coplanar(m, rec):
    """Smart extrude, finalize: a side face that lies in the plane of the face across its base edge is cut out of
    that face (3ds Max "rebuilds and stitches" coplanar faces). Returns True when anything changed."""
    from shapely.geometry import Polygon
    side = rec["side"]
    idx = m.edge_index()
    changed = False
    dead = set()
    for S in side:
        a, b = m.f[S][0], m.f[S][1]
        k = idx.get((a, b))
        if k is None:
            continue
        W = m.e[k][2] if m.e[k][3] == S else m.e[k][3]
        if W < 0 or W in dead or W in side:
            continue
        nS, nW = m.normal(S), m.normal(W)
        if abs(abs(float(nS @ nW)) - 1) > 1e-6:
            continue
        if abs(float((m.v[m.f[S][0]] - m.v[m.f[W][0]]) @ nW)) > 1e-4:
            continue
        o = m.v[m.f[W][0]]
        u, w = _plane_basis(nW)
        to2 = lambda P: np.c_[(P - o) @ u, (P - o) @ w]
        PW = Polygon(to2(m.v[m.f[W]]))
        PS = Polygon(to2(m.v[m.f[S]]))
        if not PW.is_valid or not PS.is_valid or PW.intersection(PS).area < 1e-9:
            continue
        R = PW.difference(PS)
        if R.geom_type != "Polygon" or R.area < 1e-9:
            raise ReplayError("умное выдавливание: сшивка дала не одну грань")
        pts = np.array(R.exterior.coords)[:-1]
        P3 = o + np.outer(pts[:, 0], u) + np.outer(pts[:, 1], w)
        loop = []
        for p in P3:
            dd = np.linalg.norm(m.v - p, axis=1)
            j = int(np.argmin(dd))
            if dd[j] > 1e-4:
                raise ReplayError("умное выдавливание: сшивка дала новую вершину")
            loop.append(j)
        # keep the winding of W
        if float(m.normal(W) @ _loop_normal(m.v[loop])) < 0:
            loop = loop[::-1]
        m.f[W] = loop
        dead.add(S)
        changed = True
    if not changed:
        return False
    keep = [i for i in range(len(m.f)) if i not in dead]
    m.f = [m.f[i] for i in keep]
    m.mat = [m.mat[i] for i in keep]
    _drop_redundant(m)
    used = sorted(set(x for loop in m.f for x in loop))
    remap = {o: k for k, o in enumerate(used)}
    m.v = m.v[used]
    m.f = [[remap[x] for x in loop] for loop in m.f]
    m.fill_edges()
    return True


def _loop_normal(P):
    n = np.zeros(3)
    for j in range(len(P)):
        n += np.cross(P[j], P[(j + 1) % len(P)])
    return n


def _drop_redundant(m):
    """Remove from every loop a vertex that is collinear with its neighbours and used by no other face."""
    use = {}
    for fi, loop in enumerate(m.f):
        for x in loop:
            use.setdefault(x, set()).add(fi)
    for fi, loop in enumerate(m.f):
        out = []
        for j, x in enumerate(loop):
            a, c = m.v[loop[j - 1]], m.v[loop[(j + 1) % len(loop)]]
            b = m.v[x]
            col = np.linalg.norm(np.cross(b - a, c - b)) < 1e-9 * max(1.0, np.linalg.norm(c - a) ** 2)
            if col and len(use.get(x, ())) == 1:
                continue
            out.append(x)
        m.f[fi] = out


OPS[92] = op_smart_finalize


# ---- cap, clone edge, delete edge ------------------------------------------------------------------------------------
def _border_loops(m, edges):
    """Selected border edges -> closed loops of vertices running against the existing faces."""
    nxt = {}
    for k in sorted(edges):
        a, b, f1, f2 = m.e[k]
        if f2 >= 0:
            continue
        nxt[b] = (a, k)                                      # the cap runs b -> a (opposite to f1)
    loops, used = [], set()
    for k in sorted(edges):
        a, b, f1, f2 = m.e[k]
        if f2 >= 0 or k in used:
            continue
        loop, cur = [b], b
        while True:
            if cur not in nxt:
                raise ReplayError("закрытие: граница не замкнута")
            nv, kk = nxt[cur]
            used.add(kk)
            if nv == loop[0]:
                break
            loop.append(nv)
            cur = nv
        loops.append(loop)
    return loops


def op_cap(m, op, sel):
    first = len(m.f)
    for loop in _border_loops(m, sel):
        m.f.append(loop)
        m.mat.append(0)
    idx = m.edge_index()
    for fi in range(first, len(m.f)):
        loop = m.f[fi]
        for j in range(len(loop)):
            k = idx[(loop[j], loop[(j + 1) % len(loop)])]
            m.e[k][3] = fi


OPS[9] = lambda m, op, sel: op_cap(m, op, sel)


def op_clone_edges(m, op, sel):
    """Shift-drag of border edges: a strip face per edge, its far side on new vertices."""
    for k in sorted(sel):
        a, b, f1, f2 = m.e[k]
        if f2 >= 0:
            raise ReplayError("клонирование ребра не на границе")
        nb, na = len(m.v), len(m.v) + 1                   # the far end of the edge is cloned first
        m.v = np.vstack([m.v, m.v[[b, a]]])
        fi = len(m.f)
        m.f.append([b, a, na, nb])
        m.mat.append(m.mat[f1] if f1 >= 0 else 0)
        m.e[k][3] = fi
        m.e.append([a, na, fi, -1])
        m.e.append([na, nb, fi, -1])
        m.e.append([nb, b, fi, -1])
        _fix_edge_dirs(m)


OPS[64] = lambda m, op, sel: op_clone_edges(m, op, sel)


def op_delete_edges(m, op, sel):
    """Delete edges: the faces using them go too (isolated vertices as the op says)."""
    faces = set()
    for k in sel:
        for f in m.e[k][2:]:
            if f >= 0:
                faces.add(f)
    op_delete_faces(m, faces, _pi(op, 26, 1) == 1)


OPS[54] = lambda m, op, sel: op_delete_edges(m, op, sel)


# ---- TurboSmooth ---------------------------------------------------------------------------------------------------
def mod_turbosmooth(m, mod):
    """TurboSmooth in the viewport (what 3ds Max shows and snapshotAsMesh returns): `iterations` Catmull-Clark
    steps; 0 iterations leave the cage as it is."""
    pb = mod["pb"]
    it = int(pb.get(0, 1) or 0)
    if it <= 0:
        return
    if int(pb.get(5, 0) or 0) or int(pb.get(6, 0) or 0):
        raise ReplayError("TurboSmooth с разделением по группам / материалам")
    corners = sum(len(f) for f in m.f)
    if corners * 4 ** (it - 1) > MAX_FACES:
        raise ReplayError("TurboSmooth: сетка больше %d граней - форма внутри исходной" % MAX_FACES)
    exact = (it == 1 and not getattr(m, "uncertain_topo", False) and getattr(m, "uncertain_from", None) is None
             and not getattr(m, "guessed_edges", False))
    for _ in range(it):
        _catmull_clark(m)
    # one step from a cage with known edge order: the vertices are numbered as 3ds Max numbers them (cage vertices,
    # face centres, edge points - checked on the bar table legs, the moved band is exactly the upper rings); the
    # order of the new faces and edges is not checked - selections of them stay unknown
    m.uncertain_from = None if exact else 0
    m.uncertain_topo = True


def _catmull_clark(m):
    V = m.v
    nv, ne, nf = len(V), len(m.e), len(m.f)
    E = np.array([e[:2] for e in m.e], int)
    F1 = np.array([e[2] for e in m.e], int)
    F2 = np.array([e[3] for e in m.e], int)
    fp = np.array([V[loop].mean(0) for loop in m.f])
    border = F2 < 0
    ep = np.where(border[:, None], (V[E[:, 0]] + V[E[:, 1]]) / 2,
                  (V[E[:, 0]] + V[E[:, 1]] + fp[F1] + fp[np.where(F2 < 0, F1, F2)]) / 4)
    # vertex points
    valence = np.zeros(nv)
    np.add.at(valence, E[:, 0], 1)
    np.add.at(valence, E[:, 1], 1)
    mid = (V[E[:, 0]] + V[E[:, 1]]) / 2
    Rs = np.zeros_like(V)
    np.add.at(Rs, E[:, 0], mid)
    np.add.at(Rs, E[:, 1], mid)
    Fs = np.zeros_like(V)
    fcount = np.zeros(nv)
    for fi, loop in enumerate(m.f):
        Fs[loop] += fp[fi]
        fcount[loop] += 1
    n = np.maximum(valence, 1)
    newV = (Fs / np.maximum(fcount, 1)[:, None] + 2 * Rs / n[:, None] + (n - 3)[:, None] * V) / n[:, None]
    bv = np.zeros(nv, bool)
    bv[E[border, 0]] = True
    bv[E[border, 1]] = True
    if bv.any():
        bs = np.zeros_like(V)
        bc = np.zeros(nv)
        for a, b in E[border]:
            bs[a] += V[b]
            bs[b] += V[a]
            bc[a] += 1
            bc[b] += 1
        ok = bv & (bc == 2)
        newV[ok] = (bs[ok] + 6 * V[ok]) / 8
        newV[bv & (bc != 2)] = V[bv & (bc != 2)]
    idx = {}
    for k, (a, b) in enumerate(E):
        idx[(a, b)] = k
        idx[(b, a)] = k
    verts = np.vstack([newV, fp, ep])                       # 3ds Max: cage vertices, face centres, edge points
    faces, mats = [], []
    for fi, loop in enumerate(m.f):
        d = len(loop)
        for j in range(d):
            a, b, c = loop[j - 1], loop[j], loop[(j + 1) % d]
            faces.append([b, nv + nf + idx[(b, c)], nv + fi, nv + nf + idx[(a, b)]])
            mats.append(m.mat[fi])
    m.v, m.f, m.mat = verts, faces, mats
    m.fill_edges()


# ---- Chamfer modifier (quad chamfer of every edge) -----------------------------------------------------------------
def mod_chamfer(m, mod):
    """Chamfer modifier, quad chamfer, every edge chamfered, every vertex of valence 3 (boxes, prisms): each vertex
    becomes a quad corner patch, each edge a strip of `segments` faces, each face its inset. 3ds Max stores half
    the segments it builds (an Edit Poly chamfer with 7 builds 14 - checked by the counts saved after it). The
    rounding is drawn with a quadratic profile: flat faces are exact, the rounded strips within the amount."""
    pb = mod["pb"]
    a = float(pb.get(0, 0) or 0)
    s = 2 * int(pb.get(1, 1) or 1)
    if a <= 0:
        return
    if int(pb.get(3, 0) or 0) or int(pb.get(4, 0) or 0):
        raise ReplayError("Chamfer: открытая / инвертированная фаска")
    nv = len(m.v)
    inc = {i: [] for i in range(nv)}                          # faces around each vertex
    for fi, loop in enumerate(m.f):
        for j, x in enumerate(loop):
            inc[x].append((fi, j))
    if any(len(v) != 3 for v in inc.values()):
        raise ReplayError("Chamfer: вершина не из трёх рёбер")
    V = m.v
    corner = {}                                               # (vertex, face) -> inset corner point
    for fi, loop in enumerate(m.f):
        n = m.normal(fi)
        d = len(loop)
        for j, x in enumerate(loop):
            p, q, r = V[loop[j - 1]], V[x], V[loop[(j + 1) % d]]
            u1, u2 = (p - q) / np.linalg.norm(p - q), (r - q) / np.linalg.norm(r - q)
            n1 = np.cross(n, -u1)                             # inward normals of the two edges in the face plane
            n2 = np.cross(n, u2)
            n1 /= np.linalg.norm(n1)
            n2 /= np.linalg.norm(n2)
            if n1 @ (u2) < 0 and n2 @ (u1) < 0 and False:
                pass
            A = np.array([u1, -u2]).T                         # q + a n1 + t u1 = q + a n2 + w u2
            rhs = a * (n2 - n1)
            sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
            corner[(x, fi)] = q + a * n1 + sol[0] * u1
    out_v, key = [], {}

    def add(pt, k):
        if k not in key:
            key[k] = len(out_v)
            out_v.append(pt)
        return key[k]

    # order the three faces around every vertex
    eidx = m.edge_index()
    patch = {}
    for x in range(nv):
        fs = inc[x]
        f0, j0 = fs[0]
        order = [f0]
        cur_f, cur_j = f0, j0
        for _ in range(2):
            loop = m.f[cur_f]
            prev = loop[cur_j - 1]                            # the edge x -> prev belongs to the next face
            k = eidx[(x, prev)]
            nxt = m.e[k][2] if m.e[k][3] == cur_f else m.e[k][3]
            if nxt < 0:
                raise ReplayError("Chamfer: открытая граница")
            order.append(nxt)
            cur_f, cur_j = nxt, m.f[nxt].index(x)
        C = [corner[(x, f)] for f in order]
        # edge controls: side (i, i+1) crosses the edge shared by faces order[i], order[i+1]
        E = []
        for i in range(3):
            fa, fb = order[i], order[(i + 1) % 3]
            other = [y for y in m.f[fa] if y in m.f[fb] and y != x]
            other = [y for y in other if (x, y) in eidx]
            if not other:
                raise ReplayError("Chamfer: соседние грани без общего ребра")
            dvec = V[other[0]] - V[x]
            dvec /= np.linalg.norm(dvec)
            E.append(V[x] + ((C[i] - V[x]) @ dvec) * dvec)
        patch[x] = (order, C, E)
    h = s // 2

    def bez(x, bc):
        order, C, E = patch[x]
        u = bc
        return (u[0] ** 2 * C[0] + u[1] ** 2 * C[1] + u[2] ** 2 * C[2] + 2 * u[0] * u[1] * E[0]
                + 2 * u[1] * u[2] * E[1] + 2 * u[2] * u[0] * E[2])

    def vid(x, bc):
        k = (x,) + tuple(int(round(c * 6 * s)) for c in bc)
        return add(bez(x, np.asarray(bc, float)), k)

    faces = []
    I = np.eye(3)
    for x in range(nv):                                       # corner patches: 3 quad grids h x h
        for i in range(3):
            Ck = I[i]
            Mn = (I[i] + I[(i + 1) % 3]) / 2
            O = np.ones(3) / 3
            Mp = (I[i] + I[(i - 1) % 3]) / 2
            grid = [[None] * (h + 1) for _ in range(h + 1)]
            for p_ in range(h + 1):
                for q_ in range(h + 1):
                    sp, sq = p_ / h, q_ / h
                    bc = (1 - sp) * (1 - sq) * Ck + sp * (1 - sq) * Mn + sp * sq * O + (1 - sp) * sq * Mp
                    grid[p_][q_] = vid(x, bc)
            for p_ in range(h):
                for q_ in range(h):
                    faces.append([grid[p_][q_], grid[p_][q_ + 1], grid[p_ + 1][q_ + 1], grid[p_ + 1][q_]])
    seen = set()
    for k, (va, vb, f1, f2) in enumerate(m.e):                # edge strips
        def side(x, fa, fb):
            order = patch[x][0]
            i, j = order.index(fa), order.index(fb)
            if (i + 1) % 3 == j:
                return [vid(x, (1 - t) * I[i] + t * I[j]) for t in np.linspace(0, 1, s + 1)]
            return [vid(x, (1 - t) * I[j] + t * I[i]) for t in np.linspace(0, 1, s + 1)][::-1]
        A = side(va, f1, f2)
        B = side(vb, f1, f2)
        for t in range(s):
            faces.append([A[t], A[t + 1], B[t + 1], B[t]])
    for fi, loop in enumerate(m.f):                           # inset faces
        order_pts = []
        for x in loop:
            order = patch[x][0]
            order_pts.append(vid(x, I[order.index(fi)]))
        faces.append(order_pts)
    m.v = np.array(out_v)
    m.f = faces
    m.mat = [0] * len(faces)
    _orient(m)
    m.fill_edges()
    m.uncertain_from = 0
    m.uncertain_topo = True


def _orient(m):
    """Make all faces of a closed mesh wind consistently and outward (positive volume)."""
    import collections
    nf = len(m.f)
    adj = collections.defaultdict(list)
    for fi, loop in enumerate(m.f):
        for j in range(len(loop)):
            a, b = loop[j], loop[(j + 1) % len(loop)]
            adj[frozenset((a, b))].append((fi, a, b))
    flip = [None] * nf
    for start in range(nf):
        if flip[start] is not None:
            continue
        flip[start] = False
        stack = [start]
        while stack:
            fi = stack.pop()
            loop = m.f[fi][::-1] if flip[fi] else m.f[fi]
            for j in range(len(loop)):
                a, b = loop[j], loop[(j + 1) % len(loop)]
                for g, x, y in adj[frozenset((a, b))]:
                    if g == fi or flip[g] is not None:
                        continue
                    flip[g] = (x, y) == (a, b)            # a neighbour must run b -> a
                    stack.append(g)
    m.f = [loop[::-1] if fl else loop for loop, fl in zip(m.f, flip)]
    vol = 0.0
    for loop in m.f:
        P = m.v[loop]
        for j in range(1, len(P) - 1):
            vol += np.dot(P[0], np.cross(P[j], P[j + 1]))
    if vol < 0:
        m.f = [loop[::-1] for loop in m.f]


# ---- chamfer vertex, bevel ----------------------------------------------------------------------------------------
def op_chamfer_vertex(m, op, sel):
    """Chamfer vertices (one segment, not open): every selected vertex is replaced by a new face whose corners lie
    on its edges at `amount` from it."""
    a = _pf(op, 28)
    if int(_pi(op, 100) or 0):
        raise ReplayError("фаска вершины: открытая")
    segs = _pi(op, 126, 0)
    if segs > 1:
        raise ReplayError("фаска вершины: сегментов больше одного")
    if a <= 0 or not sel:
        return
    S = set(sel)
    inc = {}
    for fi, loop in enumerate(m.f):
        for x in loop:
            if x in S:
                inc.setdefault(x, []).append(fi)
    newpts = []
    nv0 = len(m.v)
    new_faces = []
    for x in sorted(S):
        fans = [(fi, m.f[fi].index(x)) for fi in inc.get(x, [])]
        if not fans:
            continue
        ring = {}                                            # neighbour vertex -> new vertex on that edge
        for fi, j in fans:
            loop = m.f[fi]
            for y in (loop[j - 1], loop[(j + 1) % len(loop)]):
                if y in ring:
                    continue
                py = m.v[y] if y < nv0 else newpts[y - nv0]
                d = py - m.v[x]
                L = np.linalg.norm(d)
                if L <= a + 1e-9:
                    raise ReplayError("фаска вершины длиннее ребра")
                ring[y] = nv0 + len(newpts)
                newpts.append(m.v[x] + d * (a / L))
        poly = []
        for fi, j in fans:
            loop = m.f[fi]
            p, q = loop[j - 1], loop[(j + 1) % len(loop)]
            m.f[fi] = _replace_corner(loop, j, ring[p], ring[q])
            poly.append((ring[q], ring[p]))
        nxt = {u: w for u, w in poly}
        start = poly[0][0]
        loop2, cur = [start], start
        while True:
            cur = nxt.get(cur)
            if cur is None:
                raise ReplayError("фаска вершины на границе")
            if cur == start:
                break
            loop2.append(cur)
        new_faces.append((loop2, m.mat[fans[0][0]]))
    if newpts:
        m.v = np.vstack([m.v, np.array(newpts)])
    for loop2, mid in new_faces:
        m.f.append(loop2)
        m.mat.append(mid)
    used = set(x for loop in m.f for x in loop)
    dead = set(range(len(m.v))) - used
    keep = [i for i in range(len(m.v)) if i not in dead]
    remap = {o: k for k, o in enumerate(keep)}
    m.v = m.v[keep]
    m.f = [[remap[z] for z in loop] for loop in m.f]
    m.fill_edges()
    m.uncertain_from = min(sel)
    m.uncertain_topo = True


def _replace_corner(loop, j, p_new, q_new):
    out = list(loop)
    out[j:j + 1] = [p_new, q_new]
    return out


OPS[33] = lambda m, op, sel: op_chamfer_vertex(m, op, sel)


def op_bevel(m, op, sel):
    """Bevel by polygon (type 2): every selected face extruded on its own by `height` and its outline moved by
    `outline` in its plane (new vertices per face; numbering of the result is not 3ds Max's - marked)."""
    h, out, typ = _pf(op, 39), _pf(op, 40), _pi(op, 38, 0)
    if typ != 2 and len(_clusters(m, sel)) != len(sel):
        raise ReplayError("фаска граней: группой / по локальным нормалям")
    newv = []
    nv0 = len(m.v)
    side_faces, side_mats = [], []
    for fi in sorted(sel):
        loop = list(m.f[fi])
        n = m.normal(fi)
        P = m.v[loop]
        d = len(loop)
        e = np.roll(P, -1, axis=0) - P                       # edge j: P[j] -> P[j+1]
        e /= np.linalg.norm(e, axis=1)[:, None]
        nin = np.cross(n, e)                                 # inward normal of edge j
        nprev = np.roll(nin, 1, axis=0)                      # edge j-1 ends at P[j]
        bis = nin + nprev
        bis /= np.linalg.norm(bis, axis=1)[:, None]
        k = -out / np.maximum((bis * nin).sum(1), 1e-9)
        Q = P + h * n + k[:, None] * bis
        ids = list(range(nv0 + len(newv), nv0 + len(newv) + d))
        newv.extend(Q)
        for j in range(d):
            a_, b_ = loop[j], loop[(j + 1) % d]
            side_faces.append([a_, b_, ids[(j + 1) % d], ids[j]])
            side_mats.append(m.mat[fi])
        m.f[fi] = ids
    if newv:
        m.v = np.vstack([m.v, np.array(newv)])
    m.f += side_faces
    m.mat += side_mats
    m.fill_edges()
    m.uncertain_topo = True


OPS[32] = lambda m, op, sel: op_bevel(m, op, sel)


class FaceList:
    """Faces of a big mesh kept flat (offsets + vertex indices + material ids): iterates as (mat id, [loop]) like
    the importer's face lists, at a fraction of the memory of Python lists."""

    def __init__(self, loops, mats):
        n = np.fromiter((len(x) for x in loops), dtype=np.int64, count=len(loops))
        self.off = np.concatenate([[0], np.cumsum(n)]).astype(np.int64)
        self.idx = np.fromiter((x for loop in loops for x in loop), dtype=np.int32, count=int(self.off[-1]))
        self.mat = np.asarray(mats, dtype=np.int32)

    def __len__(self):
        return len(self.mat)

    def __getitem__(self, i):
        return int(self.mat[i]), self.idx[self.off[i]:self.off[i + 1]].tolist()

    def __iter__(self):
        for i in range(len(self.mat)):
            yield int(self.mat[i]), self.idx[self.off[i]:self.off[i + 1]].tolist()

    def __bool__(self):
        return len(self.mat) > 0


class TriList(FaceList):
    """Triangles of a mesh 3ds Max exported (N x 3, material id per triangle), kept as arrays - a scene of 16 million
    triangles as Python lists did not fit in the memory of the importer (L-110)."""

    def __init__(self, tris, mats):
        self.tris = np.asarray(tris, dtype=np.int32).reshape(-1, 3)
        self.mat = np.asarray(mats, dtype=np.int32)

    def __getitem__(self, i):
        return int(self.mat[i]), self.tris[i].tolist()

    def __iter__(self):
        for i in range(len(self.mat)):
            yield int(self.mat[i]), self.tris[i].tolist()


# ---- FloorGenerator --------------------------------------------------------------------------------------------------
def mod_floorgen(m, mod):
    """FloorGenerator (CG-Source): boards / tiles laid inside the flat input. The covered outline is the input's;
    the boards are recorded (length, width, grout, height) and the mesh stays the outline. Its own numbering of the
    boards is not 3ds Max-readable: an Edit Poly that edits boards by number after it is not replayed."""
    pb = mod["pb"]
    nrm = [m.normal(i) for i in range(len(m.f))]
    if nrm and any(abs(abs(float(n @ nrm[0])) - 1) > 1e-6 for n in nrm):
        raise ReplayError("FloorGenerator: основа не плоская")
    m.floor = dict(length=float(pb.get(0, 0) or 0), width=float(pb.get(4, 0) or 0),
                   grout=(float(pb.get(8, 0) or 0), float(pb.get(9, 0) or 0)),
                   height=float(pb.get(42, 0) or 0) + float(pb.get(44, 0) or 0))
    m.uncertain_from = 0
    m.uncertain_topo = True
    m.fg_outline = True
