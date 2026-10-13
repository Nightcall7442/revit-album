# -*- coding: utf-8 -*-
"""Meshes of furniture items (importers/scene_items) -> views for the production sheets.

    m = load(P, item)                      ItemMesh (local mm: x along the front, -y towards the viewer, z up from 0)
    m.view(kind, png, px_per_mm)           orthographic view 'front' | 'left' | 'top' at a known scale (info: extent)
    m.axo(png, width)                      shaded axonometric view coloured by material, part anchors for callouts
    m.levels() / m.columns()               shelf / seat / top levels and vertical boards for the chain dimensions
    m.round_top()                          a round table / stool: the top view is a circle -> «Ø»

Parts smoothed in the scene by TurboSmooth / MeshSmooth are subdivided here (Catmull-Clark) - the cage alone draws
facets that the made piece does not have. Views are drawn as a hidden-line drawing: near-white faces, visible feature
edges (outline, creases > 35°, silhouette) by a depth test (raster3d).
"""
import math
import os
import pickle
import re

import numpy as np

from . import raster3d

FAMILIES = [
    ("led", r"(?i)backlight|led|neon|lightmtl|подсвет|light"),
    ("mirror", r"(?i)mirror|зеркал"),
    ("glass", r"(?i)glass|стекл"),
    ("marble", r"(?i)marble|мрамор|calacatta|carrara|statuario|caldera|onyx|оникс"),
    ("stone", r"(?i)stone|travertin|granite|камен|травертин|terrazzo"),
    ("brick", r"(?i)brick|кирпич|clinker|клинкер|tile|плитк"),
    ("metal", r"(?i)metal|steel|iron|chrom|brass|bronze|alumin|металл|сталь|латун|metalus|\bleg|ножк"),
    ("leather", r"(?i)leather|кож"),
    ("fabric", r"(?i)fabric|textile|velvet|boucle|linen|flax|ткан|sofa|cushion|pillow|upholst|teddy"),
    ("wood", r"(?i)wood|oak|walnut|veneer|шпон|дуб|орех|ash\b|plywood|фанер"),
    ("plastic", r"(?i)plastic|пластик"),
]
COLORS = {"led": (1.0, 0.86, 0.45), "mirror": (0.80, 0.86, 0.90), "glass": (0.78, 0.87, 0.90),
          "marble": (0.93, 0.92, 0.90), "stone": (0.80, 0.78, 0.74), "brick": (0.70, 0.30, 0.24),
          "metal": (0.24, 0.24, 0.26), "leather": (0.45, 0.30, 0.22), "fabric": (0.80, 0.72, 0.60),
          "wood": (0.58, 0.43, 0.30), "plastic": (0.85, 0.85, 0.85), None: (0.80, 0.78, 0.75)}


def family(*names):
    txt = " ".join(n for n in names if n)
    for fam, rx in FAMILIES:
        if re.search(rx, txt):
            return fam
    return None


# ------------------------------------------------------------------ geometry
def _normals(v, faces):
    """Newell normals and areas of polygons (vectorised by polygon size)."""
    n = np.zeros((len(faces), 3))
    by = {}
    for i, f in enumerate(faces):
        by.setdefault(len(f), []).append(i)
    for m, idx in by.items():
        F = np.array([faces[i] for i in idx], int)
        p = v[F]                                    # k×m×3
        q = np.roll(p, -1, axis=1)
        n[idx, 0] = np.sum((p[:, :, 1] - q[:, :, 1]) * (p[:, :, 2] + q[:, :, 2]), axis=1)
        n[idx, 1] = np.sum((p[:, :, 2] - q[:, :, 2]) * (p[:, :, 0] + q[:, :, 0]), axis=1)
        n[idx, 2] = np.sum((p[:, :, 0] - q[:, :, 0]) * (p[:, :, 1] + q[:, :, 1]), axis=1)
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    n[ok] /= ln[ok][:, None]
    return n, ln / 2.0


def subdivide(v, faces):
    """One Catmull-Clark step (polygon mesh -> quads)."""
    v = np.asarray(v, float)
    nv = len(v)
    fp = np.array([v[f].mean(0) for f in faces])
    emap = {}
    for fi, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            emap.setdefault((min(a, b), max(a, b)), []).append(fi)
    ekeys = list(emap)
    eidx = {e: nv + len(faces) + i for i, e in enumerate(ekeys)}
    ep = np.zeros((len(ekeys), 3))
    for i, e in enumerate(ekeys):
        fs = emap[e]
        if len(fs) == 2:
            ep[i] = (v[e[0]] + v[e[1]] + fp[fs[0]] + fp[fs[1]]) / 4.0
        else:
            ep[i] = (v[e[0]] + v[e[1]]) / 2.0
    # vertex update
    F = np.zeros((nv, 3))
    nf = np.zeros(nv)
    for fi, f in enumerate(faces):
        for a in f:
            F[a] += fp[fi]
            nf[a] += 1
    R = np.zeros((nv, 3))
    ne = np.zeros(nv)
    bnd = [[] for _ in range(nv)]
    for e, fs in emap.items():
        mid = (v[e[0]] + v[e[1]]) / 2.0
        for a in e:
            R[a] += mid
            ne[a] += 1
        if len(fs) == 1:
            bnd[e[0]].append(e[1])
            bnd[e[1]].append(e[0])
    nvv = v.copy()
    for a in range(nv):
        if bnd[a]:
            if len(bnd[a]) == 2:
                nvv[a] = (6 * v[a] + v[bnd[a][0]] + v[bnd[a][1]]) / 8.0
            continue
        n = nf[a]
        if n < 3 or ne[a] == 0:
            continue
        nvv[a] = (F[a] / n + 2.0 * R[a] / ne[a] + (n - 3.0) * v[a]) / n
    out_v = np.vstack([nvv, fp, ep])
    out_f = []
    for fi, f in enumerate(faces):
        m = len(f)
        for i in range(m):
            a, b, c = f[i - 1], f[i], f[(i + 1) % m]
            out_f.append([b, eidx[(min(b, c), max(b, c))], nv + fi, eidx[(min(a, b), max(a, b))]])
    return out_v, out_f


class Part:
    def __init__(self, d):
        self.name = d.get("name", "")
        self.mats = d.get("mats") or []
        self.mods = d.get("mods") or []
        self.prop = bool(d.get("prop"))
        self.v = np.asarray(d["v"], float)
        nv = len(self.v)
        self.f = [list(map(int, f)) for f in d.get("f") or [] if len(f) >= 3 and max(f) < nv and min(f) >= 0]
        if len(self.f) > 500:                  # faces of a broken stream span the whole object: drop them
            tri = np.array([f[:3] for f in self.f], int)
            e = np.max(np.linalg.norm(self.v[tri] - self.v[np.roll(tri, 1, axis=1)], axis=2), axis=1)
            med = float(np.median(e))
            keep = ~((e > 25.0 * max(med, 1.0)) & (e > 500.0))
            if (~keep).any():
                self.f = [f for f, k in zip(self.f, keep) if k]
        main = [m for m in self.mats[:1]] + [self.name] + [m for m in self.mats[1:] if not re.search(r"(?i)light|led", m)]
        self.fam = None
        for nm in main:                       # the main material decides (a backlight sub-material does not)
            self.fam = family(nm)
            if self.fam:
                break

    def smooth(self, budget=60000):
        if not any(re.search(r"(?i)turbosmooth|meshsmooth", m) for m in self.mods) or not self.f:
            return
        for _ in range(2):
            if len(self.f) * 4 > budget:
                break
            self.v, self.f = subdivide(self.v, self.f)


class ItemMesh:
    def __init__(self, data, size=None):
        self.parts = [Part(p) for p in data["parts"]]
        self.parts = [p for p in self.parts if p.f and len(p.v)]
        for p in self.parts:
            p.smooth()
        body = [p for p in self.parts if not p.prop] or self.parts
        lo = np.min([p.v.min(0) for p in body], 0)
        hi = np.max([p.v.max(0) for p in body], 0)
        mid = (lo + hi) / 2.0
        z0 = min(float(lo[2]), 0.0)                 # a piece standing on feet keeps the gap under it
        for p in self.parts:
            p.v[:, 0] -= mid[0]
            p.v[:, 1] -= mid[1]
            p.v[:, 2] -= z0
        self.size = [float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - z0)]
        if size and all(size) and any(abs(a - b) > 2 for a, b in zip(size, self.size)):
            k = [s / max(1.0, t) for s, t in zip(size, self.size)]      # the designer's size: the model is stretched
            for p in self.parts:
                p.v *= np.array(k)
            self.size = [float(s) for s in size]
        self._tri = None

    # -------------------------------------------------- triangles / edges
    def tris(self, props=True, colour=True):
        key = (props, colour)
        cache = self.__dict__.setdefault("_tcache", {})
        if key in cache:
            return cache[key]
        T, C, owner = [], [], []
        for pi, p in enumerate(self.parts):
            if p.prop and not props:
                continue
            col = COLORS.get(p.fam, COLORS[None]) if colour else (0.99, 0.99, 0.99)
            by = {}
            for f in p.f:
                by.setdefault(min(len(f), 5), []).append(f)
            parts_t = []
            if 3 in by:
                parts_t.append(p.v[np.array(by[3], int)])
            if 4 in by:
                q = np.array(by[4], int)
                parts_t.append(p.v[q[:, [0, 1, 2]]])
                parts_t.append(p.v[q[:, [0, 2, 3]]])
            for f in by.get(5, []):
                idx = [(f[i], f[j], f[k]) for (i, j, k) in raster3d._triangles(p.v[f])]
                if idx:
                    parts_t.append(p.v[np.array(idx, int)])
            for t in parts_t:
                T.append(t)
                C.append(np.tile(np.array(col, float), (len(t), 1)))
                owner += [pi] * len(t)
        out = (np.concatenate(T) if T else np.zeros((0, 3, 3)), np.concatenate(C) if C else np.zeros((0, 3)), owner)
        cache[key] = out
        return out

    def edges(self, view, props=False, crease=35.0):
        """Visible-candidate feature edges for a view direction (unit vector towards the camera)."""
        out = []
        cosc = math.cos(math.radians(crease))
        for p in self.parts:
            if p.prop and not props:
                continue
            if not hasattr(p, "_adj"):
                n, _ = _normals(p.v, p.f)
                emap = {}
                for fi, f in enumerate(p.f):
                    for a, b in zip(f, f[1:] + f[:1]):
                        emap.setdefault((min(a, b), max(a, b)), []).append(fi)
                E = np.array(list(emap.keys()), int).reshape(-1, 2)
                F0 = np.array([fs[0] for fs in emap.values()], int)
                F1 = np.array([fs[1] if len(fs) > 1 else -1 for fs in emap.values()], int)
                p._adj = (n, E, F0, F1)
            n, E, F0, F1 = p._adj
            if not len(E):
                continue
            bnd = F1 < 0
            n0 = n[F0]
            n1 = n[np.where(bnd, F0, F1)]
            cre = np.sum(n0 * n1, axis=1) < cosc
            d0, d1 = n0 @ view, n1 @ view
            sil = (d0 * d1 < 0)
            m = bnd | cre | sil
            if m.any():
                out.append(np.stack([p.v[E[m, 0]], p.v[E[m, 1]]], axis=1))
        return np.concatenate(out) if out else np.zeros((0, 2, 3))

    # -------------------------------------------------- views
    VIEWS = {"front": (0.0, -90.0), "left": (0.0, 180.0), "top": (90.0, -90.0)}

    def extent(self, kind):
        el, az = self.VIEWS[kind]
        v, r, u = raster3d._basis(el, az)
        P = np.vstack([p.v for p in self.parts if not p.prop] or [p.v for p in self.parts])
        xs, ys = P @ r, P @ u
        return float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())

    def view(self, kind, png, px_per_mm=0.4, info=None):
        el, az = self.VIEWS[kind]
        v, r, u = raster3d._basis(el, az)
        T, C, _ = self.tris(props=False, colour=False)
        x0, x1, y0, y1 = self.extent(kind)
        pad = 2.0
        ext = (x0 - pad, x1 + pad, y0 - pad, y1 + pad)
        L = self.edges(v)
        width = max(60, int((ext[1] - ext[0]) * px_per_mm))
        inf = {} if info is None else info
        raster3d.render_painter(T, C, png, elev=el, azim=az, width=width, ss=2, margin=0.0, lines=L, crop=False,
                             shade=(0.88, 1.0), edge_rgb=(25, 25, 28), edge_px=2.0, info=inf, extent=ext)
        return inf

    def axo(self, png, width=900, elev=24.0, azim=-62.0, info=None):
        T, C, owner = self.tris(props=True, colour=True)
        v, r, u = raster3d._basis(elev, azim)
        L = self.edges(v, props=False, crease=50.0)
        inf = {} if info is None else info
        raster3d.render_painter(T, C, png, elev=elev, azim=azim, width=width, ss=2, margin=0.04, lines=L, crop=False,
                             shade=(0.55, 1.0), edge_rgb=(70, 66, 62), edge_px=0.8, info=inf)
        return inf

    def anchor(self, pi, info):
        """A visible-ish point of part pi on the axonometric image (px from the top-left)."""
        v, r, u = info["basis"]
        p = self.parts[pi]
        P = p.v
        d = P @ v                                     # nearest third of the part towards the camera
        sel = P[d >= np.percentile(d, 66)] if len(P) > 6 else P
        c = sel.mean(0)
        s = info["px_per_mm"]
        return ((c @ r - info["x0"]) * s, (info["y1"] - c @ u) * s)

    # -------------------------------------------------- measurements for the dimensions
    def _faces_dir(self, axis, sign=None):
        out = []
        for p in self.parts:
            if p.prop or not p.f:
                continue
            n, area = _normals(p.v, p.f)
            for fi, f in enumerate(p.f):
                c = n[fi][axis]
                if (sign is None and abs(c) > 0.92) or (sign is not None and c * sign > 0.92):
                    out.append((float(p.v[f][:, axis].mean()), float(area[fi])))
        return out

    def levels(self, maxn=8):
        """Heights of upward surfaces with a real area: seat, worktop, shelves (a board = its top)."""
        foot = self.size[0] * self.size[1]
        fs = self._faces_dir(2, 1)
        acc = {}
        for z, a in fs:
            k = round(z / 10.0) * 10
            acc[k] = acc.get(k, 0.0) + a
        zs = [z for z, a in sorted(acc.items()) if a > 0.04 * foot and 25 < z < self.size[2] - 30]
        merged = []
        for z in zs:
            if merged and z - merged[-1] < 30:
                merged[-1] = z
                continue
            merged.append(z)
        if len(merged) > maxn:
            merged = sorted(sorted(merged, key=lambda z: -acc[z])[:maxn])
        return [0.0] + [float(z) for z in merged] + [round(self.size[2])]

    def top_board(self):
        """Thickness of the top board (worktop, table top): the highest underside below the top within 15-80 mm."""
        H = self.size[2]
        foot = self.size[0] * self.size[1]
        acc = {}
        for z, a in self._faces_dir(2, -1):
            if H - 80 <= z <= H - 12:
                k = round(z / 2.0) * 2
                acc[k] = acc.get(k, 0.0) + a
        best = [z for z, a in acc.items() if a > 0.25 * foot]
        return round(H - max(best)) if best else None

    def columns(self, maxn=8):
        """x of vertical boards facing sideways (shelving divisions) for the chain along the width."""
        foot = self.size[1] * self.size[2]
        fs = self._faces_dir(0)
        acc = {}
        for x, a in fs:
            k = round(x / 10.0) * 10
            acc[k] = acc.get(k, 0.0) + a
        W = self.size[0]
        xs = [x for x, a in sorted(acc.items()) if a > 0.25 * foot and -W / 2 + 40 < x < W / 2 - 40]
        merged = []
        for x in xs:
            if merged and x - merged[-1] < 60:
                continue
            merged.append(x)
        if not merged or len(merged) > maxn:
            return []
        return [-W / 2.0] + merged + [W / 2.0]

    def round_top(self, png_top=None):
        W, D = self.size[0], self.size[1]
        if abs(W - D) > 0.04 * max(W, D):
            return False
        pts = np.vstack([p.v[:, :2] for p in self.parts if not p.prop])
        r = np.hypot(pts[:, 0], pts[:, 1])
        R = max(W, D) / 2.0
        far = pts[r > 0.9 * R]
        if len(far) < 8:
            return False
        ang = np.degrees(np.arctan2(far[:, 1], far[:, 0]))
        corner = np.sum(np.abs(((ang % 90) - 45)) < 8) / float(len(ang))
        return float(r.max()) < 1.03 * R and corner < 0.6 and np.percentile(r, 99) > 0.95 * R


def _rounded(y0, y1, z0, z1, r, seg=6):
    r = max(0.0, min(r, (y1 - y0) / 2.0, (z1 - z0) / 2.0))
    pts = []
    for cy, cz, a0 in ((y1 - r, z0 + r, -90), (y1 - r, z1 - r, 0), (y0 + r, z1 - r, 90), (y0 + r, z0 + r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cy + r * math.cos(a), cz + r * math.sin(a)))
    return pts


def profile_mesh(it):
    """A piece the designer described by its section (a sofa of rolls, a bench, a counter front): rounded blocks
    {name, mat, y0, y1, z0, z1, r, inset} extruded along the length -> mesh data like scene_items writes."""
    L = float(it["profile"].get("length") or it["size"][0])
    parts = []
    for b in it["profile"]["blocks"]:
        ins = float(b.get("inset", 0))
        x0, x1 = -L / 2.0 + ins, L / 2.0 - ins
        if b.get("x0") is not None:                  # a section along the length (cushions of a bench)
            x0, x1 = -L / 2.0 + float(b["x0"]), -L / 2.0 + float(b["x1"])
        ring = _rounded(b["y0"], b["y1"], b["z0"], b["z1"], b.get("r", 0))
        n = len(ring)
        v = [(x0, y, z) for y, z in ring] + [(x1, y, z) for y, z in ring]
        f = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
        parts.append(dict(name=b.get("name", "блок"), mats=[b.get("mat", "")], v=np.array(v, np.float32), f=f, mods=[]))
    return dict(parts=parts)


def load(P, it):
    if it.get("profile"):
        return ItemMesh(profile_mesh(it))
    path = it.get("mesh")
    if not path:
        return None
    for base in (P.base_dir, os.path.join(P.base_dir, "import")):
        fn = os.path.join(base, path)
        if os.path.isfile(fn):
            try:
                data = pickle.load(open(fn, "rb"))
            except Exception:
                return None
            return ItemMesh(data, it.get("size") if it.get("size_user") else None)
    return None
