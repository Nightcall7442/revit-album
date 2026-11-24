# -*- coding: utf-8 -*-
"""Marks of finishes, as on the reference album: a prefix by the material and a number within the prefix.

    walls    КР краска, ОБ обои, ОТ деревянные панели, З зеркало, ПЛ плитка / керамогранит, ДШ декоративная штукатурка,
             ФО фактурная отделка (кирпич, бетон, «лофт»)
    floors   НП паркет / доска / ламинат, ПЛ плитка / керамогранит, КВ ковролин, НС наливной пол
    ceiling  ПО
    others   П плинтус, К карниз, МЛ молдинг (drawn by their own sheets)

The mark is the id of the type in project.json: the engine gives it when it creates a type; types of older projects
(О1, П1, Т1 ...) are data and stay as they are.
"""
import re

WALL_PREFIX = (("З", r"зеркал|mirror"), ("ОБ", r"обо[ий]|wallpaper"), ("ОТ", r"дерев|шпон|панел|wood|veneer"),
               ("ПЛ", r"плит|керамогран|мозаик|tile|ceramic"), ("ДШ", r"штукатур|plaster"),
               ("ФО", r"кирпич|бетон|микроцемент|лофт|brick|concrete|loft"), ("КР", r"окраск|краск|paint"))
WALL_KIND = {"paint": "КР", "plaster": "ДШ", "brick": "ФО", "concrete": "ФО", "loft": "ФО", "wood": "ОТ", "tile": "ПЛ",
             "wallpaper": "ОБ", "mirror": "З"}
FLOOR_PREFIX = (("НП", r"паркет|доск|ламинат|инженерн|parquet|laminate|plank"), ("КВ", r"ковролин|ковёр|ковер|carpet"),
                ("НС", r"наливн|эпоксид|полимерн"), ("ПЛ", r"плит|керамогран|мрамор|камен|tile|stone"))
CEILING = "ПО"


def _prefix(rules, text, default):
    t = (text or "").lower()
    for p, rx in rules:
        if re.search(rx, t):
            return p
    return default


def wall_prefix(desc="", kind=None):
    if kind in WALL_KIND:
        return WALL_KIND[kind]
    return _prefix(WALL_PREFIX, desc, "КР")


def floor_prefix(material="", pattern=None):
    if pattern == "plank":
        return "НП"
    return _prefix(FLOOR_PREFIX, material, "ПЛ" if pattern in ("tile", "model", None) else "НП")


def next_id(existing, prefix):
    """«КР-1», «КР-2» ...: the next free number of the prefix among the ids (or dicts with «id») given."""
    ids = [e["id"] if isinstance(e, dict) else e for e in existing]
    n = 1
    while "%s-%d" % (prefix, n) in ids:
        n += 1
    return "%s-%d" % (prefix, n)


def wall_id(existing, desc="", kind=None):
    return next_id(existing, wall_prefix(desc, kind))


def floor_id(existing, material="", pattern=None):
    return next_id(existing, floor_prefix(material, pattern))


def ceiling_id(existing):
    return next_id(existing, CEILING)


def is_tile(t):
    """A wall finish type that is a tiled surface (by its mark or its description)."""
    tid = str(t.get("id", ""))
    return tid.startswith("ПЛ-") or t.get("kind") == "tile" or bool(re.search(r"плит|керамогран", (t.get("desc") or "").lower()))
