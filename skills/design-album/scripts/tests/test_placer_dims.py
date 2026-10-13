# -*- coding: utf-8 -*-
"""Collision-aware placement and dimension chains."""
import itertools

from shapely.geometry import box


def _doc():
    from sdalbum import gfx as S
    S.ensure_fonts()
    doc = S.new_doc()
    return doc, doc.modelspace()


def test_text_geom_scales_with_height():
    from sdalbum.placer import text_geom
    g1 = text_geom("1234", (0, 0), 1.0)
    g2 = text_geom("1234", (0, 0), 2.0)
    assert abs(g2.area / g1.area - 4.0) < 0.05


def test_place_text_avoids_obstacle():
    from sdalbum.placer import Occ, place_text, ring_candidates
    doc, msp = _doc()
    occ = Occ()
    occ.add(box(-500, -500, 500, 500), "wall")
    p, g, score = place_text(msp, occ, "Подпись", [(0, 0)] + ring_candidates((0, 0), [800, 1200], 16), 100)
    assert score == 0
    assert not g.intersects(box(-500, -500, 500, 500))


def test_masked_labels_are_drawn_last():
    """Masked labels are deferred: lines drawn after placement must not cross them in the final drawing order."""
    from sdalbum import gfx as S
    from sdalbum.placer import Occ, place_text, flush_all
    doc, msp = _doc()
    occ = Occ()
    place_text(msp, occ, "h300", [(0, 0)], 100, mask=True)
    S.line(msp, (-500, 0), (500, 0))
    flush_all()
    kinds = [e.dxftype() for e in msp]
    assert kinds.index("LINE") < kinds.index("TEXT")


def test_chain_texts_never_overlap_each_other():
    from sdalbum import dims
    from sdalbum.placer import Occ
    doc, msp = _doc()
    occ = Occ()
    vals = [0, 50, 100, 120, 2000, 2050, 2600, 2615, 4000]
    geoms = dims.chain(msp, vals, -700, 0, 50, occ)
    for a, b in itertools.combinations(geoms, 2):
        assert a.intersection(b).area < 1e-6


def test_chain_short_segment_is_raised_not_swapped():
    """A value that does not fit stays over its own segment (raised), it is not pushed into the neighbour's span."""
    from sdalbum import dims
    from sdalbum.placer import Occ
    doc, msp = _doc()
    occ = Occ()
    geoms = dims.chain(msp, [0, 1500, 1560, 3000], -700, 0, 50, occ)
    short = geoms[1]
    c = short.centroid
    assert 1400 < c.x < 1660


def test_chain_merges_close_values():
    from sdalbum import dims
    from sdalbum.placer import Occ
    doc, msp = _doc()
    geoms = dims.chain(msp, [0, 0.4, 1000], -700, 0, 50, Occ())
    assert len(geoms) == 1


def test_side_rows(urgench):
    from sdalbum import dims
    assert dims.side_rows(urgench, "T") == 2          # entrance door on the top facade
    assert dims.side_rows(urgench, "R") == 1


def test_short_value_never_written_across_own_extension_lines():
    """'50' of a 50-mm segment at 1:25 - when the raised / outside places are taken, it went between the extension
    lines on the object side (unreadable, lesson L-058). It must take any place clear of its extension lines."""
    from shapely.geometry import LineString, box
    from sdalbum import dims as DM
    from sdalbum import gfx as S
    from sdalbum.placer import Occ
    S.ensure_fonts()
    doc = S.new_doc()
    blk = doc.blocks.new("T")
    k = 25
    occ = Occ()
    occ.add(box(-400, 450, 30, 900), "x")            # 'before' and the raised rows above the short segment are taken
    occ.add(box(-100, 560, 400, 900), "x")
    out = DM.chain(blk, [0, 50, 1000], 500, 0, k, occ)
    g50 = out[0]
    for v in (0, 50):
        assert not g50.intersects(LineString([(v, 20), (v, 530)]))
