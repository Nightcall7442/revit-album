# -*- coding: utf-8 -*-
"""One command from any input (sdalbum/pipeline.py): DXF / PDF / project.json -> album + report; raster input ->
an honest 'needs digitising'; a second run keeps the user's edits."""
import json
import os
import shutil

import pytest

from conftest import STUDIO


@pytest.mark.slow
def test_make_from_dxf_gives_full_album(tmp_path):
    from sdalbum import pipeline
    from test_importers import _plan_dxf
    src = str(tmp_path / "plan.dxf")
    _plan_dxf(src)
    rep = pipeline.make(src, str(tmp_path / "out"), png=False, say=lambda *a: None)
    assert rep["status"] == "ok", rep
    titles = " ".join(rep["sheets"])
    for t in ("Обмерный план", "План освещения", "План розеток", "План полов", "Ведомость заполнения проёмов"):
        assert t in titles
    md = open(tmp_path / "out" / "report.md", encoding="utf-8").read()
    assert "Вопросы к заказчику" in md and "Проектное предложение" in md
    assert os.path.isfile(tmp_path / "out" / "album.pdf")


def test_make_raster_asks_for_digitising(tmp_path):
    from PIL import Image
    from sdalbum import pipeline
    src = str(tmp_path / "photo.jpg")
    Image.new("RGB", (400, 300), "white").save(src)
    rep = pipeline.make(src, str(tmp_path / "out"), say=lambda *a: None)
    assert rep["status"] == "digitize"
    assert "оцифровка" in open(tmp_path / "out" / "report.md", encoding="utf-8").read()


def test_folder_input_prefers_project_json(tmp_path):
    from sdalbum import pipeline
    shutil.copy(STUDIO, tmp_path / "project.json")
    (tmp_path / "notes.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "scan.png").write_bytes(b"x")
    assert pipeline.pick_input(str(tmp_path)).endswith("project.json")


@pytest.mark.slow
def test_second_run_keeps_user_edits(tmp_path):
    from sdalbum import history, pipeline
    out = str(tmp_path / "out")
    pipeline.make(STUDIO, out, png=False, sheets=["measured"], say=lambda *a: None)
    proj = os.path.join(out, "project.json")
    d = history.load(proj)
    d["meta"]["place"] = "Ташкент"
    history.save(proj, d, "правка пользователя")
    rep = pipeline.make(STUDIO, out, png=False, sheets=["measured"], say=lambda *a: None)
    assert history.load(proj)["meta"]["place"] == "Ташкент"
    assert any("сохранена" in n for n in rep["notes"])
