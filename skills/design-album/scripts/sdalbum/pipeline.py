# -*- coding: utf-8 -*-
"""One command from any input to a delivered album:

    python3 sda.py make INPUT OUT [--revit] [--target-dir "C:\\..."] [--no-propose] [--scale 50] [--no-png]

INPUT: project.json | scene.max | plan.dxf | plan.dwg | plan.pdf | photo/scan (.png/.jpg) | a folder with any of them.
Steps: import -> automatic corrections -> design proposal for empty sections -> data check -> album (PDF, DXF, PNG)
-> sheet QA -> Revit package (optional) -> OUT/report.md (what was done, what to confirm with the client).
OUT/project.json is the working copy (journal: sda.py history / undo / diff); the input is never modified.
"""
import json
import os
import shutil
import time

KEEP_ON_REIMPORT = ("item_overrides", "overrides", "notes")
IMAGES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".heic", ".webp")
ORDER = (".json", ".max", ".dxf", ".dwg", ".pdf") + IMAGES


def pick_input(src):
    if os.path.isfile(src):
        return src
    best = None
    for root, _, files in os.walk(src):
        if ".sda_history" in root:
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in ORDER:
                continue
            p = os.path.join(root, f)
            if ext == ".json":
                try:
                    d = json.load(open(p, encoding="utf-8"))
                    if not isinstance(d, dict) or "walls" not in d:
                        continue
                except Exception:
                    continue
            rank = ORDER.index(ext)
            if best is None or rank < best[0] or (rank == best[0] and os.path.getsize(p) > os.path.getsize(best[1])):
                best = (rank, p)
    if best is None:
        raise SystemExit("в папке %s нет подходящих файлов (%s)" % (src, ", ".join(ORDER)))
    return best[1]


def _import(src, out, scale=None, say=print):
    """-> (draft project.json path or None, status, notes)"""
    ext = os.path.splitext(src)[1].lower()
    imp = os.path.join(out, "import")
    os.makedirs(imp, exist_ok=True)
    if ext == ".json":
        return src, "project", []
    if ext == ".max":
        from importers import max_scene
        max_scene.main(src, imp)
        return os.path.join(imp, "draft_project.json"), "draft", [
            "стены взяты из 3D-сцены (check=true) - сверить с import/plan_cut.png",
            "мебель и проёмы сцены перенести по import/inventory.md (агент делает это по картинкам)"]
    if ext in (".dxf", ".dwg"):
        from importers import dxf_plan
        try:
            dxf_plan.main(src, imp)
        except SystemExit as ex:
            return None, "dwg", [str(ex)]
        return os.path.join(imp, "draft_project.json"), "draft", ["проёмы и помещения найдены автоматически - сверить с import/plan.png"]
    if ext == ".pdf":
        from importers import pdf_plan
        res = pdf_plan.main(src, imp, scale=scale)
        if res["status"] == "ok":
            return os.path.join(imp, "draft_project.json"), "draft", [
                "PDF векторный, масштаб 1:%g%s - сверить план с import/plan.png" % (
                    res["scale"], " (определён по размерным числам)" if res.get("auto_votes") else "")]
        why = {"raster": "PDF растровый (скан) - нужна оцифровка по страницам import/page-N.png",
               "no_scale": "масштаб PDF не определён - повторить с --scale (например 50) или оцифровать по import/page-N.png",
               "no_walls": "в PDF нет залитых стен - оцифровать по import/page-N.png"}[res["status"]]
        return None, "digitize", [why]
    if ext in IMAGES:
        dst = os.path.join(imp, os.path.basename(src))
        if os.path.abspath(dst) != os.path.abspath(src):
            shutil.copy(src, dst)
        return None, "digitize", ["фото/скан обмера - оцифровка по references/import-pdf-photo.md (размерные цепочки -> стены)"]
    raise SystemExit("формат %s не поддерживается" % ext)


def make(src, out, revit=False, target_dir=None, propose_=True, png=True, scale=None, sheets=None, say=print,
         survey=None, dwg_=True):
    from . import album, autofix, history, propose, qa, senior, validate
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    src = pick_input(src)
    rep = dict(input=os.path.abspath(src), out=os.path.abspath(out), status="", notes=[], fixes=[], decisions=[], proposals=[],
               questions=[], data=[], sheets=[], errors=0, warnings=0, files={})
    say("Вход: %s" % src)
    draft, kind, notes = _import(src, out, scale, say)
    rep["notes"] += notes
    if draft is None:
        rep["status"] = "needs_input" if kind != "digitize" else "digitize"
        _write(rep, out)
        say("Нужна оцифровка / другой формат: " + "; ".join(notes))
        return rep
    proj = os.path.join(out, "project.json")
    base = os.path.dirname(os.path.abspath(draft))
    if os.path.abspath(draft) != os.path.abspath(proj):
        d = history.load(draft)
        if kind == "draft":
            _name_from_source(d, src)
        _copy_assets(d, base, out)
        h = _hash(d)
        mark = os.path.join(out, ".sda_input.json")
        last = json.load(open(mark, encoding="utf-8")).get("hash") if os.path.isfile(mark) else None
        if not os.path.isfile(proj):
            history.save(proj, d, "исходные данные: %s" % os.path.basename(src))
        elif h != last:                      # the source changed: re-import (the old working copy stays in the journal)
            old = history.load(proj)
            for key in KEEP_ON_REIMPORT:         # the designer's own data is not the source's: it stays
                if old.get(key) and not d.get(key):
                    d[key] = old[key]
            history.save(proj, d, "исходные данные обновлены: %s" % os.path.basename(src))
            rep["notes"].append("исходник изменился - рабочая копия обновлена (прежняя - в журнале, sda.py undo)")
        else:                                # same source: keep the working copy with the user's edits
            rep["notes"].append("рабочая копия project.json сохранена со всеми правками (исходник не менялся)")
        json.dump(dict(hash=h, input=os.path.abspath(src)), open(mark, "w", encoding="utf-8"))
    d = history.load(proj)
    d2, flog, rest, qs = autofix.fix(d, out)
    plog, slog = [], []
    if propose_:                             # senior decisions first (rooms, ceilings, model lights, equipment)
        d3, slog = senior.decide(d2, out)
        if slog:
            d2, flog2, rest, qs = autofix.fix(d3, out)
            flog += flog2
    if propose_:
        d3, plog = propose.propose(d2, out)
        if plog:
            d2, flog2, rest, qs = autofix.fix(d3, out)
            flog += flog2
    if d2 != d:
        history.save(proj, d2, "make: автоисправления %d, решения %d, проектное предложение %d" % (len(flog), len(slog), len(plog)),
                     flog + slog + plog)
    rep["fixes"] = list(dict.fromkeys(e["msg"] for e in flog))
    rep["decisions"] = ["**%s**: %s%s" % (e["topic"], e["msg"], (" - %s" % e["why"]) if e.get("why") else "") for e in slog]
    rep["proposals"] = [e["msg"] for e in plog]
    rep["questions"] = list(dict.fromkeys(qs + list(d2.get("meta", {}).get("questions", []))))
    rep["data"] = rest
    errs = [i for i in rest if i["level"] == "error"]
    if errs:
        rep["status"] = "data_errors"
        rep["errors"] = len(errs)
        _write(rep, out)
        say("Ошибки данных - альбом не собран:")
        validate.print_report(rest)
        return rep
    from . import audit as AU                # every element against the 3ds Max scene it came from (L-100)
    aud, asum = AU.run(d2, out)
    rep["audit"], rep["audit_issues"] = asum, aud
    if asum.get("scene"):
        AU.print_report(aud, asum)
    say("Сборка альбома...")
    n_open = sum(1 for i in aud if i["level"] == "error")
    A = album.build(proj, out, sheets, warning=(
        "НЕ СВЕРЕНО СО СЦЕНОЙ 3ds Max (%d) - НЕ ДЛЯ ВЫДАЧИ И СТРОИТЕЛЬСТВА" % n_open) if n_open else None)
    dxf = os.path.join(out, "album.dxf")
    A.save_dxf(dxf)
    pdf = A.render_pdf(os.path.join(out, "album.pdf"), os.path.join(out, "png") if png else None)
    sheet_rep = qa.check_doc(A.doc)
    extra = A.issues + A.check_clipping()
    e, w = qa.summary(sheet_rep)
    e += sum(1 for i in rest + extra + aud if i["level"] == "error")
    w += sum(1 for i in rest + extra + aud if i["level"] == "warning")
    json.dump(dict(sheets=sheet_rep, data=rest, build=extra, audit=aud, audit_summary=asum, errors=e, warnings=w),
              open(os.path.join(out, "qa.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rep["sheets"] = ["%02d %s (%s)" % (no, title, scale_) if scale_ else "%02d %s" % (no, title) for no, key, title, scale_, fn, arg in A.sheets]
    rep["errors"], rep["warnings"] = e, w
    rep["sheet_issues"] = {k: v for k, v in sheet_rep.items() if v}
    rep["build_issues"] = extra
    rep["files"] = dict(pdf=pdf, dxf=dxf, project=proj, qa=os.path.join(out, "qa.json"))
    if dwg_:
        from . import dwg as DW
        try:                                 # the studio's draftsman edits in AutoCAD: exploded DXF + DWG (L-098)
            dres = DW.export(dxf, out)
            rep["files"]["dxf_edit"] = dres["dxf_edit"]
            rep["files"]["dwg_zip"] = dres["zip"]
            if dres["dwg"]:
                rep["files"]["dwg"] = dres["dwg"]
            rep["notes"].append(dres["note"])
        except Exception as ex:
            rep["notes"].append("DWG не сделан: %s - отдан DXF" % ex)
    if revit:
        from . import model, revit as RV
        paths = RV.export(model.load(proj), os.path.join(out, "revit"), album_dxf=dxf, target_dir=target_dir)
        rep["files"]["revit"] = paths
    if any(i["level"] == "error" for i in aud):
        rep["status"] = "audit_errors"
    else:
        rep["status"] = "ok" if e == 0 else "qa_errors"
    rep["seconds"] = round(time.time() - t0)
    _write(rep, out)
    say("Готово: листов %d, ошибок %d, предупреждений %d (%d с). Отчёт: %s" % (
        len(rep["sheets"]), e, w, rep["seconds"], os.path.join(out, "report.md")))
    return rep


OBJECT_TYPES = [   # (pattern in the file name, genitive for «интерьера ...», capitals for the cover)
    (r"cafeteria|cafe|caf\u00e9|coffee|кафе|кофейн|столов", "кафе"),
    (r"restaurant|ресторан", "ресторана"),
    (r"office|офис", "офиса"),
    (r"shop|store|boutique|магазин|бутик", "магазина"),
    (r"salon|салон|beauty|barber", "салона"),
    (r"hotel|отел|гостиниц", "отеля"),
    (r"clinic|клиник|dental|стомат", "клиники"),
    (r"house|villa|cottage|дом|коттедж|вилл", "дома"),
    (r"apartment|flat|квартир|kvartir", "квартиры"),
]


def _name_from_source(d, src):
    """A draft has no object name: take it from the file name - 'sherov cafeteria.max' -> «Дизайн-проект интерьера
    кафе «Sherov»», not «квартиры» (lesson L-065)."""
    import re
    meta = d.setdefault("meta", {})
    if meta.get("object"):
        return
    stem = re.sub(r"[_\-.]+", " ", os.path.splitext(os.path.basename(src))[0]).strip()
    typ, rest = None, stem
    for rx, gen in OBJECT_TYPES:
        m = re.search(r"\w*(?:%s)\w*" % rx, stem, re.I)          # the whole word: «Kvartira», not «kvartir» + «a»
        if m:
            typ = gen
            rest = (stem[:m.start()] + " " + stem[m.end():]).strip()
            break
    rest = re.sub(r"(?i)\b(plan|план|scene|сцена|final|draft|project|проект|last|all|new|copy|копия|v\d+|\d{4})\b", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    name = " ".join(w[:1].upper() + w[1:] for w in rest.split()) if rest and not rest.isdigit() else ""
    typ = typ or "квартиры"
    meta["object"] = "Дизайн-проект интерьера %s%s" % (typ, " «%s»" % name if name else "")
    meta["title"] = "ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА %s" % typ.upper()


def _hash(d):
    import hashlib
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _copy_assets(d, base, out):
    """Relative logo paths and the meshes of the furniture items keep working from OUT."""
    meta = d.get("meta", {})
    for it in d.get("items") or []:
        p = it.get("mesh")
        if p and not os.path.isabs(p):
            src = os.path.join(base, p)
            dst = os.path.join(out, p)
            if os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst)
    for k in ("logo", "logo_transparent"):
        p = meta.get(k)
        if p and not os.path.isabs(p) and os.path.isfile(os.path.join(base, p)):
            dst = os.path.join(out, p)
            os.makedirs(os.path.dirname(dst) or out, exist_ok=True)
            if os.path.abspath(dst) != os.path.abspath(os.path.join(base, p)):
                shutil.copy(os.path.join(base, p), dst)


STATUS = {"ok": "альбом готов, ошибок нет", "qa_errors": "альбом собран, но есть ошибки проверки листов - исправить до выдачи",
          "audit_errors": "альбом собран для проверки, но НЕ сверен со сценой 3ds Max - заказчику не выдавать (см. «Сверка со сценой»)",
          "data_errors": "ошибки в данных - альбом не собран", "digitize": "нужна оцифровка исходника",
          "needs_input": "нужен другой формат исходника"}


def _write(rep, out):
    json.dump(rep, open(os.path.join(out, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    L = ["# Отчёт агента", "", "**Итог:** %s." % STATUS.get(rep["status"], rep["status"]), "",
         "Исходник: `%s`" % os.path.basename(rep["input"]), ""]
    if rep.get("sheets"):
        L += ["## Листы (%d)" % len(rep["sheets"]), ""] + ["- " + s for s in rep["sheets"]] + [""]
        L += ["Проверка: ошибок %d, предупреждений %d (подробно - qa.json)." % (rep["errors"], rep["warnings"]), ""]
    f = rep.get("files") or {}
    if f:
        L += ["## Файлы", ""]
        for k, name in (("pdf", "альбом PDF"), ("dwg_zip", "архив для AutoCAD: DWG + DXF + картинки листов"),
                        ("dwg", "альбом DWG (AutoCAD, чертежи в модели расчленены)"),
                        ("dxf_edit", "альбом DXF для правки (то же, что DWG)"), ("dxf", "альбом DXF (исходный, чертежи блоками)"),
                        ("project", "рабочие данные project.json"),
                        ("qa", "протокол проверки qa.json")):
            if f.get(k):
                L.append("- %s: `%s`" % (name, os.path.relpath(f[k], rep["out"])))
        if f.get("revit"):
            L.append("- Revit: %s (инструкция - references/revit.md)" % ", ".join("`%s`" % os.path.relpath(p, rep["out"]) for p in f["revit"]))
        L.append("")
    asum = rep.get("audit") or {}
    if asum.get("scene"):
        L += ["## Сверка со сценой 3ds Max", "",
              "Объектов сцены с геометрией: %d; в альбоме использовано: %d; %s." % (
                  asum["objects"], asum["used"], "геометрия - из выгрузки 3ds Max (sda_export.ms), всё вычислено самим 3ds Max"
                  if asum.get("export") else "геометрия прочитана из .max без 3ds Max: точно %d, повторены правки Edit Poly %d, "
                  "в пределах исходной формы %d, НЕ вычисляется %d" % tuple(asum["statuses"].get(k, 0) for k in ("exact", "replayed", "bound", "unknown"))),
              ""]
        ai = rep.get("audit_issues") or []
        if ai:
            L += ["| Проверка | Что не так |", "|---|---|"] + ["| %s | %s |" % (i["code"], i["msg"].replace("|", "/")) for i in ai] + [""]
        if asum.get("unverified") and not asum.get("export"):
            L += ["**Как снять «не проверено»:** в 3ds Max открыть сцену, Scripting → Run Script → "
                  "`scripts/max/sda_export.ms` (из плагина); рядом со сценой появятся `<сцена>.sda.json` и `.sda.bin` - "
                  "положить их рядом с .max и пересобрать: размеры возьмутся из вычисленной 3ds Max геометрии.", ""]
    if rep.get("notes"):
        L += ["## Исходные данные", ""] + ["- " + s for s in rep["notes"]] + [""]
    if rep.get("fixes"):
        L += ["## Исправлено автоматически", ""] + ["- " + s for s in rep["fixes"]] + [""]
    if rep.get("decisions"):
        L += ["## Решения агента (приняты по нормам и модели, вопросов не требуют)", ""] + ["- " + s for s in rep["decisions"]] + [""]
    if rep.get("proposals"):
        L += ["## Проектное предложение по нормам (подтвердить)", ""] + ["- " + s for s in rep["proposals"]] + [""]
    if rep.get("questions"):
        L += ["## Вопросы к заказчику", ""] + ["%d. %s" % (i + 1, q) for i, q in enumerate(rep["questions"])] + [""]
    errs = [i for i in rep.get("data", []) if i["level"] == "error"] + [i for i in rep.get("build_issues", []) if i["level"] == "error"]
    for name, issues in (rep.get("sheet_issues") or {}).items():
        errs += [dict(i, msg="%s: %s" % (name, i["msg"])) for i in issues if i["level"] == "error"]
    if errs:
        L += ["## Ошибки (блокируют выдачу)", ""] + ["- [%s] %s" % (i["code"], i["msg"]) for i in errs] + [""]
    L += ["## Дальше", "",
          "- правка словами: `sda.py edit project.json \"set sockets[room=Спальня,note~кровать] h=700\"`",
          "- что изменилось для заказчика: `sda.py diff project.json --since 1`; откат: `sda.py undo project.json`",
          "- пересборка: `sda.py make project.json <папка>`", ""]
    open(os.path.join(out, "report.md"), "w", encoding="utf-8").write("\n".join(L))
