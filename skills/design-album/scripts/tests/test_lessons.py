# -*- coding: utf-8 -*-
"""Experience base: every lesson in references/lessons.md must name a guard that really exists
(a QA / data rule code in the engine or a test function). A lesson without a working guard is not learnt."""
import os
import re

from conftest import SKILL, SCRIPTS

LESSONS = os.path.join(SKILL, "references", "lessons.md")


def _lessons():
    text = open(LESSONS, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"^## (L-\d{3})[^\n]*\n(.*?)(?=^## L-|\Z)", text, re.S | re.M):
        g = re.search(r"Страж:\s*(.+)", m.group(2))
        out.append((m.group(1), [s.strip() for s in g.group(1).split(",")] if g else []))
    return out


def _engine_text():
    t = ""
    for fn in os.listdir(os.path.join(SCRIPTS, "sdalbum")):
        if fn.endswith(".py"):
            t += open(os.path.join(SCRIPTS, "sdalbum", fn), encoding="utf-8").read()
    return t


def test_lessons_exist():
    ls = _lessons()
    assert len(ls) >= 10
    ids = [i for i, _ in ls]
    assert len(ids) == len(set(ids)), "duplicate lesson id"


def test_every_lesson_has_a_live_guard():
    engine = _engine_text()
    tests = ""
    for fn in os.listdir(os.path.dirname(__file__)):
        if fn.endswith(".py"):
            tests += open(os.path.join(os.path.dirname(__file__), fn), encoding="utf-8").read()
    for lid, guards in _lessons():
        assert guards, "%s: no guard" % lid
        for g in guards:
            kind, _, name = g.partition(":")
            if kind in ("qa", "data", "build"):
                assert '"%s"' % name in engine, "%s: rule %s not found in the engine" % (lid, name)
            elif kind == "test":
                fn = name.split("::")[-1]
                assert re.search(r"def %s\(" % re.escape(fn), tests), "%s: test %s not found" % (lid, fn)
            else:
                raise AssertionError("%s: unknown guard kind %r" % (lid, g))
