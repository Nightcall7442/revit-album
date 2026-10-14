# -*- coding: utf-8 -*-
"""Album DXF -> an editable DXF and a DWG for the studio's draftsman (L-098).

    python3 sda.py dwg OUT/album.dxf            -> OUT/album_edit.dxf, OUT/album.dwg

* Sheet drawings live in model space as blocks SD_NN_k (one per viewport). For editing they are exploded: walls,
  dimensions, texts, hatches become ordinary model-space entities right under the sheet viewports, so the draftsman
  fixes a dimension or moves a wall without BEDIT / REFEDIT.
* DWG is written by LibreDWG `dxf2dwg` (R2000). Its writer keeps a few low handles for itself, so every DXF handle
  is shifted above them first; layout names are kept to the R2000 code page (cp1251) and short. The DWG is read
  back with `dwgread` - a file that does not read back cleanly is not delivered (the DXF always is).
"""
import os
import re
import shutil
import subprocess
import tempfile

import ezdxf

HANDLE_CODES = {5, 105, 330, 340, 350, 360, 390, 1005} | set(range(320, 370)) | set(range(480, 482))
HANDLE_SHIFT = 0x2000
NAME_MAX = 31
_REPL = {"—": "-", "–": "-", "Ø": "D", "ø": "d", "×": "x", "²": "2", "³": "3", "°": " град", "±": "+-",
         "…": "...", "«": '"', "»": '"', "№": "N"}


def _tool(name):
    env = os.environ.get("SDA_" + name.upper())
    for p in (env, shutil.which(name), "/usr/local/bin/" + name, "/home/claude/build/libredwg/build/" + name):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def available():
    return _tool("dxf2dwg") is not None


def layout_name(name, used):
    """A layout name safe for DWG R2000: cp1251 characters only, <= 31 characters, cut at a word, unique."""
    s = "".join(_REPL.get(ch, ch) for ch in name)
    s = "".join(ch if _cp1251(ch) else "_" for ch in s)
    s = re.sub(r"[<>/\\\":;?*|=`,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > NAME_MAX:
        cut = s[:NAME_MAX]
        sp = cut.rfind(" ")
        s = (cut[:sp] if sp > 8 else cut).rstrip(" -")
    base, k = s, 2
    while s.lower() in used:
        s = "%s %d" % (base[:NAME_MAX - 3], k)
        k += 1
    used.add(s.lower())
    return s


def _cp1251(ch):
    try:
        ch.encode("cp1251")
        return True
    except UnicodeEncodeError:
        return False


def editable_dxf(src_path, dst_path, dwg_names=False):
    """Explode the sheet blocks in model space; optional DWG-safe layout names. Returns {old: new} renames."""
    doc = ezdxf.readfile(src_path)
    msp = doc.modelspace()
    for ins in list(msp.query("INSERT")):
        try:
            ins.explode()
        except Exception:
            pass                                   # a block that cannot be exploded stays a block
    if "VIEWPORTS" not in doc.layers:
        doc.layers.add("VIEWPORTS", color=7)
    for v in doc.query("VIEWPORT"):
        if v.dxf.layer not in doc.layers:
            v.dxf.layer = "VIEWPORTS"
    sheets = [n for n in doc.layouts.names_in_taborder() if n != "Model"]
    for n in list(sheets):                         # ezdxf's empty default tab - not a sheet of the album
        if n.lower().startswith("layout") and not len(doc.layouts.get(n)) and len(sheets) > 1:
            doc.layouts.delete(n)
            sheets.remove(n)
    ren = {}
    if dwg_names:
        used = {"model"}
        for name in [n for n in doc.layouts.names_in_taborder() if n != "Model"]:
            new = layout_name(name, used)
            if new != name:
                doc.layouts.rename(name, new)
                ren[name] = new
    doc.saveas(dst_path)
    return ren


def shift_handles(src, dst, off=HANDLE_SHIFT):
    """Shift every handle of an ASCII DXF by `off` (group codes of handles and pointers)."""
    with open(src, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out = []
    i = 0
    while i < len(lines) - 1:
        c, v = lines[i], lines[i + 1]
        try:
            code = int(c.strip())
        except ValueError:
            out += [c, v]
            i += 2
            continue
        vs = v.strip()
        if code in HANDLE_CODES and vs and vs != "0":
            try:
                v = "%X" % (int(vs, 16) + off)
            except ValueError:
                pass
        out += [c, v]
        i += 2
    out += lines[i:]
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def to_dwg(dxf_path, dwg_path, timeout=900):
    """album.dxf -> album.dwg. Returns (path or None, note)."""
    conv = _tool("dxf2dwg")
    if not conv:
        return None, "конвертер DWG (LibreDWG dxf2dwg) не найден - отдан DXF, AutoCAD открывает его напрямую"
    tmp = tempfile.mkdtemp(prefix="sda_dwg_")
    try:
        ed = os.path.join(tmp, "a.dxf")
        editable_dxf(dxf_path, ed, dwg_names=True)
        sh = os.path.join(tmp, "b.dxf")
        shift_handles(ed, sh)
        env = dict(os.environ)
        lib = os.path.dirname(conv)
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        out = os.path.join(tmp, "c.dwg")
        r = subprocess.run([conv, "-y", "-o", out, sh], capture_output=True, text=True, timeout=timeout, env=env)
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or not os.path.isfile(out) or "ERROR" in log:
            err = [l for l in log.splitlines() if "ERROR" in l][:3]
            return None, "DWG не записан (%s) - отдан DXF" % ("; ".join(err) or "код %d" % r.returncode)
        rd = _tool("dwgread")
        if rd:
            r2 = subprocess.run([rd, out], capture_output=True, text=True, timeout=timeout, env=env)
            txt = (r2.stdout or "") + (r2.stderr or "")
            if r2.returncode != 0 or "ERROR" in txt:
                return None, "DWG не прочитался обратно - отдан DXF"
        shutil.move(out, dwg_path)
        return dwg_path, "DWG R2000 (LibreDWG); листы - вкладки, чертежи в модели расчленены"
    except subprocess.TimeoutExpired:
        return None, "DWG: конвертер не уложился во время - отдан DXF"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def images_of(dxf_path):
    """File names of the raster images (IMAGEDEF) a DXF references - they travel with the DWG."""
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        return []
    out = []
    for d in doc.objects.query("IMAGEDEF"):
        fn = d.dxf.get("filename")
        if fn and fn not in out:
            out.append(fn)
    return out


def pack(out_dir, files, zip_path):
    """album.dwg + album_edit.dxf + the images they show (relative names): one archive for the draftsman."""
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            p = f if os.path.isabs(f) else os.path.join(out_dir, f)
            if os.path.isfile(p):
                z.write(p, os.path.basename(p) if os.path.isabs(f) else f)
    return zip_path


def export(dxf_path, out_dir=None):
    """Write album_edit.dxf (exploded, original names), album.dwg and album_dwg.zip (both + images) next to
    album.dxf. Returns dict."""
    out_dir = out_dir or os.path.dirname(os.path.abspath(dxf_path))
    ed = os.path.join(out_dir, "album_edit.dxf")
    editable_dxf(dxf_path, ed)
    dwg, note = to_dwg(dxf_path, os.path.join(out_dir, "album.dwg"))
    imgs = images_of(ed)
    z = pack(out_dir, ([os.path.basename(dwg)] if dwg else []) + [os.path.basename(ed)] + imgs,
             os.path.join(out_dir, "album_dwg.zip"))
    return dict(dxf_edit=ed, dwg=dwg, zip=z, images=len(imgs), note=note)
