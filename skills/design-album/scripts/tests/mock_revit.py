# -*- coding: utf-8 -*-
"""Minimal behavioural mock of the Revit API to smoke-test revit_build_model.py outside Revit.

It checks Python-level correctness (names, data keys, control flow) and the door-orientation
logic (swing arcs react to flipFacing / flipHand exactly like a hosted door family would)."""
import sys
import types
import math
import itertools

_ids = itertools.count(1000)


class ElementId(object):
    InvalidElementId = None

    def __init__(self, v):
        if isinstance(v, (int,)):
            self.Value = v
        else:
            self.Value = abs(hash(str(v))) % 10 ** 9
        self.IntegerValue = self.Value

    def __eq__(self, o):
        return isinstance(o, ElementId) and o.Value == self.Value

    def __hash__(self):
        return self.Value


ElementId.InvalidElementId = ElementId(-1)


class _Enum(object):
    def __init__(self, name):
        self._name = name

    def __getattr__(self, item):
        return "%s.%s" % (self._name, item)


BuiltInParameter = _Enum("BIP")
BuiltInCategory = _Enum("BIC")


class StorageType(object):
    Double, String, Integer, ElementId = "D", "S", "I", "E"


class Parameter(object):
    def __init__(self, name):
        self.name = name
        self.IsReadOnly = False
        n = name.upper()
        if any(k in n for k in ("MARK", "NAME", "COMMENTS", "DESCRIPTION", "NUMBER", "TYPE_ID")):
            self.StorageType = StorageType.String
        elif any(k in n for k in ("FUNCTION", "KEY_REF")):
            self.StorageType = StorageType.Integer
        else:
            self.StorageType = StorageType.Double
        self.value = None

    def Set(self, v):
        self.value = v
        return True

    def AsString(self):
        return self.value if isinstance(self.value, str) else None


class XYZ(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = float(x), float(y), float(z)

    def CrossProduct(self, o):
        return XYZ(self.Y * o.Z - self.Z * o.Y, self.Z * o.X - self.X * o.Z, self.X * o.Y - self.Y * o.X)

    def __repr__(self):
        return "XYZ(%.3f,%.3f,%.3f)" % (self.X, self.Y, self.Z)


XYZ.BasisZ = XYZ(0, 0, 1)


class UV(object):
    def __init__(self, u, v):
        self.U, self.V = u, v


class Line(object):
    def __init__(self, a, b):
        self.a, self.b = a, b

    @staticmethod
    def CreateBound(a, b):
        return Line(a, b)


class Arc(object):
    def __init__(self, center, radius, mid):
        self.Center, self.Radius, self._mid = center, radius, mid

    def Evaluate(self, t, norm):
        return self._mid


class GeometryInstance(object):
    def __init__(self, items):
        self._items = items

    def GetInstanceGeometry(self):
        return list(self._items)


class Options(object):
    View = None


class Element(object):
    def __init__(self, doc=None, name=""):
        self.Id = ElementId(next(_ids))
        self.Name = name
        self._params = {}
        if doc is not None:
            doc.elements.append(self)

    def get_Parameter(self, bip):
        if bip not in self._params:
            self._params[bip] = Parameter(str(bip))
        return self._params[bip]

    def LookupParameter(self, name):
        return None


class ElementType(Element):
    pass


class Level(Element):
    Elevation = 0.0

    @staticmethod
    def Create(doc, elev):
        lv = Level(doc, "Level")
        lv.Elevation = elev
        return lv


class Material(Element):
    pass


class WallKind(object):
    Basic, Curtain, Stacked = "Basic", "Curtain", "Stacked"


class WallType(ElementType):
    Kind = WallKind.Basic

    def __init__(self, doc, name):
        Element.__init__(self, doc, name)
        self._doc = doc

    def Duplicate(self, name):
        if any(getattr(e, "Name", None) == name for e in self._doc.elements if isinstance(e, WallType)):
            raise Exception("duplicate name")
        return WallType(self._doc, name)

    def SetCompoundStructure(self, cs):
        self.cs = cs


class CompoundStructure(object):
    @staticmethod
    def CreateSingleLayerCompoundStructure(f, w, m):
        cs = CompoundStructure()
        cs.width = w
        return cs


class MaterialFunctionAssignment(object):
    Structure = "Structure"


class EndCapCondition(object):
    NoEndCap = "NoEndCap"


class Wall(Element):
    @staticmethod
    def Create(doc, crv, typeId, levelId, h, off, flip, struct):
        w = Wall(doc, "Wall")
        w.curve = crv
        w.height = h
        return w


class Grid(Element):
    @staticmethod
    def Create(doc, line):
        return Grid(doc, "")


class Family(Element):
    pass


class Category(object):
    def __init__(self, cat):
        self.Id = ElementId(cat)
        self.cat = cat


class FamilySymbol(ElementType):
    def __init__(self, doc, family, name, cat):
        Element.__init__(self, doc, name)
        self.Family = family
        self.Category = Category(cat)
        self._cat = cat
        self._doc = doc
        self.IsActive = False

    def Activate(self):
        self.IsActive = True

    def Duplicate(self, name):
        return FamilySymbol(self._doc, self.Family, name, self._cat)


class FamilyInstance(Element):
    def __init__(self, doc, p, sym, host):
        Element.__init__(self, doc, "inst")
        self.Symbol = sym
        self.Location = types.SimpleNamespace(Point=p)
        a, b = host.curve.a, host.curve.b
        L = math.hypot(b.X - a.X, b.Y - a.Y)
        self.wdir = ((b.X - a.X) / L, (b.Y - a.Y) / L)
        self.normal = (-self.wdir[1], self.wdir[0])  # left of the wall direction
        self.facing = 1   # swing towards +normal initially ("exterior")
        self.hand = 1     # hinge at +wdir end initially
        self.CanFlipFacing = True
        self.CanFlipHand = True
        self.width = 0.9 / 0.3048 * 1.0
        for k, v in sym._params.items():
            if "WIDTH" in str(k) and v.value:
                self.width = v.value

    @property
    def FacingOrientation(self):
        return XYZ(-self.normal[0] * self.facing, -self.normal[1] * self.facing, 0)

    def flipFacing(self):
        self.facing *= -1
        return True

    def flipHand(self):
        self.hand *= -1
        return True

    def get_Geometry(self, opt):
        if self.Symbol._cat == BuiltInCategory.OST_Windows:
            return []
        p = self.Location.Point
        w = self.width
        hx = p.X + self.wdir[0] * self.hand * w / 2.0
        hy = p.Y + self.wdir[1] * self.hand * w / 2.0
        # arc mid: 45° between closed leaf (towards the other jamb) and open leaf (towards swing side)
        cx = -self.wdir[0] * self.hand + self.normal[0] * self.facing
        cy = -self.wdir[1] * self.hand + self.normal[1] * self.facing
        n = math.hypot(cx, cy)
        mid = XYZ(hx + cx / n * w * 0.9, hy + cy / n * w * 0.9, 0)
        return [GeometryInstance([Arc(XYZ(hx, hy, 0), w * 0.9, mid), Line(p, p)])]


class StructuralType(object):
    NonStructural = "NonStructural"


class ViewType(object):
    FloorPlan = "FloorPlan"


class ViewFamily(object):
    FloorPlan, Section = "FloorPlan", "Section"


class ViewFamilyType(ElementType):
    def __init__(self, doc, fam):
        Element.__init__(self, doc, fam)
        self.ViewFamily = fam


class View(Element):
    IsTemplate = False
    Scale = 100
    DetailLevel = None


class ViewPlan(View):
    ViewType = ViewType.FloorPlan

    @staticmethod
    def Create(doc, vftId, levelId):
        v = ViewPlan(doc, "plan")
        v.GenLevel = [e for e in doc.elements if e.Id == levelId][0]
        return v


class ViewDetailLevel(object):
    Fine = "Fine"


class SketchPlane(object):
    @staticmethod
    def Create(doc, plane):
        return SketchPlane()


class Plane(object):
    @staticmethod
    def CreateByNormalAndOrigin(n, o):
        return Plane()


class CurveArray(list):
    def Append(self, c):
        self.append(c)


class Room(Element):
    Area = 0.0


class LinkElementId(object):
    def __init__(self, i):
        self.i = i


class Reference(object):
    def __init__(self, e):
        self.e = e


class TagMode(object):
    TM_ADDBY_CATEGORY = "cat"


class TagOrientation(object):
    Horizontal = "H"


class IndependentTag(object):
    @staticmethod
    def Create(*a):
        return IndependentTag()


class Transform(object):
    @classmethod
    def _identity(cls):
        t = Transform()
        t.Origin, t.BasisX, t.BasisY, t.BasisZ = XYZ(), XYZ(1, 0, 0), XYZ(0, 1, 0), XYZ(0, 0, 1)
        return t


class _TransformMeta(type):
    pass


Transform.Identity = property(lambda self: Transform._identity())
Transform.Identity = Transform._identity()


class BoundingBoxXYZ(object):
    pass


class ViewSection(View):
    @staticmethod
    def CreateSection(doc, vftId, bb):
        assert abs(bb.Transform.BasisX.CrossProduct(bb.Transform.BasisY).X - bb.Transform.BasisZ.X) < 1e-9
        assert abs(bb.Transform.BasisX.CrossProduct(bb.Transform.BasisY).Y - bb.Transform.BasisZ.Y) < 1e-9
        return ViewSection(doc, "section")


class ScheduleFieldType(object):
    Instance, Count = "Instance", "Count"


class _Field(object):
    def __init__(self, pid, ft="Instance"):
        self.ParameterId = pid
        self.FieldType = ft
        self.FieldId = next(_ids)


class _Def(object):
    def __init__(self):
        self.fields = []

    def GetSchedulableFields(self):
        bips = ["ROOM_NUMBER", "ROOM_NAME", "ROOM_AREA", "ALL_MODEL_TYPE_MARK", "ALL_MODEL_MARK", "DOOR_WIDTH",
                "DOOR_HEIGHT", "ALL_MODEL_DESCRIPTION", "WINDOW_WIDTH", "WINDOW_HEIGHT", "INSTANCE_SILL_HEIGHT_PARAM"]
        return [_Field(ElementId("BIP." + b)) for b in bips] + [_Field(ElementId(-2), "Count")]

    def AddField(self, f):
        self.fields.append(f)
        return f

    def AddSortGroupField(self, f):
        pass


class ScheduleSortGroupField(object):
    def __init__(self, fid):
        self.fid = fid


class ViewSchedule(View):
    @staticmethod
    def CreateSchedule(doc, catId):
        v = ViewSchedule(doc, "schedule")
        v.Definition = _Def()
        return v


class ViewSheet(View):
    @staticmethod
    def Create(doc, tbId):
        s = ViewSheet(doc, "sheet")
        s.Outline = types.SimpleNamespace(Min=UV(0, 0), Max=UV(1.38, 0.97))
        s.imports, s.images = [], []
        return s


class ImportPlacement(object):
    Origin = "Origin"


class ImportUnit(object):
    Millimeter = "Millimeter"


class ImportColorMode(object):
    Preserved = "Preserved"


class DWGImportOptions(object):
    pass


class ImageTypeSource(object):
    Import = "Import"


class ImageTypeOptions(object):
    def __init__(self, path, rel, src):
        import os as _os
        assert _os.path.isfile(path), "image not found: %s" % path
        self.path = path


class ImageType(Element):
    @staticmethod
    def Create(doc, opts):
        return ImageType(doc, opts.path)


class BoxPlacement(object):
    BottomLeft = "BottomLeft"


class ImagePlacementOptions(object):
    def __init__(self, p, box):
        self.p = p


class ImageInstance(Element):
    @staticmethod
    def Create(doc, view, tid, po):
        i = ImageInstance(doc, "image")
        view.images.append(i)
        return i


class Viewport(object):
    @staticmethod
    def Create(doc, sid, vid, p):
        return Viewport()


class ScheduleSheetInstance(object):
    @staticmethod
    def Create(doc, sid, vid, p):
        return ScheduleSheetInstance()


class IFailuresPreprocessor(object):
    pass


class FailureSeverity(object):
    Warning = "W"


class FailureProcessingResult(object):
    Continue = "C"


class Transaction(object):
    def __init__(self, doc, name):
        self.name = name

    def Start(self):
        pass

    def Commit(self):
        pass

    def RollBack(self):
        pass

    def GetFailureHandlingOptions(self):
        return types.SimpleNamespace(SetFailuresPreprocessor=lambda p: None)

    def SetFailureHandlingOptions(self, o):
        pass


class FilteredElementCollector(object):
    def __init__(self, doc):
        self.doc = doc
        self.items = list(doc.elements)

    def OfClass(self, cls):
        self.items = [e for e in self.items if isinstance(e, cls)]
        return self

    def OfCategory(self, cat):
        self.items = [e for e in self.items if getattr(e, "_cat", None) == cat]
        return self

    def WhereElementIsElementType(self):
        self.items = [e for e in self.items if isinstance(e, ElementType)]
        return self

    def __iter__(self):
        return iter(self.items)


class _Create(object):
    def __init__(self, doc):
        self.doc = doc

    def NewFamilyInstance(self, p, sym, host, level, st):
        assert sym.IsActive, "symbol not active"
        return FamilyInstance(self.doc, p, sym, host)

    def NewRoomBoundaryLines(self, sp, ca, view):
        self.doc.separations = list(ca)

    ROOMS = []          # [(shapely polygon in mm, area m2)] set by the test from project.json

    def NewRoom(self, level, uv):
        r = Room(self.doc, "room")
        from shapely.geometry import Point
        p = Point(uv.U * 304.8, uv.V * 304.8)
        for poly, area in _Create.ROOMS:
            if poly.contains(p):
                r.Area = area / 0.09290304
        return r

    def NewRoomTag(self, *a):
        return object()


class Document(object):
    def __init__(self):
        self.elements = []
        self.Create = _Create(self)
        self.Application = types.SimpleNamespace(VersionNumber="2027")
        self.ProjectInformation = Element(None, "pi")
        lv = Level(self, "Уровень 1")
        WallType(self, "Типовой - 200мм")
        fam_d = Family(self, "М_Однопольные-Щитовые")
        FamilySymbol(self, fam_d, "0915 x 2134 мм", BuiltInCategory.OST_Doors)
        fam_w = Family(self, "М_Окно-Одностворчатое")
        FamilySymbol(self, fam_w, "0915 x 1220 мм", BuiltInCategory.OST_Windows)
        fam_t = Family(self, "Штамп А3")
        FamilySymbol(self, fam_t, "А3", BuiltInCategory.OST_TitleBlocks)
        ViewFamilyType(self, ViewFamily.FloorPlan)
        ViewFamilyType(self, ViewFamily.Section)
        v = ViewPlan(self, "Уровень 1")
        v.GenLevel = lv

    def Regenerate(self):
        pass

    def LoadFamily(self, p):
        return True

    def Import(self, path, opts, view, out=None):
        import os as _os
        assert _os.path.isfile(path), "cad not found: %s" % path
        assert opts.Unit == "Millimeter" and opts.Placement == "Origin"
        view.imports.append(path)
        return True


def install():
    clr = types.ModuleType("clr")
    clr.AddReference = lambda *a: None
    sys.modules["clr"] = clr
    db = types.ModuleType("Autodesk.Revit.DB")
    for k, v in list(globals().items()):
        if not k.startswith("_") and k not in ("sys", "types", "math", "itertools", "install"):
            setattr(db, k, v)
    db.__all__ = [k for k in dir(db) if not k.startswith("_")]
    st = types.ModuleType("Autodesk.Revit.DB.Structure")
    st.StructuralType = StructuralType
    ar = types.ModuleType("Autodesk.Revit.DB.Architecture")
    ar.Room = Room
    sys.modules["Autodesk"] = types.ModuleType("Autodesk")
    sys.modules["Autodesk.Revit"] = types.ModuleType("Autodesk.Revit")
    sys.modules["Autodesk.Revit.DB"] = db
    sys.modules["Autodesk.Revit.DB.Structure"] = st
    sys.modules["Autodesk.Revit.DB.Architecture"] = ar


