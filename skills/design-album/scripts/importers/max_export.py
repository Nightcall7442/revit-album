# -*- coding: utf-8 -*-
"""The scene as 3ds Max evaluates it: <scene>.sda.json + <scene>.sda.bin written by scripts/max/sda_export.ms.

Reading a .max file directly gives base objects and primitive parameters; modifiers (Edit Poly, Symmetry, FFD, Shell,
FloorGenerator) are not evaluated. The export carries every object's world mesh AFTER its modifiers, its flags
(hidden, frozen, renderable, layer) and exact system units - the ground truth the album is checked against.

    load(max_path) -> Export | None
    Export.units_mm               mm per system unit (exact, no guessing)
    Export.nodes                  [{h, n, p, cls, top, mods, hidden, node_hidden, frozen, renderable, layer, ..., bb, mesh}]
    Export.mesh(node)             (verts N x 3 in system units, faces [(matid, [a, b, c])]) or None
    Export.match(name, pivot)     the export node of a .max row (same name, nearest pivot)
    Export.skipped(node)          reason the object is not in the renders (hidden / not renderable / layer) or None
    Export.missing(node)          plugin classes 3ds Max did not have when exporting ("Missing_OSM" ...): mesh not valid
    Export.hidden_ignored         most of the scene was hidden at save: "hidden" is a working state, not a decision
"""
import json
import os
import re

import numpy as np


def paths(max_path):
    base = os.path.splitext(max_path)[0]
    return base + ".sda.json", base + ".sda.bin"


class Export:
    def __init__(self, jpath, bpath):
        with open(jpath, encoding="utf-8-sig") as f:
            txt = f.read()
        # 3ds Max 2024+ returns ftell as Integer64 and prints it as "123L" (sda_export.ms before 1.6.1 wrote it so)
        txt = re.sub(r'("mesh":\[)(\d+)L,', r"\1\2,", txt)
        self.data = json.loads(txt)
        if self.data.get("format") != "sda-export":
            raise ValueError("%s: не выгрузка sda_export.ms" % jpath)
        self.bpath = bpath
        self.units_mm = float(self.data["units"]["mm_per_unit"])
        self.nodes = self.data["nodes"]
        self.by_name = {}
        for nd in self.nodes:
            self.by_name.setdefault(nd["n"], []).append(nd)
        self._bin = None
        # objects hidden at save time: a few hidden ones are variants left out of the project; most of the scene
        # hidden (Sherov: 1548 of 1609, only the cameras shown) is the designer's working state, not a decision (L-110)
        geo = [nd for nd in self.nodes if nd.get("mesh") and nd.get("sup") != "camera" and nd.get("cls") != "Targetobject"]
        hid = [nd for nd in geo if nd.get("node_hidden") or nd.get("hidden")]
        self.hidden_ignored = bool(geo) and len(hid) * 2 >= len(geo)
        self.hidden_count = len(hid)

    def _blob(self):
        if self._bin is None:
            self._bin = np.memmap(self.bpath, dtype=np.uint8, mode="r")
        return self._bin

    def mesh(self, nd):
        """-> (verts N x 3, faces) or None. Faces: a TriList (iterates as (mat id, [a, b, c]); .tris is the array) -
        the whole scene is millions of triangles (L-110). Big meshes keep float32 vertices."""
        m = nd.get("mesh")
        if not m:
            return None
        try:
            import maxgeom as MG
        except ImportError:
            from importers import maxgeom as MG
        off, nv, nf = int(m[0]), int(m[1]), int(m[2])
        b = self._blob()
        v = np.frombuffer(b, dtype="<f4", count=nv * 3, offset=off).reshape(-1, 3)
        v = v.astype(np.float32 if nv > 20000 else np.float64)
        o2 = off + nv * 12
        f = np.frombuffer(b, dtype="<i4", count=nf * 3, offset=o2).reshape(-1, 3)
        o3 = o2 + nf * 12
        mid = np.frombuffer(b, dtype="<u2", count=nf, offset=o3)
        return v, MG.TriList(f, mid.astype(np.int32))

    def match(self, name, pivot=None, used=None):
        """The export node of a .max node: same name, nearest pivot; with `used` (handles already given to other
        nodes) two copies standing in one place get the two export nodes, not one of them twice (L-111: Sherov
        pCube1 - two coincident copies with different Edit Poly data)."""
        cand = self.by_name.get(name) or []
        if used is not None:
            cand = [nd for nd in cand if nd.get("h") not in used] or cand
        if len(cand) <= 1 or pivot is None:
            got = cand[0] if cand else None
        else:
            p = np.asarray(pivot[:3], float)
            got = min(cand, key=lambda nd: float(np.linalg.norm(np.asarray(nd["tm"][3], float) - p)))
        if got is not None and used is not None:
            used.add(got.get("h"))
        return got

    @staticmethod
    def missing(nd):
        """Plugins the 3ds Max that wrote the export did not have (FloorGenerator, Corona ...): the class is
        "Missing_*" and the object / modifier did nothing there - the mesh is not the designer's (L-110)."""
        got = []
        for c in (nd.get("cls"), nd.get("top")):
            if c and str(c).startswith("Missing_") and c not in got:
                got.append(c)
        for m in nd.get("mods") or []:
            if str(m[0]).startswith("Missing_") and m[0] not in got:
                got.append(m[0])
        return got

    def skipped(self, nd):
        if (nd.get("node_hidden") or nd.get("hidden")) and not self.hidden_ignored:
            return "скрыт в сцене"
        if nd.get("layer_hidden"):
            return "слой «%s» скрыт" % nd.get("layer")
        if nd.get("renderable") is False or nd.get("layer_renderable") is False:
            return "не рендерится (Renderable выключен)"
        return None

    @staticmethod
    def bbox(nd):
        (x0, y0, z0), (x1, y1, z1) = nd["bb"]
        return [[x0, y0, z0], [x1, y1, z1]]

    @staticmethod
    def active_mods(nd):
        return [m[0] for m in nd.get("mods") or [] if m[2]]


def load(max_path):
    j, b = paths(max_path)
    if os.path.isfile(j) and os.path.isfile(b):
        return Export(j, b)
    return None


def write_fixture(path_json, path_bin, nodes, meshes, mm_per_unit=10.0):
    """Tests: an export file pair. nodes: list of dicts (n, cls, bb, tm, ...); meshes: {name: (verts, tris)}."""
    with open(path_bin, "wb") as fb:
        for nd in nodes:
            m = meshes.get(nd["n"])
            if m is None:
                nd["mesh"] = None
                continue
            v, t = np.asarray(m[0], "<f4"), np.asarray(m[1], "<i4")
            off = fb.tell()
            fb.write(v.tobytes())
            fb.write(t.tobytes())
            fb.write(np.zeros(len(t), "<u2").tobytes())
            nd["mesh"] = [off, len(v), len(t)]
    data = dict(format="sda-export", version=1, scene="test.max", units=dict(system="#centimeters", scale=1.0,
                                                                              mm_per_unit=mm_per_unit), nodes=nodes)
    with open(path_json, "w", encoding="utf-8") as fj:
        json.dump(data, fj, ensure_ascii=False)
