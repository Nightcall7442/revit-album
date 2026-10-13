# -*- coding: utf-8 -*-
"""Russian typography of every text on the sheets (applied in gfx.text / gfx.mtext, checked by QA rule TYPO).

  dash         «граница - фасад» -> «граница — фасад» (non-breaking space before the dash)
  ranges       «0,02-0,03», «15-25 мм» -> en dash «0,02–0,03»; standards (ГОСТ 30674-99, СанПиН ...-20) and
               formulas (4-16-4, 6-16Ar) are not ranges
  quotes       "..." -> «...»; «...» ellipsis -> «…»
  spaces       no double spaces, none before , . ; : ! ? ) and after ( «
  units        «м2» -> «м²»; a number and its unit are not split by a line break (200 мм, 16 А, 80 л)
  short words  one / two-letter prepositions and conjunctions do not hang at the end of a line (в, с, к, на, по...)
  empty cell   «-» -> «—»
"""
import re

NBSP = " "
_CYR = re.compile(r"[А-Яа-яЁё]")
_UNITS = r"(?:мм|см|м²|м³|м|кВт|Вт|кг|л|лк|мА|А|В|шт\.|°C|°)"
_SHORT = (r"(?:[вВсСкКоОуУиИаАяЯ]|на|На|по|По|до|До|от|От|за|За|из|Из|не|Не|но|Но|об|Об|со|Со|ко|Ко|во|Во|"
          r"без|Без|для|Для|при|При|под|Под|над|Над)")
_RANGE = re.compile(r"(?<![\w.,/\-–])(?<!ГОСТ )(?<!ГОСТ Р )(?<!СП )(?<!ТУ )(?<!СНиП )(?<!СанПиН )"
                    r"(\d+(?:,\d+)?)-(\d+(?:,\d+)?)(?![\w.,/\-–])")


def fix(s):
    if not isinstance(s, str) or not s:
        return s
    if s.strip() == "-":
        return s.replace("-", "—")
    if not _CYR.search(s):
        return s                          # numbers, marks, codes, Latin names: as they are
    t = s.replace("...", "…")
    t = re.sub(r'"([^"]+)"', "«\\1»", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"(?<=\S) - (?=\S)", NBSP + "— ", t)
    t = re.sub(r"(?<=\S) — ", NBSP + "— ", t)
    t = _RANGE.sub("\\1–\\2", t)
    t = re.sub(r" +([,.;:!?)»])", "\\1", t)
    t = re.sub(r"([(«]) +", "\\1", t)
    t = re.sub(r"(?<=[\d\s])м2(?![\w²])", "м²", t)
    t = re.sub(r"(?<=[\d\s])м3(?![\w³])", "м³", t)
    t = re.sub(r"(\d) (?=" + _UNITS + r"(?![А-Яа-яЁёA-Za-z]))", "\\1" + NBSP, t)
    t = t.replace("№ ", "№" + NBSP)
    t = re.sub(r"(?<![А-Яа-яЁёA-Za-z0-9\-–])(" + _SHORT + r") (?=\S)", "\\1" + NBSP, t)
    return t


def issues(s):
    """Typography faults left in a text as rendered (QA): [(code, message)]."""
    out = []
    if not isinstance(s, str) or not s.strip():
        return out
    t = s.replace(NBSP, " ")
    if not _CYR.search(t):
        return out
    if re.search(r"\S - \S", t):
        out.append(("TYPO_DASH", "дефис вместо тире"))
    if '"' in t:
        out.append(("TYPO_QUOTES", "прямые кавычки вместо «ёлочек»"))
    if re.search(r"\s[,.;:!?](?!\d)", t):
        out.append(("TYPO_SPACES", "пробел перед знаком препинания"))
    if re.search(r"(?<=[\d\s])м[23](?!\w)", t):
        out.append(("TYPO_UNITS", "м2 / м3 вместо м² / м³"))
    if "..." in t:
        out.append(("TYPO_ELLIPSIS", "три точки вместо многоточия"))
    for w in re.findall(r"[A-Za-zА-Яа-яЁё]+", t):
        if re.search(r"[A-Za-z]", w) and _CYR.search(w):
            out.append(("TYPO_MIXED", "латиница и кириллица в одном слове «%s»" % w))
    if _RANGE.search(t):
        out.append(("TYPO_RANGE", "диапазон через дефис вместо «–»"))
    return out
