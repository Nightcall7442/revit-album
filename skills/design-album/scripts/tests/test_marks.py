# -*- coding: utf-8 -*-
"""Marks of finishes as on the reference album (КР, ОБ, ОТ, З, ПЛ, НП, ПО ...)."""
from sdalbum import marks as MK


def test_prefix_by_material():
    assert MK.wall_prefix("Окраска интерьерной матовой краской") == "КР"
    assert MK.wall_prefix("Обои флизелиновые") == "ОБ"
    assert MK.wall_prefix("Стеновые панели шпон дуба") == "ОТ"
    assert MK.wall_prefix("Зеркало серебро 4 мм") == "З"
    assert MK.wall_prefix("Керамогранит 600×1200") == "ПЛ"
    assert MK.wall_prefix("", kind="plaster") == "ДШ"
    assert MK.floor_prefix("Паркетная доска дуб") == "НП"
    assert MK.floor_prefix("Ламинат", "plank") == "НП"
    assert MK.floor_prefix("Керамогранит 600×600", "tile") == "ПЛ"


def test_numbers_run_within_a_prefix():
    ex = [dict(id="КР-1"), dict(id="ПЛ-1")]
    assert MK.wall_id(ex, "краска") == "КР-2"
    assert MK.wall_id(ex, "плитка") == "ПЛ-2"
    assert MK.wall_id(ex, "обои") == "ОБ-1"
    assert MK.ceiling_id([]) == "ПО-1"


def test_proposed_types_get_reference_marks():
    import json
    import os
    from conftest import URGENCH
    from sdalbum import propose
    d = json.load(open(URGENCH, encoding="utf-8"))
    for key in ("floors", "finishes", "ceilings"):
        d.pop(key, None)
    for r in d["rooms"]:
        r.pop("ceiling_type", None)
    d2, log = propose.propose(d, os.path.dirname(URGENCH))
    ids = [t["id"] for t in d2["finishes"]["types"]] + [f["id"] for f in d2["floors"]] + [t["id"] for t in d2["ceilings"]["types"]]
    assert {"КР-1", "ПЛ-1", "ПО-1", "НП-1"} <= set(ids), ids
    assert all(r["ceiling_type"].startswith("ПО-") for r in d2["rooms"])


def test_rounded_mark_frame():
    import ezdxf
    from sdalbum import symbols as Y
    d = ezdxf.new()
    g = Y.tag_box(d.modelspace(), "КР-1", (0, 0), 1.0, rounded=True)
    sq = Y.tag_box(d.modelspace(), "КР-1", (0, 0), 1.0)
    assert g.area < sq.area and g.bounds[2] - g.bounds[0] == sq.bounds[2] - sq.bounds[0]


def test_schedule_cells_take_symbols_and_star_footnote():
    import ezdxf
    from sdalbum import gfx as S
    d = ezdxf.new()
    psp = d.modelspace()
    rows = [["КР-1", S.uo_line((200, 0, 0)), "Окраска", "12,03"]]
    h = S.table_height([10, 10, 50, 15], ["Марка", "УО", "Наименование", "Площадь, м²"], rows, title="* Ведомость отделки стен")
    bottom = S.table(psp, 0, 0, [10, 10, 50, 15], ["Марка", "УО", "Наименование", "Площадь, м²"], rows,
                     title="* Ведомость отделки стен")
    assert abs(-bottom - h) < 0.01
    texts = [e.dxf.text for e in psp if e.dxftype() == "TEXT"]
    assert any(t.startswith("* Ведомость для оценки") for t in texts)
    assert any(e.dxftype() == "LINE" and e.rgb == (200, 0, 0) for e in psp)


def test_bindings_of_electrics_are_red():
    import ezdxf
    from sdalbum import dims as DM
    d = ezdxf.new(setup=True)
    for n in ("SD50",):
        d.dimstyles.new(n)
    sp = d.modelspace()
    with DM.color(DM.RED):
        DM.chain(sp, [0, 1000, 2500], 500, 0, 50.0)
    DM.chain(sp, [0, 1000], 900, 0, 50.0)
    dims = [e for e in sp if e.dxftype() == "DIMENSION"]
    reds = [e for e in dims if e.override()["dimclrd"] == DM.RED]
    assert len(reds) == 2 and len(dims) == 3
