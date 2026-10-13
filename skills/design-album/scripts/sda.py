# -*- coding: utf-8 -*-
"""Space Design Album agent — command line.

  python3 sda.py doctor                         check / install dependencies and fonts
  python3 sda.py validate project.json          data checks (geometry, positions, totals)
  python3 sda.py build project.json OUT [--sheets k1,k2] [--png]
                                                DXF + PDF (+ PNG previews) + qa.json
  python3 sda.py qa OUT/album.dxf               sheet QA on an existing DXF
  python3 sda.py revit project.json OUT [--album OUT/album.dxf] [--target-dir "C:\\...\\folder"]
                                                Revit: native model + (with --album) every album sheet as a
                                                Revit sheet (flat DXF import + images); .dyn + pyRevit .py
  python3 sda.py import-max scene.max OUT [--units cm] [--cut 1100]
                                                inventory + plan sections of a 3ds Max scene
  python3 sda.py import-dxf plan.dxf OUT [--window x0,y0,x1,y1] [--units mm]
                                                draft project.json from a DWG/DXF plan
  python3 sda.py test                            full test-suite (must be green before delivery)
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def cmd_doctor(args):
    need = ["ezdxf", "shapely", "pymupdf", "matplotlib", "numpy", "PIL", "pytest"]
    miss = []
    for m in need:
        try:
            __import__(m)
        except Exception:
            miss.append(m)
    if miss:
        pipn = {"PIL": "pillow"}
        pkgs = [pipn.get(m, m) for m in miss]
        print("installing:", pkgs)
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages"] + pkgs)
    try:
        import mathutils  # noqa: F401
    except Exception:
        subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "mathutils"])
    from sdalbum import gfx
    gfx.ensure_fonts()
    from ezdxf.fonts import fonts
    print("fonts:", fonts.find_font_face(gfx.FONT), fonts.find_font_face(gfx.FONT_B))
    print("ok")


def cmd_validate(args):
    from sdalbum import model, validate
    P = model.load(args[0])
    rep = validate.run(P)
    validate.print_report(rep)
    return 1 if any(i["level"] == "error" for i in rep) else 0


def cmd_build(args):
    from sdalbum import album, qa, validate
    proj, out = args[0], args[1]
    sheets = None
    png = "--png" in args
    if "--sheets" in args:
        sheets = args[args.index("--sheets") + 1].split(",")
    t = time.time()
    A = album.build(proj, out, sheets)
    dxf = os.path.join(out, "album.dxf")
    A.save_dxf(dxf)
    pdf = A.render_pdf(os.path.join(out, "album.pdf"), os.path.join(out, "png") if png else None)
    rep = qa.check_doc(A.doc)
    data = validate.run(A.P)
    extra = A.issues + A.check_clipping()
    e, w = qa.summary(rep)
    e += sum(1 for i in data + extra if i["level"] == "error")
    w += sum(1 for i in data + extra if i["level"] == "warning")
    json.dump(dict(sheets=rep, data=data, build=extra, errors=e, warnings=w), open(os.path.join(out, "qa.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    qa.print_report(rep)
    validate.print_report(data + extra)
    print("PDF:", pdf, " DXF:", dxf, " sheets:", len(A.sheets), " %.0fs" % (time.time() - t))
    print("ИТОГ: ошибок %d, предупреждений %d" % (e, w))
    return 1 if e else 0


def cmd_qa(args):
    import ezdxf
    from sdalbum import qa
    doc = ezdxf.readfile(args[0])
    rep = qa.check_doc(doc)
    qa.print_report(rep)
    return 1 if qa.summary(rep)[0] else 0


def cmd_revit(args):
    from sdalbum import model, revit
    P = model.load(args[0])
    paths = revit.export(P, args[1], album_dxf=_opt(args, "--album"), target_dir=_opt(args, "--target-dir"))
    print("\n".join(paths))


def _opt(args, name, cast=str):
    return cast(args[args.index(name) + 1]) if name in args else None


def cmd_import_max(args):
    from importers import max_scene
    kw = {k: v for k, v in (("units", _opt(args, "--units")), ("cut", _opt(args, "--cut", float)),
                            ("floor", _opt(args, "--floor", float))) if v is not None}
    max_scene.main(args[0], args[1], **kw)


def cmd_import_dxf(args):
    from importers import dxf_plan
    w = _opt(args, "--window")
    dxf_plan.main(args[0], args[1], [float(v) for v in w.split(",")] if w else None, _opt(args, "--units"))


def cmd_test(args):
    return subprocess.call([sys.executable, "-m", "pytest", "-q", os.path.join(HERE, "tests")] + args)


CMDS = {"doctor": cmd_doctor, "validate": cmd_validate, "build": cmd_build, "qa": cmd_qa, "revit": cmd_revit,
        "import-max": cmd_import_max, "import-dxf": cmd_import_dxf, "test": cmd_test}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(CMDS[sys.argv[1]](sys.argv[2:]) or 0)
