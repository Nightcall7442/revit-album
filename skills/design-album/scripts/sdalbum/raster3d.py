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
    if n > 24:                                 # a big n-gon (the cap of a free-form top): constrained Delaunay
        return _cdt(pts, nrm)
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


def _cdt(pts, nrm):
    import shapely
    from shapely.geometry import Polygon
    a = np.array([1.0, 0.0, 0.0]) if abs(nrm[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(nrm, a)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(nrm, e1)
    xy = np.stack([pts @ e1, pts @ e2], axis=1)
    poly = Polygon(xy)
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.geom_type != "Polygon":
            return [(0, i, i + 1) for i in range(1, len(pts) - 1)]
    key = {(round(x, 3), round(y, 3)): i for i, (x, y) in enumerate(xy)}
    out = []
    for t in shapely.get_parts(shapely.constrained_delaunay_triangles(poly)):
        cs = list(t.exterior.coords)[:3]
        ids = [key.get((round(x, 3), round(y, 3))) for x, y in cs]
        if None not in ids:
            out.append(tuple(ids))
    return out or [(0, i, i + 1) for i in range(1, len(pts) - 1)]


def render(faces, out_png, elev=32, azim=-58, width=1800, ss=2, bg=(255, 255, 255), margin=0.03, edge_px=1.0,
           lines=None, crop=True, shade=(0.62, 1.0), edge_rgb=None, info=None):
    """faces -> PNG. lines: extra 3D segments [(a, b)] drawn with the depth test (feature edges of a mesh).
    crop=False with margin=0 keeps the exact extent of the projection: info gets x0, y0, x1, y1 (mm in the view
    plane: r = right, u = up) and the basis, so a view can be placed on a sheet at scale."""
    from PIL import Image
    v, r, u = _basis(elev, azim)
    allp = np.vstack([np.asarray(p, float) for p, _, _ in faces])
    xs, ys = allp @ r, allp @ u
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    W = int(width * ss)
    sc = W * (1 - 2 * margin) / max(x1 - x0, 1.0)
    H = int((y1 - y0) * sc + 2 * margin * W) + 1
    ox, oy = margin * W - x0 * sc, H - margin * W + y0 * sc
    if info is not None:                       # view-plane extent of the (uncropped) image, mm
        Wf, Hf = (W // ss) * ss, (H // ss) * ss
        info.update(x0=-ox / sc, x1=(Wf - ox) / sc, y0=(oy - Hf) / sc, y1=oy / sc, px_per_mm=sc / ss,
                    basis=(v, r, u), size=(W // ss, H // ss))
    edge_col = np.asarray(edge_rgb, float) / 255.0 if edge_rgb is not None else EDGE

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
        k = shade[1]
        if nn > 1e-9:
            n = n / nn
            k = shade[1] if abs(n[2]) > 0.9 else shade[0] + (shade[1] - shade[0]) * abs(float(n @ LIGHT))
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
            _line(img, zb, S[i], S[(i + 1) % m], eps, edge_px * ss, edge_col)
    if lines:
        A = proj(np.array([a for a, b in lines], float))
        B = proj(np.array([b for a, b in lines], float))
        for a, b in zip(A, B):
            _line(img, zb, a, b, eps, edge_px * ss, edge_col)
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    if ss > 1:
        im = im.resize((W // ss, H // ss), Image.LANCZOS)
    if crop:
        from PIL import ImageOps
        bb = ImageOps.invert(im.convert("RGB")).getbbox()
        if bb:
            im = im.crop((max(0, bb[0] - 8), max(0, bb[1] - 8), min(im.size[0], bb[2] + 8), min(im.size[1], bb[3] + 8)))
            if info is not None:
                info["crop"] = (max(0, bb[0] - 8), max(0, bb[1] - 8))
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


def _line(img, zb, a, b, eps, px, col=None):
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
            img[yi[ok], xi[ok]] = EDGE if col is None else col


def render_tris(T, cols, out_png, elev=0.0, azim=-90.0, width=1200, ss=2, bg=(255, 255, 255), margin=0.0, lines=None,
                crop=False, shade=(0.62, 1.0), edge_rgb=None, edge_px=1.0, info=None, extent=None):
    """Fast path for dense meshes: T (m×3×3 mm), cols (m×3, 0..1). Triangles smaller than ~2 px are splatted
    (vertices + centroid, nearest wins), larger ones rasterised. extent=(x0, x1, y0, y1) in the view plane fixes the
    framing (views of one item drawn at one scale). info: as in render()."""
    from PIL import Image
    v, r, u = _basis(elev, azim)
    T = np.asarray(T, float)
    P = T.reshape(-1, 3)
    xs, ys = P @ r, P @ u
    if extent is None:
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    else:
        x0, x1, y0, y1 = extent
    W = int(width * ss)
    sc = W * (1 - 2 * margin) / max(x1 - x0, 1.0)
    H = int((y1 - y0) * sc + 2 * margin * W) + 1
    ox, oy = margin * W - x0 * sc, H - margin * W + y0 * sc
    if info is not None:
        Wf, Hf = (W // ss) * ss, (H // ss) * ss
        info.update(x0=-ox / sc, x1=(Wf - ox) / sc, y0=(oy - Hf) / sc, y1=oy / sc, px_per_mm=sc / ss,
                    basis=(v, r, u), size=(W // ss, H // ss))
    edge_col = np.asarray(edge_rgb, float) / 255.0 if edge_rgb is not None else EDGE
    S = np.stack([P @ r * sc + ox, oy - P @ u * sc, P @ v], axis=-1).reshape(-1, 3, 3)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    nn = np.linalg.norm(n, axis=1)
    ok = nn > 1e-9
    n[ok] /= nn[ok][:, None]
    k = np.where(np.abs(n[:, 2]) > 0.9, shade[1], shade[0] + (shade[1] - shade[0]) * np.abs(n @ LIGHT))
    k[~ok] = shade[1]
    C = np.clip(np.asarray(cols, float)[:, :3] * k[:, None], 0, 1)
    img = np.empty((H, W, 3), float)
    img[:] = np.array(bg, float) / 255.0
    zb = np.full((H, W), -np.inf)
    span = np.maximum(S[:, :, 0].max(1) - S[:, :, 0].min(1), S[:, :, 1].max(1) - S[:, :, 1].min(1))
    area2 = np.abs((S[:, 1, 0] - S[:, 0, 0]) * (S[:, 2, 1] - S[:, 0, 1]) - (S[:, 2, 0] - S[:, 0, 0]) * (S[:, 1, 1] - S[:, 0, 1]))
    edge_on = area2 < 2.0                      # seen edge-on: nothing to fill (its outline is a feature line)
    huge = (~edge_on) & (area2 > 20000.0)
    for i in np.nonzero(huge)[0]:              # big faces: exact raster of the bounding box
        _tri(img, zb, S[i, 0], S[i, 1], S[i, 2], C[i])
    rest = np.nonzero(~huge & ~edge_on)[0]
    _sample_tris(img, zb, S[rest], C[rest])
    eps = 0.004 * (x1 - x0)
    if lines is not None and len(lines):
        L = np.asarray(lines, float)
        A = np.stack([L[:, 0] @ r * sc + ox, oy - L[:, 0] @ u * sc, L[:, 0] @ v], axis=-1)
        B = np.stack([L[:, 1] @ r * sc + ox, oy - L[:, 1] @ u * sc, L[:, 1] @ v], axis=-1)
        _lines(img, zb, A, B, eps, edge_px * ss, edge_col)
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    if ss > 1:
        im = im.resize((W // ss, H // ss), Image.LANCZOS)
    if crop:
        from PIL import ImageOps
        bb = ImageOps.invert(im.convert("RGB")).getbbox()
        if bb:
            c0 = (max(0, bb[0] - 8), max(0, bb[1] - 8))
            im = im.crop((c0[0], c0[1], min(im.size[0], bb[2] + 8), min(im.size[1], bb[3] + 8)))
            if info is not None:
                info["crop"] = c0
    im.save(out_png)
    return out_png


def _lines(img, zb, A, B, eps, px, col):
    """Many segments at once (vectorised _line)."""
    H, W = zb.shape
    L = np.hypot(B[:, 0] - A[:, 0], B[:, 1] - A[:, 1])
    n = np.maximum(2, (L * 1.5).astype(int))
    tot = int(n.sum())
    if tot == 0:
        return
    seg = np.repeat(np.arange(len(n)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    t = (np.arange(tot) - start) / np.maximum(1, np.repeat(n, n) - 1)
    P = A[seg] + (B[seg] - A[seg]) * t[:, None]
    half = max(0, int(round(px / 2.0)))
    for dx in range(-half, half + 1):
        for dy in range(-half, half + 1):
            xi = np.clip((P[:, 0] + dx).astype(int), 0, W - 1)
            yi = np.clip((P[:, 1] + dy).astype(int), 0, H - 1)
            ok = P[:, 2] >= zb[yi, xi] - eps
            img[yi[ok], xi[ok]] = col


def _splat(img, zb, pts, cc):
    H, W = zb.shape
    xi = np.clip(pts[:, 0].astype(int), 0, W - 1)
    yi = np.clip(pts[:, 1].astype(int), 0, H - 1)
    z = pts[:, 2]
    o = np.argsort(z, kind="stable")           # far first: the nearest is written last
    xi, yi, z, cc = xi[o], yi[o], z[o], cc[o]
    m = z > zb[yi, xi]
    xi, yi, z, cc = xi[m], yi[m], z[m], cc[m]
    zb[yi, xi] = z
    img[yi, xi] = cc



def _sample_tris(img, zb, S, C, step=0.7, chunk=3000000):
    """Fill triangles by samples ~step px apart along the longest edge and across it (a parallelogram folded onto
    the triangle) - the number of samples follows the area, slivers of long quads cost what they cover."""
    if not len(S):
        return
    e = np.stack([np.hypot(*(S[:, (i + 1) % 3, :2] - S[:, i, :2]).T) for i in range(3)], axis=1)
    k = np.argmax(e, axis=1)
    r = np.arange(len(S))
    A = S[r, k]
    B = S[r, (k + 1) % 3]
    Cc = S[r, (k + 2) % 3]
    L = e[r, k]
    area2 = np.abs((B[:, 0] - A[:, 0]) * (Cc[:, 1] - A[:, 1]) - (Cc[:, 0] - A[:, 0]) * (B[:, 1] - A[:, 1]))
    hgt = area2 / np.maximum(L, 1e-6)
    lac = np.hypot(Cc[:, 0] - A[:, 0], Cc[:, 1] - A[:, 1])
    nu = np.maximum(1, np.ceil(L / step)).astype(np.int64) + 1
    nv = np.maximum(1, np.ceil(np.maximum(hgt, lac * 0.0 + hgt) / step)).astype(np.int64) + 1
    cnt = nu * nv
    starts = np.concatenate([[0], np.cumsum(cnt)])
    i0 = 0
    while i0 < len(S):
        i1 = int(np.searchsorted(starts, starts[i0] + chunk, side="right")) - 1
        i1 = max(i1, i0 + 1)
        idx = np.arange(i0, i1)
        c = cnt[idx]
        tri = np.repeat(idx, c)
        j = np.arange(int(c.sum())) - np.repeat(starts[idx] - starts[i0], c)
        u = (j % nu[tri]) / np.maximum(1, nu[tri] - 1)
        v = (j // nu[tri]) / np.maximum(1, nv[tri] - 1)
        f = u + v > 1.0
        u = np.where(f, 1.0 - u, u)
        v = np.where(f, 1.0 - v, v)
        P = A[tri] + (B[tri] - A[tri]) * u[:, None] + (Cc[tri] - A[tri]) * v[:, None]
        _splat(img, zb, P, C[tri])
        i0 = i1


def _split_long(S, C, maxspan, rounds=8):
    """Split triangles at the midpoint of the longest edge until the screen span is <= maxspan (slivers of long
    quads become small triangles the sampler fills without waste)."""
    for _ in range(rounds):
        span = np.maximum(S[:, :, 0].max(1) - S[:, :, 0].min(1), S[:, :, 1].max(1) - S[:, :, 1].min(1))
        big = span > maxspan
        if not big.any():
            break
        B = S[big]
        e = np.stack([np.hypot(*(B[:, (i + 1) % 3, :2] - B[:, i, :2]).T) for i in range(3)], axis=1)
        k = np.argmax(e, axis=1)
        a = B[np.arange(len(B)), k]
        b = B[np.arange(len(B)), (k + 1) % 3]
        c = B[np.arange(len(B)), (k + 2) % 3]
        mid = (a + b) / 2.0
        T1 = np.stack([a, mid, c], axis=1)
        T2 = np.stack([mid, b, c], axis=1)
        S = np.concatenate([S[~big], T1, T2])
        C = np.concatenate([C[~big], C[big], C[big]])
    return S, C


def render_painter(T, cols, out_png, elev=0.0, azim=-90.0, width=1200, ss=2, bg=(255, 255, 255), margin=0.0,
                   lines=None, shade=(0.62, 1.0), edge_rgb=None, edge_px=1.0, info=None, extent=None, crop=False,
                   max_span=40.0):
    """Same contract as render_tris, drawn by depth-sorted primitives in PIL (C speed): triangles far to near,
    feature lines inserted at their depth (slightly towards the camera) so nearer faces hide them. Large faces are
    split first (max_span px) so the order holds. For dense furniture meshes (100k+ triangles)."""
    from PIL import Image, ImageDraw
    v, r, u = _basis(elev, azim)
    T = np.asarray(T, float)
    P = T.reshape(-1, 3)
    xs, ys = P @ r, P @ u
    if extent is None:
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    else:
        x0, x1, y0, y1 = extent
    W = int(width * ss)
    sc = W * (1 - 2 * margin) / max(x1 - x0, 1.0)
    H = int((y1 - y0) * sc + 2 * margin * W) + 1
    ox, oy = margin * W - x0 * sc, H - margin * W + y0 * sc
    if info is not None:
        Wf, Hf = (W // ss) * ss, (H // ss) * ss
        info.update(x0=-ox / sc, x1=(Wf - ox) / sc, y0=(oy - Hf) / sc, y1=oy / sc, px_per_mm=sc / ss,
                    basis=(v, r, u), size=(W // ss, H // ss))
    S = np.stack([P @ r * sc + ox, oy - P @ u * sc, P @ v], axis=-1).reshape(-1, 3, 3)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    nn = np.linalg.norm(n, axis=1)
    ok = nn > 1e-9
    n[ok] /= nn[ok][:, None]
    k = np.where(np.abs(n[:, 2]) > 0.9, shade[1], shade[0] + (shade[1] - shade[0]) * np.abs(n @ LIGHT))
    k[~ok] = shade[1]
    C = np.clip(np.asarray(cols, float)[:, :3] * k[:, None], 0, 1)
    area2 = np.abs((S[:, 1, 0] - S[:, 0, 0]) * (S[:, 2, 1] - S[:, 0, 1]) - (S[:, 2, 0] - S[:, 0, 0]) * (S[:, 1, 1] - S[:, 0, 1]))
    keep = area2 >= 0.05
    S, C = _split_long(S[keep], C[keep], max_span, rounds=10)
    depth = S[:, :, 2].mean(1)
    col8 = (C * 255).astype(np.uint8)
    prims = [(float(depth[i]), 0, i) for i in range(len(S))]
    eps = 0.004 * (x1 - x0) * sc
    if lines is not None and len(lines):
        L = np.asarray(lines, float)
        A = np.stack([L[:, 0] @ r * sc + ox, oy - L[:, 0] @ u * sc, L[:, 0] @ v * sc], axis=-1)
        B = np.stack([L[:, 1] @ r * sc + ox, oy - L[:, 1] @ u * sc, L[:, 1] @ v * sc], axis=-1)
        ld = np.maximum(A[:, 2], B[:, 2]) / sc + 0.004 * (x1 - x0)
        prims += [(float(ld[i]), 1, i) for i in range(len(L))]
    else:
        A = B = None
    prims.sort(key=lambda t: t[0])
    im = Image.new("RGB", (W, H), tuple(bg))
    dr = ImageDraw.Draw(im)
    ecol = tuple(int(c) for c in (edge_rgb or (int(EDGE[0] * 255),) * 3))
    lw = max(1, int(round(edge_px * ss)))
    Sx = S[:, :, :2]
    for _, kind, i in prims:
        if kind == 0:
            q = Sx[i]
            dr.polygon([(q[0, 0], q[0, 1]), (q[1, 0], q[1, 1]), (q[2, 0], q[2, 1])], fill=tuple(col8[i]))
        else:
            dr.line([(A[i, 0], A[i, 1]), (B[i, 0], B[i, 1])], fill=ecol, width=lw)
    if ss > 1:
        im = im.resize((W // ss, H // ss), Image.LANCZOS)
    if crop:
        from PIL import ImageOps
        bb = ImageOps.invert(im.convert("RGB")).getbbox()
        if bb:
            c0 = (max(0, bb[0] - 8), max(0, bb[1] - 8))
            im = im.crop((c0[0], c0[1], min(im.size[0], bb[2] + 8), min(im.size[1], bb[3] + 8)))
            if info is not None:
                info["crop"] = c0
    im.save(out_png)
    return out_png
