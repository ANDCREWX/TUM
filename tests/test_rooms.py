"""Tests für Raumcodes, Standorte und enge Übergänge."""

import sys
from dataclasses import replace
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, Slot  # noqa: E402
from tumcal.rooms import (  # noqa: E402
    building,
    campus,
    choose_rooms,
    parse_room_wish,
    transits,
)
from tumcal.semester import WS2627  # noqa: E402

GARCHING_MW = 'MW 0001, Hörsaal (5510.EG.001)'
GARCHING_MI = '00.04.011, MI Hörsaal 2 (5604.EG.011)'
GALILEO = 'Audimax im Galileo nur Mo-Di 7-19 Uhr (8120.01.101)'
STAMM_AUDIMAX = '0980, Audimax (0509.EG.980)'


def test_building_is_extracted_from_the_room_code():
    assert building(GARCHING_MW) == "5510"
    assert building(STAMM_AUDIMAX) == "0509"
    assert building("Online: Videokonferenz") == ""


def test_campus_mapping():
    assert campus("5510") == "Garching"
    assert campus("5604") == "Garching"
    assert campus("8120") == "Garching"        # Galileo, Walther-von-Dyck-Str.
    assert campus("0509") == "Stammgelände"    # Arcisstraße
    assert campus("9999") == ""                # nicht geraten


def _lv(titel, tag, von, bis, raum):
    return CourseOption(title=titel, kind="VO", room=raum,
                        slots=(Slot(day=tag, start=von, end=bis, room=raum),))


def test_back_to_back_in_the_same_building_is_fine():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.gap == 0
    assert t.verdict == "gleicher Raum"
    assert t.tight is False


def test_zero_gap_between_buildings_is_tight():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(10), time(12), GARCHING_MI)
    t = transits([a, b], WS2627)[0]
    assert t.verdict == "anderes Gebäude"
    assert t.needed == 10
    assert t.tight is True


def test_cross_campus_transition_is_flagged_hardest():
    """Garching → Innenstadt ist eine U-Bahn-Fahrt, kein Fußweg."""
    tag = date(2026, 10, 23)
    a = _lv("Rechnerarchitektur", tag, time(13), time(15), 'MW 1801 (5508.02.801)')
    b = _lv("Financial Accounting", tag, time(15), time(18, 15), STAMM_AUDIMAX)
    t = transits([a, b], WS2627)[0]
    assert t.campuses == ("Garching", "Stammgelände")
    assert t.verdict == "anderer Standort"
    assert t.needed == 40
    assert t.tight is True


def test_fifteen_minutes_between_buildings_on_one_campus_is_enough():
    tag = date(2026, 10, 20)
    a = _lv("A", tag, time(10), time(12), GALILEO)
    b = _lv("B", tag, time(12, 15), time(13, 45), 'Interims I (5620.01.101)')
    t = transits([a, b], WS2627)[0]
    assert t.gap == 15 and t.needed == 10
    assert t.tight is False


def test_long_gaps_are_not_reported():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(14), time(16), STAMM_AUDIMAX)
    assert transits([a, b], WS2627, max_gap=30) == []


def test_parallel_rooms_use_the_first_one():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), f"{GARCHING_MW} / {GALILEO}")
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.first_room == GARCHING_MW


def test_unknown_room_is_not_guessed():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), "Online: Videokonferenz")
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.verdict == "unbekannt"
    assert t.tight is False


# --- Raumwahl bei parallel gelisteten Räumen -------------------------------

INTERIMS = '101, Hörsaal 1, "Interims I" (5620.01.101)'
MW_2001 = 'MW 2001 Rudolf-Diesel-Hörsaal (5510.02.001)'
MW_0001 = 'MW 0001, Hörsaal (5510.EG.001)'


def _diskrete() -> CourseOption:
    """Zwei Schienen: Di mit MW 2001, Do mit MW 0001 als Übertragungsraum."""
    return CourseOption(
        title="Diskrete Strukturen",
        lv_id="0240967009",
        kind="VO",
        module="IN0015",
        slots=(
            Slot(date(2026, 10, 13), time(14, 15), time(15, 45), f"{INTERIMS} / {MW_2001}"),
            Slot(date(2026, 10, 15), time(10, 15), time(11, 45), f"{INTERIMS} / {MW_0001}"),
            Slot(date(2026, 10, 20), time(14, 15), time(15, 45), f"{INTERIMS} / {MW_2001}"),
        ),
    )


def test_room_wish_is_parsed():
    wish = parse_room_wish("IN0015=MW 2001")
    assert wish.selector == "IN0015"
    assert wish.pattern == "MW 2001"


def test_room_wish_without_equals_sign_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_room_wish("IN0015")


def test_wished_room_replaces_the_parallel_list():
    options, _ = choose_rooms([_diskrete()], [parse_room_wish("IN0015=MW 2001")])
    rooms = [slot.room for slot in options[0].slots]
    assert rooms[0] == MW_2001
    assert rooms[2] == MW_2001
    assert " / " not in rooms[0]


def test_same_building_is_the_fallback_where_the_wish_is_not_offered():
    options, report = choose_rooms([_diskrete()], [parse_room_wish("IN0015=MW 2001")])
    # Donnerstag bietet MW 2001 nicht an - MW 0001 liegt im selben Gebäude.
    assert options[0].slots[1].room == MW_0001
    assert any("Do" in line and "5510" in line for line in report)


def test_report_counts_the_dates_that_were_set():
    _, report = choose_rooms([_diskrete()], [parse_room_wish("IN0015=MW 2001")])
    assert report[0].startswith("Diskrete Strukturen")
    assert "2 von 3" in report[0]


def test_a_room_that_is_not_offered_leaves_the_entry_alone():
    option = _diskrete()
    options, report = choose_rooms([option], [parse_room_wish("IN0015=Audimax")])
    assert options[0].slots == option.slots
    assert "steht in keinem Termin" in report[0]


def test_matched_entries_without_the_room_stay_quiet():
    """Ein Modulcode trifft auch alle Übungsgruppen - die sind nicht gemeint."""
    uebung = CourseOption(
        title="Übungen zu Diskrete Strukturen", module="IN0015", kind="UE",
        group="02-10xx", slots=(
            Slot(date(2026, 10, 20), time(10, 15), time(11, 45),
                 "02.07.014, Seminarraum (5607.02.014)"),
        ),
    )
    options, report = choose_rooms(
        [_diskrete(), uebung], [parse_room_wish("IN0015=MW 2001")]
    )
    assert options[1].slots == uebung.slots          # unverändert
    assert all("Übungen" not in line for line in report)
    assert len(report) == 2                          # Treffer plus Do-Hinweis


def test_a_selector_that_matches_nothing_is_reported():
    _, report = choose_rooms([_diskrete()], [parse_room_wish("IN9999=MW 2001")])
    assert "keine Veranstaltung" in report[0]


def test_other_courses_stay_untouched():
    andere = CourseOption(
        title="Analysis für Informatik", module="MA0902", kind="VO",
        slots=(Slot(date(2026, 10, 13), time(8, 30), time(10, 0), MW_0001),),
    )
    options, _ = choose_rooms([andere], [parse_room_wish("IN0015=MW 2001")])
    assert options[0].slots[0].room == MW_0001


def test_room_choice_also_works_without_single_dates():
    serie = CourseOption(
        title="Diskrete Strukturen", module="IN0015", kind="VO",
        weekday=1, start_time=time(14, 15), end_time=time(15, 45),
        room=f"{INTERIMS} / {MW_2001}",
    )
    options, _ = choose_rooms([serie], [parse_room_wish("IN0015=MW 2001")])
    assert options[0].room == MW_2001


def test_the_chosen_room_drives_the_transit_estimate():
    """Vorher zählte der erste Raum (5620), jetzt der gewählte (5510)."""
    nachher = CourseOption(
        title="Analysis für Informatik", module="MA0902", kind="VO",
        slots=(Slot(date(2026, 10, 13), time(16, 0), time(17, 30), MW_0001),),
    )
    roh = transits([_diskrete(), nachher], WS2627, max_gap=30)
    assert roh and roh[0].verdict == "anderes Gebäude"

    gewaehlt, _ = choose_rooms([_diskrete()], [parse_room_wish("IN0015=MW 2001")])
    fein = transits(gewaehlt + [nachher], WS2627, max_gap=30)
    assert fein and fein[0].verdict == "gleiches Gebäude"


def test_the_header_room_follows_the_choice():
    """Sonst nennt der Eintrag einen Saal, in dem kein Termin mehr liegt."""
    option = replace(_diskrete(), room=f"{INTERIMS} / {MW_2001}")
    options, _ = choose_rooms([option], [parse_room_wish("IN0015=MW 2001")])
    assert options[0].room == MW_2001            # häufigster der neuen Slots
    assert INTERIMS not in options[0].room
