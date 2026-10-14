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
  python3 sda.py fix project.json [--dry]        safe automatic corrections (5-mm module, hot water left, points on
                                                walls, pass-through switches, IP44 in wet rooms, draft marks/doors)
  python3 sda.py propose project.json [--dry] [--only lighting,sockets]
                                                design proposal by norms for EMPTY sections (light, switches,
                                                sockets, plumbing, panel, groups, floors, ceilings, finishes)
  python3 sda.py find project.json 'sockets[room=Спальня]'      list items (selector syntax: sdalbum/editor.py)
  python3 sda.py edit project.json "set sockets[room=Спальня,note~кровать] h=700" "move switches[id=В3] 0 -300"
                  [-m "описание"]                edit with journal; shows what the change broke / fixed
  python3 sda.py undo project.json [N]           undo the last N changes
  python3 sda.py history project.json            journal of changes
  python3 sda.py diff old.json new.json | diff project.json --since N
                                                changes in words + sheets they touch (for the client)
  python3 sda.py make INPUT OUT [--survey plan.pdf|dxf|dwg] [--revit] [--target-dir "C:\\..."] [--no-propose]
                  [--scale 50] [--no-png] [--no-dwg]
                                                ONE COMMAND: any input (project.json / .max / .dxf / .dwg / .pdf /
                                                photo / folder) -> fixes -> proposal by norms -> album -> QA ->
                                                Revit (optional) -> OUT/report.md with questions for the client
  python3 sda.py import-pdf plan.pdf OUT [--page 1] [--scale 50]
                                                vector PDF -> DXF -> draft project.json (scale from dimensions)
  python3 sda.py dwg OUT/album.dxf [--out DIR]   editable DXF (sheet drawings exploded in model space) + DWG R2000
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


def cmd_fix(args):
    from sdalbum import autofix, history
    path = args[0]
    d = history.load(path)
    d2, log, rest, qs = autofix.fix(d, os.path.dirname(os.path.abspath(path)))
    autofix.print_log(log, rest, qs)
    if log and "--dry" not in args:
        n = history.save(path, d2, "автоисправление: " + ", ".join(sorted(set(e["code"] for e in log))), log)
        print("сохранено (правка %d; откат: sda.py undo %s)" % (n, path))
    return 1 if any(i["level"] == "error" for i in rest) else 0


def cmd_propose(args):
    from sdalbum import autofix, history, propose
    path = args[0]
    base = os.path.dirname(os.path.abspath(path))
    only = _opt(args, "--only")
    d = history.load(path)
    d2, log = propose.propose(d, base, only.split(",") if only else None)
    propose.print_log(log)
    if not log:
        print("все разделы уже заполнены - предлагать нечего (данные дизайнера не перезаписываются)")
        return 0
    d3, flog, rest, qs = autofix.fix(d2, base)
    autofix.print_log(flog, rest, qs)
    if "--dry" not in args:
        n = history.save(path, d3, "проектное предложение: " + ", ".join(e["section"] for e in log), log + flog)
        print("сохранено (правка %d; откат: sda.py undo %s)" % (n, path))
    return 1 if any(i["level"] == "error" for i in rest) else 0


def cmd_find(args):
    from sdalbum import editor, history, model
    path = args[0]
    d = history.load(path)
    P = editor._project(d, os.path.dirname(os.path.abspath(path)))
    sel = args[1] if len(args) > 1 else "rooms"
    try:
        sec, items = editor.select(d, sel, P)
    except editor.EditError as ex:
        print("ОШИБКА:", ex)
        return 2
    full = editor._container(d, sec)
    idx = {id(it): i + 1 for i, it in enumerate(full)} if isinstance(full, list) else {}
    for key, it in items:
        tag = ("#%d" % idx[id(it)]) if id(it) in idx else (str(key) if key is not None else "")
        print("%s%s  %s" % (sec, tag, editor.describe(sec, it, P)))
    print("найдено: %d" % len(items))
    return 0


def cmd_edit(args):
    from sdalbum import editor, history, model, validate
    path = args[0]
    msg = _opt(args, "-m")
    ops = [a for i, a in enumerate(args[1:], 1) if a != "-m" and args[i - 1] != "-m"]
    base = os.path.dirname(os.path.abspath(path))
    d = history.load(path)
    try:
        d2, msgs = editor.apply(d, ops, base)
    except editor.EditError as ex:
        print("ОШИБКА:", ex)
        return 2
    for m in msgs:
        print("  * " + m)
    try:
        before = {(i["code"], i["msg"]) for i in validate.run(model.Project(d, base))}
    except Exception:
        before = set()
    try:
        after_l = validate.run(model.Project(d2, base))
    except Exception as ex:
        print("ОШИБКА: после правки проект не собирается (%s) - правка не сохранена" % ex)
        return 2
    after = {(i["code"], i["msg"]) for i in after_l}
    for c, m in sorted(after - before):
        print("  ! новое замечание [%s] %s" % (c, m))
    for c, m in sorted(before - after):
        print("  ✓ снято [%s] %s" % (c, m))
    n = history.save(path, d2, msg or "; ".join(msgs)[:300], ops)
    print("сохранено (правка %d; откат: sda.py undo %s)" % (n, path))
    return 1 if any(i["level"] == "error" for i in after_l) else 0


def cmd_undo(args):
    from sdalbum import history
    steps = int(args[1]) if len(args) > 1 else 1
    undone = history.undo(args[0], steps)
    if not undone:
        print("журнал пуст - откатывать нечего")
        return 1
    for e in undone:
        print("откат правки %d: %s" % (e["n"], e["msg"]))
    return 0


def cmd_history(args):
    from sdalbum import history
    ent = history.entries(args[0])
    if not ent:
        print("журнал пуст")
    for e in ent:
        print("%3d  %s  %s" % (e["n"], e["time"], e["msg"]))
    return 0


def cmd_diff(args):
    from sdalbum import editor, history
    if "--since" in args:
        path = args[0]
        n = int(_opt(args, "--since"))
        a = history.snapshot_before(path, n)
        if a is None:
            print("в журнале нет правки %d" % n)
            return 1
        b = history.load(path)
    else:
        path = args[1]
        a, b = history.load(args[0]), history.load(args[1])
    ch, sheets = editor.diff(a, b, os.path.dirname(os.path.abspath(path)))
    editor.print_diff(ch, sheets)
    return 0


def cmd_make(args):
    from sdalbum import pipeline
    rep = pipeline.make(args[0], args[1], revit="--revit" in args, target_dir=_opt(args, "--target-dir"),
                        propose_="--no-propose" not in args, png="--no-png" not in args, scale=_opt(args, "--scale", float),
                        sheets=_opt(args, "--sheets").split(",") if "--sheets" in args else None,
                        survey=_opt(args, "--survey"), dwg_="--no-dwg" not in args)
    print(open(os.path.join(args[1], "report.md"), encoding="utf-8").read())
    return 0 if rep["status"] == "ok" else 1


def cmd_import_pdf(args):
    from importers import pdf_plan
    res = pdf_plan.main(args[0], args[1], page=_opt(args, "--page", int) or 1, scale=_opt(args, "--scale", float))
    return 0 if res["status"] == "ok" else 1


def cmd_dwg(args):
    from sdalbum import dwg
    res = dwg.export(args[0], _opt(args, "--out"))
    print("DXF для правки:", res["dxf_edit"])
    print("DWG:", res["dwg"] or "-", "|", res["note"])
    return 0 if res["dwg"] else 1


def cmd_test(args):
    return subprocess.call([sys.executable, "-m", "pytest", "-q", os.path.join(HERE, "tests")] + args)


CMDS = {"doctor": cmd_doctor, "validate": cmd_validate, "build": cmd_build, "qa": cmd_qa, "revit": cmd_revit,
        "import-max": cmd_import_max, "import-dxf": cmd_import_dxf, "test": cmd_test, "fix": cmd_fix,
        "propose": cmd_propose, "find": cmd_find, "edit": cmd_edit, "undo": cmd_undo, "history": cmd_history,
        "diff": cmd_diff, "make": cmd_make, "import-pdf": cmd_import_pdf, "dwg": cmd_dwg}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(CMDS[sys.argv[1]](sys.argv[2:]) or 0)
