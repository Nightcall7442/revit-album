# -*- coding: utf-8 -*-
"""Calibration: the agent's own reading of a .max scene against 3ds Max's export of the same scene.

    python3 sda.py calibrate scene.max [report.json]

Needs <scene>.sda.json / .sda.bin next to the scene (scripts/max/sda_export.ms). For every object:
  - the node transform the parser builds against 3ds Max's node.transform;
  - the mesh the agent rebuilds from the saved modifier stack (maxstack + maxgeom) against 3ds Max's mesh -
    vertex by vertex (snapshotAsMesh keeps the MNMesh numbering), and as point sets when the numbering differs.
Statuses: exact | same_shape (numbering differs: an Edit Poly above would move the wrong vertices) | different |
count (vertex count differs) | not_rebuilt (the agent refuses - "не проверено" in the album) | plugin (the exporting
3ds Max had no such plugin). The worst cases and the stacks they share say what to teach the engine next (L-111).
"""
import collections
import json
import os
import sys

import numpy as np

TOL = 0.5          # mm


def _mm(ex):
    return float(ex.units_mm)


def _maxtm(nd):
    t = np.array(nd["tm"], float)
    M = np.eye(4)
    M[:3, :3] = t[:3].T
    M[:3, 3] = t[3]
    return M


def compare(ours, theirs, k):
    """-> (status, error mm). ours / theirs: N x 3 world, system units; k: mm per unit."""
    if len(ours) != len(theirs):
        return "count", None
    if not len(ours):
        return "exact", 0.0
    e = float(np.abs(ours - theirs).max()) * k
    if e <= TOL:
        return "exact", e
    from scipy.spatial import cKDTree
    d1, _ = cKDTree(theirs).query(ours)
    d2, _ = cKDTree(ours).query(theirs)
    e2 = float(max(d1.max(), d2.max())) * k
    return ("same_shape", e2) if e2 <= TOL else ("different", e2)


def run(path, out=None, say=print):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import maxread as R
    import maxstack as MS
    import maxgeom as MG
    import max_export as MX
    ex = MX.load(path)
    if ex is None:
        raise SystemExit("нет выгрузки 3ds Max рядом со сценой: %s (scripts/max/sda_export.ms)" % MX.paths(path)[0])
    k = _mm(ex)
    R.load(path)
    cache = {}
    used = set()
    rows = []
    for node in R.iter_nodes():
        name = R.node_name(node)
        cands = [nd for nd in ex.by_name.get(name, []) if nd.get("h") not in used]
        if not cands:
            continue
        try:
            loc, msh, mat, lyr = R.local_matrix(node)
            Wn = np.array(R.world_matrix(node, cache))
            W = Wn @ np.array(R.offset_matrix(node))
        except Exception as e_:
            rows.append(dict(name=name, status="transform", note=repr(e_)[:120]))
            continue
        nd = min(cands, key=lambda c: float(np.abs(_maxtm(c) - Wn).max()))
        row = dict(name=name, idx=node.number, h=nd.get("h"), cls=nd.get("cls"),
                   tm_err=round(float(np.abs(_maxtm(nd)[:3, 3] - Wn[:3, 3]).max()) * k, 2),
                   rot_err=round(float(np.abs(_maxtm(nd)[:3, :3] - Wn[:3, :3]).max()), 5))
        same = [c for c in cands if np.abs(_maxtm(c) - Wn).max() < 1e-4]
        if msh is None or MX.Export.missing(nd) or not nd.get("mesh") or nd.get("sup") != "GeometryClass":
            if MX.Export.missing(nd):
                row["status"] = "plugin"
            elif nd.get("sup") == "GeometryClass" and nd.get("cls") != "Targetobject":
                row["status"] = "no_mesh"
            else:
                row["status"] = "not_geometry"
            used.add(nd.get("h"))
            rows.append(row)
            continue
        try:
            row["mods"] = R.modifiers(msh)
            st = MS.read(R, msh)
            m, log = MG.evaluate(st)
            ours = (W[:3, :3] @ m.v.T).T + W[:3, 3] if len(m.v) else np.zeros((0, 3))
        except Exception as e_:
            row["status"] = "not_rebuilt"
            row["note"] = str(e_)[:160]
            used.add(nd.get("h"))
            rows.append(row)
            continue
        best = None
        for c in (same or [nd]):     # coincident copies of one name: the one this mesh is
            got = ex.mesh(c)
            theirs = got[0] if got is not None else np.zeros((0, 3))
            st_, err = compare(ours, theirs, k)
            rank = ("exact", "same_shape", "different", "count").index(st_)
            if best is None or (rank, err or 0) < (best[0], best[1] or 0):
                best = (rank, err, st_, c, len(theirs))
        row.update(status=best[2], err=None if best[1] is None else round(best[1], 2), h=best[3].get("h"),
                   n_ours=int(len(ours)), n_max=int(best[4]))
        used.add(best[3].get("h"))
        rows.append(row)
    stat = collections.Counter(r["status"] for r in rows)
    tm_bad = [r for r in rows if r.get("tm_err", 0) > TOL or r.get("rot_err", 0) > 1e-3]
    by_stack = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.get("mods") is not None:
            by_stack[" > ".join(reversed(r["mods"])) or "-"][r["status"]] += 1
    rep = dict(scene=os.path.basename(path), tolerance_mm=TOL, statuses=dict(stat), transforms_wrong=len(tm_bad),
               stacks={s: dict(c) for s, c in sorted(by_stack.items(), key=lambda kv: -sum(kv[1].values()))},
               worst=sorted([r for r in rows if r["status"] in ("different", "same_shape", "count")],
                            key=lambda r: -(r.get("err") or 1e9))[:60],
               transforms=[dict(name=r["name"], tm_err=r["tm_err"], rot_err=r["rot_err"]) for r in tm_bad][:60],
               not_rebuilt=collections.Counter((r.get("note") or "")[:70] for r in rows
                                               if r["status"] == "not_rebuilt").most_common(40))
    if out:
        json.dump(dict(rep, rows=rows), open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    say("сверка с 3ds Max: %s" % ", ".join("%s %d" % kv for kv in stat.most_common()))
    say("трансформации не совпали: %d" % len(tm_bad))
    for r in rep["worst"][:15]:
        say("  %-12s %-40s %s мм  (%s)" % (r["status"], r["name"][:40], r.get("err"), " > ".join(reversed(r.get("mods") or []))))
    return rep


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
