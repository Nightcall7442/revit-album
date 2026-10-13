# -*- coding: utf-8 -*-
"""Album sheets -> one flat DXF per sheet (paper space + viewports rendered to model-space geometry, mm, 1:1).

Used to carry the album into Revit / any CAD that imports model space only: every sheet becomes a drawing
420 x 297 mm at the origin, viewports clipped, texts as filled outlines (looks exactly like the PDF).
"""
import os

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, config
from ezdxf.addons.drawing.dxf import DXFBackend, ColorMode
from ezdxf.path.converter import to_splines_and_polylines


class _Backend(DXFBackend):
    def draw_path(self, path, properties):          # ezdxf 1.4.4: NumpyPath2d is not iterable in the original
        attribs = self.resolve_properties(properties)
        if path.has_curves:
            for entity in to_splines_and_polylines([path.to_path()], dxfattribs=attribs):
                self.layout.add_entity(entity)
        else:
            self.layout.add_lwpolyline(path.control_vertices(), dxfattribs=attribs)


def flatten_layout(src, layout_name, dst_path):
    out = ezdxf.new("R2018", units=4)
    out.header["$INSUNITS"] = 4
    out.header["$MEASUREMENT"] = 1
    msp = out.modelspace()
    lay = src.layouts.get(layout_name)
    ctx = RenderContext(src)
    ctx.set_current_layout(lay)
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                               image_policy=config.ImagePolicy.DISPLAY,
                               lineweight_policy=config.LineweightPolicy.ABSOLUTE)
    be = _Backend(msp, color_mode=ColorMode.RGB)
    Frontend(ctx, be, config=cfg).draw_layout(lay, finalize=True)
    out.saveas(dst_path)
    return dst_path


def flatten_album(dxf_path, out_dir):
    """album.dxf -> out_dir/ДП_NN.dxf for every sheet; returns [(no, title, path)]."""
    os.makedirs(out_dir, exist_ok=True)
    src = ezdxf.readfile(dxf_path)
    src.filename = dxf_path
    res = []
    for name in src.layouts.names_in_taborder():
        if name == "Model" or not name[:2].isdigit():
            continue
        no = int(name[:2])
        p = os.path.join(out_dir, "ДП_%02d.dxf" % no)
        flatten_layout(src, name, p)
        res.append((no, name[3:].strip(), p))
    return res
