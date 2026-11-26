# -*- coding: utf-8 -*-
"""Stage 6: the list of the working drawings by sections, the explanatory note, the summary schedules."""
from conftest import URGENCH


def test_contents_by_sections_and_summary_at_the_end(tmp_path):
    from sdalbum import album, model, qa
    from sdalbum.sheets_summary import sheet_rows
    A = album.Album(model.load(URGENCH), str(tmp_path))
    keys = [k for _, k, *_ in A.sheets]
    assert keys[1] == "contents" and keys[-1].startswith("summary_")
    titles = [t for _, _, t, *_ in A.sheets]
    assert "Общие данные. Пояснительная записка" in titles
    assert {"Сводная ведомость отделки", "Сводная ведомость дверей", "Сводная ведомость освещения и электрики",
            "Сводная ведомость стекла"} <= set(titles)
    rows = sheet_rows(A)
    assert [r for r in rows if r[0] == "summary"] and all(r[0] == "summary" for r in rows[-4:])
    # the elevations of a room are one line of the list
    assert any(r[1].count("–") == 1 and "развёртки" in r[2] for r in rows)
    A2 = album.Album(model.load(URGENCH), str(tmp_path / "s"), ["cover", "contents", "general", "summary_finishes",
                                                                 "summary_doors", "summary_electric", "summary_glass"])
    A2.build()
    rep = qa.check_doc(A2.doc)
    assert not [i for v in rep.values() for i in v if i["level"] == "error"]
    txt = [e.dxf.text if e.dxftype() == "TEXT" else e.plain_text() for no in A2.layouts for e in A2.layouts[no]
           if e.dxftype() in ("TEXT", "MTEXT")]
    assert "Альбом рабочих чертежей" in txt and "Сводные ведомости" in txt
    assert "* Сводная ведомость отделки стен" in txt and "Пояснительная записка" in txt


def test_summary_of_finishes_adds_up_to_the_sheets(urgench):
    from sdalbum import sheets_plans as SP
    from sdalbum.sheets_summary import _finish_tables

    class A_:
        P = urgench
    tabs = {t[0]: t for t in _finish_tables(A_)}
    walls = tabs["* Сводная ведомость отделки стен"]
    tot = sum(sum(split.values()) for _, split in SP.room_wall_finishes(urgench))
    assert walls[5][3] == ("%.2f" % tot).replace(".", ",")
