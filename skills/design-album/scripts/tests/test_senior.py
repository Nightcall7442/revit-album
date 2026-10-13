# -*- coding: utf-8 -*-
"""Senior decisions (sdalbum/senior.py) and the public-building proposal (propose.py) on a small cafe:
rooms by purpose, the bar behind its counter, ceilings and lights from the model, evacuation door, catering
equipment, service room, staff switches, sockets in the counter, ЩР, elevations of the WC - and no questions."""
import copy

import pytest


def _cafe():
    W = lambda i, r, **kw: dict(id=i, kind=kw.pop("kind", "existing"), rect=r, **kw)
    walls = [W("W1", [-300, -300, 12300, 0]), W("W2", [-300, 0, 0, 9000]), W("W3", [12000, 0, 12300, 9000]),
             W("ВТ1", [-300, 9000, 12300, 9100], note="витраж"),
             W("W4", [0, 3000, 4000, 3200]), W("W5", [4000, 0, 4200, 3200]),
             W("W6", [6000, 0, 6100, 2600], kind="new"), W("W7", [4200, 2500, 6000, 2600], kind="new")]
    ops = [dict(id="ОК.В1а", kind="window", wall="ВТ1", c=3000, w=5600, h=2840, sill=0, note="витраж", evidence="модель"),
           dict(id="Д.В1", kind="door", wall="ВТ1", c=6500, w=900, h=2200, entrance=True, evidence="модель"),
           dict(id="ОК.В1б", kind="window", wall="ВТ1", c=9600, w=4600, h=2840, sill=0, note="витраж", evidence="модель"),
           dict(id="Д.D1", kind="door", wall="W4", c=600, w=900, h=2100, note="дверь по модели: Glass_Door_1", evidence="модель"),
           dict(id="Д.D2", kind="door", wall="W7", c=4700, w=800, h=2100, note="дверь по модели: Glass_Door_2", evidence="модель"),
           dict(id="ОК.W1", kind="window", wall="W1", c=5100, w=800, h=400, sill=1200, evidence="модель")]
    rect = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    furn = [dict(name="Барная стойка (холодильные столы под столешницей ×2)", kind="counter", h=1200, check=True,
                 poly=[[1000, 4400], [1000, 5200], [4500, 5200], [4500, 3200], [3700, 3200], [3700, 4400]],
                 front=[[[1000, 5200], [4500, 5200]], [[4500, 3200], [4500, 5200]]]),
            dict(name="Унитаз подвесной (инсталляция)", kind="wc", hung=True, check=True, poly=rect(5000, 0, 5350, 550)),
            dict(name="Раковина", kind="basin", check=True, poly=rect(5500, 2000, 5950, 2450))]
    for i, (x, y) in enumerate(((7000, 6000), (9000, 6000), (7000, 3500), (9000, 3500))):
        furn.append(dict(name="Стол", kind="table", check=True, poly=rect(x, y, x + 800, y + 800)))
        furn.append(dict(name="Стул", kind="chair", check=True, poly=rect(x - 450, y + 150, x - 50, y + 650)))
        furn.append(dict(name="Стул", kind="chair", check=True, poly=rect(x + 850, y + 150, x + 1250, y + 650)))
    lights = [dict(kind="line", name="track", rect=[8000, 4000, 8030, 7000], z0=2400, z1=2420),
              dict(kind="point", name="spot on track", rect=[7985, 5000, 8045, 5060], z0=2200, z1=2405),
              dict(kind="point", name="down", rect=[10000, 5000, 10068, 5068], z0=2760, z1=3000),
              dict(kind="point", name="down2", rect=[2000, 1500, 2068, 1568], z0=2760, z1=3000),
              dict(kind="point", name="pendant", rect=[2500, 6000, 2600, 6100], z0=2300, z1=2580),
              dict(kind="point", name="wc spot", rect=[5000, 1200, 5068, 1268], z0=2400, z1=2650),
              dict(kind="point", name="hidden", rect=[5500, 1200, 5568, 1268], z0=2760, z1=3000)]
    return dict(meta=dict(object="Дизайн-проект интерьера кафе «Тест»", title="ДИЗАЙН-ПРОЕКТ|ИНТЕРЬЕРА КАФЕ"),
                levels=dict(floor=0, ceiling=2900, slab=3000, source="модель"), walls=walls, openings=ops, rooms=[],
                furniture=furn, lighting=[], switches=[], sockets=[], plumbing=[], floors=[], elevations=[], nodes=[],
                ceilings=dict(types=[], zones=[]),
                _lights=lights, _ceil_planes=[[[4200, 0, 6000, 2500], 2560]], _beams=[[[6000, 6000, 6400, 9000], 2600]],
                _equipment=[dict(kind="coffee", title="Кофемашина", name="Victor", rect=[3800, 3700, 4400, 4300], z0=1100, z1=1550),
                            dict(kind="pos", title="POS-терминал (касса)", name="POS", rect=[2000, 4800, 2400, 5100], z0=1100, z1=1440)],
                _curtains=[[300, 8800, 2800, 8950]])


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    from sdalbum import autofix, propose, senior
    base = str(tmp_path_factory.mktemp("cafe"))
    d, flog, rest, qs = autofix.fix(_cafe(), base)
    d, slog = senior.decide(d, base)
    d, flog2, rest, qs = autofix.fix(d, base)
    d, plog = propose.propose(d, base)
    d, flog3, rest, qs = autofix.fix(d, base)
    return dict(d=d, slog=slog, plog=plog, rest=rest, qs=qs, base=base)


def _P(made):
    from sdalbum import model
    return model.Project(made["d"], made["base"])


def test_rooms_by_purpose_and_the_bar_behind_its_counter(made):
    P = _P(made)
    cls = {r["name"]: r.get("cls") for r in P.rooms}
    assert cls.get("Обеденный зал") == "public" and cls.get("Бар") == "bar"
    assert cls.get("Подсобное помещение") == "storage" and cls.get("Санузел") == "wet"
    assert made["d"]["separations"]
    counter = next(f for f in made["d"]["furniture"] if f["kind"] == "counter")
    assert counter["room"] == "Бар"


def test_no_questions_only_decisions(made):
    assert not [q for q in made["qs"] if "назначение не определено" in q or "названы по тому" in q or "по умолчанию" in q]
    topics = {e["topic"] for e in made["slog"]}
    assert {"Зонирование", "Назначение помещений", "Потолки", "Освещение", "Вход", "Горячая вода"} <= topics
    assert all(e.get("msg") for e in made["slog"])
    assert made["d"]["meta"]["decisions"]


def test_data_has_no_errors(made):
    errs = [i for i in made["rest"] if i["level"] == "error"]
    assert not errs, errs


def test_ceilings_from_the_model(made):
    P = _P(made)
    hall = P.room_by_name["Обеденный зал"]
    wc = P.room_by_name["Санузел"]
    types = {t["id"]: t for t in made["d"]["ceilings"]["types"]}
    assert types[hall["ceiling_type"]]["level"] == 3000 and "открытый" in types[hall["ceiling_type"]]["short"]
    assert wc["ceiling_level"] == 2560
    kinds = {z["kind"] for z in made["d"]["ceilings"]["zones"]}
    assert {"beam", "rail"} <= kinds


def test_lights_from_the_model(made):
    by = {}
    for f in made["d"]["lighting"]:
        by.setdefault(f["kind"], []).append(f["group"])
    assert by["track"] == ["Обеденный зал"] and by["track_spot"] == ["Обеденный зал"]
    assert "Обеденный зал" in by["surface"] and "Подсобное помещение" in by["surface"]
    assert by["pendant"] and by["spot_ip44"] == ["Санузел"]
    assert sum(len(v) for v in by.values()) == 6                   # the one above the WC ceiling is not built


def test_entrance_door_opens_outward(made):
    from sdalbum import topo as T
    P = _P(made)
    o = next(x for x in P.openings if x["kind"] == "door" and T.is_entrance(P, x))
    assert list(o["swing"]) == [0, 1]
    t = made["d"]["opening_types"][o["mark"]]
    assert "алюминиевый" in t["name"] and t["style"] == "glass"


def test_shop_front_and_wc_window_types(made):
    ts = made["d"]["opening_types"]
    front = [t for t in ts.values() if t.get("system") == "storefront"]
    assert front and all(t["transom"] == 2200 and len(t["division"]) >= 4 for t in front)
    small = [t for t in ts.values() if t.get("sash") == ["tilt"]]
    assert small and "матовое" in small[0]["glazing"]


def test_catering_equipment_and_service_room(made):
    from shapely.geometry import Polygon
    from sdalbum.symbols import door_swing_area
    d = made["d"]
    P = _P(made)
    kinds = {(f["kind"], f.get("room")) for f in d["furniture"]}
    assert ("coffee", "Бар") in kinds and ("pos", "Бар") in kinds and ("basin", "Бар") in kinds
    serv = [f for f in d["furniture"] if f.get("room") == "Подсобное помещение"]
    assert {"sink", "heater", "cabinet", "wardrobe"} <= {f["kind"] for f in serv}
    swings = [door_swing_area(P, o) for o in P.openings if o["kind"] == "door" and o.get("swing")]
    for f in serv:
        if f["kind"] == "heater":
            continue
        g = Polygon(f["poly"])
        assert not any(g.intersects(s) for s in swings), f["name"]


def test_staff_switches_in_the_bar(made):
    sw = made["d"]["switches"]
    hall_ctl = [s for s in sw if any(c["group"] == "Обеденный зал" for c in s["controls"])]
    assert hall_ctl and all(s["room"] == "Бар" for s in hall_ctl)


def test_bar_sockets_in_the_counter_and_panel_in_the_service_room(made):
    d = made["d"]
    cof = [s for s in d["sockets"] if s["kind"] == "Р32"]
    assert cof and cof[0].get("mount") == "furniture"
    assert sum(1 for s in d["sockets"] if "холодильный стол" in s.get("note", "")) == 2
    assert d["panel"]["name"] == "ЩР"
    from sdalbum import model
    P = _P(made)
    assert P.room_of_point((d["panel"]["x"], d["panel"]["y"]), 60)["name"] == "Подсобное помещение"
    txt = " ".join(r[3] for r in d["circuits"])
    assert "Кофемашина" in txt and "Аварийное освещение" in txt and "Водонагреватель" in txt


def test_wc_outlets_under_a_high_window(made):
    wc = [o for o in made["d"]["plumbing"] if "Унитаз" in o["fixture"]]
    assert {o["kind"] for o in wc} == {"ХВС", "К110"}
    assert next(o for o in wc if o["kind"] == "ХВС")["h"] == 1000      # low frame: sill 1200 - 200


def test_wc_elevations_only_where_fixtures_stand(made):
    from sdalbum.sheets_details import Elev
    P = _P(made)
    el = [e for e in made["d"]["elevations"] if e["room"] == "Санузел"]
    assert el and all(e["base"] == "tile" for e in el)
    with_wc = [e for e in el if any(fx["name"] == "унитаз" for fx in e.get("fixtures", []))]
    assert len(with_wc) == 1                       # the back wall, not the side walls meeting it at the corner
    assert any("инсталляции" in (it.get("label") or "") for it in with_wc[0]["items"])


def test_public_floors(made):
    mats = {f["material"] for f in made["d"]["floors"]}
    assert any("R11" in m for m in mats) and any("600×1200" in m for m in mats)
