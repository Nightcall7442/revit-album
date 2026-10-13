# -*- coding: utf-8 -*-
"""Small orthographic renderer with a depth buffer (numpy), for the axonometric views of the album.

matplotlib's 3D draws polygons in painter's order without a depth buffer: a large wall face is sorted by its centre
and covers the tiles in front of it, far faces show through near ones (lesson L-080). Here every triangle is
rasterised with a z-test, edges (tile joints, outlines) are drawn with the same z-test, the image is rendered at 2×
and downsampled (anti-aliasing).

    faces = [(pts (n×3, mm), rgb 0..1, edge: bool)]
    render(faces, out_png, elev=32, azim=-58, width=1800)
"""
import math

import numpy as np

LIGHT = np.array([-0.45, -0.75, 0.85])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
EDGE = np.array([0.36, 0.36, 0.39])


def _basis(elev, azim):
    e, a = math.radians(elev), math.radians(azim)
    v = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])      # towards the camera
    r = np.array([-math.sin(a), math.cos(a), 0.0])
    u = np.cross(v, r)
    return v, r, u


def _triangles(pts):
    """Planar polygon -> triangles (fan for convex, ear clipping otherwise)."""
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]
    nrm = np.zeros(3)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nrm += np.cross(a, b)
    if np.linalg.norm(nrm) < 1e-9:
        return []
    nrm /= np.linalg.norm(nrm)
    convex = True
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        if np.dot(np.cross(b - a, c - b), nrm) < -1e-9:
            convex = False
            break
    if convex:
        return [(0, i, i + 1) for i in range(1, n - 1)]
    idx = list(range(n))
    out = []
    guard = 0
    while len(idx) > 3 and guard < 10 * n:
        guard += 1
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if np.dot(np.cross(b - a, c - b), nrm) <= 1e-9:
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                if (np.dot(np.cross(b - a, p - a), nrm) >= 0 and np.dot(np.cross(c - b, p - b), nrm) >= 0
                        and np.dot(np.cross(a - c, p - c), nrm) >= 0):
                    ok = False
                    break
            if ok:
                out.append((i0, i1, i2))
                idx.pop(k)
                break
        else:
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def render(faces, out_png, elev=32, azim=-58, width=1800, ss=2, bg=(255, 255, 255), margin=0.03, edge_px=1.0):
    from PIL import Image
    v, r, u = _basis(elev, azim)
    allp = np.vstack([np.asarray(p, float) for p, _, _ in faces])
    xs, ys = allp @ r, allp @ u
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    W = int(width * ss)
    sc = W * (1 - 2 * margin) / max(x1 - x0, 1.0)
    H = int((y1 - y0) * sc + 2 * margin * W) + 1
    ox, oy = margin * W - x0 * sc, H - margin * W + y0 * sc

    def proj(P):
        P = np.asarray(P, float)
        return np.stack([P @ r * sc + ox, oy - P @ u * sc, P @ v], axis=-1)
    img = np.empty((H, W, 3), float)
    img[:] = np.array(bg, float) / 255.0
    zb = np.full((H, W), -np.inf)
    edges = []
    for pts, col, edge in faces:
        P = np.asarray(pts, float)
        if len(P) < 3:
            continue
        n = np.cross(P[1] - P[0], P[2] - P[0])
        if np.linalg.norm(n) < 1e-9 and len(P) > 3:
            n = np.cross(P[2] - P[0], P[3] - P[0])
        nn = np.linalg.norm(n)
        k = 1.0
        if nn > 1e-9:
            n = n / nn
            k = 1.0 if abs(n[2]) > 0.9 else 0.62 + 0.38 * abs(float(n @ LIGHT))
        c = np.clip(np.asarray(col, float)[:3] * k, 0, 1)
        S = proj(P)
        for (i, j, l) in _triangles(P):
            _tri(img, zb, S[i], S[j], S[l], c)
        if edge:
            edges.append(S)
    eps = 0.004 * (x1 - x0)                    # an edge on a face passes the z-test of that face
    for S in edges:
        m = len(S)
        for i in range(m):
            _line(img, zb, S[i], S[(i + 1) % m], eps, edge_px * ss)
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    if ss > 1:
        im = im.resize((W // ss, H // ss), Image.LANCZOS)
    from PIL import ImageOps
    bb = ImageOps.invert(im.convert("RGB")).getbbox()
    if bb:
        im = im.crop((max(0, bb[0] - 8), max(0, bb[1] - 8), min(im.size[0], bb[2] + 8), min(im.size[1], bb[3] + 8)))
    im.save(out_png)
    return out_png


def _tri(img, zb, a, b, c, col):
    H, W = zb.shape
    xmin = int(max(0, math.floor(min(a[0], b[0], c[0]))))
    xmax = int(min(W - 1, math.ceil(max(a[0], b[0], c[0]))))
    ymin = int(max(0, math.floor(min(a[1], b[1], c[1]))))
    ymax = int(min(H - 1, math.ceil(max(a[1], b[1], c[1]))))
    if xmax < xmin or ymax < ymin:
        return
    den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(den) < 1e-12:
        return
    X, Y = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
    w0 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / den
    w1 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / den
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
    if not inside.any():
        return
    z = w0 * a[2] + w1 * b[2] + w2 * c[2]
    sub = zb[ymin:ymax + 1, xmin:xmax + 1]
    upd = inside & (z > sub)
    sub[upd] = z[upd]
    img[ymin:ymax + 1, xmin:xmax + 1][upd] = col


def _line(img, zb, a, b, eps, px):
    H, W = zb.shape
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    n = max(2, int(L * 1.5))
    t = np.linspace(0, 1, n)
    x = a[0] + (b[0] - a[0]) * t
    y = a[1] + (b[1] - a[1]) * t
    z = a[2] + (b[2] - a[2]) * t
    half = max(0, int(round(px / 2.0)))
    for dx in range(-half, half + 1):
        for dy in range(-half, half + 1):
            xi = np.clip((x + dx).astype(int), 0, W - 1)
            yi = np.clip((y + dy).astype(int), 0, H - 1)
            ok = z >= zb[yi, xi] - eps
            img[yi[ok], xi[ok]] = EDGE
