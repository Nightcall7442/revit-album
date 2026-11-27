"""Section «3. Визуализации» (reference album): «Визуализации пом. №N Name», up to four renders on a sheet.

meta.renders: a list of image paths (relative to the project) or of {"file": ..., "room": "<room name>"}; or
meta.renders_dir: a folder whose images are taken in name order, the room recognised by its name in the file name."""
import os
from collections import OrderedDict

from PIL import Image

from . import gfx as S

EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
PER_SHEET = 4


def _abs(P, p):
    return p if os.path.isabs(p) else os.path.join(P.base_dir or ".", p)


def _room_of_name(P, fn):
    low = os.path.basename(fn).lower()
    best = None
    for r in P.rooms:
        n = r["name"].lower()
        if n and n in low and (best is None or len(n) > len(best["name"])):
            best = r
    return best["name"] if best else None


def renders(P):
    """[(room name | None, absolute path)] of the existing images."""
    m = P.meta or {}
    out = []
    for r in m.get("renders") or []:
        f, room = (r.get("file"), r.get("room")) if isinstance(r, dict) else (r, None)
        if f and os.path.isfile(_abs(P, f)):
            out.append((room or _room_of_name(P, f), _abs(P, f)))
    d = m.get("renders_dir")
    if d and os.path.isdir(_abs(P, d)):
        for fn in sorted(os.listdir(_abs(P, d))):
            if fn.lower().endswith(EXT):
                p = os.path.join(_abs(P, d), fn)
                if p not in [q for _, q in out]:
                    out.append((_room_of_name(P, fn), p))
    return out


def sheets(A):
    """[(title, scale, fn, arg)]: a room after a room, up to PER_SHEET images a sheet."""
    P = A.P
    by = OrderedDict()
    for room, p in renders(P):
        by.setdefault(room, []).append(p)
    out = []
    for room, files in by.items():
        r = P.room_by_name.get(room) if room else None
        base = "Визуализации пом. №%s %s" % (r["num"], r["name"]) if r else ("Визуализации %s" % room if room else
                                                                           "Визуализации")
        parts = [files[i:i + PER_SHEET] for i in range(0, len(files), PER_SHEET)]
        for i, part in enumerate(parts):
            t = base + (" (%d)" % (i + 1) if len(parts) > 1 else "")
            out.append((t, "б/м", visual_sheet, dict(files=part)))
    return out


def visual_sheet(A, no, title, scale, arg):
    psp = A.make_sheet(no, title, None, None, header=False, kind="B")
    files = arg["files"]
    x0, y0, x1, y1 = 26.0, 26.0, 410.0, 284.0
    n = len(files)
    cols = 1 if n == 1 else 2
    rows = 1 if n <= 2 else 2
    gap = 6.0
    cw = (x1 - x0 - gap * (cols - 1)) / cols
    ch = (y1 - y0 - gap * (rows - 1)) / rows
    for i, f in enumerate(files):
        c, r = i % cols, i // cols
        bx, by = x0 + c * (cw + gap), y1 - (r + 1) * ch - r * gap
        iw, ih = Image.open(f).size
        s_ = min(cw / iw, ch / ih)
        w, h = iw * s_, ih * s_
        name = "vis_%02d_%d%s" % (no, i, os.path.splitext(f)[1].lower())
        img = psp.add_image(A.image(name, f), insert=(bx + (cw - w) / 2.0, by + (ch - h) / 2.0), size_in_units=(w, h),
                            dxfattribs={"layer": "SD_Мебель"})
        img.rgb = (254, 254, 254)
