# -*- coding: utf-8 -*-
"""Lighting of the reference album (marking, schedule, bindings, switches) and sockets with «Н= … мм»."""
import pytest

from conftest import URGENCH


def test_heads_of_one_module_are_one_fixture():
    from sdalbum.senior import _merge_heads
    row = [dict(kind="surface", x=1600, y=2425 - i * 108, group="Зал") for i in range(3)]
    other = [dict(kind="surface", x=3600, y=2425, group="Зал")]
    out = _merge_heads(row + other)
    assert len(out) == 2
    m = next(o for o in out if o.get("heads"))
    assert m["heads"] == 3 and abs(m["y"] - 2317) <= 5          # centre of the row (snapped to 5 mm)


def test_chandeliers_and_wall_lights_of_the_items_go_on_the_plan():
    from sdalbum import model
    from sdalbum.senior import _lights_of_items
    import json
    d = json.load(open(URGENCH, encoding="utf-8"))
    P = model.Project(d, ".")
    r = P.rooms[0]
    x0, y0, x1, y1 = r["shp"].bounds
    d["items"] = [dict(kind="chandelier", size=[800, 800, 600], z0=2300, places=[[(x0 + x1) / 2, (y0 + y1) / 2, 0]],
                       name="Люстра", pos="М-1"),
                  dict(kind="sconce", size=[200, 200, 400], z0=1500, places=[[x0 + 60, (y0 + y1) / 2, 0]],
                       name="Бра", pos="М-2")]
    out = _lights_of_items(d, P, [])
    kinds = sorted(o["kind"] for o in out)
    assert kinds == ["chandelier", "wall"]
    wl = next(o for o in out if o["kind"] == "wall")
    assert wl["h"] == 1700 and abs(wl["x"] - x0) < 5            # on the wall face, centre at z0 + h/2


def test_light_marks_by_prefix(urgench):
    from sdalbum.sheets_light import light_types
    marks = [t["mark"] for t in light_types(urgench)]
    assert "СВ-1" in marks and any(m.startswith("ТР-") for m in marks) and any(m.startswith("П-") for m in marks)
    assert len(marks) == len(set(marks))


def test_lighting_sheets_build_clean(tmp_path):
    from sdalbum import album, model, qa
    A = album.Album(model.load(URGENCH), str(tmp_path), ["lighting_marks", "lighting_schedule", "lighting", "switches", "sockets"])
    titles = [t for _, _, t, *_ in A.sheets]
    assert titles == ["План освещения. Маркировка", "Ведомость светильников", "План освещения. Привязки",
                      "План выключателей и групп", "План розеток и электровыводов"]
    A.build()
    rep = qa.check_doc(A.doc)
    assert not [i for v in rep.values() for i in v if i["level"] == "error"]
    txt = [e.dxf.text for b in A.doc.blocks for e in b if e.dxftype() == "TEXT"]
    txt += [e.dxf.text for no in A.layouts for e in A.layouts[no] if e.dxftype() == "TEXT"]
    assert any(t.startswith("Н= ") and " мм" in t for t in txt)              # socket heights «Н= 300 мм»
    assert "* Ведомость светильников" in txt
