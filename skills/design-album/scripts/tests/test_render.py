# -*- coding: utf-8 -*-
"""Rendering of fills: a wall ring must stay empty inside in the PDF / PNG."""
import ezdxf
from shapely.geometry import box


def test_fill_with_hole_leaves_the_hole_empty(tmp_path):
    # «zal proj»: a room drawn as a hole of the wall fill came out solid black on every plan
    from ezdxf.addons.drawing import matplotlib as mp
    from PIL import Image
    from sdalbum import gfx
    d = ezdxf.new()
    m = d.modelspace()
    gfx.fill(m, box(0, 0, 100, 100).difference(box(10, 10, 90, 90)), (40, 40, 40))
    p = str(tmp_path / "f.png")
    mp.qsave(m, p, bg="#FFFFFF")
    im = Image.open(p).convert("L")
    assert im.getpixel((im.size[0] // 2, im.size[1] // 2)) > 200


def test_outline_of_detached_parts_is_the_building():
    from sdalbum import dims

    class P:
        mass = box(0, 0, 5000, 4000).difference(box(200, 200, 4800, 3800)).union(box(0, 9000, 3000, 9200))
    g = dims.outline_of(P)
    assert g.geom_type == "Polygon" and g.bounds == (0, 0, 5000, 4000)


def test_qa_sees_the_room_hole_of_a_wall_fill():
    # «zal proj»: every text in a room counted as «on the wall» - the QA took the wall fill without its holes
    import ezdxf
    from sdalbum import gfx, qa
    d = ezdxf.new()
    psp = d.layouts.new("t")
    gfx.fill(psp, box(0, 0, 100, 100).difference(box(10, 10, 90, 90)), (38, 38, 40))
    gfx.text(psp, "4545", (50, 50), 3.0)
    issues, _ = qa.check_layout(d, psp, False)
    assert not [i for i in issues if i["code"] == "TEXT_ON_WALL"]
