# -*- coding: utf-8 -*-
"""
АР — построение нативной модели Revit по project.json (Space Design Album agent).

Что создаётся (в открытом проекте, на уровне с отметкой 0):
  • типы стен «АР_Стена несущая …», «АР_Перегородка …» и стены по осевым линиям;
  • координационные оси;
  • двери и окна с отдельными типоразмерами по маркам, марками и направлением открывания;
  • помещения с номерами и названиями, линии разделения помещений;
  • план 1:50, разрезы 1-1 и 2-2, спецификации (экспликация, двери, окна) и, при наличии основной надписи, листы.

Как запустить (Revit 2022–2027):
  A) Dynamo (встроен в Revit): Управление → Dynamo → открыть файл .dyn из папки revit → Запуск.
  B) pyRevit / RevitPythonShell: выполнить этот файл.
Начинать лучше в НОВОМ проекте из архитектурного шаблона (единицы — мм). Нужны загруженные семейства дверей и окон.
Скрипт можно запускать повторно: уже созданные типы переиспользуются, но стены/двери будут продублированы —
поэтому повторный запуск делайте в чистом проекте.
"""
from __future__ import print_function, unicode_literals

import math
import os
import clr

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import *  # noqa: F401,F403
from Autodesk.Revit.DB.Structure import StructuralType
try:
    from Autodesk.Revit.DB.Architecture import Room  # noqa: F401
except Exception:
    pass

# ----------------------------------------------------------------------------- environment
IN_DYNAMO = False
try:
    doc = __revit__.ActiveUIDocument.Document  # noqa: F821  (pyRevit / RevitPythonShell)
except NameError:
    clr.AddReference("RevitServices")
    from RevitServices.Persistence import DocumentManager
    from RevitServices.Transactions import TransactionManager
    doc = DocumentManager.Instance.CurrentDBDocument
    TransactionManager.Instance.ForceCloseTransaction()
    IN_DYNAMO = True

LOG = []


def log(msg):
    LOG.append(msg)
    try:
        print(msg)
    except Exception:
        pass


# ----------------------------------------------------------------------------- data (mm)
DATA = __DATA__

FT = 304.8


def ft(v_mm):
    return float(v_mm) / FT


def pt(x, y, z=0.0):
    return XYZ(ft(x), ft(y), ft(z))


def ename(e):
    """Element / ElementType name that works in IronPython, CPython3 and PythonNet3."""
    for getter in (lambda: e.Name, lambda: Element.Name.GetValue(e), lambda: Element.Name.__get__(e)):
        try:
            n = getter()
            if n:
                return n
        except Exception:
            pass
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = e.get_Parameter(bip)
            if p and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return ""


def set_name(e, name):
    try:
        e.Name = name
        return True
    except Exception:
        try:
            Element.Name.SetValue(e, name)
            return True
        except Exception:
            return False


def eid(e):
    """Integer value of an ElementId across Revit versions (IntegerValue was removed in 2026)."""
    try:
        return e.Value
    except Exception:
        return e.IntegerValue


def collect(cls=None, cat=None, types_only=False):
    c = FilteredElementCollector(doc)
    if cat is not None:
        c = c.OfCategory(cat)
    if cls is not None:
        c = c.OfClass(cls)
    if types_only:
        c = c.WhereElementIsElementType()
    return list(c)


def set_param(e, bips=(), names=(), value=None):
    """Set the first writable parameter found (length values are in mm)."""
    cands = []
    for b in bips:
        try:
            p = e.get_Parameter(b)
            if p:
                cands.append(p)
        except Exception:
            pass
    for n in names:
        try:
            p = e.LookupParameter(n)
            if p:
                cands.append(p)
        except Exception:
            pass
    for p in cands:
        try:
            if p.IsReadOnly:
                continue
            st = p.StorageType
            if st == StorageType.Double:
                p.Set(ft(value))
            elif st == StorageType.String:
                p.Set(str(value) if not isinstance(value, str) else value)
            elif st == StorageType.Integer:
                p.Set(int(value))
            else:
                continue
            return True
        except Exception:
            continue
    return False


def failure_options(t):
    """Suppress warnings (e.g. 'room separation line overlaps') so transactions do not stop."""
    try:
        class WarningSwallower(IFailuresPreprocessor):
            __namespace__ = "AptBuilder"

            def PreprocessFailures(self, accessor):
                for f in accessor.GetFailureMessages():
                    if f.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(f)
                return FailureProcessingResult.Continue
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(WarningSwallower())
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass


def run_tx(name, fn):
    t = Transaction(doc, name)
    t.Start()
    failure_options(t)
    try:
        res = fn()
        t.Commit()
        return res
    except Exception as ex:
        log("ОШИБКА в '%s': %s" % (name, ex))
        try:
            t.RollBack()
        except Exception:
            pass
        return None


# ----------------------------------------------------------------------------- level
def get_level():
    levels = collect(Level)
    levels.sort(key=lambda l: abs(l.Elevation))
    if levels:
        lv = levels[0]
    else:
        lv = Level.Create(doc, 0.0)
    set_name(lv, DATA["level_name"])
    return lv


# ----------------------------------------------------------------------------- materials
def find_material(keywords):
    mats = collect(Material)
    for kw in keywords:
        for m in mats:
            if kw.lower() in ename(m).lower():
                return m.Id
    return ElementId.InvalidElementId


# ----------------------------------------------------------------------------- wall types
def get_wall_types():
    out = {}
    walltypes = collect(WallType)
    basic = [w for w in walltypes if w.Kind == WallKind.Basic]
    if not basic:
        raise Exception("В проекте нет базовых типов стен (Basic Wall)")
    for key, wt in DATA["wall_types"].items():
        name = "АР_" + wt["name"]
        found = [w for w in walltypes if ename(w) == name]
        if found:
            out[key] = found[0]
            continue
        nt = basic[0].Duplicate(name)
        mat = find_material(["Бетон", "Concrete", "Кирпич", "Masonry"] if wt["load_bearing"]
                            else ["Газобетон", "Гипс", "Gypsum", "Кирпич", "Masonry"])
        cs = CompoundStructure.CreateSingleLayerCompoundStructure(MaterialFunctionAssignment.Structure, ft(wt["t"]), mat)
        try:
            cs.EndCap = EndCapCondition.NoEndCap
        except Exception:
            pass
        nt.SetCompoundStructure(cs)
        set_param(nt, (BuiltInParameter.FUNCTION_PARAM,), (), 1 if wt.get("ext") else 0)
        set_param(nt, (BuiltInParameter.ALL_MODEL_DESCRIPTION,), (), wt["name"] + " (по project.json)")
        out[key] = nt
        log("Создан тип стены: %s (%d мм)" % (name, wt["t"]))
    return out


# ----------------------------------------------------------------------------- build steps
def build_walls(level, wtypes):
    walls = {}
    for w in DATA["walls"]:
        (ax, ay), (bx, by) = w["a"], w["b"]
        crv = Line.CreateBound(pt(ax, ay), pt(bx, by))
        wt = wtypes[w["type"]]
        structural = DATA["wall_types"][w["type"]]["load_bearing"]
        wall = Wall.Create(doc, crv, wt.Id, level.Id, ft(DATA["wall_h"]), 0.0, False, structural)
        set_param(wall, (BuiltInParameter.WALL_KEY_REF_PARAM,), (), 0)
        set_param(wall, (BuiltInParameter.ALL_MODEL_MARK,), (), w["id"])
        set_param(wall, (BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,), (), "Источник: " + w["src"])
        walls[w["id"]] = wall
    log("Стены: %d" % len(walls))
    return walls


def build_grids():
    n = 0
    existing = set(ename(g) for g in collect(Grid))
    for g in DATA["grids"]:
        if g["name"] in existing:
            continue
        (x0, y0), (x1, y1) = g["a"], g["b"]
        try:
            gr = Grid.Create(doc, Line.CreateBound(pt(x0, y0), pt(x1, y1)))
            if not set_name(gr, g["name"]):
                log("  ось %s: не удалось задать имя" % g["name"])
            n += 1
        except Exception as ex:
            log("  ось %s: %s" % (g["name"], ex))
    log("Оси: %d" % n)


def library_rfa(keywords, max_files=4000):
    """Look for a door/window family in the standard Revit content folders."""
    ver = doc.Application.VersionNumber
    roots = [r"C:\ProgramData\Autodesk\RVT %s\Libraries" % ver,
             r"C:\ProgramData\Autodesk\RVT %s\Family Templates" % ver]
    seen = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for d, _, files in os.walk(root):
            for fn in files:
                seen += 1
                if seen > max_files:
                    return None
                low = fn.lower()
                if low.endswith(".rfa") and any(k in low for k in keywords):
                    return os.path.join(d, fn)
    return None


def family_symbols(cat):
    return [s for s in collect(FamilySymbol, cat) if isinstance(s, FamilySymbol)]


def ensure_family(cat, keywords):
    syms = family_symbols(cat)
    if syms:
        return syms
    path = library_rfa(keywords)
    if path:
        try:
            doc.LoadFamily(path)
            log("Загружено семейство: %s" % path)
        except Exception as ex:
            log("Не удалось загрузить %s: %s" % (path, ex))
    return family_symbols(cat)


def find_kw(syms, prefer):
    for kw in prefer:
        for s in syms:
            full = (ename(s.Family) + " " + ename(s)).lower()
            if kw in full:
                return s
    return None


def pick_base(syms, prefer):
    return find_kw(syms, prefer) or (syms[0] if syms else None)


def make_type(base, type_name, w_mm, h_mm, mark, is_window):
    for s in family_symbols(BuiltInCategory.OST_Windows if is_window else BuiltInCategory.OST_Doors):
        if ename(s) == type_name and eid(s.Family.Id) == eid(base.Family.Id):
            return s
    s = base.Duplicate(type_name)
    wb = (BuiltInParameter.WINDOW_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM) if is_window else \
         (BuiltInParameter.DOOR_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM)
    hb = (BuiltInParameter.WINDOW_HEIGHT, BuiltInParameter.FAMILY_HEIGHT_PARAM) if is_window else \
         (BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.FAMILY_HEIGHT_PARAM)
    okw = set_param(s, wb, ("Ширина", "Width", "Ширина проема", "Ширина проёма"), w_mm)
    okh = set_param(s, hb, ("Высота", "Height", "Высота проема", "Высота проёма"), h_mm)
    set_param(s, (BuiltInParameter.ALL_MODEL_TYPE_MARK, BuiltInParameter.WINDOW_TYPE_ID), (), mark)
    set_param(s, (BuiltInParameter.ALL_MODEL_DESCRIPTION,), (), DATA["opening_types"][mark]["name"])
    if not (okw and okh):
        log("  внимание: у типа %s не удалось задать ширину/высоту (параметры семейства)" % type_name)
    return s


def wall_dir(w):
    return "V" if w["a"][0] == w["b"][0] else "H"


def build_openings(level, walls):
    doors = ensure_family(BuiltInCategory.OST_Doors, ("door", "двер"))
    wins = ensure_family(BuiltInCategory.OST_Windows, ("window", "окн", "окно"))
    if not doors:
        log("В проекте нет семейств дверей — двери не размещены (загрузите семейство и запустите снова)")
    if not wins:
        log("В проекте нет семейств окон — окна не размещены")
    base_door = pick_base(doors, ("одностворч", "single", "однопольн", "м_одн", "flush"))
    base_glass = find_kw(doors, ("балкон", "остекл", "glass", "glaz")) or base_door
    base_win = pick_base(wins, ("одностворч", "fixed", "casement", "окно", "window"))
    wall_by = dict((w["id"], w) for w in DATA["walls"])
    created = []
    types = {}
    for o in DATA["openings"]:
        is_win = o["kind"] == "window"
        base = base_win if is_win else (base_glass if o["kind"] == "balcony" else base_door)
        if base is None:
            continue
        tname = "%s %dx%d" % (o["mark"], o["w"], o["h"])
        if tname not in types:
            types[tname] = make_type(base, tname, o["w"], o["h"], o["mark"], is_win)
        sym = types[tname]
        if not sym.IsActive:
            sym.Activate()
            doc.Regenerate()
        w = wall_by[o["wall"]]
        if wall_dir(w) == "H":
            p = pt(o["c"], w["a"][1], 0.0)
        else:
            p = pt(w["a"][0], o["c"], 0.0)
        inst = doc.Create.NewFamilyInstance(p, sym, walls[o["wall"]], level, StructuralType.NonStructural)
        set_param(inst, (BuiltInParameter.ALL_MODEL_MARK,), (), o["id"])
        set_param(inst, (BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,), (), "Источник: " + o["src"])
        if is_win:
            set_param(inst, (BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM,), ("Высота нижнего бруса", "Sill Height"), o["sill"])
        created.append((o, inst))
    log("Двери/окна: %d" % len(created))
    return created


def plan_view(level):
    for v in collect(ViewPlan):
        try:
            if (not v.IsTemplate) and v.ViewType == ViewType.FloorPlan and v.GenLevel and eid(v.GenLevel.Id) == eid(level.Id):
                return v
        except Exception:
            pass
    vft = [t for t in collect(ViewFamilyType) if t.ViewFamily == ViewFamily.FloorPlan][0]
    return ViewPlan.Create(doc, vft.Id, level.Id)


def swing_arcs(inst, view):
    opt = Options()
    opt.View = view
    arcs = []
    geo = inst.get_Geometry(opt)
    if geo is None:
        return arcs
    for g in geo:
        if isinstance(g, GeometryInstance):
            for gg in g.GetInstanceGeometry():
                if isinstance(gg, Arc):
                    arcs.append(gg)
        elif isinstance(g, Arc):
            arcs.append(g)
    return arcs


def orient_doors(created, view):
    """Flip doors so that the swing arc lies on the required side and the hinge at the required end."""
    wall_by = dict((w["id"], w) for w in DATA["walls"])
    fixed = 0
    for o, inst in created:
        if o["kind"] == "window":
            continue
        w = wall_by[o["wall"]]
        vertical = wall_dir(w) == "V"
        sx, sy = o["swing"]
        cxy = (w["a"][0], o["c"]) if vertical else (o["c"], w["a"][1])
        for attempt in range(2):
            arcs = swing_arcs(inst, view)
            if arcs:
                arc = max(arcs, key=lambda a: a.Radius)
                mid = arc.Evaluate(0.5, True)
                ctr = arc.Center
                side = (mid.X - ft(cxy[0])) * sx + (mid.Y - ft(cxy[1])) * sy
                if side < 0 and inst.CanFlipFacing:
                    inst.flipFacing()
                    doc.Regenerate()
                    continue
                along_c = ctr.Y if vertical else ctr.X
                along_0 = ft(o["c"])
                want_min = o["hinge"] == "min"
                if (along_c < along_0) != want_min and inst.CanFlipHand:
                    inst.flipHand()
                    doc.Regenerate()
                fixed += 1
                break
            else:
                # fallback: standard Revit families swing away from FacingOrientation
                fo = inst.FacingOrientation
                if (-fo.X * sx - fo.Y * sy) < 0 and inst.CanFlipFacing:
                    inst.flipFacing()
                    doc.Regenerate()
                log("  %s: дуга открывания не найдена, ориентация по FacingOrientation — проверьте" % o["id"])
                break
    log("Двери сориентированы по модели: %d" % fixed)


def build_rooms(level, view):
    sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, level.Elevation)))
    ca = CurveArray()
    for (a, b) in DATA["separations"]:
        ca.Append(Line.CreateBound(pt(a[0], a[1], 0), pt(b[0], b[1], 0)))
    doc.Create.NewRoomBoundaryLines(sp, ca, view)
    doc.Regenerate()
    rooms = []
    for r in DATA["rooms"]:
        room = doc.Create.NewRoom(level, UV(ft(r["seed"][0]), ft(r["seed"][1])))
        set_param(room, (BuiltInParameter.ROOM_NAME,), (), r["name"])
        set_param(room, (BuiltInParameter.ROOM_NUMBER,), (), r["num"])
        rooms.append((r, room))
    doc.Regenerate()
    for r, room in rooms:
        area = room.Area * 0.09290304
        flag = "OK" if abs(area - r["area"]) < 0.05 else "ПРОВЕРИТЬ"
        log("  пом. %s %-20s %.2f м² (ожидалось %.2f) %s" % (r["num"], r["name"], area, r["area"], flag))
        try:
            doc.Create.NewRoomTag(LinkElementId(room.Id), UV(ft(r["seed"][0]), ft(r["seed"][1])), view.Id)
        except Exception:
            pass
    log("Помещения: %d" % len(rooms))
    return rooms


def tag_openings(created, view):
    n = 0
    for o, inst in created:
        try:
            loc = inst.Location.Point
            IndependentTag.Create(doc, view.Id, Reference(inst), False, TagMode.TM_ADDBY_CATEGORY,
                                  TagOrientation.Horizontal, loc)
            n += 1
        except Exception:
            pass
    log("Марки дверей/окон на плане: %d" % n)


def setup_plan(view):
    try:
        view.Scale = 50
        view.DetailLevel = ViewDetailLevel.Fine
        set_name(view, "АР_План этажа на отм. 0.000")
    except Exception:
        pass


def make_section(name, origin_mm, view_dir, up=(0, 0, 1), half_w=4000.0, depth=6000.0, z0=-500.0, z1=3800.0):
    vft = [t for t in collect(ViewFamilyType) if t.ViewFamily == ViewFamily.Section][0]
    tr = Transform.Identity
    vz = XYZ(-view_dir[0], -view_dir[1], 0)  # towards the viewer
    vy = XYZ(up[0], up[1], up[2])
    vx = vy.CrossProduct(vz)
    tr.Origin = pt(origin_mm[0], origin_mm[1], 0)
    tr.BasisX = vx
    tr.BasisY = vy
    tr.BasisZ = vz
    bb = BoundingBoxXYZ()
    bb.Transform = tr
    bb.Min = XYZ(-ft(half_w), ft(z0), -ft(depth))
    bb.Max = XYZ(ft(half_w), ft(z1), 0)
    sec = ViewSection.CreateSection(doc, vft.Id, bb)
    set_name(sec, name)
    try:
        sec.Scale = 50
        sec.DetailLevel = ViewDetailLevel.Fine
    except Exception:
        pass
    return sec


def make_schedule(cat, name, bips, count=False, sort_bip=None):
    vs = ViewSchedule.CreateSchedule(doc, ElementId(cat))
    set_name(vs, name)
    d = vs.Definition
    fields = d.GetSchedulableFields()
    added = {}
    for bip in bips:
        for f in fields:
            try:
                if eid(f.ParameterId) == eid(ElementId(bip)):
                    added[bip] = d.AddField(f)
                    break
            except Exception:
                pass
    if count:
        for f in fields:
            if f.FieldType == ScheduleFieldType.Count:
                d.AddField(f)
                break
    if sort_bip is not None and sort_bip in added:
        try:
            d.AddSortGroupField(ScheduleSortGroupField(added[sort_bip].FieldId))
        except Exception:
            pass
    return vs


def make_sheets(plan, secs, schedules):
    tbs = collect(FamilySymbol, BuiltInCategory.OST_TitleBlocks)
    if not tbs:
        log("Основная надпись (семейство штампа) не найдена — листы не созданы")
        return
    tb = tbs[0]
    sheets = [("АР-2", "План этажа. Экспликация помещений", [plan], [schedules[0]]),
              ("АР-3", "Разрезы 1-1, 2-2", secs, []),
              ("АР-4", "Спецификации заполнения проёмов", [], schedules[1:])]
    for num, title, views, scheds in sheets:
        sh = ViewSheet.Create(doc, tb.Id)
        sh.SheetNumber = num
        sh.Name = title
        doc.Regenerate()
        o = sh.Outline
        cx = (o.Min.U + o.Max.U) / 2.0
        cy = (o.Min.V + o.Max.V) / 2.0
        w = o.Max.U - o.Min.U
        h = o.Max.V - o.Min.V
        for i, v in enumerate(views):
            try:
                yy = cy + (h * 0.22 if len(views) > 1 and i == 0 else (-h * 0.18 if len(views) > 1 else 0.0))
                Viewport.Create(doc, sh.Id, v.Id, XYZ(cx - w * 0.12, yy, 0))
            except Exception as ex:
                log("  вид %s на лист %s: %s" % (ename(v), num, ex))
        for i, s in enumerate(scheds):
            try:
                ScheduleSheetInstance.Create(doc, sh.Id, s.Id, XYZ(o.Min.U + w * (0.68 if views else 0.05), o.Max.V - h * 0.08 - i * h * 0.35, 0))
            except Exception as ex:
                log("  спецификация на лист %s: %s" % (num, ex))
    log("Листы: %d" % len(sheets))


# ----------------------------------------------------------------------------- album sheets (ДП)
def _import_cad(path, view):
    """Import a flat DXF sheet into a view at the origin, mm, colours preserved. Handles the out-ElementId of
    Document.Import in IronPython (tuple), pythonnet 2 and PythonNet3 (clr.Reference)."""
    opts = DWGImportOptions()
    opts.Placement = ImportPlacement.Origin
    opts.Unit = ImportUnit.Millimeter
    opts.ThisViewOnly = True
    try:
        opts.ColorMode = ImportColorMode.Preserved
    except Exception:
        pass
    errors = []
    try:
        ref = clr.Reference[ElementId]()
        return doc.Import(path, opts, view, ref)
    except Exception as ex:
        errors.append(str(ex))
    try:
        return doc.Import(path, opts, view, ElementId.InvalidElementId)
    except Exception as ex:
        errors.append(str(ex))
    try:
        return doc.Import(path, opts, view)
    except Exception as ex:
        errors.append(str(ex))
    raise Exception("импорт %s: %s" % (os.path.basename(path), " | ".join(errors)))


def _place_image(sheet, path, x_mm, y_mm, w_mm):
    it = ImageType.Create(doc, ImageTypeOptions(path, False, ImageTypeSource.Import))
    po = ImagePlacementOptions(pt(x_mm, y_mm), BoxPlacement.BottomLeft)
    inst = ImageInstance.Create(doc, sheet, it.Id, po)
    try:
        inst.Width = ft(w_mm)
    except Exception:
        pass
    return inst


def build_album():
    al = DATA.get("album")
    if not al:
        return 0
    folder = al["dir"]
    if not os.path.isdir(folder):
        log("Папка альбома не найдена: %s — листы ДП не созданы (положите файлы туда же или поправьте путь)" % folder)
        return 0
    have = set()
    for v in collect(ViewSheet):
        try:
            have.add(v.SheetNumber)
        except Exception:
            pass
    n = 0
    for sh in al["sheets"]:
        num = "%s-%02d" % (al.get("prefix", "ДП"), sh["no"])
        if num in have:
            log("  лист %s уже есть — пропущен" % num)
            continue

        def one(sh=sh, num=num):
            vs = ViewSheet.Create(doc, ElementId.InvalidElementId)
            vs.SheetNumber = num
            vs.Name = sh["title"]
            _import_cad(os.path.join(folder, sh["dxf"]), vs)
            for im in sh.get("images", []):
                try:
                    _place_image(vs, os.path.join(folder, im["file"]), im["x"], im["y"], im["w"])
                except Exception as ex:
                    log("  изображение %s на листе %s: %s" % (im["file"], num, ex))
            return vs
        if run_tx("ДП: лист %s" % num, one) is not None:
            n += 1
    log("Альбом ДП: листов %d из %d" % (n, len(al["sheets"])))
    return n


def project_info():
    pi = doc.ProjectInformation
    set_param(pi, (BuiltInParameter.PROJECT_NAME,), (), DATA["project"]["object"])
    set_param(pi, (BuiltInParameter.PROJECT_NUMBER,), (), DATA["project"]["code"])


# ----------------------------------------------------------------------------- main
def main():
    log("АР: построение модели «%s» (Revit %s)" % (DATA["project"]["object"], doc.Application.VersionNumber))
    level = run_tx("АР: уровень", get_level)
    if level is None:
        return
    wtypes = run_tx("АР: типы стен", get_wall_types)
    walls = run_tx("АР: стены", lambda: build_walls(level, wtypes))
    run_tx("АР: оси", build_grids)
    run_tx("АР: сведения о проекте", project_info)
    view = run_tx("АР: план", lambda: plan_view(level))
    created = run_tx("АР: двери и окна", lambda: build_openings(level, walls)) or []
    if view is not None:
        run_tx("АР: план 1:50", lambda: setup_plan(view))
        run_tx("АР: ориентация дверей", lambda: orient_doors(created, view))
        run_tx("АР: помещения", lambda: build_rooms(level, view))
        run_tx("АР: марки", lambda: tag_openings(created, view))
    secs = []
    for sd in DATA.get("sections", []):
        sv = run_tx("АР: " + sd["name"], lambda sd=sd: make_section(sd["name"], tuple(sd["origin"]), tuple(sd["dir"]),
                                                                     half_w=sd["half_w"], depth=sd["depth"]))
        if sv is not None:
            secs.append(sv)
    sch = []
    sch.append(run_tx("АР: экспликация", lambda: make_schedule(BuiltInCategory.OST_Rooms, "АР_Экспликация помещений",
                      [BuiltInParameter.ROOM_NUMBER, BuiltInParameter.ROOM_NAME, BuiltInParameter.ROOM_AREA],
                      sort_bip=BuiltInParameter.ROOM_NUMBER)))
    sch.append(run_tx("АР: спецификация дверей", lambda: make_schedule(BuiltInCategory.OST_Doors, "АР_Спецификация дверей",
                      [BuiltInParameter.ALL_MODEL_TYPE_MARK, BuiltInParameter.ALL_MODEL_MARK, BuiltInParameter.DOOR_WIDTH,
                       BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.ALL_MODEL_DESCRIPTION], sort_bip=BuiltInParameter.ALL_MODEL_TYPE_MARK)))
    sch.append(run_tx("АР: спецификация окон", lambda: make_schedule(BuiltInCategory.OST_Windows, "АР_Спецификация окон",
                      [BuiltInParameter.ALL_MODEL_TYPE_MARK, BuiltInParameter.ALL_MODEL_MARK, BuiltInParameter.WINDOW_WIDTH,
                       BuiltInParameter.WINDOW_HEIGHT, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM], sort_bip=BuiltInParameter.ALL_MODEL_TYPE_MARK)))
    sch = [s for s in sch if s is not None]
    if view is not None and len(sch) == 3 and DATA.get("ar_sheets", True):
        run_tx("АР: листы", lambda: make_sheets(view, secs, sch))
    build_album()
    log("Готово.")


main()
OUT = "\n".join(LOG)
