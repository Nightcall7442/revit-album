# -*- coding: utf-8 -*-
"""3D views of the reference album: wall finishes with marks, furniture, the title with the axonometry."""
from conftest import URGENCH


def test_finish_scene_has_full_walls_facing_the_camera_only(urgench):
    import numpy as np
    from sdalbum import sheets_3d as S3
    faces, anchors = S3.finish_scene(urgench, 38.0, -58.0)
    zs = [max(p[2] for p in f[0]) for f in faces]
    assert max(zs) >= 2700 and S3.LOW in zs                    # some skins full height, the rest cut down
    types = {t for t, _, _ in anchors}
    assert {"О1", "О2"} <= types                                # every finish of the flat gets a mark
    faces2, anchors2 = S3.finish_scene(urgench, 38.0, 122.0)
    tall = lambda fs: {tuple(np.round(f[0][0][:2])) for f in fs if max(p[2] for p in f[0]) > 2000}
    assert tall(faces) != tall(faces2)                         # the opposite view shows the other walls


def test_3d_sheets_and_reference_cover_build_clean(tmp_path):
    from sdalbum import album, model, qa
    A = album.Album(model.load(URGENCH), str(tmp_path), ["cover", "finishes_3d", "furniture_3d"])
    titles = [t for _, _, t, *_ in A.sheets]
    assert titles == ["Обложка", "3D-вид отделки стен. Вид 1", "3D-вид отделки стен. Вид 2", "3D-вид мебели. Вид 1",
                      "3D-вид мебели. Вид 2"]
    A.build()
    rep = qa.check_doc(A.doc)
    assert not [i for v in rep.values() for i in v if i["level"] == "error"]
    cover = A.layouts[1]
    txt = [e.dxf.text for e in cover if e.dxftype() == "TEXT"]
    assert "Проект:" in txt and "Адрес:" in txt and "Заказчик:" not in txt     # empty fields left out
    assert any(e.dxftype() == "IMAGE" for e in cover)                       # the axonometry of the flat
