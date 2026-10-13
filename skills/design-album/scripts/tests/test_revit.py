# -*- coding: utf-8 -*-
"""The generated Revit builder must run end-to-end against the behavioural Revit API mock (no Revit here):
every wall / opening / room of project.json is created and doors open to the side the project says."""
import os
import sys
import types

import pytest

from conftest import URGENCH, STUDIO, HERE


@pytest.mark.parametrize("path", [URGENCH, STUDIO], ids=["urgench", "studio"])
def test_revit_builder_runs_in_mock(path, tmp_path):
    from sdalbum import model, revit
    P = model.load(path)
    paths = revit.export(P, str(tmp_path))
    assert len(paths) == 3 and all(os.path.getsize(p) > 1000 for p in paths)
    sys.path.insert(0, HERE)
    import mock_revit as MR
    MR.install()
    MR._Create.ROOMS = [(r["shp"], r["area_exact"]) for r in P.rooms]
    doc = MR.Document()
    rv = types.SimpleNamespace(ActiveUIDocument=types.SimpleNamespace(Document=doc))
    g = {"__revit__": rv, "__name__": "__main__"}
    src = open(paths[0], encoding="utf-8").read()
    exec(compile(src, "revit_build_model.py", "exec"), g)
    log = g["OUT"]
    assert "Готово" in log
    assert "ОШИБКА" not in log, log[-2000:]
    assert "Помещения" in log or "помещени" in log
    D = revit.data(P)
    walls = [e for e in doc.elements if type(e).__name__ == "Wall"]
    insts = [e for e in doc.elements if type(e).__name__ == "FamilyInstance"]
    assert len(walls) == len(D["walls"])
    assert len(insts) == len(D["openings"])
    assert not D["skipped_walls"]


def test_revit_album_sheets_in_mock(tmp_path):
    """--album: every album sheet becomes a Revit sheet with its flat DXF imported and its images placed."""
    from sdalbum import album, model, revit
    A = album.build(STUDIO, str(tmp_path / "alb"), ["cover", "general", "measured", "openings"])
    A.save_dxf(str(tmp_path / "alb" / "album.dxf"))
    P = model.load(STUDIO)
    out = tmp_path / "rv"
    paths = revit.export(P, str(out), album_dxf=str(tmp_path / "alb" / "album.dxf"))
    sys.path.insert(0, HERE)
    import mock_revit as MR
    MR.install()
    MR._Create.ROOMS = [(r["shp"], r["area_exact"]) for r in P.rooms]
    doc = MR.Document()
    rv = types.SimpleNamespace(ActiveUIDocument=types.SimpleNamespace(Document=doc))
    g = {"__revit__": rv, "__name__": "__main__"}
    exec(compile(open(paths[0], encoding="utf-8").read(), "revit_build_model.py", "exec"), g)
    assert "ОШИБКА" not in g["OUT"], g["OUT"][-1500:]
    sheets = [e for e in doc.elements if type(e).__name__ == "ViewSheet" and getattr(e, "imports", None)]
    assert len(sheets) == 4
    assert all(len(s.imports) == 1 for s in sheets)
    assert sum(len(s.images) for s in sheets) >= 4        # logos in stamps + cover logo + axonometry
    assert "Альбом ДП: листов 4 из 4" in g["OUT"]
