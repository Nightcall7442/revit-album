# -*- coding: utf-8 -*-
"""Web home of the design-album agent (Railway): upload a source -> the album.

    GET  /                 page: upload form, jobs, downloads (HTTP Basic auth, password = ACCESS_TOKEN)
    POST /jobs             file(s): .max / .dxf / .dwg / .pdf / photo / project.json / .zip of a folder -> job
    GET  /jobs/{id}        status (JSON); /jobs/{id}/files/{name} - album.pdf, album.dwg, album_edit.dxf, album.dxf, report.md, project.json, log
    GET  /plugin           the Claude plugin built from this deployment (space-design-album-<version>.plugin)
    GET  /health           liveness

Jobs run one at a time (a 3ds Max scene takes up to ~8 GB of memory), results stay on the volume DATA_DIR.
"""
import base64
import html
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "design-album", "scripts")
DATA = os.environ.get("DATA_DIR", "/data")
JOBS = os.path.join(DATA, "jobs")
TOKEN = os.environ.get("ACCESS_TOKEN", "")
os.makedirs(JOBS, exist_ok=True)

app = FastAPI(title="Space Design Album")
_queue = []
_lock = threading.Lock()
_running = {"id": None}


def _version():
    try:
        return json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))["version"]
    except Exception:
        return "?"


@app.middleware("http")
async def auth(request: Request, call_next):
    if request.url.path == "/health" or not TOKEN:
        return await call_next(request)
    h = request.headers.get("authorization", "")
    ok = False
    if h.lower().startswith("basic "):
        try:
            _, pw = base64.b64decode(h[6:]).decode("utf-8").split(":", 1)
            ok = secrets.compare_digest(pw, TOKEN)
        except Exception:
            ok = False
    if not ok:
        return Response("auth", status_code=401, headers={"WWW-Authenticate": 'Basic realm="space-design-album"'})
    return await call_next(request)


def _job_dir(jid):
    if not jid or any(c not in "0123456789abcdef-" for c in jid):
        raise HTTPException(404)
    d = os.path.join(JOBS, jid)
    if not os.path.isdir(d):
        raise HTTPException(404)
    return d


def _meta(jid):
    p = os.path.join(JOBS, jid, "job.json")
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def _save_meta(jid, m):
    json.dump(m, open(os.path.join(JOBS, jid, "job.json"), "w", encoding="utf-8"), ensure_ascii=False)


def _worker():
    while True:
        jid = None
        with _lock:
            if _queue and _running["id"] is None:
                jid = _queue.pop(0)
                _running["id"] = jid
        if jid is None:
            time.sleep(1.0)
            continue
        d = os.path.join(JOBS, jid)
        m = _meta(jid)
        m.update(status="running", started=time.time())
        _save_meta(jid, m)
        src = os.path.join(d, "src")
        out = os.path.join(d, "out")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(d, "log.txt"), "w", encoding="utf-8") as log:
            rc = subprocess.call([sys.executable, "sda.py", "make", src, out], cwd=SCRIPTS, stdout=log,
                                 stderr=subprocess.STDOUT)
        m = _meta(jid)
        rep = {}
        try:
            rep = json.load(open(os.path.join(out, "report.json"), encoding="utf-8"))
        except Exception:
            pass
        m.update(status="done" if os.path.isfile(os.path.join(out, "album.pdf")) else "failed",
                 finished=time.time(), rc=rc, errors=rep.get("errors"), warnings=rep.get("warnings"),
                 sheets=len(rep.get("sheets") or []), result=rep.get("status"))
        _save_meta(jid, m)
        with _lock:
            _running["id"] = None


threading.Thread(target=_worker, daemon=True).start()


@app.on_event("startup")
def _resume():
    for jid in sorted(os.listdir(JOBS)):            # jobs cut by a restart go back to the queue
        m = _meta(jid)
        if m.get("status") in ("queued", "running"):
            m["status"] = "queued"
            _save_meta(jid, m)
            _queue.append(jid)


@app.get("/health")
def health():
    return {"ok": True, "version": _version()}


@app.post("/jobs")
async def create_job(request: Request, files: list[UploadFile] = File(...)):
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    src = os.path.join(JOBS, jid, "src")
    os.makedirs(src, exist_ok=True)
    names = []
    for f in files:
        name = os.path.basename(f.filename or "file")
        dst = os.path.join(src, name)
        with open(dst, "wb") as fh:
            shutil.copyfileobj(f.file, fh, 1 << 20)
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(dst) as z:
                for zi in z.infolist():
                    p = os.path.normpath(zi.filename)
                    if p.startswith("..") or os.path.isabs(p):
                        continue
                    z.extract(zi, src)
            os.remove(dst)
        names.append(name)
    _save_meta(jid, dict(id=jid, files=names, status="queued", created=time.time()))
    with _lock:
        _queue.append(jid)
    if "text/html" in request.headers.get("accept", ""):       # the upload form of the page: back to the job list
        return RedirectResponse("/", status_code=303)
    return JSONResponse({"id": jid, "status": "queued"})


@app.get("/jobs/{jid}")
def job(jid: str):
    _job_dir(jid)
    return _meta(jid)


@app.get("/jobs/{jid}/files/{name}")
def job_file(jid: str, name: str):
    d = _job_dir(jid)
    allowed = {"album.pdf": "out", "album.dxf": "out", "album.dwg": "out", "album_edit.dxf": "out", "album_dwg.zip": "out",
               "report.md": "out", "report.json": "out", "project.json": "out",
               "qa.json": "out", "log.txt": ""}
    if name not in allowed:
        raise HTTPException(404)
    p = os.path.join(d, allowed[name], name)
    if not os.path.isfile(p):
        raise HTTPException(404)
    return FileResponse(p, filename="%s_%s" % (jid, name))


@app.get("/plugin")
def plugin():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", ".pytest_cache", "server")]
            for fn in files:
                if fn.endswith(".pyc") or fn in ("Dockerfile", "railway.toml", ".dockerignore"):
                    continue
                p = os.path.join(base, fn)
                z.write(p, os.path.relpath(p, ROOT))
    buf.seek(0)
    name = "space-design-album-%s.plugin" % _version()
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@app.get("/", response_class=HTMLResponse)
def index():
    rows = []
    for jid in sorted(os.listdir(JOBS), reverse=True)[:50]:
        m = _meta(jid)
        st = m.get("status", "?")
        ru = {"queued": "в очереди", "running": "собирается…", "done": "готово", "failed": "ошибка"}.get(st, st)
        links = ""
        if st == "done":
            links = " ".join('<a href="/jobs/%s/files/%s">%s</a>' % (jid, n, t) for n, t in
                             (("album.pdf", "PDF"), ("album_dwg.zip", "DWG (архив)"), ("album_edit.dxf", "DXF"), ("report.md", "отчёт"),
                              ("project.json", "project.json")) if os.path.isfile(os.path.join(_job_dir(jid), "out", n)))
        links += ' <a href="/jobs/%s/files/log.txt">лог</a>' % jid
        info = ""
        if m.get("sheets"):
            info = "листов %s, ошибок %s, предупреждений %s" % (m.get("sheets"), m.get("errors"), m.get("warnings"))
            if m.get("result") == "audit_errors":
                info += "; <b>не сверен со сценой 3ds Max - см. отчёт</b>"
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(jid), html.escape(", ".join(m.get("files", []))), ru, info, links))
    busy = "сейчас собирается: %s" % _running["id"] if _running["id"] else "свободен"
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Space Design Album</title><style>
:root{--bg:#f6f4f0;--fg:#1d1b18;--mut:#6f6a62;--acc:#a8844f;--line:#ddd6cb}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--fg:#ece8e1;--mut:#a39d93;--acc:#c9a26b;--line:#3a3631}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 Inter,system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:980px;margin:0 auto}h1{font-weight:600;margin:0 0 4px}h1 b{color:var(--acc)}p{color:var(--mut)}
form{border:1px solid var(--line);border-radius:10px;padding:16px;margin:20px 0}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:9px 16px;font-weight:600;cursor:pointer}
table{width:100%%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:8px 6px;text-align:left;vertical-align:top}
a{color:var(--acc)}</style></head><body><main>
<h1><b>Space</b> Design Album · агент %s</h1>
<p>Загрузите сцену 3ds Max (.max), чертёж DWG/DXF, PDF, фото обмера, project.json или .zip папки — агент соберёт альбом дизайн-проекта. Сборка кафе ≈ 10 минут, страница обновляется сама. %s.</p>
<form action="/jobs" method="post" enctype="multipart/form-data" onsubmit="this.querySelector('button').textContent='Загрузка…'">
<input type="file" name="files" multiple required> <button>Собрать альбом</button></form>
<p><a href="/plugin">Скачать плагин для Claude (space-design-album-%s.plugin)</a></p>
<table><tr><th>Задание</th><th>Исходник</th><th>Статус</th><th>Итог</th><th>Файлы</th></tr>%s</table>
<script>setTimeout(()=>{if(document.body.innerHTML.includes('собирается')||document.body.innerHTML.includes('в очереди'))location.reload()},15000)</script>
</main></body></html>""" % (_version(), busy, _version(), "".join(rows) or "<tr><td colspan=5>заданий пока нет</td></tr>")
