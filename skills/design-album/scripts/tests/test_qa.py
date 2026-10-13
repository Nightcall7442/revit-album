# -*- coding: utf-8 -*-
"""Sheet QA must catch every defect class the client complained about (overlaps, text on walls, clipping)."""
from sdalbum import gfx as S
from sdalbum import qa


def _sheet(name="05 Тест"):
    S.ensure_fonts()
    doc = S.new_doc()
    psp = doc.layouts.new(name)
    psp.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")
    return doc, psp


def _codes(doc):
    rep = qa.check_doc(doc)
    return [i["code"] for v in rep.values() for i in v if i["level"] == "error"]


def test_clean_sheet_has_no_errors():
    doc, psp = _sheet()
    S.text(psp, "Гостиная", (100, 150), 3.0)
    S.text(psp, "14,34 м²", (100, 140), 2.5)
    assert _codes(doc) == []


def test_text_overlap_is_error():
    doc, psp = _sheet()
    S.text(psp, "3220", (100, 150), 2.5)
    S.text(psp, "1500", (101.5, 150.3), 2.5)
    assert "TEXT_OVERLAP" in _codes(doc)


def test_text_on_wall_is_error():
    doc, psp = _sheet()
    S.fill(psp, [(90, 140), (130, 140), (130, 160), (90, 160)], S.C_WALL, "SD_Стены")
    S.text(psp, "400", (110, 150), 2.5)
    assert "TEXT_ON_WALL" in _codes(doc)


def test_white_mask_over_wall_is_ok():
    doc, psp = _sheet()
    S.fill(psp, [(90, 140), (130, 140), (130, 160), (90, 160)], S.C_WALL, "SD_Стены")
    S.fill(psp, [(104, 147), (116, 147), (116, 153), (104, 153)], (255, 255, 255), "SD_Текст")
    S.text(psp, "400", (110, 150), 2.5)
    assert "TEXT_ON_WALL" not in _codes(doc)


def test_text_in_stamp_and_out_of_frame():
    doc, psp = _sheet()
    S.text(psp, "залезло в штамп", (300, 20), 2.5)
    S.text(psp, "за рамкой", (10, 150), 2.5)
    c = _codes(doc)
    assert "TEXT_IN_STAMP" in c and "TEXT_OUT_FRAME" in c


def test_clipped_dimension_is_found_by_album(tmp_path):
    """A dimension drawn beyond its viewport window -> CONTENT_CLIPPED (the old album lost its top chain this way)."""
    from sdalbum.album import Album
    from sdalbum import model
    from conftest import STUDIO
    P = model.load(STUDIO)
    A = Album(P, str(tmp_path), ["measured"])
    A.cur_title = "04 test"
    psp = A.make_sheet(4, "Тест", "1:50")
    blk, off = A.model_block(4)
    A.vp(psp, off, (0, 0, 1000, 1000), (30, 40), 50)
    S.text(blk, "500", (500, 500), 100)
    assert A.check_clipping() == []
    S.text(blk, "1100", (1200, 500), 100)
    issues = A.check_clipping()
    assert issues and issues[0]["code"] == "CONTENT_CLIPPED"


def test_wrapped_legend_cell_grows_the_row():
    """A long group list in a legend row (rows of fixed height) wrapped into the next row (lesson L-051)."""
    doc, psp = _sheet()
    rows = [["", "Светильник встраиваемый поворотный, GU10, 7 Вт, 3000 K", "31",
             "Гостиная, Коридор, Кухня-столовая, Прихожая, Спальня"],
            ["", "Светильник встраиваемый влагозащищённый IP44", "4", "Санузел, Санузел совмещённый"]]
    S.table(psp, 303, 250, [16, 49, 9, 27], ["Эскиз", "Наименование", "Кол.", "Группа"], rows, h=1.45, row_h=5.2, head_h=5.5)
    assert "TEXT_OVERLAP" not in _codes(doc)
