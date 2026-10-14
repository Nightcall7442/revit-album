# -*- coding: utf-8 -*-
"""3ds Max scene (.max) -> survey pack for building project.json.

    python3 sda.py import-max scene.max OUT [--units cm|mm|m|in] [--cut 1100] [--floor 0]

Writes to OUT:
  inventory.json     every node: class, modifiers, layer, material, world bbox (mm), primitive params (mm)
  inventory.md       summary: classes, units guess, objects whose geometry can't be read (modifiers not evaluated)
  sections.json      plan sections (mm) of every readable mesh at the cut heights
  plan_cut.png       plan section at the cut height + primitive footprints (blue) + names: read walls / openings from it
  plan_floor.png     section just above the floor (furniture footprints, sanitary ware)
  plan_ceiling.png   section just below the ceiling (bulkheads, coves, ceiling fixtures)
  draft_project.json skeleton with meta / levels / wall candidates (from tall thin boxes / planes) - to be checked

Nothing here is final: the agent reads the pictures + inventory, decides walls / openings / rooms, writes project.json
and runs `sda.py validate`. Units: 3ds Max files do not reliably tell the system unit; it is guessed from storey height.
"""
import json
import math
import re
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
SKIP_CLASSES = ("CoronaLight", "CoronaCam", "CoronaSun", "Target", "Dummy", "VRayLight", "VRayPhysicalCamera",
                "Free Camera", "Target Camera", "Omni", "Point", "Physical", "Sunlight")


def _pb2(base, R):
    """ParamBlock2 values of a primitive: {param id: float}."""
    M = R.M
    out = {}
    try:
        refs = M.get_references(base)
    except Exception:
        return out
    for r in refs or []:
        if r is None or R.cls_name(r) != "ParamBlock2":
            continue
        for c in getattr(r, "children", []):
            if c.types != 0x100E or isinstance(c.data, tuple):
                continue
            b = bytes(c.data)
            if len(b) != 19:
                continue
            pid, typ = struct.unpack_from("<HH", b, 0)
            if typ in (0, 7):                     # float / world-unit float
                out[pid] = struct.unpack_from("<f", b, 15)[0]
        break
    return out


def _footprint(cls, prm, W):
    """2D footprint + z range of Plane / Box primitives in scene units (world)."""
    if cls == "Plane" and 0 in prm and 1 in prm:
        L, Wd = prm[0], prm[1]
        z0 = z1 = 0.0
    elif cls == "Box" and 0 in prm and 1 in prm and 2 in prm:
        L, Wd, H = prm[0], prm[1], prm[2]
        z0, z1 = sorted((0.0, H))
    else:
        return None
    pts = [(-Wd / 2, -L / 2), (Wd / 2, -L / 2), (Wd / 2, L / 2), (-Wd / 2, L / 2)]
    out = []
    for x, y in pts:
        v = W @ np.array([x, y, z0, 1.0])
        out.append((float(v[0]), float(v[1])))
    zz = [float((W @ np.array([0, 0, z, 1.0]))[2]) for z in (z0, z1)]
    return out, min(zz), max(zz)


def _tri(faces):
    for _, f in faces:
        for i in range(1, len(f) - 1):
            yield f[0], f[i], f[i + 1]


def section(v, faces, h):
    """Segments of the mesh cut by plane z = h."""
    tris = np.array(list(_tri(faces)), dtype=np.int64)
    if not len(tris):
        return []
    tris = tris[(tris < len(v)).all(1)]
    P = v[tris]                                  # n x 3 x 3
    z = P[:, :, 2] - h
    s = np.sign(z)
    keep = ~((s > 0).all(1) | (s < 0).all(1))
    P, z = P[keep], z[keep]
    segs = []
    for tri, zz in zip(P, z):
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (zz[a] > 0) != (zz[b] > 0) and zz[a] != zz[b]:
                t = zz[a] / (zz[a] - zz[b])
                q = tri[a] + (tri[b] - tri[a]) * t
                pts.append((float(q[0]), float(q[1])))
        if len(pts) >= 2 and (abs(pts[0][0] - pts[1][0]) + abs(pts[0][1] - pts[1][1])) > 1e-6:
            segs.append([pts[0][0], pts[0][1], pts[1][0], pts[1][1]])
    return segs


def guess_units(rows):
    """System unit of the scene (3ds Max files do not say it reliably) by voting of known sizes: door height
    1.9-2.7 m, toilet length 0.55-0.8 m, chair height 0.7-1.15 m, bed length 1.9-2.3 m, simple tall wall boxes
    2.4-9 m. The old guess by the 90th percentile of object heights took a cm scene for inches (lesson L-062).
    -> (unit, storey height in scene units or None)"""
    import re
    from collections import Counter
    cues = []
    walls = []
    for r in rows:
        if not r.get("bbox") or r["class"] in SKIP_CLASSES:
            continue
        (x0, y0, z0), (x1, y1, z1) = r["bbox"]
        h, L, W = z1 - z0, max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
        n = (r.get("name") or "").lower()
        if re.search(r"door|двер", n) and "handle" not in n and "ручк" not in n:
            cues.append((h, 1900, 2700, 3))
        if re.search(r"toilet|унитаз", n) and not re.search(r"paper|brush|seat|cover|accessor|ерш", n):
            cues.append((L, 550, 800, 3))
        if re.search(r"chair|стул", n) and not re.search(r"leg|ножк|seat", n):
            cues.append((h, 700, 1150, 1))
        if re.search(r"\bbed\b|кроват", n):
            cues.append((L, 1900, 2300, 2))
        if (r.get("nverts") or 99) <= 64 and W > 0 and L > 4 * W:
            walls.append(h)
            cues.append((h, 2400, 9000, 1))
    votes = Counter()
    for u, k in UNIT_MM.items():
        for v, lo, hi, w in cues:
            if lo <= v * k <= hi:
                votes[u] += w
    if votes:
        u, n = votes.most_common(1)[0]
        H = float(np.percentile(walls, 90)) if walls else None
        return u, H
    hs = []
    for r in rows:
        if r.get("bbox") and r["class"] not in SKIP_CLASSES:
            (x0, y0, z0), (x1, y1, z1) = r["bbox"]
            hs.append(z1 - z0)
        if r.get("prim") and r["class"] == "Box":
            hs.append(abs(r["prim"].get("2", 0)))
    if not hs:
        return "mm", None
    H = float(np.percentile(hs, 90))
    for u, lo, hi in (("m", 2.0, 4.5), ("cm", 200, 450), ("in", 80, 180), ("mm", 2000, 4500)):
        if lo <= H <= hi:
            return u, H
    return "mm", H


def _full_stack(R, msh, W, row, meshes):
    """The whole modifier stack rebuilt the way 3ds Max does it (maxgeom). True when the node's mesh is now the
    scene's: the row gets bbox / footprint / the mesh; False leaves the node to the bounding evaluator."""
    import maxstack as MS
    import maxgeom as MG
    try:
        st = MS.read(R, msh)
        mesh, log = MG.evaluate(st)
    except MG.ReplayError as e_:
        row["geom_full_fail"] = str(e_)
        return False
    except Exception as e_:                    # a reader / numeric failure is the same as "not rebuilt"
        row["geom_full_fail"] = repr(e_)[:200]
        return False
    if not len(mesh.v) or not mesh.f:
        row["geom"] = "replayed"
        row["geom_notes"] = ["стек модификаторов вычислен: геометрии нет"]
        row.pop("footprint", None)
        row["skip"] = row.get("skip") or "пустая геометрия после модификаторов"
        return True
    vw = mesh.v @ W[:3, :3].T + W[:3, 3]
    row["geom"] = "replayed"
    notes = ["стек модификаторов вычислен как в 3ds Max: %s" % ", ".join(c for c, _ in log)] if log else []
    if getattr(mesh, "inferred", False):
        notes.append("перемещение после сшивки выдавливания: вершины найдены по геометрии (единственный вариант)")
    row["geom_notes"] = notes
    row["bbox"] = [vw.min(0).tolist(), vw.max(0).tolist()]
    row["nverts"] = int(len(vw))
    meshes[row["idx"]] = (row["name"], vw.astype(np.float32) if len(vw) > 20000 else vw, MG.FaceList(mesh.f, mesh.mat))
    if row.get("footprint"):
        from shapely.geometry import MultiPoint
        hull = MultiPoint([(float(a), float(b)) for a, b in vw[:, :2]]).convex_hull
        if hull.geom_type == "Polygon":
            row["footprint"] = [list(c) for c in list(hull.exterior.coords)[:-1]]
        row["z0"], row["z1"] = float(vw[:, 2].min()), float(vw[:, 2].max())
        row["replayed"] = True
    row.pop("note", None)
    return True


def _lattice_proxy(R, msh, W, row, meshes, k=10.0):
    """A node whose stack could not be computed but ends with an FFD: the deformed lattice of that FFD is where 3ds Max
    shows it (a sofa roll stretched to 4.3 m along the wall, its cage a metre away at 45 degrees) - the lattice
    hexahedron replaces the cage as its outline. The node stays «не проверено» (L-107)."""
    import maxstack as MS
    import maxgeom as MG
    try:
        st = MS.read(R, msh)
    except Exception:
        return False
    mods = [m for m in st["mods"] if m["cls"] not in MG.NEUTRAL_MODS]
    if not mods or mods[-1]["cls"] not in ("FFD 2x2x2", "FFD 3x3x3", "FFD 4x4x4"):
        return False
    mod = mods[-1]
    n = int(mod["cls"][4])
    raw = (mod.get("chunks") or {}).get(0x0200)
    if raw is None or mod.get("ctx_box") is None or len(raw) < 12 * n ** 3:
        return False
    pts = np.frombuffer(raw[:12 * n ** 3], "<f4").reshape(-1, 3).astype(float)
    lo, hi = np.asarray(mod["ctx_box"], float)
    order = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    m1 = n - 1                                   # corner control points of the lattice (index i * n * n + j * n + k)
    q = np.array([lo + pts[i * m1 * n * n + j * m1 * n + k * m1] * (hi - lo) for i, j, k in order])
    C = np.asarray(mod["ctx_tm"], float)
    obj = (np.linalg.inv(C) @ np.c_[q, np.ones(8)].T).T[:, :3]
    vw = obj @ W[:3, :3].T + W[:3, 3]
    if not np.all(np.isfinite(vw)):
        return False
    cage = row.get("bbox")                       # where the cage is, or - without one - a piece of a room
    if cage:
        clo, chi = np.asarray(cage[0], float), np.asarray(cage[1], float)
        ext = np.maximum(chi - clo, 1e-6)
        c = (vw.min(0) + vw.max(0)) / 2.0
        if np.any(c < clo - 0.5 * ext.max()) or np.any(c > chi + 0.5 * ext.max()) or \
                vw[:, 2].max() < clo[2] or vw[:, 2].min() > chi[2]:
            return False
    elif vw[:, 2].min() * k < -50.0 or vw[:, 2].max() * k > 4500.0 or np.ptp(vw, axis=0).max() * k > 6000.0:
        return False
    faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    meshes[row["idx"]] = (row["name"], vw, MG.FaceList(faces, [0] * 6))
    row["bbox"] = [vw.min(0).tolist(), vw.max(0).tolist()]
    row["nverts"] = 8
    row["geom_notes"] = list(row.get("geom_notes") or []) + ["габарит - по решётке последнего FFD (сетка внутри не "
                                                             "вычислена)"]
    return True


def main(path, out, units=None, cut=1100.0, floor=0.0):
    import maxread as R
    import maxeval as EV
    import max_export as MX
    os.makedirs(out, exist_ok=True)
    ex = MX.load(path)                       # the scene as 3ds Max evaluates it (sda_export.ms), if it was run
    if ex is not None:
        print("выгрузка 3ds Max найдена: %s - геометрия после модификаторов, единицы %.3g мм" % (
            os.path.basename(MX.paths(path)[0]), ex.units_mm))
        units = units or next((u for u, v in UNIT_MM.items() if abs(v - ex.units_mm) < 1e-6), None)
    pending = []                             # nodes with modifiers: evaluated once the units are known
    mf = R.load(path)
    try:
        assets = R.asset_table(mf)
    except Exception:
        assets = {}
    tex_cache = {}
    cache = {}
    rows, meshes = [], {}
    for node in R.iter_nodes():
        name = R.node_name(node)
        loc, msh, mat, lyr = R.local_matrix(node)
        base = R.base_object(msh) if msh is not None else None
        cls = R.cls_name(base) if base is not None else None
        row = dict(idx=node.number, name=name, cls=cls, mods=R.modifiers(msh) if msh is not None else [],
                   material=R.mat_name(mat), layer=R.layer_name(lyr))
        try:                                 # node flags (chunk 0x0960: parent, flags); 0x100000 is set on every
            fch = node.get_first(0x0960)     # rendered object of the scenes seen - off: probably not rendered
            fb = bytes(fch.data) if fch is not None and not isinstance(fch.data, tuple) else b""
            if len(fb) >= 8:
                row["flags"] = struct.unpack_from("<I", fb, 4)[0]
                if cls not in SKIP_CLASSES and cls is not None and not row["flags"] & 0x100000:
                    row["render_off"] = True
        except Exception:
            pass
        if mat is not None and assets:          # texture files name what the material is (tile, plaster, brick)
            key = id(mat)
            if key not in tex_cache:
                try:
                    tex_cache[key] = [p.replace("\\", "/").split("/")[-3:] for p in R.mat_textures(mat, assets)][:12]
                except Exception:
                    tex_cache[key] = []
            if tex_cache[key]:
                row["tex"] = ["/".join(p) for p in tex_cache[key]]
        try:
            row["materials"] = R.mat_names(mat)
        except Exception:
            row["materials"] = [row["material"]] if row["material"] else []
        row["class"] = cls
        try:
            par = R.M.get_node_parent(node)
            row["parent"] = R.node_name(par) if par is not None and R.is_node(par) else None
        except Exception:
            row["parent"] = None
        try:
            W = np.array(R.world_matrix(node, cache) @ R.offset_matrix(node))
        except Exception as ex:
            row["err"] = repr(ex)
            rows.append(row)
            continue
        if base is not None and cls not in SKIP_CLASSES:
            prm = _pb2(base, R)
            if prm:
                row["prim"] = {str(k): round(v, 3) for k, v in prm.items()}
                fp = _footprint(cls, prm, W)
                if fp:
                    row["footprint"], row["z0"], row["z1"] = fp
            nd = ex.match(name, W[:3, 3]) if ex is not None else None
            if nd is not None:               # 3ds Max's own result: flags and the mesh after all modifiers
                row["geom"] = "export"
                row["export_h"] = nd.get("h")
                why = ex.skipped(nd)
                if why:
                    row["skip"] = why
                row["mods_on"] = ex.active_mods(nd)
                got = ex.mesh(nd)
                if got is not None and len(got[0]):
                    vw, ftri = got
                    row["bbox"] = [vw.min(0).tolist(), vw.max(0).tolist()]
                    row["nverts"] = int(len(vw))
                    meshes[row["idx"]] = (name, vw, ftri)
                    row.pop("footprint", None)   # the mesh is the truth, not the primitive
            else:
                try:
                    import maxstack as MS
                    pm = MS.editable_poly(base) if base.get_first(0x08FE) is not None else None
                    if pm is not None and len(pm["verts"]):      # dead elements dropped (L-105)
                        import maxgeom as MG
                        v = pm["verts"]
                        fl = MG.FaceList(pm["faces"], pm["mats"])
                    else:
                        v = R.poly_coords(base)
                        fl = R.poly_faces(base) if v is not None else []
                    if v is not None and len(v):
                        vw = v @ W[:3, :3].T + W[:3, 3]
                        row["bbox"] = [vw.min(0).tolist(), vw.max(0).tolist()]
                        row["nverts"] = int(len(v))
                        meshes[row["idx"]] = (name, vw, fl)
                except Exception as e_:
                    row["err"] = repr(e_)
                if row.get("mods") and msh is not None:
                    pending.append((row, msh, base, cls, W))
            if "FloorGenerator" in (row.get("mods") or []):
                fg = R.modifier_params(msh, "FloorGenerator")       # tile length (0) / width (4), scene units
                if fg.get(0) and fg.get(4):
                    row["fg_tile"] = [float(fg[0]), float(fg[4])]
            if cls == "Text":                    # a sign: its words and where it stands
                try:
                    font, txt = R.text_string(base)
                except Exception:
                    font, txt = None, None
                if txt:
                    row["text"], row["font"] = txt, font
                    row["pos"] = [float(v) for v in W[:3, 3]]
            if cls in ("SplineShape", "Line"):
                try:
                    lines = R.spline_lines(base)
                except Exception:
                    lines = []
                if lines and sum(len(p) for p, _ in lines) <= 4000:
                    pw = [(p @ W[:3, :3].T + W[:3, 3], cl) for p, cl in lines]
                    row["lines"] = [dict(p=[[float(q[0]), float(q[1])] for q in p], closed=cl) for p, cl in pw]
                    row["lines_z"] = float(np.mean([p[:, 2].mean() for p, _ in pw]))
        rows.append(row)
    u = units
    H = None
    if not u:
        u, H = guess_units(rows)
    else:
        _, H = guess_units(rows)
    k = UNIT_MM[u]
    for row, msh, base, cls, W in pending:  # what the modifiers did, without 3ds Max (L-099, L-105)
        full = _full_stack(R, msh, W, row, meshes)
        if full:
            continue
        try:
            evr = EV.evaluate(msh, R, base=base, cls=cls, W=W, unit_mm=k)
        except Exception as e_:
            evr = dict(status="unknown", notes=["модификаторы не разобраны (%r)" % (e_,)], verts=None)
        row["geom"] = evr["status"]
        row["geom_notes"] = evr["notes"]
        if evr.get("verts") is not None:
            vw = evr["verts"] @ W[:3, :3].T + W[:3, 3]
            if row.get("footprint"):
                from shapely.geometry import MultiPoint
                hull = MultiPoint([(float(a), float(b)) for a, b in vw[:, :2]]).convex_hull
                row["footprint"] = [list(c) for c in list(hull.exterior.coords)[:-1]] if hull.geom_type == "Polygon" else row["footprint"]
                row["z0"], row["z1"] = float(vw[:, 2].min()), float(vw[:, 2].max())
                row["replayed"] = True
        if evr["status"] == "unknown":
            row["note"] = "геометрия не проверена: %s - нужна выгрузка 3ds Max (scripts/max/sda_export.ms)" % (
                "; ".join(evr["notes"][-3:]) or ", ".join(row.get("mods") or []))
            _lattice_proxy(R, msh, W, row, meshes, k)
    for row in rows:
        if row.get("mods") and "bbox" not in row and not row.get("footprint") and row.get("class") not in SKIP_CLASSES \
                and row.get("geom") != "export" and "note" not in row:
            row["note"] = "геометрия не читается: модификаторы (%s) не вычисляются" % ", ".join(row["mods"])
    # convert to mm
    for r in rows:
        if r.get("bbox"):
            r["bbox"] = [[round(c * k, 1) for c in p] for p in r["bbox"]]
        if r.get("footprint"):
            r["footprint"] = [[round(x * k, 1), round(y * k, 1)] for x, y in r["footprint"]]
            r["z0"], r["z1"] = round(r["z0"] * k, 1), round(r["z1"] * k, 1)
        if r.get("prim"):
            r["prim_mm"] = {kk: round(vv * k, 1) for kk, vv in r["prim"].items()}
        if r.get("fg_tile"):
            r["fg_tile"] = [round(v * k, 1) for v in r["fg_tile"]]
        if r.get("pos"):
            r["pos"] = [round(v * k, 1) for v in r["pos"]]
        if r.get("lines"):
            for ln in r["lines"]:
                ln["p"] = [[round(x * k, 1), round(y * k, 1)] for x, y in ln["p"]]
            r["lines_z"] = round(r["lines_z"] * k, 1)
    json.dump(dict(source=os.path.basename(path), units=u, unit_mm=k, storey_guess=H, nodes=rows,
                   export=os.path.basename(MX.paths(path)[0]) if ex is not None else None),
              open(os.path.join(out, "inventory.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # sections
    cuts = {"floor": floor + 250.0, "cut": floor + cut, "ceiling": None}
    tops = [r["bbox"][1][2] for r in rows if r.get("bbox") and r["class"] not in SKIP_CLASSES]
    ceil = float(np.percentile(tops, 95)) - 60 if tops else floor + 2700
    if H:                                       # storey from the simple wall boxes (the unit vote) is more reliable
        ceil = min(ceil, H * k - 60) if H * k > 2000 else ceil
    cuts["ceiling"] = ceil
    sec = {}
    for key, h in cuts.items():
        sec[key] = dict(h=round(h, 1), objects={})
        for idx, (name, vw, faces) in meshes.items():
            vmm = vw * k
            if not (vmm[:, 2].min() <= h <= vmm[:, 2].max()):
                continue
            s = section(vmm, faces, h)
            if s:
                sec[key]["objects"]["%s#%d" % (name, idx)] = [[round(c, 1) for c in q] for q in s]
    json.dump(sec, open(os.path.join(out, "sections.json"), "w", encoding="utf-8"), ensure_ascii=False)
    for key in cuts:
        _plot(rows, sec[key], os.path.join(out, "plan_%s.png" % key), "%s: z = %.0f мм" % (key, sec[key]["h"]))
    _summary(rows, u, H, sec, os.path.join(out, "inventory.md"), path)
    slab = H * k if H and H * k > 2000 else None      # wall height of the scene = floor-to-slab
    live = [r for r in rows if not r.get("skip")]       # hidden / not rendered objects are not in the project
    d = _draft(live, os.path.join(out, "draft_project.json"), ceil, slab)
    _surfaces(live, meshes, k, d, out)
    _items(live, meshes, k, d, out)
    print("units:", u, "(guess from storey %s)" % (round(H, 1) if H else "-") if not units else "")
    print("nodes:", len(rows), " meshes:", len(meshes), " ->", out)
    meshes.clear()                              # the parsed .max (gigabytes) is not needed by the album build
    try:
        R.M.SCENE_LIST = None
    except Exception:
        pass
    import gc
    gc.collect()


def _plot(rows, sec, png, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    segs = [((q[0], q[1]), (q[2], q[3])) for s in sec["objects"].values() for q in s]
    fps = [r for r in rows if r.get("footprint")]
    pts = [p for s in segs for p in s] + [tuple(p) for r in fps for p in r["footprint"]]
    if not pts:
        return
    a = np.array(pts)
    # robust extent: centres of primitives and of mesh sections, outliers (ground planes, library objects parked
    # far away) dropped by percentiles; architectural primitives (walls as Plane/Box) define the flat best
    cen = [np.mean(r["footprint"], axis=0) for r in fps
           if max(np.ptp(np.array(r["footprint"]), axis=0)) < 20000]
    cen += [np.array(q).reshape(-1, 2).mean(0) for q in sec["objects"].values()]
    c = np.array(cen) if cen else a
    lo, hi = np.percentile(c, 4, axis=0) - 1500, np.percentile(c, 96, axis=0) + 1500
    span = max(hi - lo)
    fig, ax = plt.subplots(figsize=(16, min(30, 16 * (hi[1] - lo[1] + 1) / (hi[0] - lo[0] + 1) + 1)))
    ax.add_collection(LineCollection(segs, colors="k", linewidths=0.6))
    for r in fps:
        f = np.array(r["footprint"] + [r["footprint"][0]])
        ax.plot(f[:, 0], f[:, 1], color="#1f6fd0", lw=0.8, ls="--")
        c = f[:-1].mean(0)
        if lo[0] <= c[0] <= hi[0] and lo[1] <= c[1] <= hi[1]:
            ax.text(c[0], c[1], r["name"], fontsize=6, color="#1f6fd0", ha="center", clip_on=True)
    for name, s in sec["objects"].items():
        q = np.array(s).reshape(-1, 2)
        if len(q) > 6:
            c = q.mean(0)
            if lo[0] <= c[0] <= hi[0] and lo[1] <= c[1] <= hi[1]:
                ax.text(c[0], c[1], name.split("#")[0], fontsize=5, color="#b03030", ha="center", alpha=0.8, clip_on=True)
    step = 1000 if span < 25000 else 5000
    ax.set_xticks(np.arange(math.floor(lo[0] / step) * step, hi[0] + step, step))
    ax.set_yticks(np.arange(math.floor(lo[1] / step) * step, hi[1] + step, step))
    ax.grid(True, lw=0.3, alpha=0.5)
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_aspect("equal")
    ax.set_title(title + "   (сетка 1 м, синий пунктир - примитивы Plane/Box, красное - имена мешей)")
    fig.savefig(png, dpi=130, bbox_inches="tight")
    plt.close(fig)


def _summary(rows, u, H, sec, md, path):
    from collections import Counter
    c = Counter(r["class"] for r in rows)
    lines = ["# Инвентаризация сцены %s" % os.path.basename(path), "",
             "Единицы: **%s** (оценка по высоте этажа: %s). Если неверно - перезапустить с `--units`." % (u, round(H, 1) if H else "-"),
             "", "## Классы объектов", ""]
    for k, n in c.most_common():
        lines.append("- %s: %d" % (k, n))
    bad = [r for r in rows if r.get("note")]
    lines += ["", "## Геометрия не читается напрямую (%d)" % len(bad), "",
              "Модификаторы не вычисляются: размеры брать из параметров примитива (prim_mm), положение - из footprint, "
              "толщину / высоту - из соседних объектов или уточнить у заказчика.", ""]
    for r in bad[:80]:
        lines.append("- `%s` (%s, %s): prim_mm=%s" % (r["name"], r["class"], ", ".join(r["mods"]), r.get("prim_mm")))
    lines += ["", "## Разрезы", ""]
    for key, s in sec.items():
        lines.append("- %s (z = %.0f мм): объектов %d -> plan_%s.png" % (key, s["h"], len(s["objects"]), key))
    open(md, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def scene_objects(rows):
    """Inventory rows (mm) -> objects for scene_draft: plan rect, z range, flat primitive flag."""
    out = []
    for r in rows:
        if r["class"] in SKIP_CLASSES:
            continue
        if r.get("bbox"):
            (x0, y0, z0), (x1, y1, z1) = r["bbox"]
            flat = False
        elif r.get("footprint"):
            xs = [p[0] for p in r["footprint"]]
            ys = [p[1] for p in r["footprint"]]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            z0, z1 = r.get("z0", 0.0), r.get("z1", 0.0)
            flat = r["class"] == "Plane" or abs(z1 - z0) < 1
        else:
            continue
        out.append(dict(name=r.get("name") or "", parent=r.get("parent"), cls=r["class"], nverts=r.get("nverts"),
                        rect=(x0, y0, x1, y1), z0=z0, z1=z1, flat=flat, mods=r.get("mods") or []))
    return out


def _draft(rows, path, ceil, slab=None):
    """Walls, openings (doors / glazing in wall gaps), furniture by object names, named objects for room naming."""
    from importers import scene_draft
    objs = scene_objects(rows)
    d, shell = scene_draft.build(objs, ceil, path, png=os.path.join(os.path.dirname(path), "draft_plan.png"), slab=slab)
    return d


def _surfaces(rows, meshes, k, d, out):
    """Floor coverings (zones, tile formats) and boxes of the scene -> evidence for the senior."""
    from importers import scene_surfaces as SS
    try:
        fl = SS.floors(rows, meshes, k)
        outl = {}                            # plan outlines of tiled full-height solids (pipe boxes are not rectangles)
        for r in rows:
            if r.get("idx") in meshes and r.get("bbox") and (re.search(r"_FG\d", r.get("name") or "")
                                                             or SS.tex_info(r).get("kind") == "tile"):
                (x0, y0, z0), (x1, y1, z1) = r["bbox"]
                if z1 - z0 >= 2000 and z0 < 100:
                    _, vw, faces = meshes[r["idx"]]
                    try:
                        pg = SS.outline(np.asarray(vw, float) * k, faces, z0 + (z1 - z0) / 2.0)
                    except Exception:
                        pg = None
                    if pg:
                        outl[r["name"]] = pg
        bx = SS.boxes(rows, d.get("walls", []), d.get("_ledges", []), outlines=outl)
        wm = SS.wall_materials(rows, d.get("walls", []))
    except Exception as ex:                  # the album is still built: floors and boxes by norms
        print("surfaces: не собраны (%r)" % (ex,))
        return
    texts = [dict(name=r["name"], text=r["text"], font=r.get("font"), pos=r["pos"], parent=r.get("parent"),
                  light=any("LightMtl" in (m or "") or "neon" in (m or "").lower() for m in (r.get("materials") or [])))
             for r in rows if r.get("text") and r.get("pos")]
    p = os.path.join(out, "draft_project.json")
    dd = json.load(open(p, encoding="utf-8"))
    dd["_texts"] = d["_texts"] = texts
    dd["_floor_src"], dd["_box_src"], dd["_wall_mats"] = fl, bx, wm
    json.dump(dd, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    d["_floor_src"], d["_box_src"], d["_wall_mats"] = fl, bx, wm
    print("surfaces: покрытий пола %d (%s), коробов %d" % (
        len(fl), ", ".join("%s %s" % (f["material"], "×".join(map(str, f["tile"])) if f["tile"] else "-") for f in fl), len(bx)))


def _items(rows, meshes, k, d, out):
    """Furniture / decor items with their meshes (sheets «Мебель индивидуального изготовления»)."""
    from importers import scene_items
    try:
        items, signs = scene_items.collect(rows, meshes, k, d, out)
    except Exception as ex:                  # the album is still built without the items
        print("items: не собраны (%r)" % (ex,))
        return
    try:                                     # chandeliers and wall lights: sketches of their own
        lights = scene_items.collect_lights(rows, meshes, k, d, out, len(items))
    except Exception as ex:
        print("items: светильники не собраны (%r)" % (ex,))
        lights = []
    items = items + lights
    p = os.path.join(out, "draft_project.json")
    dd = json.load(open(p, encoding="utf-8"))
    dd["items"] = items
    if signs:
        dd["_signs"] = signs
    json.dump(dd, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("items:", len(items), "types,", sum(i["qty"] for i in items), "pcs")


if __name__ == "__main__":
    a = sys.argv[1:]
    kw = {}
    if "--units" in a:
        kw["units"] = a[a.index("--units") + 1]
    if "--cut" in a:
        kw["cut"] = float(a[a.index("--cut") + 1])
    if "--floor" in a:
        kw["floor"] = float(a[a.index("--floor") + 1])
    main(a[0], a[1], **kw)
