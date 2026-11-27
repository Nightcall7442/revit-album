"""Reference album, round 2: numbering from 0, «Узлы и сечения», moldings summary with real profiles, renders."""
import os

HERE = os.path.dirname(__file__)
URGENCH = os.path.join(HERE, "..", "..", "examples", "urgench-apartment", "project.json")


def test_floor_layers_parsed():
    from sdalbum.sheets_nodes import parse_layers
    lay = parse_layers({"layers": "Паркетная доска 14 мм; подложка 3 мм; стяжка ЦПС М150 (по факту)"})
    assert [round(t) for _, t, _, _ in lay] == [14, 3, 50]
    assert [k for _, _, k, _ in lay] == ["wood", "under", "screed"]
    assert "уточнить" in lay[2][0] and lay[2][3] is False
    lay = parse_layers({"material": "Керамогранит 600×600", "layers": "Керамогранит 8-12 мм; клей 5-7 мм"})
    assert [t for _, t, _, _ in lay] == [10.0, 6.0]


def test_reference_order_numbers_from_zero_with_sections(tmp_path):
    from sdalbum import album, model, qa
    A = album.Album(model.load(URGENCH), str(tmp_path), ["cover", "contents", "general", "sections", "measured"])
    assert [(n, t) for n, _, t, *_ in A.sheets][:4] == [(0, "Титульный лист"), (1, "Оглавление"),
                                                       (2, "Пояснительная записка"), (3, "Узлы и сечения")]
    assert A.total == 4 and A.count == 5
    A.build()
    rep = qa.check_doc(A.doc)
    assert not [i for v in rep.values() for i in v if i["level"] == "error"]


def test_old_order_still_numbers_from_one(tmp_path):
    from sdalbum import album, model
    A = album.Album(model.load(URGENCH), str(tmp_path), ["cover", "general", "measured"])
    assert [n for n, *_ in A.sheets] == [1, 2, 3]


def test_renders_make_visual_sheets(tmp_path):
    from PIL import Image
    from sdalbum import album, model, visuals
    P = model.load(URGENCH)
    files = []
    for i in range(5):
        f = tmp_path / ("Гостиная_%d.png" % i)
        Image.new("RGB", (160, 90), (200, 180, 150)).save(f)
        files.append(str(f))
    P.meta["renders"] = files
    sh = visuals.sheets(album.Album(P, str(tmp_path / "a"), ["visuals"]))
    assert len(sh) == 2 and sh[0][0].startswith("Визуализации пом.") and "Гостиная" in sh[0][0]
    assert [len(a["files"]) for _, _, _, a in sh] == [4, 1]


def test_molding_section_of_a_mesh():
    """A box-section moulding 40 high, 20 off the wall along the X wall: the cut gives a 20×40 outline."""
    import numpy as np
    from sdalbum.moldings import _cut
    V = np.array([[0, 0, 1000], [1000, 0, 1000], [1000, 20, 1000], [0, 20, 1000],
                  [0, 0, 1040], [1000, 0, 1040], [1000, 20, 1040], [0, 20, 1040]], float)
    F = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [3, 2, 6], [3, 6, 7]])
    segs = _cut(V, F, (1.0, 0.0), (0.0, 1.0), (0.0, 0.0), 500.0, 900.0, 1100.0)
    ds = [p[0] for s in segs for p in s]
    zs = [p[1] for s in segs for p in s]
    assert abs(max(ds) - min(ds) - 20) < 1e-6 and abs(max(zs) - min(zs) - 40) < 1e-6
