# -*- coding: utf-8 -*-
"""Edits in plain terms (selectors), journal with undo, diff between versions (sdalbum/editor.py, history.py)."""
import copy
import json
import os
import shutil

import pytest

from conftest import STUDIO, URGENCH


def _P(d, base):
    from sdalbum import model
    return model.Project(d, base)


@pytest.fixture
def urg():
    return json.load(open(URGENCH, encoding="utf-8"))


def test_select_by_computed_room_and_word_stem(urg):
    from sdalbum import editor
    P = _P(urg, os.path.dirname(URGENCH))
    sec, items = editor.select(urg, "sockets[room=Спальня,note~кровать]", P)
    assert sec == "sockets" and len(items) == 2
    sec, items = editor.select(urg, "switches[id=В7]", P)
    assert len(items) == 1 and items[0][1]["x"] == 3420
    sec, items = editor.select(urg, "sockets[near=10600:780]", P)
    assert len(items) == 1 and items[0][1]["kind"] in ("Р32", "Р")
    sec, items = editor.select(urg, "sockets[h>2000]", P)
    assert all(it["h"] > 2000 for _, it in items) and items


def test_set_move_del_add(urg):
    from sdalbum import editor
    base = os.path.dirname(URGENCH)
    d2, msgs = editor.apply(urg, ["set sockets[room=Спальня,note~кровать] h=700",
                                  "move switches[id=В5] 0 -300",
                                  "del sockets[note~торшер]",
                                  'add sockets {"kind": "Р", "x": 3820, "y": 3000, "h": 300, "wall": "X+", "group": "4"}'], base)
    assert [s["h"] for s in d2["sockets"] if s.get("note") == "у кровати"] == [700, 700]
    assert next(s for s in d2["switches"] if s["id"] == "В5")["y"] == 3750
    assert not [s for s in d2["sockets"] if s.get("note") == "торшер"]
    assert d2["sockets"][-1]["y"] == 3000
    assert urg["sockets"][0]["h"] == 600                 # the input is not mutated
    assert len(msgs) == 5


def test_opening_moves_along_its_wall(urg):
    from sdalbum import editor
    d2, _ = editor.apply(urg, ["move openings[id=Д-3.2] 100 0"], os.path.dirname(URGENCH))
    o0 = next(o for o in urg["openings"] if o["id"] == "Д-3.2")
    o1 = next(o for o in d2["openings"] if o["id"] == "Д-3.2")
    assert o1["c"] == o0["c"] + 100


def test_rename_room_updates_every_reference(urg):
    from sdalbum import editor, validate
    base = os.path.dirname(URGENCH)
    d2, msgs = editor.apply(urg, ["rename-room Спальня \"Спальня родителей\""], base)
    s = json.dumps(d2, ensure_ascii=False)
    assert '"Спальня"' not in s
    P = _P(d2, base)
    assert "Спальня родителей" in P.room_by_name
    codes = {i["code"] for i in validate.run(P)}
    assert not codes & {"SWITCH_GROUP_MISSING", "FURN_NO_ROOM", "FLOOR_UNCOVERED"}


def test_bad_selector_is_explained(urg):
    from sdalbum import editor
    with pytest.raises(editor.EditError) as e:
        editor.apply(urg, ["set sockets[room=Кладовая] h=700"], os.path.dirname(URGENCH))
    assert "ничего не найдено" in str(e.value)


def test_journal_and_undo(tmp_path):
    from sdalbum import history
    p = str(tmp_path / "project.json")
    shutil.copy(STUDIO, p)
    orig = open(p, encoding="utf-8").read()
    d = history.load(p)
    d["levels"]["ceiling"] = 2600
    history.save(p, d, "потолок 2600")
    d["levels"]["ceiling"] = 2500
    history.save(p, d, "потолок 2500")
    assert [e["msg"] for e in history.entries(p)] == ["потолок 2600", "потолок 2500"]
    history.undo(p)
    assert history.load(p)["levels"]["ceiling"] == 2600
    history.undo(p)
    assert open(p, encoding="utf-8").read() == orig and history.entries(p) == []


def test_diff_in_words(urg):
    from sdalbum import editor
    base = os.path.dirname(URGENCH)
    d2, _ = editor.apply(urg, ["set sockets[room=Спальня,note~кровать] h=700", "move switches[id=В5] 0 -300",
                               "del furniture[name=Ковёр,room=Гостиная]", "set meta place=\"Ургенч\""], base)
    ch, sheets = editor.diff(urg, d2, base)
    txt = "\n".join(t for _, t in ch)
    assert txt.count("h 600 -> 700") == 2
    assert "(3420; 4050) -> (3420; 3750)" in txt
    assert "удалено: Ковёр" in txt
    assert "place:" in txt
    assert "розетки" in sheets and "освещение" in sheets


def test_cli_edit_reports_new_problem(tmp_path, capsys):
    import sda
    p = str(tmp_path / "project.json")
    shutil.copy(STUDIO, p)
    sda.cmd_edit([p, "move sockets#1 300 0"])
    out = capsys.readouterr().out
    assert "новое замечание [SOCKET_NOT_ON_WALL]" in out
    sda.cmd_undo([p])
    assert history_len(p) == 0


def history_len(p):
    from sdalbum import history
    return len(history.entries(p))


def test_diff_reports_a_rename_once(urg):
    from sdalbum import editor
    base = os.path.dirname(URGENCH)
    d2, _ = editor.apply(urg, ['rename-room Спальня "Спальня родителей"'], base)
    ch, sheets = editor.diff(urg, d2, base)
    assert ch == [("rooms", "переименовано: «Спальня» -> «Спальня родителей» (все ссылки)")]
