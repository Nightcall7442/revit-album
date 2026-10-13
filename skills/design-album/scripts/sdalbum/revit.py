# -*- coding: utf-8 -*-
"""project.json -> native Revit model builder (pyRevit / RevitPythonShell script + Dynamo graphs).

    python3 sda.py revit project.json OUT

OUT/revit_build_model.py          run in pyRevit / RevitPythonShell (Revit 2022-2027)
OUT/<name>_Revit.dyn              Dynamo, Python engine PythonNet3 (Revit 2025+)
OUT/<name>_Revit_CPython3.dyn     Dynamo, CPython3 engine (Revit 2022-2024)

Walls are created on their centre lines with types per (kind, thickness); openings as family types per mark with
width / height / sill; doors are oriented by `swing` / `hinge`; rooms by seeds + separation lines; plan 1:50,
two sections, schedules and sheets. The template is tested against tests/mock_revit.py (tests/test_revit.py).
"""
import json
import os
import pprint
import re
import uuid

from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))


def _centerline(w):
    x0, y0, x1, y1 = w["shape"].bounds
    if w.get("a") and w.get("b") and w.get("t"):
        return list(map(float, w["a"])), list(map(float, w["b"])), float(w["t"])
    if w["dir"] == "H":
        yc = (y0 + y1) / 2.0
        return [x0, yc], [x1, yc], y1 - y0
    xc = (x0 + x1) / 2.0
    return [xc, y0], [xc, y1], x1 - x0


def data(P):
    outline = unary_union([Polygon(g.exterior) for g in (P.mass.geoms if hasattr(P.mass, "geoms") else [P.mass])])
    wall_types, walls, skipped = {}, [], []
    for w in P.walls:
        if w["kind"] == "box":
            continue
        x0, y0, x1, y1 = w["shape"].bounds
        if abs(w["shape"].area - (x1 - x0) * (y1 - y0)) > 0.02 * w["shape"].area:
            skipped.append(w["id"])          # non-rectangular outline: model by hand / split into rect walls
            continue
        a, b, t = _centerline(w)
        bearing = w["kind"] == "existing"
        ext = w["shape"].buffer(5).intersects(outline.exterior) and bearing
        key = "%s%d%s" % ("W" if bearing else "P", round(t), "e" if ext else "")
        if key not in wall_types:
            name = ("Стена наружная %d" if ext else "Стена несущая %d" if bearing else "Перегородка %d") % round(t)
            wall_types[key] = dict(name=name, t=round(t), load_bearing=bearing, ext=ext)
        walls.append(dict(id=w["id"], type=key, a=[round(v, 1) for v in a], b=[round(v, 1) for v in b],
                          src=str(w.get("source", w.get("material", "project.json")))))
    x0, y0, x1, y1 = P.bounds
    grids = []
    for name, x in P.grid.get("x", []):
        grids.append(dict(name=name, a=(x, y0 - 1500), b=(x, y1 + 1500)))
    for name, y in P.grid.get("y", []):
        grids.append(dict(name=name, a=(x0 - 1500, y), b=(x1 + 1500, y)))
    wall_ids = {w["id"] for w in walls}
    openings = []
    for o in P.openings:
        if o["wall"] not in wall_ids or o["kind"] == "passage":
            continue
        openings.append(dict(id=o["id"], mark=o.get("mark") or o["id"], kind=o["kind"], wall=o["wall"], c=o["c"],
                             w=o["w"], h=o["h"], sill=o.get("sill", 0 if o["kind"] != "window" else 900),
                             swing=tuple(o.get("swing", (0, 0))), hinge=o.get("hinge", "min"),
                             src=str(o.get("source", ""))))
    types = {}
    for o in openings:
        t = P.opening_types.get(o["mark"], {})
        types[o["mark"]] = dict(name=t.get("name", "%s %dx%d" % (o["mark"], o["w"], o["h"])))
    rooms = [dict(num=r["num"], name=r["name"], seed=list(r["shp"].representative_point().coords)[0] if not r.get("seed")
                  else r["seed"], area=r["area"]) for r in P.rooms]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    sections = [dict(name="Разрез 1-1", origin=(cx, y0 + (y1 - y0) * 0.45), dir=(0, 1), half_w=(x1 - x0) / 2 + 600,
                     depth=(y1 - y0) * 0.6),
                dict(name="Разрез 2-2", origin=(x0 + (x1 - x0) * 0.45, cy), dir=(-1, 0), half_w=(y1 - y0) / 2 + 600,
                     depth=(x1 - x0) * 0.5)]
    code = re.sub(r"[^A-ZА-Я0-9]", "", P.meta.get("object", "АР").upper())[:6] or "АР"
    return dict(project=dict(object=P.meta.get("object", "Квартира"), code=P.meta.get("code", "%s-АР" % code)),
                level_name="Этаж 1", wall_h=P.slab, wall_types=wall_types, walls=walls, grids=grids,
                openings=openings, opening_types=types,
                separations=[[list(a), list(b)] for a, b in P.separations],
                rooms=rooms, sections=sections, skipped_walls=skipped)


def album_manifest(album_dxf, out):
    """Flatten every album sheet to out/ДП_NN.dxf, copy the raster images (logos, axonometry) and list their
    placement on the sheet (mm). Images are not part of a CAD import, Revit places them separately."""
    import shutil
    import ezdxf
    from .flatten import flatten_album
    sheets = []
    src = ezdxf.readfile(album_dxf)
    base = os.path.dirname(os.path.abspath(album_dxf))
    imgs = {}
    for name in src.layouts.names_in_taborder():
        if name == "Model" or not name[:2].isdigit():
            continue
        lst = []
        for e in src.layouts.get(name):
            if e.dxftype() != "IMAGE":
                continue
            fn = e.image_def.dxf.filename
            w = e.dxf.u_pixel.magnitude * e.dxf.image_size.x
            lst.append(dict(file=fn, x=round(e.dxf.insert.x, 3), y=round(e.dxf.insert.y, 3), w=round(w, 3)))
            if fn not in imgs and os.path.isfile(os.path.join(base, fn)):
                shutil.copy(os.path.join(base, fn), os.path.join(out, fn))
                imgs[fn] = True
        imgs_ok = [i for i in lst if i["file"] in imgs]
        sheets.append(dict(no=int(name[:2]), title=name[3:].strip(), images=imgs_ok))
    flat = {no: p for no, _, p in flatten_album(album_dxf, out)}
    for sh in sheets:
        sh["dxf"] = os.path.basename(flat[sh["no"]])
    return sheets


def export(P, out, album_dxf=None, target_dir=None):
    """target_dir - where the files will lie on the user's computer (Windows path), written into the script."""
    os.makedirs(out, exist_ok=True)
    d = data(P)
    if album_dxf:
        d["album"] = dict(dir=target_dir or os.path.abspath(out), prefix="ДП", sheets=album_manifest(album_dxf, out))
    tpl = open(os.path.join(HERE, "revit_template.py"), encoding="utf-8").read()
    code = tpl.replace("__DATA__", pprint.pformat(d, width=120, sort_dicts=False))
    py = os.path.join(out, "revit_build_model.py")
    open(py, "w", encoding="utf-8").write(code)
    stem = re.sub(r"[^\wА-Яа-я]+", "_", P.meta.get("object", "Проект"))[:40].strip("_") or "Проект"
    paths = [py]
    for suffix, engine in (("", "PythonNet3"), ("_CPython3", "CPython3")):
        p = os.path.join(out, "%s_Revit%s.dyn" % (stem, suffix))
        _dyn(p, code, engine, P.meta.get("object", "Проект"))
        paths.append(p)
    if d["skipped_walls"]:
        print("ВНИМАНИЕ: непрямоугольные стены не переданы в Revit:", ", ".join(d["skipped_walls"]))
    return paths


def _dyn(path, code, engine, title):
    hx = lambda: uuid.uuid4().hex  # noqa: E731
    py_id, out_port, watch_id, w_in, w_out = hx(), hx(), hx(), hx(), hx()
    port = dict(UsingDefaultValue=False, Level=2, UseLevels=False, KeepListStructure=False)
    dyn = {
        "Uuid": str(uuid.uuid4()), "IsCustomNode": False, "Description": "Построение модели (АР): %s" % title,
        "Name": "АР_Revit", "ElementResolver": {"ResolutionMap": {}}, "Inputs": [], "Outputs": [],
        "Nodes": [
            {"ConcreteType": "PythonNodeModels.PythonNode, PythonNodeModels", "Code": code, "Engine": engine,
             "EngineName": engine, "VariableInputPorts": True, "Id": py_id, "NodeType": "PythonScriptNode",
             "Inputs": [], "Outputs": [dict(Id=out_port, Name="OUT", Description="Result of the python script", **port)],
             "Replication": "Disabled", "Description": "Runs an embedded Python script."},
            {"ConcreteType": "CoreNodeModels.Watch, CoreNodeModels", "WatchWidth": 520.0, "WatchHeight": 420.0,
             "Id": watch_id, "NodeType": "ExtensionNode",
             "Inputs": [dict(Id=w_in, Name="", Description="Node to show output from", **port)],
             "Outputs": [dict(Id=w_out, Name="", Description="Node output", **port)],
             "Replication": "Disabled", "Description": "Visualizes a node's output"}],
        "Connectors": [{"Start": out_port, "End": w_in, "Id": hx(), "IsHidden": "False"}],
        "Dependencies": [], "NodeLibraryDependencies": [], "Thumbnail": "", "GraphDocumentationURL": None,
        "ExtensionWorkspaceData": [], "Author": "Space Design Album agent",
        "Linting": {"activeLinter": "None", "activeLinterId": "7b75fb44-43fd-4631-a878-29f4d5d8399a", "warningCount": 0,
                    "errorCount": 0},
        "Bindings": [],
        "View": {"Dynamo": {"ScaleFactor": 1.0, "HasRunWithoutCrash": True, "IsVisibleInDynamoLibrary": True,
                            "Version": "2.19.0.0", "RunType": "Manual", "RunPeriod": "1000"},
                 "Camera": {"Name": "Background Preview", "EyeX": -17.0, "EyeY": 24.0, "EyeZ": 50.0, "LookX": 12.0,
                            "LookY": -13.0, "LookZ": -58.0, "UpX": 0.0, "UpY": 1.0, "UpZ": 0.0},
                 "ConnectorPins": [],
                 "NodeViews": [{"Id": py_id, "Name": "АР: построение модели", "IsSetAsInput": False, "IsSetAsOutput": False,
                                "Excluded": False, "ShowGeometry": True, "X": 100.0, "Y": 200.0},
                               {"Id": watch_id, "Name": "Журнал построения", "IsSetAsInput": False, "IsSetAsOutput": False,
                                "Excluded": False, "ShowGeometry": True, "X": 520.0, "Y": 200.0}],
                 "Annotations": [], "X": 0.0, "Y": 0.0, "Zoom": 1.0},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dyn, fh, ensure_ascii=False, indent=2)
