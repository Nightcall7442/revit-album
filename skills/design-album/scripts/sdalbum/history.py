# -*- coding: utf-8 -*-
"""Edit journal of project.json: every change by fix / propose / edit is saved with a snapshot of the previous
state, so any step can be undone and the list of changes can be shown to the client.

    <project dir>/.sda_history/<stem>/0001.json   state BEFORE change 1
    <project dir>/.sda_history/<stem>/log.jsonl   one line per change: n, time, msg, ops
"""
import json
import os
import shutil
import time


def _dir(path):
    base = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(base, ".sda_history", stem)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def dump(data, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def entries(path):
    lp = os.path.join(_dir(path), "log.jsonl")
    if not os.path.isfile(lp):
        return []
    out = []
    with open(lp, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def save(path, data, msg, ops=None):
    """Write data to path; the previous file content becomes snapshot N (undo restores it)."""
    d = _dir(path)
    os.makedirs(d, exist_ok=True)
    ent = entries(path)
    n = (ent[-1]["n"] + 1) if ent else 1
    if os.path.isfile(path):
        shutil.copy(path, os.path.join(d, "%04d.json" % n))
    else:
        with open(os.path.join(d, "%04d.json" % n), "w", encoding="utf-8") as fh:
            fh.write("null")
    dump(data, path)
    with open(os.path.join(d, "log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(n=n, time=time.strftime("%Y-%m-%d %H:%M"), msg=msg, ops=ops or []), ensure_ascii=False) + "\n")
    return n


def undo(path, steps=1):
    """Restore the state before the last `steps` changes. Returns the undone entries."""
    d = _dir(path)
    ent = entries(path)
    if not ent:
        return []
    steps = min(steps, len(ent))
    undone = ent[-steps:]
    snap = os.path.join(d, "%04d.json" % undone[0]["n"])
    with open(snap, encoding="utf-8") as fh:
        content = fh.read()
    if content.strip() == "null":
        os.remove(path)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    for e in undone:
        p = os.path.join(d, "%04d.json" % e["n"])
        if os.path.isfile(p):
            os.remove(p)
    with open(os.path.join(d, "log.jsonl"), "w", encoding="utf-8") as fh:
        for e in ent[:-steps]:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return undone


def snapshot_before(path, n):
    """Content of project.json before change n (for diff 'what changed since change n')."""
    p = os.path.join(_dir(path), "%04d.json" % n)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        c = fh.read()
    return None if c.strip() == "null" else json.loads(c)
