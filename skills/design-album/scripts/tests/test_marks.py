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
